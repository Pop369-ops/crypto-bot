"""
MAHMOUD TRADING BOT v3
======================
8 مؤشرات:
  1. Funding Rate
  2. Open Interest
  3. Long/Short Ratio
  4. EMA + Volume
  5. Liquidations
  6. CVD
  7. On-Chain (Etherscan Gas Oracle)
  8. Candlestick Patterns (15m | 1h | 4h | 1d)

+ نظام خروج تلقائي: SL / TP1 / TP2 / انعكاس

للأغراض التعليمية فقط
"""

import asyncio
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)

logging.basicConfig(level=logging.WARNING)

# ==================================================
# ضع التوكن هنا — أو شغّل SETUP.py تلقائياً
# ==================================================
import os as _os
BOT_TOKEN = _os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ETHERSCAN_KEY  = os.environ.get("ETHERSCAN_KEY", "YOUR_ETHERSCAN_KEY_HERE")
# ==================================================

BASE        = "https://fapi.binance.com"
ETH_API     = "https://api.etherscan.io/api"
watching    = {}
_scheduler  = None  # APScheduler instance
open_trades = {}  # {chat_id: {sym: {action,entry,sl,tp1,tp2,tp1_hit}}}

session = requests.Session()
adapter = requests.adapters.HTTPAdapter(max_retries=0)
session.mount("https://", adapter)
session.mount("http://",  adapter)


def api_get(url, params=None, timeout=(4, 8)):
    return session.get(url, params=params, timeout=timeout)


# ==================================================
# Binance — جلب البيانات
# ==================================================


# ── قاموس شامل لكل العملات الشائعة ──
_ALIASES = {
    "BTC":"BTCUSDT","ETH":"ETHUSDT","SOL":"SOLUSDT","BNB":"BNBUSDT",
    "XRP":"XRPUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","DOT":"DOTUSDT",
    "LINK":"LINKUSDT","MATIC":"MATICUSDT","POL":"POLUSDT",
    "OP":"OPUSDT","ARB":"ARBUSDT","SUI":"SUIUSDT","SEI":"SEIUSDT",
    "APT":"APTUSDT","INJ":"INJUSDT","TIA":"TIAUSDT","NEAR":"NEARUSDT",
    "ATOM":"ATOMUSDT","FTM":"FTMUSDT","S":"SUSDT",
    # DeFi
    "UNI":"UNIUSDT","AAVE":"AAVEUSDT","MKR":"MKRUSDT","CRV":"CRVUSDT",
    "LDO":"LDOUSDT","COMP":"COMPUSDT","SNX":"SNXUSDT",
    # AI/Compute
    "RENDER":"RENDERUSDT","RNDR":"RENDERUSDT","FET":"FETUSDT",
    "AGIX":"AGIXUSDT","OCEAN":"OCEANUSDT","TAO":"TAOUSDT",
    # Gaming/NFT
    "AXS":"AXSUSDT","SAND":"SANDUSDT","MANA":"MANAUSDT",
    "IMX":"IMXUSDT","GALA":"GALAUSDT",
    # Memecoins
    "DOGE":"DOGEUSDT","SHIB":"SHIBUSDT","PEPE":"PEPEUSDT",
    "FLOKI":"FLOKIUSDT","BONK":"BONKUSDT","BOME":"BOMEUSDT",
    "WIF":"WIFUSDT","POPCAT":"POPCATUSDT","MEW":"MEWUSDT",
    "NEIRO":"NEIROUSDT","MOG":"MOGUSDT","TURBO":"TURBOUSDT",
    "1000PEPE":"1000PEPEUSDT","1000SHIB":"1000SHIBUSDT",
    "1000BONK":"1000BONKUSDT","SATS":"1000SATSUSDT",
    # DEX/Solana
    "ORCA":"ORCAUSDT","JUP":"JUPUSDT","PYTH":"PYTHUSDT",
    "JITO":"JITOUSDT","RAY":"RAYUSDT","DRIFT":"DRIFTUSDT",
    # Special
    "HYPE":"HYPEUSDT","HYPR":"HYPRUSDT","CHIP":"CHIPUSDT",
    "OKB":"OKBUSDT","GT":"GTUSDT","CRO":"CROUSDT",
    # New
    "ZK":"ZKUSDT","EIGEN":"EIGENUSDT","IO":"IOUSDT",
    "ZEUS":"ZEUSUSDT","JUP":"JUPUSDT","W":"WUSDT",
    "STRK":"STRKUSDT","ALT":"ALTUSDT","MANTA":"MANTAUSDT",
    "PORTAL":"PORTALUSDT","PIXEL":"PIXELUSDT","SAGA":"SAGAUSDT",
}

def resolve_sym(raw: str) -> str:
    """تحويل اسم مختصر لرمز Binance الصحيح."""
    s = raw.upper().strip()
    if s in _ALIASES:
        return _ALIASES[s]
    if any(s.endswith(x) for x in ("USDT","USDC","BTC","ETH","BUSD")):
        return s
    return s + "USDT"

def fetch_binance(sym):
    """جلب بيانات Binance — Futures أولاً ثم Spot."""
    out = {
        "price": None, "rate": None, "df": None,
        "ls_long": None, "ls_short": None,
        "oi_chg": None, "liq_l": 0.0, "liq_s": 0.0,
    }

    # ① Futures markPrice
    try:
        r = api_get(f"{BASE}/fapi/v1/premiumIndex", {"symbol": sym}, timeout=(5,12))
        if r and r.status_code == 200:
            d = r.json()
            if isinstance(d, list): d = d[0]
            mp = d.get("markPrice")
            if mp and float(mp) > 0:
                out["price"] = float(mp)
                out["rate"]  = float(d.get("lastFundingRate","0")) * 100
    except Exception: pass

    # ② Spot price fallback
    if not out["price"]:
        for url in [
            "https://api.binance.com/api/v3/ticker/price",
            "https://api1.binance.com/api/v3/ticker/price",
            "https://api2.binance.com/api/v3/ticker/price",
        ]:
            try:
                r = api_get(url, {"symbol": sym}, timeout=(5,10))
                if r and r.status_code == 200:
                    d = r.json()
                    if "price" in d and float(d["price"]) > 0:
                        out["price"] = float(d["price"])
                        out["rate"]  = 0.0
                        break
            except Exception: continue

    if not out["price"]:
        raise Exception(f"❌ {sym} غير متاح — تحقق من اسم العملة")

    # 2. شموع 1h (60 شمعة للمؤشرات الأساسية)
    try:
        r  = api_get(f"{BASE}/fapi/v1/klines",
                     {"symbol": sym, "interval": "1h", "limit": 60})
        df = pd.DataFrame(r.json(), columns=[
            "t","o","h","l","c","v","ct","qv","tr","bb","bq","ig"])
        for col in ["o","h","l","c","v","qv","bq"]:
            df[col] = df[col].astype(float)
        out["df"] = df
    except Exception:
        pass

    # 3. Long/Short Ratio
    try:
        r = api_get(f"{BASE}/futures/data/globalLongShortAccountRatio",
                    {"symbol": sym, "period": "1h", "limit": 1})
        d = r.json()
        if isinstance(d, list) and d:
            ls = float(d[0]["longShortRatio"])
            lp = ls / (1 + ls) * 100
            out["ls_long"]  = lp
            out["ls_short"] = 100 - lp
    except Exception:
        pass

    # 4. Open Interest
    try:
        r = api_get(f"{BASE}/futures/data/openInterestHist",
                    {"symbol": sym, "period": "1h", "limit": 5})
        d = r.json()
        if isinstance(d, list) and len(d) >= 3:
            now  = float(d[-1]["sumOpenInterest"])
            prev = float(d[-3]["sumOpenInterest"])
            if prev > 0:
                out["oi_chg"] = (now - prev) / prev * 100
    except Exception:
        pass

    # 5. Liquidations
    try:
        r = api_get(f"{BASE}/futures/data/allForceOrders",
                    {"symbol": sym, "limit": 500})
        d = r.json()
        if isinstance(d, list):
            for o in d:
                try:
                    qty = float(o.get("origQty") or 0)
                    px  = float(o.get("averagePrice") or o.get("price") or 0)
                    val = qty * px
                    if o.get("side") == "SELL":
                        out["liq_l"] += val
                    elif o.get("side") == "BUY":
                        out["liq_s"] += val
                except Exception:
                    pass
    except Exception:
        pass

    return out


def fetch_tf(sym, interval, limit):
    """جلب شموع لفريم محدد."""
    r  = api_get(f"{BASE}/fapi/v1/klines",
                 {"symbol": sym, "interval": interval, "limit": limit})
    df = pd.DataFrame(r.json(), columns=[
        "t","o","h","l","c","v","ct","qv","tr","bb","bq","ig"])
    for col in ["o","h","l","c","v"]:
        df[col] = df[col].astype(float)
    return df


# ==================================================
# Etherscan — On-Chain
# ==================================================

def fetch_onchain(sym):
    """Fear & Greed Index + BTC Dominance (مجاني بدون API Key)"""
    try:
        r = session.get("https://api.alternative.me/fng/",
                        params={"limit": 1}, timeout=(5,10))
        d = r.json()
        fg = int(d["data"][0]["value"])
        fc = d["data"][0]["value_classification"]
        val = f"Fear&Greed: {fg}/100 ({fc})"
        if fg <= 20:   return "✅", val, "خوف شديد = فرصة شراء", True, False
        elif fg <= 40: return "🟡", val, "خوف = سوق ضعيف", True, False
        elif fg >= 80: return "🔴", val, "جشع شديد = احذر الذروة", False, True
        elif fg >= 60: return "🟡", val, "جشع = احذر", False, False
        else:          return "⚪", val, "محايد", False, False
    except Exception:
        try:
            r2 = session.get("https://api.coingecko.com/api/v3/global",
                             timeout=(5,10))
            dom = r2.json().get("data",{}).get("market_cap_percentage",{}).get("btc",50)
            val2 = f"BTC Dom: {dom:.1f}%"
            if dom > 55:   return "🔴", val2, "هيمنة BTC عالية", False, True
            elif dom < 45: return "✅", val2, "Altcoin Season", True, False
            else:          return "⚪", val2, "سوق متوازن", False, False
        except Exception:
            return "⚪", "Sentiment: N/A", "", False, False

