"""
MAHMOUD_NEWS.py
═════════════════════════════════════════════════
نظام الأخبار:
  • 9 RSS feeds من مواقع كريبتو رائدة
  • Dedup عبر hash الـURL
  • Impact scoring (0-10) — كلمات مفتاحية + AI optional
  • Coin tagging تلقائي (BTC, ETH, SOL...)
  • Sentiment detection (bullish/bearish/neutral)
  • تنبيهات فورية للأخبار العاجلة
═════════════════════════════════════════════════
"""

import os
import re
import hashlib
import logging
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False
    feedparser = None

import MAHMOUD_DB as db


# ─────────────────────────────────────────────
# Massive.com News API (supplementary)
# ─────────────────────────────────────────────
MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY", "")
MASSIVE_BASE = "https://api.massive.com"

# Crypto tickers اللي ندورهم في Massive News (Massive يستخدم X:BTCUSD format)
MASSIVE_CRYPTO_TICKERS = [
    "X:BTCUSD", "X:ETHUSD", "X:SOLUSD", "X:XRPUSD",
    "X:ADAUSD", "X:DOGEUSD", "X:AVAXUSD", "X:DOTUSD",
    "X:LINKUSD", "X:MATICUSD",
]


# ─────────────────────────────────────────────
# RSS Feeds — 9 مصادر
# ─────────────────────────────────────────────

RSS_FEEDS = [
    ("CoinDesk",       "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph",  "https://cointelegraph.com/rss"),
    ("The Block",      "https://www.theblock.co/rss.xml"),
    ("Decrypt",        "https://decrypt.co/feed"),
    ("Bitcoin Magazine","https://bitcoinmagazine.com/.rss/full/"),
    ("CryptoSlate",    "https://cryptoslate.com/feed/"),
    ("CryptoBriefing", "https://cryptobriefing.com/feed/"),
    ("U.Today",        "https://u.today/rss"),
    ("Bitcoinist",     "https://bitcoinist.com/feed/"),
]

# عملات مهمة لاكتشاف tagging
COIN_KEYWORDS = {
    "BTC":   ["bitcoin", "btc", "satoshi"],
    "ETH":   ["ethereum", "eth", "vitalik", "ether ", "ether,", "ether."],
    "SOL":   ["solana", "sol "],
    "XRP":   ["xrp", "ripple"],
    "BNB":   ["binance coin", "bnb"],
    "DOGE":  ["dogecoin", "doge "],
    "ADA":   ["cardano", "ada "],
    "AVAX":  ["avalanche", "avax"],
    "LINK":  ["chainlink", "link "],
    "MATIC": ["polygon", "matic"],
    "DOT":   ["polkadot", "dot "],
    "SHIB":  ["shiba", "shib"],
    "TRX":   ["tron", "trx"],
    "LTC":   ["litecoin", "ltc"],
    "NEAR":  ["near protocol", " near "],
    "TIA":   ["celestia", "tia"],
    "SUI":   ["sui network", " sui "],
    "ARB":   ["arbitrum", "arb "],
    "OP":    ["optimism", " op "],
    "INJ":   ["injective"],
    "ONDO":  ["ondo finance", "ondo"],
    "PYTH":  ["pyth network", "pyth "],
    "RENDER":["render", "rndr"],
    "HYPE":  ["hyperliquid", "hype "],
    "TON":   ["toncoin", "ton "],
}

# ─────────────────────────────────────────────
# Impact scoring (كلمات مفتاحية وزنية)
# ─────────────────────────────────────────────

