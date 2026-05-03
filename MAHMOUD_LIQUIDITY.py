"""
MAHMOUD_LIQUIDITY.py — v5.0 Smart Risk Engine
═════════════════════════════════════════════════
يحسب SL/TP بناءً على السيولة الفعلية بدلاً من ATR ثابت.

المنهجية (مأخوذة من WALL STREET PRO V6):
1. تحليل خريطة السيولة:
   • Order Blocks (Bullish/Bearish)
   • Fair Value Gaps (FVG)
   • Swing Highs/Lows
   • Equal Highs/Lows (تجمعات stops)
   • Round Numbers
   • Weekly/Daily R/S

2. SL ذكي بـ3 مستويات:
   🟢 Conservative: خلف Order Block 4H + ATR×0.5
   🟡 Balanced: خلف Swing Point + ATR×0.3
   🔴 Aggressive: ATR×0.9 (مع تحذير)

3. TP ذكي بـ3 مستويات:
   🟢 TP1 Conservative: قبل Bearish/Bullish OB (78-85% احتمال)
   🟡 TP2 Balanced: Equal Highs Cluster (50-65% احتمال)
   🔴 TP3 Extended: Round Number / Weekly R/S (25-40% احتمال)

4. Danger Zones: أماكن لا تضع SL فيها (round numbers, swing levels)
5. Reject Zones: مقاومات في طريق TP (OB معاكسة، FVG)
═════════════════════════════════════════════════
"""

import logging
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np


# ─────────────────────────────────────────────
# Helper: نطبّع أسماء الأعمدة (h/l/c/o → high/low/close/open)
# ─────────────────────────────────────────────

def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """يطبّع dataframe ليستخدم: open, high, low, close, volume"""
    if df is None or df.empty:
        return df
    column_map = {
        "h": "high", "l": "low", "c": "close", "o": "open", "v": "volume",
        "H": "high", "L": "low", "C": "close", "O": "open", "V": "volume",
    }
    df = df.copy()
    for old, new in column_map.items():
        if old in df.columns and new not in df.columns:
            df[new] = df[old]
    return df


# ─────────────────────────────────────────────
# Helpers — Pivot Detection
# ─────────────────────────────────────────────

def find_swing_points(df: pd.DataFrame, lookback: int = 5) -> Dict[str, List[float]]:
    """
    يجد Swing Highs/Lows باستخدام pivot logic.
    Swing High = شمعة highest high لمدة 'lookback' شموع قبل وبعد.
    """
    if df is None or len(df) < (lookback * 2 + 1):
        return {"highs": [], "lows": []}

    highs = []
    lows = []

    for i in range(lookback, len(df) - lookback):
        # Check if this is a swing high
        is_high = all(df["high"].iloc[i] >= df["high"].iloc[i - j] for j in range(1, lookback + 1)) and \
                  all(df["high"].iloc[i] >= df["high"].iloc[i + j] for j in range(1, lookback + 1))

        # Check if this is a swing low
        is_low = all(df["low"].iloc[i] <= df["low"].iloc[i - j] for j in range(1, lookback + 1)) and \
                 all(df["low"].iloc[i] <= df["low"].iloc[i + j] for j in range(1, lookback + 1))

        if is_high:
            highs.append(float(df["high"].iloc[i]))
        if is_low:
            lows.append(float(df["low"].iloc[i]))

    return {"highs": highs, "lows": lows}


