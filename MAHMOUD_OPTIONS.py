"""
MAHMOUD_OPTIONS.py — v5.1 Options Suite (Greeks + Strategies + Signals)
═══════════════════════════════════════════════════════════════════════════
Comprehensive Options Analysis للكريبتو:

1. **Greeks Calculator** (Black-Scholes):
   • Delta — حساسية السعر للأصل الأساسي
   • Gamma — تسارع الـDelta
   • Theta — تآكل القيمة الزمنية (يومياً)
   • Vega — حساسية التقلب الضمني
   • Rho — حساسية معدل الفائدة (نادراً مهم للكريبتو)

2. **Real-time Data**:
   • Deribit (الأساسي - BTC/ETH/SOL، API مجاني بدون auth)
   • OKX (احتياطي - BTC/ETH، يحتاج API key للـoptions)
   • Auto-fallback بين البورصتين

3. **Options Chain Analysis**:
   • Open Interest distribution
   • Put/Call Ratio
   • IV Rank (هل التقلب عالي أو منخفض؟)
   • Skew (السوق يتوقع صعود/هبوط؟)
   • Max Pain (نقطة ألم Market Makers)
   • Top OI strikes

4. **Strategy Builder**:
   • Bull Call Spread
   • Bear Put Spread
   • Long Straddle (تذبذب)
   • Long Strangle (تذبذب أرخص)
   • Iron Condor (range-bound)
   • Covered Call

5. **Options Signals**:
   • متى تشتري Call vs Put؟
   • هل الـIV غالي أو رخيص؟
   • أي expiry الأفضل؟
═══════════════════════════════════════════════════════════════════════════
"""

import os
import math
import logging
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────
# Constants & Config
# ─────────────────────────────────────────────

DERIBIT_BASE = "https://www.deribit.com/api/v2"
OKX_BASE = "https://www.okx.com/api/v5"
HTTP_TIMEOUT = 15

# User-Agent عشان نتجنب blocks من الـAPI
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# Deribit يدعم: BTC, ETH, SOL (وقد يضيف المزيد)
DERIBIT_CURRENCIES = ["BTC", "ETH", "SOL"]

# OKX options يدعم: BTC, ETH أساساً
OKX_CURRENCIES = ["BTC", "ETH"]

# Binance Futures (للحصول على Realized Volatility لأي عملة)
BINANCE_FUTURES_BASE = "https://fapi.binance.com/fapi/v1"
BINANCE_SPOT_BASE = "https://api.binance.com/api/v3"

# OKX API credentials (اختياري - public market data ما يحتاج auth)
OKX_API_KEY = os.environ.get("OKX_API_KEY", "")
OKX_SECRET = os.environ.get("OKX_API_SECRET", "")
OKX_PASSPHRASE = os.environ.get("OKX_API_PASSPHRASE", "")


# ─────────────────────────────────────────────
# Black-Scholes Greeks (Backup Calculator)
# ─────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    """دالة التوزيع التراكمي الطبيعي (Standard Normal CDF)"""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x: float) -> float:
    """دالة الكثافة الاحتمالية الطبيعية (Standard Normal PDF)"""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def black_scholes_greeks(S: float, K: float, T: float,
                         r: float = 0.0, sigma: float = 0.5,
                         option_type: str = "call") -> Dict:
    """
    Black-Scholes Greeks Calculator.

    Parameters:
    - S: السعر الحالي للأصل
    - K: سعر التنفيذ (Strike)
    - T: الوقت المتبقي بالسنوات (e.g., 30 days = 30/365)
    - r: معدل الفائدة الخالي من المخاطر (للكريبتو ≈ 0)
    - sigma: التقلب الضمني (IV) كنسبة عشرية (e.g., 0.65 = 65%)
    - option_type: "call" أو "put"

    Returns dict with: price, delta, gamma, theta, vega, rho
    """
    try:
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            return {"error": "invalid inputs"}

        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        if option_type.lower() == "call":
            price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
            delta = _norm_cdf(d1)
            theta = (-(S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T))
                     - r * K * math.exp(-r * T) * _norm_cdf(d2)) / 365
            rho = K * T * math.exp(-r * T) * _norm_cdf(d2) / 100
        else:  # put
            price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
            delta = _norm_cdf(d1) - 1
            theta = (-(S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T))
                     + r * K * math.exp(-r * T) * _norm_cdf(-d2)) / 365
            rho = -K * T * math.exp(-r * T) * _norm_cdf(-d2) / 100

        # Gamma و Vega نفس الصيغة لـCall و Put
        gamma = _norm_pdf(d1) / (S * sigma * math.sqrt(T))
        vega = S * _norm_pdf(d1) * math.sqrt(T) / 100  # per 1% IV change

        return {
            "ok": True,
            "price": round(price, 4),
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "theta": round(theta, 4),
            "vega": round(vega, 4),
            "rho": round(rho, 4),
            "d1": round(d1, 4),
            "d2": round(d2, 4),
        }
    except Exception as e:
        return {"error": str(e)[:100]}


# ─────────────────────────────────────────────
# Deribit API (الأساسي)
# ─────────────────────────────────────────────