def detect_patterns(df):
    """كشف أنماط الشموع على آخر 3 شموع."""
    if df is None or len(df) < 3:
        return [], []

    bulls, bears = [], []

    o0 = float(df["o"].iloc[-1]); h0 = float(df["h"].iloc[-1])
    l0 = float(df["l"].iloc[-1]); c0 = float(df["c"].iloc[-1])
    o1 = float(df["o"].iloc[-2]); h1 = float(df["h"].iloc[-2])
    l1 = float(df["l"].iloc[-2]); c1 = float(df["c"].iloc[-2])
    o2 = float(df["o"].iloc[-3]); h2 = float(df["h"].iloc[-3])
    l2 = float(df["l"].iloc[-3]); c2 = float(df["c"].iloc[-3])

    body0 = abs(c0 - o0) or 1e-9
    body1 = abs(c1 - o1) or 1e-9
    rng0  = (h0 - l0) or 1e-9
    rng1  = (h1 - l1) or 1e-9
    uw0   = h0 - max(o0, c0)
    lw0   = min(o0, c0) - l0

    bull0 = c0 > o0; bear0 = c0 < o0
    bull1 = c1 > o1; bear1 = c1 < o1
    bull2 = c2 > o2; bear2 = c2 < o2

    mid_body = abs(c1 - o1)
    mid_rng  = (h1 - l1) or 1e-9

    # ── Bullish ──
    if bear1 and bull0 and o0 <= c1 and c0 >= o1:
        bulls.append("Bullish Engulfing")
    if lw0 > body0 * 2 and uw0 < body0 * 0.5 and body0 / rng0 < 0.4:
        bulls.append("Hammer")
    if lw0 > rng0 * 0.65 and body0 < rng0 * 0.15:
        bulls.append("Dragonfly Doji")
    if bear1 and mid_body < mid_rng * 0.35 and bull0 and c0 > (o2+c2)/2:
        bulls.append("Morning Star")
    if bull0 and bull1 and bull2 and c0>c1 and c1>c2 and o0>o1 and o1>o2:
        bulls.append("3 جنود بيضاء")

    # ── Bearish ──
    if bull1 and bear0 and o0 >= c1 and c0 <= o1:
        bears.append("Bearish Engulfing")
    uw0b = h0 - max(o0, c0)
    lw0b = min(o0, c0) - l0
    if uw0b > body0 * 2 and lw0b < body0 * 0.5 and body0 / rng0 < 0.4:
        bears.append("Shooting Star")
    if uw0b > rng0 * 0.65 and body0 < rng0 * 0.15:
        bears.append("Gravestone Doji")
    if bull1 and mid_body < mid_rng * 0.35 and bear0 and c0 < (o2+c2)/2:
        bears.append("Evening Star")
    if bear0 and bear1 and bear2 and c0<c1 and c1<c2 and o0<o1 and o1<o2:
        bears.append("3 غربان سوداء")

    return bulls, bears


# ══════════════════════════════════════════
# ICT Smart Money للكريبتو
# ══════════════════════════════════════════

def find_ob_crypto(df, lookback=20):
    """Order Blocks للكريبتو — مناطق تجمع المؤسسات."""
    if df is None or len(df) < lookback:
        return [], []
    bull_obs = []; bear_obs = []
    c = df["c"].values; h = df["h"].values
    l = df["l"].values; o = df["o"].values
    for i in range(2, min(lookback, len(df)-2)):
        idx = -(i+2)
        if o[idx] > c[idx]:  # هابطة
            if c[idx+1] > o[idx+1] and c[idx+2] > o[idx+2]:
                ob_h = max(o[idx], c[idx]); ob_l = min(o[idx], c[idx])
                if ob_h > ob_l:
                    bull_obs.append({"h":round(float(ob_h),6),"l":round(float(ob_l),6),
                                     "mid":round((ob_h+ob_l)/2,6),"age":i})
        if c[idx] > o[idx]:  # صاعدة
            if c[idx+1] < o[idx+1] and c[idx+2] < o[idx+2]:
                ob_h = max(o[idx], c[idx]); ob_l = min(o[idx], c[idx])
                if ob_h > ob_l:
                    bear_obs.append({"h":round(float(ob_h),6),"l":round(float(ob_l),6),
                                     "mid":round((ob_h+ob_l)/2,6),"age":i})
    price = c[-1]
    bull_obs = sorted([x for x in bull_obs if x["h"] < price],
                      key=lambda x: abs(price-x["mid"]))[:2]
    bear_obs = sorted([x for x in bear_obs if x["l"] > price],
                      key=lambda x: abs(price-x["mid"]))[:2]
    return bull_obs, bear_obs


def find_fvg_crypto(df, lookback=12):
    """Fair Value Gap للكريبتو."""
    if df is None or len(df) < 3:
        return [], []
    bull_fvgs = []; bear_fvgs = []
    price = float(df["c"].iloc[-1])
    for i in range(2, min(lookback+2, len(df))):
        idx = -i
        h0 = float(df["h"].iloc[idx-2]); l0 = float(df["l"].iloc[idx-2])
        h2 = float(df["h"].iloc[idx]);   l2 = float(df["l"].iloc[idx])
        if h0 < l2 and l2 - h0 > 0:
            bull_fvgs.append({"h":round(l2,6),"l":round(h0,6),"mid":round((l2+h0)/2,6)})
        if l0 > h2 and l0 - h2 > 0:
            bear_fvgs.append({"h":round(l0,6),"l":round(h2,6),"mid":round((l0+h2)/2,6)})
    bull_fvgs = sorted([f for f in bull_fvgs if f["h"] < price],
                       key=lambda x: abs(price-x["mid"]))[:2]
    bear_fvgs = sorted([f for f in bear_fvgs if f["l"] > price],
                       key=lambda x: abs(price-x["mid"]))[:2]
    return bull_fvgs, bear_fvgs


def find_liquidity_crypto(df, lookback=25):
    """مناطق السيولة للكريبتو — BSL فوق، SSL تحت."""
    if df is None or len(df) < lookback:
        return [], []
    h = df["h"].values[-lookback:]; l = df["l"].values[-lookback:]
    price = float(df["c"].iloc[-1])
    bsl = [round(float(h[i]),6) for i in range(1,len(h)-1)
           if h[i]>h[i-1] and h[i]>h[i+1] and h[i]>price]
    ssl = [round(float(l[i]),6) for i in range(1,len(l)-1)
           if l[i]<l[i-1] and l[i]<l[i+1] and l[i]<price]
    return sorted(set(bsl))[:3], sorted(set(ssl),reverse=True)[:3]


def detect_sweep_crypto(df, lookback=20):
    """كشف Liquidity Sweep للكريبتو."""
    if df is None or len(df) < lookback:
        return None
    h = df["h"].values[-lookback:]; l = df["l"].values[-lookback:]
    c = df["c"].values[-lookback:]; o = df["o"].values[-lookback:]
    price = c[-1]; prev_low = min(l[-10:-1]); prev_high = max(h[-10:-1])
    body = abs(c[-1]-o[-1]); rng = h[-1]-l[-1] or 1e-9
    impulse = body/rng*100
    if l[-1] < prev_low and c[-1] > prev_low:
        return {"type":"BULLISH SWEEP","action":"LONG",
                "level":round(float(prev_low),6),
                "impulse":round(impulse,1),
                "conf":"عالية" if impulse>60 else "متوسطة"}
    if h[-1] > prev_high and c[-1] < prev_high:
        return {"type":"BEARISH SWEEP","action":"SHORT",
                "level":round(float(prev_high),6),
                "impulse":round(impulse,1),
                "conf":"عالية" if impulse>60 else "متوسطة"}
    return None


def detect_bos_crypto(df, lookback=25):
    """BOS/CHOCH للكريبتو — تحليل الاتجاه العام."""
    if df is None or len(df) < lookback:
        return "محايد", "محايد"
    c = df["c"].values[-lookback:]
    h = df["h"].values[-lookback:]
    l = df["l"].values[-lookback:]

    # اتجاه EMA
    close_s = pd.Series(c)
    ema20 = close_s.ewm(span=20, adjust=False).mean().iloc[-1]
    ema7  = close_s.ewm(span=7,  adjust=False).mean().iloc[-1]
    price = c[-1]

    # مقارنة نصفين: النصف الأول vs النصف الثاني
    mid = lookback // 2
    avg_first  = float(close_s.iloc[:mid].mean())
    avg_second = float(close_s.iloc[mid:].mean())

    # أعلى قمة وأدنى قاع في النصف الثاني
    recent_high = max(h[-8:])
    recent_low  = min(l[-8:])
    prev_high   = max(h[:-8])
    prev_low    = min(l[:-8])

    # BOS صاعد: قمم جديدة + سعر فوق EMA
    if recent_high > prev_high and price > ema20:
        return "BOS ▲", "صاعد"
    # BOS هابط: قيعان جديدة + سعر تحت EMA
    if recent_low < prev_low and price < ema20:
        return "BOS ▼", "هابط"
    # CHOCH: تغيير محتمل
    if avg_second > avg_first and price > ema7:
        return "CHOCH ▲?", "صاعد محتمل"
    if avg_second < avg_first and price < ema7:
        return "CHOCH ▼?", "هابط محتمل"
    return "محايد", "محايد"


def calc_rsi_crypto(df, period=14):
    """RSI للكريبتو."""
    if df is None or len(df) < period+1:
        return 50
    close = df["c"].astype(float)
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def calc_atr_crypto(df, period=14):
    """ATR للكريبتو."""
    if df is None or len(df) < period+1:
        return 0
    h = df["h"].astype(float); l = df["l"].astype(float)
    c = df["c"].astype(float)
    tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def fp_crypto(v, d=4):
    """تنسيق سعر."""
    if v is None: return "—"
    if abs(v) >= 10000: return f"{v:,.2f}"
    if abs(v) >= 1:     return f"{v:.{d}f}"
    return f"{v:.6f}"


