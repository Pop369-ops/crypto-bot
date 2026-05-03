"""
MAHMOUD_TRACKER.py
═════════════════════════════════════════════════
نظام التتبع اليدوي للصفقات:
  • إضافة صفقة: المستخدم يقول "صفقة LONG BTC 43500 42500 44500 45500 46500"
  • مراقبة تلقائية كل 60 ثانية للصفقات المفتوحة
  • تنبيهات:
      🛑 SL hit          → إقفال
      🎯 TP1/TP2/TP3 hit → جزئي / كامل
      ⚠️ NEAR_SL / NEAR_TP (1% بعيد)
      🔄 إشارة انعكاس قوية ضد الصفقة
      ➕ فرصة إضافة (OB hit, FVG, ترند مستمر)
  • إقفال يدوي: "اقفل BTC" أو "اقفل BTC 43200"
  • تعديل: "تعديل BTC sl 42800"
═════════════════════════════════════════════════
"""

import re
from typing import Dict, Optional, List, Tuple
from datetime import datetime

import MAHMOUD_DB as db


# ─────────────────────────────────────────────
# Parse trade input
# ─────────────────────────────────────────────

def parse_trade_input(text: str) -> Optional[Dict]:
    """
    يفسر أمر إدخال الصفقة. صيغ مدعومة:

      صفقة LONG BTC 43500 42500 44500 45500 46500
      صفقة SHORT ETH 2500 2600 2400 2300 2200
      صفقة BTC LONG 43500 42500 44500 45500
      صفقة btc long 43500 sl 42500 tp 44500 tp 45500
      صفقة LONG BTC entry=43500 sl=42500 tp1=44500 tp2=45500 tp3=46500 lev=5

    العناصر الإجبارية: action (LONG/SHORT) + symbol + entry + sl
    TPs اختيارية. leverage و size_pct اختياريين.
    """
    t = text.strip()
    # نشيل الأمر الأول "صفقة" أو "trade"
    t = re.sub(r"^(صفقة|trade)\s+", "", t, count=1, flags=re.IGNORECASE)

    # الصيغة المختصرة: action symbol entry sl [tp1 tp2 tp3]
    parts = t.split()
    if len(parts) < 4:
        return None

    # تحديد action و symbol (أيهما أولاً)
    action = None
    symbol = None
    rest = []
    for i, p in enumerate(parts[:2]):
        u = p.upper()
        if u in ("LONG", "BUY", "L"):
            action = "LONG"
        elif u in ("SHORT", "SELL", "S"):
            action = "SHORT"
        else:
            symbol = u
    rest = parts[2:]
    # لو لقينا action لكن مش symbol (يعني الـ2 كانوا long short)
    if action and not symbol:
        if rest:
            symbol = rest[0].upper()
            rest = rest[1:]
    if not action or not symbol:
        return None

    # تطبيع الـsymbol
    if not symbol.endswith("USDT") and not symbol.endswith("USDC"):
        symbol = symbol + "USDT"

    # استخرج الأرقام والكلمات المفتاحية
    nums_pos = []  # numbers in order
    kv = {}        # key=value pairs
    for r in rest:
        # السماح بأرقام في الـkey (tp1, tp2, tp3)
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)[=:]([0-9.]+)$", r)
        if m:
            kv[m.group(1).lower()] = float(m.group(2))
            continue
        # كلمات مفتاحية متبوعة برقم في الـ token التالي - skip لأن split فصلهم
        try:
            nums_pos.append(float(r.replace(",", "")))
        except ValueError:
            pass

    # الترتيب الإيجابي: entry, sl, tp1, tp2, tp3
    entry = kv.get("entry") or (nums_pos[0] if len(nums_pos) > 0 else None)
    sl    = kv.get("sl")    or (nums_pos[1] if len(nums_pos) > 1 else None)
    tp1   = kv.get("tp1")   or (nums_pos[2] if len(nums_pos) > 2 else None)
    tp2   = kv.get("tp2")   or (nums_pos[3] if len(nums_pos) > 3 else None)
    tp3   = kv.get("tp3")   or (nums_pos[4] if len(nums_pos) > 4 else None)
    lev   = int(kv.get("lev") or kv.get("leverage") or 1)
    size  = float(kv.get("size") or kv.get("size_pct") or 1.0)

    if entry is None or sl is None:
        return None

    # تحقق منطقي: SL لازم يكون في الجهة الصحيحة
    if action == "LONG" and sl >= entry:
        return {"_error": "SL لازم يكون أقل من Entry للـLONG"}
    if action == "SHORT" and sl <= entry:
        return {"_error": "SL لازم يكون أكبر من Entry للـSHORT"}

    return {
        "symbol": symbol,
        "action": action,
        "entry": entry,
        "sl": sl,
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "leverage": lev,
        "size_pct": size,
    }


