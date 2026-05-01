"""
MAHMOUD_AI.py
═════════════════════════════════════════════════
3 AI Brains + Consensus Engine:
  • Claude (Anthropic)
  • Gemini 2.0 Flash (Google)
  • GPT-4o (OpenAI)
  • Multi-AI Consensus — يجمع آراء الـ3
═════════════════════════════════════════════════
"""

import os
import json
import logging
import asyncio
import requests
from typing import Dict, Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed

import MAHMOUD_DB as db


# ─────────────────────────────────────────────
# API Keys
# ─────────────────────────────────────────────
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Models
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# Timeouts
HTTP_TIMEOUT = 45


def has_any_ai() -> bool:
    return bool(CLAUDE_API_KEY or GEMINI_API_KEY or OPENAI_API_KEY)


def ai_status() -> Dict[str, bool]:
    return {
        "claude": bool(CLAUDE_API_KEY),
        "gemini": bool(GEMINI_API_KEY),
        "openai": bool(OPENAI_API_KEY),
    }


# ─────────────────────────────────────────────
# System prompts (crypto-focused, Wall Street style)
# ─────────────────────────────────────────────

CRYPTO_SYSTEM_PROMPT = """أنت محلل كريبتو محترف بمستوى Wall Street + Bridgewater.
تحلل العملات الرقمية بمنهجية مؤسسية صارمة:

1. **Macro Context**: تأخذ في الاعتبار Fed policy, inflation, DXY, yields, ETF flows
2. **On-chain**: تحلل whale activity, exchange flows, network metrics
3. **Technical**: ICT/Smart Money + Order Blocks + FVG + RSI/MACD/EMA
4. **Sentiment**: Fear & Greed, Funding Rates, L/S Ratio, social sentiment
5. **Risk Management**: Position sizing + ATR-based SL + 3 TPs

قواعد:
- أعطِ توصية واضحة: LONG / SHORT / HOLD مع مستوى ثقة (0-100)
- اذكر السبب بإيجاز (3-5 نقاط)
- اقترح Entry / SL / TP1 / TP2 / TP3
- حدد Risk:Reward ratio
- نبه على Catalysts قادمة قد تأثر
- إذا كانت الإشارة ضعيفة — قل HOLD وانتظر
- العربية + الإنجليزية في نفس الرد (المصطلحات الفنية بالإنجليزية)

JSON output schema:
{
  "action": "LONG" | "SHORT" | "HOLD",
  "confidence": 0-100,
  "entry": float,
  "sl": float,
  "tp1": float,
  "tp2": float,
  "tp3": float,
  "rr": "1:X.X",
  "reasoning": ["نقطة1", "نقطة2", "نقطة3"],
  "catalysts": ["حدث1", "حدث2"],
  "risk_level": "low" | "medium" | "high"
}
"""

QUESTION_SYSTEM_PROMPT = """أنت محلل كريبتو محترف. تجيب على أسئلة المستخدم
بدقة وموضوعية. تستخدم أحدث المعلومات المتاحة. تجيب بالعربية مع المصطلحات
الفنية بالإنجليزية. الردود مختصرة (3-5 فقرات قصيرة) ومنظمة."""


# ─────────────────────────────────────────────
# Claude API call
# ─────────────────────────────────────────────

