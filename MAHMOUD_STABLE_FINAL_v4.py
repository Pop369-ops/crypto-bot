"""
MAHMOUD TRADING BOT v4
======================
نظام إشارات متطور + نظام تتبع يدوي للصفقات

🎯 الإشارات (سلم وزني 0-15):
  1. ICT Smart Money (3pts)
  2. MTF Alignment 1h+4h+1d (2pts)
  3. MACD(12,26,9) (2pts)
  4. EMA Stack 20/50/200 (2pts)
  5. Funding Rate (1pt)
  6. Open Interest (1pt)
  7. RSI(14) (1pt)
  8. Long/Short Ratio (1pt)
  9. Liquidations (dynamic threshold) (1pt)
 10. CVD (1pt)
 + Bonus من الشموع MTF / On-Chain / Fear&Greed

🎮 نظام التتبع اليدوي:
  • صفقة LONG BTC 43500 42500 44500 45500 46500
  • مراقبة كل دقيقة + تنبيهات SL/TP/Reversal/Add
  • SQLite persistence — الصفقات تبقى بعد إعادة التشغيل

🛡 حماية المخاطر:
  • حد يومي / أسبوعي / صفقات مفتوحة / خسائر متتالية
  • Trade Journal (Win Rate / PF / Sharpe)

للأغراض التعليمية فقط
"""

import asyncio
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)

# ── موديولات v4 الجديدة ──
import MAHMOUD_DB as db
import MAHMOUD_SIGNALS as signals
import MAHMOUD_TRACKER as tracker
import MAHMOUD_RISK as risk

# ── موديولات v4 الموجة 1+2+3 ──
import MAHMOUD_NEWS as news_mod
import MAHMOUD_CALENDAR as cal_mod
import MAHMOUD_TODAY as today_mod
import MAHMOUD_AI as ai_mod
import MAHMOUD_WHALE as whale_mod
import MAHMOUD_BACKTEST as bt_mod
import MAHMOUD_LONGTERM as lt_mod

logging.basicConfig(level=logging.WARNING)

# ==================================================
# ضع التوكن هنا — أو شغّل SETUP.py تلقائياً
# ==================================================
import os as _os
BOT_TOKEN     = _os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE").strip()
ETHERSCAN_KEY = (_os.environ.get("ETHERSCAN_KEY", "").strip()
                 or _os.environ.get("ETHERSCAN_API_KEY", "").strip())
# ==================================================

BASE        = "https://fapi.binance.com"
ETH_API     = "https://api.etherscan.io/v2/api"  # V2 API (V1 deprecated Aug 2025)
ETH_CHAIN   = 1  # Ethereum Mainnet
watching    = {}
open_trades = {}  # {chat_id: {sym: {action,entry,sl,tp1,tp2,tp1_hit}}}

session = requests.Session()
adapter = requests.adapters.HTTPAdapter(max_retries=0)
session.mount("https://", adapter)
session.mount("http://",  adapter)



# ── قاموس الأسماء ──
_ALIASES = {
    "BTC":"BTCUSDT","ETH":"ETHUSDT","SOL":"SOLUSDT","BNB":"BNBUSDT",
    "XRP":"XRPUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","DOT":"DOTUSDT",
    "LINK":"LINKUSDT","MATIC":"MATICUSDT","OP":"OPUSDT","ARB":"ARBUSDT",
    "SUI":"SUIUSDT","INJ":"INJUSDT","TIA":"TIAUSDT","NEAR":"NEARUSDT",
    "RENDER":"RENDERUSDT","RNDR":"RENDERUSDT","FET":"FETUSDT","TAO":"TAOUSDT",
    "AXS":"AXSUSDT","SAND":"SANDUSDT","IMX":"IMXUSDT","GALA":"GALAUSDT",
    "DOGE":"DOGEUSDT","SHIB":"SHIBUSDT","PEPE":"PEPEUSDT","BONK":"BONKUSDT",
    "WIF":"WIFUSDT","BOME":"BOMEUSDT","POPCAT":"POPCATUSDT","NEIRO":"NEIROUSDT",
    "ORCA":"ORCAUSDT","JUP":"JUPUSDT","PYTH":"PYTHUSDT","RAY":"RAYUSDT",
    "HYPE":"HYPEUSDT","CHIP":"CHIPUSDT","AAVE":"AAVEUSDT","UNI":"UNIUSDT",
    "MKR":"MKRUSDT","CRV":"CRVUSDT","LDO":"LDOUSDT","ATOM":"ATOMUSDT",
    "SEI":"SEIUSDT","APT":"APTUSDT","STRK":"STRKUSDT","ZK":"ZKUSDT",
    "EIGEN":"EIGENUSDT","IO":"IOUSDT","W":"WUSDT","ALT":"ALTUSDT",
    "1000PEPE":"1000PEPEUSDT","1000SHIB":"1000SHIBUSDT","SATS":"1000SATSUSDT",
    "FTM":"FTMUSDT","FLOKI":"FLOKIUSDT","MOG":"MOGUSDT","TURBO":"TURBOUSDT",
    "POL":"POLUSDT","JITO":"JITOUSDT",
}

def resolve_sym(raw:str) -> str:
    s = raw.upper().strip()
    if s in _ALIASES: return _ALIASES[s]
    if any(s.endswith(x) for x in ("USDT","USDC","BTC","ETH","BNB")): return s
    return s + "USDT"

def api_get(url, params=None, timeout=(4, 8)):
    return session.get(url, params=params, timeout=timeout)


# ==================================================
# Binance — جلب البيانات
# ==================================================

def fetch_binance(sym):
    """جلب بيانات Binance Futures + Spot fallback."""
    out = {"price":None,"rate":0.0,"df":None,
           "ls_long":None,"ls_short":None,
           "oi_chg":None,"liq_l":0.0,"liq_s":0.0}

    # ① Spot (الأكثر موثوقية)
    for url in ["https://api.binance.com/api/v3/ticker/price",
                "https://api1.binance.com/api/v3/ticker/price",
                "https://api2.binance.com/api/v3/ticker/price"]:
        try:
            r = api_get(url, {"symbol":sym}, timeout=(5,10))
            if r and r.status_code == 200:
                d = r.json()
                p = d.get("price")
                if p and float(p) > 0:
                    out["price"] = float(p)
                    break
        except: continue

    # ② Futures (للـ Funding Rate)
    try:
        r = api_get(f"{BASE}/fapi/v1/premiumIndex", {"symbol":sym}, timeout=(5,10))
        if r and r.status_code == 200:
            d = r.json()
            if isinstance(d,list): d = d[0]
            mp = d.get("markPrice")
            if mp and float(mp) > 0:
                if not out["price"]: out["price"] = float(mp)
            fr = d.get("lastFundingRate","0")
            out["rate"] = float(fr or 0) * 100
    except: pass

    if not out["price"]:
        # لعلها ليست في Futures — أعطِ رسالة مفيدة
        raise Exception(f"❌ {sym} غير موجودة على Binance Futures\n"
                        f"جرب: BTC ETH SOL BNB أو اسم العملة الكامل")

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
    """جلب شموع — Futures أولاً ثم Spot."""
    cols = ["t","o","h","l","c","v","ct","qv","tr","bb","bq","ig"]
    nums = ["o","h","l","c","v","qv","bb","bq"]
    for url in [f"{BASE}/fapi/v1/klines",
                "https://api.binance.com/api/v3/klines",
                "https://api1.binance.com/api/v3/klines"]:
        try:
            r = api_get(url, {"symbol":sym,"interval":interval,"limit":limit}, timeout=(6,15))
            if r and r.status_code == 200:
                data = r.json()
                if isinstance(data,list) and len(data) > 3:
                    df = pd.DataFrame(data, columns=cols)
                    for col in nums:
                        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
                    return df
        except: pass
    return None

def fetch_onchain(sym):
    """
    On-Chain Gas Oracle من Etherscan فقط (المؤشر #7).
    - Gas منخفض = شبكة هادئة = نشاط أقل
    - Gas مرتفع = شبكة مزدحمة = طلب عالي
    """
    if not ETHERSCAN_KEY or ETHERSCAN_KEY in ("YOUR_ETHERSCAN_KEY_HERE", "NO_KEY", ""):
        return "❓", "غير مفعّل", "أضف ETHERSCAN_KEY", False, False
    try:
        r = session.get(
            ETH_API,
            params={
                "chainid": ETH_CHAIN,  # مطلوب في V2
                "module": "gastracker",
                "action": "gasoracle",
                "apikey": ETHERSCAN_KEY,
            },
            timeout=(5,10),
        )
        j = r.json()
        if j.get("status") != "1" or not j.get("result"):
            return "⚪", "Etherscan: N/A", "", False, False
        res = j["result"]
        safe_gas = float(res.get("SafeGasPrice", 0))
        prop_gas = float(res.get("ProposeGasPrice", 0))
        fast_gas = float(res.get("FastGasPrice", 0))
        # عرض ذكي: لو Gas منخفض جداً (< 1 gwei) نعرض رقمين بعد العلامة
        # لو Gas طبيعي/مرتفع نعرض رقم صحيح
        def _g(x):
            if x < 1:    return f"{x:.2f}"
            elif x < 10: return f"{x:.1f}"
            else:        return f"{x:.0f}"
        val = f"Gas: {_g(safe_gas)}/{_g(prop_gas)}/{_g(fast_gas)} gwei"
        if prop_gas < 5:
            return "🟡", val, "شبكة هادئة جداً — نشاط ضعيف", False, False
        elif prop_gas < 15:
            return "⚪", val, "نشاط طبيعي", False, False
        elif prop_gas < 40:
            return "✅", val, "نشاط مرتفع — طلب صحي", True, False
        elif prop_gas < 80:
            return "🔥", val, "ازدحام — طلب قوي", True, False
        else:
            return "🔴", val, "ازدحام شديد — احذر FOMO", False, True
    except Exception as e:
        logging.warning(f"[ONCHAIN] {e}")
        return "⚪", "Etherscan: خطأ", "", False, False