# ─────────────────────────────────────────────
# Add / List / Close / Modify
# ─────────────────────────────────────────────

def add_trade_from_text(chat_id: int, text: str) -> Tuple[Optional[int], str]:
    """يرجع (trade_id, message). لو فشل: (None, error)."""
    parsed = parse_trade_input(text)
    if not parsed:
        return None, ("❌ صيغة غير صحيحة\n\n"
                      "*الصيغة:*\n"
                      "`صفقة LONG BTC <Entry> <SL> [TP1] [TP2] [TP3]`\n\n"
                      "*أمثلة:*\n"
                      "`صفقة LONG BTC 43500 42500 44500 45500 46500`\n"
                      "`صفقة SHORT ETH 2500 2600 2400`")
    if "_error" in parsed:
        return None, f"❌ {parsed['_error']}"

    # تحقق من حماية المخاطر
    can, why = db.check_can_trade(chat_id)
    if not can:
        return None, why

    # تأكد ما فيش صفقة مفتوحة على نفس العملة
    existing = db.get_trade_by_symbol(chat_id, parsed["symbol"])
    if existing:
        return None, (f"⚠️ عندك صفقة مفتوحة على {parsed['symbol']} (#{existing['id']})\n"
                      f"اقفلها أولاً: `اقفل {parsed['symbol'][:-4]}`")

    tid = db.insert_trade(
        chat_id=chat_id,
        symbol=parsed["symbol"],
        action=parsed["action"],
        entry=parsed["entry"],
        sl=parsed["sl"],
        tp1=parsed["tp1"], tp2=parsed["tp2"], tp3=parsed["tp3"],
        leverage=parsed["leverage"],
        size_pct=parsed["size_pct"],
    )

    risk_pct = abs(parsed["entry"] - parsed["sl"]) / parsed["entry"] * 100
    rr = ""
    if parsed["tp1"]:
        rew = abs(parsed["tp1"] - parsed["entry"])
        risk = abs(parsed["entry"] - parsed["sl"])
        if risk > 0:
            rr = f"R:R = 1:{rew/risk:.2f}"

    msg = (f"✅ *تم إضافة الصفقة #{tid}*\n\n"
           f"📊 {parsed['symbol']} | {parsed['action']}\n"
           f"💵 Entry: `{parsed['entry']}`\n"
           f"🛑 SL: `{parsed['sl']}` ({risk_pct:.2f}%)\n")
    if parsed["tp1"]:
        msg += f"🎯 TP1: `{parsed['tp1']}`\n"
    if parsed["tp2"]:
        msg += f"🎯 TP2: `{parsed['tp2']}`\n"
    if parsed["tp3"]:
        msg += f"🎯 TP3: `{parsed['tp3']}`\n"
    if parsed["leverage"] > 1:
        msg += f"⚙️ Leverage: x{parsed['leverage']}\n"
    if rr:
        msg += f"📐 {rr}\n"
    msg += "\n🔔 المراقبة كل دقيقة — هتجيك تنبيهات تلقائية"
    return tid, msg


