# 📊 MAHMOUD TRADING BOT v5 — PURE TRADING

بوت Telegram احترافي للتداول الكريبتو، مع:
- 🎯 **نظام إشارات موزون** (15 نقطة) عبر 10 مؤشرات
- 💎 **Smart Liquidity Engine** — SL/TP بناءً على السيولة الفعلية (Order Blocks, FVG, Equal Highs/Lows)
- 🤖 **AI Verdict** — رأي AI ترجيحي مع كل إشارة
- 🔍 **Auto Scanner** — مسح تلقائي لـ580 عملة كل 30 دقيقة
- ⚡ **Scalp Scanner** — مسح كل العملات على 1m/5m كل 5 دقائق
- 🐋 **Whale Alert** — تنبيهات الحركات الكبيرة
- 📊 **Tracker** — تتبع الصفقات اليدوية + Risk Protection + Journal
- 🔬 **Backtest** — اختبار الإشارات على البيانات التاريخية
- 📈 **Long-term** — تحليل D1/W1 للـHodlers

---

## 🎯 الفلسفة

**v5 يركز فقط على التداول.** إذا كنت تحتاج أخبار/AI Council/Calendar، استخدم بوت آخر منفصل (مثل `news_crypto_bot`). هذا التقسيم يضمن:
- ⚡ سرعة استجابة أعلى
- 🛡 استقرار أكبر (لا يتأثر بمشاكل RSS أو AI)
- 🎯 تركيز كامل على جودة الإشارات

---

## 📂 هيكل الملفات

```
v5/
├── MAHMOUD_TRADING_v5.py       ← الملف الرئيسي (2816 سطر)
├── MAHMOUD_LIQUIDITY.py        ← Smart SL/TP بالسيولة (886 سطر) ⭐
├── MAHMOUD_AI_TRADING.py       ← AI ترجيح للإشارات (476 سطر) ⭐
├── MAHMOUD_DB.py               ← SQLite (5 جداول)
├── MAHMOUD_SIGNALS.py          ← نظام الـ15 نقطة
├── MAHMOUD_TRACKER.py          ← تتبع الصفقات اليدوية
├── MAHMOUD_RISK.py             ← حماية المحفظة + Journal
├── MAHMOUD_WHALE.py            ← Whale Alert
├── MAHMOUD_BACKTEST.py         ← اختبار تاريخي
├── MAHMOUD_LONGTERM.py         ← تحليل D1/W1
├── Procfile                    ← worker: python MAHMOUD_TRADING_v5.py
├── requirements.txt
├── runtime.txt                 ← python-3.11.9
└── env.example
```

---

## 🔑 Environment Variables

### إجباري:
```bash
BOT_TOKEN=8123456789:AAH...        # من @BotFather
ETHERSCAN_KEY=YOUR_KEY              # https://etherscan.io/apis
```

### موصى به (للأداء الكامل):
```bash
# AI Verdict — يكفي واحد فقط
GEMINI_API_KEY=AIza...              # 🆓 مجاني (1500 req/day)
# أو
CLAUDE_API_KEY=sk-ant-...           # الأذكى (مدفوع)
# أو  
OPENAI_API_KEY=sk-...               # احتياطي
```

### اختياري:
```bash
WHALE_ALERT_KEY=YOUR_KEY            # تنبيهات الحيتان
MIN_WHALE_USD=1000000               # الحد الأدنى ($1M)
```

---

## 🚀 النشر على Railway