def fetch_sentiment(sym):
    """
    Fear & Greed Index من alternative.me (المؤشر #8 الجديد).
    مؤشر مزاج السوق العام للكريبتو.
    """
    try:
        r = session.get("https://api.alternative.me/fng/",
                        params={"limit":1}, timeout=(5,10))
        d = r.json()
        fg = int(d["data"][0]["value"])
        fc = d["data"][0]["value_classification"]
        val = f"F&G: {fg}/100 ({fc})"
        if fg <= 20:
            return "✅", val, "خوف شديد = فرصة شراء", True, False
        elif fg <= 40:
            return "🟡", val, "خوف = حذر، فرصة محتملة", False, False
        elif fg <= 55:
            return "⚪", val, "محايد", False, False
        elif fg < 75:
            return "🟡", val, "جشع = احذر القمة", False, False
        else:
            return "🔴", val, "جشع شديد = احذر التصحيح", False, True
    except Exception:
        # احتياطي: BTC Dominance
        try:
            r2 = session.get("https://api.coingecko.com/api/v3/global", timeout=(5,10))
            dom = r2.json().get("data",{}).get("market_cap_percentage",{}).get("btc",50)
            val2 = f"BTC Dom: {dom:.1f}%"
            if dom > 55: return "🔴", val2, "هيمنة BTC عالية", False, True
            elif dom < 45: return "✅", val2, "Altcoin Season", True, False
            else: return "⚪", val2, "متوازن", False, False
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

        # ─── 8. Fear & Greed Sentiment ───
        fg_icon, fg_val, fg_note, fg_bull, fg_bear = fetch_sentiment(sym)
        if fg_bull:
            R["sl"] += 1
        elif fg_bear:
            R["ss"] += 1
        R["sigs"].append(("8","Fear & Greed 🧠",fg_icon,fg_val,fg_note))

        # ─── 9. Candlestick Patterns MTF ───
        try:
            tf_res, bt, brt = analyze_mtf(sym)
            tf_line = " | ".join(f"{lb}:{ic}" for lb,ic,_ in tf_res)
            pats    = [p for _,ic,p in tf_res if ic in ("✅","🔴") and p != "محايد"]
            pat_str = " / ".join(pats) if pats else "لا أنماط"

            if bt >= 3:
                R["sl"] += 1
                R["sigs"].append(("9","شموع MTF","✅",
                    tf_line, f"{bt}/4 فريمات صاعدة — {pat_str}"))
            elif brt >= 3:
                R["ss"] += 1
                R["sigs"].append(("9","شموع MTF","🔴",
                    tf_line, f"{brt}/4 فريمات هابطة — {pat_str}"))
            elif bt == 2 and brt == 0:
                R["sigs"].append(("9","شموع MTF","🟡",
                    tf_line, f"صاعد ضعيف — {pat_str}"))
            elif brt == 2 and bt == 0:
                R["sigs"].append(("9","شموع MTF","🟡",
                    tf_line, f"هابط ضعيف — {pat_str}"))
            else:
                R["sigs"].append(("9","شموع MTF","⚪",tf_line,"محايد"))
        except Exception:
            R["sigs"].append(("9","شموع MTF","❓","خطأ في الجلب",""))

        # ═══════════════════════════════════════════
        # القرار v4 — Weighted Scoring (سلم 0-15)
        # ═══════════════════════════════════════════
        try:
            # نجلب 4h و 1d للـMTF
            df_4h_dec = fetch_tf(sym, "4h", 60)
            df_1d_dec = fetch_tf(sym, "1d", 60)

            # حقن البيانات الخام في R للـsignals module
            R["sym"] = sym

            # احسب الـscore الموزون
            score = signals.compute_signal_score(R, df, df_4h_dec, df_1d_dec)
            R["long_score"]  = score["long_score"]
            R["short_score"] = score["short_score"]
            R["max_score"]   = score["max_score"]
            R["components"]  = score["components"]
            R["mtf_data"]    = score["mtf"]

            # BTC bias filter للـaltcoins
            btc_bias_4h = "NEUTRAL"
            if sym not in ("BTCUSDT",):
                try:
                    df_btc_4h = fetch_tf("BTCUSDT", "4h", 60)
                    if df_btc_4h is not None:
                        btc_bias_4h = signals.get_tf_bias(df_btc_4h)
                        R["btc_bias_4h"] = btc_bias_4h
                except Exception:
                    pass

            # القرار النهائي
            decision = signals.make_decision(score, btc_bias_4h, sym)
            R["action"]      = decision["action"]
            R["confidence"]  = decision["confidence"]
            R["reason"]      = decision["reason"]
            R["decision"]    = {
                "LONG":  f"✅ إشارة LONG قوية ({decision['confidence']})",
                "SHORT": f"🔴 إشارة SHORT قوية ({decision['confidence']})",
                "WAIT":  f"⏳ انتظر — {decision['reason']}",
            }[decision["action"]]
            R["conf"] = (
                f"L:{decision['long_score']}/{decision['max_score']} | "
                f"S:{decision['short_score']}/{decision['max_score']}"
            )

            # حظر SHORT لو funding سالب جداً
            if decision["action"] == "SHORT" and rate <= -0.05:
                R["action"] = "WAIT"
                R["decision"] = "⛔ SHORT محظور — Funding سالب"
                R["warn"].append("Funding سالب يعني short squeeze محتمل")

        except Exception as e:
            R["err"] = f"❌ خطأ في حساب الإشارة: {str(e)[:80]}"
            R["action"] = "WAIT"
            R["decision"] = "⏳ انتظر — خطأ تقني"
            R["conf"] = ""

        # ─── Smart SL / TP (ATR-based, 3 levels) ───
        try:
            if df is not None and R.get("action") in ("LONG", "SHORT"):
                smart = signals.calc_smart_sl_tp(price, R["action"], df, sym)
                R["smart_levels"] = smart
                # نختار "balanced" كافتراضي
                bal = smart.get("levels", {}).get("balanced", {})
                R["slp"] = bal.get("sl")
                R["tp1"] = bal.get("tp1")
                R["tp2"] = bal.get("tp2")
                R["tp3"] = bal.get("tp3")
                R["risk_pct"] = bal.get("risk_pct")
                R["atr_pct"]  = smart.get("atr_pct")
            else:
                R["slp"] = R["tp1"] = R["tp2"] = R["tp3"] = None
        except Exception:
            R["slp"] = R["tp1"] = R["tp2"] = R["tp3"] = None

        # ─── الرافعة المقترحة ───
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


# ==================================================
# بناء الرسائل
# ==================================================

def fmt(v):
    """تنسيق السعر بعدد خانات مناسب."""
    if v >= 1000:  return f"{v:,.2f}"
    if v >= 1:     return f"{v:.4f}"
    return f"{v:.6f}"



# ╔══════════════════════════════╗
# ║  SCALPING MODULE             ║
# ╚══════════════════════════════╝

def analyze_scalp(sym):
    R={"sym":sym,"bull":0,"bear":0,"sigs":[],"warn":[],"err":None}
    try:
        price=None
        for url in ["https://api.binance.com/api/v3/ticker/price",f"{BASE}/fapi/v1/premiumIndex"]:
            try:
                r=api_get(url,{"symbol":sym},timeout=(4,8)); d=r.json()
                p=d.get("price") or d.get("markPrice")
                if p and float(p)>0: price=float(p); break
            except: continue
        if not price: R["err"]=f"❌ {sym}"; return R
        R["price"]=price
        df1=fetch_tf(sym,"1m",60); df5=fetch_tf(sym,"5m",30)
        if df1 is None or len(df1)<20: R["err"]="❌ بيانات 1m"; return R
        c1=df1["c"]; h1=df1["h"]; l1=df1["l"]; o1=df1["o"]; v1=df1["v"]
        # RSI7
        d_=c1.diff(); g_=d_.clip(lower=0).rolling(7).mean(); l_=(-d_.clip(upper=0)).rolling(7).mean()
        rsi7=float((100-100/(1+g_/l_.replace(0,np.nan))).iloc[-1]); R["rsi7"]=rsi7
        if rsi7<=25: R["bull"]+=2; R["sigs"].append(("1","RSI(7)","✅",f"{rsi7:.1f}","ذروة بيع ⚡"))
        elif rsi7>=75: R["bear"]+=2; R["sigs"].append(("1","RSI(7)","🔴",f"{rsi7:.1f}","ذروة شراء ⚡"))
        else: R["sigs"].append(("1","RSI(7)","⚪",f"{rsi7:.1f}","محايد"))
        # EMA Cross
        e5=c1.ewm(span=5,adjust=False).mean(); e13=c1.ewm(span=13,adjust=False).mean()
        if float(e5.iloc[-2])<float(e13.iloc[-2]) and float(e5.iloc[-1])>=float(e13.iloc[-1]):
            R["bull"]+=3; R["sigs"].append(("2","EMA Cross","✅","5↗13","Golden Cross ⚡"))
        elif float(e5.iloc[-2])>float(e13.iloc[-2]) and float(e5.iloc[-1])<=float(e13.iloc[-1]):
            R["bear"]+=3; R["sigs"].append(("2","EMA Cross","🔴","5↘13","Death Cross ⚡"))
        elif float(e5.iloc[-1])>float(e13.iloc[-1]):
            R["bull"]+=1; R["sigs"].append(("2","EMA Cross","✅","5>13","صاعد"))
        else: R["bear"]+=1; R["sigs"].append(("2","EMA Cross","🔴","5<13","هابط"))
        # Bollinger
        if df5 is not None and len(df5)>=20:
            c5=df5["c"]; bm=c5.rolling(20).mean(); bs=c5.rolling(20).std()
            bup=float((bm+2*bs).iloc[-1]); blo=float((bm-2*bs).iloc[-1])
            bw=(bup-blo)/float(bm.iloc[-1])*100 if float(bm.iloc[-1])>0 else 5
            if price<=blo: R["bull"]+=2; R["sigs"].append(("3","Bollinger","✅","BB↓","Bounce ⚡"))
            elif price>=bup: R["bear"]+=2; R["sigs"].append(("3","Bollinger","🔴","BB↑","انعكاس ⚡"))
            elif bw<2.0: R["sigs"].append(("3","Bollinger","🟡",f"Squeeze {bw:.1f}%","اختراق وشيك 🔥"))
            else: R["sigs"].append(("3","Bollinger","⚪",f"{bw:.1f}%","طبيعي"))
        # Volume
        va=float(v1.iloc[-20:-1].mean()) or 1; vc=float(v1.iloc[-1]); vr=vc/va
        if vr>=3.0:
            is_bull=float(c1.iloc[-1])>float(o1.iloc[-1])
            R["bull" if is_bull else "bear"]+=2
            R["sigs"].append(("4","Volume","✅" if is_bull else "🔴",f"x{vr:.1f}","ضغط شراء 🔥" if is_bull else "ضغط بيع 🔥"))
        else: R["sigs"].append(("4","Volume","⚪",f"x{vr:.1f}","طبيعي"))
        # CVD
        try:
            _bq=df1["bq"]; _qv=df1["qv"]
            if float(_bq.sum())>0:
                _cvd=(_bq-(_qv-_bq)).cumsum()
                _chg=float(_cvd.iloc[-1])-float(_cvd.iloc[-5]); _pd=float(c1.iloc[-1])-float(c1.iloc[-5])
                if _chg>0 and _pd>0: R["bull"]+=2; R["sigs"].append(("5","CVD","✅","↑","شراء حقيقي ⚡"))
                elif _chg<0 and _pd<0: R["bear"]+=2; R["sigs"].append(("5","CVD","🔴","↓","بيع حقيقي ⚡"))
                elif _chg<0 and _pd>0: R["bear"]+=1; R["sigs"].append(("5","CVD","🔴","Div↓","ارتفاع وهمي"))
                elif _chg>0 and _pd<0: R["bull"]+=1; R["sigs"].append(("5","CVD","✅","Div↑","هبوط وهمي"))
                else: R["sigs"].append(("5","CVD","⚪","محايد",""))
            else: raise ValueError
        except:
            bull_c=(c1>o1).astype(float); ce=(v1*(2*bull_c-1)).cumsum()
            if float(ce.iloc[-1])>float(ce.iloc[-5]): R["bull"]+=1; R["sigs"].append(("5","CVD","✅","~↑",""))
            else: R["bear"]+=1; R["sigs"].append(("5","CVD","🔴","~↓",""))
        # ATR
        hv=h1.values; lv=l1.values; cv=c1.values
        tr=pd.Series([max(hv[i]-lv[i],abs(hv[i]-cv[i-1]),abs(lv[i]-cv[i-1])) for i in range(1,len(cv))],dtype=float)
        atr1=float(tr.rolling(7).mean().iloc[-1]) if len(tr)>=7 else 0
        atrp=atr1/price*100 if price>0 else 0; R["atr1"]=atr1
        if atrp>=0.5: R["sigs"].append(("6","ATR","🔥",f"{atrp:.2f}%","تقلب عالي ⚡"))
        else: R["sigs"].append(("6","ATR","⚪",f"{atrp:.2f}%","هادئ"))
        # القرار
        if R["bull"]>=6: R["action"]="LONG"; R["decision"]="⚡ SCALP LONG قوي"
        elif R["bear"]>=6: R["action"]="SHORT"; R["decision"]="⚡ SCALP SHORT قوي"
        elif R["bull"]>=4: R["action"]="LONG"; R["decision"]="✅ SCALP LONG"
        elif R["bear"]>=4: R["action"]="SHORT"; R["decision"]="🔴 SCALP SHORT"
        else: R["action"]="WAIT"; R["decision"]="⏳ انتظر"; R["conf"]=f"↑{R['bull']} ↓{R['bear']}"
        R["conf"]=f"{max(R['bull'],R['bear'])} إشارة"
        if R["action"]!="WAIT" and atr1>0:
            sd=max(atr1*0.5,price*0.002)
            if R["action"]=="LONG":
                R["sl"]=round(price-sd,8); R["tp1"]=round(price+sd,8); R["tp2"]=round(price+sd*2,8); R["tp3"]=round(price+sd*3,8)
            else:
                R["sl"]=round(price+sd,8); R["tp1"]=round(price-sd,8); R["tp2"]=round(price-sd*2,8); R["tp3"]=round(price-sd*3,8)
            R["sl_pct"]=round(sd/price*100,3)
    except Exception as e: R["err"]=f"❌ {str(e)[:80]}"
    return R