def list_trades_msg(chat_id: int, current_prices: Dict[str, float] = None) -> str:
    trades = db.get_open_trades(chat_id)
    if not trades:
        return ("📋 *لا توجد صفقات مفتوحة*\n\n"
                "أضف صفقة:\n"
                "`صفقة LONG BTC 43500 42500 44500 45500`")

    current_prices = current_prices or {}
    lines = [f"📊 *الصفقات المفتوحة ({len(trades)}):*\n"]
    for t in trades:
        sym = t["symbol"]
        cur = current_prices.get(sym)
        if cur:
            pnl = calc_pnl_pct(t, cur)
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            pnl_str = f"  {pnl_emoji} {pnl:+.2f}%"
        else:
            pnl_str = ""
        action_emoji = "🟢" if t["action"] == "LONG" else "🔴"
        tp_status = ""
        if t["tp1_hit"]: tp_status += " ✅TP1"
        if t["tp2_hit"]: tp_status += " ✅TP2"
        if t["tp3_hit"]: tp_status += " ✅TP3"
        lines.append(
            f"#{t['id']} {action_emoji} *{sym}* {t['action']}{pnl_str}\n"
            f"   Entry `{t['entry']}` | SL `{t['sl']}`"
            f"{tp_status}\n"
        )
    lines.append("\n_اقفل_: `اقفل BTC` | _تعديل_: `تعديل BTC sl 42800`")
    return "\n".join(lines)


def close_trade_msg(chat_id: int, symbol: str, exit_price: Optional[float] = None,
                    reason: str = "MANUAL") -> str:
    sym = symbol.upper()
    if not sym.endswith("USDT") and not sym.endswith("USDC"):
        sym = sym + "USDT"
    trade = db.get_trade_by_symbol(chat_id, sym)
    if not trade:
        return f"⚠️ لا توجد صفقة مفتوحة على {sym}"

    if exit_price is None:
        return f"⚠️ ابعت السعر: `اقفل {sym[:-4]} <السعر>`"

    pnl = calc_pnl_pct(trade, exit_price)
    closed = db.close_trade(trade["id"], exit_price, reason, pnl)
    db.record_trade_close(chat_id, pnl)

    emoji = "🟢" if pnl > 0 else "🔴"
    return (f"{emoji} *تم إقفال الصفقة #{trade['id']}*\n\n"
            f"📊 {sym} | {trade['action']}\n"
            f"Entry: `{trade['entry']}` → Exit: `{exit_price}`\n"
            f"PnL: *{pnl:+.2f}%*\n"
            f"السبب: {reason}")


def modify_trade_msg(chat_id: int, symbol: str, field: str, value: float) -> str:
    sym = symbol.upper()
    if not sym.endswith("USDT") and not sym.endswith("USDC"):
        sym = sym + "USDT"
    trade = db.get_trade_by_symbol(chat_id, sym)
    if not trade:
        return f"⚠️ لا توجد صفقة مفتوحة على {sym}"

    field = field.lower()
    if field not in ("sl", "tp1", "tp2", "tp3"):
        return "⚠️ الحقول المسموحة: sl / tp1 / tp2 / tp3"

    # تحقق منطقي
    if field == "sl":
        if trade["action"] == "LONG" and value >= trade["entry"]:
            return "❌ SL لازم أقل من Entry للـLONG"
        if trade["action"] == "SHORT" and value <= trade["entry"]:
            return "❌ SL لازم أكبر من Entry للـSHORT"

    db.update_trade(trade["id"], **{field: value})
    # امسح تنبيهات NEAR لو الـSL تحرك
    if field == "sl":
        db.reset_repeating_alert(trade["id"], "NEAR_SL")

    return f"✅ تم تحديث {field.upper()} للصفقة #{trade['id']} → `{value}`"


# ─────────────────────────────────────────────
# PnL calc
# ─────────────────────────────────────────────

def calc_pnl_pct(trade: Dict, current_price: float) -> float:
    entry = trade["entry"]
    if not entry or not current_price:
        return 0.0
    if trade["action"] == "LONG":
        return (current_price - entry) / entry * 100
    return (entry - current_price) / entry * 100


# ─────────────────────────────────────────────
# Alert detection (الأهم!)
# ─────────────────────────────────────────────

