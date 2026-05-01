# MIGRATION v3 → v4.2 FULL EDITION

## ملخص الإصدار
v4.2 FULL EDITION هو إعادة بناء جذرية لـ MAHMOUD Bot. يضيف **3 موجات + Scanner v4** على نواة v3.

---

## 🆕 الجديد في v4.2: Scanner ذكي شامل

### المواصفات
- **النطاق:** Binance Futures + Spot (~580 عملة USDT)
- **المؤشرات:** 10 مؤشرات موزونة (15 نقطة كاملة)
- **حد الإشارة:** ≥80% (12/15 فيوتشر، 9/11 سبوت)
- **الدورة:** كل 30 دقيقة
- **الـCooldown:** 4 ساعات/عملة (يمنع التكرار)
- **Persistence:** يحفظ الاشتراكات في DB (يستمر بعد restart)
- **أقصى/دورة:** 5 إشارات (الأعلى قوة)

### الجداول الجديدة
```sql
scanner_subscribers     -- chat_id, threshold, scan_spot, cooldown_hours
scanner_alerts_sent     -- chat_id, symbol, sent_at, action, score
```

### الأوامر
```
ماسح               → تفعيل (12/15 = 80%، فيوتشر+سبوت)
ماسح 13            → أقوى (87%)
ماسح 9             → أكثر إشارات (60%، فيوتشر فقط لأن 80% لا يتحقق هنا)
ماسح nospot        → فيوتشر فقط
حالة الماسح        → الإعدادات الحالية
وقف ماسح           → إيقاف + حذف من DB
```

---

## 🆕 الملفات الجديدة (12 ملف)

### Core Modules (Wave 0):
- **MAHMOUD_DB.py** — SQLite layer (8 جداول)
- **MAHMOUD_SIGNALS.py** — Weighted scoring (0-15)
- **MAHMOUD_TRACKER.py** — Manual trade tracking
- **MAHMOUD_RISK.py** — Risk protection + journal

### Wave 1 — News + Time Awareness:
- **MAHMOUD_NEWS.py** — RSS من 9 مصادر + **Massive.com News API** (sentiment + ticker tagging)
- **MAHMOUD_CALENDAR.py** — **Massive.com Economy API** (CPI/Yields/Expectations) + FOMC 2026 hardcoded + CoinMarketCal
- **MAHMOUD_TODAY.py** — Today's View + Sessions + Top 3 Catalysts

### Wave 2 — AI Brains:
- **MAHMOUD_AI.py** — Claude + Gemini + GPT-4o + Multi-AI Consensus

### Wave 3 — Power Tools:
- **MAHMOUD_WHALE.py** — Whale Alert API
- **MAHMOUD_BACKTEST.py** — Historical signal backtesting
- **MAHMOUD_LONGTERM.py** — D1/W1 hodl recommendations
- **Bollinger Bands** مدمج في SIGNALS

---

## 🔧 التعديلات الجوهرية

### 1. النقاط الـ7 الجوهرية:

| # | المشكلة في v3 | الحل في v4 |
|---|---|---|
| 1 | 5/9 threshold فضفاض | **12/15 موزون** + 9/15 ضعيف |
| 2 | RSI داخل ICT فقط | RSI + MACD + EMA Stack منفصلة |
| 3 | SL ثابت `low * 0.99` | **ATR-based × 3 احتياطات** |
| 4 | لا MTF alignment | **MTF بين 1h/4h/1d** إجباري |
| 5 | Liquidations $100 | **Dynamic threshold** ($1M/$200K/$50K) |
| 6 | لا BTC filter للـalts | **BTC bias filter** على 4h |
| 7 | كل 15 دقيقة | **60s** للصفقات + 5min للتحليل العميق |

### 2. تحويل من Auto-Entry إلى Manual Tracking:
- v3: البوت كان يفتح صفقات تلقائياً
- v4: **إشارات فقط** + المستخدم يدخل يدوياً
- جديد: تتبع كامل للصفقات (SL/TP/NEAR/REVERSAL/ADD)

---

## 📊 الجداول الجديدة في DB

```sql
tracked_trades, trade_alerts_sent, risk_protection, trade_journal  -- Wave 0
seen_news, news_subscribers                                          -- Wave 1
ai_recommendations                                                    -- Wave 2
whale_alerts, cache_store                                             -- Wave 3
```

---

## 🎯 الأوامر الجديدة

### Wave 0 (Tracking):
```
صفقة LONG BTC 43500 42500 44500 45500 46500
صفقاتي | اقفل BTC 43200 | الغاء BTC | تعديل BTC sl 42800
حماية | حد_يومي 8 | حد_صفقات 5 | جورنال
```

### Wave 1 (News + Calendar):
```
أخبار | أخبار BTC | عاجل
تقويم | تقويم_اسبوع | كاتاليست
ماكرو                # CPI/Yields/Inflation Expectations من Massive
اليوم | جلسات | خطة BTC
اشترك_اخبار | اشترك_تقرير 8 0 | فلتر_عملات BTC,ETH
```

### Wave 2 (AI):
```
اجماع BTC          # تحليل بـ3 AIs
سؤال [نص]          # سؤال حر
```

### Wave 3 (Power):
```
حيتان | حيتان BTC
backtest BTC 30
طويل BTC
```

---

## ⚙️ Background Jobs

| Job | Interval | Purpose |
|---|---|---|
| `tracked_monitor_job` | 60s | مراقبة SL/TP/NEAR للصفقات |
| `tracked_deep_analysis_job` | 5min | كشف Reversal/Add Opportunities |
| `news_check_job` | 15min | جلب RSS + إرسال breaking |
| `whale_check_job` | 10min | جلب تحويلات Whale Alert |
| `daily_report_job` | 60s | فحص لإرسال التقرير الصباحي |

---

## 🚀 خطوات النشر على Railway

### 1. الـVariables الإجبارية:
```
BOT_TOKEN, ETHERSCAN_KEY
```

### 2. Wave 1: `MASSIVE_API_KEY` (مفتاح واحد لكل من News + Calendar), `COINMARKETCAL_KEY` (اختياري)
### 3. Wave 2: `CLAUDE_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`
### 4. Wave 3: `WHALE_ALERT_KEY`, `MIN_WHALE_USD`

### 5. ⚠️ DB Persistence (مهم):
```bash
# على Railway Pro + Volume:
MAHMOUD_DB_PATH=/data/mahmoud_bot.db
# Settings → Volumes → /data
```

### 6. Procfile:
```
worker: python MAHMOUD_STABLE_FINAL_v4.py
```

---

## 📦 الإحصائيات

| | عدد |
|---|---|
| الموديولات | 12 |
| الجداول في DB | 8 |
| Background jobs | 7 |
| الأوامر الجديدة | 30+ |
| الـAPIs الخارجية | 7 (Binance + Etherscan + RSS×9 + TE + CMC + 3×AI + Whale) |
| AI Brains | 3 |
| إجمالي السطور | ~5,500 |

---

## ⚠️ ملاحظات مهمة

1. **DB Persistence** — على Railway Free Tier، الـDB يضيع عند redeploy. استخدم Volume mount.
2. **AI Costs** — كل تحليل بالـconsensus = 3 API calls. Claude/GPT-4o ليست مجانية.
3. **Whale Alert Free Tier** — 10 req/min، قد يفوّت بعض التحويلات في السوق النشط.
4. **Trading Economics** — guest:guest محدود؛ احصل على key مجاني.
5. **feedparser** — يحتاج تثبيت (موجود في requirements.txt).