def build_scalp(R):
    if R.get("err"): return R["err"]
    sym=R["sym"]; price=R.get("price",0); action=R.get("action","WAIT")
    from datetime import datetime,timezone,timedelta
    now=datetime.now(timezone(timedelta(hours=3))).strftime("%H:%M:%S %d/%m/%Y")
    m=f"⚡ *SCALP — {sym}*\n💰 `${fmt(price)}` | 🕐 {now}\n"
    m+="━━━━━━━━━━━━━━━━\n\n📊 *المؤشرات (1m/5m):*\n\n"
    for num,name,icon,val,note in sorted(R.get("sigs",[]),key=lambda x:x[0]):
        m+=f"{icon} *{num}. {name}:* `{val}`"
        if note: m+=f" _{note}_"
        m+="\n"
    m+=f"\n━━━━━━━━━━━━━━━━\n⚡ *القرار:* {R.get('decision','')} ({R.get('conf','')})"
    if R.get("action")!="WAIT" and R.get("sl"):
        sl_p=R.get("sl_pct",0)
        m+=f"\n\n🟢 دخول: `${fmt(price)}`\n🔴 SL: `${fmt(R['sl'])}` _(-{sl_p:.2f}%)_"
        m+=f"\n💰 TP1: `${fmt(R['tp1'])}`\n💰 TP2: `${fmt(R['tp2'])}`\n🏆 TP3: `${fmt(R['tp3'])}`"
    m+="\n\n⚠️ _للأغراض التعليمية فقط_"
    return m


async def scalp_monitor_job(ctx):
    cid=ctx.job.data["chat_id"]; sym=ctx.job.data["sym"]
    try:
        loop=asyncio.get_event_loop()
        R=await asyncio.wait_for(loop.run_in_executor(None,analyze_scalp,sym),timeout=25)
        if R.get("err") or R.get("action","WAIT")=="WAIT": return
        msg="🔔 *تنبيه Scalp!*\n"+build_scalp(R)
        await ctx.bot.send_message(cid,msg,parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚡ تحديث",callback_data=f"s:{sym}"),
                InlineKeyboardButton("📊 تحليل",callback_data=f"r:{sym}"),
            ]]))
    except Exception: pass


# ╔══════════════════════════════╗
# ║  ICT/SMC SCANNER             ║
# ╚══════════════════════════════╝

_scan_excl={"USDTUSDT","BUSDUSDT","USDCUSDT","FDUSDUSDT","WBTCUSDT","WETHUSDT",
           "TUSDUSDT","DAIUSDT","USDPUSDT","SUSDUSDT","FRAXUSDT","LUSDUSDT"}
_fut_cache:list=[]; _fut_ts:float=0
_spot_cache:list=[]; _spot_ts:float=0
scan_lists:dict={}; scan_alerted:dict={}; SCAN_COOL=7200

def get_futures_syms():
    global _fut_cache,_fut_ts
    import time as _t
    if _fut_cache and (_t.time()-_fut_ts)<3600: return _fut_cache
    try:
        for url in [f"{BASE}/fapi/v1/ticker/24hr","https://fapi.binance.com/fapi/v1/ticker/24hr"]:
            r=api_get(url,timeout=(12,30))
            if r and r.status_code==200:
                syms=[t["symbol"] for t in r.json() if t.get("symbol","").endswith("USDT") and t.get("symbol") not in _scan_excl]
                if syms: _fut_cache=sorted(syms); _fut_ts=_t.time(); return syms
    except: pass
    return _fut_cache or ["BTCUSDT","ETHUSDT","SOLUSDT"]


def get_spot_syms():
    """يجلب كل عملات Binance Spot USDT (للسبوت بس، بدون اللي في الفيوتشر)"""
    global _spot_cache, _spot_ts
    import time as _t
    if _spot_cache and (_t.time()-_spot_ts)<3600: return _spot_cache
    try:
        for url in ["https://api.binance.com/api/v3/ticker/24hr",
                    "https://api1.binance.com/api/v3/ticker/24hr",
                    "https://api2.binance.com/api/v3/ticker/24hr"]:
            r = api_get(url, timeout=(12,30))
            if r and r.status_code == 200:
                # نأخذ عملات USDT بحجم تداول معقول (>100K USD)
                syms = []
                for t in r.json():
                    sym = t.get("symbol", "")
                    if not sym.endswith("USDT"): continue
                    if sym in _scan_excl: continue
                    try:
                        vol = float(t.get("quoteVolume", 0))
                        if vol < 100_000: continue  # نتجاهل العملات الميتة
                    except (ValueError, TypeError):
                        continue
                    syms.append(sym)
                if syms:
                    _spot_cache = sorted(syms)
                    _spot_ts = _t.time()
                    return _spot_cache
    except Exception as e:
        logging.warning(f"get_spot_syms error: {e}")
    return _spot_cache or []


def get_all_scannable_syms(include_spot: bool = True):
    """يرجع [(sym, is_futures: bool)] — الفيوتشر أولاً، ثم السبوت اللي مش في الفيوتشر"""
    futures = set(get_futures_syms())
    result = [(s, True) for s in sorted(futures)]
    if include_spot:
        spot = get_spot_syms()
        # السبوت فقط (مش في الفيوتشر)
        spot_only = [s for s in spot if s not in futures]
        result.extend([(s, False) for s in sorted(spot_only)])
    return result

def ict_score(sym):
    """Order Block + FVG + Smart Money + ICP."""
    sb=0; ss=0; sigs=[]
    try:
        df=fetch_tf(sym,"1h",80)
        if df is None or len(df)<30: return 0,0,[]
        c=df["c"]; h=df["h"]; l=df["l"]; o=df["o"]; v=df["v"]
        price=float(c.iloc[-1])
        avg_mv=float(abs(c.diff()).iloc[-20:].mean()) or 1
        # Order Block
        for i in range(2,min(35,len(df)-3)):
            idx=-(i+1); ot=max(float(o.iloc[idx]),float(c.iloc[idx])); ob=min(float(o.iloc[idx]),float(c.iloc[idx]))
            mv=abs(float(c.iloc[idx+3])-float(c.iloc[idx+1]))
            if mv>avg_mv*1.5:
                is_bear=float(c.iloc[idx])<float(o.iloc[idx])
                if is_bear and float(c.iloc[idx+3])>float(c.iloc[idx]) and ob<=price<=ot*1.01:
                    sb+=3; sigs.append("🟩 OB صاعد"); break
                is_bull=float(c.iloc[idx])>float(o.iloc[idx])
                if is_bull and float(c.iloc[idx+3])<float(c.iloc[idx]) and ob*0.99<=price<=ot:
                    ss+=3; sigs.append("🟥 OB هابط"); break
        # FVG
        for i in range(2,min(20,len(df)-1)):
            idx=-i
            flo=float(l.iloc[idx]); fhi=float(h.iloc[idx-2])
            if flo>fhi and (flo-fhi)/fhi*100>=0.1 and fhi<=price<=flo:
                sb+=2; sigs.append("💹 FVG صاعد"); break
            fhi2=float(h.iloc[idx]); flo2=float(l.iloc[idx-2])
            if fhi2<flo2 and (flo2-fhi2)/fhi2*100>=0.1 and fhi2<=price<=flo2:
                ss+=2; sigs.append("🔻 FVG هابط"); break
        # SMC
        sh=float(h.iloc[-20:].max()); sl2=float(l.iloc[-20:].min())
        ph=float(h.iloc[-5:-1].max()); pl=float(l.iloc[-5:-1].min())
        if price>sh*0.998: sb+=3; sigs.append("🚀 BOS صاعد")
        elif price<sl2*1.002: ss+=3; sigs.append("📉 BOS هابط")
        if float(c.iloc[-3])<float(c.iloc[-5]) and price>ph: sb+=2; sigs.append("🔄 CHoCH صاعد")
        elif float(c.iloc[-3])>float(c.iloc[-5]) and price<pl: ss+=2; sigs.append("🔄 CHoCH هابط")
        if float(l.iloc[-2])<sl2 and price>sl2: sb+=3; sigs.append("💎 Bull Sweep")
        elif float(h.iloc[-2])>sh and price<sh: ss+=3; sigs.append("🐻 Bear Sweep")
        # ICP
        h30=float(h.iloc[-30:].max()); l30=float(l.iloc[-30:].min()); rng=h30-l30
        if rng>0:
            f50=l30+rng*0.5; f618=l30+rng*0.618; tol=rng*0.03
            if float(c.iloc[-10])>float(c.iloc[-20]):
                if abs(price-f50)<=tol or abs(price-f618)<=tol: sb+=3; sigs.append(f"⭐ ICP صاعد")
            else:
                f382=l30+rng*0.382
                if abs(price-f382)<=tol or abs(price-f50)<=tol: ss+=3; sigs.append(f"⭐ ICP هابط")
    except: pass
    return sb,ss,sigs

def full_scan_sync(sym):
    try:
        base=analyze(sym)
        if not base or base.get("err"): return None
        sb,ss,ict_s=ict_score(sym)
        price = base.get("price", 0)

        # احصل على SL/TP من analyze() (يستخدم مفتاح "slp" للـ SL)
        sl_v  = base.get("slp")  or 0
        tp1_v = base.get("tp1")  or 0
        tp2_v = base.get("tp2")  or 0
        tp3_v = 0

        # حساب SL/TP/TP3 بناءً على اتجاه الإشارة (لو analyze ما حدّد action)
        # نحسب الاتجاه من النقاط: إن البول > البير → LONG، والعكس
        bull_total = base.get("sl", 0) + sb
        bear_total = base.get("ss", 0) + ss
        direction  = "LONG" if bull_total > bear_total else "SHORT"

        # لو SL مش محسوب أو محسوب لاتجاه عكسي، نحسبه من ATR
        atr = base.get("atr1", 0) or (price * 0.015)  # 1.5% احتياطي
        if atr > 0:
            atr_safe = min(atr, price * 0.05)  # حد أقصى 5%
            if direction == "LONG":
                # تأكد من اتجاه SL/TP صحيح
                if not sl_v or sl_v >= price:
                    sl_v  = round(price - 1.5 * atr_safe, 6)
                if not tp1_v or tp1_v <= price:
                    tp1_v = round(price + 1.5 * atr_safe, 6)
                if not tp2_v or tp2_v <= price:
                    tp2_v = round(price + 3.0 * atr_safe, 6)
                tp3_v = round(price + 4.5 * atr_safe, 6)
            else:  # SHORT
                if not sl_v or sl_v <= price:
                    sl_v  = round(price + 1.5 * atr_safe, 6)
                if not tp1_v or tp1_v >= price:
                    tp1_v = round(price - 1.5 * atr_safe, 6)
                if not tp2_v or tp2_v >= price:
                    tp2_v = round(price - 3.0 * atr_safe, 6)
                tp3_v = round(price - 4.5 * atr_safe, 6)

        return {"sym": sym, "bull": bull_total, "bear": bear_total,
                "price": price, "tp1": tp1_v, "tp2": tp2_v, "tp3": tp3_v,
                "sl": sl_v, "base_sigs": base.get("sigs", []), "ict_sigs": ict_s}
    except Exception as e:
        logging.warning(f"[SCAN] {sym}: {e}")
        return None

