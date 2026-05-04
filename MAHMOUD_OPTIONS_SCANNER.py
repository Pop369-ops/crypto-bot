"""
MAHMOUD_OPTIONS_SCANNER.py — v5.3 Smart Options Scanner
═══════════════════════════════════════════════════════════════════════════

ماسح ذكي للـoptions opportunities عبر كل العملات.

الفئات الـ3 من المسح:
1. Real Options Scan (BTC/ETH/SOL) — فحص شامل بـOI, Skew, Max Pain
2. Top Volume Scan (top 30 عملة) — Synthetic Greeks + IV scan
3. Light Scan (باقي العملات) — IV opportunities فقط

ما يكتشفه الماسح:
✅ IV Opportunities — IV عالي/منخفض جداً
✅ Skew Anomalies — Calls vs Puts pricing imbalance
✅ OI Spikes — تجمعات Whale activity
✅ Volume Surges — option volume غير طبيعي

كيف يعمل:
• Concurrent fetching (10 عملات في نفس الوقت)
• Cache نتائج لـ30 دقيقة (لتجنب hammering APIs)
• Skip العملات بسيولة منخفضة
• Ranking by opportunity score
═══════════════════════════════════════════════════════════════════════════
"""

import os
import math
import time
import logging
import asyncio
import requests
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import MAHMOUD_OPTIONS as opt_mod


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

# الحد الأدنى للسيولة (24h volume USD)
MIN_VOLUME_USD = float(os.environ.get("OPT_SCAN_MIN_VOL_USD", "5000000"))

# عدد الـthreads للـconcurrent scanning
SCAN_WORKERS = int(os.environ.get("OPT_SCAN_WORKERS", "10"))

# Cache TTL (ثواني)
CACHE_TTL = 1800  # 30 دقيقة

# Thresholds للـopportunity detection
IV_LOW_THRESHOLD = 0.40       # IV < 40% = فرصة شراء
IV_HIGH_THRESHOLD = 1.00      # IV > 100% = فرصة بيع
SKEW_BULLISH = -0.05          # Skew < -5% = bullish
SKEW_BEARISH = 0.05           # Skew > +5% = bearish (خوف)
OI_SPIKE_RATIO = 2.0          # OI زاد 200% = spike

# Real options currencies (Deribit)
REAL_CURRENCIES = ["BTC", "ETH", "SOL"]

# Cache (in-memory)
_SCAN_CACHE = {}              # {key: (timestamp, data)}


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _cache_get(key: str) -> Optional[Dict]:
    """جلب من الـcache لو لسه فعّال"""
    if key in _SCAN_CACHE:
        ts, data = _SCAN_CACHE[key]
        if time.time() - ts < CACHE_TTL:
            return data
    return None


def _cache_set(key: str, data: Dict):
    """تخزين في الـcache"""
    _SCAN_CACHE[key] = (time.time(), data)


def get_top_symbols_by_volume(limit: int = 50) -> List[str]:
    """
    يجلب أعلى عملات تداولاً من Binance Futures.
    Returns: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', ...]
    """
    cache_key = f"top_symbols_{limit}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/ticker/24hr",
            headers=opt_mod.DEFAULT_HEADERS,
            timeout=15
        )
        if r.status_code != 200:
            logging.warning(f"Binance ticker failed: {r.status_code}")
            return REAL_CURRENCIES

        data = r.json()
        # نفلتر USDT pairs ونرتب حسب quoteVolume
        usdt_pairs = [
            t for t in data
            if t.get("symbol", "").endswith("USDT")
            and float(t.get("quoteVolume", 0)) >= MIN_VOLUME_USD
        ]
        usdt_pairs.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)

        symbols = [t["symbol"] for t in usdt_pairs[:limit]]
        _cache_set(cache_key, symbols)
        return symbols
    except Exception as e:
        logging.warning(f"get_top_symbols error: {e}")
        return [f"{c}USDT" for c in REAL_CURRENCIES]