def deribit_get(endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """جلب بيانات من Deribit Public API"""
    url = f"{DERIBIT_BASE}{endpoint}"
    try:
        r = requests.get(url, params=params or {},
                         headers=DEFAULT_HEADERS, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            logging.warning(f"Deribit {endpoint} returned {r.status_code}: {r.text[:100]}")
            return None
        data = r.json()
        if "result" in data:
            return data["result"]
        return data
    except Exception as e:
        logging.warning(f"Deribit {endpoint} error: {e}")
        return None


def deribit_get_index(currency: str) -> Optional[float]:
    """يجلب السعر الحالي للـindex (BTC/ETH/SOL)"""
    result = deribit_get("/public/get_index_price",
                         {"index_name": f"{currency.lower()}_usd"})
    if result and "index_price" in result:
        return float(result["index_price"])
    return None


def deribit_get_instruments(currency: str,
                            kind: str = "option",
                            expired: bool = False) -> List[Dict]:
    """يجلب كل instruments المتاحة (options) لعملة معينة"""
    result = deribit_get("/public/get_instruments", {
        "currency": currency.upper(),
        "kind": kind,
        "expired": "true" if expired else "false",
    })
    return result if isinstance(result, list) else []


def deribit_get_book_summary(currency: str,
                             kind: str = "option") -> List[Dict]:
    """يجلب ملخص order book لكل instruments — يحتوي على IV, Greeks, OI"""
    result = deribit_get("/public/get_book_summary_by_currency", {
        "currency": currency.upper(),
        "kind": kind,
    })
    return result if isinstance(result, list) else []


def deribit_get_ticker(instrument: str) -> Optional[Dict]:
    """يجلب ticker كامل لعقد معين (مع Greeks)"""
    return deribit_get("/public/ticker", {"instrument_name": instrument})


# ─────────────────────────────────────────────
# OKX API (احتياطي)
# ─────────────────────────────────────────────

def okx_get(endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """جلب بيانات من OKX Public API"""
    url = f"{OKX_BASE}{endpoint}"
    try:
        r = requests.get(url, params=params or {},
                         headers=DEFAULT_HEADERS, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get("code") == "0":
            return data.get("data")
        return None
    except Exception as e:
        logging.warning(f"OKX {endpoint} error: {e}")
        return None


def okx_get_options_instruments(currency: str) -> List[Dict]:
    """يجلب كل options instruments من OKX"""
    result = okx_get("/public/instruments", {
        "instType": "OPTION",
        "uly": f"{currency.upper()}-USD",
    })
    return result if isinstance(result, list) else []


def okx_get_index(currency: str) -> Optional[float]:
    """يجلب index price من OKX"""
    result = okx_get("/market/index-tickers", {
        "instId": f"{currency.upper()}-USD"
    })
    if result and len(result) > 0:
        try:
            return float(result[0].get("idxPx", 0))
        except (ValueError, TypeError):
            return None
    return None


def okx_get_options_summary(currency: str,
                            expiry: Optional[str] = None) -> List[Dict]:
    """يجلب ملخص options chain من OKX"""
    params = {
        "instType": "OPTION",
        "uly": f"{currency.upper()}-USD",
    }
    if expiry:
        params["expTime"] = expiry
    result = okx_get("/public/opt-summary", params)
    return result if isinstance(result, list) else []


# ─────────────────────────────────────────────
# Binance Fetcher (للـRealized Volatility + سعر العملات)
# ─────────────────────────────────────────────

def binance_get_klines(symbol: str, interval: str = "1d",
                       limit: int = 30) -> List[List]:
    """
    يجلب klines من Binance Futures (مع Spot fallback).
    يرجع: [[time, open, high, low, close, volume, ...], ...]
    """
    sym = symbol.upper()
    if not sym.endswith("USDT"):
        sym += "USDT"

    # نجرب Futures أولاً
    for url in [f"{BINANCE_FUTURES_BASE}/klines", f"{BINANCE_SPOT_BASE}/klines"]:
        try:
            r = requests.get(url,
                             params={"symbol": sym, "interval": interval,
                                     "limit": limit},
                             headers=DEFAULT_HEADERS,
                             timeout=HTTP_TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception:
            continue
    return []


def binance_get_price(symbol: str) -> Optional[float]:
    """يجلب السعر الحالي من Binance"""
    sym = symbol.upper()
    if not sym.endswith("USDT"):
        sym += "USDT"

    for url in [f"{BINANCE_FUTURES_BASE}/ticker/price",
                f"{BINANCE_SPOT_BASE}/ticker/price"]:
        try:
            r = requests.get(url,
                             params={"symbol": sym},
                             headers=DEFAULT_HEADERS,
                             timeout=HTTP_TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                if "price" in data:
                    return float(data["price"])
        except Exception:
            continue
    return None


# ─────────────────────────────────────────────
# Realized Volatility (للـSynthetic IV)
# ─────────────────────────────────────────────

def calc_realized_volatility(symbol: str, days: int = 30) -> Optional[Dict]:
    """
    يحسب التقلب التاريخي (Realized Volatility) من Binance.

    الطريقة:
    1. نجلب آخر N يوم من klines
    2. نحسب daily log returns
    3. Std dev للـreturns × √365 = annualized volatility

    Returns:
    {
        "ok": bool,
        "symbol": "SOL",
        "rv_daily": 0.045,          # 4.5% daily
        "rv_annualized": 0.86,      # 86% annual
        "rv_pct": 86.0,
        "days_used": 30,
        "current_price": 200.5,
    }
    """
    try:
        klines = binance_get_klines(symbol, interval="1d", limit=days + 1)
        if len(klines) < days // 2:
            return {"ok": False, "error": "بيانات غير كافية من Binance"}

        # نأخذ closes فقط
        closes = [float(k[4]) for k in klines]
        if len(closes) < 5:
            return {"ok": False, "error": "بيانات قليلة جداً"}

        # نحسب log returns
        log_returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0 and closes[i] > 0:
                log_returns.append(math.log(closes[i] / closes[i - 1]))

        if len(log_returns) < 5:
            return {"ok": False, "error": "returns قليلة"}

        # Standard deviation
        mean_r = sum(log_returns) / len(log_returns)
        variance = sum((r - mean_r) ** 2 for r in log_returns) / (len(log_returns) - 1)
        std_daily = math.sqrt(variance)

        # Annualized (×√365 لأن الكريبتو 24/7)
        std_annualized = std_daily * math.sqrt(365)

        return {
            "ok": True,
            "symbol": symbol.upper().replace("USDT", ""),
            "rv_daily": round(std_daily, 4),
            "rv_annualized": round(std_annualized, 4),
            "rv_pct": round(std_annualized * 100, 2),
            "days_used": len(log_returns),
            "current_price": closes[-1],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:100]}


# ─────────────────────────────────────────────
# Auto-Discovery (يكتشف العملات المدعومة من Deribit/OKX)
# ─────────────────────────────────────────────

_DISCOVERED_CURRENCIES = None  # cache


def discover_currencies(force_refresh: bool = False) -> Dict[str, List[str]]:
    """
    يكتشف العملات المدعومة فعلياً في Deribit/OKX (live).
    يـcache النتيجة.

    Returns: {"deribit": [...], "okx": [...]}
    """
    global _DISCOVERED_CURRENCIES

    if _DISCOVERED_CURRENCIES is not None and not force_refresh:
        return _DISCOVERED_CURRENCIES

    deribit_currs = []
    okx_currs = []

    # Deribit: نستعلم كل العملات
    try:
        result = deribit_get("/public/get_currencies")
        if isinstance(result, list):
            deribit_currs = sorted([
                c.get("currency", "") for c in result
                if c.get("currency")
            ])
    except Exception:
        deribit_currs = DERIBIT_CURRENCIES.copy()

    # OKX: نسجّل قائمة معروفة (الـAPI يحتاج لكل عملة طلب منفصل)
    okx_currs = OKX_CURRENCIES.copy()

    _DISCOVERED_CURRENCIES = {
        "deribit": deribit_currs or DERIBIT_CURRENCIES.copy(),
        "okx": okx_currs,
    }
    return _DISCOVERED_CURRENCIES


# ─────────────────────────────────────────────
# Synthetic Options (لأي عملة - باستخدام RV من Binance)
# ─────────────────────────────────────────────

def get_synthetic_chain(currency: str,
                        days_list: List[int] = None) -> Dict:
    """
    يبني options chain "synthetic" لأي عملة.

    الفكرة:
    1. نجلب RV من Binance (30 يوم)
    2. نضيف premium مناسب (RV × 1.15 ≈ IV typical)
    3. نولّد strikes حول السعر الحالي (-30%, -20%, -10%, ATM, +10%, +20%, +30%)
    4. نحسب Greeks لكل strike لكل expiry بـBlack-Scholes

    Returns: نفس structure كـreal chain لكن مع flag synthetic=True
    """
    if days_list is None:
        days_list = [7, 14, 30, 60, 90]

    # ① نحصل على RV
    rv_data = calc_realized_volatility(currency, days=30)
    if not rv_data.get("ok"):
        return {"ok": False, "error": rv_data.get("error", "RV failed"),
                "synthetic": True}

    spot = rv_data["current_price"]
    rv_annual = rv_data["rv_annualized"]

    # ② IV synthetic = RV × 1.15 (premium typical في options vs realized)
    iv_synthetic = rv_annual * 1.15
    iv_synthetic = max(0.20, min(3.0, iv_synthetic))  # clamp 20%-300%

    # ③ نولّد strikes
    strike_pcts = [-30, -20, -10, -5, 0, 5, 10, 20, 30]

    # نقرّب strikes حسب السعر
    if spot > 10000:
        round_to = 1000
    elif spot > 1000:
        round_to = 100
    elif spot > 100:
        round_to = 10
    elif spot > 10:
        round_to = 1
    elif spot > 1:
        round_to = 0.1
    else:
        round_to = 0.01

    strikes = []
    for pct in strike_pcts:
        raw = spot * (1 + pct / 100)
        rounded = round(raw / round_to) * round_to
        strikes.append(round(rounded, 8))
    strikes = sorted(set(strikes))

    # ④ نحسب Greeks لكل strike × expiry
    calls = []
    puts = []
    expiries_used = []

    for days in days_list:
        T = days / 365
        expiry_label = f"{days}D"
        expiries_used.append(expiry_label)

        # IV varies slightly with maturity (term structure)
        # Short-term IV عادة أعلى قليلاً
        if days <= 14:
            iv_use = iv_synthetic * 1.05
        elif days >= 60:
            iv_use = iv_synthetic * 0.95
        else:
            iv_use = iv_synthetic

        for K in strikes:
            # Call
            g_call = black_scholes_greeks(spot, K, T, r=0.0,
                                           sigma=iv_use, option_type="call")
            if g_call.get("ok"):
                calls.append({
                    "strike": K,
                    "expiry": expiry_label,
                    "instrument": f"{currency}-{expiry_label}-{int(K)}-C",
                    "iv": round(iv_use, 4),
                    "iv_pct": round(iv_use * 100, 2),
                    "delta": g_call["delta"],
                    "gamma": g_call["gamma"],
                    "theta": g_call["theta"],
                    "vega": g_call["vega"],
                    "mark": g_call["price"],
                    "bid": 0,
                    "ask": 0,
                    "oi": 0,        # synthetic: no real OI
                    "volume": 0,
                })

            # Put
            g_put = black_scholes_greeks(spot, K, T, r=0.0,
                                          sigma=iv_use, option_type="put")
            if g_put.get("ok"):
                puts.append({
                    "strike": K,
                    "expiry": expiry_label,
                    "instrument": f"{currency}-{expiry_label}-{int(K)}-P",
                    "iv": round(iv_use, 4),
                    "iv_pct": round(iv_use * 100, 2),
                    "delta": g_put["delta"],
                    "gamma": g_put["gamma"],
                    "theta": g_put["theta"],
                    "vega": g_put["vega"],
                    "mark": g_put["price"],
                    "bid": 0,
                    "ask": 0,
                    "oi": 0,
                    "volume": 0,
                })

    return {
        "ok": True,
        "currency": currency.upper().replace("USDT", ""),
        "exchange": "synthetic",
        "spot_price": spot,
        "expiries": expiries_used,
        "calls": sorted(calls, key=lambda x: (x["expiry"], x["strike"])),
        "puts": sorted(puts, key=lambda x: (x["expiry"], x["strike"])),
        "total_call_oi": 0,
        "total_put_oi": 0,
        "put_call_ratio": 0,
        "synthetic": True,
        "rv_data": rv_data,
        "iv_used": round(iv_synthetic, 4),
        "iv_used_pct": round(iv_synthetic * 100, 2),
    }


def get_supported_currency(currency: str) -> Tuple[str, str]:
    """
    يحدد أي بورصة تدعم العملة:
    Returns: (currency_upper, exchange) - exchange = 'deribit' or 'okx'
    """
    cur = currency.upper().replace("USDT", "").replace("USD", "")

    # Deribit أولاً (أكثر بيانات)
    if cur in DERIBIT_CURRENCIES:
        return cur, "deribit"
    if cur in OKX_CURRENCIES:
        return cur, "okx"

    return cur, "none"


# ─────────────────────────────────────────────
# Get Options Chain (Unified)
# ─────────────────────────────────────────────

def get_options_chain(currency: str,
                      expiry_filter: Optional[str] = None,
                      allow_synthetic: bool = True) -> Dict:
    """
    يجلب options chain موحّد بـsmart routing:
    1. يحاول Deribit (لو مدعوم)
    2. ثم OKX (لو مدعوم)
    3. ثم Synthetic (Black-Scholes من Binance RV)

    Args:
        currency: العملة (BTC, ETH, SOL, ADA, ANY)
        expiry_filter: للـreal options فقط
        allow_synthetic: لو False، يرجع error إذا ما فيه real options

    Returns:
    {
        "ok": bool,
        "currency": "BTC",
        "exchange": "deribit" | "okx" | "synthetic",
        "spot_price": 43500.0,
        "synthetic": False,  # True لو Black-Scholes
        ...
    }
    """
    cur = currency.upper().replace("USDT", "").replace("USD", "")

    # ① حاول Deribit
    if cur in DERIBIT_CURRENCIES:
        chain = _get_deribit_chain(cur, expiry_filter)
        if chain.get("ok") and len(chain.get("calls", [])) > 0:
            chain["synthetic"] = False
            return chain

    # ② حاول OKX
    if cur in OKX_CURRENCIES:
        chain = _get_okx_chain(cur, expiry_filter)
        if chain.get("ok") and len(chain.get("calls", [])) > 0:
            chain["synthetic"] = False
            return chain

    # ③ Synthetic fallback (لأي عملة)
    if allow_synthetic:
        synthetic_chain = get_synthetic_chain(cur)
        if synthetic_chain.get("ok"):
            return synthetic_chain
        return {
            "ok": False,
            "error": f"❌ {cur}: ما قدرت أجلب أي بيانات\n"
                     f"السبب: {synthetic_chain.get('error', 'unknown')}\n\n"
                     f"تأكد إن العملة موجودة على Binance",
        }

    return {
        "ok": False,
        "error": f"عملة {cur} ما تدعم real options\n"
                 f"المدعومة فعلياً: {', '.join(set(DERIBIT_CURRENCIES + OKX_CURRENCIES))}\n"
                 f"للحصول على Greeks synthetic، استخدم بدون allow_synthetic=False"
    }


def _get_deribit_chain(currency: str,
                       expiry_filter: Optional[str] = None) -> Dict:
    """يبني options chain من Deribit"""
    spot = deribit_get_index(currency)
    if spot is None:
        return {"ok": False, "error": "فشل جلب السعر من Deribit"}

    # Book summary يحتوي على كل ما نحتاج
    summary = deribit_get_book_summary(currency, kind="option")
    if not summary:
        return {"ok": False, "error": "Deribit: لا توجد options"}

    calls = []
    puts = []
    expiries_set = set()
    total_call_oi = 0.0
    total_put_oi = 0.0

    for s in summary:
        instr = s.get("instrument_name", "")
        # شكل instrument: BTC-3MAY26-45000-C
        parts = instr.split("-")
        if len(parts) != 4:
            continue

        try:
            cur_part, expiry_part, strike_str, type_part = parts
            strike = float(strike_str)
            opt_type = type_part.upper()  # 'C' or 'P'
        except (ValueError, IndexError):
            continue

        # Filter by expiry لو محدد
        if expiry_filter and expiry_part != expiry_filter:
            continue

        expiries_set.add(expiry_part)

        # نجلب ticker للحصول على Greeks
        ticker = deribit_get_ticker(instr)

        if not ticker:
            continue

        greeks_data = ticker.get("greeks", {}) or {}
        oi = float(s.get("open_interest", 0) or 0)
        volume_24h = float(s.get("volume", 0) or 0)
        iv = float(ticker.get("mark_iv", 0) or 0) / 100  # نسبة عشرية
        # ⚠️ Deribit يرجع الأسعار بـunits العملة الأساسية (BTC/ETH/SOL)
        # مثال: mark_price = 0.0111 BTC = 0.0111 × spot USD
        mark_price_native = float(ticker.get("mark_price", 0) or 0)
        bid_native = float(s.get("bid_price", 0) or 0)
        ask_native = float(s.get("ask_price", 0) or 0)

        # نحوّل للدولار
        mark_price_usd = mark_price_native * spot
        bid_usd = bid_native * spot
        ask_usd = ask_native * spot

        # Greeks:
        # • Delta و Gamma → ratios (لا تحتاج تحويل)
        # • Theta و Vega → بـunits العملة (تحتاج × spot للحصول على USD)
        delta_raw = float(greeks_data.get("delta", 0) or 0)
        gamma_raw = float(greeks_data.get("gamma", 0) or 0)
        theta_native = float(greeks_data.get("theta", 0) or 0)
        vega_native = float(greeks_data.get("vega", 0) or 0)

        # نحول Theta و Vega لـUSD
        theta_usd = theta_native * spot
        vega_usd = vega_native * spot

        opt_data = {
            "strike": strike,
            "expiry": expiry_part,
            "instrument": instr,
            "iv": round(iv, 4),
            "iv_pct": round(iv * 100, 2),
            "delta": round(delta_raw, 4),
            "gamma": round(gamma_raw, 6),
            "theta": round(theta_usd, 2),       # ← USD per day
            "vega": round(vega_usd, 2),         # ← USD per 1% IV change
            "mark": round(mark_price_usd, 2),   # ← USD now
            "mark_native": round(mark_price_native, 6),  # نحفظ الأصلي للمرجع
            "bid": round(bid_usd, 2),
            "ask": round(ask_usd, 2),
            "oi": oi,
            "volume": volume_24h,
        }

        if opt_type == "C":
            calls.append(opt_data)
            total_call_oi += oi
        elif opt_type == "P":
            puts.append(opt_data)
            total_put_oi += oi

    pcr = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else 0

    return {
        "ok": True,
        "currency": currency,
        "exchange": "deribit",
        "spot_price": spot,
        "expiries": sorted(list(expiries_set)),
        "calls": sorted(calls, key=lambda x: x["strike"]),
        "puts": sorted(puts, key=lambda x: x["strike"]),
        "total_call_oi": round(total_call_oi, 2),
        "total_put_oi": round(total_put_oi, 2),
        "put_call_ratio": pcr,
    }


def _get_okx_chain(currency: str,
                   expiry_filter: Optional[str] = None) -> Dict:
    """يبني options chain من OKX (احتياطي)"""
    spot = okx_get_index(currency)
    if spot is None:
        return {"ok": False, "error": "فشل جلب السعر من OKX"}

    # OKX opt-summary يحتوي على Greeks
    summary = okx_get_options_summary(currency, expiry_filter)
    if not summary:
        return {"ok": False, "error": "OKX: لا توجد options"}

    calls = []
    puts = []
    expiries_set = set()
    total_call_oi = 0.0
    total_put_oi = 0.0

    for s in summary:
        instr = s.get("instId", "")
        # شكل OKX: BTC-USD-260503-45000-C
        parts = instr.split("-")
        if len(parts) != 5:
            continue

        try:
            strike = float(parts[3])
            opt_type = parts[4].upper()
            expiry = parts[2]  # YYMMDD
        except (ValueError, IndexError):
            continue

        if expiry_filter and expiry != expiry_filter:
            continue

        expiries_set.add(expiry)

        try:
            iv = float(s.get("markVol", 0) or 0)  # OKX يعطيها كنسبة عشرية مباشرة
            oi = float(s.get("oi", 0) or 0)
            delta = float(s.get("delta", 0) or 0)
            gamma = float(s.get("gamma", 0) or 0)
            theta = float(s.get("theta", 0) or 0)
            vega = float(s.get("vega", 0) or 0)
            mark = float(s.get("markPx", 0) or 0)
        except (ValueError, TypeError):
            continue

        opt_data = {
            "strike": strike,
            "expiry": expiry,
            "instrument": instr,
            "iv": round(iv, 4),
            "iv_pct": round(iv * 100, 2),
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "theta": round(theta, 4),
            "vega": round(vega, 4),
            "mark": round(mark, 6),
            "bid": 0,  # OKX summary لا يرجع bid/ask
            "ask": 0,
            "oi": oi,
            "volume": 0,
        }

        if opt_type == "C":
            calls.append(opt_data)
            total_call_oi += oi
        elif opt_type == "P":
            puts.append(opt_data)
            total_put_oi += oi

    pcr = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else 0

    return {
        "ok": True,
        "currency": currency,
        "exchange": "okx",
        "spot_price": spot,
        "expiries": sorted(list(expiries_set)),
        "calls": sorted(calls, key=lambda x: x["strike"]),
        "puts": sorted(puts, key=lambda x: x["strike"]),
        "total_call_oi": round(total_call_oi, 2),
        "total_put_oi": round(total_put_oi, 2),
        "put_call_ratio": pcr,
    }


# ─────────────────────────────────────────────
# Options Analysis Functions
# ─────────────────────────────────────────────

def calc_max_pain(chain: Dict) -> Dict:
    """
    Max Pain = السعر الذي يجعل أكبر عدد من options expire worthless.
    نقطة "ألم" Market Makers لو السعر استقر هناك عند الـexpiry.
    """
    if not chain.get("ok"):
        return {"max_pain": None}

    # Synthetic ما عنده OI حقيقي = max pain ما يصلح
    if chain.get("synthetic"):
        return {"max_pain": None, "synthetic_skip": True}

    calls = chain["calls"]
    puts = chain["puts"]
    if not calls and not puts:
        return {"max_pain": None}

    # نجمع كل الـstrikes الفريدة
    all_strikes = sorted(set(
        [c["strike"] for c in calls] + [p["strike"] for p in puts]
    ))
    if not all_strikes:
        return {"max_pain": None}

    pain_data = []
    for test_price in all_strikes:
        total_pain = 0.0
        # Pain لـCalls = sum(OI × max(test_price - strike, 0))
        for c in calls:
            if test_price > c["strike"]:
                total_pain += (test_price - c["strike"]) * c["oi"]
        # Pain لـPuts = sum(OI × max(strike - test_price, 0))
        for p in puts:
            if test_price < p["strike"]:
                total_pain += (p["strike"] - test_price) * p["oi"]

        pain_data.append((test_price, total_pain))

    # Max Pain = السعر اللي يقلل total pain
    max_pain_price, _ = min(pain_data, key=lambda x: x[1])

    spot = chain["spot_price"]
    distance_pct = (max_pain_price - spot) / spot * 100

    return {
        "max_pain": max_pain_price,
        "spot": spot,
        "distance_pct": round(distance_pct, 2),
        "direction": "صاعد" if distance_pct > 0 else "هابط",
    }


def calc_iv_metrics(chain: Dict) -> Dict:
    """
    يحسب IV statistics:
    - Average IV
    - ATM IV (At-The-Money)
    - IV Skew (Put IV - Call IV at 25 delta)
    """
    if not chain.get("ok") or not chain["calls"] or not chain["puts"]:
        return {}

    spot = chain["spot_price"]

    # ATM = أقرب strike للسعر الحالي
    atm_call = min(chain["calls"], key=lambda x: abs(x["strike"] - spot))
    atm_put = min(chain["puts"], key=lambda x: abs(x["strike"] - spot))
    atm_iv = (atm_call["iv"] + atm_put["iv"]) / 2

    # 25-delta skew
    # نجد call عند delta ≈ 0.25 و put عند delta ≈ -0.25
    calls_25d = sorted(chain["calls"],
                       key=lambda x: abs(abs(x["delta"]) - 0.25))
    puts_25d = sorted(chain["puts"],
                      key=lambda x: abs(abs(x["delta"]) - 0.25))

    skew = None
    skew_interpretation = "غير محدد"
    if calls_25d and puts_25d:
        call_25d_iv = calls_25d[0]["iv"]
        put_25d_iv = puts_25d[0]["iv"]
        skew = put_25d_iv - call_25d_iv  # موجب = puts أغلى = توقع هبوط

        if skew > 0.05:
            skew_interpretation = "🔴 السوق يخاف من الهبوط (Puts أغلى)"
        elif skew < -0.05:
            skew_interpretation = "🟢 السوق يتوقع صعود (Calls أغلى)"
        else:
            skew_interpretation = "⚪ متوازن"

    # Average IV
    all_ivs = [c["iv"] for c in chain["calls"]] + [p["iv"] for p in chain["puts"]]
    avg_iv = sum(all_ivs) / len(all_ivs) if all_ivs else 0

    return {
        "atm_iv": round(atm_iv, 4),
        "atm_iv_pct": round(atm_iv * 100, 2),
        "avg_iv": round(avg_iv, 4),
        "avg_iv_pct": round(avg_iv * 100, 2),
        "skew": round(skew, 4) if skew is not None else None,
        "skew_pct": round(skew * 100, 2) if skew is not None else None,
        "skew_interpretation": skew_interpretation,
        "atm_call_strike": atm_call["strike"],
        "atm_put_strike": atm_put["strike"],
    }


def get_top_oi_strikes(chain: Dict, n: int = 5) -> Dict:
    """يرجع أعلى n strikes حسب OI لـCalls و Puts"""
    if not chain.get("ok"):
        return {"top_calls": [], "top_puts": []}

    top_calls = sorted(chain["calls"], key=lambda x: x["oi"], reverse=True)[:n]
    top_puts = sorted(chain["puts"], key=lambda x: x["oi"], reverse=True)[:n]

    return {"top_calls": top_calls, "top_puts": top_puts}


def get_iv_rank_estimate(atm_iv: float) -> Tuple[str, str]:
    """
    تقدير IV Rank بناءً على levels تقريبية للكريبتو:
    - < 40%: منخفض جداً (ارخص للشراء)
    - 40-60%: منخفض
    - 60-80%: متوسط
    - 80-100%: مرتفع
    - > 100%: مرتفع جداً (افضل للبيع)
    """
    iv_pct = atm_iv * 100
    if iv_pct < 40:
        return "📉 منخفض جداً", "افضل وقت لشراء options (premiums رخيصة)"
    elif iv_pct < 60:
        return "📊 منخفض", "options معقولة السعر"
    elif iv_pct < 80:
        return "📈 متوسط", "حياد - SPY/IV historical avg"
    elif iv_pct < 100:
        return "🔥 مرتفع", "احذر شراء options - premiums غالية"
    else:
        return "🚨 مرتفع جداً", "افضل وقت لبيع options (Iron Condor / Strangle قصير)"


# ─────────────────────────────────────────────
# Strategy Builder
# ─────────────────────────────────────────────

def build_bull_call_spread(chain: Dict, lower_strike: float,
                           upper_strike: float) -> Dict:
    """
    Bull Call Spread:
    - شراء Call عند lower_strike
    - بيع Call عند upper_strike
    Max Profit = (upper - lower) - net_debit
    Max Loss = net_debit
    Breakeven = lower + net_debit
    """
    if not chain.get("ok"):
        return {"ok": False, "error": "chain not ready"}

    long_call = next((c for c in chain["calls"] if c["strike"] == lower_strike), None)
    short_call = next((c for c in chain["calls"] if c["strike"] == upper_strike), None)

    if not long_call or not short_call:
        return {"ok": False, "error": "strikes not found"}

    net_debit = long_call["mark"] - short_call["mark"]
    max_profit = (upper_strike - lower_strike) - net_debit
    max_loss = net_debit
    breakeven = lower_strike + net_debit
    rr = max_profit / max_loss if max_loss > 0 else 0

    return {
        "ok": True,
        "strategy": "Bull Call Spread",
        "outlook": "🟢 صاعد معتدل",
        "long_call": long_call,
        "short_call": short_call,
        "net_debit": round(net_debit, 4),
        "max_profit": round(max_profit, 4),
        "max_loss": round(max_loss, 4),
        "breakeven": round(breakeven, 4),
        "rr": round(rr, 2),
        "best_when": "تتوقع ارتفاع للسعر بين الـstrike الأول والثاني",
        "delta": round(long_call["delta"] - short_call["delta"], 4),
    }


def build_bear_put_spread(chain: Dict, upper_strike: float,
                          lower_strike: float) -> Dict:
    """
    Bear Put Spread:
    - شراء Put عند upper_strike (ITM/ATM)
    - بيع Put عند lower_strike (OTM)
    """
    if not chain.get("ok"):
        return {"ok": False, "error": "chain not ready"}

    long_put = next((p for p in chain["puts"] if p["strike"] == upper_strike), None)
    short_put = next((p for p in chain["puts"] if p["strike"] == lower_strike), None)

    if not long_put or not short_put:
        return {"ok": False, "error": "strikes not found"}

    net_debit = long_put["mark"] - short_put["mark"]
    max_profit = (upper_strike - lower_strike) - net_debit
    max_loss = net_debit
    breakeven = upper_strike - net_debit
    rr = max_profit / max_loss if max_loss > 0 else 0

    return {
        "ok": True,
        "strategy": "Bear Put Spread",
        "outlook": "🔴 هابط معتدل",
        "long_put": long_put,
        "short_put": short_put,
        "net_debit": round(net_debit, 4),
        "max_profit": round(max_profit, 4),
        "max_loss": round(max_loss, 4),
        "breakeven": round(breakeven, 4),
        "rr": round(rr, 2),
        "best_when": "تتوقع انخفاض للسعر بين الـstrike الأول والثاني",
        "delta": round(long_put["delta"] - short_put["delta"], 4),
    }


def build_long_straddle(chain: Dict, strike: float) -> Dict:
    """
    Long Straddle: شراء Call + Put على نفس Strike
    يربح من التذبذب القوي (أي اتجاه)
    """
    if not chain.get("ok"):
        return {"ok": False, "error": "chain not ready"}

    call = next((c for c in chain["calls"] if c["strike"] == strike), None)
    put = next((p for p in chain["puts"] if p["strike"] == strike), None)

    if not call or not put:
        return {"ok": False, "error": "strike not found"}

    total_cost = call["mark"] + put["mark"]
    upper_be = strike + total_cost
    lower_be = strike - total_cost

    return {
        "ok": True,
        "strategy": "Long Straddle",
        "outlook": "⚡ تذبذب قوي (أي اتجاه)",
        "call": call,
        "put": put,
        "total_cost": round(total_cost, 4),
        "max_loss": round(total_cost, 4),
        "max_profit": "غير محدود (نظرياً)",
        "upper_breakeven": round(upper_be, 4),
        "lower_breakeven": round(lower_be, 4),
        "be_distance_pct": round((total_cost / strike) * 100, 2),
        "best_when": "تتوقع حركة قوية لكن ما تعرف الاتجاه (مثل قبل أحداث كبيرة)",
    }


def build_long_strangle(chain: Dict, call_strike: float,
                        put_strike: float) -> Dict:
    """
    Long Strangle: شراء OTM Call + OTM Put
    أرخص من Straddle لكن يحتاج تذبذب أكبر
    """
    if not chain.get("ok"):
        return {"ok": False, "error": "chain not ready"}

    call = next((c for c in chain["calls"] if c["strike"] == call_strike), None)
    put = next((p for p in chain["puts"] if p["strike"] == put_strike), None)

    if not call or not put:
        return {"ok": False, "error": "strikes not found"}

    total_cost = call["mark"] + put["mark"]
    upper_be = call_strike + total_cost
    lower_be = put_strike - total_cost

    return {
        "ok": True,
        "strategy": "Long Strangle",
        "outlook": "⚡ تذبذب قوي (أرخص من Straddle)",
        "call": call,
        "put": put,
        "total_cost": round(total_cost, 4),
        "max_loss": round(total_cost, 4),
        "max_profit": "غير محدود (نظرياً)",
        "upper_breakeven": round(upper_be, 4),
        "lower_breakeven": round(lower_be, 4),
        "best_when": "تتوقع حركة قوية مع تكلفة أقل (لكن تحتاج حركة أكبر للربح)",
    }


def build_iron_condor(chain: Dict, put_short: float, put_long: float,
                      call_short: float, call_long: float) -> Dict:
    """
    Iron Condor: 4 legs
    - Sell OTM Put (put_short) + Buy further OTM Put (put_long)
    - Sell OTM Call (call_short) + Buy further OTM Call (call_long)
    يربح من Range-bound market
    """
    if not chain.get("ok"):
        return {"ok": False, "error": "chain not ready"}

    sp = next((p for p in chain["puts"] if p["strike"] == put_short), None)
    lp = next((p for p in chain["puts"] if p["strike"] == put_long), None)
    sc = next((c for c in chain["calls"] if c["strike"] == call_short), None)
    lc = next((c for c in chain["calls"] if c["strike"] == call_long), None)

    if not all([sp, lp, sc, lc]):
        return {"ok": False, "error": "strikes not found"}

    # Net credit = ما تستلم - ما تدفع
    net_credit = (sp["mark"] + sc["mark"]) - (lp["mark"] + lc["mark"])

    # Max profit = net credit (لو السعر بقي بين short strikes)
    max_profit = net_credit

    # Max loss = wing width - net credit
    put_wing = put_short - put_long
    call_wing = call_long - call_short
    max_wing = max(put_wing, call_wing)
    max_loss = max_wing - net_credit

    # Breakevens
    upper_be = call_short + net_credit
    lower_be = put_short - net_credit

    rr = max_profit / max_loss if max_loss > 0 else 0

    return {
        "ok": True,
        "strategy": "Iron Condor",
        "outlook": "📊 Range-bound (السوق ما يتحرك)",
        "short_put": sp,
        "long_put": lp,
        "short_call": sc,
        "long_call": lc,
        "net_credit": round(net_credit, 4),
        "max_profit": round(max_profit, 4),
        "max_loss": round(max_loss, 4),
        "upper_breakeven": round(upper_be, 4),
        "lower_breakeven": round(lower_be, 4),
        "rr": round(rr, 2),
        "best_when": "تتوقع السعر يبقى بين {} و {} حتى الـexpiry".format(
            put_short, call_short),
    }


# ─────────────────────────────────────────────
# Smart Strategy Recommender
# ─────────────────────────────────────────────

def recommend_strategy(chain: Dict, outlook: str = "neutral") -> Dict:
    """
    يقترح استراتيجية بناءً على:
    - outlook: 'bullish' / 'bearish' / 'neutral' / 'volatile'
    - IV level (high IV = sell premium, low IV = buy premium)
    - السعر الحالي
    """
    if not chain.get("ok"):
        return {"ok": False, "error": "chain not ready"}

    spot = chain["spot_price"]
    iv_metrics = calc_iv_metrics(chain)
    atm_iv = iv_metrics.get("atm_iv", 0.5)
    iv_level, _ = get_iv_rank_estimate(atm_iv)
    iv_high = atm_iv > 0.8  # 80%+

    # نختار strikes معقولة
    strikes = sorted(set(c["strike"] for c in chain["calls"]))
    if not strikes:
        return {"ok": False, "error": "no strikes"}

    # ATM strike
    atm = min(strikes, key=lambda x: abs(x - spot))
    atm_idx = strikes.index(atm)

    suggestions = []

    if outlook == "bullish":
        # Lower strike = ATM, Upper = OTM
        if atm_idx + 2 < len(strikes):
            upper = strikes[atm_idx + 2]
            spread = build_bull_call_spread(chain, atm, upper)
            if spread.get("ok"):
                suggestions.append(spread)

    elif outlook == "bearish":
        if atm_idx - 2 >= 0:
            lower = strikes[atm_idx - 2]
            spread = build_bear_put_spread(chain, atm, lower)
            if spread.get("ok"):
                suggestions.append(spread)

    elif outlook == "volatile":
        # Long Straddle لو IV منخفض، Strangle لو معتدل
        if not iv_high:
            sd = build_long_straddle(chain, atm)
            if sd.get("ok"):
                suggestions.append(sd)

            # Strangle (أرخص)
            if atm_idx + 1 < len(strikes) and atm_idx - 1 >= 0:
                sg = build_long_strangle(chain, strikes[atm_idx + 1],
                                          strikes[atm_idx - 1])
                if sg.get("ok"):
                    suggestions.append(sg)
        else:
            # IV عالي - أفضل تبيع
            if atm_idx + 2 < len(strikes) and atm_idx - 2 >= 0:
                ic = build_iron_condor(
                    chain,
                    put_short=strikes[atm_idx - 1],
                    put_long=strikes[atm_idx - 2],
                    call_short=strikes[atm_idx + 1],
                    call_long=strikes[atm_idx + 2],
                )
                if ic.get("ok"):
                    suggestions.append(ic)

    elif outlook == "neutral":
        # Iron Condor كلاسيك
        if atm_idx + 3 < len(strikes) and atm_idx - 3 >= 0:
            ic = build_iron_condor(
                chain,
                put_short=strikes[atm_idx - 1],
                put_long=strikes[atm_idx - 3],
                call_short=strikes[atm_idx + 1],
                call_long=strikes[atm_idx + 3],
            )
            if ic.get("ok"):
                suggestions.append(ic)

    return {
        "ok": True,
        "outlook": outlook,
        "iv_level": iv_level,
        "iv_high": iv_high,
        "atm_iv_pct": round(atm_iv * 100, 2),
        "spot": spot,
        "suggestions": suggestions,
    }


# ─────────────────────────────────────────────
# Display Formatters
# ─────────────────────────────────────────────

def fmt_options_overview(chain: Dict, top_n: int = 5) -> str:
    """تنسيق نظرة عامة على options chain (Real أو Synthetic)"""
    if not chain.get("ok"):
        err = chain.get("error", "?")
        return f"❌ {err}"

    cur = chain["currency"]
    spot = chain["spot_price"]
    exch = chain["exchange"].upper()
    expiries = chain["expiries"][:5]
    is_synthetic = chain.get("synthetic", False)

    # Header مختلف للـSynthetic
    if is_synthetic:
        rv = chain.get("rv_data", {})
        iv_used_pct = chain.get("iv_used_pct", 0)
        msg = f"📊 *Synthetic Options — {cur}* ⚠️\n"
        msg += f"━━━━━━━━━━━━━━━━━━\n"
        msg += f"💰 السعر الحالي: `${spot:,.6f}`\n"
        msg += f"📡 المصدر: *Black-Scholes Calculator*\n"
        msg += f"📊 RV (30D): {rv.get('rv_pct', 0):.1f}% (Realized)\n"
        msg += f"📈 IV المستخدم: {iv_used_pct:.1f}% (RV × 1.15)\n"
        msg += f"📅 Expiries: {', '.join(expiries)}\n\n"

        msg += "⚠️ *ملاحظة مهمة:*\n"
        msg += "هذي البيانات *حسابية* (Synthetic) — لا توجد options "
        msg += "حقيقية لـ" + cur + " على Deribit/OKX.\n"
        msg += "الـGreeks محسوبة بـBlack-Scholes من تذبذب Binance التاريخي.\n\n"
        msg += "*لا يوجد:* OI, Volume, Skew, Max Pain, Bid/Ask\n\n"

        # نعرض sample من Greeks للـATM
        atm_strike = min(set(c["strike"] for c in chain["calls"]),
                         key=lambda x: abs(x - spot))

        # ATM call عبر expiries
        msg += f"📊 *ATM Call (${atm_strike:,.4f}) — Greeks لكل Expiry:*\n"
        msg += "```\n"
        msg += "Days  Price     Δ      Γ        Θ/day\n"
        for exp in expiries:
            atm_calls = [c for c in chain["calls"]
                         if c["strike"] == atm_strike and c["expiry"] == exp]
            if atm_calls:
                c = atm_calls[0]
                msg += f"{exp:<5} ${c['mark']:>8.4f} {c['delta']:+.2f} {c['gamma']:.5f} ${c['theta']:>+7.4f}\n"
        msg += "```\n\n"

        # ATM put مماثل
        msg += f"📊 *ATM Put (${atm_strike:,.4f}) — Greeks لكل Expiry:*\n"
        msg += "```\n"
        msg += "Days  Price     Δ      Γ        Θ/day\n"
        for exp in expiries:
            atm_puts = [p for p in chain["puts"]
                        if p["strike"] == atm_strike and p["expiry"] == exp]
            if atm_puts:
                p = atm_puts[0]
                msg += f"{exp:<5} ${p['mark']:>8.4f} {p['delta']:+.2f} {p['gamma']:.5f} ${p['theta']:>+7.4f}\n"
        msg += "```\n\n"

        # Strikes range
        all_strikes = sorted(set(c["strike"] for c in chain["calls"]))
        msg += f"📐 *Strikes المتاحة:* {len(all_strikes)} مستوى\n"
        msg += f"`${all_strikes[0]:,.4f}` — `${all_strikes[-1]:,.4f}`\n\n"

        # نقترح أمثلة حقيقية بناءً على spot price
        atm_strike_for_example = all_strikes[len(all_strikes) // 2]
        otm_call_strike = all_strikes[len(all_strikes) // 2 + 1] if len(all_strikes) > len(all_strikes) // 2 + 1 else atm_strike_for_example
        otm_put_strike = all_strikes[len(all_strikes) // 2 - 1] if len(all_strikes) > 1 else atm_strike_for_example

        # نختار format للأرقام حسب الحجم
        if spot < 1:
            fmt_strike = lambda x: f"{x:.4f}"
        elif spot < 100:
            fmt_strike = lambda x: f"{x:.2f}"
        else:
            fmt_strike = lambda x: f"{int(x)}"

        msg += "━━━━━━━━━━━━━━━━━━\n"
        msg += "💡 *جرّب الأوامر دي مباشرة:*\n\n"
        msg += f"📊 *Greeks:*\n"
        msg += f"`greeks {cur} {fmt_strike(atm_strike_for_example)} 30 call`\n"
        msg += f"`greeks {cur} {fmt_strike(otm_put_strike)} 14 put`\n\n"
        msg += f"💎 *استراتيجيات:*\n"
        msg += f"`استراتيجية {cur} bullish` (صاعد)\n"
        msg += f"`استراتيجية {cur} bearish` (هابط)\n"
        msg += f"`استراتيجية {cur} volatile` (تذبذب)\n\n"
        msg += "💎 *للحصول على real options بـOI/Skew/MaxPain:*\n"
        msg += "جرّب: `خيارات BTC` أو `خيارات ETH` أو `خيارات SOL`"

        return msg

    # ─── Real Options (Deribit/OKX) ───
    pcr = chain["put_call_ratio"]
    iv_metrics = calc_iv_metrics(chain)
    max_pain = calc_max_pain(chain)
    top_oi = get_top_oi_strikes(chain, top_n)
    iv_level, iv_advice = get_iv_rank_estimate(iv_metrics.get("atm_iv", 0.5))

    # PCR interpretation
    pcr_interp = "⚪ متوازن"
    if pcr > 1.2:
        pcr_interp = "🔴 خوف من الهبوط (Puts أكثر)"
    elif pcr < 0.7:
        pcr_interp = "🟢 توقعات صاعدة (Calls أكثر)"

    msg = f"📊 *Options Overview — {cur}* ✅ REAL\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n"
    msg += f"💰 السعر الحالي: `${spot:,.2f}`\n"
    msg += f"📡 المصدر: *{exch}*\n"
    msg += f"📅 Expiries: {len(chain['expiries'])} ({', '.join(expiries)}{'...' if len(chain['expiries']) > 5 else ''})\n\n"

    msg += f"📊 *المقاييس الرئيسية:*\n"
    msg += f"• Put/Call OI Ratio: *{pcr}* — {pcr_interp}\n"
    msg += f"• ATM IV: *{iv_metrics.get('atm_iv_pct', 0):.1f}%* {iv_level}\n"
    msg += f"  _{iv_advice}_\n"
    msg += f"• Avg IV: {iv_metrics.get('avg_iv_pct', 0):.1f}%\n"

    if iv_metrics.get("skew_pct") is not None:
        msg += f"• 25-Delta Skew: {iv_metrics['skew_pct']:+.2f}%\n"
        msg += f"  _{iv_metrics['skew_interpretation']}_\n"

    if max_pain.get("max_pain"):
        mp = max_pain["max_pain"]
        dist = max_pain["distance_pct"]
        msg += f"• Max Pain: `${mp:,.0f}` ({dist:+.2f}%)\n"
        msg += f"  _نقطة ألم Market Makers_\n"

    msg += f"\n📈 *Top {top_n} Calls (أعلى OI):*\n"
    for c in top_oi["top_calls"]:
        moneyness = "🔥" if abs(c["strike"] - spot) / spot < 0.05 else " "
        msg += f"{moneyness} `${c['strike']:,.0f}` — OI: {c['oi']:,.0f}, "
        msg += f"IV: {c['iv_pct']:.1f}%, Δ: {c['delta']:.2f}\n"

    msg += f"\n📉 *Top {top_n} Puts (أعلى OI):*\n"
    for p in top_oi["top_puts"]:
        moneyness = "🔥" if abs(p["strike"] - spot) / spot < 0.05 else " "
        msg += f"{moneyness} `${p['strike']:,.0f}` — OI: {p['oi']:,.0f}, "
        msg += f"IV: {p['iv_pct']:.1f}%, Δ: {p['delta']:.2f}\n"

    msg += "\n━━━━━━━━━━━━━━━━━━\n"
    msg += "💡 *الأوامر:*\n"
    msg += f"`greeks {cur} 45000 30 call` — Greeks لعقد محدد\n"
    msg += f"`استراتيجية {cur} bullish` — اقتراح استراتيجية\n"
    msg += f"`maxpain {cur}` — Max Pain تفصيلي\n"

    return msg


def fmt_greeks(symbol: str, strike: float, expiry_days: int,
               option_type: str, greeks_data: Dict, spot: float,
               iv: Optional[float] = None) -> str:
    """تنسيق Greeks لعقد محدد"""
    if greeks_data.get("error"):
        return f"❌ {greeks_data['error']}"

    if not greeks_data.get("ok"):
        return "❌ فشل حساب Greeks"

    moneyness = "ATM"
    if option_type.lower() == "call":
        if strike < spot * 0.97:
            moneyness = "🔥 ITM (داخل النقود)"
        elif strike > spot * 1.03:
            moneyness = "❄️ OTM (خارج النقود)"
        else:
            moneyness = "🎯 ATM (عند النقود)"
    else:
        if strike > spot * 1.03:
            moneyness = "🔥 ITM (داخل النقود)"
        elif strike < spot * 0.97:
            moneyness = "❄️ OTM (خارج النقود)"
        else:
            moneyness = "🎯 ATM (عند النقود)"

    delta = greeks_data["delta"]
    gamma = greeks_data["gamma"]
    theta = greeks_data["theta"]
    vega = greeks_data["vega"]
    price = greeks_data["price"]

    msg = f"📊 *Greeks — {symbol} {option_type.upper()}*\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n"
    msg += f"💵 السعر الحالي: `${spot:,.2f}`\n"
    msg += f"🎯 Strike: `${strike:,.2f}` — {moneyness}\n"
    msg += f"📅 Days to Expiry: {expiry_days} يوم\n"
    if iv is not None:
        msg += f"📊 IV: {iv * 100:.1f}%\n"
    msg += f"💰 السعر النظري: `${price:,.4f}`\n\n"

    # Delta
    msg += f"🎯 *Delta:* `{delta:+.4f}`\n"
    msg += f"   _لو السعر تحرك \\$1، العقد يتحرك \\${abs(delta):.2f}_\n"
    if abs(delta) > 0.7:
        msg += f"   ⚡ deep ITM — يتحرك مثل الأصل\n"
    elif abs(delta) < 0.3:
        msg += f"   ❄️ deep OTM — حساسية منخفضة\n"
    msg += "\n"

    # Gamma
    msg += f"⚡ *Gamma:* `{gamma:+.6f}`\n"
    msg += f"   _تسارع Delta لكل \\$1 حركة_\n"
    if gamma > 0.001:
        msg += f"   🔥 Gamma عالي — Delta يتغير بسرعة\n"
    msg += "\n"

    # Theta
    msg += f"⏳ *Theta:* `${theta:+.4f}`/يوم\n"
    if theta < -1:
        msg += f"   🚨 تآكل سريع — كل يوم يخسر \\${abs(theta):.2f}\n"
    elif theta < -0.1:
        msg += f"   ⚠️ تآكل معتدل\n"
    else:
        msg += f"   ✅ تآكل بطيء\n"
    msg += "\n"

    # Vega
    msg += f"📊 *Vega:* `${vega:+.4f}`\n"
    msg += f"   _لكل 1% تغير في IV، السعر يتغير \\${vega:.2f}_\n"
    if abs(vega) > 0.5:
        msg += f"   ⚡ حساسية عالية للـIV\n"
    msg += "\n"

    # نصائح ذكية
    msg += "━━━━━━━━━━━━━━━━━━\n"
    msg += "💡 *تفسير ذكي:*\n"

    if abs(delta) > 0.7:
        msg += "• Delta عالي → يتحرك مثل الأصل تقريباً\n"
        msg += "• مناسب لمن يريد leverage بدون margin\n"
    elif abs(delta) < 0.3:
        msg += "• Delta منخفض → احتمال انتهاء worthless عالي\n"
        msg += "• رهان رخيص لكن صعب الربح\n"

    if theta < -2:
        msg += f"• ⚠️ Theta سالب جداً (\\${abs(theta):.2f}/يوم)\n"
        msg += "• كلما اقترب Expiry، الخسارة تتسارع\n"
        msg += "• فكر في expiry أبعد لو ما حركة فورية\n"

    return msg


def fmt_strategy(strategy_data: Dict, spot: float) -> str:
    """تنسيق استراتيجية مقترحة"""
    if not strategy_data.get("ok"):
        return f"❌ {strategy_data.get('error', 'unknown')}"

    name = strategy_data["strategy"]
    outlook = strategy_data["outlook"]
    best_when = strategy_data.get("best_when", "")

    msg = f"💎 *{name}*\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n"
    msg += f"📊 التوقع: {outlook}\n"
    msg += f"💰 السعر الحالي: `${spot:,.2f}`\n\n"

    # Strategy-specific details
    if name == "Bull Call Spread":
        msg += f"🟢 *Long Call:* `${strategy_data['long_call']['strike']:,.0f}` "
        msg += f"@ \\${strategy_data['long_call']['mark']:,.2f}\n"
        msg += f"🔴 *Short Call:* `${strategy_data['short_call']['strike']:,.0f}` "
        msg += f"@ \\${strategy_data['short_call']['mark']:,.2f}\n\n"
        msg += f"💸 *Net Debit:* `${strategy_data['net_debit']:,.2f}`\n"
        msg += f"🎯 *Max Profit:* `${strategy_data['max_profit']:,.2f}` "
        msg += f"(R:R 1:{strategy_data['rr']})\n"
        msg += f"🛑 *Max Loss:* `${strategy_data['max_loss']:,.2f}`\n"
        msg += f"⚖️ *Breakeven:* `${strategy_data['breakeven']:,.2f}`\n"
        msg += f"🎯 *Net Delta:* {strategy_data['delta']:+.2f}\n"

    elif name == "Bear Put Spread":
        msg += f"🟢 *Long Put:* `${strategy_data['long_put']['strike']:,.0f}` "
        msg += f"@ \\${strategy_data['long_put']['mark']:,.2f}\n"
        msg += f"🔴 *Short Put:* `${strategy_data['short_put']['strike']:,.0f}` "
        msg += f"@ \\${strategy_data['short_put']['mark']:,.2f}\n\n"
        msg += f"💸 *Net Debit:* `${strategy_data['net_debit']:,.2f}`\n"
        msg += f"🎯 *Max Profit:* `${strategy_data['max_profit']:,.2f}` "
        msg += f"(R:R 1:{strategy_data['rr']})\n"
        msg += f"🛑 *Max Loss:* `${strategy_data['max_loss']:,.2f}`\n"
        msg += f"⚖️ *Breakeven:* `${strategy_data['breakeven']:,.2f}`\n"

    elif name == "Long Straddle":
        msg += f"🟢 *Long Call:* `${strategy_data['call']['strike']:,.0f}` "
        msg += f"@ \\${strategy_data['call']['mark']:,.2f}\n"
        msg += f"🟢 *Long Put:* `${strategy_data['put']['strike']:,.0f}` "
        msg += f"@ \\${strategy_data['put']['mark']:,.2f}\n\n"
        msg += f"💸 *Total Cost:* `${strategy_data['total_cost']:,.2f}`\n"
        msg += f"🛑 *Max Loss:* `${strategy_data['max_loss']:,.2f}`\n"
        msg += f"🎯 *Max Profit:* {strategy_data['max_profit']}\n"
        msg += f"⚖️ *Upper BE:* `${strategy_data['upper_breakeven']:,.2f}`\n"
        msg += f"⚖️ *Lower BE:* `${strategy_data['lower_breakeven']:,.2f}`\n"
        msg += f"📏 *Required Move:* ±{strategy_data['be_distance_pct']:.1f}%\n"

    elif name == "Long Strangle":
        msg += f"🟢 *Long Call:* `${strategy_data['call']['strike']:,.0f}` "
        msg += f"@ \\${strategy_data['call']['mark']:,.2f}\n"
        msg += f"🟢 *Long Put:* `${strategy_data['put']['strike']:,.0f}` "
        msg += f"@ \\${strategy_data['put']['mark']:,.2f}\n\n"
        msg += f"💸 *Total Cost:* `${strategy_data['total_cost']:,.2f}`\n"
        msg += f"⚖️ *Upper BE:* `${strategy_data['upper_breakeven']:,.2f}`\n"
        msg += f"⚖️ *Lower BE:* `${strategy_data['lower_breakeven']:,.2f}`\n"

    elif name == "Iron Condor":
        msg += f"📊 *4 Legs:*\n"
        msg += f"  🔴 Sell Put: `${strategy_data['short_put']['strike']:,.0f}`\n"
        msg += f"  🟢 Buy Put: `${strategy_data['long_put']['strike']:,.0f}`\n"
        msg += f"  🔴 Sell Call: `${strategy_data['short_call']['strike']:,.0f}`\n"
        msg += f"  🟢 Buy Call: `${strategy_data['long_call']['strike']:,.0f}`\n\n"
        msg += f"💰 *Net Credit:* `${strategy_data['net_credit']:,.2f}`\n"
        msg += f"🎯 *Max Profit:* `${strategy_data['max_profit']:,.2f}` "
        msg += f"(R:R 1:{strategy_data['rr']})\n"
        msg += f"🛑 *Max Loss:* `${strategy_data['max_loss']:,.2f}`\n"
        msg += f"⚖️ *Profit Range:* `${strategy_data['lower_breakeven']:,.0f}` - "
        msg += f"`${strategy_data['upper_breakeven']:,.0f}`\n"

    if best_when:
        msg += f"\n💡 *الأفضل عندما:* {best_when}\n"

    msg += "\n⚠️ _تحليل تعليمي - ليس نصيحة استثمارية_"
    return msg


def fmt_recommendations(rec: Dict) -> str:
    """تنسيق التوصيات الذكية"""
    if not rec.get("ok"):
        return f"❌ {rec.get('error', 'failed')}"

    spot = rec["spot"]
    outlook = rec["outlook"]
    iv_level = rec["iv_level"]
    iv_pct = rec["atm_iv_pct"]
    iv_high = rec["iv_high"]

    outlook_ar = {
        "bullish": "🟢 صاعد",
        "bearish": "🔴 هابط",
        "neutral": "⚪ محايد",
        "volatile": "⚡ متقلب",
    }.get(outlook, outlook)

    msg = f"💡 *الاستراتيجيات المقترحة*\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n"
    msg += f"📊 السعر: `${spot:,.2f}`\n"
    msg += f"🎯 توقعك: {outlook_ar}\n"
    msg += f"📈 ATM IV: {iv_pct:.1f}% {iv_level}\n\n"

    if iv_high:
        msg += "⚠️ *IV عالي* — افضل تبيع premium بدلاً من الشراء\n\n"

    suggestions = rec.get("suggestions", [])
    if not suggestions:
        msg += "❌ لا توجد استراتيجيات مناسبة (strikes غير متاحة)"
        return msg

    msg += f"📋 *{len(suggestions)} استراتيجية مقترحة:*\n\n"

    for i, s in enumerate(suggestions, 1):
        msg += f"━━━ #{i} ━━━\n"
        msg += fmt_strategy(s, spot)
        msg += "\n"

    return msg
