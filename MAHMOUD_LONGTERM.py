"""
MAHMOUD_LONGTERM.py
═════════════════════════════════════════════════
Long-term mode — توصيات استثمارية:
  • فلترة على D1 و W1
  • Hodl signals (>3 شهور)
  • Bollinger Bands + EMA200 + RSI weekly
  • تحديد points of accumulation
═════════════════════════════════════════════════
"""

import logging
import requests
import pandas as pd
from datetime import datetime
from typing import Dict, Optional

import MAHMOUD_SIGNALS as signals


# ─────────────────────────────────────────────
# Long-term indicators
# ─────────────────────────────────────────────

def calc_bollinger(closes: pd.Series, period: int = 20,
                   std_dev: float = 2.0) -> Dict:
    """Bollinger Bands"""
    if len(closes) < period:
        return {"upper": None, "middle": None, "lower": None,
                "width": 0, "position": 0.5}
    sma = closes.rolling(window=period).mean()
    std = closes.rolling(window=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    cur_close = float(closes.iloc[-1])
    cur_upper = float(upper.iloc[-1])
    cur_lower = float(lower.iloc[-1])
    cur_middle = float(sma.iloc[-1])

    # %B (موقع السعر داخل الباندز)
    bw = cur_upper - cur_lower
    if bw > 0:
        pos = (cur_close - cur_lower) / bw
    else:
        pos = 0.5

    return {
        "upper": cur_upper,
        "middle": cur_middle,
        "lower": cur_lower,
        "width": bw,
        "width_pct": (bw / cur_middle * 100) if cur_middle else 0,
        "position": pos,  # 0 = bottom, 1 = top
        "squeeze": (bw / cur_middle * 100) < 5 if cur_middle else False,
    }


def calc_distance_from_ath(closes: pd.Series) -> Dict:
    """يحسب البعد من أعلى قمة"""
    ath = float(closes.max())
    cur = float(closes.iloc[-1])
    drawdown_pct = (cur - ath) / ath * 100
    return {
        "ath": ath,
        "current": cur,
        "drawdown_pct": drawdown_pct,
    }


# ─────────────────────────────────────────────
# Long-term analysis
# ─────────────────────────────────────────────

def fetch_klines(symbol: str, interval: str, limit: int = 500) -> Optional[pd.DataFrame]:
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/klines",
                          params={"symbol": symbol, "interval": interval,
                                   "limit": limit},
                          timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        if not data:
            return None
        df = pd.DataFrame(data, columns=[
            "ot", "o", "h", "l", "c", "v", "ct", "qv", "n", "bv", "bq", "ig"
        ])
        for col in ["o", "h", "l", "c"]:
            df[col] = df[col].astype(float)
        return df
    except Exception:
        return None


def long_term_analysis(symbol: str) -> Dict:
    """تحليل long-term على D1 + W1"""
    df_d = fetch_klines(symbol, "1d", 365)
    df_w = fetch_klines(symbol, "1w", 200)

    if df_d is None or len(df_d) < 50:
        return {"ok": False, "error": "no_daily_data"}

    closes_d = df_d["c"]
    closes_w = df_w["c"] if df_w is not None else closes_d
    cur_price = float(closes_d.iloc[-1])

    # D1 indicators
    rsi_d = signals.calc_rsi(closes_d)
    macd_d = signals.calc_macd(closes_d)
    ema_d = signals.calc_ema_stack(closes_d)
    bb_d = calc_bollinger(closes_d)
    ath_d = calc_distance_from_ath(closes_d)

    # W1 indicators
    rsi_w = signals.calc_rsi(closes_w) if len(closes_w) > 14 else 50
    ema_w = signals.calc_ema_stack(closes_w) if len(closes_w) > 50 else None
    bb_w = calc_bollinger(closes_w) if len(closes_w) > 20 else None

    # ─── Scoring (long-term) ───
    score = 0
    reasons_bull = []
    reasons_bear = []

    # 1. EMA stacks (الأهم على المدى الطويل)
    if ema_d["bullish_stack"]:
        score += 3; reasons_bull.append("EMA20>EMA50>EMA200 (D1) — uptrend راسخ")
    elif ema_d["bearish_stack"]:
        score -= 3; reasons_bear.append("EMA20<EMA50<EMA200 (D1) — downtrend")

    if ema_w and ema_w["above_200"]:
        score += 2; reasons_bull.append("السعر فوق EMA200 (W1)")
    elif ema_w and not ema_w["above_200"]:
        score -= 2; reasons_bear.append("السعر تحت EMA200 (W1) — bear market")

    # 2. RSI Weekly
    if rsi_w < 35:
        score += 2; reasons_bull.append(f"RSI W1 منخفض ({rsi_w:.0f}) — منطقة شراء")
    elif rsi_w > 70:
        score -= 2; reasons_bear.append(f"RSI W1 مرتفع ({rsi_w:.0f}) — مشبع")

    # 3. Distance from ATH (للـaccumulation)
    if ath_d["drawdown_pct"] < -50:
        score += 2
        reasons_bull.append(f"-{abs(ath_d['drawdown_pct']):.0f}% من ATH — فرصة accumulation")
    elif ath_d["drawdown_pct"] > -10:
        reasons_bear.append(f"قريب من ATH ({ath_d['drawdown_pct']:.0f}%) — حذر")

    # 4. Bollinger position
    if bb_d["position"] < 0.2:
        score += 1; reasons_bull.append("قاع Bollinger D1 — momentum معكوس محتمل")
    elif bb_d["position"] > 0.85:
        score -= 1; reasons_bear.append("قمة Bollinger D1 — احتمال تصحيح")

    if bb_d.get("squeeze"):
        reasons_bull.append("⚠️ Bollinger Squeeze — تحرك كبير قادم")

    # 5. MACD weekly trend
    if macd_d["hist"] > 0 and macd_d["macd"] > 0:
        score += 1; reasons_bull.append("MACD D1 إيجابي")
    elif macd_d["hist"] < 0 and macd_d["macd"] < 0:
        score -= 1; reasons_bear.append("MACD D1 سلبي")

    # ─── التوصية ───
    if score >= 5:
        recommendation = "STRONG_BUY"
        timeframe = "3-12 شهر"
        confidence = "قوي"
    elif score >= 2:
        recommendation = "BUY"
        timeframe = "1-6 شهور"
        confidence = "متوسط"
    elif score <= -5:
        recommendation = "STRONG_SELL"
        timeframe = "تفادي"
        confidence = "قوي"
    elif score <= -2:
        recommendation = "AVOID"
        timeframe = "انتظر"
        confidence = "متوسط"
    else:
        recommendation = "HOLD"
        timeframe = "غير محدد"
        confidence = "ضعيف"

    return {
        "ok": True,
        "symbol": symbol,
        "price": cur_price,
        "score": score,
        "recommendation": recommendation,
        "confidence": confidence,
        "timeframe": timeframe,
        "indicators": {
            "rsi_d": round(rsi_d, 1),
            "rsi_w": round(rsi_w, 1),
            "macd_d_hist": round(macd_d["hist"], 4),
            "ema_stack_d": ema_d,
            "bb_d": bb_d,
            "ath": ath_d,
        },
        "reasons_bull": reasons_bull,
        "reasons_bear": reasons_bear,
    }


def fmt_long_term(R: Dict) -> str:
    if not R.get("ok"):
        return f"❌ تحليل long-term فشل: {R.get('error', 'unknown')}"

    sym = R["symbol"]
    price = R["price"]
    rec = R["recommendation"]
    score = R["score"]

    rec_emoji = {
        "STRONG_BUY": "🟢🟢", "BUY": "🟢", "HOLD": "🟡",
        "AVOID": "🟠", "STRONG_SELL": "🔴🔴",
    }.get(rec, "⚪")

    rec_label = {
        "STRONG_BUY": "شراء قوي", "BUY": "شراء",
        "HOLD": "احتفاظ", "AVOID": "تفادي", "STRONG_SELL": "بيع قوي",
    }.get(rec, "?")

    msg = f"📈 *تحليل Long-term — {sym}*\n"
    msg += f"السعر: `${price:,.4f}`\n"
    msg += "━━━━━━━━━━━━━━━━\n\n"

    msg += f"{rec_emoji} *التوصية: {rec_label}*\n"
    msg += f"📊 Score: *{score:+d}* (الثقة: {R['confidence']})\n"
    msg += f"⏰ الإطار الزمني: {R['timeframe']}\n\n"

    ind = R["indicators"]
    msg += "📐 *المؤشرات الفنية:*\n"
    msg += f"  • RSI D1: {ind['rsi_d']} | RSI W1: {ind['rsi_w']}\n"
    msg += f"  • MACD D1 hist: {ind['macd_d_hist']:+.4f}\n"
    msg += f"  • ATH: ${ind['ath']['ath']:,.2f} ({ind['ath']['drawdown_pct']:+.0f}%)\n"

    bb = ind["bb_d"]
    msg += f"  • Bollinger D1:\n"
    msg += f"     Upper `${bb['upper']:.4f}` | "
    msg += f"Lower `${bb['lower']:.4f}`\n"
    msg += f"     Position: {bb['position']*100:.0f}% "
    msg += "(قاع)" if bb["position"] < 0.3 else \
           ("قمة" if bb["position"] > 0.7 else "وسط")
    msg += "\n"

    if R["reasons_bull"]:
        msg += "\n🟢 *العوامل الإيجابية:*\n"
        for r in R["reasons_bull"]:
            msg += f"  • {r}\n"

    if R["reasons_bear"]:
        msg += "\n🔴 *العوامل السلبية:*\n"
        for r in R["reasons_bear"]:
            msg += f"  • {r}\n"

    msg += "\n💡 *للـHodlers:*\n"
    if rec in ("STRONG_BUY", "BUY"):
        msg += "  ✅ DCA منطقي على المدى الطويل\n"
        msg += "  ✅ افتح position أساسي + إضافات على التراجعات\n"
    elif rec == "AVOID" or rec == "STRONG_SELL":
        msg += "  ⚠️ ابتعد حالياً — انتظر التأكيد\n"
        msg += "  ⚠️ لو مفتوح position — فكّر تخفيض الحجم\n"
    else:
        msg += "  🟡 ابقَ على وضعك — لا تضيف ولا تقلل الآن\n"

    msg += "\n_⚠️ تحليل تعليمي — استشر مستشار مالي قبل قرار استثماري كبير_"
    return msg