def get_all_active_symbols() -> List[str]:
    """يجلب كل العملات النشطة (USDT pairs) من Binance"""
    cache_key = "all_active_symbols"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/ticker/24hr",
            headers=opt_mod.DEFAULT_HEADERS,
            timeout=15
        )
        if r.status_code != 200:
            return []

        data = r.json()
        usdt_active = [
            t["symbol"] for t in data
            if t.get("symbol", "").endswith("USDT")
            and float(t.get("quoteVolume", 0)) >= MIN_VOLUME_USD
        ]
        _cache_set(cache_key, usdt_active)
        return usdt_active
    except Exception as e:
        logging.warning(f"get_all_active_symbols error: {e}")
        return []


# ─────────────────────────────────────────────
# Single Symbol Analyzer
# ─────────────────────────────────────────────

def analyze_symbol_options(symbol: str, deep: bool = False) -> Optional[Dict]:
    """
    يحلل عملة واحدة ويرجع opportunity score + signals.

    Args:
        symbol: مثل 'BTCUSDT' أو 'BTC'
        deep: إذا True، يستخدم real chain (لـBTC/ETH/SOL فقط)

    Returns:
    {
        "ok": bool,
        "symbol": "BTC",
        "spot": 79740.0,
        "iv_pct": 32.7,
        "iv_signal": "very_low" | "low" | "normal" | "high" | "very_high",
        "skew_pct": -2.3,           # only for real chain
        "skew_signal": "bullish" | "neutral" | "bearish",
        "is_real": True/False,
        "opportunities": [list of opportunities],
        "score": 0-10,              # opportunity score
        "summary_ar": "BTC: IV منخفض = فرصة شراء"
    }
    """
    cur = symbol.upper().replace("USDT", "")
    cache_key = f"analysis_{cur}_{deep}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    result = {
        "ok": False,
        "symbol": cur,
        "opportunities": [],
        "score": 0,
    }

    try:
        if deep and cur in REAL_CURRENCIES:
            # Real chain analysis
            chain = opt_mod.get_options_chain(cur, allow_synthetic=False)
            if not chain.get("ok"):
                return None

            spot = chain["spot_price"]
            iv_metrics = opt_mod.calc_iv_metrics(chain)
            iv_pct = iv_metrics.get("atm_iv_pct", 50)
            skew_pct = iv_metrics.get("skew_pct", 0) or 0
            pcr = chain.get("put_call_ratio", 1.0)

            result["is_real"] = True
            result["spot"] = spot
            result["iv_pct"] = round(iv_pct, 1)
            result["skew_pct"] = round(skew_pct, 2)
            result["pcr"] = round(pcr, 2)

            # IV Signal
            iv = iv_pct / 100
            if iv < IV_LOW_THRESHOLD:
                result["iv_signal"] = "very_low"
                result["opportunities"].append({
                    "type": "iv_buy",
                    "strength": min(10, int((IV_LOW_THRESHOLD - iv) * 25)),
                    "msg_ar": f"🔥 IV منخفض جداً ({iv_pct:.1f}%) — شراء premium مفيد"
                })
            elif iv < 0.60:
                result["iv_signal"] = "low"
                result["opportunities"].append({
                    "type": "iv_buy_mild",
                    "strength": 4,
                    "msg_ar": f"📊 IV منخفض ({iv_pct:.1f}%) — premium معقولة"
                })
            elif iv > IV_HIGH_THRESHOLD:
                result["iv_signal"] = "very_high"
                result["opportunities"].append({
                    "type": "iv_sell",
                    "strength": min(10, int((iv - IV_HIGH_THRESHOLD) * 15) + 6),
                    "msg_ar": f"🚨 IV عالي جداً ({iv_pct:.1f}%) — بيع premium مفيد (Iron Condor)"
                })
            elif iv > 0.80:
                result["iv_signal"] = "high"
                result["opportunities"].append({
                    "type": "iv_sell_mild",
                    "strength": 5,
                    "msg_ar": f"🔥 IV عالي ({iv_pct:.1f}%) — احذر شراء premium"
                })
            else:
                result["iv_signal"] = "normal"

            # Skew Signal
            if skew_pct < SKEW_BULLISH * 100:
                result["skew_signal"] = "bullish"
                result["opportunities"].append({
                    "type": "skew_bullish",
                    "strength": min(8, int(abs(skew_pct))),
                    "msg_ar": f"🟢 Skew صاعد قوي ({skew_pct:+.1f}%) — Calls أرخص = توقع صعود"
                })
            elif skew_pct > SKEW_BEARISH * 100:
                result["skew_signal"] = "bearish"
                result["opportunities"].append({
                    "type": "skew_bearish",
                    "strength": min(8, int(skew_pct)),
                    "msg_ar": f"🔴 Skew هابط ({skew_pct:+.1f}%) — السوق خايف من الهبوط (Puts أغلى)"
                })
            else:
                result["skew_signal"] = "neutral"

            # PCR signal
            if pcr > 1.5:
                result["opportunities"].append({
                    "type": "pcr_bearish",
                    "strength": 5,
                    "msg_ar": f"⚠️ Put/Call Ratio عالي ({pcr:.2f}) — توقعات هابطة"
                })
            elif pcr < 0.6:
                result["opportunities"].append({
                    "type": "pcr_bullish",
                    "strength": 5,
                    "msg_ar": f"🟢 Put/Call Ratio منخفض ({pcr:.2f}) — توقعات صاعدة"
                })

            # Max Pain
            mp_data = opt_mod.calc_max_pain(chain)
            if mp_data.get("max_pain"):
                mp = mp_data["max_pain"]
                dist = mp_data["distance_pct"]
                result["max_pain"] = mp
                result["max_pain_distance"] = round(dist, 2)
                if abs(dist) > 5:
                    direction = "صعود" if dist > 0 else "هبوط"
                    result["opportunities"].append({
                        "type": "max_pain_pull",
                        "strength": min(7, int(abs(dist) / 2)),
                        "msg_ar": f"🎯 Max Pain ${mp:,.0f} ({dist:+.1f}%) — توقع {direction} نحو الـMax Pain"
                    })

        else:
            # Light scan via Synthetic (للعملات اللي ما عندها real options)
            rv_data = opt_mod.calc_realized_volatility(cur, days=30)
            if not rv_data.get("ok"):
                return None

            spot = rv_data["current_price"]
            rv_annual = rv_data["rv_annualized"]
            iv_synthetic = rv_annual * 1.15
            iv_pct = iv_synthetic * 100

            result["is_real"] = False
            result["spot"] = spot
            result["iv_pct"] = round(iv_pct, 1)
            result["rv_pct"] = round(rv_annual * 100, 1)

            # IV Signal للـsynthetic (نفس thresholds)
            if iv_synthetic < IV_LOW_THRESHOLD:
                result["iv_signal"] = "very_low"
                result["opportunities"].append({
                    "type": "iv_buy",
                    "strength": min(8, int((IV_LOW_THRESHOLD - iv_synthetic) * 20)),
                    "msg_ar": f"❄️ Synthetic IV منخفض ({iv_pct:.1f}%) — التذبذب التاريخي ضعيف"
                })
            elif iv_synthetic > IV_HIGH_THRESHOLD:
                result["iv_signal"] = "very_high"
                result["opportunities"].append({
                    "type": "iv_sell",
                    "strength": min(8, int((iv_synthetic - IV_HIGH_THRESHOLD) * 10) + 4),
                    "msg_ar": f"🔥 Synthetic IV عالي ({iv_pct:.1f}%) — تذبذب تاريخي قوي"
                })
            else:
                result["iv_signal"] = "normal"

        # حساب الـscore الإجمالي
        if result["opportunities"]:
            result["score"] = max(o["strength"] for o in result["opportunities"])
            result["ok"] = True

            # Summary بالعربي
            top_opp = max(result["opportunities"], key=lambda o: o["strength"])
            result["summary_ar"] = top_opp["msg_ar"]
        else:
            result["ok"] = True
            result["summary_ar"] = f"⚪ {cur}: لا توجد فرص واضحة (IV {result.get('iv_pct', 0):.1f}%)"

        _cache_set(cache_key, result)
        return result

    except Exception as e:
        logging.warning(f"analyze_symbol_options({symbol}) error: {e}")
        return None


