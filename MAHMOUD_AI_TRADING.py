"""
MAHMOUD_AI_TRADING.py — v5.0 AI Verdict Module
═════════════════════════════════════════════════
AI ترجيحي للإشارات التداولية فقط.

الـAI يستلم:
1. الإشارة (LONG/SHORT) + قوتها (12-15/15)
2. التحليل التقني (RSI, MACD, EMA stack, ICT, MTF)
3. المستويات الذكية (SL/TP × 3 + Liquidity Map)
4. السعر الحالي + السياق

AI يرد بـJSON:
{
  "verdict": "ENTER_NOW | WAIT | SKIP",
  "confidence": 1-10,
  "reasoning_ar": "السبب باختصار",
  "warnings_ar": "تحذيرات/ملاحظات",
  "entry_strategy_ar": "كيف يدخل (Market / Limit عند مستوى معين)",
  "preferred_sl": "Conservative | Balanced | Aggressive",
  "preferred_tp": "TP1 | TP2 | TP3 (أيهم الأفضل للهدف)"
}

يدعم 3 AIs:
• Claude (افتراضي — أدق)
• Gemini 2.5 Flash (مجاني)
• GPT-4o-mini (احتياطي)
═════════════════════════════════════════════════
"""

import os
import json
import logging
import requests
from typing import Dict, Optional


# ─────────────────────────────────────────────
# API Keys
# ─────────────────────────────────────────────
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

HTTP_TIMEOUT = 30


def has_any_ai() -> bool:
    return bool(CLAUDE_API_KEY or GEMINI_API_KEY or OPENAI_API_KEY)


def ai_status() -> Dict[str, bool]:
    return {
        "claude": bool(CLAUDE_API_KEY),
        "gemini": bool(GEMINI_API_KEY),
        "openai": bool(OPENAI_API_KEY),
    }


def best_available_ai() -> Optional[str]:
    """يرجع أفضل AI متاح حالياً (Claude > Gemini > OpenAI)"""
    if CLAUDE_API_KEY:
        return "claude"
    if GEMINI_API_KEY:
        return "gemini"
    if OPENAI_API_KEY:
        return "openai"
    return None


# ─────────────────────────────────────────────
# AI Prompt للإشارات التداولية
# ─────────────────────────────────────────────

TRADING_VERDICT_PROMPT = """أنت محلل تداول كريبتو محترف من Wall Street.
دورك: تستلم إشارة من بوت تقني وتعطي رأيك الترجيحي.

ترد بـJSON فقط (لا نص قبل أو بعد):
{
  "verdict": "ENTER_NOW" أو "WAIT" أو "SKIP",
  "confidence": 1-10 (مدى ثقتك في الترجيح),
  "reasoning_ar": "سبب الترجيح في 2-3 جمل قصيرة",
  "warnings_ar": "تحذيرات أو ملاحظات (إن وجدت)",
  "entry_strategy_ar": "كيف يدخل: Market الآن / Limit عند سعر معين / انتظار retest",
  "preferred_sl": "Conservative" أو "Balanced" أو "Aggressive",
  "preferred_tp": "TP1" أو "TP2" أو "TP3"
}

معايير القرار:
✅ ENTER_NOW: قوة الإشارة 13+/15، MTF محاذي، السيولة قريبة، R:R ممتاز
🟡 WAIT: قوة الإشارة 12/15، نحتاج retest أو confirmation
🔴 SKIP: تعارض إشارات، السيولة ضعيفة، أو R:R غير مجدي

كن مباشراً وعملياً. تذكر: المتداول يحتاج قرار، ليس تحليل طويل."""


# ─────────────────────────────────────────────
# AI Calls
# ─────────────────────────────────────────────