def analyze_ict_crypto(sym, df_1h, df_4h, df_15m, price):
    """
    تحليل ICT كامل للكريبتو:
    Order Blocks + FVG + Liquidity + Sweep + BOS + RSI + ATR
    يعيد dict نتائج.
    """
    result = {"bull":0,"bear":0,"sigs":[],"sl":None,"tp1":None,"tp2":None,"tp3":None}

    # استخدم أفضل فريم متاح
    df = df_1h if df_1h is not None and len(df_1h)>5 else (df_4h if df_4h is not None and len(df_4h)>5 else df_15m)
    if df is None or len(df) < 15:
        return result

    # BOS
    bos, bias = detect_bos_crypto(df_4h if df_4h is not None and len(df_4h)>5 else df, 25)
    result["bos"] = bos; result["bias"] = bias
    if "صاعد" in bias: result["bull"] += 2
    elif "هابط" in bias: result["bear"] += 2

    # Order Blocks
    bull_obs, bear_obs = find_ob_crypto(df, 20)
    result["bull_obs"] = bull_obs; result["bear_obs"] = bear_obs
    if bull_obs and abs(price - bull_obs[0]["mid"])/price < 0.005:
        result["bull"] += 2; result["sigs"].append("قرب Bullish OB")
    if bear_obs and abs(price - bear_obs[0]["mid"])/price < 0.005:
        result["bear"] += 2; result["sigs"].append("قرب Bearish OB")

    # FVG
    bull_fvg, bear_fvg = find_fvg_crypto(df, 12)
    result["bull_fvg"] = bull_fvg; result["bear_fvg"] = bear_fvg
    if bull_fvg and abs(price - bull_fvg[0]["mid"])/price < 0.005:
        result["bull"] += 2; result["sigs"].append("داخل Bullish FVG")
    if bear_fvg:
        # إذا السعر أقل من Bear FVG أو داخله = ضغط هابط
        if price <= bear_fvg[0]["h"] and price >= bear_fvg[0]["l"]:
            result["bear"] += 3; result["sigs"].append("داخل Bear FVG (ضغط هابط)")
        elif abs(price - bear_fvg[0]["mid"])/price < 0.005:
            result["bear"] += 2; result["sigs"].append("قرب Bear FVG")

    # Liquidity
    bsl, ssl = find_liquidity_crypto(df, 25)
    result["bsl"] = bsl; result["ssl"] = ssl

    # Sweep
    sweep = detect_sweep_crypto(df_15m if df_15m is not None and len(df_15m)>5 else df, 20)
    result["sweep"] = sweep
    if sweep:
        if sweep["action"]=="LONG":  result["bull"] += 3; result["sigs"].append("Bullish Sweep")
        elif sweep["action"]=="SHORT": result["bear"] += 3; result["sigs"].append("Bearish Sweep")

    # RSI
    rsi = calc_rsi_crypto(df)
    result["rsi"] = rsi
    if rsi < 35: result["bull"] += 1; result["sigs"].append(f"RSI={rsi:.0f} ذروة بيع")
    elif rsi > 65: result["bear"] += 1; result["sigs"].append(f"RSI={rsi:.0f} ذروة شراء")

    # ATR للـ SL/TP
    atr = calc_atr_crypto(df)
    result["atr"] = atr
    if atr > 0:
        # تأكد ATR منطقي (أقل من 10% من السعر)
        atr_safe = min(atr, price * 0.05)
        if result["bull"] > result["bear"]:
            result["sl"]  = round(price - 1.5*atr_safe, 6)
            result["tp1"] = round(price + 1.5*atr_safe, 6)
            result["tp2"] = round(price + 3.0*atr_safe, 6)
            # TP3 = أقرب BSL أو 2xATR
            result["tp3"] = bsl[0] if bsl and bsl[0] < price*1.15 else round(price + 4.5*atr_safe, 6)
        elif result["bear"] > result["bull"]:
            result["sl"]  = round(price + 1.5*atr_safe, 6)
            result["tp1"] = round(price - 1.5*atr_safe, 6)
            result["tp2"] = round(price - 3.0*atr_safe, 6)
            result["tp3"] = ssl[0] if ssl and ssl[0] > price*0.85 else round(price - 4.5*atr_safe, 6)

    return result


def build_ict_section(ict, price):
    """بناء قسم ICT في رسالة التليقرام."""
    if not ict:
        return ""
    if "err" in ict:
        return f"ICT Error: {ict['err']}\n"
    msg = ""

    bos  = ict.get("bos", "-")
    bias = ict.get("bias", "-")
    msg += "*BOS/CHOCH:* `" + bos + "` - " + bias + "\n\n"

    for ob in ict.get("bull_obs",[])[:2]:
        msg += "Bullish OB: `" + fp_crypto(ob["l"]) + "`-`" + fp_crypto(ob["h"]) + "`\n"

    for ob in ict.get("bear_obs",[])[:2]:
        msg += "Bearish OB: `" + fp_crypto(ob["l"]) + "`-`" + fp_crypto(ob["h"]) + "`\n"

    for fvg in ict.get("bull_fvg",[])[:1]:
        msg += "Bull FVG: `" + fp_crypto(fvg["l"]) + "`-`" + fp_crypto(fvg["h"]) + "`\n"

    for fvg in ict.get("bear_fvg",[])[:1]:
        msg += "Bear FVG: `" + fp_crypto(fvg["l"]) + "`-`" + fp_crypto(fvg["h"]) + "`\n"

    bsl = ict.get("bsl",[])
    ssl = ict.get("ssl",[])
    if bsl:
        msg += "BSL (فوق): " + " | ".join(["`"+fp_crypto(x)+"`" for x in bsl[:3]]) + "\n"
    if ssl:
        msg += "SSL (تحت): " + " | ".join(["`"+fp_crypto(x)+"`" for x in ssl[:3]]) + "\n"

    sweep = ict.get("sweep")
    if sweep:
        msg += "Sweep: " + sweep["type"] + " | " + fp_crypto(sweep["level"]) + "\n"

    if ict.get("sl") and ict.get("tp1"):
        action = "LONG" if ict.get("bull",0) > ict.get("bear",0) else "SHORT"
        msg += "---\n"
        msg += "ICT Entry (" + action + "):\n"
        msg += "  دخول: `" + fp_crypto(price) + "`\n"
        msg += f"  SL:  `{fp_crypto(ict['sl'])}`\n"
        msg += f"  TP1: `{fp_crypto(ict['tp1'])}` (1:1)\n"
        msg += f"  TP2: `{fp_crypto(ict['tp2'])}` (1:2)\n"
        msg += f"  TP3: `{fp_crypto(ict['tp3'])}` (سيولة)\n"
        msg += f"  ATR: `{fp_crypto(ict.get('atr',0))}`\n"
        rr_risk = abs(price - ict["sl"]) if ict.get("sl") else 0
        rr_val  = abs(ict["tp1"] - price) / rr_risk if rr_risk > 0 else 0
        msg += f"  RR:   1:{rr_val:.1f}\n"

    return msg + "\n"
def analyze_mtf(sym):
    """تحليل 4 فريمات زمنية."""
    frames = [("15m","15m",30), ("1h","1h",30), ("4h","4h",20), ("1d","1d",15)]
    results = []
    bull_count = bear_count = 0

    for label, interval, limit in frames:
        try:
            df = fetch_tf(sym, interval, limit)
            b, r = detect_patterns(df)
            if b and len(b) >= len(r):
                results.append((label, "✅", b[0]))
                bull_count += 1
            elif r and len(r) > len(b):
                results.append((label, "🔴", r[0]))
                bear_count += 1
            else:
                results.append((label, "⚪", "محايد"))
        except Exception:
            results.append((label, "❓", "خطأ"))

    return results, bull_count, bear_count


# ==================================================
# التحليل الرئيسي
# ==================================================

