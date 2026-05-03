"""
MAHMOUD_RISK.py
═════════════════════════════════════════════════
أوامر حماية المخاطر + عرض الجورنال:
  • حماية      → عرض الإعدادات الحالية
  • حد_يومي 7  → تحديد الحد اليومي للخسارة (%)
  • حد_صفقات 5 → تحديد أقصى عدد صفقات مفتوحة
  • حد_خسائر 3 → خسائر متتالية قبل التوقف
  • تفعيل_حماية / الغاء_حماية
  • جورنال     → إحصائيات آخر 30 يوم
═════════════════════════════════════════════════
"""

import MAHMOUD_DB as db


# ─────────────────────────────────────────────
# Risk commands
# ─────────────────────────────────────────────

def risk_status_msg(chat_id: int) -> str:
    s = db.get_risk(chat_id)
    enabled = "✅ مفعّلة" if s.get("enabled", 1) else "❌ متوقفة"
    daily = s["daily_pnl_pct"] or 0
    consec = s["consecutive_losses"] or 0
    open_count = len(db.get_open_trades(chat_id))
    can, why = db.check_can_trade(chat_id)

    msg = (
        f"🛡 *حماية المحفظة*  ({enabled})\n\n"
        f"📊 *الحدود:*\n"
        f"  • خسارة يومية: -{s['max_daily_loss_pct']:.0f}%\n"
        f"  • خسارة أسبوعية: -{s['max_weekly_loss_pct']:.0f}%\n"
        f"  • أقصى صفقات مفتوحة: {s['max_open_trades']}\n"
        f"  • خسائر متتالية: {s['max_consecutive_losses']}\n\n"
        f"📈 *الوضع الحالي:*\n"
        f"  • PnL اليوم: *{daily:+.2f}%*\n"
        f"  • خسائر متتالية: {consec}\n"
        f"  • صفقات مفتوحة: {open_count}/{s['max_open_trades']}\n\n"
    )
    if can:
        msg += "✅ *مسموح بالتداول*"
    else:
        msg += f"{why}"

    msg += (
        "\n\n*أوامر التعديل:*\n"
        "`حد_يومي 8` — حد الخسارة اليومية\n"
        "`حد_اسبوعي 15` — حد الخسارة الأسبوعية\n"
        "`حد_صفقات 5` — أقصى صفقات مفتوحة\n"
        "`حد_خسائر 3` — خسائر متتالية\n"
        "`الغاء_حماية` / `تفعيل_حماية`"
    )
    return msg


def update_daily_limit(chat_id: int, value: float) -> str:
    if value < 1 or value > 50:
        return "❌ القيمة لازم بين 1% و 50%"
    db.update_risk(chat_id, max_daily_loss_pct=value)
    return f"✅ تم تحديد الحد اليومي: -{value:.0f}%"


def update_weekly_limit(chat_id: int, value: float) -> str:
    if value < 1 or value > 80:
        return "❌ القيمة لازم بين 1% و 80%"
    db.update_risk(chat_id, max_weekly_loss_pct=value)
    return f"✅ تم تحديد الحد الأسبوعي: -{value:.0f}%"


def update_max_trades(chat_id: int, value: int) -> str:
    if value < 1 or value > 20:
        return "❌ القيمة لازم بين 1 و 20"
    db.update_risk(chat_id, max_open_trades=value)
    return f"✅ أقصى صفقات مفتوحة: {value}"


def update_max_losses(chat_id: int, value: int) -> str:
    if value < 1 or value > 10:
        return "❌ القيمة لازم بين 1 و 10"
    db.update_risk(chat_id, max_consecutive_losses=value)
    return f"✅ أقصى خسائر متتالية: {value}"


def disable_protection(chat_id: int) -> str:
    db.update_risk(chat_id, enabled=0)
    return "❌ تم إيقاف حماية المخاطر — التداول بدون حدود"


def enable_protection(chat_id: int) -> str:
    db.update_risk(chat_id, enabled=1)
    return "✅ تم تفعيل حماية المخاطر"


def reset_daily(chat_id: int) -> str:
    from datetime import datetime
    db.update_risk(chat_id,
                   daily_pnl_pct=0,
                   consecutive_losses=0,
                   last_reset_daily=datetime.utcnow().date().isoformat())
    return "✅ تم إعادة تعيين عداد اليوم"


# ─────────────────────────────────────────────
# Journal display
# ─────────────────────────────────────────────

def journal_msg(chat_id: int, days: int = 30) -> str:
    s = db.journal_stats(chat_id, days)
    if s["total"] == 0:
        return (f"📊 *دفتر التداول (آخر {days} يوم)*\n\n"
                "لا توجد صفقات مغلقة بعد.\n"
                "أضف صفقتك الأولى:\n"
                "`صفقة LONG BTC 43500 42500 44500`")

    win_emoji = "🟢" if s["win_rate"] >= 50 else "🔴"
    pnl_emoji = "🟢" if s["total_pnl"] >= 0 else "🔴"
    pf_emoji = "🟢" if s["profit_factor"] >= 1.5 else ("🟡" if s["profit_factor"] >= 1 else "🔴")
    sharpe_emoji = "🟢" if s["sharpe"] >= 1.5 else ("🟡" if s["sharpe"] >= 0.5 else "🔴")

    msg = (
        f"📊 *دفتر التداول — آخر {days} يوم*\n\n"
        f"🔢 إجمالي الصفقات: *{s['total']}*\n"
        f"{win_emoji} Win Rate: *{s['win_rate']:.1f}%* "
        f"({s['wins']}W / {s['losses']}L)\n\n"
        f"💰 *الأرباح:*\n"
        f"  {pnl_emoji} إجمالي PnL: *{s['total_pnl']:+.2f}%*\n"
        f"  🟢 متوسط الرابحة: +{s['avg_win']:.2f}%\n"
        f"  🔴 متوسط الخاسرة: {s['avg_loss']:.2f}%\n\n"
        f"📈 *المقاييس:*\n"
        f"  {pf_emoji} Profit Factor: *{s['profit_factor']}*\n"
        f"  {sharpe_emoji} Sharpe Ratio: *{s['sharpe']}*\n"
    )

    if s["best"]:
        b = s["best"]
        msg += (f"\n🏆 *أفضل صفقة:*\n"
                f"  {b['symbol']} {b['action']} → {b['pnl_pct']:+.2f}%\n")
    if s["worst"]:
        w = s["worst"]
        msg += (f"💀 *أسوأ صفقة:*\n"
                f"  {w['symbol']} {w['action']} → {w['pnl_pct']:+.2f}%\n")

    # تقييم
    msg += "\n💡 *التقييم:*\n"
    if s["win_rate"] >= 55 and s["profit_factor"] >= 1.5:
        msg += "  ⭐ أداء ممتاز — استمر بنفس النهج"
    elif s["win_rate"] >= 45 and s["profit_factor"] >= 1.2:
        msg += "  👍 أداء جيد — مراجعة الخاسرة لتحسين Win Rate"
    elif s["profit_factor"] >= 1:
        msg += "  ⚠️ أداء حدّي — راجع SL/TP وحجم المراكز"
    else:
        msg += "  🚨 أداء سلبي — توقف وراجع الاستراتيجية"

    return msg