### 1️⃣ احصل على API Keys
- **Telegram Bot Token:** [@BotFather](https://t.me/botfather) → `/newbot`
- **Etherscan:** https://etherscan.io/apis (مجاني)
- **Gemini AI (موصى به):** https://aistudio.google.com/apikey (مجاني)

### 2️⃣ ارفع الكود
```bash
git init
git add .
git commit -m "v5 initial"
git remote add origin <YOUR_REPO>
git push -u origin main
```

### 3️⃣ على Railway
1. **New Project** → **Deploy from GitHub**
2. **Variables** → أضف `BOT_TOKEN` و `ETHERSCAN_KEY` (والأخرى الاختيارية)
3. **Deploy**

### 4️⃣ تأكد من النجاح
في **Deploy Logs** يجب أن ترى:
```
======================================================
  MAHMOUD TRADING BOT v5 — PURE TRADING ✅
======================================================
  Core Engine:
  ├ Scoring     : موزون 0-15 (إشارة قوية ≥12)
  ├ Smart SL/TP : 3 مستويات بناءً على السيولة
  ...
  AI Verdict (للإشارات): 1/3
  ├ Claude    : ❌
  ├ Gemini    : ✅
  └ OpenAI    : ❌
======================================================
  أرسل /start على تيليقرام
======================================================
```

---

## 📱 الأوامر الكاملة

### 📈 التحليل الفوري
| الأمر | الوصف |
|---|---|
| `BTC` / `ETH` / `SOL` / أي عملة | تحليل كامل + Smart SL/TP + AI verdict |
| `تابع BTC` | تنبيه عند الإشارات القوية ≥12/15 |
| `وقف BTC` | إيقاف المتابعة |

### ⚡ Scalping
| الأمر | الوصف |
|---|---|
| `سكالب BTC` | تحليل سكالب فوري (1m/5m) |
| `تابع سكالب BTC` | متابعة سكالب |
| `ماسح_سكالب` | مسح كل العملات الفيوتشر كل 5 دقائق |
| `وقف_مسح_سكالب` | إيقاف |

### 🔍 الماسح الذكي (~580 عملة)
| الأمر | الوصف |
|---|---|
| `ماسح` | تفعيل (12/15 = 80% قوة) |
| `ماسح 13` | حد أقوى (إشارات أقل لكن أدق) |
| `ماسح 9` | حد أخف (إشارات أكثر) |
| `ماسح nospot` | فيوتشر فقط (~350 عملة) |
| `حالة الماسح` | عرض الإعدادات الحالية |
| `وقف ماسح` | إيقاف |

### 🎮 تتبع الصفقات اليدوية
| الأمر | الوصف |
|---|---|
| `صفقة LONG BTC 43500 42500 44500 45500 46500` | تسجيل صفقة LONG |
| `صفقة SHORT BTC 43500 44500 42500 41500 40500` | تسجيل صفقة SHORT |
| `صفقاتي` | عرض الصفقات المفتوحة |
| `اقفل BTC 43200` | إغلاق صفقة |
| `الغاء BTC` | إلغاء بدون احتساب |
| `تعديل BTC sl 42800` | تعديل SL/TP |

### 🛡 حماية المحفظة
| الأمر | الوصف |
|---|---|
| `حماية` | عرض الإعدادات الحالية |
| `حد_يومي 5` | حد الخسارة اليومية (5%) |
| `حد_صفقات 5` | الحد الأقصى للصفقات اليومية |

### 📊 دفتر التداول
| الأمر | الوصف |
|---|---|
| `جورنال` | Win Rate / Profit Factor / Sharpe (آخر 30 يوم) |
| `جورنال 7` | آخر 7 أيام |
| `جورنال 90` | آخر 90 يوم |

### 🐋 الحيتان
| الأمر | الوصف |
|---|---|
| `حيتان` | حركات الحيتان آخر 6 ساعات |
| `حيتان BTC` | حركات BTC فقط آخر 24 ساعة |

### 🔬 Backtest + Long-term
| الأمر | الوصف |
|---|---|
| `backtest BTC 30` | اختبار الإشارات على آخر 30 يوم |
| `طويل BTC` | تحليل D1/W1 + Bollinger Bands |

### 🏥 تشخيصي
| الأمر | الوصف |
|---|---|
| `صحة` | فحص شامل: DB + Modules + AI test + Functions |

---

## 🎯 شكل الإشارة الكاملة (مثال)

```
📊 BTCUSDT — 🟢 LONG
💰 $43,500.00 | 🕐 14:25
━━━━━━━━━━━━━━━━━

📊 النتيجة الموزونة (0-15):
🟢 LONG:  ████████░░ 13/15
🔴 SHORT: ██░░░░░░░░ 2/15

⏱ MTF: 1h🟢 | 4h🟢 | 1d🟢

🔍 تفصيل المؤشرات:
✅ ICT/SMC bullish +3pt
✅ MTF aligned +2pt
✅ MACD صاعد +2pt
✅ EMA stack +2pt
✅ Funding سلبي +1pt
...

⚡ القرار: 🟢 LONG قوي (13/15)

📊 المستويات الذكية (مبنية على السيولة):

🛡 Stop Loss (3 خيارات):
🟢 Conservative: $42,180
   _خلف Order Block 4H + Buffer ATR×0.5_
   Risk: 3.03%
🟡 Balanced: $42,580
   _خلف Swing Low + Buffer ATR×0.3_
   Risk: 2.11%
🔴 Aggressive: $42,950
   _ATR×0.9 (سريع)_
   Risk: 1.27%

⚠️ Danger Zones (تجنّب SL هنا):
🚨 $43,000 (Round Number)

🎯 Take Profit (3 أهداف):
🟢 TP1: $44,300 (80% احتمال)
   _قبل Bearish OB (سيولة قوية)_
   R:R = 1:0.87
🟡 TP2: $45,200 (55% احتمال)
   _Equal Highs Cluster (تجمع stops)_
   R:R = 1:1.85
🔴 TP3: $46,500 (35% احتمال)
   _Round Number $46,500_
   R:R = 1:3.27

⚠️ Reject Zones (مقاومة في الطريق):
🟠 $44,500 (Bearish OB)

━━━━━━━━━━━━━━━━━
📊 متوسط R:R مرجّح: 1:1.85
🎖 جودة الصفقة: 🟡 مقبول

📋 خطة الخروج التدريجي:
• @ TP1 → اقفل 50% + SL → Breakeven
• @ TP2 → اقفل 30% + SL → TP1
• @ TP3 → اقفل آخر 20%

💰 Position Size (مع SL Balanced):
Account  Risk   Qty       Value
$1000   1.0%   0.0237   $1,031
$1000   2.0%   0.0473   $2,061
$5000   1.5%   0.1773   $7,729

🤖 رأي AI (GEMINI):
━━━━━━━━━━━━━━━━━
🟢 الترجيح: ✅ ادخل الآن
💪 الثقة: ████████░░ 8/10

📝 السبب:
ICT bullish + MTF aligned + Funding سلبي = 
انعكاس قوي. السيولة عند $42,580 محمية بـSwing Low.

🎯 استراتيجية الدخول:
ادخل بـ50% Market الآن، 50% Limit عند $43,200 (retest)

⚙️ AI يفضّل:
  • SL: Balanced
  • TP: TP2

⚠️ تحذيرات:
احذر من Reject Zone عند $44,500 — قد يحتاج retest

📋 لإضافة هذه الصفقة في التتبع:
صفقة LONG BTC 43500 42580 44300 45200 46500

⚠️ تحليل تعليمي — البوت لا يفتح صفقات تلقائياً
```

---

## 🛠 المعمارية الفنية

### نظام النقاط (15 نقطة كحد أقصى):
| المؤشر | النقاط |
|---|---|
| ICT/SMC | 3 |
| MTF Alignment (1h+4h+1d) | 2 |
| MACD | 2 |
| EMA Stack | 2 |
| Funding Rate | 1 |
| Open Interest | 1 |
| RSI | 1 |
| Long/Short Ratio | 1 |
| Liquidations | 1 |
| CVD | 1 |
| **المجموع** | **15** |

### Smart Liquidity Engine:
- يحلل **خريطة السيولة الفعلية** حول السعر (آخر 50 شمعة)
- يكتشف Order Blocks (Bullish/Bearish) مع قياس قوة كل واحد
- يحدد FVG (Fair Value Gaps) كـsupport/resistance
- يجد Equal Highs/Lows (تجمعات stops)
- يحسب Round Numbers الذكية حسب نطاق السعر

### AI Verdict (للإشارات فقط):
- **Gemini 2.5 Flash** افتراضي (مجاني، JSON mode)
- **Claude Sonnet 4.5** للأذكى (مدفوع)
- **GPT-4o-mini** احتياطي
- Auto-fallback: إذا فشل واحد، يجرب الباقي

---

## ⚠️ تحذيرات

1. **هذا تحليل تعليمي**، ليس نصيحة استثمارية
2. **دقة الإشارات المتوقعة:** 55-70% (مع MTF + ICT)
3. **إدارة المخاطر:** 1-2% مخاطرة لكل صفقة كحد أقصى
4. **البوت لا يفتح صفقات تلقائياً** — أنت تنفذ يدوياً
5. **لا تستخدم رأس مال لا يمكنك خسارته**
6. **Smart Liquidity يساعد لكن لا يضمن** — السوق قد يكسر أي مستوى

---

## 🔧 استكشاف الأخطاء

### `OperationalError: unable to open database file`
- المسار في `MAHMOUD_DB_PATH` غير قابل للكتابة
- الحل: احذف `MAHMOUD_DB_PATH` من Variables، وسيستخدم cwd

### `AI verdict failed`
- جرّب `صحة` لرؤية أي AI يفشل
- تحقق من API key (نسخ خاطئ، انتهاء صلاحية، رصيد منتهي)

### `Smart Liquidity levels failed`
- البوت سيستخدم ATR-based fallback تلقائياً
- في الـlogs: ابحث عن `Smart Liquidity levels failed for SYMBOL`

### قاعدة البيانات تختفي بعد restart
- Railway Free Tier: container غير دائم
- الحل: أضف Railway Volume mount على `/data`

---

## 📞 الدعم

للمشاكل والاقتراحات، تواصل عبر Telegram أو افتح issue.

⚠️ _تحليلات تعليمية فقط — ليس نصيحة استثمارية._

---

## 📊 سجل التحديثات

### v5.0 (الحالي) — Pure Trading
- ❌ حذف: News, AI News, Calendar, Today's View, Massive integration
- ✅ إضافة: **Smart Liquidity Engine** (Order Blocks + FVG + Equal Levels)
- ✅ إضافة: **AI Verdict** للإشارات (Claude/Gemini/OpenAI auto-fallback)
- ⚡ تحسينات: Health Check محدّث، menu أوضح، logging أفضل

### v4 — Full Edition (deprecated)
- 12 موديل مع News + AI Council + Calendar + Today
- معقّد ومتشابك مع dependencies كثيرة