def call_claude(prompt: str, system: str = CRYPTO_SYSTEM_PROMPT,
                max_tokens: int = 1500) -> Dict:
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
                "system": system,
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
        return {"ok": True, "text": text, "model": "claude",
                "tokens_used": data.get("usage", {}).get("input_tokens", 0)
                              + data.get("usage", {}).get("output_tokens", 0)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


# ─────────────────────────────────────────────
# Gemini API call
# ─────────────────────────────────────────────

def call_gemini(prompt: str, system: str = CRYPTO_SYSTEM_PROMPT,
                max_tokens: int = 1500) -> Dict:
    if not GEMINI_API_KEY:
        return {"ok": False, "error": "no_key"}
    try:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
        r = requests.post(
            url,
            headers={"content-type": "application/json"},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": 0.7,
                },
            },
            timeout=HTTP_TIMEOUT,
        )
        if r.status_code != 200:
            return {"ok": False, "error": f"http_{r.status_code}",
                    "detail": r.text[:200]}
        data = r.json()
        text = ""
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                text += part.get("text", "")
        return {"ok": True, "text": text, "model": "gemini"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


# ─────────────────────────────────────────────
# OpenAI API call
# ─────────────────────────────────────────────

def call_openai(prompt: str, system: str = CRYPTO_SYSTEM_PROMPT,
                max_tokens: int = 1500) -> Dict:
    if not OPENAI_API_KEY:
        return {"ok": False, "error": "no_key"}
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "content-type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "max_tokens": max_tokens,
                "temperature": 0.7,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=HTTP_TIMEOUT,
        )
        if r.status_code != 200:
            return {"ok": False, "error": f"http_{r.status_code}",
                    "detail": r.text[:200]}
        data = r.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"ok": True, "text": text, "model": "openai",
                "tokens_used": data.get("usage", {}).get("total_tokens", 0)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


# ─────────────────────────────────────────────
# Parallel call — كل الـ3 معاً
# ─────────────────────────────────────────────

def call_all_ais(prompt: str, system: str = CRYPTO_SYSTEM_PROMPT,
                 max_tokens: int = 1500) -> Dict[str, Dict]:
    """يستدعي الـ3 AIs بالتوازي ويرجع النتائج"""
    results = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {}
        if CLAUDE_API_KEY:
            futs[ex.submit(call_claude, prompt, system, max_tokens)] = "claude"
        if GEMINI_API_KEY:
            futs[ex.submit(call_gemini, prompt, system, max_tokens)] = "gemini"
        if OPENAI_API_KEY:
            futs[ex.submit(call_openai, prompt, system, max_tokens)] = "openai"

        for fut in as_completed(futs):
            name = futs[fut]
            try:
                results[name] = fut.result()
            except Exception as e:
                results[name] = {"ok": False, "error": str(e)[:120]}

    return results


# ─────────────────────────────────────────────
# Parse JSON response
# ─────────────────────────────────────────────

def extract_json(text: str) -> Optional[Dict]:
    """يحاول يستخرج JSON من رد الـAI"""
    if not text:
        return None
    # محاولة 1: رد JSON مباشر
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # محاولة 2: داخل ```json ... ```
    import re
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # محاولة 3: أول { ... }
    m = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


# ─────────────────────────────────────────────
# Consensus Engine
# ─────────────────────────────────────────────