# ─────────────────────────────────────────────
# Concurrent Scanner
# ─────────────────────────────────────────────

def scan_real_options_deep() -> List[Dict]:
    """فحص شامل لـBTC/ETH/SOL (real options)"""
    results = []
    for cur in REAL_CURRENCIES:
        try:
            r = analyze_symbol_options(cur, deep=True)
            if r and r.get("ok"):
                results.append(r)
        except Exception as e:
            logging.warning(f"deep scan {cur} failed: {e}")
    return results


def scan_symbols_concurrent(symbols: List[str],
                            workers: int = SCAN_WORKERS) -> List[Dict]:
    """
    يفحص قائمة عملات بـconcurrent threads.
    Returns: [analyze results...]
    """
    results = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(analyze_symbol_options, sym, False): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            try:
                r = future.result(timeout=30)
                if r and r.get("ok"):
                    results.append(r)
            except Exception as e:
                sym = futures[future]
                logging.warning(f"scan {sym} error: {e}")

    return results


# ─────────────────────────────────────────────
# Master Scan Function
# ─────────────────────────────────────────────

def run_full_scan(scope: str = "all",
                  min_score: int = 5) -> Dict:
    """
    تشغيل المسح الكامل.

    Args:
        scope: 'real' (BTC/ETH/SOL only) | 'top30' | 'top100' | 'all'
        min_score: الحد الأدنى للـscore لإظهار الفرصة

    Returns:
    {
        "ok": True,
        "scope": "all",
        "scanned": 580,
        "opportunities_found": 47,
        "duration_sec": 65,
        "results": [...]  # مرتبة حسب الـscore
    }
    """
    start_time = time.time()

    # ① Deep scan لـBTC/ETH/SOL
    real_results = scan_real_options_deep()
    logging.info(f"Real scan: {len(real_results)} results")

    # ② نحدد العملات المسح بناءً على الـscope
    light_results = []

    if scope == "real":
        # فقط real options
        pass
    else:
        if scope == "top30":
            symbols = get_top_symbols_by_volume(30)
        elif scope == "top100":
            symbols = get_top_symbols_by_volume(100)
        else:  # all
            symbols = get_all_active_symbols()

        # نستثني العملات اللي عملنا لها deep scan
        symbols = [s for s in symbols
                   if s.replace("USDT", "") not in REAL_CURRENCIES]

        logging.info(f"Light scan: {len(symbols)} symbols...")

        if symbols:
            light_results = scan_symbols_concurrent(symbols)
            logging.info(f"Light scan: {len(light_results)} results")

    # ③ نجمع كل النتائج ونرتب
    all_results = real_results + light_results

    # نفلتر حسب min_score
    filtered = [r for r in all_results if r.get("score", 0) >= min_score]

    # نرتب حسب الـscore
    filtered.sort(key=lambda x: x.get("score", 0), reverse=True)

    duration = time.time() - start_time

    return {
        "ok": True,
        "scope": scope,
        "scanned": len(all_results),
        "opportunities_found": len(filtered),
        "duration_sec": round(duration, 1),
        "min_score": min_score,
        "results": filtered,
        "scanned_at": datetime.utcnow().isoformat(),
    }