def check_trade_for_alerts(trade: Dict, current_price: float,
                            signal_decision: Optional[Dict] = None) -> List[Dict]:
    """
    يرجع قائمة التنبيهات اللي يحتاج البوت يبعتها للصفقة دي.
    كل تنبيه dict: {type, title, message, close_trade?, hit_level?}
    """
    alerts = []
    action = trade["action"]
    entry = trade["entry"]
    sl = trade["sl"]
    tp1 = trade.get("tp1")
    tp2 = trade.get("tp2")
    tp3 = trade.get("tp3")

    # ─── 1. SL Hit ───
    sl_hit = (action == "LONG" and current_price <= sl) or \
             (action == "SHORT" and current_price >= sl)
    if sl_hit:
        if not db.alert_was_sent(trade["id"], "SL_HIT"):
            alerts.append({
                "type": "SL_HIT",
                "title": "🛑 SL ضرب — إقفال الصفقة",
                "message": f"السعر `{current_price}` ضرب SL `{sl}`",
                "close_trade": True,
                "exit_reason": "SL",
            })
        return alerts  # لا تكمل الفحوصات الأخرى

    # ─── 2. TPs ───
    tps = [(1, tp1, "tp1_hit"), (2, tp2, "tp2_hit"), (3, tp3, "tp3_hit")]
    for level, tp, flag in tps:
        if not tp or trade.get(flag):
            continue
        tp_hit = (action == "LONG" and current_price >= tp) or \
                 (action == "SHORT" and current_price <= tp)
        if tp_hit:
            close_now = (level == 3) or (level == 2 and not tp3)
            alerts.append({
                "type": f"TP{level}_HIT",
                "title": f"🎯 TP{level} ضرب!",
                "message": (f"السعر وصل `{current_price}` (TP{level} `{tp}`)\n"
                            + ("💰 *إقفال كامل*" if close_now else
                               f"💡 اقفل جزء + حرّك SL لـ"
                               + ("Break-Even" if level == 1 else f"TP{level-1}"))),
                "hit_level": level,
                "close_trade": close_now,
                "exit_reason": f"TP{level}" if close_now else None,
            })

    # ─── 3. NEAR SL/TP (1% تحذير) ───
    near_sl_threshold = 0.01  # 1%
    if action == "LONG":
        dist_sl = (current_price - sl) / current_price
        if 0 < dist_sl < near_sl_threshold:
            if not db.alert_was_sent(trade["id"], "NEAR_SL"):
                alerts.append({
                    "type": "NEAR_SL",
                    "title": "⚠️ السعر اقترب من SL!",
                    "message": (f"السعر `{current_price}` على بعد {dist_sl*100:.2f}% من SL `{sl}`\n"
                                "فكر في إقفال يدوي مبكر إذا الحركة قوية"),
                    "close_trade": False,
                })
    else:
        dist_sl = (sl - current_price) / current_price
        if 0 < dist_sl < near_sl_threshold:
            if not db.alert_was_sent(trade["id"], "NEAR_SL"):
                alerts.append({
                    "type": "NEAR_SL",
                    "title": "⚠️ السعر اقترب من SL!",
                    "message": (f"السعر `{current_price}` على بعد {dist_sl*100:.2f}% من SL `{sl}`\n"
                                "فكر في إقفال يدوي مبكر"),
                    "close_trade": False,
                })

    # NEAR TP1
    if tp1 and not trade.get("tp1_hit"):
        if action == "LONG":
            dist_tp = (tp1 - current_price) / current_price
        else:
            dist_tp = (current_price - tp1) / current_price
        if 0 < dist_tp < near_sl_threshold:
            if not db.alert_was_sent(trade["id"], "NEAR_TP1"):
                alerts.append({
                    "type": "NEAR_TP1",
                    "title": "🎯 السعر يقترب من TP1!",
                    "message": (f"السعر `{current_price}` على بعد {dist_tp*100:.2f}% من TP1 `{tp1}`\n"
                                "استعد لإقفال جزئي"),
                    "close_trade": False,
                })

    # ─── 4. Reversal warning (إشارة قوية ضد الصفقة) ───
    if signal_decision:
        opp = "SHORT" if action == "LONG" else "LONG"
        decided = signal_decision.get("action")
        score_key = "short_score" if action == "LONG" else "long_score"
        score = signal_decision.get(score_key, 0)
        if decided == opp and score >= 12:
            if not db.alert_was_sent(trade["id"], "REVERSAL"):
                pnl = calc_pnl_pct(trade, current_price)
                alerts.append({
                    "type": "REVERSAL",
                    "title": "🔄 إشارة انعكاس قوية!",
                    "message": (f"إشارة *{opp}* قوية ({score}/15) ضد صفقتك\n"
                                f"PnL الحالي: *{pnl:+.2f}%*\n"
                                "💡 فكر في إقفال يدوي أو تحريك SL لـBreak-Even"),
                    "close_trade": False,
                })

    # ─── 5. Add opportunity (لو الصفقة في ربح + إشارة قوية في نفس الاتجاه) ───
    if signal_decision:
        same = action
        decided = signal_decision.get("action")
        score_key = "long_score" if action == "LONG" else "short_score"
        score = signal_decision.get(score_key, 0)
        pnl = calc_pnl_pct(trade, current_price)
        if decided == same and score >= 13 and pnl > 0.5:
            if not db.alert_was_sent(trade["id"], "ADD_OPP"):
                alerts.append({
                    "type": "ADD_OPP",
                    "title": "➕ فرصة إضافة على الصفقة!",
                    "message": (f"إشارة *{same}* قوية جداً ({score}/15) في نفس اتجاهك\n"
                                f"PnL الحالي: *+{pnl:.2f}%*\n"
                                "💡 يمكن زيادة المركز (size صغير + SL أقرب)"),
                    "close_trade": False,
                })

    return alerts