def analyze(sym):
    R = {"sym": sym, "sigs": [], "sl": 0, "ss": 0,
         "warn": [], "err": None}
    try:
        data  = fetch_binance(sym)
        price = data["price"]
        rate  = data["rate"]
        df    = data["df"]
        R["price"] = price
        R["rate"]  = rate

        # ─── 1. Funding Rate ───
        if rate <= -0.05:
            R["sl"] += 1
            R["sigs"].append(("1","Funding Rate","✅",
                f"{rate:.4f}%","شورتات تدفع للونجات"))
            if rate <= -0.3:
                R["warn"].append(f"⚠️ Funding {rate:.3f}% — رافعة x2 فقط")
        elif rate >= 0.1:
            R["ss"] += 1
            R["sigs"].append(("1","Funding Rate","🔴",
                f"{rate:.4f}%","لونجات تدفع للشورتات"))
        else:
            R["sigs"].append(("1","Funding Rate","⚪",
                f"{rate:.4f}%","متوازن"))

        # ─── ICT Smart Money Analysis ───
        try:
            # df موجود من fetch_binance (1h) — نجلب 15m و 4h إضافية
            df_15m = fetch_tf(sym, "15m", 40)
            df_4h  = fetch_tf(sym, "4h",  25)
            # نحول أعمدة Binance لأعمدة ICT
            # Binance df already has columns: o,h,l,c,v,qv,bq
            # ICT functions use: df["c"], df["h"], df["l"], df["o"] - direct match
            ict = analyze_ict_crypto(sym, df,
                df_4h if df_4h is not None and len(df_4h)>5 else df,
                df_15m if df_15m is not None and len(df_15m)>5 else df,
                price)
            R["ict"] = ict
            # أضف نقاط ICT للقرار
            if ict.get("bull",0) >= 3: R["sl"] += 1
            if ict.get("bear",0) >= 3: R["ss"] += 1
            if ict.get("sweep"):
                sw = ict["sweep"]
                if sw["action"]=="LONG":  R["sl"] += 1
                elif sw["action"]=="SHORT": R["ss"] += 1
        except Exception as _e:
            R["ict"] = {"err": str(_e)[:60]}
            R["sigs"].append(("0","ICT","❓",f"خطأ ICT: {str(_e)[:40]}",""))

        # ─── 2. Open Interest ───
        oi = data["oi_chg"]
        if oi is not None and df is not None:
            pc = df["c"].iloc[-1] - df["c"].iloc[-3]
            if oi > 3 and pc > 0:
                R["sl"] += 1
                R["sigs"].append(("2","Open Interest","✅",
                    f"+{oi:.1f}%","أموال جديدة تدخل"))
            elif oi < -3 and pc < 0:
                R["ss"] += 1
                R["sigs"].append(("2","Open Interest","🔴",
                    f"{oi:.1f}%","بيع حقيقي"))
            elif oi > 3 and pc < 0:
                R["ss"] += 1
                R["sigs"].append(("2","Open Interest","🔴",
                    f"+{oi:.1f}%","مراكز بيع جديدة"))
            else:
                R["sigs"].append(("2","Open Interest","⚪",
                    f"{oi:+.1f}%","محايد"))
        else:
            R["sigs"].append(("2","Open Interest","❓","غير متاح",""))

        # ─── 3. Long/Short Ratio ───
        lp = data["ls_long"]
        sp = data["ls_short"]
        if lp is not None:
            if sp >= 60:
                R["sl"] += 1
                R["sigs"].append(("3","Long/Short","✅",
                    f"ش {sp:.1f}% | ل {lp:.1f}%","Squeeze محتمل"))
            elif lp >= 65:
                R["ss"] += 1
                R["sigs"].append(("3","Long/Short","🔴",
                    f"ل {lp:.1f}% | ش {sp:.1f}%","خطر تصحيح"))
            else:
                R["sigs"].append(("3","Long/Short","⚪",
                    f"ل {lp:.0f}% | ش {sp:.0f}%","متوازن"))
        else:
            R["sigs"].append(("3","Long/Short","❓","غير متاح",""))

        # ─── 4. EMA + Volume ───
        if df is not None:
            e7  = df["c"].ewm(span=7,  adjust=False).mean().iloc[-1]
            e21 = df["c"].ewm(span=21, adjust=False).mean().iloc[-1]
            vr  = df["v"].iloc[-1] / max(df["v"].iloc[-20:].mean(), 0.001)
            cn  = "🟢" if df["c"].iloc[-1] > df["o"].iloc[-1] else "🔴"
            if price > e7 and price > e21:
                R["sl"] += 1
                R["sigs"].append(("4","EMA + حجم","✅",
                    f"فوق EMA7({e7:.4f}) و EMA21({e21:.4f})",
                    f"شمعة {cn} | حجم {vr:.1f}x"))
            elif price < e7 and price < e21:
                R["ss"] += 1
                R["sigs"].append(("4","EMA + حجم","🔴",
                    f"تحت EMA7({e7:.4f}) و EMA21({e21:.4f})",
                    f"شمعة {cn} | حجم {vr:.1f}x"))
            else:
                R["sigs"].append(("4","EMA + حجم","⚪",
                    f"بين EMA7({e7:.4f}) و EMA21({e21:.4f})",""))
        else:
            R["sigs"].append(("4","EMA + حجم","❓","غير متاح",""))

        # ─── 5. Liquidations ───
        ll  = data["liq_l"]
        ls  = data["liq_s"]
        tot = ll + ls
        if ls > ll * 2 and tot > 100:
            R["sl"] += 1
            R["sigs"].append(("5","Liquidations","✅",
                f"ش ${ls:,.0f} | ل ${ll:,.0f}","Short Squeeze"))
        elif ll > ls * 2 and tot > 100:
            R["ss"] += 1
            R["sigs"].append(("5","Liquidations","🔴",
                f"ل ${ll:,.0f} | ش ${ls:,.0f}","تصفية لونجات"))
        else:
            R["sigs"].append(("5","Liquidations","⚪",
                f"${tot:,.0f}","متوازن"))

        # ─── 6. CVD ───
        if df is not None:
            try:
                d2         = df.copy()
                d2["dlta"] = d2["bq"] - (d2["qv"] - d2["bq"])
                d2["cvd"]  = d2["dlta"].cumsum()
                cn2 = d2["cvd"].iloc[-1]
                cp2 = d2["cvd"].iloc[-6]
                pd2 = df["c"].iloc[-1] - df["c"].iloc[-6]
                if cn2 > cp2 and pd2 > 0:
                    R["sl"] += 1
                    R["sigs"].append(("6","CVD","✅",
                        f"{cn2:,.0f}","شراء حقيقي"))
                elif cn2 < cp2 and pd2 < 0:
                    R["ss"] += 1
                    R["sigs"].append(("6","CVD","🔴",
                        f"{cn2:,.0f}","بيع حقيقي"))
                elif cn2 < cp2 and pd2 > 0:
                    R["ss"] += 1
                    R["sigs"].append(("6","CVD","🔴",
                        f"{cn2:,.0f}","ارتفاع وهمي"))
                else:
                    R["sigs"].append(("6","CVD","⚪",
                        f"{cn2:,.0f}","محايد"))
            except Exception:
                R["sigs"].append(("6","CVD","❓","غير متاح",""))
        else:
            R["sigs"].append(("6","CVD","❓","غير متاح",""))

        # ─── 7. On-Chain (Etherscan Gas Oracle) ───
        oc_icon, oc_val, oc_note, oc_bull, oc_bear = fetch_onchain(sym)
        if oc_bull:
            R["sl"] += 1
        elif oc_bear:
            R["ss"] += 1
        R["sigs"].append(("7","On-Chain ⛓",oc_icon,oc_val,oc_note))

        # ─── 8. Candlestick Patterns MTF ───
        try:
            tf_res, bt, brt = analyze_mtf(sym)
            tf_line = " | ".join(f"{lb}:{ic}" for lb,ic,_ in tf_res)
            pats    = [p for _,ic,p in tf_res if ic in ("✅","🔴") and p != "محايد"]
            pat_str = " / ".join(pats) if pats else "لا أنماط"

            if bt >= 3:
                R["sl"] += 1
                R["sigs"].append(("8","شموع MTF","✅",
                    tf_line, f"{bt}/4 فريمات صاعدة — {pat_str}"))
            elif brt >= 3:
                R["ss"] += 1
                R["sigs"].append(("8","شموع MTF","🔴",
                    tf_line, f"{brt}/4 فريمات هابطة — {pat_str}"))
            elif bt == 2 and brt == 0:
                R["sigs"].append(("8","شموع MTF","🟡",
                    tf_line, f"صاعد ضعيف — {pat_str}"))
            elif brt == 2 and bt == 0:
                R["sigs"].append(("8","شموع MTF","🟡",
                    tf_line, f"هابط ضعيف — {pat_str}"))
            else:
                R["sigs"].append(("8","شموع MTF","⚪",tf_line,"محايد"))
        except Exception:
            R["sigs"].append(("8","شموع MTF","❓","خطأ في الجلب",""))

        # ─── القرار: 5 من 8 ───
        sl = R["sl"];  ss = R["ss"]
        no_short = (rate <= -0.05)

        # احسب ICT كعامل مساعد
        ict_data = R.get("ict", {})
        ict_bull = ict_data.get("bull", 0) if ict_data else 0
        ict_bear = ict_data.get("bear", 0) if ict_data else 0
        ict_bonus_l = 1 if ict_bull >= 4 else 0
        ict_bonus_s = 1 if ict_bear >= 4 else 0
        sl_total = sl + ict_bonus_l
        ss_total = ss + ict_bonus_s

        if sl_total >= 5:
            R["action"]   = "LONG"
            R["decision"] = "✅ ادخل LONG"
            R["conf"]     = f"{sl}/8 مؤشرات + ICT {'✅' if ict_bonus_l else ''}"
        elif ss_total >= 5 and not no_short:
            R["action"]   = "SHORT"
            R["decision"] = "🔴 ادخل SHORT"
            R["conf"]     = f"{ss}/8 مؤشرات + ICT {'✅' if ict_bonus_s else ''}"
        elif ss_total >= 5 and no_short:
            R["action"]   = "WAIT"
            R["decision"] = "⛔ لا تشورت — Funding سالب"
            R["conf"]     = "الشورت محظور"
        else:
            R["action"]   = "WAIT"
            R["decision"] = "⏳ انتظر — الشروط ناقصة"
            R["conf"]     = f"لونج {sl}/8 | شورت {ss}/8"

        # ─── SL / TP ───
        if df is not None:
            low  = df["l"].iloc[-20:].min()
            high = df["h"].iloc[-20:].max()
            if R["action"] == "LONG":
                slp  = low * 0.99
                risk = price - slp
                R["slp"] = slp
                R["tp1"] = price + risk
                R["tp2"] = price + risk * 2
            elif R["action"] == "SHORT":
                slp  = high * 1.01
                risk = slp - price
                R["slp"] = slp
                R["tp1"] = price - risk
                R["tp2"] = price - risk * 2
            else:
                R["slp"] = R["tp1"] = R["tp2"] = None
        else:
            R["slp"] = R["tp1"] = R["tp2"] = None

        # ─── الرافعة ───
        if abs(rate) > 0.3:
            R["lev"]  = "x2 فقط (تقلب شديد)"
            R["size"] = "1% من المحفظة"
        elif sym in ("BTCUSDT","ETHUSDT"):
            R["lev"]  = "x3 إلى x5"
            R["size"] = "3-5% من المحفظة"
        else:
            R["lev"]  = "x2 إلى x3"
            R["size"] = "2% من المحفظة"

    except Exception as e:
        R["err"] = f"❌ {str(e)[:120]}"

    return R