# ─────────────────────────────────────────────
# Display Formatters
# ─────────────────────────────────────────────

def generate_trade_decision(result: Dict) -> Dict:
    """
    يحوّل الفرص (opportunities) إلى **قرار تداولي واضح**.

    Returns:
    {
        "action": "BUY_STRADDLE" | "SELL_IRON_CONDOR" | "BUY_CALL" | "BUY_PUT" |
                  "BUY_CALL_SPREAD" | "BUY_PUT_SPREAD" | "WAIT",
        "action_ar": "اشتري Long Straddle (شراء Call + Put معاً)",
        "reason_ar": "IV عالي جداً + skew محايد = الأفضل بيع premium",
        "trade_setup": {
            "what": "Long Straddle ATM",
            "how": "اشتري Call + Put عند نفس الـStrike",
            "best_when": "تتوقع تذبذب قوي بأي اتجاه",
            "max_loss": "تكلفة الـpremium",
            "max_profit": "غير محدود (نظرياً)",
        },
        "quick_command": "استراتيجية BTC volatile",
        "color": "🟢" | "🔴" | "🟡" | "⚪",
        "risk_warning_ar": "..."
    }
    """
    if not result.get("opportunities"):
        return {
            "action": "WAIT",
            "action_ar": "⏳ انتظر — لا توجد إشارات قوية",
            "reason_ar": "الفرص غير واضحة الآن",
            "color": "⚪",
        }

    cur = result.get("symbol", "?")
    spot = result.get("spot", 0)
    iv_pct = result.get("iv_pct", 0)
    iv_signal = result.get("iv_signal", "normal")
    skew_signal = result.get("skew_signal", "neutral")
    is_real = result.get("is_real", False)

    # Format للأرقام حسب السعر
    if spot < 1:
        fmt_price = lambda x: f"{x:.4f}"
    elif spot < 100:
        fmt_price = lambda x: f"{x:.2f}"
    else:
        fmt_price = lambda x: f"{int(x):,}"

    # ATM strike تقريبي
    atm = spot
    otm_call = spot * 1.10  # +10%
    otm_put = spot * 0.90   # -10%

    # ════════════════════════════════════════
    # القرار حسب الإشارات
    # ════════════════════════════════════════

    # 🔥 حالة 1: IV عالي جداً (>100%) → بيع Premium
    if iv_signal == "very_high":
        return {
            "action": "SELL_PREMIUM",
            "action_ar": "🔴 *بيع Premium* (Iron Condor)",
            "reason_ar": f"IV عالي جداً ({iv_pct:.0f}%) — Options غالية، الأفضل تبيع",
            "trade_setup": {
                "what": "Iron Condor",
                "how": f"بيع Put ${fmt_price(otm_put)} + بيع Call ${fmt_price(otm_call)} "
                       f"+ شراء Put أبعد (حماية) + شراء Call أبعد (حماية)",
                "best_when": "تتوقع السعر يبقى في نطاق ضيق (ranging)",
                "max_profit": "Net Credit (تستلم premium مقدماً)",
                "max_loss": "محدود (الفرق بين الـwings)",
                "estimated_profit": "5-15% من الـcollateral",
            },
            "quick_command": f"استراتيجية {cur} neutral",
            "color": "🔴",
            "risk_warning_ar": (
                "⚠️ *خطر:* لو السعر تجاوز الـwings، خسارة سريعة. "
                "حدد Stop Loss عند 50% من max loss."
            ),
            "trader_type": "محترف (يعرف option spreads)",
        }

    # ❄️ حالة 2: IV منخفض جداً (<40%) → شراء Premium
    if iv_signal == "very_low":
        # نتحقق من Skew لتحديد الاتجاه
        if skew_signal == "bullish":
            return {
                "action": "BUY_CALL",
                "action_ar": "🟢 *شراء Call* (رهان صاعد)",
                "reason_ar": (
                    f"IV منخفض ({iv_pct:.0f}%) + Skew bullish — "
                    f"Calls رخيصة + السوق متفائل = فرصة شراء"
                ),
                "trade_setup": {
                    "what": "Long Call ATM/OTM",
                    "how": f"اشتري Call عند ${fmt_price(atm)} (ATM) "
                           f"أو ${fmt_price(otm_call)} (OTM = أرخص)",
                    "best_when": "تتوقع صعود قوي خلال 30-60 يوم",
                    "max_profit": "غير محدود (نظرياً)",
                    "max_loss": "محدود (الـpremium المدفوع)",
                    "estimated_breakeven": f"${fmt_price(atm * 1.05)}",
                },
                "quick_command": f"استراتيجية {cur} bullish",
                "color": "🟢",
                "risk_warning_ar": (
                    "⚠️ Time decay يأكل قيمة Call يومياً. "
                    "اختر expiry بعيد (60D+) لتقليل Theta."
                ),
                "trader_type": "متوسط",
            }
        elif skew_signal == "bearish":
            return {
                "action": "BUY_PUT",
                "action_ar": "🔴 *شراء Put* (رهان هابط)",
                "reason_ar": (
                    f"IV منخفض ({iv_pct:.0f}%) + Skew bearish — "
                    f"Puts رخيصة + السوق خايف = فرصة شراء حماية"
                ),
                "trade_setup": {
                    "what": "Long Put ATM/OTM",
                    "how": f"اشتري Put عند ${fmt_price(atm)} (ATM) "
                           f"أو ${fmt_price(otm_put)} (OTM = أرخص)",
                    "best_when": "تتوقع هبوط قوي خلال 30-60 يوم",
                    "max_profit": f"كبير (يصل للـstrike - premium)",
                    "max_loss": "محدود (الـpremium المدفوع)",
                },
                "quick_command": f"استراتيجية {cur} bearish",
                "color": "🔴",
                "risk_warning_ar": "⚠️ نفس مخاطر الـCall لكن في الاتجاه المعاكس.",
                "trader_type": "متوسط",
            }
        else:
            # Skew محايد + IV منخفض = Long Straddle
            return {
                "action": "BUY_STRADDLE",
                "action_ar": "⚡ *شراء Straddle* (رهان على التذبذب)",
                "reason_ar": (
                    f"IV منخفض ({iv_pct:.0f}%) — Options رخيصة جداً، "
                    f"اشتري الإثنين معاً (Call + Put) للربح من أي حركة قوية"
                ),
                "trade_setup": {
                    "what": "Long Straddle (Call + Put على نفس Strike)",
                    "how": f"اشتري Call + Put عند ${fmt_price(atm)} (ATM)",
                    "best_when": "تتوقع حركة قوية لكن ما تعرف الاتجاه (قبل أحداث)",
                    "max_profit": "غير محدود (إذا السعر تحرك بقوة)",
                    "max_loss": "تكلفة الـpremiums",
                    "required_move": f"~{iv_pct/4:.1f}% للتعادل",
                },
                "quick_command": f"استراتيجية {cur} volatile",
                "color": "🟡",
                "risk_warning_ar": (
                    "⚠️ تحتاج حركة قوية للربح. لو السعر استقر، خسارة كاملة للـpremium."
                ),
                "trader_type": "متوسط - متقدم",
            }

    # 🟢 حالة 3: Skew bullish قوي + IV عادي = شراء Call
    if skew_signal == "bullish":
        return {
            "action": "BUY_CALL",
            "action_ar": "🟢 *شراء Call* (السوق صاعد)",
            "reason_ar": f"Skew bullish — السوق يسعّر Calls أرخص نسبياً",
            "trade_setup": {
                "what": "Long Call OTM",
                "how": f"اشتري Call عند ${fmt_price(otm_call)} (10% فوق السعر)",
                "best_when": "تتوقع استمرار الصعود",
                "max_profit": "غير محدود",
                "max_loss": "محدود (الـpremium)",
            },
            "quick_command": f"استراتيجية {cur} bullish",
            "color": "🟢",
            "risk_warning_ar": "⚠️ Theta decay، اختر expiry بعيد.",
            "trader_type": "متوسط",
        }

    # 🔴 حالة 4: Skew bearish + IV عادي = شراء Put
    if skew_signal == "bearish":
        return {
            "action": "BUY_PUT",
            "action_ar": "🔴 *شراء Put* (السوق خايف)",
            "reason_ar": f"Skew bearish — Puts أغلى = توقع هبوط",
            "trade_setup": {
                "what": "Long Put OTM",
                "how": f"اشتري Put عند ${fmt_price(otm_put)} (10% تحت السعر)",
                "best_when": "تتوقع استمرار الهبوط",
                "max_profit": "كبير",
                "max_loss": "محدود",
            },
            "quick_command": f"استراتيجية {cur} bearish",
            "color": "🔴",
            "risk_warning_ar": "⚠️ نفس مخاطر Call.",
            "trader_type": "متوسط",
        }

    # 🎯 حالة 5: Max Pain pull (للـreal options فقط)
    for opp in result.get("opportunities", []):
        if opp.get("type") == "max_pain_pull":
            mp = result.get("max_pain", 0)
            mp_dist = result.get("max_pain_distance", 0)
            direction = "صعود" if mp_dist > 0 else "هبوط"
            action_type = "BUY_CALL" if mp_dist > 0 else "BUY_PUT"
            return {
                "action": action_type,
                "action_ar": f"🎯 *Max Pain Pull* — توقع {direction}",
                "reason_ar": (
                    f"Max Pain عند ${mp:,.0f} ({mp_dist:+.1f}%) — "
                    f"السوق قد ينجذب نحو هذا السعر عند الـExpiry"
                ),
                "trade_setup": {
                    "what": f"Buy {'Call' if mp_dist > 0 else 'Put'} عند Max Pain",
                    "how": f"Strike ≈ ${mp:,.0f}, Expiry قريب من weekly",
                    "best_when": "خلال آخر 7 أيام قبل expiry",
                    "max_profit": "محدود",
                },
                "quick_command": f"خيارات {cur}",
                "color": "🟢" if mp_dist > 0 else "🔴",
                "risk_warning_ar": "⚠️ Max Pain إشارة إحصائية، ليس قاعدة مطلقة.",
                "trader_type": "متقدم",
            }

    # ⚪ حالة 6: ما فيش إشارة قوية
    return {
        "action": "WAIT",
        "action_ar": "⏳ *انتظر* — الإشارات ضعيفة",
        "reason_ar": "لا توجد فرصة واضحة الآن",
        "color": "⚪",
    }


