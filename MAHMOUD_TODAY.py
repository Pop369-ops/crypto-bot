"""
MAHMOUD_TODAY.py
═════════════════════════════════════════════════
Today's View — تقرير شامل لليوم:
  • Top 3 Catalysts (الأحداث الأهم القادمة)
  • Session Scenarios (آسيا / أوروبا / أمريكا)
  • Intraday Plan (سيناريوهات اليوم)
  • تقرير صباحي تلقائي للمشتركين
═════════════════════════════════════════════════
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import MAHMOUD_DB as db
import MAHMOUD_NEWS as news_mod
import MAHMOUD_CALENDAR as cal_mod


# ─────────────────────────────────────────────
# Sessions (UTC)
# ─────────────────────────────────────────────
# الجلسات بالـUTC. الكريبتو 24/7 لكن Volume يتركز في الجلسات

SESSIONS = {
    "asia":   {"name": "آسيا (طوكيو)",   "start": 0,  "end": 8,  "emoji": "🇯🇵"},
    "europe": {"name": "أوروبا (لندن)",  "start": 7,  "end": 16, "emoji": "🇬🇧"},
    "us":     {"name": "أمريكا (نيويورك)", "start": 13, "end": 22, "emoji": "🇺🇸"},
}


def current_session() -> str:
    """يرجع الجلسة الحالية"""
    h = datetime.utcnow().hour
    if 13 <= h < 22:
        return "us"
    if 7 <= h < 13:
        return "europe"
    return "asia"


def session_status_msg() -> str:
    cur = current_session()
    h = datetime.utcnow().hour
    msg = "🌍 *الجلسات الآن:*\n"
    for key, s in SESSIONS.items():
        active = s["start"] <= h < s["end"]
        marker = "🟢 *(نشطة)*" if active else "⚪"
        msg += f"  {s['emoji']} {s['name']}: {marker}\n"
    msg += f"\n📍 الجلسة الحالية: *{SESSIONS[cur]['name']}*"
    return msg


# ─────────────────────────────────────────────
# Session-specific behavior expectations
# ─────────────────────────────────────────────

SESSION_PATTERNS = {
    "asia": {
        "characteristics": [
            "🐢 Volume أقل عادة",
            "📈 BTC/ETH range-bound في الغالب",
            "🇯🇵 ساعات Tokyo/Seoul أكثر نشاطاً",
            "🎯 العملات الـAsian-favored (HYPER/SUI/NEAR) أنشط",
        ],
        "watch": ["BTC", "ETH", "SUI", "NEAR", "HYPER"],
    },
    "europe": {
        "characteristics": [
            "📊 Volume يبدأ يزيد",
            "🏦 افتتاح London = الأكبر للـForex",
            "🌊 موجات أكبر — breakouts ممكنة",
            "📰 أخبار EU/BoE قد تأثر",
        ],
        "watch": ["BTC", "ETH", "EUR-correlated"],
    },
    "us": {
        "characteristics": [
            "💥 الجلسة الأقوى — Volume عالي",
            "🇺🇸 افتتاح NY = ساعات الزخم",
            "📊 CPI/FOMC/News تنزل عادة هنا",
            "⚡ Volatility أعلى — حركات حادة",
            "🎯 ETF flows + معظم المؤسسات تتحرك",
        ],
        "watch": ["BTC", "ETH", "SOL", "ETF tickers"],
    },
}


def session_scenarios_msg() -> str:
    """سيناريوهات لكل جلسة"""
    msg = "🌐 *سيناريوهات الجلسات اليوم:*\n\n"
    for key, s in SESSIONS.items():
        pat = SESSION_PATTERNS.get(key, {})
        msg += f"{s['emoji']} *{s['name']}* "
        msg += f"({s['start']:02d}:00 - {s['end']:02d}:00 UTC)\n"
        for c in pat.get("characteristics", []):
            msg += f"   {c}\n"
        watch = pat.get("watch", [])
        if watch:
            msg += f"   👁 ركز على: *{', '.join(watch)}*\n"
        msg += "\n"
    return msg


# ─────────────────────────────────────────────
# Top 3 Catalysts (combines macro events + crypto news + market state)
# ─────────────────────────────────────────────

def get_top_3_catalysts() -> List[Dict]:
    """
    يجمع: macro events قادمة + breaking news + market events
    ويرجع أهم 3 حسب التأثير المتوقع
    """
    cats = []

    # ① Macro events قادمة في آخر 48h
    macro_events = cal_mod.get_top_catalysts(5)
    for ev in macro_events:
        d = ev["date"] if isinstance(ev["date"], datetime) \
            else datetime.fromisoformat(ev["date"])
        d_naive = d.replace(tzinfo=None) if d.tzinfo else d
        hours_until = int((d_naive - datetime.utcnow()).total_seconds() / 3600)
        if hours_until < 0 or hours_until > 48:
            continue
        priority = ev.get("importance", 1) * 10
        # bonus لو خلال 24h
        if hours_until < 24:
            priority += 5
        cats.append({
            "type": "macro",
            "title": ev.get("event", ""),
            "when": f"خلال {hours_until}h" if hours_until > 0
                    else "بدأت!",
            "details": (f"التوقع: {ev.get('forecast', 'N/A')} | "
                        f"السابق: {ev.get('previous', 'N/A')}"),
            "priority": priority,
            "emoji": "🏛",
        })

    # ② Breaking crypto news (impact >= 7) في آخر 6h
    breaking_news = db.get_recent_news(hours=6, min_impact=7, limit=5)
    for n in breaking_news:
        cats.append({
            "type": "news",
            "title": n["title"],
            "when": "اليوم",
            "details": f"المصدر: {n['source']} | تأثير {n['impact']}/10",
            "url": n.get("url"),
            "priority": n["impact"] * 8,
            "emoji": "🚨",
        })

    # ③ Token unlocks (لو COINMARKETCAL_KEY متاح)
    try:
        crypto_events = cal_mod.fetch_crypto_events(days_ahead=7)
        for ev in crypto_events[:3]:
            d = ev["date"] if isinstance(ev["date"], datetime) \
                else datetime.fromisoformat(ev["date"])
            d_naive = d.replace(tzinfo=None) if d.tzinfo else d
            hours_until = int((d_naive - datetime.utcnow()).total_seconds() / 3600)
            if hours_until < 0 or hours_until > 48:
                continue
            cats.append({
                "type": "crypto_event",
                "title": ev.get("title", ""),
                "when": f"خلال {hours_until}h",
                "details": f"العملات: {', '.join(ev.get('coins', []))}",
                "priority": 30 + ev.get("votes", 0) / 10,
                "emoji": "🎯",
            })
    except Exception:
        pass

    # ترتيب حسب الـpriority + خد أعلى 3
    cats.sort(key=lambda c: -c["priority"])
    return cats[:3]


def fmt_top_3_catalysts() -> str:
    cats = get_top_3_catalysts()
    if not cats:
        return ("🎯 *Top 3 Catalysts*\n\n"
                "✅ لا توجد محركات قوية في الـ48 ساعة القادمة\n"
                "_السوق في وضع \"بلا محرك\"_")
    msg = "🎯 *أهم 3 Catalysts قادمة:*\n\n"
    for i, c in enumerate(cats, 1):
        msg += f"*{i}. {c['emoji']} {c['title']}*\n"
        msg += f"   ⏰ {c['when']}\n"
        msg += f"   _{c['details']}_\n"
        if c.get("url"):
            msg += f"   [التفاصيل]({c['url']})\n"
        msg += "\n"
    return msg


# ─────────────────────────────────────────────
# Today's View — التقرير الشامل
# ─────────────────────────────────────────────

def today_view_msg(market_summary: Optional[str] = None) -> str:
    """
    التقرير اليومي الكامل:
    - ملخص السوق
    - Top 3 Catalysts
    - Session Scenarios
    - الأخبار العاجلة
    - تقويم اليوم
    """
    now = datetime.utcnow()
    msg = f"☀️ *تقرير اليوم — {now.strftime('%Y-%m-%d %H:%M UTC')}*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    # ── ملخص السوق ──
    if market_summary:
        msg += f"📊 *وضع السوق:*\n{market_summary}\n\n"

    # ── الجلسة الحالية ──
    msg += session_status_msg() + "\n\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    # ── Top 3 Catalysts ──
    msg += fmt_top_3_catalysts() + "\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    # ── أحداث اليوم (Macro) ──
    today_events = cal_mod.get_today_events()
    if today_events:
        msg += "📅 *أحداث اليوم (Macro):*\n\n"
        for ev in today_events[:5]:
            msg += cal_mod.fmt_event(ev)
        msg += "\n━━━━━━━━━━━━━━━━━━━━\n\n"

    # ── أخبار عاجلة آخر 12h ──
    breaking = db.get_recent_news(hours=12, min_impact=7, limit=5)
    if breaking:
        msg += "🚨 *أخبار مهمة (12h):*\n\n"
        for i, it in enumerate(breaking[:5], 1):
            sentiment_emoji = {"bullish": "🟢", "bearish": "🔴",
                               "neutral": "⚪"}.get(it.get("sentiment"), "⚪")
            msg += f"{i}. {sentiment_emoji} *{it['title'][:80]}*\n"
            msg += f"   _{it['source']} • تأثير {it['impact']}/10_\n\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    msg += "_التقرير لأغراض تعليمية — نظم وقتك بناءً على الـCatalysts_"
    return msg


def intraday_plan_msg(symbol: str = "BTC",
                      current_price: Optional[float] = None) -> str:
    """خطة Intraday لعملة محددة"""
    cur_session = current_session()
    pat = SESSION_PATTERNS.get(cur_session, {})

    msg = f"📋 *خطة Intraday — {symbol.upper()}*\n"
    if current_price:
        msg += f"السعر الآن: `${current_price}`\n"
    msg += f"الجلسة: {SESSIONS[cur_session]['emoji']} {SESSIONS[cur_session]['name']}\n"
    msg += "━━━━━━━━━━━━━━━━\n\n"

    msg += "🎯 *سمات الجلسة الحالية:*\n"
    for c in pat.get("characteristics", []):
        msg += f"  {c}\n"

    msg += "\n📊 *التوقع:*\n"
    if cur_session == "asia":
        msg += "  • تحركات هادئة — Range trading أفضل\n"
        msg += "  • انتظر breakout عند فتح أوروبا\n"
        msg += "  • SL ضيقة (0.5-1%)\n"
    elif cur_session == "europe":
        msg += "  • Volume يبدأ يزيد — حركة أكبر متوقعة\n"
        msg += "  • فرص breakout/breakdown قوية\n"
        msg += "  • انتبه لأخبار EU/BoE\n"
    else:  # us
        msg += "  • أكبر Volume + أعلى Volatility\n"
        msg += "  • فرص swing الكبيرة هنا\n"
        msg += "  • انتبه للـCPI/FOMC لو فيه\n"
        msg += "  • Liquidations كبيرة محتملة\n"

    # احداث الـ24h القادمة
    today_events = cal_mod.get_today_events()
    if today_events:
        msg += "\n⚠️ *أحداث اليوم تتطلب الانتباه:*\n"
        for ev in today_events[:3]:
            d = ev["date"] if isinstance(ev["date"], datetime) \
                else datetime.fromisoformat(ev["date"])
            msg += f"  • {ev.get('event', '')} ({d.strftime('%H:%M UTC')})\n"

    return msg


# ─────────────────────────────────────────────
# Background job — daily report
# ─────────────────────────────────────────────

async def daily_report_job(ctx):
    """
    يشتغل كل دقيقة، يفحص لو في حد مشترك في تقرير في هذه الدقيقة بالضبط.
    """
    try:
        now = datetime.utcnow()
        subs = db.get_daily_report_subscribers(now.hour, now.minute)
        if not subs:
            return

        # نبني التقرير مرة واحدة
        report = today_view_msg()

        for sub in subs:
            try:
                await ctx.bot.send_message(
                    chat_id=sub["chat_id"],
                    text=report,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
            except Exception:
                pass
    except Exception as e:
        logging.error(f"daily_report_job error: {e}")