def consensus(results: Dict[str, Dict]) -> Dict:
    """
    يجمع آراء الـ3 AIs ويرجع توصية موحدة.
    - تصويت على action (LONG/SHORT/HOLD)
    - متوسط confidence
    - متوسط levels
    """
    parsed = {}
    for name, res in results.items():
        if not res.get("ok"):
            continue
        j = extract_json(res.get("text", ""))
        if j and "action" in j:
            parsed[name] = j

    if not parsed:
        return {
            "action": "HOLD", "confidence": 0,
            "agreement": 0, "n_ais": 0,
            "reasoning": ["لم يستجب أي AI بصيغة صحيحة"],
            "raw": results,
        }

    # تصويت
    votes = {"LONG": 0, "SHORT": 0, "HOLD": 0}
    confidences = []
    entries = []
    sls = []
    tp1s = []
    tp2s = []
    tp3s = []
    all_reasoning = []

    for name, j in parsed.items():
        action = (j.get("action") or "HOLD").upper()
        if action not in votes:
            action = "HOLD"
        votes[action] += 1
        if j.get("confidence") is not None:
            confidences.append(float(j["confidence"]))
        for fld, target in [("entry", entries), ("sl", sls),
                             ("tp1", tp1s), ("tp2", tp2s), ("tp3", tp3s)]:
            v = j.get(fld)
            if v is not None and isinstance(v, (int, float)):
                target.append(float(v))
        for r in j.get("reasoning", []):
            all_reasoning.append(f"[{name}] {r}")

    # winner
    winner = max(votes.items(), key=lambda x: x[1])
    action = winner[0]
    agreement_count = winner[1]
    n = len(parsed)
    agreement_pct = (agreement_count / n) * 100

    # متوسط confidence لمن صوتوا للـwinner
    win_confidences = []
    for name, j in parsed.items():
        if (j.get("action") or "HOLD").upper() == action:
            if j.get("confidence") is not None:
                win_confidences.append(float(j["confidence"]))
    avg_conf = (sum(win_confidences) / len(win_confidences)) \
                if win_confidences else 0

    # ضرب confidence بـagreement (3 AIs متفقين = ثقة كاملة)
    final_confidence = avg_conf * (agreement_pct / 100)

    out = {
        "action": action,
        "confidence": round(final_confidence, 1),
        "agreement_pct": round(agreement_pct, 1),
        "votes": votes,
        "n_ais": n,
        "reasoning": all_reasoning[:8],
        "ais_used": list(parsed.keys()),
        "raw": parsed,
    }
    if entries: out["entry"] = round(sum(entries) / len(entries), 4)
    if sls:     out["sl"]    = round(sum(sls) / len(sls), 4)
    if tp1s:    out["tp1"]   = round(sum(tp1s) / len(tp1s), 4)
    if tp2s:    out["tp2"]   = round(sum(tp2s) / len(tp2s), 4)
    if tp3s:    out["tp3"]   = round(sum(tp3s) / len(tp3s), 4)

    return out


# ─────────────────────────────────────────────
# Build crypto analysis prompt
# ─────────────────────────────────────────────

def build_crypto_prompt(symbol: str, R: Dict,
                        news_items: Optional[List[Dict]] = None,
                        catalysts: Optional[List[Dict]] = None) -> str:
    """يبني prompt متكامل للـAI من بيانات التحليل + الأخبار + Catalysts"""
    price = R.get("price", 0)
    long_s = R.get("long_score", 0)
    short_s = R.get("short_score", 0)
    max_s = R.get("max_score", 15)

    p = f"حلل {symbol} (Crypto Futures) واعطِ توصية تداول.\n\n"
    p += f"━━ البيانات الفنية ━━\n"
    p += f"السعر: ${price}\n"
    p += f"Score (Internal Engine): LONG {long_s}/{max_s} | SHORT {short_s}/{max_s}\n"

    # Funding & OI
    if R.get("rate") is not None:
        p += f"Funding Rate: {R['rate']:+.4f}%\n"
    if R.get("oi_chg") is not None:
        p += f"Open Interest: {R['oi_chg']:+.2f}%\n"
    if R.get("ls_long") and R.get("ls_short"):
        p += f"Long/Short: {R['ls_long']:.0f}% / {R['ls_short']:.0f}%\n"
    if R.get("liq_l") or R.get("liq_s"):
        p += f"Liquidations: Long ${R.get('liq_l',0):,.0f} | Short ${R.get('liq_s',0):,.0f}\n"

    # MTF
    mtf = R.get("mtf_data", {})
    if mtf:
        p += (f"MTF Bias: 1h={mtf.get('1h','?')} | "
              f"4h={mtf.get('4h','?')} | 1d={mtf.get('1d','?')}\n")

    if R.get("btc_bias_4h"):
        p += f"BTC Trend (4h): {R['btc_bias_4h']}\n"

    # ICT
    ict = R.get("ict", {})
    if ict:
        p += f"ICT: {ict.get('bull',0)} bullish vs {ict.get('bear',0)} bearish signals\n"

    # ATR/Smart levels
    smart = R.get("smart_levels", {})
    if smart:
        p += f"ATR: {smart.get('atr_pct', 0):.2f}%\n"
        bal = smart.get("levels", {}).get("balanced", {})
        if bal:
            p += (f"Suggested Levels: SL=${bal.get('sl', 0):.2f} | "
                  f"TP1=${bal.get('tp1', 0):.2f} | "
                  f"TP2=${bal.get('tp2', 0):.2f}\n")

    # News
    if news_items:
        p += f"\n━━ آخر الأخبار ━━\n"
        for n in news_items[:5]:
            sentiment = n.get("sentiment", "neutral")
            p += f"• [{sentiment}] {n.get('title','')[:120]}\n"

    # Catalysts
    if catalysts:
        p += f"\n━━ Catalysts قادمة ━━\n"
        for c in catalysts[:3]:
            p += f"• {c.get('title','')} ({c.get('when','')})\n"

    p += ("\n━━━━━━━━━━━━━━━━\n"
          "أعطِ توصية احترافية بصيغة JSON كما في النظام المحدد. "
          "ركز على risk-adjusted return.\n")
    return p