# ╔══════════════════════════════════════════════════════════════╗
# ║      AUTO SCANNER — ماسح ذكي بمؤشرات ICT + SMC            ║
# ║  المؤشرات:                                                   ║
# ║  ① المؤشرات الأساسية الـ 8 (من run_analysis)               ║
# ║  ② Order Block — مناطق القرار الكبرى                        ║
# ║  ③ Fair Value Gap (FVG) — فجوات السعر                      ║
# ║  ④ Smart Money — تتبع الأموال الذكية                        ║
# ║  ⑤ ICP — نقطة الانجذاب المثالية للسعر                      ║
# ╚══════════════════════════════════════════════════════════════╝

import time as _time_mod

# عملات مستبعدة
_SCAN_EXCLUDED = {
    "USDTUSDT","BUSDUSDT","USDCUSDT","DAIUSDT","TUSDUSDT",
    "FDUSDUSDT","WBTCUSDT","WETHUSDT","STETHUSDT",
}

# كاش قائمة العملات
_all_futures_cache: list = []
_cache_ts: float = 0

def get_all_futures_symbols() -> list:
    """جلب كل رموز Binance Futures USDT ديناميكياً."""
    global _all_futures_cache, _cache_ts
    import time as _t
    # تحديث كل ساعة
    if _all_futures_cache and (_t.time() - _cache_ts) < 3600:
        return _all_futures_cache
    try:
        for url in [
            f"{BASE}/fapi/v1/ticker/24hr",
            "https://fapi.binance.com/fapi/v1/ticker/24hr",
        ]:
            r = api_get(url, timeout=(12, 30))
            if r and r.status_code == 200:
                syms = []
                for t in r.json():
                    s = t.get("symbol","")
                    if s.endswith("USDT") and s not in _SCAN_EXCLUDED:
                        syms.append(s)
                if syms:
                    _all_futures_cache = sorted(syms)
                    _cache_ts = _t.time()
                    logging.warning(f"[SCAN_LIST] {len(syms)} عملة Futures")
                    return syms
    except Exception as e:
        logging.warning(f"[SCAN_LIST] {e}")
    # fallback
    return _all_futures_cache or ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT"]

DEFAULT_SCAN_LIST = []  # يُجلب ديناميكياً

scan_lists:   dict = {}
scan_alerted: dict = {}
SCAN_COOLDOWN = 7200


# ══════════════════════════════════════════════════════════════
# ICT / SMC FUNCTIONS
# ══════════════════════════════════════════════════════════════

def detect_order_blocks(df, lookback=50):
    """
    Order Block: آخر شمعة هابطة قبل حركة صاعدة قوية (Bullish OB)
    أو آخر شمعة صاعدة قبل حركة هابطة قوية (Bearish OB).
    """
    try:
        c = pd.to_numeric(df["c"], errors="coerce")
        o = pd.to_numeric(df["o"], errors="coerce")
        h = pd.to_numeric(df["h"], errors="coerce")
        l = pd.to_numeric(df["l"], errors="coerce")
        v = pd.to_numeric(df["v"], errors="coerce")
        price = float(c.iloc[-1])

        bull_obs = []  # Bullish Order Blocks
        bear_obs = []  # Bearish Order Blocks

        for i in range(2, min(lookback, len(df)-2)):
            idx = -(i+1)
            is_bear_candle = float(c.iloc[idx]) < float(o.iloc[idx])
            is_bull_candle = float(c.iloc[idx]) > float(o.iloc[idx])

            # حجم الحركة بعد الشمعة
            move_after = abs(float(c.iloc[idx+3]) - float(c.iloc[idx+1]))
            avg_move   = float(abs(c.diff()).iloc[-20:].mean())

            # Bullish OB: شمعة هابطة تليها حركة صاعدة قوية
            if is_bear_candle and move_after > avg_move * 1.5:
                if float(c.iloc[idx+3]) > float(c.iloc[idx]):
                    ob_top = max(float(o.iloc[idx]), float(c.iloc[idx]))
                    ob_bot = min(float(o.iloc[idx]), float(c.iloc[idx]))
                    bull_obs.append({
                        "top":    ob_top,
                        "bot":    ob_bot,
                        "vol":    float(v.iloc[idx]),
                        "age":    i,
                    })

            # Bearish OB: شمعة صاعدة تليها حركة هابطة قوية
            if is_bull_candle and move_after > avg_move * 1.5:
                if float(c.iloc[idx+3]) < float(c.iloc[idx]):
                    ob_top = max(float(o.iloc[idx]), float(c.iloc[idx]))
                    ob_bot = min(float(o.iloc[idx]), float(c.iloc[idx]))
                    bear_obs.append({
                        "top":    ob_top,
                        "bot":    ob_bot,
                        "vol":    float(v.iloc[idx]),
                        "age":    i,
                    })

        # هل السعر عند Order Block؟
        in_bull_ob = any(ob["bot"] <= price <= ob["top"] * 1.01 for ob in bull_obs[:3])
        in_bear_ob = any(ob["bot"] * 0.99 <= price <= ob["top"] for ob in bear_obs[:3])

        return {
            "bull_obs":   bull_obs[:3],
            "bear_obs":   bear_obs[:3],
            "in_bull_ob": in_bull_ob,
            "in_bear_ob": in_bear_ob,
            "price":      price,
        }
    except Exception as e:
        return {"bull_obs":[],"bear_obs":[],"in_bull_ob":False,"in_bear_ob":False,"price":0}


def detect_fvg(df, min_gap_pct=0.1):
    """
    Fair Value Gap (FVG): فجوة بين wick شمعة 1 وbody شمعة 3.
    Bullish FVG: low[i] > high[i-2] — فجوة صاعدة
    Bearish FVG: high[i] < low[i-2] — فجوة هابطة
    """
    try:
        h = pd.to_numeric(df["h"], errors="coerce")
        l = pd.to_numeric(df["l"], errors="coerce")
        c = pd.to_numeric(df["c"], errors="coerce")
        price = float(c.iloc[-1])

        bull_fvgs = []
        bear_fvgs = []

        for i in range(2, min(30, len(df)-1)):
            idx = -i
            # Bullish FVG: فجوة صاعدة
            fvg_low  = float(l.iloc[idx])
            fvg_high = float(h.iloc[idx-2])
            if fvg_low > fvg_high:
                gap_pct = (fvg_low - fvg_high) / fvg_high * 100
                if gap_pct >= min_gap_pct:
                    bull_fvgs.append({
                        "top":     fvg_low,
                        "bot":     fvg_high,
                        "gap_pct": gap_pct,
                        "age":     i,
                        "filled":  price <= fvg_low,  # هل السعر داخل الفجوة؟
                    })

            # Bearish FVG: فجوة هابطة
            fvg_high2 = float(h.iloc[idx])
            fvg_low2  = float(l.iloc[idx-2])
            if fvg_high2 < fvg_low2:
                gap_pct2 = (fvg_low2 - fvg_high2) / fvg_high2 * 100
                if gap_pct2 >= min_gap_pct:
                    bear_fvgs.append({
                        "top":     fvg_low2,
                        "bot":     fvg_high2,
                        "gap_pct": gap_pct2,
                        "age":     i,
                        "filled":  price >= fvg_high2,
                    })

        # هل السعر عند FVG غير مملوء؟
        at_bull_fvg = any(
            f["bot"] <= price <= f["top"] and not f["filled"]
            for f in bull_fvgs[:3]
        )
        at_bear_fvg = any(
            f["bot"] <= price <= f["top"] and not f["filled"]
            for f in bear_fvgs[:3]
        )

        return {
            "bull_fvgs":   bull_fvgs[:3],
            "bear_fvgs":   bear_fvgs[:3],
            "at_bull_fvg": at_bull_fvg,
            "at_bear_fvg": at_bear_fvg,
        }
    except Exception:
        return {"bull_fvgs":[],"bear_fvgs":[],"at_bull_fvg":False,"at_bear_fvg":False}


def detect_smart_money(df):
    """
    Smart Money Concepts:
    - BOS (Break of Structure): كسر هيكل السوق
    - CHoCH (Change of Character): تغيير طابع السوق
    - Sweep: اصطياد السيولة تحت القيعان أو فوق القمم
    """
    try:
        h = pd.to_numeric(df["h"], errors="coerce")
        l = pd.to_numeric(df["l"], errors="coerce")
        c = pd.to_numeric(df["c"], errors="coerce")
        price = float(c.iloc[-1])

        # آخر 20 شمعة لتحديد الهيكل
        recent_h = h.iloc[-20:]
        recent_l = l.iloc[-20:]

        # القمم والقيعان الهيكلية
        structure_high = float(recent_h.max())
        structure_low  = float(recent_l.min())
        prev_high      = float(h.iloc[-5:-1].max())
        prev_low       = float(l.iloc[-5:-1].min())

        signals = []
        score   = 0

        # BOS صاعد: السعر كسر أعلى هيكل
        if price > structure_high * 0.998:
            score += 3
            signals.append("🚀 BOS صاعد — كسر هيكل للأعلى")

        # BOS هابط: السعر كسر أدنى هيكل
        elif price < structure_low * 1.002:
            score -= 3
            signals.append("📉 BOS هابط — كسر هيكل للأسفل")

        # CHoCH: السعر كان هابطاً ثم كسر قمة سابقة
        if float(c.iloc[-3]) < float(c.iloc[-5]) and price > prev_high:
            score += 2
            signals.append("🔄 CHoCH صاعد — تغيير طابع السوق")
        elif float(c.iloc[-3]) > float(c.iloc[-5]) and price < prev_low:
            score -= 2
            signals.append("🔄 CHoCH هابط — تغيير طابع السوق")

        # Liquidity Sweep: اختراق قاع ثم ارتداد (Bull Sweep)
        if float(l.iloc[-2]) < structure_low and price > structure_low:
            score += 3
            signals.append("💎 Bull Sweep — اصطياد سيولة صاعد")

        # Liquidity Sweep: اختراق قمة ثم انعكاس (Bear Sweep)
        if float(h.iloc[-2]) > structure_high and price < structure_high:
            score -= 3
            signals.append("🐻 Bear Sweep — اصطياد سيولة هابط")

        return {
            "score":          score,
            "signals":        signals,
            "structure_high": structure_high,
            "structure_low":  structure_low,
            "bull":           score > 0,
            "bear":           score < 0,
        }
    except Exception:
        return {"score":0,"signals":[],"structure_high":0,"structure_low":0,"bull":False,"bear":False}