def build_scan_alert(r,direction):
    sym=r["sym"]; price=r["price"]; score=r["bull"] if direction=="BUY" else r["bear"]
    from datetime import datetime,timezone,timedelta
    now=datetime.now(timezone(timedelta(hours=3))).strftime("%H:%M:%S %d/%m/%Y")
    icon="🟢" if direction=="BUY" else "🔴"
    bar="█"*min(int(score/2),10)+"░"*(10-min(int(score/2),10))
    m=f"🎯 *إشارة {icon} {'شراء' if direction=='BUY' else 'بيع'} — {sym}*\n🕐 {now}\n"
    m+=f"━━━━━━━━━━━━━━━━\n💰 `${fmt(price)}` | نقاط: `{score}`\n`{bar}`\n\n"
    m+="📡 *ICT/SMC:*\n"
    for s in r.get("ict_sigs",[]): m+=f"  {s}\n"
    m+="\n📊 *المؤشرات:*\n"
    for sig in r.get("base_sigs",[])[:4]:
        ic=sig[2]; nm=sig[1]; vl=sig[3]
        if (direction=="BUY" and ic=="✅") or (direction=="SELL" and ic=="🔴"):
            m+=f"  {ic} *{nm}:* `{vl}`\n"

    # نتأكد إن SL/TP منطقية
    sl  = r.get("sl",  0) or 0
    tp1 = r.get("tp1", 0) or 0
    tp2 = r.get("tp2", 0) or 0
    tp3 = r.get("tp3", 0) or 0

    # احتياطي أخير: لو SL لسه 0، نحسبه على شكل ±2% من السعر
    if not sl or sl <= 0:
        sl = round(price * (0.98 if direction == "BUY" else 1.02), 6)
    if not tp1 or tp1 <= 0:
        tp1 = round(price * (1.015 if direction == "BUY" else 0.985), 6)
    if not tp2 or tp2 <= 0:
        tp2 = round(price * (1.03 if direction == "BUY" else 0.97), 6)
    if not tp3 or tp3 <= 0:
        tp3 = round(price * (1.045 if direction == "BUY" else 0.955), 6)

    # نسبة المخاطرة/المكافأة
    risk = abs(price - sl)
    reward = abs(tp1 - price)
    rr = (reward / risk) if risk > 0 else 0

    m += f"\n━━━━━━━━━━━━━━━━\n🟢 دخول: `${fmt(price)}`\n"
    m += f"🛑 SL : `${fmt(sl)}` ({((sl-price)/price*100):+.2f}%)\n"
    m += f"💰 TP1: `${fmt(tp1)}` ({((tp1-price)/price*100):+.2f}%)\n"
    m += f"💰 TP2: `${fmt(tp2)}` ({((tp2-price)/price*100):+.2f}%)\n"
    m += f"🏆 TP3: `${fmt(tp3)}` ({((tp3-price)/price*100):+.2f}%)\n"
    if rr > 0:
        m += f"⚖️ R:R = `1:{rr:.2f}`\n"

    m+="\n⚠️ _للأغراض التعليمية فقط_"
    return m

async def auto_scanner_job(ctx):
    import time as _t
    cid=ctx.job.data["chat_id"]; min_sc=ctx.job.data.get("min_score",7)
    sym_list=scan_lists.get(cid,[]) or get_futures_syms()
    now_ts=_t.time(); found=[]
    for sym in sym_list:
        if now_ts-scan_alerted.get(cid,{}).get(sym,0)<SCAN_COOL: continue
        try:
            loop=asyncio.get_event_loop()
            r=await asyncio.wait_for(loop.run_in_executor(None,full_scan_sync,sym),timeout=35)
            if not r: continue
            if r["bull"]>=min_sc: found.append(("BUY",sym,r["bull"],r))
            elif r["bear"]>=min_sc: found.append(("SELL",sym,r["bear"],r))
        except: continue
    found.sort(key=lambda x:x[2],reverse=True)
    for direction,sym,score,r in found[:3]:
        scan_alerted.setdefault(cid,{})[sym]=now_ts
        try:
            await ctx.bot.send_message(cid,build_scan_alert(r,direction),parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"📊 {sym[:-4]}",callback_data=f"r:{sym}"),
                    InlineKeyboardButton("⚡ سكالب",callback_data=f"s:{sym}"),
                ]]))
        except Exception as e: logging.warning(f"[SCAN_SEND] {e}")


# ╔═══════════════════════════════════════════╗
# ║  v4 SCANNER (Spot + Futures, 80%+)        ║
# ╚═══════════════════════════════════════════╝

async def auto_scanner_v4_job(ctx):
    """
    v4 Scanner — يفحص كل العملات (Spot + Futures) ويرسل إشارات بـ80%+ confidence.
    يستخدم signals.compute_signal_score الموزون (15 نقطة للفيوتشر، 11 للسبوت).
    """
    cid = ctx.job.data["chat_id"]

    # 1) جلب إعدادات المستخدم من DB (إن موجودة)
    sub = db.get_scanner_subscriber(cid)
    if not sub:
        # أُلغي الاشتراك — وقّف الـjob
        for j in ctx.job_queue.get_jobs_by_name(f"sc_v4_{cid}"):
            j.schedule_removal()
        return

    threshold = sub.get("threshold", 12)
    scan_spot = bool(sub.get("scan_spot", 1))
    cooldown_h = sub.get("cooldown_hours", 4)
    max_per_cycle = sub.get("max_per_cycle", 5)

    # حد السبوت = 80% من 11 = 9 (لو threshold=12، لو 13→10، لو 9→7)
    spot_threshold = max(7, int(round(threshold * 11 / 15)))

    # 2) جلب قائمة العملات
    all_syms = get_all_scannable_syms(include_spot=scan_spot)
    if not all_syms:
        logging.warning(f"Scanner v4 [{cid}]: no symbols available")
        return

    logging.info(f"Scanner v4 [{cid}]: scanning {len(all_syms)} symbols "
                 f"(threshold={threshold}f/{spot_threshold}s)")

    # 3) فحص كل عملة
    found = []
    cooldown_seconds = cooldown_h * 3600
    now = datetime.now()

    for sym, is_futures in all_syms:
        # cooldown check
        last_alert = db.last_scanner_alert(cid, sym)
        if last_alert:
            elapsed = (now - last_alert).total_seconds()
            if elapsed < cooldown_seconds:
                continue

        try:
            loop = asyncio.get_event_loop()
            R = await asyncio.wait_for(
                loop.run_in_executor(None, analyze, sym),
                timeout=30
            )
            if not R or R.get("err"):
                continue

            action = R.get("action", "WAIT")
            if action not in ("LONG", "SHORT"):
                continue

            long_s = R.get("long_score", 0)
            short_s = R.get("short_score", 0)
            score = long_s if action == "LONG" else short_s

            # حد مختلف للسبوت
            min_sc = threshold if is_futures else spot_threshold
            if score < min_sc:
                continue

            found.append((action, sym, score, R, is_futures))

        except asyncio.TimeoutError:
            continue
        except Exception as e:
            logging.warning(f"Scanner v4 error for {sym}: {str(e)[:60]}")
            continue

    # 4) ترتيب حسب القوة (الأعلى أولاً)
    found.sort(key=lambda x: x[2], reverse=True)

    # 5) إرسال الإشارات (max_per_cycle)
    sent_count = 0
    for action, sym, score, R, is_futures in found[:max_per_cycle]:
        try:
            market_tag = "🔵 Futures" if is_futures else "🟣 Spot"
            max_sc = 15 if is_futures else 11
            pct = round(score / max_sc * 100)

            header = (
                f"📡 *مسح ذكي v4* — {market_tag}\n"
                f"💪 قوة الإشارة: *{pct}%* ({score}/{max_sc})\n"
                f"━━━━━━━━━━━━━━━━\n\n"
            )
            body = build_entry(R, alert=True)
            full_msg = header + body

            await ctx.bot.send_message(
                cid, full_msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"📊 تحليل كامل",
                                         callback_data=f"r:{sym}"),
                    InlineKeyboardButton(f"⚡ سكالب",
                                         callback_data=f"s:{sym}"),
                ]])
            )
            db.record_scanner_alert(cid, sym, action, float(score))
            sent_count += 1
        except Exception as e:
            logging.warning(f"Scanner v4 send error: {e}")

    if sent_count == 0 and len(found) == 0:
        # نظافة دورية للتنبيهات القديمة
        try:
            db.cleanup_old_scanner_alerts(days=7)
        except Exception:
            pass

    logging.info(f"Scanner v4 [{cid}]: scanned {len(all_syms)}, "
                 f"found {len(found)}, sent {sent_count}")


def build_entry(R, alert=False):
    if R.get("err"):
        return R["err"]

    sym    = R["sym"]
    price  = R.get("price", 0)
    action = R.get("action", "WAIT")
    now    = datetime.now().strftime("%H:%M")
    icons  = {"LONG":"🟢 LONG","SHORT":"🔴 SHORT","WAIT":"⏳ انتظر"}
    hdr    = icons.get(action,"⏳")
    pre    = "🔔 *إشارة قوية!*\n" if alert else ""

    m  = f"{pre}📊 *{sym}* — {hdr}\n"
    m += f"💰 `${fmt(price)}` | 🕐 {now}\n"
    m += "━━━━━━━━━━━━━━━━\n\n"

    # ─── Weighted Score (الجديد) ───
    long_s  = R.get("long_score", 0)
    short_s = R.get("short_score", 0)
    max_s   = R.get("max_score", 15)

    # شريط بصري
    def bar(score, max_score=15):
        filled = int((score / max_score) * 10)
        return "█" * filled + "░" * (10 - filled)

    m += f"📊 *النتيجة الموزونة (0-{max_s}):*\n"
    m += f"🟢 LONG:  `{bar(long_s, max_s)}` *{long_s}/{max_s}*\n"
    m += f"🔴 SHORT: `{bar(short_s, max_s)}` *{short_s}/{max_s}*\n\n"

    # MTF status
    mtf = R.get("mtf_data", {})
    if mtf:
        emoji_map = {"BULLISH":"🟢", "BEARISH":"🔴", "NEUTRAL":"⚪"}
        m += f"⏱ *MTF:* "
        m += f"1h{emoji_map.get(mtf.get('1h','NEUTRAL'),'⚪')} | "
        m += f"4h{emoji_map.get(mtf.get('4h','NEUTRAL'),'⚪')} | "
        m += f"1d{emoji_map.get(mtf.get('1d','NEUTRAL'),'⚪')}\n"

    # BTC bias warning
    if R.get("btc_bias_4h") and sym != "BTCUSDT":
        m += f"₿ *BTC 4h:* {R['btc_bias_4h']}\n"

    m += "\n━━━━━━━━━━━━━━━━\n"
    m += "🔍 *تفصيل المؤشرات:*\n\n"

    # المكونات الموزونة
    for name, status, detail, pts in R.get("components", []):
        pts_str = f"+{pts:.1f}pt" if pts > 0 else ""
        m += f"{status} *{name}* {pts_str}\n"
        if detail:
            m += f"   _{detail}_\n"

    # شموع MTF (من v3)
    candles_sigs = [s for s in R.get("sigs", []) if s[1] == "شموع MTF"]
    if candles_sigs:
        for num,name,icon,val,note in candles_sigs:
            m += f"{icon} *{name}*\n   `{val}`\n"
            if note: m += f"   _{note}_\n"

    m += "\n━━━━━━━━━━━━━━━━\n"
    m += f"⚡ *القرار:* {R.get('decision','')}\n\n"

    # المستويات الذكية
    if action != "WAIT" and R.get("smart_levels"):
        smart = R["smart_levels"]
        bal = smart.get("levels", {}).get("balanced", {})
        m += "🎯 *مستويات ذكية (ATR-based):*\n"
        m += f"📥 الدخول:  `${fmt(price)}`\n"
        m += f"🛑 SL:      `${fmt(bal.get('sl'))}` ({bal.get('risk_pct',0):.2f}%)\n"
        m += f"🎯 TP1:     `${fmt(bal.get('tp1'))}` (1.5R)\n"
        m += f"🎯 TP2:     `${fmt(bal.get('tp2'))}` (3R)\n"
        m += f"🎯 TP3:     `${fmt(bal.get('tp3'))}` (4.5R)\n"
        m += f"📏 ATR:     {smart.get('atr_pct', 0):.2f}%\n"
        m += f"⚙️ الرافعة: {R.get('lev','')}\n"
        m += f"💼 الحجم:   {R.get('size','')}\n\n"

        # دعوة لإضافة الصفقة في التتبع
        action_word = "LONG" if action == "LONG" else "SHORT"
        m += "📋 *لإضافة هذه الصفقة في التتبع:*\n"
        m += (f"`صفقة {action_word} {sym[:-4]} "
              f"{fmt(price)} {fmt(bal.get('sl'))} "
              f"{fmt(bal.get('tp1'))} {fmt(bal.get('tp2'))} "
              f"{fmt(bal.get('tp3'))}`\n\n")

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

    m += "\n⚠️ _تحليل تعليمي — البوت لا يفتح صفقات تلقائياً_"
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