# ─────────────────────────────────────────────
# High-level: get consensus recommendation
# ─────────────────────────────────────────────

def get_consensus_recommendation(symbol: str, R: Dict,
                                  news_items: Optional[List[Dict]] = None,
                                  catalysts: Optional[List[Dict]] = None) -> Dict:
    """High-level: يجمع البيانات، يستدعي الـ3 AIs، يرجع consensus"""
    if not has_any_ai():
        return {
            "ok": False,
            "error": "no_ai_keys",
            "msg": "لم يتم إعداد أي AI API key",
        }

    prompt = build_crypto_prompt(symbol, R, news_items, catalysts)
    results = call_all_ais(prompt)
    cons = consensus(results)
    cons["ok"] = cons["n_ais"] > 0
    return cons


# ─────────────────────────────────────────────
# Free-form question
# ─────────────────────────────────────────────

def ask_question(question: str, prefer: str = "consensus") -> Dict:
    """
    سؤال حر — يرجع رد نصي.
    prefer: 'claude' | 'gemini' | 'openai' | 'consensus'
    """
    if prefer == "consensus":
        results = call_all_ais(question, system=QUESTION_SYSTEM_PROMPT,
                               max_tokens=1000)
        # نختار الرد الأطول/الأكمل
        valid = [(name, r) for name, r in results.items()
                 if r.get("ok") and r.get("text")]
        if not valid:
            return {"ok": False, "error": "all_ais_failed"}
        # نرتب: longest first
        valid.sort(key=lambda x: len(x[1].get("text", "")), reverse=True)
        primary = valid[0]
        return {
            "ok": True,
            "primary": primary[0],
            "text": primary[1]["text"],
            "all_responses": {n: r.get("text", "") for n, r in valid},
        }
    elif prefer == "claude":
        r = call_claude(question, system=QUESTION_SYSTEM_PROMPT)
    elif prefer == "gemini":
        r = call_gemini(question, system=QUESTION_SYSTEM_PROMPT)
    elif prefer == "openai":
        r = call_openai(question, system=QUESTION_SYSTEM_PROMPT)
    else:
        return {"ok": False, "error": "unknown_ai"}

    if r.get("ok"):
        return {"ok": True, "primary": prefer, "text": r["text"]}
    return {"ok": False, "error": r.get("error", "unknown")}


# ─────────────────────────────────────────────
# Format consensus for Telegram
# ─────────────────────────────────────────────