def detect_icp(df):
    """
    ICP — Ideal Continuation Point (نقطة الاستمرار المثالية):
    السعر يتراجع إلى 50% Fibonacci من آخر حركة كبيرة
    مع وجود Order Block أو FVG عند نفس المنطقة.
    """
    try:
        h = pd.to_numeric(df["h"], errors="coerce")
        l = pd.to_numeric(df["l"], errors="coerce")
        c = pd.to_numeric(df["c"], errors="coerce")
        price = float(c.iloc[-1])

        # آخر حركة كبيرة (أعلى قمة وأدنى قاع في 30 شمعة)
        high30 = float(h.iloc[-30:].max())
        low30  = float(l.iloc[-30:].min())
        range_ = high30 - low30

        if range_ <= 0:
            return {"at_bull_icp": False, "at_bear_icp": False, "signals": []}

        # مستويات Fibonacci
        fib_50  = low30  + range_ * 0.50
        fib_618 = low30  + range_ * 0.618
        fib_382 = low30  + range_ * 0.382

        tolerance = range_ * 0.03  # 3% tolerance

        signals = []
        at_bull_icp = False
        at_bear_icp = False

        # Bull ICP: السعر عند 50-61.8% Fib من حركة صاعدة
        if (float(c.iloc[-10]) > float(c.iloc[-20])):  # اتجاه صاعد
            if abs(price - fib_50) <= tolerance or abs(price - fib_618) <= tolerance:
                at_bull_icp = True
                fib_level = 50 if abs(price - fib_50) < abs(price - fib_618) else 61.8
                signals.append(f"⭐ ICP صاعد — عند Fib {fib_level}%")

        # Bear ICP: السعر عند 38.2-50% Fib من حركة هابطة
        if (float(c.iloc[-10]) < float(c.iloc[-20])):  # اتجاه هابط
            if abs(price - fib_382) <= tolerance or abs(price - fib_50) <= tolerance:
                at_bear_icp = True
                fib_level = 38.2 if abs(price - fib_382) < abs(price - fib_50) else 50
                signals.append(f"⭐ ICP هابط — عند Fib {fib_level}%")

        return {
            "at_bull_icp": at_bull_icp,
            "at_bear_icp": at_bear_icp,
            "fib_50":      round(fib_50, 6),
            "fib_618":     round(fib_618, 6),
            "fib_382":     round(fib_382, 6),
            "signals":     signals,
        }
    except Exception:
        return {"at_bull_icp":False,"at_bear_icp":False,"signals":[]}


def full_scan_analysis(sym: str) -> dict:
    """
    تحليل شامل يجمع:
    ① run_analysis الأساسي (8 مؤشرات)
    ② Order Block
    ③ Fair Value Gap
    ④ Smart Money (BOS/CHoCH/Sweep)
    ⑤ ICP (Fibonacci)
    """
    result = {
        "sym":          sym,
        "bull_total":   0,
        "bear_total":   0,
        "signals_bull": [],
        "signals_bear": [],
        "price":        0,
        "tp1":0,"tp2":0,"tp3":0,"sl":0,
        "error":        None,
    }

    # ① المؤشرات الأساسية
    try:
        base = run_analysis(sym)
        if base.get("err"):
            result["error"] = base["err"]
            return result

        result["price"] = base.get("price", 0)
        result["tp1"]   = base.get("tp1", 0)
        result["tp2"]   = base.get("tp2", 0)
        result["tp3"]   = base.get("tp3", 0)
        result["sl"]    = base.get("sl", 0)

        bull_base = base.get("bull", 0)
        bear_base = base.get("bear", 0)
        result["bull_total"] += bull_base
        result["bear_total"] += bear_base

        # استخرج الإشارات المهمة
        for sig in base.get("sigs", []):
            icon = sig[2] if len(sig) > 2 else ""
            name = sig[1] if len(sig) > 1 else ""
            val  = sig[3] if len(sig) > 3 else ""
            note = sig[4] if len(sig) > 4 else ""
            label = f"*{name}:* `{val}`" + (f" _{note}_" if note else "")
            if icon == "✅":
                result["signals_bull"].append(f"✅ {label}")
            elif icon == "🔴":
                result["signals_bear"].append(f"🔴 {label}")
    except Exception as e:
        result["error"] = str(e)[:80]
        return result

    # جلب شموع 1h للـ ICT
    df1h = fetch_tf(sym, "1h", 100)
    if df1h is None or len(df1h) < 30:
        return result

    # ② Order Block
    ob = detect_order_blocks(df1h)
    if ob["in_bull_ob"]:
        result["bull_total"] += 3
        result["signals_bull"].append("🟩 *Order Block:* سعر عند OB صاعد")
    if ob["in_bear_ob"]:
        result["bear_total"] += 3
        result["signals_bear"].append("🟥 *Order Block:* سعر عند OB هابط")

    # ③ Fair Value Gap
    fvg = detect_fvg(df1h)
    if fvg["at_bull_fvg"]:
        result["bull_total"] += 2
        result["signals_bull"].append("💹 *FVG:* فجوة سعر صاعدة غير مملوءة")
    if fvg["at_bear_fvg"]:
        result["bear_total"] += 2
        result["signals_bear"].append("🔻 *FVG:* فجوة سعر هابطة غير مملوءة")

    # ④ Smart Money
    smc = detect_smart_money(df1h)
    if smc["score"] > 0:
        result["bull_total"] += min(smc["score"], 4)
        for s in smc["signals"]:
            result["signals_bull"].append(f"💰 *SMC:* {s}")
    elif smc["score"] < 0:
        result["bear_total"] += min(abs(smc["score"]), 4)
        for s in smc["signals"]:
            result["signals_bear"].append(f"💰 *SMC:* {s}")

    # ⑤ ICP
    icp = detect_icp(df1h)
    if icp["at_bull_icp"]:
        result["bull_total"] += 3
        for s in icp["signals"]:
            result["signals_bull"].append(f"⭐ *ICP:* {s}")
    if icp["at_bear_icp"]:
        result["bear_total"] += 3
        for s in icp["signals"]:
            result["signals_bear"].append(f"⭐ *ICP:* {s}")

    return result


def build_scanner_alert(r: dict, direction: str) -> str:
    sym   = r["sym"]
    price = r["price"]
    bull  = r["bull_total"]
    bear  = r["bear_total"]
    tp1   = r["tp1"]; tp2=r["tp2"]; tp3=r["tp3"]; sl=r["sl"]
    _tz3  = timezone(timedelta(hours=3))
    now   = datetime.now(_tz3).strftime("%H:%M:%S %d/%m/%Y")
    total = bull + bear or 1

    if direction == "BUY":
        sigs   = r["signals_bull"]
        header = "🟢 إشارة شراء — مؤشرات مجتمعة"
        pct    = bull/total*100
        score  = bull
    else:
        sigs   = r["signals_bear"]
        header = "🔴 إشارة بيع — مؤشرات مجتمعة"
        pct    = bear/total*100
        score  = bear

    bar = "█"*int(pct/10) + "░"*(10-int(pct/10))
    m   = f"🎯 *{header}*\n"
    m  += f"🪙 *{sym}* | 🕐 {now}\n"
    m  += "━━━━━━━━━━━━━━━━━━━━\n\n"
    m  += f"💰 السعر: `${fmt(price)}`\n"
    m  += f"📊 نقاط {'صاعدة' if direction=='BUY' else 'هابطة'}: `{score}`\n"
    m  += f"`{bar}` {pct:.0f}%\n\n"
    m  += "📡 *المؤشرات المجتمعة:*\n"
    for s in sigs[:8]:
        m += f"  {s}\n"
    m += "\n"
    if sl and tp1:
        m += "━━━━━━━━━━━━━━━━━━━━\n"
        m += f"🟢 دخول: `${fmt(price)}`\n"
        m += f"🔴 SL:   `${fmt(sl)}`\n"
        m += f"💰 TP1:  `${fmt(tp1)}`\n"
        m += f"💰 TP2:  `${fmt(tp2)}`\n"
        m += f"🏆 TP3:  `${fmt(tp3)}`\n\n"
    m += "━━━━━━━━━━━━━━━━━━━━\n"
    m += "⚠️ _للأغراض التعليمية فقط_"
    return m


async def auto_scanner_job(ctx):
    """مسح تلقائي كل 30 دقيقة بكل المؤشرات."""
    chat_id   = ctx.job.data["chat_id"]
    min_score = ctx.job.data.get("min_score", 7)
    # جلب كل عملات Futures أو القائمة المخصصة
    custom = scan_lists.get(chat_id, [])
    sym_list = custom if custom else get_all_futures_symbols()
    now_ts    = _time_mod.time()
    found     = []

    for sym in sym_list:
        if now_ts - scan_alerted.get(chat_id,{}).get(sym,0) < SCAN_COOLDOWN:
            continue
        try:
            loop = asyncio.get_event_loop()
            r = await asyncio.wait_for(
                loop.run_in_executor(None, full_scan_analysis, sym),
                timeout=30)
            if r.get("error") or r.get("price",0) == 0:
                continue
            if r["bull_total"] >= min_score:
                found.append(("BUY",  sym, r["bull_total"], r))
            elif r["bear_total"] >= min_score:
                found.append(("SELL", sym, r["bear_total"], r))
        except: continue

    found.sort(key=lambda x: x[2], reverse=True)
    for direction, sym, score, r in found[:3]:
        scan_alerted.setdefault(chat_id,{})[sym] = now_ts
        msg = build_scanner_alert(r, direction)
        try:
            await ctx.bot.send_message(
                chat_id=chat_id, text=msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"📊 تحليل {sym[:-4]}", callback_data=f"r:{sym}"),
                    InlineKeyboardButton("⚡ سكالب", callback_data=f"s:{sym}"),
                ]]))
        except Exception as e:
            logging.warning(f"[SCANNER_SEND] {e}")