async def monitor_job(ctx):
    """متابعة عملة معينة — يعطي إشارة فقط (لا يفتح صفقات تلقائياً)"""
    chat_id = ctx.job.data["chat_id"]
    sym     = ctx.job.data["sym"]
    try:
        R = await run_analysis(sym)
        if R.get("err"):
            return

        action = R.get("action", "WAIT")
        long_s = R.get("long_score", 0)
        short_s = R.get("short_score", 0)

        # نبعت تنبيه فقط لو إشارة قوية (≥12) أو متوسطة قوية (≥10)
        threshold = 12.0
        score = max(long_s, short_s)

        if action in ("LONG", "SHORT") and score >= threshold:
            # هل أبلغنا عن نفس الإشارة قبل قليل؟ (نتجنب التكرار)
            jname = ctx.job.name or ""
            last_alert = watching.get(chat_id, {}).get(f"_last_{sym}")
            cur_signal = f"{action}_{int(score)}"
            if last_alert == cur_signal:
                return  # نفس الإشارة - تجاهل
            watching.setdefault(chat_id, {})[f"_last_{sym}"] = cur_signal

            await ctx.bot.send_message(
                chat_id=chat_id,
                text=build_entry(R, alert=True),
                parse_mode="Markdown",
                reply_markup=kb(sym),
            )

    except Exception:
        pass


# ═══════════════════════════════════════════
# Tracked Trades Monitor (الجديد) - يفحص الصفقات المتتبعة كل دقيقة
# ═══════════════════════════════════════════

def _quick_price(sym):
    """جلب السعر الحالي بسرعة (للمراقبة)"""
    try:
        r = api_get("https://api.binance.com/api/v3/ticker/price",
                    {"symbol": sym}, timeout=(3, 5))
        if r and r.status_code == 200:
            return float(r.json().get("price", 0))
    except Exception:
        pass
    # fallback لـfutures
    try:
        r = api_get(f"{BASE}/fapi/v1/premiumIndex",
                    {"symbol": sym}, timeout=(3, 5))
        if r and r.status_code == 200:
            d = r.json()
            if isinstance(d, list): d = d[0]
            return float(d.get("markPrice", 0))
    except Exception:
        pass
    return None


async def tracked_monitor_job(ctx):
    """يفحص الصفقات المتتبعة كل 60 ثانية ويرسل التنبيهات"""
    try:
        await tracker.tracked_trades_monitor(
            ctx,
            fetch_price_fn=_quick_price,
            run_analysis_fn=None,  # سريع - بدون تحليل ثقيل
        )
    except Exception:
        pass


async def tracked_deep_analysis_job(ctx):
    """يحلل العملات في الصفقات المفتوحة كل 5 دقائق (للـreversal/add)"""
    try:
        open_trades = db.get_open_trades()
        if not open_trades:
            return
        symbols = list(set(t["symbol"] for t in open_trades))
        for sym in symbols:
            try:
                R = await run_analysis(sym)
                if R.get("err"):
                    continue
                price = R.get("price")
                if not price:
                    continue
                # تأمين قرار للـ reversal/add detection
                signal_decision = {
                    "action": R.get("action"),
                    "long_score": R.get("long_score", 0),
                    "short_score": R.get("short_score", 0),
                }
                # افحص كل صفقة على هذه العملة
                for t in [t for t in open_trades if t["symbol"] == sym]:
                    alerts = tracker.check_trade_for_alerts(
                        t, price, signal_decision)
                    # نرسل بس reversal و add (الباقي يتولاه quick monitor)
                    for alert in alerts:
                        if alert["type"] not in ("REVERSAL", "ADD_OPP"):
                            continue
                        emoji_action = "🟢" if t["action"] == "LONG" else "🔴"
                        pnl = tracker.calc_pnl_pct(t, price)
                        msg = (f"{alert['title']}\n\n"
                               f"📊 *#{t['id']} {t['symbol']} "
                               f"{emoji_action} {t['action']}*\n"
                               f"💵 Entry: `{t['entry']}` | "
                               f"السعر: `{price}`\n"
                               f"📈 PnL: *{pnl:+.2f}%*\n\n"
                               f"{alert['message']}")
                        try:
                            await ctx.bot.send_message(
                                chat_id=t["chat_id"],
                                text=msg,
                                parse_mode="Markdown",
                            )
                            db.mark_alert_sent(t["id"], alert["type"])
                        except Exception:
                            pass
            except Exception:
                continue
    except Exception:
        pass


# ==================================================
# Telegram Handlers
# ==================================================

async def cmd_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    eth_status = "✅" if ETHERSCAN_KEY not in ("YOUR_ETHERSCAN_KEY_HERE","NO_KEY","") else "❌"
    ai_st = ai_mod.ai_status()
    ai_count = sum(1 for v in ai_st.values() if v)
    whale_st = "✅" if whale_mod.is_available() else "❌"

    await u.message.reply_text(
        "👋 *MAHMOUD TRADING BOT v4 — FULL EDITION*\n\n"
        "📊 *نظام إشارات موزون (0-15):*\n"
        "ICT(3) + MTF(2) + MACD(2) + EMA(2) + Funding(1)\n"
        "+ OI(1) + RSI(1) + L/S(1) + Liq(1) + CVD(1)\n\n"
        f"🧠 AI Brains: {ai_count}/3 مفعّلة "
        f"(C{'✅' if ai_st['claude'] else '❌'} "
        f"G{'✅' if ai_st['gemini'] else '❌'} "
        f"O{'✅' if ai_st['openai'] else '❌'})\n"
        f"⛓ Etherscan: {eth_status} | 🐋 Whale Alert: {whale_st}\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📈 *تحليل فوري:*\n"
        "أرسل: `BTC` / `ETH` / `SOL` / أي عملة\n"
        "`تابع BTC` — تنبيه عند الإشارات القوية ≥12/15\n\n"
        "🧠 *AI Multi-Brain (الجديد!):*\n"
        "`اجماع BTC` — تحليل بـ3 AIs + إجماع\n"
        "`سؤال [نصك]` — اسأل أي شيء\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📰 *الأخبار + التقويم (الجديد):*\n"
        "`أخبار` — آخر 24h | `أخبار BTC` | `عاجل`\n"
        "`تقويم` — أحداث اليوم Macro\n"
        "`تقويم_اسبوع` — كل الأسبوع\n"
        "`ماكرو` — CPI/Yields/توقعات (Massive.com)\n"
        "`اشترك_اخبار` — تنبيهات فورية\n"
        "`اشترك_تقرير 8 0` — تقرير 8 ص\n"
        "`فلتر_عملات BTC,ETH`\n\n"
        "🎯 *Today's View:*\n"
        "`اليوم` — تقرير شامل + Catalysts\n"
        "`كاتاليست` — أهم 3 محركات قادمة\n"
        "`جلسات` — سيناريوهات Asia/EU/US\n"
        "`خطة BTC` — Intraday plan\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🎮 *تتبع الصفقات اليدوية:*\n"
        "`صفقة LONG BTC 43500 42500 44500 45500 46500`\n"
        "`صفقاتي` | `اقفل BTC 43200` | `تعديل BTC sl 42800`\n\n"
        "🛡 *حماية المحفظة:*\n"
        "`حماية` | `حد_يومي 8` | `حد_صفقات 5`\n\n"
        "📊 *دفتر التداول:*\n"
        "`جورنال` — Win Rate / PF / Sharpe\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🐋 *تتبع الحيتان:*\n"
        "`حيتان` — آخر 6h | `حيتان BTC`\n\n"
        "🔬 *Backtest:*\n"
        "`backtest BTC 30` — اختبار على آخر 30 يوم\n\n"
        "📈 *Long-term:*\n"
        "`طويل BTC` — تحليل D1/W1 للـHodlers\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "⚡ *Scalping:* `سكالب BTC` | `تابع سكالب BTC`\n\n"
        "🔍 *الماسح الذكي v4 (~580 عملة Spot+Futures):*\n"
        "`ماسح` — تفعيل (12/15 = 80% قوة)\n"
        "`ماسح 13` — أقوى | `ماسح 9` — أكثر إشارات\n"
        "`ماسح nospot` — فيوتشر فقط (~350)\n"
        "`حالة الماسح` | `وقف ماسح`\n\n"
        "⚠️ _تحليلات تعليمية — البوت لا يفتح صفقات تلقائياً_",
        parse_mode="Markdown")