# كلمات عالية الأثر = +X نقطة
HIGH_IMPACT_KEYWORDS = {
    # Regulatory / Macro
    "sec": 8, "etf": 9, "fed ": 9, "fomc": 9, "cpi ": 8, "interest rate": 8,
    "approves": 8, "rejects": 8, "lawsuit": 7, "regulation": 7, "ban": 8,
    "approved": 8, "rejected": 8, "ruling": 7, "verdict": 7, "settlement": 7,
    # Hacks / Exploits
    "hack": 9, "exploit": 9, "stolen": 8, "drained": 8, "rug pull": 8,
    "vulnerability": 7, "phishing": 6, "exploit": 9,
    # Market events
    "crash": 9, "plunge": 8, "surge": 7, "rally": 6, "all-time high": 8,
    "ath ": 8, "liquidation": 7, "flash crash": 9,
    # Institutional
    "blackrock": 8, "fidelity": 7, "grayscale": 7, "blackrock": 8,
    "michael saylor": 6, "microstrategy": 7,
    # Token events
    "halving": 9, "fork": 7, "merge": 7, "upgrade": 6, "mainnet": 6,
    "airdrop": 6, "listing": 6, "delisting": 7, "unlock": 7,
    # Whale activity
    "whale": 6, "moves": 5, "transfers": 5, "$100m": 7, "$1b": 8,
    # Bankruptcies / Failures
    "bankruptcy": 9, "insolvent": 9, "collapsed": 9, "ftx": 7,
    # Central bank
    "powell": 7, "yellen": 7, "lagarde": 6,
    # Big economy
    "recession": 7, "inflation": 6, "gdp ": 5,
}

BULLISH_WORDS = ["surge", "rally", "soars", "gains", "approval", "approved",
                 "adoption", "buy", "bullish", "moon", "all-time high", "ath",
                 "breakthrough", "support", "boost", "upgrade"]
BEARISH_WORDS = ["crash", "plunge", "drops", "fall", "rejected", "ban",
                 "lawsuit", "hack", "exploit", "stolen", "bearish",
                 "collapse", "decline", "losses", "warning", "panic"]


def score_impact(title: str, summary: str = "") -> int:
    """يرجع 0-10"""
    text = (title + " " + summary).lower()
    score = 1  # base
    for word, weight in HIGH_IMPACT_KEYWORDS.items():
        if word in text:
            score = max(score, weight)
    return min(score, 10)


def detect_sentiment(title: str, summary: str = "") -> str:
    text = (title + " " + summary).lower()
    bull = sum(1 for w in BULLISH_WORDS if w in text)
    bear = sum(1 for w in BEARISH_WORDS if w in text)
    if bull > bear + 1:
        return "bullish"
    if bear > bull + 1:
        return "bearish"
    return "neutral"


def detect_coins(title: str, summary: str = "") -> List[str]:
    text = (title + " " + summary).lower()
    found = []
    for coin, keywords in COIN_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                found.append(coin)
                break
    return list(dict.fromkeys(found))  # dedup preserve order


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────
# Fetch
# ─────────────────────────────────────────────

def fetch_feed(name: str, url: str, max_items: int = 25) -> List[Dict]:
    """يجلب RSS feed ويرجع list من المقالات"""
    if not HAS_FEEDPARSER:
        return []
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:max_items]:
            link = entry.get("link", "")
            if not link:
                continue
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "") or entry.get("description", "")
            # تنظيف HTML
            summary = re.sub(r"<[^>]+>", "", summary)[:500]

            published = entry.get("published", "") or entry.get("updated", "") \
                        or datetime.utcnow().isoformat()

            items.append({
                "url": link,
                "title": title,
                "summary": summary,
                "source": name,
                "published": published,
            })
        return items
    except Exception as e:
        logging.warning(f"RSS fetch failed for {name}: {e}")
        return []


def fetch_all_feeds() -> List[Dict]:
    """يجلب من كل الـ9 مصادر RSS + Massive News لو متاح"""
    all_items = []
    for name, url in RSS_FEEDS:
        items = fetch_feed(name, url)
        all_items.extend(items)
    # إضافة Massive News (لو الـkey متاح)
    massive_items = fetch_massive_news()
    all_items.extend(massive_items)
    return all_items