def fmt_consensus(symbol: str, cons: Dict) -> str:
    if not cons.get("ok"):
        return f"❌ AI Analysis فشل: {cons.get('error', 'unknown')}"

    action = cons["action"]
    conf = cons["confidence"]
    agree = cons["agreement_pct"]
    n = cons["n_ais"]
    votes = cons.get("votes", {})

    action_emoji = {"LONG": "🟢", "SHORT": "🔴", "HOLD": "🟡"}.get(action, "⚪")
    conf_emoji = "🔥" if conf >= 75 else ("⚡" if conf >= 50 else "💡")

    msg = f"🧠 *Multi-AI Consensus — {symbol.upper()}*\n"
    msg += f"━━━━━━━━━━━━━━━━\n\n"
    msg += f"{action_emoji} *التوصية: {action}*\n"
    msg += f"{conf_emoji} الثقة: *{conf:.0f}%*\n"
    msg += f"🤝 الاتفاق: *{agree:.0f}%* ({n} AI)\n"
    msg += f"🗳 الأصوات: LONG {votes.get('LONG',0)} | "
    msg += f"SHORT {votes.get('SHORT',0)} | HOLD {votes.get('HOLD',0)}\n\n"

    # Levels
    if cons.get("entry"):
        msg += "🎯 *المستويات (متوسط الـAIs):*\n"
        msg += f"  📥 Entry: `${cons.get('entry'):.4f}`\n"
        if cons.get("sl"):
            msg += f"  🛑 SL: `${cons['sl']:.4f}`\n"
        if cons.get("tp1"):
            msg += f"  🎯 TP1: `${cons['tp1']:.4f}`\n"
        if cons.get("tp2"):
            msg += f"  🎯 TP2: `${cons['tp2']:.4f}`\n"
        if cons.get("tp3"):
            msg += f"  🎯 TP3: `${cons['tp3']:.4f}`\n"
        msg += "\n"

    # Reasoning
    reasoning = cons.get("reasoning", [])
    if reasoning:
        msg += "💡 *الأسباب:*\n"
        for r in reasoning[:6]:
            msg += f"  • {r}\n"
        msg += "\n"

    msg += f"_AIs المستخدمة: {', '.join(cons.get('ais_used', []))}_\n"
    msg += "⚠️ _تحليل تعليمي — مش نصيحة مالية_"
    return msg


# ═════════════════════════════════════════════
# News Analysis (v4.3)
# ═════════════════════════════════════════════

NEWS_ANALYSIS_PROMPT = """أنت محلل كريبتو محترف. تحلل خبر واحد وترد بـJSON فقط:
{
  "summary_ar": "ملخص الخبر بالعربية في جملتين",
  "impact_score": 0-10,
  "affected_coins": ["BTC", "ETH"],
  "direction": "bullish|bearish|neutral",
  "horizon": "minutes|hours|days|weeks",
  "action_ar": "ماذا يفعل المتداول الآن (3-4 أسطر تعليمات عملية)",
  "key_levels_ar": "مستويات مهمة لـBTC/المتأثر",
  "what_to_watch": "ماذا تراقب الـ24 ساعة القادمة"
}
كن دقيقاً وعملياً. لا تنصح بالشراء/البيع المباشر، بل اشرح السيناريوهات."""


DAILY_BRIEF_PROMPT = """أنت محلل كريبتو محترف. حلل أهم أخبار اليوم وارد بـJSON:
{
  "market_mood": "risk-on|risk-off|mixed",
  "top_themes": ["موضوع 1", "موضوع 2", "موضوع 3"],
  "btc_outlook_ar": "نظرة BTC للـ24 ساعة القادمة (3 أسطر)",
  "alts_outlook_ar": "نظرة الألتس",
  "key_catalysts_ar": ["catalyst 1", "catalyst 2"],
  "action_plan_ar": "خطة عمل عملية للمتداول (5 نقاط مرقمة)",
  "risks_ar": "المخاطر اللي تنتبه لها"
}"""