def fmt_decision(decision: Dict) -> str:
    """تنسيق القرار التداولي للعرض"""
    action_ar = decision.get("action_ar", "")
    reason = decision.get("reason_ar", "")
    color = decision.get("color", "⚪")
    setup = decision.get("trade_setup", {})
    quick_cmd = decision.get("quick_command", "")
    risk = decision.get("risk_warning_ar", "")
    trader = decision.get("trader_type", "")

    msg = f"   {color} *القرار:* {action_ar}\n"
    msg += f"   _{reason}_\n"

    if setup:
        msg += f"\n   📋 *كيف:*\n"
        msg += f"   • {setup.get('how', '?')}\n"
        if setup.get("best_when"):
            msg += f"   • متى: {setup['best_when']}\n"
        if setup.get("max_profit"):
            msg += f"   • أقصى ربح: {setup['max_profit']}\n"
        if setup.get("max_loss"):
            msg += f"   • أقصى خسارة: {setup['max_loss']}\n"

    if risk:
        msg += f"\n   {risk}\n"

    if trader:
        msg += f"   👤 المتداول المناسب: _{trader}_\n"

    if quick_cmd:
        msg += f"\n   💎 الأمر السريع: `{quick_cmd}`\n"

    return msg


def fmt_scan_results(scan_data: Dict, top_n: int = 15) -> str:
    """تنسيق نتائج المسح للعرض في تيليجرام"""
    if not scan_data.get("ok"):
        return "❌ المسح فشل"

    scanned = scan_data["scanned"]
    found = scan_data["opportunities_found"]
    duration = scan_data["duration_sec"]
    scope = scan_data["scope"]
    results = scan_data["results"][:top_n]

    scope_label = {
        "real": "BTC/ETH/SOL فقط",
        "top30": "أعلى 30 عملة",
        "top100": "أعلى 100 عملة",
        "all": "كل العملات",
    }.get(scope, scope)

    msg = f"🔍 *Options Scanner — نتائج*\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n"
    msg += f"📊 النطاق: *{scope_label}*\n"
    msg += f"🔬 تم فحص: *{scanned}* عملة\n"
    msg += f"💎 الفرص: *{found}* عملة\n"
    msg += f"⏱ الوقت: {duration:.1f}s\n"
    msg += f"📊 Min score: {scan_data['min_score']}/10\n\n"

    if not results:
        msg += "❌ ما لقينا فرص بهذه المعايير\n"
        msg += "💡 جرّب: `ماسح_خيارات low` (min_score=3)"
        return msg

    msg += f"━━━━━━━━━━━━━━━━━━\n"
    msg += f"📋 *Top {min(top_n, len(results))} فرصة:*\n\n"

    for i, r in enumerate(results, 1):
        cur = r["symbol"]
        score = r["score"]
        is_real = r.get("is_real", False)
        spot = r.get("spot", 0)
        iv_pct = r.get("iv_pct", 0)

        # Score emoji
        if score >= 8:
            emoji = "🔥🔥"
        elif score >= 6:
            emoji = "🔥"
        elif score >= 4:
            emoji = "⚡"
        else:
            emoji = "📊"

        real_tag = "✅" if is_real else "⚠️"

        msg += f"━━━ *#{i}* ━━━\n"
        msg += f"{emoji} *{cur}* {real_tag} (score {score}/10)\n"
        msg += f"   💰 ${spot:,.4f} | IV {iv_pct:.1f}%\n"

        # نضيف skew لو real
        if is_real and r.get("skew_pct") is not None:
            msg += f"   📊 Skew: {r['skew_pct']:+.1f}%"
            if r.get("pcr"):
                msg += f" | PCR: {r['pcr']:.2f}"
            msg += "\n"

        # ✨ القرار التداولي الواضح
        decision = generate_trade_decision(r)
        msg += "\n"
        msg += fmt_decision(decision)
        msg += "\n"

    msg += "━━━━━━━━━━━━━━━━━━\n"
    msg += "💡 *الأوامر المساعدة:*\n"
    msg += "`خيارات [عملة]` — تحليل تفصيلي\n"
    msg += "`اشترك_خيارات` — تنبيهات تلقائية كل 30 دقيقة\n"
    msg += "`ماسح_خيارات real` — فقط BTC/ETH/SOL (أسرع)\n"

    return msg