# ─────────────────────────────────────────────
# Background monitor
# ─────────────────────────────────────────────

async def tracked_trades_monitor(ctx, fetch_price_fn, run_analysis_fn=None):
    """
    Job يشتغل كل 60 ثانية.
    fetch_price_fn(symbol) → float (سريع، تيكر فقط)
    run_analysis_fn(symbol) → R dict (للـreversal/add detection — أبطأ)
    """
    open_trades = db.get_open_trades()
    if not open_trades:
        return

    # نجمّع الصفقات حسب symbol عشان ما نجلبش السعر مرتين
    by_symbol = {}
    for t in open_trades:
        by_symbol.setdefault(t["symbol"], []).append(t)

    # نجلب أسعار كل العملات
    price_map = {}
    for sym in by_symbol.keys():
        try:
            p = fetch_price_fn(sym)
            if p:
                price_map[sym] = p
        except Exception:
            pass

    # نفحص كل صفقة
    for sym, trades in by_symbol.items():
        price = price_map.get(sym)
        if not price:
            continue

        # تحليل ثقيل اختياري — مش لكل صفقة في كل مرة (بس لو مر >5 دقائق)
        # هنبسط هنا - run_analysis_fn اختياري
        analysis = None
        if run_analysis_fn:
            try:
                analysis = await run_analysis_fn(sym)
            except Exception:
                pass

        signal_decision = None
        if analysis and "decision" in analysis:
            signal_decision = analysis["decision"]

        for trade in trades:
            alerts = check_trade_for_alerts(trade, price, signal_decision)
            for alert in alerts:
                # ابعت التنبيه
                emoji_action = "🟢" if trade["action"] == "LONG" else "🔴"
                pnl = calc_pnl_pct(trade, price)
                pnl_str = f"{pnl:+.2f}%"
                msg = (f"{alert['title']}\n\n"
                       f"📊 *#{trade['id']} {trade['symbol']} {emoji_action} {trade['action']}*\n"
                       f"💵 Entry: `{trade['entry']}` | السعر: `{price}`\n"
                       f"📈 PnL: *{pnl_str}*\n\n"
                       f"{alert['message']}")
                try:
                    await ctx.bot.send_message(
                        chat_id=trade["chat_id"],
                        text=msg,
                        parse_mode="Markdown",
                    )
                    db.mark_alert_sent(trade["id"], alert["type"])
                except Exception as e:
                    pass

                # إقفال تلقائي للـSL/TP3 hit
                if alert.get("close_trade"):
                    try:
                        db.close_trade(
                            trade["id"], price,
                            alert.get("exit_reason", alert["type"]),
                            calc_pnl_pct(trade, price),
                        )
                        db.record_trade_close(trade["chat_id"],
                                              calc_pnl_pct(trade, price))
                    except Exception:
                        pass

                # تحديث TP flags بدون إقفال (TP1/TP2 partial)
                hit_level = alert.get("hit_level")
                if hit_level and not alert.get("close_trade"):
                    db.update_trade(trade["id"], **{f"tp{hit_level}_hit": 1})