async def handle_msg(u: Update, c: ContextTypes.DEFAULT_TYPE):
    text    = u.message.text.strip()
    chat_id = u.effective_chat.id
    text_lower = text.lower()

    # ═══════════════════════════════════════════
    # 🎮 أوامر تتبع الصفقات اليدوية (v4)
    # ═══════════════════════════════════════════

    # ── صفقة LONG/SHORT BTC entry sl tp1 tp2 tp3 ──
    if text_lower.startswith("صفقة") or text_lower.startswith("trade"):
        tid, msg = tracker.add_trade_from_text(chat_id, text)
        await u.message.reply_text(msg, parse_mode="Markdown")
        return

    # ── صفقاتي ──
    if text in ("صفقاتي", "trades", "my trades"):
        # نجلب الأسعار للعملات المفتوحة
        trades = db.get_open_trades(chat_id)
        prices = {}
        for t in trades:
            sym = t["symbol"]
            if sym not in prices:
                p = _quick_price(sym)
                if p: prices[sym] = p
        await u.message.reply_text(
            tracker.list_trades_msg(chat_id, prices),
            parse_mode="Markdown")
        return

    # ── اقفل BTC [السعر] ──
    if text_lower.startswith("اقفل") or text_lower.startswith("close"):
        parts = text.split()
        if len(parts) < 2:
            await u.message.reply_text(
                "مثال: `اقفل BTC 43200`\nأو: `اقفل BTC` (بسعر السوق)",
                parse_mode="Markdown")
            return
        sym = parts[1].upper()
        exit_price = None
        if len(parts) >= 3:
            try:
                exit_price = float(parts[2].replace(",", ""))
            except ValueError:
                pass
        # لو ما اعطى سعر، نجلب السعر الحالي
        if exit_price is None:
            sym_full = sym if sym.endswith("USDT") else sym + "USDT"
            exit_price = _quick_price(sym_full)
        if exit_price is None:
            await u.message.reply_text("❌ ابعت السعر يدوياً")
            return
        msg = tracker.close_trade_msg(chat_id, sym, exit_price, "MANUAL")
        await u.message.reply_text(msg, parse_mode="Markdown")
        return

    # ── الغاء BTC (يلغي الصفقة بدون احتساب) ──
    if text_lower.startswith("الغاء صفقة") or text_lower.startswith("الغاء_صفقة"):
        parts = text.split()
        if len(parts) < 2:
            await u.message.reply_text("مثال: `الغاء_صفقة BTC`", parse_mode="Markdown")
            return
        sym = parts[-1].upper()
        if not sym.endswith("USDT"): sym += "USDT"
        trade = db.get_trade_by_symbol(chat_id, sym)
        if not trade:
            await u.message.reply_text(f"⚠️ لا توجد صفقة على {sym}")
            return
        db.cancel_trade(trade["id"])
        await u.message.reply_text(f"✅ تم إلغاء الصفقة #{trade['id']}")
        return

    # ── تعديل BTC sl 42800 ──
    if text_lower.startswith("تعديل") or text_lower.startswith("edit"):
        parts = text.split()
        if len(parts) < 4:
            await u.message.reply_text(
                "مثال: `تعديل BTC sl 42800`\n"
                "الحقول: sl / tp1 / tp2 / tp3",
                parse_mode="Markdown")
            return
        sym = parts[1].upper()
        field = parts[2].lower()
        try:
            value = float(parts[3].replace(",", ""))
        except ValueError:
            await u.message.reply_text("❌ القيمة لازم رقم")
            return
        msg = tracker.modify_trade_msg(chat_id, sym, field, value)
        await u.message.reply_text(msg, parse_mode="Markdown")
        return

    # ═══════════════════════════════════════════
    # 🛡 حماية المحفظة + جورنال (v4)
    # ═══════════════════════════════════════════

    if text in ("حماية", "protection", "risk"):
        await u.message.reply_text(risk.risk_status_msg(chat_id), parse_mode="Markdown")
        return

    if text_lower.startswith("حد_يومي") or text_lower.startswith("حد يومي"):
        try:
            v = float(text.split()[-1])
            await u.message.reply_text(risk.update_daily_limit(chat_id, v))
        except (ValueError, IndexError):
            await u.message.reply_text("مثال: `حد_يومي 8`", parse_mode="Markdown")
        return

    if text_lower.startswith("حد_اسبوعي") or text_lower.startswith("حد اسبوعي"):
        try:
            v = float(text.split()[-1])
            await u.message.reply_text(risk.update_weekly_limit(chat_id, v))
        except (ValueError, IndexError):
            await u.message.reply_text("مثال: `حد_اسبوعي 15`", parse_mode="Markdown")
        return

    if text_lower.startswith("حد_صفقات") or text_lower.startswith("حد صفقات"):
        try:
            v = int(text.split()[-1])
            await u.message.reply_text(risk.update_max_trades(chat_id, v))
        except (ValueError, IndexError):
            await u.message.reply_text("مثال: `حد_صفقات 5`", parse_mode="Markdown")
        return

    if text_lower.startswith("حد_خسائر") or text_lower.startswith("حد خسائر"):
        try:
            v = int(text.split()[-1])
            await u.message.reply_text(risk.update_max_losses(chat_id, v))
        except (ValueError, IndexError):
            await u.message.reply_text("مثال: `حد_خسائر 3`", parse_mode="Markdown")
        return

    if text in ("الغاء_حماية", "الغاء حماية"):
        await u.message.reply_text(risk.disable_protection(chat_id))
        return

    if text in ("تفعيل_حماية", "تفعيل حماية"):
        await u.message.reply_text(risk.enable_protection(chat_id))
        return

    if text in ("تصفير_يومي", "تصفير يومي", "reset daily"):
        await u.message.reply_text(risk.reset_daily(chat_id))
        return

    if text in ("جورنال", "journal", "احصائيات"):
        await u.message.reply_text(risk.journal_msg(chat_id, 30), parse_mode="Markdown")
        return

    if text_lower.startswith("جورنال "):
        try:
            days = int(text.split()[1])
            await u.message.reply_text(
                risk.journal_msg(chat_id, days), parse_mode="Markdown")
        except (ValueError, IndexError):
            await u.message.reply_text("مثال: `جورنال 7` أو `جورنال 90`",
                                        parse_mode="Markdown")
        return

    # ═══════════════════════════════════════════
    # 📰 الأخبار + التقويم + Today's View (الموجة 1)
    # ═══════════════════════════════════════════

    # ── أخبار / أخبار BTC ──
    if text in ("أخبار", "اخبار", "news"):
        await u.message.reply_text(
            news_mod.get_news_msg(hours=24, limit=10),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        return

    if text_lower.startswith("أخبار ") or text_lower.startswith("اخبار "):
        coin = text.split()[-1].upper()
        await u.message.reply_text(
            news_mod.get_news_msg(coin=coin, hours=48, limit=15),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        return

    # ── Health Check (تشخيصي — يفحص كل المكونات) ──
    if text in ("صحة", "health", "تشخيص", "/health"):
        report = ["🏥 *Health Check — v4.2*\n"]

        # ① DB
        try:
            import sqlite3 as _sql
            conn = db.get_conn()
            tbls = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            tbl_names = [t["name"] for t in tbls]
            conn.close()
            expected = ["tracked_trades", "trade_alerts_sent", "risk_protection",
                        "trade_journal", "seen_news", "news_subscribers",
                        "ai_recommendations", "cache_store", "whale_alerts",
                        "scanner_subscribers", "scanner_alerts_sent"]
            missing = [t for t in expected if t not in tbl_names]
            if not missing:
                report.append(f"✅ DB: {len(tbl_names)} جدول (كامل)")
            else:
                report.append(f"⚠️ DB: ناقص {len(missing)} جدول")
                report.append(f"   مفقود: {', '.join(missing)}")
        except Exception as e:
            report.append(f"❌ DB: {type(e).__name__}: {str(e)[:80]}")

        # ② DB Path & Permissions
        try:
            import os as _os
            db_path = db.DB_PATH
            exists = _os.path.exists(db_path)
            writable = _os.access(_os.path.dirname(db_path) or ".", _os.W_OK)
            size = _os.path.getsize(db_path) if exists else 0
            report.append(f"📁 DB Path: `{db_path}`")
            report.append(f"   موجود: {exists} | قابل للكتابة: {writable} | حجم: {size}b")
        except Exception as e:
            report.append(f"⚠️ Path check: {e}")

        # ③ Modules
        mods = [
            ("news_mod", news_mod), ("cal_mod", cal_mod),
            ("today_mod", today_mod), ("ai_mod", ai_mod),
            ("whale_mod", whale_mod), ("bt_mod", bt_mod),
            ("lt_mod", lt_mod), ("signals", signals),
            ("tracker", tracker), ("risk", risk),
        ]
        loaded = sum(1 for _, m in mods if m is not None)
        report.append(f"📦 Modules: {loaded}/{len(mods)} loaded")

        # ④ API Keys
        report.append("🔑 API Keys:")
        report.append(f"   ETHERSCAN_KEY: {'✅' if ETHERSCAN_KEY else '❌'}")
        report.append(f"   MASSIVE_API_KEY: "
                      f"{'✅' if cal_mod.MASSIVE_API_KEY else '❌'}")
        ai_st = ai_mod.ai_status()
        report.append(f"   AI Brains: Claude={'✅' if ai_st['claude'] else '❌'} "
                      f"Gemini={'✅' if ai_st['gemini'] else '❌'} "
                      f"OpenAI={'✅' if ai_st['openai'] else '❌'}")
        report.append(f"   WHALE_ALERT_KEY: "
                      f"{'✅' if whale_mod.is_available() else '❌'}")

        # ⑤ Critical functions
        report.append("🔧 Functions:")
        try:
            j = db.journal_stats(chat_id, 30)
            report.append(f"   journal_stats: ✅ ({j['total']} صفقات)")
        except Exception as e:
            report.append(f"   journal_stats: ❌ {type(e).__name__}: {str(e)[:60]}")

        try:
            n = db.get_recent_news(hours=24, min_impact=0, limit=1)
            report.append(f"   get_recent_news: ✅ ({len(n)} خبر في DB)")
        except Exception as e:
            report.append(f"   get_recent_news: ❌ {type(e).__name__}: {str(e)[:60]}")

        try:
            w = db.get_recent_whales(hours=24, limit=1)
            report.append(f"   get_recent_whales: ✅ ({len(w)} حوت)")
        except Exception as e:
            report.append(f"   get_recent_whales: ❌ {type(e).__name__}: {str(e)[:60]}")

        try:
            s = db.get_scanner_subscriber(chat_id)
            report.append(f"   scanner_subscriber: "
                          f"✅ {'مشترك' if s else 'غير مشترك'}")
        except Exception as e:
            report.append(f"   scanner_subscriber: ❌ {type(e).__name__}: {str(e)[:60]}")

        # نرسل بدون Markdown عشان لا يفشل
        await u.message.reply_text("\n".join(report))
        return

    # ── عاجل (الأخبار العالية التأثير فقط) ──
    if text in ("عاجل", "breaking"):
        await u.message.reply_text(
            news_mod.get_news_msg(hours=12, min_impact=7, limit=10),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        return

    # ── اشتراك في تنبيهات الأخبار ──
    if text in ("اشترك_اخبار", "اشترك اخبار"):
        db.add_subscriber(chat_id, breaking_news=1)
        await u.message.reply_text(
            "✅ *تم تفعيل تنبيهات الأخبار العاجلة*\n\n"
            "هتيجيلك الأخبار اللي تأثيرها ≥7/10\n\n"
            "أوامر:\n"
            "`اشترك_تقرير 8 0` — تقرير صباحي 8:00 UTC\n"
            "`فلتر_عملات BTC,ETH` — فلترة\n"
            "`الغاء_اخبار` — إلغاء",
            parse_mode="Markdown")
        return

    if text in ("الغاء_اخبار", "الغاء اخبار"):
        db.remove_subscriber(chat_id)
        await u.message.reply_text("❌ تم إلغاء الاشتراك في الأخبار")
        return

    # ── اشتراك في التقرير الصباحي ──
    if text_lower.startswith("اشترك_تقرير") or text_lower.startswith("اشترك تقرير"):
        parts = text.split()
        h, m = 8, 0
        try:
            if len(parts) >= 2: h = int(parts[1])
            if len(parts) >= 3: m = int(parts[2])
        except ValueError:
            pass
        db.add_subscriber(chat_id, daily_report=1,
                          report_hour=h, report_minute=m)
        await u.message.reply_text(
            f"✅ تم تفعيل التقرير الصباحي على {h:02d}:{m:02d} UTC")
        return

    # ── فلتر العملات للأخبار ──
    if text_lower.startswith("فلتر_عملات") or text_lower.startswith("فلتر عملات"):
        parts = text.split(maxsplit=1)
        if len(parts) >= 2:
            coins = parts[1].replace(" ", ",")
            db.add_subscriber(chat_id, coins_filter=coins)
            await u.message.reply_text(f"✅ هتجيك الأخبار عن: {coins}")
        else:
            db.add_subscriber(chat_id, coins_filter=None)
            await u.message.reply_text("✅ تم إزالة الفلتر — كل الأخبار")
        return

    # ── تقويم اقتصادي ──
    if text in ("تقويم", "كاليندر", "calendar"):
        await u.message.reply_text(
            cal_mod.calendar_today_msg(), parse_mode="Markdown")
        return

    if text in ("تقويم_اسبوع", "calendar week", "تقويم اسبوع"):
        await u.message.reply_text(
            cal_mod.calendar_week_msg(), parse_mode="Markdown")
        return

    # ── Macro Snapshot من Massive.com (CPI + Yields + Inflation Expectations) ──
    if text in ("ماكرو", "macro", "ماكرو_حالة", "snapshot"):
        await u.message.reply_text(
            cal_mod.fmt_macro_snapshot(), parse_mode="Markdown")
        return

    # ── Top 3 Catalysts ──
    if text in ("كاتاليست", "catalysts", "محركات"):
        await u.message.reply_text(
            today_mod.fmt_top_3_catalysts(), parse_mode="Markdown")
        return

    # ── Today's View / تقرير اليوم ──
    if text in ("اليوم", "تقرير_يومي", "today", "تقرير اليوم"):
        await u.message.reply_text(
            today_mod.today_view_msg(),
            parse_mode="Markdown",
            disable_web_page_preview=True)
        return

    # ── الجلسات ──
    if text in ("جلسات", "sessions"):
        await u.message.reply_text(
            today_mod.session_scenarios_msg(), parse_mode="Markdown")
        return

    # ── خطة Intraday ──
    if text_lower.startswith("intraday") or text_lower.startswith("خطة"):
        parts = text.split()
        sym = parts[-1].upper() if len(parts) > 1 else "BTC"
        if not sym.endswith("USDT"): sym_full = sym + "USDT"
        else: sym_full = sym
        price = _quick_price(sym_full)
        await u.message.reply_text(
            today_mod.intraday_plan_msg(sym, price), parse_mode="Markdown")
        return

    # ═══════════════════════════════════════════
    # 🧠 AI Brains (الموجة 2)
    # ═══════════════════════════════════════════

    # ── تحليل ذكي بـ3 AIs ──
    if text_lower.startswith("تحليل_ذكي") or text_lower.startswith("اجماع") \
       or text_lower.startswith("consensus"):
        if not ai_mod.has_any_ai():
            await u.message.reply_text(
                "❌ لم يتم إعداد أي AI API key\n\n"
                "أضف في Variables:\n"
                "`CLAUDE_API_KEY` و/أو\n"
                "`GEMINI_API_KEY` و/أو\n"
                "`OPENAI_API_KEY`",
                parse_mode="Markdown")
            return
        parts = text.split()
        sym = parts[-1].upper() if len(parts) > 1 else "BTC"
        if not sym.endswith("USDT"): sym += "USDT"

        await u.message.reply_text(
            f"🧠 جاري تحليل {sym} بـ3 AIs...\n_30-60 ثانية_",
            parse_mode="Markdown")

        try:
            R = await run_analysis(sym)
            if R.get("err"):
                await u.message.reply_text(R["err"])
                return

            # نجمع الأخبار + Catalysts
            coin = sym[:-4]  # BTCUSDT → BTC
            news_items = db.get_recent_news(hours=24, coin=coin, limit=5)
            catalysts = today_mod.get_top_3_catalysts()

            # نستدعي الـ3 AIs بشكل غير معلق
            loop = asyncio.get_event_loop()
            cons = await loop.run_in_executor(
                None,
                lambda: ai_mod.get_consensus_recommendation(
                    sym, R, news_items, catalysts))

            # نخزن التوصية
            if cons.get("ok"):
                db.insert_ai_rec(
                    chat_id=chat_id,
                    symbol=sym,
                    action=cons["action"],
                    confidence=cons["confidence"],
                    entry_price=R.get("price", 0),
                    sl=cons.get("sl"),
                    tp1=cons.get("tp1"),
                    tp2=cons.get("tp2"),
                    tp3=cons.get("tp3"),
                    ai_used="consensus",
                    reasoning=" | ".join(cons.get("reasoning", [])[:3]),
                )

            await u.message.reply_text(
                ai_mod.fmt_consensus(sym, cons),
                parse_mode="Markdown")
        except Exception as e:
            await u.message.reply_text(f"❌ خطأ: {str(e)[:100]}")
        return

    # ── سؤال حر ──
    if text_lower.startswith("سؤال") or text_lower.startswith("اسأل"):
        if not ai_mod.has_any_ai():
            await u.message.reply_text("❌ لم يتم إعداد AI keys")
            return
        question = text.split(maxsplit=1)
        if len(question) < 2:
            await u.message.reply_text("مثال: `سؤال متى البتكوين هيوصل 100k؟`",
                                        parse_mode="Markdown")
            return
        q = question[1]
        await u.message.reply_text("🧠 جاري التفكير...")
        try:
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(
                None, lambda: ai_mod.ask_question(q, prefer="consensus"))
            if res.get("ok"):
                txt = res["text"][:3500]
                await u.message.reply_text(
                    f"🧠 *إجابة من {res['primary'].title()}:*\n\n{txt}",
                    parse_mode="Markdown")
            else:
                await u.message.reply_text(f"❌ {res.get('error', 'failed')}")
        except Exception as e:
            await u.message.reply_text(f"❌ {str(e)[:100]}")
        return

    # ═══════════════════════════════════════════
    # 🐋 Whale Alert (الموجة 3)
    # ═══════════════════════════════════════════

    if text in ("حيتان", "whales", "whale"):
        await u.message.reply_text(
            whale_mod.whales_msg(hours=6, limit=15),
            parse_mode="Markdown")
        return

    if text_lower.startswith("حيتان "):
        coin = text.split()[-1].upper()
        if not coin.endswith("USDT"): coin_sym = coin
        else: coin_sym = coin[:-4]
        await u.message.reply_text(
            whale_mod.whales_msg(symbol=coin_sym, hours=24, limit=20),
            parse_mode="Markdown")
        return

    # ═══════════════════════════════════════════
    # 🔬 Backtest (الموجة 3)
    # ═══════════════════════════════════════════

    if text_lower.startswith("backtest") or text_lower.startswith("رجعي"):
        parts = text.split()
        if len(parts) < 2:
            await u.message.reply_text(
                "مثال: `backtest BTC 30` (آخر 30 يوم)\n"
                "أو: `backtest ETH 60 6` (الحد الأدنى 6/8)",
                parse_mode="Markdown")
            return
        sym = parts[1].upper()
        if not sym.endswith("USDT"): sym += "USDT"
        days = 30
        min_score = 6.0
        try:
            if len(parts) >= 3: days = int(parts[2])
            if len(parts) >= 4: min_score = float(parts[3])
        except ValueError:
            pass
        days = max(7, min(days, 90))  # safety

        await u.message.reply_text(
            f"🔬 جاري الـbacktest على {sym}... ({days} يوم)\n_30-60 ثانية_",
            parse_mode="Markdown")
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: bt_mod.run_backtest(sym, days=days,
                                             min_score=min_score))
            await u.message.reply_text(
                bt_mod.fmt_backtest(result), parse_mode="Markdown")
        except Exception as e:
            await u.message.reply_text(f"❌ {str(e)[:120]}")
        return

    # ═══════════════════════════════════════════
    # 📈 Long-term (الموجة 3)
    # ═══════════════════════════════════════════

    if text_lower.startswith("طويل") or text_lower.startswith("long"):
        parts = text.split()
        sym = parts[-1].upper() if len(parts) > 1 else "BTC"
        if not sym.endswith("USDT"): sym += "USDT"
        await u.message.reply_text(f"📊 جاري تحليل {sym} long-term...")
        try:
            loop = asyncio.get_event_loop()
            R = await loop.run_in_executor(
                None, lambda: lt_mod.long_term_analysis(sym))
            await u.message.reply_text(
                lt_mod.fmt_long_term(R), parse_mode="Markdown")
        except Exception as e:
            await u.message.reply_text(f"❌ {str(e)[:120]}")
        return

    # ═══════════════════════════════════════════
    # الأوامر القديمة (متابعة عملة، ماسح، سكالب)
    # ═══════════════════════════════════════════

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
            # استخدم job_queue المدمج (متوافق مع event loop)
            for j in c.job_queue.get_jobs_by_name(jn):
                j.schedule_removal()
            c.job_queue.run_repeating(
                monitor_job, interval=900, first=15,
                data={"chat_id": chat_id, "sym": sym}, name=jn)
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
            f"✅ تنبيه دخول: 5/9 إشارات\n"
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
                for j in c.job_queue.get_jobs_by_name(f"w_{chat_id}_{s}"):
                    j.schedule_removal()
            watching[chat_id]    = {}
            open_trades[chat_id] = {}
            await u.message.reply_text("⛔ تم إيقاف كل المتابعات والصفقات")
        else:
            sym = parts[1].upper()
            if not sym.endswith("USDT"):
                sym += "USDT"
            for j in c.job_queue.get_jobs_by_name(f"w_{chat_id}_{sym}"):
                j.schedule_removal()
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

    # ══ ماسح v4 (Spot + Futures, 80%+ confidence, DB persistence) ══
    if text.startswith("ماسح") or text.lower() == "scanner":
        parts = text.split()
        threshold = 12  # افتراضي = 80% من 15 (الإشارات القوية)
        scan_spot = True

        for p in parts:
            try:
                n = int(p)
                # نقبل قيم بين 7-15 (47%-100%)
                if 7 <= n <= 15:
                    threshold = n
            except ValueError:
                pass
            # خيار: إيقاف السبوت
            if p.lower() in ("nospot", "بدون_سبوت", "futures_only"):
                scan_spot = False

        # 1) سجل في DB (يستمر بعد restart)
        db.subscribe_scanner(chat_id, threshold=threshold,
                             scan_spot=scan_spot,
                             cooldown_hours=4,
                             max_per_cycle=5)

        # 2) جدول الـjob
        jn = f"sc_v4_{chat_id}"
        for j in c.job_queue.get_jobs_by_name(jn):
            j.schedule_removal()
        c.job_queue.run_repeating(
            auto_scanner_v4_job,
            interval=1800,  # كل 30 دقيقة
            first=30,
            data={"chat_id": chat_id},
            name=jn,
        )

        # 3) إحصائيات
        fut_count = len(get_futures_syms())
        spot_count = 0
        if scan_spot:
            spot_only = [s for s in get_spot_syms()
                         if s not in set(get_futures_syms())]
            spot_count = len(spot_only)
        total = fut_count + spot_count
        spot_threshold = max(7, int(round(threshold * 11 / 15)))
        pct = round(threshold / 15 * 100)

        await u.message.reply_text(
            f"🔍 *تم تفعيل الماسح الذكي v4*\n\n"
            f"⏱ كل 30 دقيقة | 📊 {total} عملة\n"
            f"   🔵 فيوتشر: {fut_count} (15 نقطة كاملة)\n"
            f"   🟣 سبوت: {spot_count} (11 نقطة)\n\n"
            f"🎯 *حد الإشارة القوية:*\n"
            f"   • فيوتشر: ≥{threshold}/15 ({pct}%)\n"
            f"   • سبوت: ≥{spot_threshold}/11 (≥80%)\n\n"
            f"*المؤشرات الموزونة (15):*\n"
            f"• ICT/SMC: 3 | MTF: 2 | MACD: 2\n"
            f"• EMA Stack: 2 | RSI: 1 | CVD: 1\n"
            f"• Funding/OI/LS/Liq: 1+1+1+1 _(فيوتشر فقط)_\n\n"
            f"💾 _الاشتراك محفوظ بعد restart_\n"
            f"🛡 *Cooldown:* 4 ساعات لكل عملة\n\n"
            f"`ماسح 13` أقوى | `ماسح 9` أكثر إشارات\n"
            f"`ماسح nospot` فيوتشر فقط\n"
            f"`وقف ماسح` للإيقاف | `حالة الماسح` للتفاصيل",
            parse_mode="Markdown")
        return

    if text in ("وقف ماسح", "stop scanner"):
        # حذف من DB + إيقاف الـjob
        db.unsubscribe_scanner(chat_id)
        jn = f"sc_v4_{chat_id}"
        for j in c.job_queue.get_jobs_by_name(jn):
            j.schedule_removal()
        # إيقاف الماسح القديم لو شغال
        for j in c.job_queue.get_jobs_by_name(f"sc_{chat_id}"):
            j.schedule_removal()
        await u.message.reply_text(
            "⛔ تم إيقاف الماسح + حذف الاشتراك\n"
            "_(`ماسح` لإعادة التفعيل)_",
            parse_mode="Markdown")
        return

    if text in ("حالة الماسح", "حالة_الماسح", "scanner status"):
        sub = db.get_scanner_subscriber(chat_id)
        if not sub:
            await u.message.reply_text(
                "⚠️ الماسح غير مفعّل\n\nأرسل `ماسح` للتفعيل",
                parse_mode="Markdown")
            return
        thr = sub["threshold"]
        scan_spot = bool(sub["scan_spot"])
        cd = sub["cooldown_hours"]
        max_pc = sub["max_per_cycle"]
        started = sub["started_at"]
        fut_n = len(get_futures_syms())
        spot_n = len([s for s in get_spot_syms()
                      if s not in set(get_futures_syms())]) if scan_spot else 0

        await u.message.reply_text(
            f"📊 *حالة الماسح v4:*\n\n"
            f"✅ مفعّل منذ: {started[:19]}\n"
            f"🎯 الحد: {thr}/15 (فيوتشر) | {max(7, int(round(thr*11/15)))}/11 (سبوت)\n"
            f"📊 العملات: {fut_n + spot_n} "
            f"({fut_n} فيوتشر + {spot_n} سبوت)\n"
            f"🛡 Cooldown: {cd} ساعات/عملة\n"
            f"📨 أقصى/دورة: {max_pc} إشارات\n"
            f"⏱ الدورة: كل 30 دقيقة",
            parse_mode="Markdown")
        return

    if text in ("قائمة الماسح",):
        try: lst=scan_lists.get(chat_id,[]) or get_futures_syms()
        except: lst=[]
        m2=f"📋 *الماسح ({len(lst)} عملة):*\n"+" | ".join([f"`{s[:-4]}`" for s in lst[:30]])
        if len(lst)>30: m2+=f"\n... و{len(lst)-30} أخرى"
        await u.message.reply_text(m2,parse_mode="Markdown"); return
    if text.startswith("أضف ") or text.startswith("اضف "):
        raw=text.split(maxsplit=1)[1].upper()
        sym2=raw if raw.endswith("USDT") else raw+"USDT"
        lst=scan_lists.setdefault(chat_id,list(get_futures_syms()))
        if sym2 not in lst: lst.append(sym2)
        await u.message.reply_text(f"✅ أضفت `{sym2}`",parse_mode="Markdown"); return
    if text.startswith("احذف "):
        raw=text.split(maxsplit=1)[1].upper()
        sym2=raw if raw.endswith("USDT") else raw+"USDT"
        lst=scan_lists.setdefault(chat_id,list(get_futures_syms()))
        if sym2 in lst: lst.remove(sym2)
        await u.message.reply_text(f"✅ حذفت `{sym2}`",parse_mode="Markdown"); return

    # ══ سكالب ══
    if text.startswith("سكالب") or text.lower().startswith("scalp"):
        parts=text.split()
        sym2=resolve_sym(parts[1]) if len(parts)>1 else "BTCUSDT"
        wait2=await u.message.reply_text(f"⚡ جاري تحليل Scalp *{sym2}*...",parse_mode="Markdown")
        loop=asyncio.get_event_loop()
        try:
            R2=await asyncio.wait_for(loop.run_in_executor(None,analyze_scalp,sym2),timeout=30)
            await wait2.delete()
            await u.message.reply_text(build_scalp(R2),parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 تحديث",callback_data=f"s:{sym2}"),
                    InlineKeyboardButton("📊 تحليل",callback_data=f"r:{sym2}"),
                ]]))
        except Exception as e:
            await wait2.edit_text(f"❌ {str(e)[:80]}")
        return

    if text.startswith("تابع سكالب"):
        parts=text.split()
        sym2=resolve_sym(parts[2]) if len(parts)>2 else "BTCUSDT"
        jn=f"ss_{chat_id}_{sym2}"
        for j in c.job_queue.get_jobs_by_name(jn): j.schedule_removal()
        c.job_queue.run_repeating(scalp_monitor_job,interval=300,first=10,
            data={"chat_id":chat_id,"sym":sym2},name=jn)
        await u.message.reply_text(f"⚡ تابع Scalp *{sym2}* كل 5 دقائق",parse_mode="Markdown"); return

    if text.startswith("وقف سكالب"):
        parts=text.split()
        sym2=resolve_sym(parts[2]) if len(parts)>2 else ""
        if sym2:
            jn=f"ss_{chat_id}_{sym2}"
            for j in c.job_queue.get_jobs_by_name(jn): j.schedule_removal()
            await u.message.reply_text(f"⛔ وقف Scalp {sym2}"); return

        # ── تحليل فوري ──
    if not text or len(text) > 15:
        await u.message.reply_text(
            "أرسل اسم العملة مثل: `BTC`", parse_mode="Markdown")
        return

    sym = resolve_sym(text)

    wait = await u.message.reply_text(
        f"⏳ جاري تحليل *{sym}*\n(9 مؤشرات + 4 فريمات شموع)...",
        parse_mode="Markdown")
    R = await run_analysis(sym)
    await wait.delete()
    await u.message.reply_text(
        build_entry(R), parse_mode="Markdown", reply_markup=kb(sym))