def fetch_massive_news(limit: int = 50) -> List[Dict]:
    """
    يجلب الأخبار من Massive.com News API.
    مزايا فوق RSS:
      • Sentiment analysis مدمج
      • Ticker tagging تلقائي (BTC, ETH...)
      • Publisher metadata
    """
    if not MASSIVE_API_KEY:
        return []

    items = []
    headers = {"Authorization": f"Bearer {MASSIVE_API_KEY}"}

    # نفحص الأخبار للتيكرز الكريبتو الرئيسية
    for ticker in MASSIVE_CRYPTO_TICKERS[:5]:  # نقتصر على أهم 5 لتوفير quota
        try:
            r = requests.get(
                f"{MASSIVE_BASE}/v2/reference/news",
                headers=headers,
                params={
                    "ticker": ticker,
                    "limit": 10,
                    "order": "desc",
                    "sort": "published_utc",
                },
                timeout=15,
            )
            if r.status_code != 200:
                continue
            data = r.json()
            for art in data.get("results", []):
                pub_str = art.get("published_utc", "")
                try:
                    pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                    pub_dt = pub_dt.replace(tzinfo=None)
                except (ValueError, AttributeError):
                    pub_dt = datetime.utcnow()

                # ما نأخذش أخبار قديمة جداً (>3 أيام)
                if (datetime.utcnow() - pub_dt).days > 3:
                    continue

                publisher = art.get("publisher", {})
                items.append({
                    "title": art.get("title", ""),
                    "url": art.get("article_url", ""),
                    "source": f"Massive/{publisher.get('name', 'Unknown')}",
                    "published": pub_dt,
                    "summary": art.get("description", ""),
                    # Massive ينطينا الـsentiment والـtickers مباشرة!
                    "_massive_sentiment": art.get("insights", [{}])[0].get("sentiment")
                                          if art.get("insights") else None,
                    "_massive_tickers": art.get("tickers", []),
                })
        except Exception as e:
            logging.warning(f"Massive news fetch error for {ticker}: {e}")

    return items


def process_and_store_news(do_ai: bool = False) -> Tuple[int, List[Dict]]:
    """
    يجلب الأخبار ويخزنها فقط (سريع، لا AI).
    AI يتعامل في job منفصل (background) لتجنب الحجب.
    do_ai=True فقط للاستخدام الصريح (e.g. حلل_الكل).
    """
    items = fetch_all_feeds()
    new_items = []
    breaking = []

    for it in items:
        h = url_hash(it["url"])
        if db.news_seen(h):
            continue
        impact = score_impact(it["title"], it["summary"])

        if it.get("_massive_sentiment"):
            sentiment = it["_massive_sentiment"]
            sentiment_map = {"positive": "bullish", "negative": "bearish",
                             "neutral": "neutral"}
            sentiment = sentiment_map.get(sentiment, sentiment)
        else:
            sentiment = detect_sentiment(it["title"], it["summary"])

        if it.get("_massive_tickers"):
            coins = []
            for t in it["_massive_tickers"]:
                if t.startswith("X:") and "USD" in t:
                    sym = t.replace("X:", "").replace("USD", "")
                    if sym and sym not in coins:
                        coins.append(sym)
            if not coins:
                coins = detect_coins(it["title"], it["summary"])
        else:
            coins = detect_coins(it["title"], it["summary"])

        coins_str = ",".join(coins) if coins else None

        nid = db.insert_news(h, it["url"], it["title"], it["source"],
                             it["published"], impact, coins_str, sentiment,
                             summary=(it.get("summary") or "")[:1000])
        if nid <= 0:
            continue

        it["impact"] = impact
        it["sentiment"] = sentiment
        it["coins"] = coins
        it["id"] = nid
        new_items.append(it)
        if impact >= 7:
            breaking.append(it)

    return len(new_items), breaking


