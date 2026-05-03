"""
MAHMOUD_SIGNALS.py
═════════════════════════════════════════════════
محرك الإشارات المحسّن:
  • RSI(14) + MACD(12,26,9) كمؤشرات أساسية
  • Weighted scoring (0-15 سلم وزني)
  • MTF alignment (1h + 4h يجب يتفقا)
  • ATR-based Smart SL/TP (3 مستويات SL × 3 TPs)
  • BTC correlation filter للـAltcoins
  • Dynamic liquidation thresholds حسب market cap
═════════════════════════════════════════════════
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional


# ─────────────────────────────────────────────
# المؤشرات الأساسية
# ─────────────────────────────────────────────

def calc_rsi(closes: pd.Series, period: int = 14) -> float:
    """RSI(14) — يرجع آخر قيمة"""
    if len(closes) < period + 1:
        return 50.0
    delta = closes.diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def calc_macd(closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
    """MACD(12,26,9) — يرجع dict فيه macd, signal, hist, prev_hist"""
    if len(closes) < slow + signal:
        return {"macd": 0.0, "signal": 0.0, "hist": 0.0, "prev_hist": 0.0,
                "cross_up": False, "cross_down": False}
    ema_f = closes.ewm(span=fast, adjust=False).mean()
    ema_s = closes.ewm(span=slow, adjust=False).mean()
    macd_line = ema_f - ema_s
    sig_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - sig_line
    h_now = float(hist.iloc[-1])
    h_prev = float(hist.iloc[-2])
    return {
        "macd": float(macd_line.iloc[-1]),
        "signal": float(sig_line.iloc[-1]),
        "hist": h_now,
        "prev_hist": h_prev,
        "cross_up": h_prev <= 0 < h_now,
        "cross_down": h_prev >= 0 > h_now,
    }


def calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    """ATR(14) — للـ SL ديناميكي"""
    if df is None or len(df) < period + 1:
        return 0.0
    high = df["h"].astype(float)
    low = df["l"].astype(float)
    close = df["c"].astype(float)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    return float(atr.iloc[-1])


def calc_ema_stack(closes: pd.Series) -> Dict:
    """EMA stack — 20/50/200 لتحديد الترند"""
    e20 = closes.ewm(span=20, adjust=False).mean().iloc[-1]
    e50 = closes.ewm(span=50, adjust=False).mean().iloc[-1] if len(closes) >= 50 else e20
    e200 = closes.ewm(span=200, adjust=False).mean().iloc[-1] if len(closes) >= 200 else e50
    price = float(closes.iloc[-1])
    return {
        "e20": float(e20), "e50": float(e50), "e200": float(e200),
        "bullish_stack": price > e20 > e50 > e200,
        "bearish_stack": price < e20 < e50 < e200,
        "above_200": price > e200,
        "below_200": price < e200,
    }


def calc_bollinger(closes: pd.Series, period: int = 20,
                   std_dev: float = 2.0) -> Dict:
    """Bollinger Bands — يكتشف overbought/oversold و squeeze"""
    if len(closes) < period:
        return {"upper": 0, "middle": 0, "lower": 0,
                "position": 0.5, "squeeze": False, "width_pct": 0}
    sma = closes.rolling(window=period).mean()
    std = closes.rolling(window=period).std()
    upper = float((sma + std * std_dev).iloc[-1])
    lower = float((sma - std * std_dev).iloc[-1])
    middle = float(sma.iloc[-1])
    cur = float(closes.iloc[-1])

    bw = upper - lower
    pos = (cur - lower) / bw if bw > 0 else 0.5
    width_pct = (bw / middle * 100) if middle else 0

    return {
        "upper": upper, "middle": middle, "lower": lower,
        "position": pos,                # 0=bottom, 1=top
        "width_pct": width_pct,
        "squeeze": width_pct < 4,        # narrow band = breakout incoming
    }


# ─────────────────────────────────────────────
# MTF Alignment
# ─────────────────────────────────────────────

def get_tf_bias(df: pd.DataFrame) -> str:
    """يرجع BULLISH / BEARISH / NEUTRAL لإطار زمني واحد"""
    if df is None or len(df) < 30:
        return "NEUTRAL"
    closes = df["c"].astype(float)
    rsi = calc_rsi(closes)
    macd = calc_macd(closes)
    ema = calc_ema_stack(closes)
    price = float(closes.iloc[-1])

    bull = 0
    bear = 0
    if rsi > 55: bull += 1
    elif rsi < 45: bear += 1
    if macd["hist"] > 0 and macd["macd"] > macd["signal"]: bull += 1
    elif macd["hist"] < 0 and macd["macd"] < macd["signal"]: bear += 1
    if price > ema["e20"]: bull += 1
    else: bear += 1
    if ema["above_200"]: bull += 1
    else: bear += 1

    if bull >= 3: return "BULLISH"
    if bear >= 3: return "BEARISH"
    return "NEUTRAL"


def mtf_alignment(df_1h: pd.DataFrame, df_4h: pd.DataFrame,
                  df_1d: Optional[pd.DataFrame] = None) -> Dict:
    """
    يفحص توافق الإطارات الزمنية.
    للدخول القوي: 1h + 4h لازم في نفس الاتجاه.
    1d مفضل لكن مش إجباري.
    """
    b1h = get_tf_bias(df_1h)
    b4h = get_tf_bias(df_4h)
    b1d = get_tf_bias(df_1d) if df_1d is not None else "NEUTRAL"

    aligned_long = (b1h == "BULLISH" and b4h == "BULLISH")
    aligned_short = (b1h == "BEARISH" and b4h == "BEARISH")

    # bonus لو الـ1d موافق
    bonus = 0
    if aligned_long and b1d == "BULLISH": bonus = 1
    if aligned_short and b1d == "BEARISH": bonus = 1

    return {
        "1h": b1h, "4h": b4h, "1d": b1d,
        "aligned_long": aligned_long,
        "aligned_short": aligned_short,
        "bonus": bonus,
    }


# ─────────────────────────────────────────────
# Smart SL / TP (ATR-based, 3 levels)
# ─────────────────────────────────────────────

def calc_smart_sl_tp(price: float, action: str, df: pd.DataFrame,
                     symbol: str = "") -> Dict:
    """
    يحسب 3 مستويات SL × 3 TPs بناءً على ATR + Swing levels.

    Conservative:  SL = 2.0 × ATR  | TP1=1×R, TP2=2×R, TP3=3×R
    Balanced:      SL = 1.5 × ATR  | TP1=1.5×R, TP2=3×R, TP3=4.5×R
    Aggressive:    SL = 1.0 × ATR  | TP1=2×R, TP2=4×R, TP3=6×R
    """
    if df is None or len(df) < 20 or action not in ("LONG", "SHORT"):
        return {}

    atr = calc_atr(df)
    if atr <= 0:
        atr = price * 0.01  # 1% fallback

    # Swing low/high كحماية إضافية للـSL
    lookback = min(20, len(df))
    swing_low = float(df["l"].iloc[-lookback:].min())
    swing_high = float(df["h"].iloc[-lookback:].max())

    levels = {}
    for name, sl_mult, tp_mults in [
        ("conservative", 2.0, [1.0, 2.0, 3.0]),
        ("balanced",     1.5, [1.5, 3.0, 4.5]),
        ("aggressive",   1.0, [2.0, 4.0, 6.0]),
    ]:
        if action == "LONG":
            atr_sl = price - (atr * sl_mult)
            # SL = الأبعد بين ATR و swing low - قليل (حماية من stop hunt)
            sl = min(atr_sl, swing_low * 0.998)
            risk = price - sl
            tps = [price + (risk * m) for m in tp_mults]
        else:  # SHORT
            atr_sl = price + (atr * sl_mult)
            sl = max(atr_sl, swing_high * 1.002)
            risk = sl - price
            tps = [price - (risk * m) for m in tp_mults]

        levels[name] = {
            "sl": sl,
            "tp1": tps[0], "tp2": tps[1], "tp3": tps[2],
            "risk_pct": (abs(price - sl) / price * 100),
        }

    return {
        "atr": atr,
        "atr_pct": atr / price * 100,
        "swing_low": swing_low,
        "swing_high": swing_high,
        "levels": levels,
        "recommended": "balanced",
    }


# ─────────────────────────────────────────────
# Weighted Scoring (0-15)
# ─────────────────────────────────────────────

# الأوزان لكل مؤشر (مجموعها = 15)
WEIGHTS = {
    "ict":         3,   # ICT/SMC أقوى مؤشر
    "mtf":         2,   # MTF alignment
    "macd":        2,   # MACD cross/momentum
    "ema_stack":   2,   # EMA 20/50/200 stack
    "funding":     1,   # Funding rate
    "oi":          1,   # Open Interest
    "rsi":         1,   # RSI
    "ls_ratio":    1,   # Long/Short
    "liq":         1,   # Liquidations
    "cvd":         1,   # CVD
}
# Total = 15


def compute_signal_score(R: Dict, df_1h: pd.DataFrame, df_4h: pd.DataFrame,
                         df_1d: Optional[pd.DataFrame] = None) -> Dict:
    """
    يحسب score موزون من 15 لكل اتجاه (LONG/SHORT).
    R = dict من analyze() الأصلي مع البيانات الخام.
    يرجع: {long_score, short_score, components}
    """
    long_pts = 0.0
    short_pts = 0.0
    components = []

    price = R.get("price", 0)
    rate = R.get("rate", 0)
    df = df_1h

    # ─── 1. ICT (3 pts) ───
    ict = R.get("ict", {})
    ict_bull = ict.get("bull", 0)
    ict_bear = ict.get("bear", 0)
    if ict_bull >= 4:
        long_pts += WEIGHTS["ict"]
        components.append(("ICT", "✅ LONG", f"{ict_bull} bullish signals", WEIGHTS["ict"]))
    elif ict_bear >= 4:
        short_pts += WEIGHTS["ict"]
        components.append(("ICT", "🔴 SHORT", f"{ict_bear} bearish signals", WEIGHTS["ict"]))
    elif ict_bull >= 2:
        long_pts += WEIGHTS["ict"] * 0.5
        components.append(("ICT", "🟡 LONG ضعيف", f"{ict_bull}", WEIGHTS["ict"]*0.5))
    elif ict_bear >= 2:
        short_pts += WEIGHTS["ict"] * 0.5
        components.append(("ICT", "🟡 SHORT ضعيف", f"{ict_bear}", WEIGHTS["ict"]*0.5))
    else:
        components.append(("ICT", "⚪", "محايد", 0))

    # ─── 2. MTF Alignment (2 pts) ───
    mtf = mtf_alignment(df_1h, df_4h, df_1d)
    if mtf["aligned_long"]:
        pts = WEIGHTS["mtf"] + mtf["bonus"] * 0.5
        long_pts += pts
        components.append(("MTF", "✅ LONG",
                           f"1h:{mtf['1h']} | 4h:{mtf['4h']} | 1d:{mtf['1d']}", pts))
    elif mtf["aligned_short"]:
        pts = WEIGHTS["mtf"] + mtf["bonus"] * 0.5
        short_pts += pts
        components.append(("MTF", "🔴 SHORT",
                           f"1h:{mtf['1h']} | 4h:{mtf['4h']} | 1d:{mtf['1d']}", pts))
    else:
        components.append(("MTF", "⚪",
                           f"1h:{mtf['1h']} | 4h:{mtf['4h']}", 0))

    # ─── 3. MACD (2 pts) ───
    if df is not None and len(df) > 35:
        macd = calc_macd(df["c"])
        if macd["cross_up"] and macd["macd"] < 0:
            long_pts += WEIGHTS["macd"]
            components.append(("MACD", "✅ LONG",
                               "تقاطع صاعد من المنطقة السالبة", WEIGHTS["macd"]))
        elif macd["cross_up"]:
            long_pts += WEIGHTS["macd"] * 0.7
            components.append(("MACD", "✅ LONG",
                               "تقاطع صاعد", WEIGHTS["macd"]*0.7))
        elif macd["cross_down"] and macd["macd"] > 0:
            short_pts += WEIGHTS["macd"]
            components.append(("MACD", "🔴 SHORT",
                               "تقاطع هابط من المنطقة الموجبة", WEIGHTS["macd"]))
        elif macd["cross_down"]:
            short_pts += WEIGHTS["macd"] * 0.7
            components.append(("MACD", "🔴 SHORT", "تقاطع هابط", WEIGHTS["macd"]*0.7))
        elif macd["hist"] > 0 and macd["hist"] > macd["prev_hist"]:
            long_pts += WEIGHTS["macd"] * 0.4
            components.append(("MACD", "🟡 LONG", "زخم متصاعد", WEIGHTS["macd"]*0.4))
        elif macd["hist"] < 0 and macd["hist"] < macd["prev_hist"]:
            short_pts += WEIGHTS["macd"] * 0.4
            components.append(("MACD", "🟡 SHORT", "زخم متراجع", WEIGHTS["macd"]*0.4))
        else:
            components.append(("MACD", "⚪", f"hist={macd['hist']:.4f}", 0))

    # ─── 4. EMA Stack (2 pts) ───
    if df is not None and len(df) > 50:
        ema = calc_ema_stack(df["c"])
        if ema["bullish_stack"]:
            long_pts += WEIGHTS["ema_stack"]
            components.append(("EMA", "✅ LONG", "Stack صاعد كامل", WEIGHTS["ema_stack"]))
        elif ema["bearish_stack"]:
            short_pts += WEIGHTS["ema_stack"]
            components.append(("EMA", "🔴 SHORT", "Stack هابط كامل", WEIGHTS["ema_stack"]))
        elif ema["above_200"] and price > ema["e20"]:
            long_pts += WEIGHTS["ema_stack"] * 0.6
            components.append(("EMA", "🟡 LONG", "فوق 20 و 200", WEIGHTS["ema_stack"]*0.6))
        elif ema["below_200"] and price < ema["e20"]:
            short_pts += WEIGHTS["ema_stack"] * 0.6
            components.append(("EMA", "🟡 SHORT", "تحت 20 و 200", WEIGHTS["ema_stack"]*0.6))
        else:
            components.append(("EMA", "⚪", "ترند مختلط", 0))

    # ─── 5. Funding Rate (1 pt) ───
    if rate <= -0.05:
        long_pts += WEIGHTS["funding"]
        components.append(("Funding", "✅ LONG", f"{rate:.4f}%", WEIGHTS["funding"]))
    elif rate >= 0.1:
        short_pts += WEIGHTS["funding"]
        components.append(("Funding", "🔴 SHORT", f"{rate:.4f}%", WEIGHTS["funding"]))
    else:
        components.append(("Funding", "⚪", f"{rate:.4f}%", 0))

    # ─── 6. Open Interest (1 pt) ───
    oi = R.get("oi_chg")
    if df is not None and oi is not None and len(df) >= 4:
        pc = float(df["c"].iloc[-1] - df["c"].iloc[-3])
        if oi > 3 and pc > 0:
            long_pts += WEIGHTS["oi"]
            components.append(("OI", "✅ LONG", f"+{oi:.1f}% + سعر صاعد", WEIGHTS["oi"]))
        elif oi < -3 and pc < 0:
            short_pts += WEIGHTS["oi"]
            components.append(("OI", "🔴 SHORT", f"{oi:.1f}% + سعر هابط", WEIGHTS["oi"]))
        elif oi > 3 and pc < 0:
            short_pts += WEIGHTS["oi"]
            components.append(("OI", "🔴 SHORT", f"+{oi:.1f}% مع هبوط", WEIGHTS["oi"]))
        else:
            components.append(("OI", "⚪", f"{oi:+.1f}%", 0))

    # ─── 7. RSI (1 pt) ───
    if df is not None and len(df) > 15:
        rsi = calc_rsi(df["c"])
        if rsi < 30:
            long_pts += WEIGHTS["rsi"]
            components.append(("RSI", "✅ LONG", f"{rsi:.1f} (مشبع بيع)", WEIGHTS["rsi"]))
        elif rsi > 70:
            short_pts += WEIGHTS["rsi"]
            components.append(("RSI", "🔴 SHORT", f"{rsi:.1f} (مشبع شراء)", WEIGHTS["rsi"]))
        elif 45 <= rsi <= 55:
            components.append(("RSI", "⚪", f"{rsi:.1f} متعادل", 0))
        elif rsi > 55:
            long_pts += WEIGHTS["rsi"] * 0.4
            components.append(("RSI", "🟡 LONG", f"{rsi:.1f}", WEIGHTS["rsi"]*0.4))
        else:
            short_pts += WEIGHTS["rsi"] * 0.4
            components.append(("RSI", "🟡 SHORT", f"{rsi:.1f}", WEIGHTS["rsi"]*0.4))

    # ─── 8. Long/Short Ratio (1 pt) ───
    lp = R.get("ls_long")
    sp = R.get("ls_short")
    if lp is not None and sp is not None:
        if sp >= 60:
            long_pts += WEIGHTS["ls_ratio"]
            components.append(("L/S", "✅ LONG (Squeeze)",
                               f"L:{lp:.0f} | S:{sp:.0f}", WEIGHTS["ls_ratio"]))
        elif lp >= 65:
            short_pts += WEIGHTS["ls_ratio"]
            components.append(("L/S", "🔴 SHORT (overcrowded long)",
                               f"L:{lp:.0f} | S:{sp:.0f}", WEIGHTS["ls_ratio"]))
        else:
            components.append(("L/S", "⚪", f"L:{lp:.0f} | S:{sp:.0f}", 0))

    # ─── 9. Liquidations (1 pt) ───
    ll = R.get("liq_l", 0) or 0
    ls_ = R.get("liq_s", 0) or 0
    tot = ll + ls_
    threshold = dynamic_liq_threshold(R.get("sym", ""))
    if ls_ > ll * 2 and tot > threshold:
        long_pts += WEIGHTS["liq"]
        components.append(("Liquidations", "✅ LONG (Short Squeeze)",
                           f"S:${ls_:,.0f} > L:${ll:,.0f}", WEIGHTS["liq"]))
    elif ll > ls_ * 2 and tot > threshold:
        short_pts += WEIGHTS["liq"]
        components.append(("Liquidations", "🔴 SHORT (Long Liq)",
                           f"L:${ll:,.0f} > S:${ls_:,.0f}", WEIGHTS["liq"]))
    else:
        components.append(("Liquidations", "⚪", f"${tot:,.0f}", 0))

    # ─── 10. CVD (1 pt) ───
    if df is not None and len(df) > 6:
        try:
            d2 = df.copy()
            d2["dlta"] = d2["bq"] - (d2["qv"] - d2["bq"])
            d2["cvd"] = d2["dlta"].cumsum()
            cn = float(d2["cvd"].iloc[-1])
            cp = float(d2["cvd"].iloc[-6])
            pd_ = float(df["c"].iloc[-1] - df["c"].iloc[-6])
            if cn > cp and pd_ > 0:
                long_pts += WEIGHTS["cvd"]
                components.append(("CVD", "✅ LONG", "شراء حقيقي", WEIGHTS["cvd"]))
            elif cn < cp and pd_ < 0:
                short_pts += WEIGHTS["cvd"]
                components.append(("CVD", "🔴 SHORT", "بيع حقيقي", WEIGHTS["cvd"]))
            elif cn < cp and pd_ > 0:
                short_pts += WEIGHTS["cvd"] * 0.7
                components.append(("CVD", "🟡 ضعف",
                                   "ارتفاع وهمي (CVD ينزل)", WEIGHTS["cvd"]*0.7))
            else:
                components.append(("CVD", "⚪", "محايد", 0))
        except Exception:
            components.append(("CVD", "❓", "خطأ", 0))

    return {
        "long_score": round(long_pts, 1),
        "short_score": round(short_pts, 1),
        "max_score": sum(WEIGHTS.values()),  # 15
        "components": components,
        "mtf": mtf,
    }


# ─────────────────────────────────────────────
# Liquidation thresholds (ديناميكية حسب العملة)
# ─────────────────────────────────────────────

# الفئات تقريبية - top tier = high liquidity
HIGH_TIER = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"}
MID_TIER = {"DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
            "MATICUSDT", "LTCUSDT", "SHIBUSDT", "TRXUSDT", "NEARUSDT",
            "OPUSDT", "ARBUSDT", "INJUSDT", "TIAUSDT", "SUIUSDT"}


def dynamic_liq_threshold(symbol: str) -> float:
    """يرجع الحد الأدنى لتصفيات معتبرة"""
    s = symbol.upper()
    if s in HIGH_TIER:
        return 1_000_000  # $1M+ فقط
    if s in MID_TIER:
        return 200_000    # $200K+
    return 50_000          # $50K للعملات الصغيرة


# ─────────────────────────────────────────────
# BTC correlation filter
# ─────────────────────────────────────────────

def btc_filter(symbol: str, action: str, btc_bias_4h: str) -> Tuple[bool, str]:
    """
    للـAltcoins: لو BTC 4h في عكس الاتجاه، حذّر.
    يرجع: (allow: bool, warning: str)
    """
    s = symbol.upper()
    if s in ("BTCUSDT", "BTCUSD"):
        return True, ""

    if action == "LONG" and btc_bias_4h == "BEARISH":
        return False, "⚠️ BTC هابط على 4h — LONG على altcoin خطر"
    if action == "SHORT" and btc_bias_4h == "BULLISH":
        return False, "⚠️ BTC صاعد على 4h — SHORT على altcoin خطر"
    return True, ""


# ─────────────────────────────────────────────
# القرار النهائي
# ─────────────────────────────────────────────

# الحدود (يمكن تعديلها)
MIN_STRONG_SIGNAL = 12.0   # ≥12/15 = إشارة قوية
MIN_WEAK_SIGNAL = 9.0      # ≥9/15 = إشارة متوسطة (تحذير)


def make_decision(score: Dict, btc_bias_4h: str = "NEUTRAL",
                  symbol: str = "",
                  min_strong: float = MIN_STRONG_SIGNAL,
                  min_weak: float = MIN_WEAK_SIGNAL) -> Dict:
    """
    يحدد القرار النهائي بناءً على score + MTF + BTC filter.
    min_strong/min_weak قابلة للتخصيص للـSpot vs Futures.
    """
    long_s = score["long_score"]
    short_s = score["short_score"]
    mtf = score.get("mtf", {})

    # شرط الإشارة القوية: ≥min_strong و MTF aligned
    decision = "WAIT"
    confidence = "ضعيف"
    reason = ""

    if long_s >= min_strong and mtf.get("aligned_long"):
        ok, warn = btc_filter(symbol, "LONG", btc_bias_4h)
        if ok:
            decision = "LONG"
            confidence = "قوي"
            reason = f"score={long_s}/{score['max_score']} + MTF محاذي"
        else:
            decision = "WAIT"
            confidence = "محظور"
            reason = warn
    elif short_s >= min_strong and mtf.get("aligned_short"):
        ok, warn = btc_filter(symbol, "SHORT", btc_bias_4h)
        if ok:
            decision = "SHORT"
            confidence = "قوي"
            reason = f"score={short_s}/{score['max_score']} + MTF محاذي"
        else:
            decision = "WAIT"
            confidence = "محظور"
            reason = warn
    elif long_s >= min_weak and not mtf.get("aligned_short"):
        decision = "WAIT"
        confidence = "متوسط"
        reason = f"LONG محتمل ({long_s}) لكن MTF غير محاذٍ تماماً"
    elif short_s >= min_weak and not mtf.get("aligned_long"):
        decision = "WAIT"
        confidence = "متوسط"
        reason = f"SHORT محتمل ({short_s}) لكن MTF غير محاذٍ تماماً"
    else:
        decision = "WAIT"
        confidence = "ضعيف"
        reason = f"L:{long_s} | S:{short_s} (الحد {min_strong})"

    return {
        "action": decision,
        "confidence": confidence,
        "reason": reason,
        "long_score": long_s,
        "short_score": short_s,
        "max_score": score["max_score"],
    }