# ==================================================
# بناء الرسائل
# ==================================================

def fmt(v):
    """تنسيق السعر بعدد خانات مناسب."""
    if v >= 1000:  return f"{v:,.2f}"
    if v >= 1:     return f"{v:.4f}"
    return f"{v:.6f}"


def build_entry(R, alert=False):
    if R.get("err"):
        return R["err"]

    sym    = R["sym"]
    price  = R.get("price", 0)
    action = R.get("action", "WAIT")
    now    = datetime.now().strftime("%H:%M")
    icons  = {"LONG":"🟢 LONG","SHORT":"🔴 SHORT","WAIT":"⏳ انتظر"}
    hdr    = icons.get(action,"⏳")
    pre    = "🔔 *تنبيه تلقائي!*\n" if alert else ""

    m  = f"{pre}📊 *{sym}* — {hdr}\n"
    m += f"💰 `${fmt(price)}` | 🕐 {now}\n"
    m += "━━━━━━━━━━━━━━━━\n\n"
    m += "🔍 *المؤشرات الثمانية:*\n\n"

    for num,name,icon,val,note in sorted(R.get("sigs",[]), key=lambda x:x[0]):
        m += f"{icon} *{num}. {name}*\n"
        m += f"   `{val}`\n"
        if note:
            m += f"   _{note}_\n"
        m += "\n"

    m += "━━━━━━━━━━━━━━━━\n"
    m += f"📊 *النتيجة:* {R.get('conf','')}\n"
    m += f"⚡ *القرار:* {R.get('decision','')}\n\n"

    if action != "WAIT" and R.get("slp"):
        m += "━━━━━━━━━━━━━━━━\n"
        m += f"🟢 دخول:      `${fmt(price)}`\n"
        m += f"🔴 Stop Loss:  `${fmt(R['slp'])}`\n"
        m += f"💰 TP1 (1:1):  `${fmt(R['tp1'])}`\n"
        m += f"💰 TP2 (1:2):  `${fmt(R['tp2'])}`\n"
        m += f"🔧 الرافعة:   `{R['lev']}`\n"
        m += f"💼 الحجم:     `{R['size']}`\n\n"

    # ICT Section
    ict = R.get("ict")
    if ict is not None:
        ict_txt = build_ict_section(ict, R.get("price",0))
        if ict_txt and len(ict_txt) > 5:
            m += "━━━━━━━━━━━━━━━━\n"
            m += "*ICT Smart Money:*\n"
            m += ict_txt

    for w in R.get("warn",[]):
        m += f"{w}\n"

    m += "\n⚠️ _للأغراض التعليمية فقط_"
    return m


def build_exit(sym, price, exit_type, trade):
    now = datetime.now().strftime("%H:%M")
    p   = fmt(price)
    e   = fmt(trade["entry"])

    if exit_type == "SL":
        return (
            f"🚨 *STOP LOSS — {sym}*\n🕐 {now}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💰 السعر الحالي: `${p}`\n"
            f"🛑 SL عند:       `${fmt(trade['sl'])}`\n"
            f"📥 سعر الدخول:   `${e}`\n\n"
            f"📉 الصفقة أُغلقت — الخسارة محسوبة ✅\n\n"
            f"⚠️ _للأغراض التعليمية فقط_"
        )
    elif exit_type == "TP1":
        return (
            f"💰 *TP1 وصل — {sym}*\n🕐 {now}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"✅ السعر الحالي: `${p}`\n"
            f"🎯 TP1 عند:      `${fmt(trade['tp1'])}`\n"
            f"📥 سعر الدخول:   `${e}`\n\n"
            f"💡 *الخطوة التالية:*\n"
            f"   • أغلق 50% من المركز الآن\n"
            f"   • حرّك SL إلى سعر الدخول\n"
            f"   • انتظر TP2 بالـ 50% الباقية\n\n"
            f"⚠️ _للأغراض التعليمية فقط_"
        )
    elif exit_type == "TP2":
        return (
            f"🏆 *TP2 وصل — {sym}*\n🕐 {now}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"✅ السعر الحالي: `${p}`\n"
            f"🎯 TP2 عند:      `${fmt(trade['tp2'])}`\n"
            f"📥 سعر الدخول:   `${e}`\n\n"
            f"🎉 الهدف الكامل تحقق — أغلق كل المركز\n\n"
            f"⚠️ _للأغراض التعليمية فقط_"
        )
    elif exit_type == "REV":
        opp = "SHORT" if trade["action"] == "LONG" else "LONG"
        return (
            f"🔄 *انعكاس إشارة — {sym}*\n🕐 {now}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⚠️ الإشارات تحولت لـ *{opp}*\n"
            f"💰 السعر الحالي: `${p}`\n"
            f"📥 سعر الدخول:   `${e}`\n\n"
            f"💡 فكر في إغلاق مركز {trade['action']} الآن\n\n"
            f"⚠️ _للأغراض التعليمية فقط_"
        )
    return ""


def kb(sym):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 تحديث",  callback_data=f"r:{sym}"),
        InlineKeyboardButton("👁 تابع",   callback_data=f"w:{sym}"),
    ]])


# ==================================================
# Async
# ==================================================

async def run_analysis(sym):
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, analyze, sym), timeout=40)
    except asyncio.TimeoutError:
        return {"sym": sym, "err": "❌ انتهى الوقت — جرب مرة ثانية"}


# ==================================================
# Monitor Job — دخول + خروج تلقائي
# ==================================================

async def _run_monitor(bot, chat_id, sym):
    """wrapper لـ APScheduler"""
    try:
        R      = await run_analysis(sym)
        if R.get("err"): return
        price  = R["price"]
        action = R.get("action","WAIT")
        trade  = open_trades.get(chat_id, {}).get(sym)
        if trade:
            pass  # handled below
        elif action in ("LONG","SHORT"):
            msg = build_entry(R, alert=True)
            kb  = InlineKeyboardMarkup([[
                InlineKeyboardButton("تحديث", callback_data=f"u:{sym}"),
                InlineKeyboardButton("تابع",  callback_data=f"w:{sym}"),
            ]])
            await bot.send_message(chat_id=chat_id, text=msg,
                                   parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass


async def monitor_job(ctx):
    chat_id = ctx.job.data["chat_id"]
    sym     = ctx.job.data["sym"]
    try:
        R      = await run_analysis(sym)
        if R.get("err"):
            return

        price  = R["price"]
        action = R.get("action","WAIT")
        trade  = open_trades.get(chat_id, {}).get(sym)

        # ── صفقة مفتوحة — تحقق من الخروج ──
        if trade:
            t_act     = trade["action"]
            exit_type = None
            close     = False

            if t_act == "LONG":
                if price <= trade["sl"]:
                    exit_type, close = "SL", True
                elif not trade["tp1_hit"] and price >= trade["tp1"]:
                    exit_type = "TP1"
                    trade["tp1_hit"] = True
                elif trade["tp1_hit"] and price >= trade["tp2"]:
                    exit_type, close = "TP2", True
                elif action == "SHORT":
                    exit_type, close = "REV", True

            elif t_act == "SHORT":
                if price >= trade["sl"]:
                    exit_type, close = "SL", True
                elif not trade["tp1_hit"] and price <= trade["tp1"]:
                    exit_type = "TP1"
                    trade["tp1_hit"] = True
                elif trade["tp1_hit"] and price <= trade["tp2"]:
                    exit_type, close = "TP2", True
                elif action == "LONG":
                    exit_type, close = "REV", True

            if exit_type:
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=build_exit(sym, price, exit_type, trade),
                    parse_mode="Markdown")

            if close:
                open_trades.setdefault(chat_id, {}).pop(sym, None)

            return  # لا تفتح صفقة جديدة أثناء وجود صفقة مفتوحة

        # ── لا صفقة — تحقق من الدخول ──
        if action in ("LONG","SHORT"):
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=build_entry(R, alert=True),
                parse_mode="Markdown",
                reply_markup=kb(sym))

            if R.get("slp") and R.get("tp1") and R.get("tp2"):
                open_trades.setdefault(chat_id, {})[sym] = {
                    "action":   action,
                    "entry":    price,
                    "sl":       R["slp"],
                    "tp1":      R["tp1"],
                    "tp2":      R["tp2"],
                    "tp1_hit":  False,
                }

    except Exception:
        pass


# ==================================================
# Telegram Handlers
# ==================================================

async def cmd_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    eth_status = "✅ متصل" if ETHERSCAN_KEY not in ("YOUR_ETHERSCAN_KEY_HERE","NO_KEY","") else "❌ غير مفعّل"
    await u.message.reply_text(
        "👋 *MAHMOUD TRADING BOT v3*\n\n"
        "📊 *8 مؤشرات:*\n"
        "① Funding Rate | ② Open Interest\n"
        "③ Long/Short | ④ EMA + Volume\n"
        "⑤ Liquidations | ⑥ CVD\n"
        f"⑦ On-Chain (Etherscan) {eth_status}\n"
        "⑧ شموع MTF (15m|1h|4h|1d)\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📈 *تحليل فوري:*\n"
        "أرسل: `BTC` أو `ETH` أو `SOL` أو أي عملة\n\n"
        "👁 *متابعة تلقائية:*\n"
        "`تابع BTC` | `وقف BTC` | `وقف الكل`\n\n"
        "⚡ *Scalping (1m/5m):*\n"
        "`سكالب BTC` — تحليل فوري\n"
        "`تابع سكالب BTC` — تنبيه كل 5 دقائق\n"
        "`وقف سكالب BTC` — إيقاف\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔍 *الماسح الذكي (ICT/SMC):*\n"
        "`ماسح` — يفحص 30 عملة كل 30 دقيقة\n"
        "`ماسح 5` — أكثر إشارات (حد 5 نقاط)\n"
        "`ماسح 8` — أقوى فقط (حد 8 نقاط)\n"
        "`وقف ماسح` — إيقاف\n"
        "`قائمة الماسح` — العملات المراقبة\n"
        "`أضف ORCA` | `احذف ORCA`\n\n"
        "📋 *القائمة:* `قائمة`\n\n"
        "⚠️ _للأغراض التعليمية فقط_",
        parse_mode="Markdown")