def find_order_blocks(df: pd.DataFrame, min_size_atr: float = 1.5,
                      atr_value: Optional[float] = None) -> Dict[str, List[Dict]]:
    """
    يكتشف Order Blocks:
    Bullish OB: آخر شمعة هابطة قبل دفعة صاعدة قوية (انعكاس).
    Bearish OB: آخر شمعة صاعدة قبل دفعة هابطة قوية.
    """
    if df is None or len(df) < 10:
        return {"bullish": [], "bearish": []}

    bullish_obs = []
    bearish_obs = []

    if atr_value is None:
        # نحسب ATR بسيط
        tr = pd.concat([
            df["high"] - df["low"],
            abs(df["high"] - df["close"].shift()),
            abs(df["low"] - df["close"].shift())
        ], axis=1).max(axis=1)
        atr_value = float(tr.rolling(14).mean().iloc[-1])
        if pd.isna(atr_value) or atr_value <= 0:
            atr_value = float(df["high"].iloc[-20:].max() - df["low"].iloc[-20:].min()) / 20

    threshold = atr_value * min_size_atr

    # نفحص آخر 50 شمعة
    start = max(2, len(df) - 50)
    for i in range(start, len(df) - 2):
        candle = df.iloc[i]
        next_candle = df.iloc[i + 1]
        next2 = df.iloc[i + 2]

        # Bullish OB: شمعة حمراء، تليها شمعة خضراء كبيرة
        if (candle["close"] < candle["open"] and  # red
                next_candle["close"] > next_candle["open"] and  # green
                (next_candle["close"] - next_candle["open"]) > threshold and
                next_candle["close"] > candle["high"]):
            bullish_obs.append({
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "mid": float((candle["high"] + candle["low"]) / 2),
                "index": i,
                "strength": float((next_candle["close"] - next_candle["open"]) / atr_value)
            })

        # Bearish OB: شمعة خضراء، تليها شمعة حمراء كبيرة
        if (candle["close"] > candle["open"] and  # green
                next_candle["close"] < next_candle["open"] and  # red
                (next_candle["open"] - next_candle["close"]) > threshold and
                next_candle["close"] < candle["low"]):
            bearish_obs.append({
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "mid": float((candle["high"] + candle["low"]) / 2),
                "index": i,
                "strength": float((next_candle["open"] - next_candle["close"]) / atr_value)
            })

    return {"bullish": bullish_obs[-5:], "bearish": bearish_obs[-5:]}


def find_fvg(df: pd.DataFrame) -> Dict[str, List[Dict]]:
    """
    Fair Value Gap: 3 شموع متتالية حيث:
    Bullish FVG: low[i] > high[i-2] (gap to upside)
    Bearish FVG: high[i] < low[i-2] (gap to downside)
    """
    if df is None or len(df) < 4:
        return {"bullish": [], "bearish": []}

    bullish_fvgs = []
    bearish_fvgs = []

    start = max(2, len(df) - 50)
    for i in range(start, len(df)):
        if i < 2:
            continue
        c0 = df.iloc[i - 2]
        c2 = df.iloc[i]

        if c2["low"] > c0["high"]:
            bullish_fvgs.append({
                "high": float(c2["low"]),
                "low": float(c0["high"]),
                "mid": float((c2["low"] + c0["high"]) / 2),
                "index": i
            })
        if c2["high"] < c0["low"]:
            bearish_fvgs.append({
                "high": float(c0["low"]),
                "low": float(c2["high"]),
                "mid": float((c0["low"] + c2["high"]) / 2),
                "index": i
            })

    return {"bullish": bullish_fvgs[-5:], "bearish": bearish_fvgs[-5:]}


def find_equal_levels(df: pd.DataFrame, tolerance_pct: float = 0.15) -> Dict[str, List[float]]:
    """
    يجد Equal Highs / Equal Lows (تجمعات stops):
    مستويات قريبة من بعضها بنسبة <= tolerance_pct
    """
    swings = find_swing_points(df)

    def cluster(points: List[float], tol: float) -> List[float]:
        if not points:
            return []
        sorted_pts = sorted(points)
        clusters = []
        current = [sorted_pts[0]]

        for p in sorted_pts[1:]:
            avg = sum(current) / len(current)
            if abs(p - avg) / avg * 100 <= tol:
                current.append(p)
            else:
                if len(current) >= 2:  # 2+ touches = equal
                    clusters.append(sum(current) / len(current))
                current = [p]
        if len(current) >= 2:
            clusters.append(sum(current) / len(current))
        return clusters

    return {
        "highs": cluster(swings["highs"], tolerance_pct),
        "lows": cluster(swings["lows"], tolerance_pct),
    }