async def handle_btn(u: Update, c: ContextTypes.DEFAULT_TYPE):
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
    """يسجل تفاصيل الخطأ + يكشف نوعه للمستخدم لأغراض التشخيص"""
    err = context.error
    err_type = type(err).__name__
    err_msg = str(err)[:300]

    # Traceback كامل للـlog
    import traceback as _tb
    tb_str = "".join(_tb.format_exception(type(err), err, err.__traceback__))
    logging.error(f"Bot error [{err_type}]: {err_msg}")
    logging.error(f"Traceback:\n{tb_str[:2000]}")

    # تفاصيل الـupdate
    user_text = ""
    chat_id = "?"
    try:
        if update and hasattr(update, 'effective_message') and update.effective_message:
            user_text = (update.effective_message.text or "")[:80]
        if update and hasattr(update, 'effective_chat') and update.effective_chat:
            chat_id = update.effective_chat.id
        logging.error(f"  ↳ Failed input: '{user_text}' (chat={chat_id})")
    except Exception:
        pass

    # محاولة إرسال رسالة تشخيصية (بدون Markdown)
    try:
        if update and hasattr(update, 'effective_message') and update.effective_message:
            # نرسل تفاصيل تشخيصية مفيدة بدون Markdown parsing
            diag = (
                f"⚠️ خطأ في تنفيذ الأمر\n\n"
                f"الأمر: {user_text}\n"
                f"النوع: {err_type}\n"
                f"التفاصيل: {err_msg[:180]}"
            )
            await update.effective_message.reply_text(
                diag,
                disable_web_page_preview=True,
            )
    except Exception as send_err:
        logging.error(f"  ↳ Even error reply failed: {send_err}")


