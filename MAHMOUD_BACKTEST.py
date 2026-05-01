"""
MAHMOUD_BACKTEST.py
═════════════════════════════════════════════════
محرك Backtesting:
  • يجلب بيانات تاريخية من Binance
  • يطبق نظام إشارات v4 الموزون على كل شمعة
  • يحسب: Win Rate / PF / Max Drawdown / Sharpe
  • يعرض equity curve كنص
═════════════════════════════════════════════════
"""

import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import MAHMOUD_SIGNALS as signals


# ─────────────────────────────────────────────
# Fetch historical data
# ─────────────────────────────────────────────

def fetch_historical(symbol: str, interval: str = "1h",
                     limit: int = 1000) -> Optional[pd.DataFrame]:
    """يجلب klines من Binance Futures"""
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
        for col in ["o", "h", "l", "c", "v", "qv", "bv", "bq"]:
            df[col] = df[col].astype(float)
        df["ot"] = pd.to_datetime(df["ot"], unit="ms")
        return df
    except Exception as e:
        logging.error(f"fetch_historical error: {e}")
        return None


# ─────────────────────────────────────────────
# Single bar signal (نسخة مبسطة من compute_signal_score)
# ─────────────────────────────────────────────

def compute_score_at_bar(df_1h_window: pd.DataFrame,
                         df_4h: Optional[pd.DataFrame] = None,
                         df_1d: Optional[pd.DataFrame] = None) -> Dict:
    """
    يحسب score مبسط على نافذة من البيانات (للـbacktest).
    يستخدم بس المؤشرات الفنية (RSI, MACD, EMA, MTF).
    لأن Funding/OI/Liq غير متاحة تاريخياً عبر Binance API الحرة.
    """
    if df_1h_window is None or len(df_1h_window) < 50:
        return {"long_score": 0, "short_score": 0, "max_score": 8}

    closes = df_1h_window["c"]
    long_pts = 0.0
    short_pts = 0.0

    # ① RSI (1)
    rsi = signals.calc_rsi(closes)
    if rsi < 30: long_pts += 1
    elif rsi > 70: short_pts += 1

    # ② MACD (2)
    macd = signals.calc_macd(closes)
    if macd["cross_up"]: long_pts += 2
    elif macd["cross_down"]: short_pts += 2
    elif macd["hist"] > 0 and macd["hist"] > macd["prev_hist"]:
        long_pts += 1
    elif macd["hist"] < 0 and macd["hist"] < macd["prev_hist"]:
        short_pts += 1

    # ③ EMA Stack (2)
    if len(closes) > 200:
        ema = signals.calc_ema_stack(closes)
        if ema["bullish_stack"]: long_pts += 2
        elif ema["bearish_stack"]: short_pts += 2
        elif ema["above_200"]: long_pts += 1
        else: short_pts += 1

    # ④ MTF Alignment (3)
    if df_4h is not None and len(df_4h) > 30:
        mtf = signals.mtf_alignment(df_1h_window, df_4h, df_1d)
        if mtf["aligned_long"]: long_pts += 3
        elif mtf["aligned_short"]: short_pts += 3

    return {
        "long_score": round(long_pts, 1),
        "short_score": round(short_pts, 1),
        "max_score": 8,  # 1+2+2+3
        "rsi": round(rsi, 2),
        "macd_hist": round(macd["hist"], 4),
    }


# ─────────────────────────────────────────────
# Backtest engine
# ─────────────────────────────────────────────