async def handle_msg(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global _scheduler
    text    = u.message.text.strip()
    chat_id = u.effective_chat.id

    # ── تابع ──
    if text.startswith("تابع"):
        parts = text.split()
        if len(parts) < 2:
            await u.message.reply_text("مثال: `تابع BTC`", parse_mode="Markdown")
            return
        sym = parts[1].upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        try:
            watching.setdefault(chat_id, {})[sym] = True
            jn = f"w_{chat_id}_{sym}"
            if _scheduler and _scheduler.get_job(jn):
                _scheduler.remove_job(jn)
            if _scheduler:
                bot = c.bot
                _scheduler.add_job(
                    _run_monitor, "interval", seconds=900,
                    args=[bot, chat_id, sym],
                    id=jn, replace_existing=True)
        except Exception as _we:
            await u.message.reply_text(f"⚠️ خطأ: {str(_we)[:80]}")
            return
        # تحقق من وجود الرمز
        try:
            test_r = api_get(f"{BASE}/fapi/v1/premiumIndex", {"symbol": sym}, timeout=(3,6))
            if test_r.status_code != 200 or "markPrice" not in test_r.text:
                await u.message.reply_text(
                    sym + " غير متاح على Binance Futures\n"
                    "جرب: BTC | ETH | SOL | BNB",
                    parse_mode="Markdown")
                watching.get(chat_id, {}).pop(sym, None)
                return
        except Exception:
            pass

        await u.message.reply_text(
            f"👁 *بدأت متابعة {sym}*\n"
            f"كل 15 دقيقة\n"
            f"✅ تنبيه دخول: 5/8 إشارات\n"
            f"🔔 تنبيه خروج: SL | TP1 | TP2 | انعكاس\n"
            f"إيقاف: `وقف {sym[:-4]}`",
            parse_mode="Markdown")
        return

    # ── وقف ──
    if text.startswith("وقف"):
        parts = text.split()
        if len(parts) < 2:
            await u.message.reply_text("مثال: `وقف BTC`", parse_mode="Markdown")
            return
        if parts[1] == "الكل":
            for s in list(watching.get(chat_id, {}).keys()):
                if _scheduler and _scheduler.get_job(f"w_{chat_id}_{s}"):
                    _scheduler.remove_job(f"w_{chat_id}_{s}")
            watching[chat_id]    = {}
            open_trades[chat_id] = {}
            await u.message.reply_text("⛔ تم إيقاف كل المتابعات والصفقات")
        else:
            sym = parts[1].upper()
            if not sym.endswith("USDT"):
                sym += "USDT"
            if _scheduler and _scheduler.get_job(f"w_{chat_id}_{sym}"):
                _scheduler.remove_job(f"w_{chat_id}_{sym}")
            watching.get(chat_id, {}).pop(sym, None)
            open_trades.get(chat_id, {}).pop(sym, None)
            await u.message.reply_text(f"⛔ تم إيقاف {sym}")
        return

    # ── قائمة ──
    if text == "قائمة":
        syms = watching.get(chat_id, {})
        if not syms:
            await u.message.reply_text(
                "📋 لا توجد متابعات\n`تابع BTC` للبدء",
                parse_mode="Markdown")
        else:
            lines = []
            for s in syms:
                tr  = open_trades.get(chat_id, {}).get(s)
                tag = f"  🔴 {tr['action']} مفتوح" if tr else ""
                lines.append(f"👁 `{s}`{tag}")
            await u.message.reply_text(
                "📋 *تحت المتابعة:*\n\n" + "\n".join(lines),
                parse_mode="Markdown")
        return

    # ══ ماسح ICT/SMC ══
    if text.startswith("ماسح") or text.lower().startswith("scanner"):
        parts=text.split(); min_sc=7
        for p in parts:
            try:
                n=int(p)
                if 4<=n<=15: min_sc=n
            except: pass
        jn=f"ascan_{chat_id}"
        for j in c.job_queue.get_jobs_by_name(jn): j.schedule_removal()
        c.job_queue.run_repeating(auto_scanner_job,interval=1800,first=30,
            data={"chat_id":chat_id,"min_score":min_sc},name=jn)
        cnt=len(scan_lists.get(chat_id,DEFAULT_SCAN_LIST))
        await u.message.reply_text(
            f"🔍 *تم تفعيل الماسح الذكي*\n\n"
            f"⏱ يفحص كل 30 دقيقة\n"
            f"📊 يراقب {cnt} عملة\n"
            f"🎯 حد المؤشرات: ≥{min_sc} نقطة\n\n"
            f"*المؤشرات المستخدمة:*\n"
            f"① المؤشرات الأساسية (8 مؤشرات)\n"
            f"② Order Block (OB)\n"
            f"③ Fair Value Gap (FVG)\n"
            f"④ Smart Money (BOS/CHoCH/Sweep)\n"
            f"⑤ ICP — نقطة Fibonacci المثالية\n\n"
            f"`ماسح 5` — أكثر إشارات | `ماسح 10` — أقوى فقط\n"
            f"`وقف ماسح` — إيقاف | `أضف ORCA` — إضافة عملة",
            parse_mode="Markdown")
        return

    if text in ("وقف ماسح","stop scanner"):
        jn=f"ascan_{chat_id}"
        for j in c.job_queue.get_jobs_by_name(jn): j.schedule_removal()
        await u.message.reply_text("⛔ تم إيقاف الماسح الذكي"); return

    if text in ("قائمة الماسح","عملات الماسح"):
        lst=scan_lists.get(chat_id,[]) or get_all_futures_symbols()
        m2=f"📋 *عملات الماسح ({len(lst)}):*\n\n"
        m2+=" | ".join([f"`{s[:-4]}`" for s in lst])
        m2+="\n\n`أضف ORCA` أو `احذف ORCA`"
        await u.message.reply_text(m2,parse_mode="Markdown"); return

    if text.startswith("أضف ") or text.startswith("اضف "):
        raw=text.split(maxsplit=1)[1].upper()
        sym=raw if raw.endswith("USDT") else raw+"USDT"
        lst=scan_lists.setdefault(chat_id,list(DEFAULT_SCAN_LIST))
        if sym not in lst: lst.append(sym); await u.message.reply_text(f"✅ أضفت `{sym}`",parse_mode="Markdown")
        else: await u.message.reply_text(f"ℹ️ `{sym}` موجودة",parse_mode="Markdown")
        return

    if text.startswith("احذف ") or text.startswith("احزف "):
        raw=text.split(maxsplit=1)[1].upper()
        sym=raw if raw.endswith("USDT") else raw+"USDT"
        lst=scan_lists.setdefault(chat_id,list(DEFAULT_SCAN_LIST))
        if sym in lst: lst.remove(sym); await u.message.reply_text(f"✅ حذفت `{sym}`",parse_mode="Markdown")
        else: await u.message.reply_text(f"ℹ️ `{sym}` غير موجودة",parse_mode="Markdown")
        return

        # ── تحليل فوري ──
    if not text or len(text) > 15:
        await u.message.reply_text(
            "أرسل اسم العملة مثل: `BTC`", parse_mode="Markdown")
        return

    # بحث ذكي عن الرمز
    sym = resolve_sym(text)

    wait = await u.message.reply_text(
        f"⏳ جاري تحليل *{sym}*\n(8 مؤشرات + 4 فريمات شموع)...",
        parse_mode="Markdown")
    R = await run_analysis(sym)
    await wait.delete()
    await u.message.reply_text(
        build_entry(R), parse_mode="Markdown", reply_markup=kb(sym))


async def handle_btn(u: Update, c: ContextTypes.DEFAULT_TYPE):
    global _scheduler
    q       = u.callback_query
    chat_id = q.message.chat_id
    await q.answer()
    action, sym = q.data.split(":", 1)

    if action == "r":
        await q.edit_message_text(
            f"⏳ تحديث *{sym}*...", parse_mode="Markdown")
        R = await run_analysis(sym)
        await q.edit_message_text(
            build_entry(R), parse_mode="Markdown", reply_markup=kb(sym))

    elif action == "w":
        watching.setdefault(chat_id, {})[sym] = True
        jn = f"w_{chat_id}_{sym}"
        for j in c.job_queue.get_jobs_by_name(jn):
            j.schedule_removal()
        c.job_queue.run_repeating(
            monitor_job, interval=900, first=15,
            data={"chat_id": chat_id, "sym": sym}, name=jn)
        await q.answer(
            f"✅ بدأت متابعة {sym}\nدخول + خروج تلقائي",
            show_alert=True)


# ==================================================
# Error Handler
# ==================================================

async def error_handler(update, context):
    logging.warning(f"Bot error: {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ حدث خطأ مؤقت — حاول مرة ثانية")
    except Exception:
        pass


# ==================================================
# Run
# ==================================================

def main():
    if BOT_TOKEN in ("YOUR_BOT_TOKEN_HERE", ""):
        print("=" * 50)
        print("  ERROR: لم يتم إدخال Bot Token")
        print("  شغّل SETUP.py أولاً:")
        print("  python SETUP.py")
        print("=" * 50)
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_btn))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_msg))
    app.add_error_handler(error_handler)

    eth_status = "✅ Fear & Greed Index (مجاني)"

    print("=" * 55)
    print("  MAHMOUD TRADING BOT v3 — Running ✅")
    print("=" * 55)
    print(f"  المؤشرات : 8 مؤشرات")
    print(f"  الشموع   : 15m | 1h | 4h | 1d")
    print(f"  الأنماط  : 10 نمط صاعد وهابط")
    print(f"  Etherscan: {eth_status}")
    print(f"  الخروج   : SL / TP1 / TP2 / انعكاس")
    print(f"  الحد     : 5/8 إشارات للدخول")
    print("=" * 55)
    print("  أرسل /start على تيليقرام")
    print("=" * 55)

    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.start()

    app.run_polling(drop_pending_updates=True,
                    allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