def analyze_news_item(title: str, summary: str = "",
                      source: str = "", coins: List[str] = None,
                      prefer: str = "claude") -> Dict:
    """
    يحلل خبر واحد ويرجع تحليل + توصية عملية.
    prefer: 'claude' أسرع، 'consensus' أدق.
    """
    coins_str = ", ".join(coins) if coins else "غير محدد"
    prompt = (
        f"خبر:\nالعنوان: {title}\n"
        f"الملخص: {summary[:500]}\n"
        f"المصدر: {source}\n"
        f"العملات المتأثرة: {coins_str}\n\n"
        f"حلل الخبر."
    )

    if prefer == "consensus":
        results = call_all_ais(prompt, system=NEWS_ANALYSIS_PROMPT, max_tokens=800)
        valid = [(n, r) for n, r in results.items() if r.get("ok") and r.get("text")]
        if not valid:
            return {"ok": False, "error": "all_failed"}
        # نأخذ من Claude أفضل، أو الأطول
        primary_name = "claude" if any(n == "claude" for n, _ in valid) else valid[0][0]
        primary = next(r for n, r in valid if n == primary_name)
        text = primary["text"]
    else:
        if prefer == "claude":
            r = call_claude(prompt, system=NEWS_ANALYSIS_PROMPT, max_tokens=800)
        elif prefer == "gemini":
            r = call_gemini(prompt, system=NEWS_ANALYSIS_PROMPT, max_tokens=800)
        else:
            r = call_openai(prompt, system=NEWS_ANALYSIS_PROMPT, max_tokens=800)
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error", "unknown")}
        text = r["text"]

    parsed = extract_json(text) or {}
    if not parsed:
        return {"ok": False, "error": "json_parse_failed", "raw": text}

    return {"ok": True, "analysis": parsed, "ai_used": prefer}


def fmt_news_analysis(title: str, analysis: Dict, url: str = "") -> str:
    """تنسيق تحليل الخبر للعرض في تيليجرام"""
    a = analysis
    direction = a.get("direction", "neutral")
    dir_emoji = {"bullish": "🟢", "bearish": "🔴",
                 "neutral": "⚪"}.get(direction, "⚪")
    dir_ar = {"bullish": "صاعد", "bearish": "هابط",
              "neutral": "محايد"}.get(direction, "محايد")

    horizon = a.get("horizon", "hours")
    horizon_ar = {"minutes": "دقائق", "hours": "ساعات",
                  "days": "أيام", "weeks": "أسابيع"}.get(horizon, "ساعات")

    impact = a.get("impact_score", 5)
    impact_emoji = "🔥" if impact >= 8 else ("⚡" if impact >= 6 else "📊")

    coins = a.get("affected_coins", [])
    coins_str = " ".join([f"#{c}" for c in coins[:5]]) if coins else ""

    # Markdown escape للعنوان
    safe_title = title
    for ch in ("_", "*", "[", "]", "`"):
        safe_title = safe_title.replace(ch, "\\" + ch)

    msg = f"🤖 *تحليل AI للخبر*\n\n"
    msg += f"📰 *{safe_title}*\n\n"
    msg += f"📝 *الملخص:* {a.get('summary_ar', '—')}\n\n"
    msg += f"{impact_emoji} *التأثير:* {impact}/10  {dir_emoji} *الاتجاه:* {dir_ar}\n"
    msg += f"⏱ *المدى:* {horizon_ar}\n"
    if coins_str:
        msg += f"💰 *العملات:* {coins_str}\n"
    msg += "\n"

    msg += f"━━━━━━━━━━━━━━━━\n"
    msg += f"💡 *ماذا تفعل الآن:*\n"
    msg += f"{a.get('action_ar', '—')}\n\n"

    if a.get("key_levels_ar"):
        msg += f"📊 *مستويات مهمة:*\n{a['key_levels_ar']}\n\n"

    if a.get("what_to_watch"):
        msg += f"👁 *راقب:*\n{a['what_to_watch']}\n\n"

    if url:
        safe_url = url.replace(")", "%29")
        msg += f"[المصدر الكامل]({safe_url})"

    return msg