async def ai_analyze_pending_news(max_items: int = 5,
                                  min_impact: int = 5) -> int:
    """
    Background AI analysis — يحلل الأخبار اللي مفيش لها AI بعد.
    Async-safe: يستدعي الـAI في thread executor و يضع sleep بين كل تحليل.
    يرجع عدد الأخبار اللي تم تحليلها.
    """
    try:
        import MAHMOUD_AI as ai_module
        if not ai_module.has_any_ai():
            return 0
    except Exception:
        return 0

    pending = db.get_news_without_ai(hours=12, limit=max_items)
    if not pending:
        return 0

    analyzed = 0
    loop = asyncio.get_event_loop()

    for n in pending:
        if (n.get("impact") or 0) < min_impact:
            continue
        try:
            coins_list = (n.get("coins") or "").split(",") if n.get("coins") else []
            coins_list = [c.strip() for c in coins_list if c.strip()]
            # Run in thread executor (async-safe)
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda nn=n, cc=coins_list: ai_module.analyze_news_item(
                        nn["title"], nn.get("summary", ""),
                        nn.get("source", ""), cc, prefer="claude"
                    )
                ),
                timeout=30
            )
            if result.get("ok"):
                a = result["analysis"]
                db.update_news_ai(
                    news_id=n["id"],
                    ai_summary=a.get("summary_ar", "")[:500],
                    ai_action=a.get("action_ar", "")[:500],
                    ai_levels=a.get("key_levels_ar", "")[:300],
                    ai_horizon=a.get("horizon", "hours"),
                    ai_sentiment=a.get("direction"),
                    ai_impact=a.get("impact_score"),
                )
                analyzed += 1
            await asyncio.sleep(1)  # سلس على الـAPI
        except (asyncio.TimeoutError, Exception) as e:
            logging.warning(f"AI analysis timeout/err for news {n.get('id')}: {e}")
            continue

    return analyzed


# ─────────────────────────────────────────────
# Display formatting
# ─────────────────────────────────────────────

def _esc_md(s: str) -> str:
    """يهرب رموز Markdown الخاصة لتجنب parse errors"""
    if not s:
        return ""
    s = str(s)
    # نهرب: _ * [ ] ` (الأكثر شيوعاً في العناوين)
    for ch in ("_", "*", "[", "]", "`"):
        s = s.replace(ch, "\\" + ch)
    return s


def fmt_news_item(item: Dict, idx: Optional[int] = None) -> str:
    """تنسيق خبر واحد للعرض — مع تحليل AI inline لو متاح"""
    impact = item.get("impact", 0)
    sentiment = item.get("sentiment", "neutral")
    coins = item.get("coins") or ""
    if isinstance(coins, str):
        coins = coins.split(",") if coins else []

    s_emoji = {"bullish": "🟢", "bearish": "🔴",
               "neutral": "⚪"}.get(sentiment, "⚪")
    impact_emoji = "🔥" if impact >= 9 else ("⚡" if impact >= 7 else "📰")

    prefix = f"{idx}. " if idx else ""
    title = _esc_md(item.get("title", "").strip())
    source = _esc_md(item.get("source", ""))
    url = item.get("url", "")
    coins_tag = "  ".join([f"#{_esc_md(c)}" for c in coins[:5]]) if coins else ""

    msg = f"{prefix}{impact_emoji} {s_emoji} *{title}*\n"
    if coins_tag:
        msg += f"   {coins_tag}\n"
    msg += f"   _{source} • تأثير {impact}/10_\n"

    # ✨ NEW: AI analysis inline (Wall Street Pro style)
    ai_summary = item.get("ai_summary")
    ai_action = item.get("ai_action")
    if ai_summary:
        # Esc the AI text too
        safe_summary = _esc_md(ai_summary)
        msg += f"   🤖 *تحليل:* {safe_summary}\n"
    if ai_action:
        safe_action = _esc_md(ai_action)
        # ناخذ أول جملة بس عشان ما يطول
        first_line = safe_action.split("\n")[0][:200]
        msg += f"   💡 *اعمل:* {first_line}\n"

    if url:
        safe_url = url.replace(")", "%29")
        msg += f"   [اقرأ المزيد]({safe_url})\n"
    return msg