def fmt_scan_quick(scan_data: Dict) -> str:
    """نسخة مختصرة (للـpush alerts)"""
    if not scan_data.get("ok"):
        return ""

    found = scan_data["opportunities_found"]
    if found == 0:
        return ""

    results = scan_data["results"][:5]  # top 5 only

    msg = f"💎 *Options Scanner Alert*\n"
    msg += f"━━━━━━━━━━━━━━━━━\n"
    msg += f"🔥 *{found}* فرصة جديدة!\n\n"

    for i, r in enumerate(results, 1):
        cur = r["symbol"]
        score = r["score"]
        spot = r.get("spot", 0)
        iv_pct = r.get("iv_pct", 0)
        is_real = "✅" if r.get("is_real") else "⚠️"

        msg += f"*{i}.* *{cur}* {is_real} (score {score}/10)\n"
        msg += f"   💰 ${spot:,.4f} | IV {iv_pct:.1f}%\n"

        if r.get("opportunities"):
            top = max(r["opportunities"], key=lambda o: o["strength"])
            msg += f"   {top['msg_ar']}\n\n"

    msg += "━━━━━━━━━━━━━━━━━\n"
    msg += "💡 `ماسح_خيارات` للتفاصيل الكاملة"
    return msg


# ─────────────────────────────────────────────
# Background Job (للماسح التلقائي)
# ─────────────────────────────────────────────

async def options_scanner_job(ctx):
    """
    Job يعمل في الخلفية كل 30 دقيقة.
    يمسح ويرسل alerts للمشتركين.
    """
    try:
        # نجلب المشتركين من DB
        try:
            import MAHMOUD_DB as db
            subscribers = db.get_options_scanner_subscribers()
        except Exception:
            return

        if not subscribers:
            return

        logging.info(f"Options scanner: running for {len(subscribers)} subscribers")

        # نشغّل المسح (real فقط للـbackground - أسرع)
        loop = asyncio.get_event_loop()
        scan_data = await loop.run_in_executor(
            None,
            lambda: run_full_scan(scope="real", min_score=6)
        )

        if not scan_data.get("ok") or scan_data["opportunities_found"] == 0:
            return

        msg = fmt_scan_quick(scan_data)
        if not msg:
            return

        # نرسل للمشتركين
        for sub in subscribers:
            chat_id = sub.get("chat_id")
            if not chat_id:
                continue
            try:
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=msg,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.warning(f"Send options alert to {chat_id} failed: {e}")

    except Exception as e:
        logging.warning(f"options_scanner_job error: {e}")
