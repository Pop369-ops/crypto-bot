"""
MAHMOUD_CALENDAR.py — v4.1 (Massive.com Edition)
═════════════════════════════════════════════════
التقويم الاقتصادي للكريبتو:
  • Massive.com Economy API (CPI + Treasury Yields + Inflation Expectations)
    → بديل أقوى من Trading Economics
  • Hardcoded FOMC 2026 Schedule (8 اجتماعات سنوية)
  • CoinMarketCal (token unlocks, listings, AMAs)
  • Filter: high-impact فقط للكريبتو

Authentication: Bearer token (Polygon.io style)
Base URL: https://api.massive.com
═════════════════════════════════════════════════
"""

import os
import json
import logging
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import MAHMOUD_DB as db


MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY", "")
COINMARKETCAL_KEY = os.environ.get("COINMARKETCAL_KEY", "")

MASSIVE_BASE = "https://api.massive.com"

# ─────────────────────────────────────────────
# FOMC 2026 Schedule (هاردكود — مصدر: federalreserve.gov)
# 8 اجتماعات؛ الـ* = Summary of Economic Projections
# ─────────────────────────────────────────────
FOMC_2026_SCHEDULE = [
    {"date": "2026-01-28", "time": "19:00", "type": "FOMC Decision", "sep": False},
    {"date": "2026-03-18", "time": "18:00", "type": "FOMC Decision", "sep": True},
    {"date": "2026-04-29", "time": "18:00", "type": "FOMC Decision", "sep": False},
    {"date": "2026-06-17", "time": "18:00", "type": "FOMC Decision", "sep": True},
    {"date": "2026-07-29", "time": "18:00", "type": "FOMC Decision", "sep": False},
    {"date": "2026-09-16", "time": "18:00", "type": "FOMC Decision", "sep": True},
    {"date": "2026-10-28", "time": "18:00", "type": "FOMC Decision", "sep": False},
    {"date": "2026-12-09", "time": "19:00", "type": "FOMC Decision", "sep": True},
]

# ─────────────────────────────────────────────
# الأحداث المهمة للكريبتو (Tagger للأخبار/البيانات)
# ─────────────────────────────────────────────
HIGH_IMPACT_EVENTS = [
    "Inflation Rate", "CPI", "Core CPI",
    "Fed Interest Rate", "FOMC", "Fed Chair",
    "Non Farm Payrolls", "Unemployment Rate",
    "GDP Growth Rate", "Retail Sales",
    "PCE Price Index", "PPI",
    "ECB Interest Rate", "ECB Press Conference",
    "Fed Minutes", "FOMC Minutes",
    "Powell Speech", "Yellen Speech",
    "Treasury Yields", "10Y Yield", "2Y Yield",
]

# ─────────────────────────────────────────────
# Massive.com Economy API
# ─────────────────────────────────────────────