def get_news_msg(coin: Optional[str] = None, hours: int = 24,
                 min_impact: int = 0, limit: int = 10) -> str:
    items = db.get_recent_news(hours=hours, min_impact=min_impact,
                                coin=coin, limit=limit)
    if not items:
        scope = f"على {coin}" if coin else "في الفترة دي"
        return f"📰 لا توجد أخبار {scope} بهذا التأثير\n\nجرّب: `أخبار` (بدون فلتر)"

    title = "🔥 *عاجل*" if min_impact >= 7 else "📰 *أحدث الأخبار*"
    if coin:
        title += f" — {coin.upper()}"
    msg = f"{title}  _(آخر {hours}h)_\n\n"
    for i, it in enumerate(items, 1):
        msg += fmt_news_item(it, i) + "\n"
    return msg


def get_breaking_msg(items: List[Dict]) -> str:
    """رسالة تنبيه عاجل لخبر واحد أو أكثر"""
    if not items:
        return ""
    if len(items) == 1:
        it = items[0]
        return f"🚨 *خبر عاجل!* (تأثير {it['impact']}/10)\n\n" + fmt_news_item(it)
    msg = f"🚨 *{len(items)} أخبار عاجلة!*\n\n"
    for i, it in enumerate(items, 1):
        msg += fmt_news_item(it, i) + "\n"
    return msg


# ─────────────────────────────────────────────
# Background job
# ─────────────────────────────────────────────

async def news_check_job(ctx):
    """
    يشتغل كل 15 دقيقة. سريع — فقط fetch + store.
    AI تحليل في job منفصل (ai_analysis_job) لتجنب blocking.
    """
    try:
        # ① جلب وتخزين سريع (بدون AI)
        loop = asyncio.get_event_loop()
        count, breaking = await loop.run_in_executor(
            None, process_and_store_news
        )
        if count > 0:
            logging.info(f"News: +{count} new items, {len(breaking)} breaking")

        # ② إرسال الـbreaking بدون AI أولاً (سريع)
        for item in breaking:
            min_impact = item["impact"]
            subscribers = db.get_breaking_subscribers(min_impact)
            for sub in subscribers:
                coins_filter = sub.get("coins_filter") or ""
                if coins_filter:
                    user_coins = [c.strip().upper() for c in coins_filter.split(",")]
                    item_coins = item.get("coins", [])
                    if not any(c in user_coins for c in item_coins):
                        continue
                if item["impact"] < sub.get("min_impact", 7):
                    continue
                try:
                    await ctx.bot.send_message(
                        chat_id=sub["chat_id"],
                        text=get_breaking_msg([item]),
                        parse_mode="Markdown",
                        disable_web_page_preview=False,
                    )
                except Exception:
                    pass

        # ③ AI analysis للـpending (background — لا يحجب)
        # نحلل بحد أقصى 3 أخبار/دورة لتجنب الإرهاق
        try:
            analyzed = await ai_analyze_pending_news(max_items=3, min_impact=6)
            if analyzed > 0:
                logging.info(f"AI analyzed {analyzed} pending news items")
        except Exception as e:
            logging.warning(f"AI background analysis failed: {e}")
    except Exception as e:
        logging.error(f"news_check_job error: {e}")


async def ai_analysis_job(ctx):
    """
    Job منفصل كل 5 دقائق — يحلل أي خبر بدون AI.
    """
    try:
        analyzed = await ai_analyze_pending_news(max_items=3, min_impact=5)
        if analyzed > 0:
            logging.info(f"[ai_job] analyzed {analyzed} news items")
    except Exception as e:
        logging.warning(f"ai_analysis_job error: {e}")