def find_round_numbers(price: float, n: int = 3) -> List[float]:
    """
    يجد Round Numbers قريبة من السعر.
    للكريبتو: على حسب السعر:
    - BTC > $1000: round to 500/1000
    - $100 < price < $1000: round to 50/100
    - $1 < price < $100: round to 5/10
    - price < $1: round to 0.05/0.1
    """
    if price > 10000:
        step = 1000
    elif price > 1000:
        step = 500
    elif price > 100:
        step = 50
    elif price > 10:
        step = 10
    elif price > 1:
        step = 1
    elif price > 0.1:
        step = 0.1
    else:
        step = 0.01

    rounds = []
    base = round(price / step) * step
    for i in range(-n, n + 1):
        candidate = base + (i * step)
        if candidate > 0:
            rounds.append(round(candidate, 8))
    return rounds


# ─────────────────────────────────────────────
# ATR Helper
# ─────────────────────────────────────────────

def calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    """يحسب Average True Range"""
    if df is None or len(df) < period:
        return 0.0
    tr = pd.concat([
        df["high"] - df["low"],
        abs(df["high"] - df["close"].shift()),
        abs(df["low"] - df["close"].shift())
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr) if not pd.isna(atr) else 0.0


# ─────────────────────────────────────────────
# Liquidity Map (الأساس)
# ─────────────────────────────────────────────

def build_liquidity_map(df_15m: pd.DataFrame, df_1h: pd.DataFrame,
                        df_4h: pd.DataFrame, current_price: float) -> Dict:
    """
    يبني خريطة كاملة للسيولة حول السعر.
    """
    # نطبّع أسماء الأعمدة (h/l/c → high/low/close)
    df_15m = _normalize_df(df_15m)
    df_1h = _normalize_df(df_1h)
    df_4h = _normalize_df(df_4h)

    atr_4h = calc_atr(df_4h, 14)
    atr_1h = calc_atr(df_1h, 14)

    # Order Blocks من 4H (أقوى)
    obs_4h = find_order_blocks(df_4h, min_size_atr=1.5, atr_value=atr_4h)

    # FVG من 1H
    fvgs_1h = find_fvg(df_1h)

    # Swing points من 1H + 4H
    swings_1h = find_swing_points(df_1h, lookback=3)
    swings_4h = find_swing_points(df_4h, lookback=5)

    # Equal levels (liquidity pools)
    equal_1h = find_equal_levels(df_1h, tolerance_pct=0.15)

    # Round numbers
    rounds = find_round_numbers(current_price, n=4)

    # Bollinger Bands من 1H للـboundaries
    if len(df_1h) >= 20:
        ma20 = df_1h["close"].rolling(20).mean().iloc[-1]
        std20 = df_1h["close"].rolling(20).std().iloc[-1]
        bb_upper = float(ma20 + 2 * std20)
        bb_lower = float(ma20 - 2 * std20)
    else:
        bb_upper = current_price * 1.05
        bb_lower = current_price * 0.95

    return {
        "current_price": current_price,
        "atr_4h": atr_4h,
        "atr_1h": atr_1h,
        "obs_4h": obs_4h,
        "fvgs_1h": fvgs_1h,
        "swings_1h": swings_1h,
        "swings_4h": swings_4h,
        "equal_levels": equal_1h,
        "round_numbers": rounds,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
    }


# ─────────────────────────────────────────────
# Smart Stop Loss (3 مستويات)
# ─────────────────────────────────────────────

def smart_stop_loss(action: str, liq_map: Dict) -> Dict:
    """
    يحسب 3 مستويات SL بناءً على السيولة:
    • Conservative: خلف Order Block 4H + Buffer
    • Balanced: خلف Swing Point + Buffer
    • Aggressive: ATR × 0.9
    """
    price = liq_map["current_price"]
    atr_4h = liq_map["atr_4h"]
    atr_1h = liq_map["atr_1h"]

    if atr_4h <= 0:
        atr_4h = price * 0.02  # fallback
    if atr_1h <= 0:
        atr_1h = price * 0.01

    obs = liq_map["obs_4h"]
    swings_1h = liq_map["swings_1h"]
    swings_4h = liq_map["swings_4h"]

    if action == "LONG":
        # ─── Conservative SL: خلف أقرب Bullish OB (4H) ───
        bullish_obs_below = [ob for ob in obs["bullish"] if ob["low"] < price]
        if bullish_obs_below:
            closest_ob = max(bullish_obs_below, key=lambda x: x["low"])
            cons_sl = closest_ob["low"] - (atr_4h * 0.5)
            cons_reason = "خلف Order Block 4H + Buffer ATR×0.5"
        else:
            cons_sl = price - (atr_4h * 2.0)
            cons_reason = "ATR×2 (لا يوجد OB قريب)"

        # ─── Balanced SL: خلف أقرب Swing Low (1H) ───
        all_swings = swings_1h["lows"] + swings_4h["lows"]
        swings_below = [s for s in all_swings if s < price]
        if swings_below:
            closest_swing = max(swings_below)
            bal_sl = closest_swing - (atr_1h * 0.3)
            bal_reason = "خلف Swing Low + Buffer ATR×0.3"
        else:
            bal_sl = price - (atr_1h * 1.5)
            bal_reason = "ATR×1.5 (لا يوجد Swing قريب)"

        # ─── Aggressive SL: ATR × 0.9 ───
        agg_sl = price - (atr_1h * 0.9)
        agg_reason = "ATR×0.9 (سريع)"

    else:  # SHORT
        # ─── Conservative SL: فوق أقرب Bearish OB (4H) ───
        bearish_obs_above = [ob for ob in obs["bearish"] if ob["high"] > price]
        if bearish_obs_above:
            closest_ob = min(bearish_obs_above, key=lambda x: x["high"])
            cons_sl = closest_ob["high"] + (atr_4h * 0.5)
            cons_reason = "فوق Order Block 4H + Buffer ATR×0.5"
        else:
            cons_sl = price + (atr_4h * 2.0)
            cons_reason = "ATR×2 (لا يوجد OB قريب)"

        # ─── Balanced SL: فوق أقرب Swing High (1H) ───
        all_swings = swings_1h["highs"] + swings_4h["highs"]
        swings_above = [s for s in all_swings if s > price]
        if swings_above:
            closest_swing = min(swings_above)
            bal_sl = closest_swing + (atr_1h * 0.3)
            bal_reason = "فوق Swing High + Buffer ATR×0.3"
        else:
            bal_sl = price + (atr_1h * 1.5)
            bal_reason = "ATR×1.5 (لا يوجد Swing قريب)"

        # ─── Aggressive SL: ATR × 0.9 ───
        agg_sl = price + (atr_1h * 0.9)
        agg_reason = "ATR×0.9 (سريع)"

    # تحقق من Aggressive SL لو قريب من round number
    rounds = liq_map["round_numbers"]
    agg_warning = ""
    for rn in rounds:
        if abs(agg_sl - rn) / price * 100 < 0.3:  # < 0.3% bound
            agg_warning = f"⚠️ قريب من Round Number ${rn:,.2f}"
            break

    return {
        "conservative": {
            "level": round(cons_sl, 8),
            "reason": cons_reason,
            "risk_pct": abs(price - cons_sl) / price * 100,
        },
        "balanced": {
            "level": round(bal_sl, 8),
            "reason": bal_reason,
            "risk_pct": abs(price - bal_sl) / price * 100,
        },
        "aggressive": {
            "level": round(agg_sl, 8),
            "reason": agg_reason,
            "warning": agg_warning,
            "risk_pct": abs(price - agg_sl) / price * 100,
        },
    }


# ─────────────────────────────────────────────
# Smart Take Profit (3 أهداف + احتمالات)
# ─────────────────────────────────────────────

def smart_take_profit(action: str, liq_map: Dict, sl_balanced: float) -> Dict:
    """
    يحسب 3 أهداف TP بناءً على السيولة:
    • TP1 Conservative: قبل Bearish/Bullish OB (78-85% احتمال)
    • TP2 Balanced: Equal Highs Cluster (50-65% احتمال)
    • TP3 Extended: Round Number / BB / Weekly R (25-40% احتمال)
    """
    price = liq_map["current_price"]
    atr_4h = liq_map["atr_4h"]
    atr_1h = liq_map["atr_1h"]
    risk = abs(price - sl_balanced)

    obs = liq_map["obs_4h"]
    fvgs = liq_map["fvgs_1h"]
    equal = liq_map["equal_levels"]
    rounds = liq_map["round_numbers"]
    bb_upper = liq_map["bb_upper"]
    bb_lower = liq_map["bb_lower"]

    if action == "LONG":
        # ─── TP1: قبل Bearish OB (سيولة قريبة) ───
        bearish_obs_above = [ob for ob in obs["bearish"] if ob["low"] > price]
        if bearish_obs_above:
            closest_ob = min(bearish_obs_above, key=lambda x: x["low"])
            tp1 = closest_ob["low"] - (atr_1h * 0.2)  # نخرج قبل OB بقليل
            tp1_reason = "قبل Bearish OB (سيولة قوية)"
            tp1_prob = 80
        else:
            tp1 = price + (risk * 1.5)
            tp1_reason = "1.5R (لا يوجد OB قريب)"
            tp1_prob = 70

        # ─── TP2: Equal Highs Cluster ───
        equal_highs_above = [h for h in equal["highs"] if h > tp1]
        if equal_highs_above:
            tp2 = min(equal_highs_above)
            tp2_reason = "Equal Highs Cluster (تجمع stops)"
            tp2_prob = 55
        else:
            tp2 = price + (risk * 2.5)
            tp2_reason = "2.5R (لا يوجد cluster)"
            tp2_prob = 50

        # ─── TP3: Round Number / Weekly R ───
        rounds_above = [r for r in rounds if r > tp2]
        if rounds_above:
            tp3 = min(rounds_above)
            tp3_reason = f"Round Number ${tp3:,.2f}"
            tp3_prob = 35
        elif bb_upper > tp2:
            tp3 = bb_upper
            tp3_reason = "Bollinger Band Upper"
            tp3_prob = 30
        else:
            tp3 = price + (risk * 4)
            tp3_reason = "4R (target ممتد)"
            tp3_prob = 25

    else:  # SHORT
        # ─── TP1: قبل Bullish OB ───
        bullish_obs_below = [ob for ob in obs["bullish"] if ob["high"] < price]
        if bullish_obs_below:
            closest_ob = max(bullish_obs_below, key=lambda x: x["high"])
            tp1 = closest_ob["high"] + (atr_1h * 0.2)
            tp1_reason = "قبل Bullish OB (سيولة قوية)"
            tp1_prob = 80
        else:
            tp1 = price - (risk * 1.5)
            tp1_reason = "1.5R (لا يوجد OB قريب)"
            tp1_prob = 70

        # ─── TP2: Equal Lows Cluster ───
        equal_lows_below = [low for low in equal["lows"] if low < tp1]
        if equal_lows_below:
            tp2 = max(equal_lows_below)
            tp2_reason = "Equal Lows Cluster (تجمع stops)"
            tp2_prob = 55
        else:
            tp2 = price - (risk * 2.5)
            tp2_reason = "2.5R (لا يوجد cluster)"
            tp2_prob = 50

        # ─── TP3: Round Number / Weekly S ───
        rounds_below = [r for r in rounds if r < tp2]
        if rounds_below:
            tp3 = max(rounds_below)
            tp3_reason = f"Round Number ${tp3:,.2f}"
            tp3_prob = 35
        elif bb_lower < tp2:
            tp3 = bb_lower
            tp3_reason = "Bollinger Band Lower"
            tp3_prob = 30
        else:
            tp3 = price - (risk * 4)
            tp3_reason = "4R (target ممتد)"
            tp3_prob = 25

    # حساب R:R لكل هدف
    def rr(target):
        return abs(target - price) / risk if risk > 0 else 0

    return {
        "tp1": {"level": round(tp1, 8), "reason": tp1_reason,
                "probability": tp1_prob, "rr": round(rr(tp1), 2)},
        "tp2": {"level": round(tp2, 8), "reason": tp2_reason,
                "probability": tp2_prob, "rr": round(rr(tp2), 2)},
        "tp3": {"level": round(tp3, 8), "reason": tp3_reason,
                "probability": tp3_prob, "rr": round(rr(tp3), 2)},
        "weighted_rr": round((rr(tp1) * tp1_prob/100 +
                              rr(tp2) * tp2_prob/100 +
                              rr(tp3) * tp3_prob/100) /
                             ((tp1_prob + tp2_prob + tp3_prob)/100), 2),
    }


# ─────────────────────────────────────────────
# Danger Zones (تجنب SL هنا)
# ─────────────────────────────────────────────

def find_danger_zones(action: str, liq_map: Dict,
                      sl_min: float, sl_max: float) -> List[Dict]:
    """
    Danger Zones: مناطق تجمع stops حيث لا يجب وضع SL.
    """
    zones = []
    price = liq_map["current_price"]

    # Round Numbers في نطاق الـSL
    for rn in liq_map["round_numbers"]:
        if action == "LONG":
            if sl_min <= rn <= sl_max + (price * 0.005):
                zones.append({
                    "level": rn,
                    "type": "Round Number",
                    "icon": "🚨",
                    "warning": "تجمع stops كبير متوقع"
                })
        else:
            if sl_min - (price * 0.005) <= rn <= sl_max:
                zones.append({
                    "level": rn,
                    "type": "Round Number",
                    "icon": "🚨",
                    "warning": "تجمع stops كبير متوقع"
                })

    # Equal Highs/Lows في النطاق
    if action == "LONG":
        for eq in liq_map["equal_levels"]["lows"]:
            if sl_min <= eq <= price:
                zones.append({
                    "level": eq,
                    "type": "Equal Lows",
                    "icon": "🚨",
                    "warning": "Liquidity Pool"
                })
    else:
        for eq in liq_map["equal_levels"]["highs"]:
            if price <= eq <= sl_max:
                zones.append({
                    "level": eq,
                    "type": "Equal Highs",
                    "icon": "🚨",
                    "warning": "Liquidity Pool"
                })

    # Order Blocks
    obs = liq_map["obs_4h"]
    if action == "LONG":
        for ob in obs["bullish"]:
            if sl_min <= ob["mid"] <= price:
                zones.append({
                    "level": ob["mid"],
                    "type": "Bullish OB",
                    "icon": "📦",
                    "warning": f"OB strength {ob['strength']:.1f}x"
                })
    else:
        for ob in obs["bearish"]:
            if price <= ob["mid"] <= sl_max:
                zones.append({
                    "level": ob["mid"],
                    "type": "Bearish OB",
                    "icon": "📦",
                    "warning": f"OB strength {ob['strength']:.1f}x"
                })

    # Sort by distance from price
    zones.sort(key=lambda z: abs(z["level"] - price))
    return zones[:5]


# ─────────────────────────────────────────────
# Reject Zones (مقاومات في طريق TP)
# ─────────────────────────────────────────────

def find_reject_zones(action: str, liq_map: Dict, tp3_level: float) -> List[Dict]:
    """
    Reject Zones: OB معاكسة و FVG في طريق الـTP.
    """
    zones = []
    price = liq_map["current_price"]
    obs = liq_map["obs_4h"]
    fvgs = liq_map["fvgs_1h"]

    if action == "LONG":
        # Bearish OBs بين السعر والـTP3
        for ob in obs["bearish"]:
            if price < ob["mid"] < tp3_level:
                zones.append({
                    "level": ob["mid"],
                    "type": "Bearish OB",
                    "icon": "🟠",
                    "warning": "مقاومة OB قوية"
                })

        # Bearish FVGs
        for fvg in fvgs["bearish"]:
            if price < fvg["mid"] < tp3_level:
                zones.append({
                    "level": fvg["mid"],
                    "type": "Bearish FVG",
                    "icon": "🟡",
                    "warning": "Gap هابط في الطريق"
                })
    else:
        # Bullish OBs بين السعر والـTP3
        for ob in obs["bullish"]:
            if tp3_level < ob["mid"] < price:
                zones.append({
                    "level": ob["mid"],
                    "type": "Bullish OB",
                    "icon": "🟠",
                    "warning": "دعم OB قوي"
                })

        # Bullish FVGs
        for fvg in fvgs["bullish"]:
            if tp3_level < fvg["mid"] < price:
                zones.append({
                    "level": fvg["mid"],
                    "type": "Bullish FVG",
                    "icon": "🟡",
                    "warning": "Gap صاعد في الطريق"
                })

    zones.sort(key=lambda z: abs(z["level"] - price))
    return zones[:5]


# ─────────────────────────────────────────────
# Position Sizing
# ─────────────────────────────────────────────

def calc_position_size(price: float, sl: float,
                       account_size: float, risk_pct: float) -> Dict:
    """
    يحسب حجم الصفقة المثالي:
    Position Size = (Account × Risk%) / |Price - SL|
    """
    risk_amount = account_size * (risk_pct / 100)
    price_diff = abs(price - sl)
    if price_diff <= 0:
        return {"qty": 0, "value": 0, "risk_amount": 0}

    qty = risk_amount / price_diff
    value = qty * price

    return {
        "qty": round(qty, 6),
        "value": round(value, 2),
        "risk_amount": round(risk_amount, 2),
    }


def position_sizing_table(price: float, sl: float) -> List[Dict]:
    """جدول للسيناريوهات الشائعة"""
    scenarios = [
        (1000, 1.0), (1000, 1.5), (1000, 2.0),
        (5000, 1.0), (5000, 1.5), (5000, 2.0),
        (10000, 1.0), (10000, 1.5), (10000, 2.0),
    ]
    table = []
    for size, risk in scenarios:
        s = calc_position_size(price, sl, size, risk)
        table.append({
            "account": size,
            "risk_pct": risk,
            "qty": s["qty"],
            "value_usd": s["value"],
            "risk_usd": s["risk_amount"],
        })
    return table


# ─────────────────────────────────────────────
# Main API: get_smart_levels
# ─────────────────────────────────────────────

def get_smart_levels(action: str, df_15m: pd.DataFrame,
                     df_1h: pd.DataFrame, df_4h: pd.DataFrame,
                     current_price: float) -> Dict:
    """
    الواجهة الرئيسية — يرجع كل المستويات الذكية:
    • SL × 3
    • TP × 3
    • Danger Zones
    • Reject Zones
    • Liquidity Map
    • Risk metrics
    """
    if action not in ("LONG", "SHORT"):
        return {"error": "action must be LONG or SHORT"}

    # نطبّع أسماء الأعمدة
    df_15m = _normalize_df(df_15m)
    df_1h = _normalize_df(df_1h)
    df_4h = _normalize_df(df_4h)

    # تحقق من البيانات
    if df_4h is None or len(df_4h) < 20:
        return {"ok": False, "error": "insufficient_4h_data"}
    if df_1h is None or len(df_1h) < 30:
        return {"ok": False, "error": "insufficient_1h_data"}

    try:
        # ① Build liquidity map
        liq_map = build_liquidity_map(df_15m, df_1h, df_4h, current_price)

        # ② SL (3 levels)
        sl_levels = smart_stop_loss(action, liq_map)

        # ③ TP (3 targets) - based on Balanced SL
        tp_levels = smart_take_profit(action, liq_map,
                                       sl_levels["balanced"]["level"])

        # ④ Danger zones
        if action == "LONG":
            sl_min = sl_levels["conservative"]["level"]
            sl_max = sl_levels["aggressive"]["level"]
        else:
            sl_min = sl_levels["aggressive"]["level"]
            sl_max = sl_levels["conservative"]["level"]
        danger_zones = find_danger_zones(action, liq_map, sl_min, sl_max)

        # ⑤ Reject zones
        reject_zones = find_reject_zones(action, liq_map,
                                          tp_levels["tp3"]["level"])

        # ⑥ Quality assessment
        weighted_rr = tp_levels["weighted_rr"]
        if weighted_rr >= 2.5:
            quality = "✅ ممتاز"
        elif weighted_rr >= 1.5:
            quality = "🟡 مقبول"
        else:
            quality = "🔴 ضعيف"

        return {
            "ok": True,
            "action": action,
            "current_price": current_price,
            "sl": sl_levels,
            "tp": tp_levels,
            "danger_zones": danger_zones,
            "reject_zones": reject_zones,
            "weighted_rr": weighted_rr,
            "quality": quality,
            "liq_map": liq_map,
        }
    except Exception as e:
        logging.error(f"get_smart_levels error: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────
# Display formatter
# ─────────────────────────────────────────────

def fmt_smart_levels(levels: Dict) -> str:
    """تنسيق المستويات الذكية للعرض في تيليجرام"""
    if not levels.get("ok"):
        return f"❌ فشل تحليل السيولة: {levels.get('error', '?')}"

    action = levels["action"]
    price = levels["current_price"]
    sl = levels["sl"]
    tp = levels["tp"]
    quality = levels["quality"]
    weighted_rr = levels["weighted_rr"]

    msg = f"\n📊 *المستويات الذكية (مبنية على السيولة):*\n\n"

    # SL Section
    msg += "🛡 *Stop Loss (3 خيارات):*\n"
    msg += f"🟢 Conservative: `${sl['conservative']['level']:,.4f}`\n"
    msg += f"   _{sl['conservative']['reason']}_\n"
    msg += f"   Risk: {sl['conservative']['risk_pct']:.2f}%\n\n"

    msg += f"🟡 Balanced: `${sl['balanced']['level']:,.4f}`\n"
    msg += f"   _{sl['balanced']['reason']}_\n"
    msg += f"   Risk: {sl['balanced']['risk_pct']:.2f}%\n\n"

    msg += f"🔴 Aggressive: `${sl['aggressive']['level']:,.4f}`\n"
    msg += f"   _{sl['aggressive']['reason']}_\n"
    msg += f"   Risk: {sl['aggressive']['risk_pct']:.2f}%"
    if sl['aggressive'].get('warning'):
        msg += f"\n   {sl['aggressive']['warning']}"
    msg += "\n\n"

    # Danger Zones
    if levels["danger_zones"]:
        msg += "⚠️ *Danger Zones (تجنّب SL هنا):*\n"
        for z in levels["danger_zones"][:3]:
            msg += f"{z['icon']} `${z['level']:,.4f}` ({z['type']})\n"
        msg += "\n"

    # TP Section
    msg += "🎯 *Take Profit (3 أهداف):*\n"
    msg += f"🟢 TP1: `${tp['tp1']['level']:,.4f}` "
    msg += f"({tp['tp1']['probability']}% احتمال)\n"
    msg += f"   _{tp['tp1']['reason']}_\n"
    msg += f"   R:R = 1:{tp['tp1']['rr']}\n\n"

    msg += f"🟡 TP2: `${tp['tp2']['level']:,.4f}` "
    msg += f"({tp['tp2']['probability']}% احتمال)\n"
    msg += f"   _{tp['tp2']['reason']}_\n"
    msg += f"   R:R = 1:{tp['tp2']['rr']}\n\n"

    msg += f"🔴 TP3: `${tp['tp3']['level']:,.4f}` "
    msg += f"({tp['tp3']['probability']}% احتمال)\n"
    msg += f"   _{tp['tp3']['reason']}_\n"
    msg += f"   R:R = 1:{tp['tp3']['rr']}\n\n"

    # Reject Zones
    if levels["reject_zones"]:
        msg += "⚠️ *Reject Zones (مقاومة في الطريق):*\n"
        for z in levels["reject_zones"][:3]:
            msg += f"{z['icon']} `${z['level']:,.4f}` ({z['type']})\n"
        msg += "\n"

    # Summary
    msg += f"━━━━━━━━━━━━━━━━━\n"
    msg += f"📊 *متوسط R:R مرجّح:* 1:{weighted_rr}\n"
    msg += f"🎖 *جودة الصفقة:* {quality}\n\n"

    # Partial Close Plan
    msg += "📋 *خطة الخروج التدريجي:*\n"
    msg += "• @ TP1 → اقفل 50% + SL → Breakeven\n"
    msg += "• @ TP2 → اقفل 30% + SL → TP1\n"
    msg += "• @ TP3 → اقفل آخر 20%\n\n"

    # Position Size
    table = position_sizing_table(price, sl["balanced"]["level"])
    msg += "💰 *Position Size (مع SL Balanced):*\n"
    msg += "```\n"
    msg += "Account  Risk   Qty       Value\n"
    for r in table[:6:2]:  # نأخذ 3 سيناريوهات
        msg += f"${r['account']:<6} {r['risk_pct']}%   {r['qty']:.4f}   ${r['value_usd']:,.0f}\n"
    msg += "```\n"

    return msg