def daily_brief(news_items: List[Dict], catalysts: List[Dict] = None,
                prefer: str = "claude") -> Dict:
    """
    يولد تقرير يومي شامل من قائمة أخبار + catalysts.
    """
    if not news_items:
        return {"ok": False, "error": "no_news"}

    # نبني prompt مع أهم 15 خبر
    news_text = "أهم أخبار اليوم:\n\n"
    for i, n in enumerate(news_items[:15], 1):
        news_text += f"{i}. [{n.get('impact', '?')}/10] {n.get('title', '')}\n"
        if n.get('coins'):
            news_text += f"   عملات: {n['coins']}\n"

    if catalysts:
        news_text += "\n\nأحداث ماكرو قادمة:\n"
        for c in catalysts[:5]:
            news_text += f"• {c.get('event', c.get('title', ''))}\n"

    if prefer == "consensus":
        results = call_all_ais(news_text, system=DAILY_BRIEF_PROMPT, max_tokens=1200)
        valid = [(n, r) for n, r in results.items() if r.get("ok") and r.get("text")]
        if not valid:
            return {"ok": False, "error": "all_failed"}
        primary_name = "claude" if any(n == "claude" for n, _ in valid) else valid[0][0]
        text = next(r["text"] for n, r in valid if n == primary_name)
    else:
        if prefer == "claude":
            r = call_claude(news_text, system=DAILY_BRIEF_PROMPT, max_tokens=1200)
        elif prefer == "gemini":
            r = call_gemini(news_text, system=DAILY_BRIEF_PROMPT, max_tokens=1200)
        else:
            r = call_openai(news_text, system=DAILY_BRIEF_PROMPT, max_tokens=1200)
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error", "unknown")}
        text = r["text"]

    parsed = extract_json(text) or {}
    if not parsed:
        return {"ok": False, "error": "json_parse_failed", "raw": text}

    return {"ok": True, "brief": parsed, "news_count": len(news_items)}


def fmt_daily_brief(brief_data: Dict) -> str:
    """تنسيق التقرير اليومي للعرض"""
    if not brief_data.get("ok"):
        return f"❌ فشل توليد التقرير: {brief_data.get('error', 'unknown')}"

    b = brief_data["brief"]
    n_count = brief_data.get("news_count", 0)

    mood = b.get("market_mood", "mixed")
    mood_emoji = {"risk-on": "🟢", "risk-off": "🔴",
                  "mixed": "🟡"}.get(mood, "🟡")
    mood_ar = {"risk-on": "Risk-On (شهية مخاطرة)",
               "risk-off": "Risk-Off (هروب للأمان)",
               "mixed": "مختلط"}.get(mood, "مختلط")

    msg = f"📊 *التقرير اليومي AI*\n"
    msg += f"_(تحليل {n_count} خبر)_\n\n"
    msg += f"{mood_emoji} *مزاج السوق:* {mood_ar}\n\n"

    themes = b.get("top_themes", [])
    if themes:
        msg += f"🎯 *أهم المواضيع:*\n"
        for t in themes[:3]:
            msg += f"  • {t}\n"
        msg += "\n"

    msg += f"━━━━━━━━━━━━━━━━\n"
    msg += f"₿ *BTC outlook:*\n{b.get('btc_outlook_ar', '—')}\n\n"
    msg += f"🪙 *Alts outlook:*\n{b.get('alts_outlook_ar', '—')}\n\n"

    cats = b.get("key_catalysts_ar", [])
    if cats:
        msg += f"🔥 *Catalysts اليوم:*\n"
        for ca in cats[:3]:
            msg += f"  • {ca}\n"
        msg += "\n"

    msg += f"━━━━━━━━━━━━━━━━\n"
    msg += f"📋 *خطة العمل:*\n{b.get('action_plan_ar', '—')}\n\n"

    if b.get("risks_ar"):
        msg += f"⚠️ *المخاطر:*\n{b['risks_ar']}"

    return msg