def _massive_get(endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """Helper: GET to Massive API with bearer auth"""
    if not MASSIVE_API_KEY:
        return None
    url = f"{MASSIVE_BASE}{endpoint}"
    headers = {"Authorization": f"Bearer {MASSIVE_API_KEY}"}
    try:
        r = requests.get(url, headers=headers, params=params or {}, timeout=15)
        if r.status_code == 200:
            return r.json()
        logging.warning(f"Massive API {endpoint} HTTP {r.status_code}")
        return None
    except Exception as e:
        logging.error(f"Massive API error: {e}")
        return None


def fetch_inflation_data(limit: int = 12) -> List[Dict]:
    """آخر بيانات التضخم (CPI) من Massive Economy API."""
    cache_key = f"massive_cpi_{limit}"
    cached = db.cache_get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    data = _massive_get("/v1/economy/inflation",
                        {"limit": limit, "sort": "date.desc"})
    if not data or "results" not in data:
        return []

    results = data.get("results", [])
    db.cache_set(cache_key, json.dumps(results), ttl_seconds=21600)
    return results


def fetch_treasury_yields() -> Optional[Dict]:
    """آخر عوائد الخزانة الأمريكية (Treasury Yields)."""
    cache_key = "massive_treasury_latest"
    cached = db.cache_get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    data = _massive_get("/v1/economy/treasury-yields",
                        {"limit": 1, "sort": "date.desc"})
    if not data or "results" not in data:
        return None

    results = data.get("results", [])
    if not results:
        return None

    latest = results[0]
    db.cache_set(cache_key, json.dumps(latest), ttl_seconds=3600)
    return latest


def fetch_inflation_expectations() -> Optional[Dict]:
    """توقعات التضخم (5Y/10Y breakeven inflation rates)."""
    cache_key = "massive_inf_expectations"
    cached = db.cache_get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    data = _massive_get("/v1/economy/inflation-expectations",
                        {"limit": 1, "sort": "date.desc"})
    if not data or "results" not in data:
        return None

    results = data.get("results", [])
    if not results:
        return None

    latest = results[0]
    db.cache_set(cache_key, json.dumps(latest), ttl_seconds=21600)
    return latest


# ─────────────────────────────────────────────
# FOMC Schedule (Hardcoded)
# ─────────────────────────────────────────────


def get_upcoming_fomc(days_ahead: int = 30) -> List[Dict]:
    """اجتماعات FOMC القادمة في الـX يوم القادم."""
    now = datetime.utcnow()
    cutoff = now + timedelta(days=days_ahead)
    upcoming = []

    for meeting in FOMC_2026_SCHEDULE:
        try:
            dt_str = f"{meeting['date']}T{meeting['time']}:00"
            ev_dt = datetime.fromisoformat(dt_str)
        except (ValueError, KeyError):
            continue

        if ev_dt < now or ev_dt > cutoff:
            continue

        upcoming.append({
            "country": "United States",
            "event": f"FOMC Meeting{' (with SEP)' if meeting.get('sep') else ''}",
            "date": ev_dt,
            "importance": 3,
            "currency": "USD",
            "category": "Monetary Policy",
            "type": "macro",
            "source": "Federal Reserve",
        })

    return sorted(upcoming, key=lambda e: e["date"])


# ─────────────────────────────────────────────
# CoinMarketCal — Crypto-specific events
# ─────────────────────────────────────────────


def fetch_crypto_events(coins: Optional[List[str]] = None,
                        days_ahead: int = 14) -> List[Dict]:
    """أحداث الكريبتو من CoinMarketCal (token unlocks, listings, AMAs)."""
    if not COINMARKETCAL_KEY:
        return []

    headers = {
        "x-api-key": COINMARKETCAL_KEY,
        "Accept": "application/json",
        "Accept-Encoding": "deflate, gzip",
    }
    params = {
        "max": 50,
        "page": 1,
        "showOnly": "hot_events",
        "translations": "en",
    }
    if coins:
        params["coins"] = ",".join(coins).lower()

    try:
        r = requests.get("https://developers.coinmarketcal.com/v1/events",
                         headers=headers, params=params, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json().get("body", [])
        events = []
        cutoff = datetime.utcnow() + timedelta(days=days_ahead)
        for ev in data:
            try:
                ev_dt = datetime.fromisoformat(
                    ev.get("date_event", "").replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            ev_dt_naive = ev_dt.replace(tzinfo=None)
            if ev_dt_naive > cutoff:
                continue
            events.append({
                "title": ev.get("title", {}).get("en", ""),
                "event": ev.get("title", {}).get("en", ""),
                "date": ev_dt_naive,
                "coins": [c.get("symbol") for c in ev.get("coins", [])],
                "category": [c.get("name") for c in ev.get("categories", [])],
                "source": ev.get("source", ""),
                "votes": ev.get("vote_count", 0),
                "importance": 2,
                "type": "crypto",
            })
        return events
    except Exception as e:
        logging.error(f"CoinMarketCal error: {e}")
        return []


# ─────────────────────────────────────────────
# Combined view + filtering
# ─────────────────────────────────────────────


def get_today_events() -> List[Dict]:
    """أحداث اليوم: FOMC + crypto events"""
    fomc = get_upcoming_fomc(days_ahead=2)
    crypto = fetch_crypto_events(days_ahead=2)
    today = datetime.utcnow().date()

    today_events = []
    for ev in fomc + crypto:
        d = ev["date"]
        if isinstance(d, str):
            d = datetime.fromisoformat(d)
        if d.date() == today:
            today_events.append(ev)
    return sorted(today_events, key=lambda e: e["date"])


def get_week_events() -> List[Dict]:
    """أحداث الأسبوع: FOMC + crypto events"""
    fomc = get_upcoming_fomc(days_ahead=7)
    crypto = fetch_crypto_events(days_ahead=7)
    return sorted(fomc + crypto, key=lambda e: e["date"])


def is_high_impact_for_crypto(event_name: str) -> bool:
    """يحدد إذا الحدث يأثر على الكريبتو"""
    name_lower = event_name.lower()
    return any(k.lower() in name_lower for k in HIGH_IMPACT_EVENTS)


# ─────────────────────────────────────────────
# Macro Snapshot (الجديد — لقطة شاملة من Massive)
# ─────────────────────────────────────────────


def get_macro_snapshot() -> Dict:
    """لقطة شاملة للوضع الماكرو (CPI + Yields + توقعات التضخم)."""
    snap = {
        "cpi": None,
        "yields": None,
        "inflation_exp": None,
        "available": bool(MASSIVE_API_KEY),
    }

    if not MASSIVE_API_KEY:
        return snap

    cpi = fetch_inflation_data(limit=2)
    if cpi and len(cpi) >= 1:
        snap["cpi"] = {
            "latest": cpi[0],
            "previous": cpi[1] if len(cpi) > 1 else None,
        }

    yields = fetch_treasury_yields()
    if yields:
        snap["yields"] = yields

    exp = fetch_inflation_expectations()
    if exp:
        snap["inflation_exp"] = exp

    return snap


def fmt_macro_snapshot() -> str:
    """عرض لقطة الماكرو في رسالة تيليجرام"""
    snap = get_macro_snapshot()

    if not snap["available"]:
        return ("📊 *لقطة الماكرو*\n\n"
                "⚠️ Massive.com API key غير متاح\n"
                "أضف `MASSIVE_API_KEY` في Railway → Variables")

    msg = "📊 *لقطة الماكرو الحالية*\n"
    msg += "_(مصدر: Massive.com — Federal Reserve data)_\n\n"

    # CPI
    if snap["cpi"]:
        latest = snap["cpi"]["latest"]
        prev = snap["cpi"].get("previous")
        rate = latest.get("rate") or latest.get("value") or "—"
        date = latest.get("date", "")
        msg += f"🔥 *Inflation (CPI):* `{rate}%`\n"
        msg += f"   _آخر قراءة: {date}_\n"
        if prev:
            prev_rate = prev.get("rate") or prev.get("value")
            if prev_rate:
                try:
                    delta = float(rate) - float(prev_rate)
                    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
                    msg += f"   التغير: {arrow} {abs(delta):.2f}%\n"
                except (ValueError, TypeError):
                    pass
        msg += "\n"

    # Treasury Yields
    if snap["yields"]:
        y = snap["yields"]
        y2 = y.get("yield_2_year") or y.get("rate_2y") or "—"
        y10 = y.get("yield_10_year") or y.get("rate_10y") or "—"
        y30 = y.get("yield_30_year") or y.get("rate_30y") or "—"
        msg += "💵 *Treasury Yields:*\n"
        msg += f"   2Y: `{y2}%`  •  10Y: `{y10}%`  •  30Y: `{y30}%`\n"
        try:
            spread = float(y10) - float(y2)
            if spread < 0:
                msg += f"   ⚠️ Inverted curve ({spread:.2f}%) — إشارة ركود\n"
            elif spread < 0.5:
                msg += f"   🟡 Flat curve ({spread:.2f}%)\n"
            else:
                msg += f"   ✅ Normal curve ({spread:.2f}%)\n"
        except (ValueError, TypeError):
            pass
        msg += "\n"

    # Inflation Expectations
    if snap["inflation_exp"]:
        exp = snap["inflation_exp"]
        exp_5y = exp.get("expectation_5y") or exp.get("be_5y") or "—"
        exp_10y = exp.get("expectation_10y") or exp.get("be_10y") or "—"
        msg += "🔮 *Inflation Expectations:*\n"
        msg += f"   5Y: `{exp_5y}%`  •  10Y: `{exp_10y}%`\n"
        msg += "\n"

    msg += "_📝 ارتفاع الـyields = ضغط على الكريبتو_\n"
    msg += "_📝 ارتفاع توقعات التضخم = bullish للذهب والـBTC_"
    return msg


# ─────────────────────────────────────────────
# Display
# ─────────────────────────────────────────────


def fmt_event(ev: Dict) -> str:
    d = ev["date"]
    if isinstance(d, str):
        d = datetime.fromisoformat(d)
    time_str = d.strftime("%H:%M UTC")
    country_emoji = {
        "United States": "🇺🇸", "Euro Area": "🇪🇺", "China": "🇨🇳",
        "Japan": "🇯🇵", "United Kingdom": "🇬🇧", "Germany": "🇩🇪",
    }
    country = ev.get("country", "")
    flag = country_emoji.get(country, "🌍")
    impact = ev.get("importance", 1)
    impact_emoji = "🔥" if impact >= 3 else ("⚡" if impact >= 2 else "📅")

    msg = f"{impact_emoji} {flag} *{ev.get('event', ev.get('title', ''))}*\n"
    msg += f"   ⏰ {d.strftime('%Y-%m-%d')} • {time_str}"

    if ev.get("type") == "crypto":
        coins = ev.get("coins", [])
        if coins:
            msg += f"\n   💰 العملات: {', '.join(coins[:5])}"
        cats = ev.get("category", [])
        if cats:
            msg += f"\n   🏷️ {', '.join(cats[:3])}"

    msg += "\n"
    return msg


def calendar_today_msg() -> str:
    """تقويم اليوم"""
    events = get_today_events()
    if not events:
        return ("📅 *تقويم اليوم*\n\n"
                "✅ لا توجد أحداث ماكرو/كريبتو عالية التأثير اليوم\n"
                "_السوق هادئ نسبياً_\n\n"
                "_💡 استخدم `ماكرو` للقطة شاملة عن الـCPI/Yields_")
    msg = f"📅 *تقويم اليوم* — {datetime.utcnow().strftime('%Y-%m-%d')}\n\n"
    for ev in events:
        msg += fmt_event(ev) + "\n"
    msg += "_⚠️ الأحداث دي ممكن تسبب تقلبات قوية في الكريبتو_"
    return msg


def calendar_week_msg() -> str:
    """تقويم الأسبوع — مفصول حسب اليوم"""
    events = get_week_events()
    if not events:
        return ("📅 *تقويم الأسبوع*\n\n"
                "لا توجد أحداث ماكرو/كريبتو في الأسبوع القادم\n"
                "_💡 استخدم `ماكرو` للحالة الحالية_")

    by_day = {}
    for ev in events:
        d = ev["date"]
        if isinstance(d, str):
            d = datetime.fromisoformat(d)
        key = d.date().isoformat()
        by_day.setdefault(key, []).append(ev)

    msg = "📅 *تقويم الأسبوع*\n\n"
    for day in sorted(by_day.keys()):
        d = datetime.fromisoformat(day).date()
        day_label = d.strftime("%A %d-%m")
        msg += f"━━━ *{day_label}* ━━━\n"
        for ev in sorted(by_day[day], key=lambda e: e["date"] if isinstance(e["date"], datetime)
                         else datetime.fromisoformat(e["date"])):
            msg += fmt_event(ev)
        msg += "\n"
    return msg


def get_top_catalysts(n: int = 3) -> List[Dict]:
    """أهم 3 catalysts قادمة (الأقرب + الأعلى تأثير)"""
    events = get_week_events()
    today = datetime.utcnow()
    upcoming = []
    for ev in events:
        d = ev["date"]
        if isinstance(d, str):
            d = datetime.fromisoformat(d)
        if d > today and d < today + timedelta(days=7):
            upcoming.append(ev)
    upcoming.sort(key=lambda e: (-e.get("importance", 1),
                                  e["date"] if isinstance(e["date"], datetime)
                                  else datetime.fromisoformat(e["date"])))
    return upcoming[:n]


def fmt_top_catalysts() -> str:
    cats = get_top_catalysts(3)
    if not cats:
        return ("🎯 *Top Catalysts*\n\n"
                "لا توجد أحداث ماكرو في الأسبوع القادم\n"
                "_💡 استخدم `ماكرو` للقطة شاملة_")

    msg = "🎯 *أهم 3 Catalysts قادمة:*\n\n"
    for i, ev in enumerate(cats, 1):
        d = ev["date"]
        if isinstance(d, str):
            d = datetime.fromisoformat(d)
        delta = d - datetime.utcnow()
        hours = int(delta.total_seconds() / 3600)
        if hours < 24:
            when = f"خلال {hours}h"
        else:
            when = f"خلال {hours // 24}d"
        msg += f"*{i}. {ev.get('event', ev.get('title', ''))}*\n"
        msg += f"   {when} • {d.strftime('%Y-%m-%d %H:%M UTC')}\n"
        if ev.get("type") == "crypto" and ev.get("coins"):
            msg += f"   💰 {', '.join(ev['coins'][:3])}\n"
        msg += "\n"
    return msg
