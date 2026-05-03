"""
MAHMOUD_WHALE.py
═════════════════════════════════════════════════
Whale Alert integration:
  • تتبع التحويلات الكبيرة (>$1M)
  • مراقبة دخول/خروج الـExchanges
  • تنبيهات للمشتركين
═════════════════════════════════════════════════
"""

import os
import logging
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

import MAHMOUD_DB as db


WHALE_ALERT_KEY = os.environ.get("WHALE_ALERT_KEY", "")
MIN_WHALE_USD = float(os.environ.get("MIN_WHALE_USD", "1000000"))


def is_available() -> bool:
    return bool(WHALE_ALERT_KEY)


# ─────────────────────────────────────────────
# Fetch from Whale Alert API
# ─────────────────────────────────────────────

def fetch_whale_transactions(min_usd: float = None,
                             cursor: Optional[str] = None) -> Dict:
    """
    يجلب التحويلات الأخيرة من Whale Alert.
    https://api.whale-alert.io/v1/transactions
    """
    if not WHALE_ALERT_KEY:
        return {"ok": False, "error": "no_key", "transactions": []}

    min_usd = min_usd or MIN_WHALE_USD
    # Whale Alert: max 1 hour lookback for free tier
    start_time = int((datetime.utcnow() - timedelta(minutes=15)).timestamp())

    params = {
        "api_key": WHALE_ALERT_KEY,
        "min_value": int(min_usd),
        "start": start_time,
        "limit": 100,
    }
    if cursor:
        params["cursor"] = cursor

    try:
        r = requests.get("https://api.whale-alert.io/v1/transactions",
                         params=params, timeout=15)
        if r.status_code != 200:
            logging.warning(f"Whale Alert HTTP {r.status_code}: {r.text[:200]}")
            return {"ok": False, "error": f"http_{r.status_code}",
                    "transactions": []}
        data = r.json()
        return {
            "ok": data.get("result") == "success",
            "transactions": data.get("transactions", []),
            "cursor": data.get("cursor"),
            "count": data.get("count", 0),
        }
    except Exception as e:
        logging.error(f"Whale Alert error: {e}")
        return {"ok": False, "error": str(e)[:120], "transactions": []}


def store_new_whales(transactions: List[Dict]) -> int:
    """يخزن التحويلات الجديدة فقط"""
    new_count = 0
    for tx in transactions:
        tx_hash = tx.get("hash", "")
        if not tx_hash or db.whale_seen(tx_hash):
            continue
        symbol = (tx.get("symbol") or "").upper()
        amount = float(tx.get("amount", 0))
        amount_usd = float(tx.get("amount_usd", 0))
        from_owner = tx.get("from", {}).get("owner") or \
                     tx.get("from", {}).get("owner_type") or "unknown"
        to_owner = tx.get("to", {}).get("owner") or \
                   tx.get("to", {}).get("owner_type") or "unknown"
        timestamp = tx.get("timestamp", 0)

        wid = db.insert_whale(tx_hash, amount, amount_usd, symbol,
                               from_owner, to_owner, timestamp)
        if wid > 0:
            new_count += 1
    return new_count


# ─────────────────────────────────────────────
# Display
# ─────────────────────────────────────────────

def _esc_md(s: str) -> str:
    """يهرب رموز Markdown الخاصة"""
    if not s:
        return ""
    s = str(s)
    for ch in ("_", "*", "[", "]", "`"):
        s = s.replace(ch, "\\" + ch)
    return s


def fmt_whale(w: Dict) -> str:
    symbol = _esc_md(w.get("symbol", ""))
    amount_usd = w.get("amount_usd", 0)
    amount = w.get("amount", 0)
    from_owner = _esc_md(w.get("from_owner", "?"))
    to_owner = _esc_md(w.get("to_owner", "?"))
    ts = w.get("timestamp", 0)

    # Direction logic
    arrow = "→"
    if w.get("from_owner") == "exchange" and w.get("to_owner") != "exchange":
        flow_emoji = "📤"  # exchange outflow (bullish)
        flow_label = "خروج من Exchange"
    elif w.get("from_owner") != "exchange" and w.get("to_owner") == "exchange":
        flow_emoji = "📥"  # inflow (bearish)
        flow_label = "دخول لـ Exchange"
    elif w.get("from_owner") == "exchange" and w.get("to_owner") == "exchange":
        flow_emoji = "🔄"
        flow_label = "بين Exchanges"
    else:
        flow_emoji = "💸"
        flow_label = "تحويل"

    # Time
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        time_str = dt.strftime("%H:%M UTC")
    except (ValueError, OSError):
        time_str = "?"

    # Size emoji
    if amount_usd >= 100_000_000:
        size_emoji = "🐋🐋🐋"
    elif amount_usd >= 10_000_000:
        size_emoji = "🐋🐋"
    elif amount_usd >= 1_000_000:
        size_emoji = "🐋"
    else:
        size_emoji = "🐟"

    msg = f"{size_emoji} {flow_emoji} *{amount:,.0f} {symbol}* "
    msg += f"(`${amount_usd:,.0f}`)\n"
    msg += f"   {from_owner} {arrow} {to_owner}\n"
    msg += f"   _{flow_label} • {time_str}_\n"
    return msg


def whales_msg(symbol: Optional[str] = None, hours: int = 6,
               min_usd: float = 1_000_000, limit: int = 15) -> str:
    whales = db.get_recent_whales(hours=hours, symbol=symbol,
                                   min_usd=min_usd, limit=limit)
    if not whales:
        scope = f"على {symbol}" if symbol else ""
        return (f"🐋 لا توجد تحويلات حيتان كبيرة {scope} "
                f"في آخر {hours} ساعة\n\n"
                "_المستوى الأدنى: $1M_")

    title = f"🐋 *تحويلات الحيتان"
    if symbol:
        title += f" — {symbol.upper()}"
    title += f"*  _(آخر {hours}h)_\n"
    msg = title + "\n"

    # ملخص الـflows
    inflow = sum(w["amount_usd"] for w in whales
                 if w["to_owner"] in ("exchange",) and
                    w["from_owner"] not in ("exchange",))
    outflow = sum(w["amount_usd"] for w in whales
                  if w["from_owner"] in ("exchange",) and
                     w["to_owner"] not in ("exchange",))
    if inflow + outflow > 0:
        net = outflow - inflow
        net_emoji = "🟢" if net > 0 else "🔴"
        msg += f"📊 *الصافي:* {net_emoji} ${net:+,.0f}\n"
        msg += f"  📤 خروج: ${outflow:,.0f}\n"
        msg += f"  📥 دخول: ${inflow:,.0f}\n\n"

    msg += "━━━━━━━━━━━━━━━━\n\n"
    for w in whales:
        msg += fmt_whale(w) + "\n"

    msg += ("\n💡 *تفسير:*\n"
            "📤 خروج من Exchange = ⚠️ نية شراء طويل (Bullish)\n"
            "📥 دخول لـ Exchange = ⚠️ نية بيع (Bearish)")
    return msg


# ─────────────────────────────────────────────
# Background job
# ─────────────────────────────────────────────

async def whale_check_job(ctx):
    """يشتغل كل 10 دقائق — يجلب التحويلات الجديدة"""
    if not WHALE_ALERT_KEY:
        return
    try:
        result = fetch_whale_transactions()
        if not result.get("ok"):
            return
        new_count = store_new_whales(result.get("transactions", []))
        if new_count > 0:
            logging.info(f"Whale: +{new_count} new transactions")
    except Exception as e:
        logging.error(f"whale_check_job error: {e}")