def run_backtest(symbol: str, days: int = 30,
                 interval: str = "1h",
                 min_score: float = 6.0,
                 sl_atr_mult: float = 1.5,
                 tp_rr: float = 3.0) -> Dict:
    """
    Backtest على بيانات تاريخية.

    استراتيجية:
    - افحص كل شمعة 1h
    - لو score >= min_score → افتح صفقة
    - SL = atr * sl_atr_mult, TP = sl_dist * tp_rr
    - تتبع: SL أو TP أو إغلاق بعد 24h
    """
    # عدد الشموع المطلوبة
    candles = days * 24 if interval == "1h" else days * 6 if interval == "4h" else days
    candles = min(candles, 1500)

    df_1h = fetch_historical(symbol, "1h", candles + 100)
    df_4h = fetch_historical(symbol, "4h", min(500, candles // 4 + 50))
    df_1d = fetch_historical(symbol, "1d", min(200, days + 30))

    if df_1h is None or len(df_1h) < 100:
        return {"ok": False, "error": "no_data",
                "msg": "لم نستطع جلب بيانات كافية"}

    trades = []
    equity = [100.0]  # base 100

    # ابدأ من 200 شمعة (لـEMA200)
    start_idx = max(200, 50)

    i = start_idx
    while i < len(df_1h) - 24:  # نخلي 24 شمعة للـTP/SL
        window = df_1h.iloc[:i+1]
        # 4h و 1d windows مقابلة (تقريبية)
        cur_time = df_1h.iloc[i]["ot"]
        df_4h_cur = df_4h[df_4h["ot"] <= cur_time] if df_4h is not None else None
        df_1d_cur = df_1d[df_1d["ot"] <= cur_time] if df_1d is not None else None

        score = compute_score_at_bar(window, df_4h_cur, df_1d_cur)
        long_s = score["long_score"]
        short_s = score["short_score"]

        action = None
        if long_s >= min_score and long_s > short_s:
            action = "LONG"
            score_used = long_s
        elif short_s >= min_score and short_s > long_s:
            action = "SHORT"
            score_used = short_s

        if action:
            entry_price = float(df_1h.iloc[i]["c"])
            atr = signals.calc_atr(window)
            if atr <= 0:
                atr = entry_price * 0.01

            if action == "LONG":
                sl = entry_price - (atr * sl_atr_mult)
                tp = entry_price + ((entry_price - sl) * tp_rr)
            else:
                sl = entry_price + (atr * sl_atr_mult)
                tp = entry_price - ((sl - entry_price) * tp_rr)

            # تتبع 24 شمعة قادمة
            outcome = "TIMEOUT"
            exit_price = entry_price
            exit_idx = min(i + 24, len(df_1h) - 1)

            for j in range(i + 1, min(i + 25, len(df_1h))):
                bar = df_1h.iloc[j]
                if action == "LONG":
                    if bar["l"] <= sl:
                        outcome = "SL"
                        exit_price = sl
                        exit_idx = j
                        break
                    if bar["h"] >= tp:
                        outcome = "TP"
                        exit_price = tp
                        exit_idx = j
                        break
                else:
                    if bar["h"] >= sl:
                        outcome = "SL"
                        exit_price = sl
                        exit_idx = j
                        break
                    if bar["l"] <= tp:
                        outcome = "TP"
                        exit_price = tp
                        exit_idx = j
                        break

            if outcome == "TIMEOUT":
                exit_price = float(df_1h.iloc[exit_idx]["c"])

            # حساب pnl
            if action == "LONG":
                pnl_pct = (exit_price - entry_price) / entry_price * 100
            else:
                pnl_pct = (entry_price - exit_price) / entry_price * 100

            # افترض 2% size
            equity.append(equity[-1] * (1 + pnl_pct / 100 * 0.02))

            trades.append({
                "entry_time": df_1h.iloc[i]["ot"].isoformat(),
                "exit_time": df_1h.iloc[exit_idx]["ot"].isoformat(),
                "action": action,
                "entry": entry_price,
                "exit": exit_price,
                "sl": sl,
                "tp": tp,
                "outcome": outcome,
                "pnl_pct": round(pnl_pct, 2),
                "score": score_used,
                "duration_h": exit_idx - i,
            })

            # نتقدم للـoutcome bar (تجنب صفقات متراكبة)
            i = exit_idx + 1
        else:
            i += 1

    # ─── احصائيات ───
    if not trades:
        return {"ok": True, "trades": [], "msg": "لا توجد إشارات في الفترة"}

    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] < 0]
    timeouts = [t for t in trades if t["outcome"] == "TIMEOUT"]

    total_pnl = sum(t["pnl_pct"] for t in trades)
    gross_profit = sum(t["pnl_pct"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["pnl_pct"] for t in losses)) if losses else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else (999 if gross_profit > 0 else 0)

    # Max drawdown
    peak = equity[0]
    max_dd = 0
    for e in equity:
        if e > peak: peak = e
        dd = (peak - e) / peak * 100
        if dd > max_dd: max_dd = dd

    # Sharpe (بسيط)
    pnls = [t["pnl_pct"] for t in trades]
    if len(pnls) > 1:
        avg = sum(pnls) / len(pnls)
        var = sum((p - avg) ** 2 for p in pnls) / len(pnls)
        std = var ** 0.5
        sharpe = (avg / std) * (365 ** 0.5) if std > 0 else 0
    else:
        sharpe = 0

    return {
        "ok": True,
        "symbol": symbol,
        "days": days,
        "interval": interval,
        "min_score": min_score,
        "trades": trades,
        "stats": {
            "total": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "timeouts": len(timeouts),
            "win_rate": round(len(wins) / len(trades) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(sum(t["pnl_pct"] for t in wins) / len(wins), 2)
                       if wins else 0,
            "avg_loss": round(sum(t["pnl_pct"] for t in losses) / len(losses), 2)
                        if losses else 0,
            "profit_factor": round(pf, 2),
            "max_drawdown": round(max_dd, 2),
            "sharpe": round(sharpe, 2),
            "final_equity": round(equity[-1], 2),
            "best_trade": max(trades, key=lambda t: t["pnl_pct"]),
            "worst_trade": min(trades, key=lambda t: t["pnl_pct"]),
        },
    }


def fmt_backtest(result: Dict) -> str:
    if not result.get("ok"):
        return f"❌ Backtest فشل: {result.get('error', 'unknown')}"

    if not result.get("trades"):
        return f"📊 لا توجد إشارات في {result.get('days', 0)} يوم"

    s = result["stats"]
    sym = result["symbol"]

    win_emoji = "🟢" if s["win_rate"] >= 50 else "🔴"
    pnl_emoji = "🟢" if s["total_pnl"] > 0 else "🔴"
    pf_emoji = "🟢" if s["profit_factor"] >= 1.5 else \
               ("🟡" if s["profit_factor"] >= 1 else "🔴")

    msg = f"📊 *Backtest — {sym}*\n"
    msg += f"الفترة: {result['days']} يوم | "
    msg += f"الإطار: {result['interval']} | "
    msg += f"حد الإشارة: ≥{result['min_score']}/8\n"
    msg += "━━━━━━━━━━━━━━━━\n\n"

    msg += f"🔢 *الصفقات:* {s['total']}\n"
    msg += f"  {win_emoji} رابحة: {s['wins']} ({s['win_rate']}%)\n"
    msg += f"  🔴 خاسرة: {s['losses']}\n"
    if s["timeouts"]: msg += f"  ⏱ انتهت بدون نتيجة: {s['timeouts']}\n"

    msg += f"\n💰 *الأرباح:*\n"
    msg += f"  {pnl_emoji} إجمالي: *{s['total_pnl']:+.2f}%*\n"
    msg += f"  🟢 متوسط الرابحة: +{s['avg_win']}%\n"
    msg += f"  🔴 متوسط الخاسرة: {s['avg_loss']}%\n"
    msg += f"  💼 رأس مال نهائي: {s['final_equity']} (من 100)\n"

    msg += f"\n📈 *المقاييس:*\n"
    msg += f"  {pf_emoji} Profit Factor: *{s['profit_factor']}*\n"
    msg += f"  📉 Max Drawdown: -{s['max_drawdown']}%\n"
    msg += f"  📊 Sharpe Ratio: {s['sharpe']}\n"

    if s["best_trade"]:
        b = s["best_trade"]
        msg += f"\n🏆 *أفضل صفقة:* {b['action']} → {b['pnl_pct']:+.2f}%"
    if s["worst_trade"]:
        w = s["worst_trade"]
        msg += f"\n💀 *أسوأ صفقة:* {w['action']} → {w['pnl_pct']:+.2f}%"

    # تقييم
    msg += "\n\n💡 *التقييم:*\n"
    if s["win_rate"] >= 55 and s["profit_factor"] >= 1.5:
        msg += "  ⭐ استراتيجية ممتازة"
    elif s["win_rate"] >= 45 and s["profit_factor"] >= 1.2:
        msg += "  👍 استراتيجية جيدة"
    elif s["profit_factor"] >= 1:
        msg += "  ⚠️ حدّية — راجع المعايير"
    else:
        msg += "  🚨 خاسرة — لا تستخدم"

    msg += "\n\n_⚠️ النتائج الماضية لا تضمن المستقبل_"
    return msg