def call_claude(prompt: str, max_tokens: int = 600) -> Dict:
    if not CLAUDE_API_KEY:
        return {"ok": False, "error": "no_key"}
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": max_tokens,
                "system": TRADING_VERDICT_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=HTTP_TIMEOUT,
        )
        if r.status_code != 200:
            return {"ok": False, "error": f"http_{r.status_code}",
                    "detail": r.text[:200]}
        data = r.json()
        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")
        return {"ok": True, "text": text, "model": CLAUDE_MODEL}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def call_gemini(prompt: str, max_tokens: int = 600) -> Dict:
    if not GEMINI_API_KEY:
        return {"ok": False, "error": "no_key"}
    try:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")

        gen_config = {
            "maxOutputTokens": max_tokens,
            "temperature": 0.5,  # أقل عشوائية للقرارات
            "responseMimeType": "application/json",
        }
        # Disable thinking لـGemini 2.5+ (أسرع وأرخص)
        if "2.5" in GEMINI_MODEL or "3" in GEMINI_MODEL:
            gen_config["thinkingConfig"] = {"thinkingBudget": 0}

        r = requests.post(
            url,
            headers={"content-type": "application/json"},
            json={
                "systemInstruction": {"parts": [{"text": TRADING_VERDICT_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": gen_config,
            },
            timeout=HTTP_TIMEOUT,
        )
        if r.status_code != 200:
            return {"ok": False, "error": f"http_{r.status_code}",
                    "detail": r.text[:300]}
        data = r.json()
        text = ""
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                text += part.get("text", "")
        return {"ok": True, "text": text, "model": GEMINI_MODEL}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def call_openai(prompt: str, max_tokens: int = 600) -> Dict:
    if not OPENAI_API_KEY:
        return {"ok": False, "error": "no_key"}
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "max_tokens": max_tokens,
                "temperature": 0.5,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": TRADING_VERDICT_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=HTTP_TIMEOUT,
        )
        if r.status_code != 200:
            return {"ok": False, "error": f"http_{r.status_code}",
                    "detail": r.text[:200]}
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        return {"ok": True, "text": text, "model": OPENAI_MODEL}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


# ─────────────────────────────────────────────
# JSON Extractor
# ─────────────────────────────────────────────

def extract_json(text: str) -> Optional[Dict]:
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    import re
    # markdown code block
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    # first { to last }
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except json.JSONDecodeError:
            cleaned = re.sub(r",(\s*[}\]])", r"\1", text[first:last + 1])
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass
    return None


# ─────────────────────────────────────────────
# Build Trading Prompt
# ─────────────────────────────────────────────

def build_trading_prompt(symbol: str, action: str, score_data: Dict,
                         smart_levels: Dict, R: Optional[Dict] = None) -> str:
    """يبني prompt مفصّل للـAI من كل البيانات"""
    long_s = score_data.get("long_score", 0)
    short_s = score_data.get("short_score", 0)
    max_s = score_data.get("max_score", 15)
    components = score_data.get("components", [])
    mtf = score_data.get("mtf", {})

    sl = smart_levels.get("sl", {})
    tp = smart_levels.get("tp", {})
    quality = smart_levels.get("quality", "?")
    weighted_rr = smart_levels.get("weighted_rr", 0)
    danger = smart_levels.get("danger_zones", [])
    reject = smart_levels.get("reject_zones", [])
    price = smart_levels.get("current_price", 0)

    # نبني prompt واضح
    prompt = f"""إشارة من البوت التقني:

🎯 *{symbol}* — {action}
السعر الحالي: ${price:,.4f}
قوة الإشارة: {long_s if action == 'LONG' else short_s}/{max_s}

📊 المؤشرات (الـ{len(components)} الأعلى):
"""
    for comp in components[:6]:
        # comp = (name, status, value, weight)
        try:
            prompt += f"  • {comp[0]}: {comp[1]} ({comp[2]}) [+{comp[3]}]\n"
        except (IndexError, TypeError):
            continue

    prompt += f"\n📈 MTF Alignment:\n"
    prompt += f"  • 1H bias: {mtf.get('bias_1h', '?')}\n"
    prompt += f"  • 4H bias: {mtf.get('bias_4h', '?')}\n"
    prompt += f"  • 1D bias: {mtf.get('bias_1d', '?')}\n"
    prompt += f"  • Aligned: {mtf.get('aligned_long' if action == 'LONG' else 'aligned_short', False)}\n"

    prompt += f"\n🛡 SL Options:\n"
    prompt += f"  • Conservative ${sl.get('conservative', {}).get('level', 0):,.4f} (risk {sl.get('conservative', {}).get('risk_pct', 0):.1f}%) — {sl.get('conservative', {}).get('reason', '?')}\n"
    prompt += f"  • Balanced ${sl.get('balanced', {}).get('level', 0):,.4f} (risk {sl.get('balanced', {}).get('risk_pct', 0):.1f}%) — {sl.get('balanced', {}).get('reason', '?')}\n"
    prompt += f"  • Aggressive ${sl.get('aggressive', {}).get('level', 0):,.4f} (risk {sl.get('aggressive', {}).get('risk_pct', 0):.1f}%) — {sl.get('aggressive', {}).get('reason', '?')}\n"

    prompt += f"\n🎯 TP Targets:\n"
    prompt += f"  • TP1 ${tp.get('tp1', {}).get('level', 0):,.4f} ({tp.get('tp1', {}).get('probability', 0)}% prob, R:R 1:{tp.get('tp1', {}).get('rr', 0)}) — {tp.get('tp1', {}).get('reason', '?')}\n"
    prompt += f"  • TP2 ${tp.get('tp2', {}).get('level', 0):,.4f} ({tp.get('tp2', {}).get('probability', 0)}% prob, R:R 1:{tp.get('tp2', {}).get('rr', 0)}) — {tp.get('tp2', {}).get('reason', '?')}\n"
    prompt += f"  • TP3 ${tp.get('tp3', {}).get('level', 0):,.4f} ({tp.get('tp3', {}).get('probability', 0)}% prob, R:R 1:{tp.get('tp3', {}).get('rr', 0)}) — {tp.get('tp3', {}).get('reason', '?')}\n"

    prompt += f"\n📊 Risk Metrics:\n"
    prompt += f"  • Weighted R:R = 1:{weighted_rr}\n"
    prompt += f"  • Quality: {quality}\n"

    if danger:
        prompt += f"\n⚠️ Danger Zones (قرب SL):\n"
        for z in danger[:3]:
            prompt += f"  • ${z['level']:,.4f} ({z['type']})\n"

    if reject:
        prompt += f"\n⚠️ Reject Zones (في طريق TP):\n"
        for z in reject[:3]:
            prompt += f"  • ${z['level']:,.4f} ({z['type']})\n"

    if R:
        # نضيف معلومات إضافية لو موجودة
        funding = R.get("funding_rate") or R.get("funding")
        if funding is not None:
            prompt += f"\n💰 Funding Rate: {funding:.4f}%\n"
        oi_change = R.get("oi_change_24h")
        if oi_change is not None:
            prompt += f"📊 OI Change 24h: {oi_change:+.2f}%\n"

    prompt += "\n\nأعطني ترجيحك الآن (JSON فقط)."
    return prompt


# ─────────────────────────────────────────────
# Main API: get_ai_verdict
# ─────────────────────────────────────────────

def get_ai_verdict(symbol: str, action: str, score_data: Dict,
                   smart_levels: Dict, R: Optional[Dict] = None,
                   prefer: Optional[str] = None) -> Dict:
    """
    الواجهة الرئيسية — يرجع ترجيح AI للإشارة.
    prefer: 'claude' / 'gemini' / 'openai' (أو None للأفضل المتاح)

    Returns:
    {
        "ok": bool,
        "verdict": "ENTER_NOW" | "WAIT" | "SKIP",
        "confidence": 1-10,
        "reasoning_ar": "...",
        "warnings_ar": "...",
        "entry_strategy_ar": "...",
        "preferred_sl": "Conservative" | "Balanced" | "Aggressive",
        "preferred_tp": "TP1" | "TP2" | "TP3",
        "ai_used": "claude" | "gemini" | "openai"
    }
    """
    if not has_any_ai():
        return {"ok": False, "error": "no_ai_keys",
                "msg": "أضف على الأقل CLAUDE_API_KEY أو GEMINI_API_KEY"}

    if action not in ("LONG", "SHORT"):
        return {"ok": False, "error": "invalid_action"}

    # نختار AI
    if prefer is None:
        prefer = best_available_ai()

    # نبني الـprompt
    prompt = build_trading_prompt(symbol, action, score_data, smart_levels, R)

    # نستدعي AI مع fallback
    tried = []
    result = None
    for ai_name in [prefer, "claude", "gemini", "openai"]:
        if ai_name in tried:
            continue
        tried.append(ai_name)

        if ai_name == "claude":
            r = call_claude(prompt)
        elif ai_name == "gemini":
            r = call_gemini(prompt)
        elif ai_name == "openai":
            r = call_openai(prompt)
        else:
            continue

        if r.get("ok"):
            parsed = extract_json(r["text"])
            if parsed:
                result = parsed
                result["ai_used"] = ai_name
                result["ok"] = True
                break
            else:
                logging.warning(f"AI {ai_name} returned non-JSON: {r['text'][:100]}")
        else:
            logging.warning(f"AI {ai_name} failed: {r.get('error')}")

    if not result:
        return {"ok": False, "error": "all_ais_failed",
                "tried": tried}

    # Validation
    verdict = result.get("verdict", "WAIT")
    if verdict not in ("ENTER_NOW", "WAIT", "SKIP"):
        verdict = "WAIT"
    result["verdict"] = verdict

    confidence = result.get("confidence", 5)
    try:
        confidence = max(1, min(10, int(confidence)))
    except (ValueError, TypeError):
        confidence = 5
    result["confidence"] = confidence

    return result


# ─────────────────────────────────────────────
# Display formatter
# ─────────────────────────────────────────────

def fmt_ai_verdict(verdict_data: Dict) -> str:
    """تنسيق الـverdict للعرض في تيليجرام"""
    if not verdict_data.get("ok"):
        err = verdict_data.get("error", "unknown")
        if err == "no_ai_keys":
            return ("\n🤖 *AI:* غير متاح\n"
                    "_أضف GEMINI_API_KEY في Variables (مجاني)_")
        return f"\n🤖 *AI:* فشل ({err})"

    verdict = verdict_data["verdict"]
    confidence = verdict_data["confidence"]
    reasoning = verdict_data.get("reasoning_ar", "")
    warnings = verdict_data.get("warnings_ar", "")
    entry = verdict_data.get("entry_strategy_ar", "")
    pref_sl = verdict_data.get("preferred_sl", "Balanced")
    pref_tp = verdict_data.get("preferred_tp", "TP2")
    ai_used = verdict_data.get("ai_used", "?")

    # Verdict emoji + label
    if verdict == "ENTER_NOW":
        v_emoji = "✅"
        v_label = "ادخل الآن"
        v_color = "🟢"
    elif verdict == "WAIT":
        v_emoji = "⏳"
        v_label = "انتظر"
        v_color = "🟡"
    else:  # SKIP
        v_emoji = "❌"
        v_label = "تجنّب"
        v_color = "🔴"

    # Confidence bar
    filled = "█" * confidence
    empty = "░" * (10 - confidence)

    # Markdown escape
    def esc(s: str) -> str:
        if not s:
            return ""
        s = str(s)
        for ch in ("_", "*", "[", "]", "`"):
            s = s.replace(ch, "\\" + ch)
        return s

    msg = f"\n🤖 *رأي AI ({ai_used.upper()}):*\n"
    msg += f"━━━━━━━━━━━━━━━━━\n"
    msg += f"{v_color} الترجيح: {v_emoji} *{v_label}*\n"
    msg += f"💪 الثقة: `{filled}{empty}` {confidence}/10\n\n"

    if reasoning:
        msg += f"📝 *السبب:*\n{esc(reasoning)}\n\n"

    if entry:
        msg += f"🎯 *استراتيجية الدخول:*\n{esc(entry)}\n\n"

    msg += f"⚙️ *AI يفضّل:*\n"
    msg += f"  • SL: *{pref_sl}*\n"
    msg += f"  • TP: *{pref_tp}*\n"

    if warnings:
        msg += f"\n⚠️ *تحذيرات:*\n{esc(warnings)}\n"

    return msg