# ==================================================
# Run
# ==================================================

async def _post_init(app):
    """يشتغل بعد ما البوت يبدأ الـ event loop — يحذف webhook قديم ويفحص Etherscan + ينشئ DB"""
    # ① حذف أي webhook قديم — يمنع Conflict
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.warning(f"delete_webhook failed: {e}")

    # ② إعداد قاعدة البيانات
    try:
        db.init_db()
        logging.info("DB initialized successfully")
    except Exception as e:
        logging.error(f"DB init failed: {e}")

    # ③ فحص Etherscan فعلياً
    eth_status = "❌ غير مفعّل"
    if ETHERSCAN_KEY:
        try:
            r = session.get(
                ETH_API,
                params={
                    "chainid": ETH_CHAIN,
                    "module": "stats",
                    "action": "ethsupply",
                    "apikey": ETHERSCAN_KEY,
                },
                timeout=(5, 10),
            )
            j = r.json()
            if j.get("status") == "1":
                eth_status = "✅ مفعّل"
            else:
                eth_status = f"⚠️ {j.get('message', 'unknown')}"
        except Exception as e:
            eth_status = f"⚠️ {type(e).__name__}"

    # ④ عدد الصفقات المفتوحة (للإحصائيات)
    open_count = 0
    try:
        open_count = len(db.get_open_trades())
    except Exception:
        pass

    # ⑤ فحص الـAI Brains
    ai_st = ai_mod.ai_status()
    ai_count = sum(1 for v in ai_st.values() if v)

    # ⑥ Whale Alert
    whale_status = "✅ مفعّل" if whale_mod.is_available() else "❌ غير مفعّل"

    # ⑦ News (RSS)
    news_status = "✅ feedparser" if news_mod.HAS_FEEDPARSER else "❌ feedparser ناقص"

    # ⑧ Calendar (Massive.com)
    cal_status = "✅ Massive.com" if cal_mod.MASSIVE_API_KEY else "❌ غير مفعّل"

    # ⑨ عدد المشتركين في الأخبار
    try:
        sub_count = len(db.get_breaking_subscribers(0))
    except Exception:
        sub_count = 0

    # ⑩ المشتركون في الماسح v4 — جدول الـjobs لكل واحد
    scanner_subs = []
    try:
        scanner_subs = db.get_scanner_subscribers()
        for sub in scanner_subs:
            cid = sub["chat_id"]
            jn = f"sc_v4_{cid}"
            for j in app.job_queue.get_jobs_by_name(jn):
                j.schedule_removal()
            app.job_queue.run_repeating(
                auto_scanner_v4_job,
                interval=1800,  # كل 30 دقيقة
                first=60,        # أول دورة بعد دقيقة من البداية
                data={"chat_id": cid},
                name=jn,
            )
        if scanner_subs:
            logging.info(f"Loaded {len(scanner_subs)} scanner subscribers")
    except Exception as e:
        logging.error(f"Failed to load scanner subscribers: {e}")

    print("=" * 60)
    print("  MAHMOUD TRADING BOT v4 — FULL EDITION ✅")
    print("=" * 60)
    print(f"  Core Engine:")
    print(f"  ├ Scoring  : موزون 0-15 (إشارة قوية ≥12)")
    print(f"  ├ مؤشرات  : ICT+MTF+MACD+EMA+Funding+OI+RSI+L/S+Liq+CVD")
    print(f"  └ Auto-Entry: ❌ ملغى (إشارات فقط)")
    print(f"")
    print(f"  Wave 0 — Core:")
    print(f"  ├ Etherscan : {eth_status}")
    print(f"  ├ التتبع    : ✅ SQLite ({open_count} صفقات مفتوحة)")
    print(f"  └ الحماية   : ✅ مفعّلة (حدود يومية + جورنال)")
    print(f"")
    print(f"  Wave 1 — News + Calendar:")
    print(f"  ├ RSS Feeds : {news_status} (9 مصادر)")
    print(f"  ├ Calendar  : {cal_status}")
    print(f"  ├ Today View: ✅ Sessions+Catalysts")
    print(f"  └ المشتركون : {sub_count}")
    print(f"")
    print(f"  Wave 2 — AI Brains: {ai_count}/3")
    print(f"  ├ Claude    : {'✅' if ai_st['claude'] else '❌'}")
    print(f"  ├ Gemini    : {'✅' if ai_st['gemini'] else '❌'}")
    print(f"  └ OpenAI    : {'✅' if ai_st['openai'] else '❌'}")
    print(f"")
    print(f"  Wave 3 — Power Tools:")
    print(f"  ├ Whale Alert: {whale_status}")
    print(f"  ├ Backtest   : ✅ مفعّل")
    print(f"  ├ Long-term  : ✅ D1+W1 مع Bollinger")
    print(f"  └ Bollinger  : ✅ مدمج في SIGNALS")
    print(f"")
    print(f"  Auto Scanner v4: ✅ مفعّل ({len(scanner_subs)} مشترك)")
    print(f"  ├ النطاق     : Spot + Futures (~580 عملة)")
    print(f"  ├ الحد       : 80%+ (12/15 فيوتشر، 9/11 سبوت)")
    print(f"  └ الدورة     : كل 30 دقيقة")
    print("=" * 60)
    print("  أرسل /start على تيليقرام")
    print("=" * 60)


def main():
    if BOT_TOKEN in ("YOUR_BOT_TOKEN_HERE", ""):
        print("=" * 50)
        print("  ERROR: لم يتم إدخال Bot Token")
        print("  أضفه في Railway → Variables → BOT_TOKEN")
        print("=" * 50)
        return

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_btn))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_msg))
    app.add_error_handler(error_handler)

    # ═══════════════════════════════════════════
    # Background Jobs (v4)
    # ═══════════════════════════════════════════
    # ① مراقبة سريعة كل 60 ثانية للصفقات المتتبعة (SL/TP/NEAR)
    app.job_queue.run_repeating(
        tracked_monitor_job,
        interval=60,
        first=30,
        name="tracked_monitor",
    )
    # ② تحليل عميق كل 5 دقائق للصفقات المفتوحة (Reversal/Add)
    app.job_queue.run_repeating(
        tracked_deep_analysis_job,
        interval=300,
        first=120,
        name="tracked_deep_analysis",
    )

    # ③ فحص الأخبار كل 15 دقيقة (RSS من 9 مصادر + breaking alerts)
    app.job_queue.run_repeating(
        news_mod.news_check_job,
        interval=900,
        first=60,
        name="news_check",
    )

    # ④ Whale Alert كل 10 دقائق (لو الـAPI key متاح)
    if whale_mod.is_available():
        app.job_queue.run_repeating(
            whale_mod.whale_check_job,
            interval=600,
            first=120,
            name="whale_check",
        )

    # ⑤ التقرير الصباحي — يفحص كل دقيقة لو فيه مشتركين بالتوقيت ده
    app.job_queue.run_repeating(
        today_mod.daily_report_job,
        interval=60,
        first=30,
        name="daily_report",
    )

    # ملاحظة: ما نستخدم AsyncIOScheduler — JobQueue المدمج كافٍ ومتوافق مع event loop
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
