"""
MAHMOUD_CALENDAR.py
═════════════════════════════════════════════════
التقويم الاقتصادي للكريبتو:
  • Trading Economics API (للأحداث الماكرو CPI/FOMC/NFP)
  • Fallback: Public APIs مجانية (investpy / forex factory rss)
  • Crypto events: token unlocks (CoinMarketCal-style)
  • Filter: high-impact فقط للكريبتو
═════════════════════════════════════════════════
"""

import os
import json
import logging
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

import MAHMOUD_DB as db


TE_API_KEY = os.environ.get("TRADING_ECONOMICS_KEY", "")
COINMARKETCAL_KEY = os.environ.get("COINMARKETCAL_KEY", "")

# الأحداث المهمة للكريبتو (تؤثر على السوق)
HIGH_IMPACT_EVENTS = [
    "Inflation Rate", "CPI", "Core CPI",
    "Fed Interest Rate", "FOMC", "Fed Chair",
    "Non Farm Payrolls", "Unemployment Rate",
    "GDP Growth Rate", "Retail Sales",
    "PCE Price Index", "PPI",
    "ECB Interest Rate", "ECB Press Conference",
    "Fed Minutes", "FOMC Minutes",
    "Powell Speech", "Yellen Speech",
]

# ─────────────────────────────────────────────
# Trading Economics API
# ─────────────────────────────────────────────

def fetch_te_calendar(days_ahead: int = 7) -> List[Dict]:
    """
    يجلب التقويم من Trading Economics.
    لو ما فيش API key، يستخدم guest:guest (حد محدود).
    """
    auth = TE_API_KEY if TE_API_KEY else "guest:guest"
    today = datetime.utcnow().date()
    end = today + timedelta(days=days_ahead)

    url = f"https://api.tradingeconomics.com/calendar"
    params = {
        "c": auth,
        "f": "json",
        "d1": today.isoformat(),
        "d2": end.isoformat(),
        "importance": "3",  # high only
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            logging.warning(f"TE calendar HTTP {r.status_code}")
            return []
        data = r.json()
        if not isinstance(data, list):
            return []

        events = []
        for ev in data:
            country = ev.get("Country", "")
            event = ev.get("Event", "")
            date_str = ev.get("Date", "")
            try:
                ev_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            events.append({
                "country": country,
                "event": event,
                "date": ev_dt,
                "actual": ev.get("Actual"),
                "forecast": ev.get("Forecast"),
                "previous": ev.get("Previous"),
                "importance": ev.get("Importance", 1),
                "currency": ev.get("Currency", ""),
                "category": ev.get("Category", ""),
            })
        return events
    except Exception as e:
        logging.error(f"TE calendar error: {e}")
        return []


def fetch_te_calendar_cached(days_ahead: int = 7) -> List[Dict]:
    """نفس فكرة fetch_te_calendar مع كاش لمدة ساعة"""
    cache_key = f"te_cal_{days_ahead}"
    cached = db.cache_get(cache_key)
    if cached:
        try:
            data = json.loads(cached)
            # نحول التواريخ النصية لـ datetime
            for ev in data:
                if isinstance(ev.get("date"), str):
                    ev["date"] = datetime.fromisoformat(ev["date"])
            return data
        except Exception:
            pass

    events = fetch_te_calendar(days_ahead)
    if events:
        # نحفظ التواريخ كـ ISO strings
        cacheable = [{**e, "date": e["date"].isoformat()
                      if isinstance(e.get("date"), datetime) else e.get("date")}
                     for e in events]
        db.cache_set(cache_key, json.dumps(cacheable), ttl_seconds=3600)
    return events


# ─────────────────────────────────────────────
# CoinMarketCal — Crypto-specific events (token unlocks, listings, AMAs)
# ─────────────────────────────────────────────

def fetch_crypto_events(coins: Optional[List[str]] = None,
                        days_ahead: int = 14) -> List[Dict]:
    """
    يجلب أحداث الكريبتو من CoinMarketCal (token unlocks, listings).
    يحتاج API key مجاني.
    """
    if not COINMARKETCAL_KEY:
        return []

    headers = {
        "x-api-key": COINMARKETCAL_KEY,
        "Accept": "application/json",
        "Accept-Encoding": "deflate, gzip",
    }
    params = {
        "max": 50,
        "page": 1,
        "showOnly": "hot_events",
        "translations": "en",
    }
    if coins:
        params["coins"] = ",".join(coins).lower()

    try:
        r = requests.get("https://developers.coinmarketcal.com/v1/events",
                         headers=headers, params=params, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json().get("body", [])
        events = []
        cutoff = datetime.utcnow() + timedelta(days=days_ahead)
        for ev in data:
            try:
                ev_dt = datetime.fromisoformat(
                    ev.get("date_event", "").replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if ev_dt > cutoff:
                continue
            events.append({
                "title": ev.get("title", {}).get("en", ""),
                "date": ev_dt,
                "coins": [c.get("symbol") for c in ev.get("coins", [])],
                "category": [c.get("name") for c in ev.get("categories", [])],
                "source": ev.get("source", ""),
                "votes": ev.get("vote_count", 0),
                "type": "crypto",
            })
        return events
    except Exception as e:
        logging.error(f"CoinMarketCal error: {e}")
        return []


# ─────────────────────────────────────────────
# Combined view + filtering
# ─────────────────────────────────────────────

def get_today_events() -> List[Dict]:
    """أحداث اليوم فقط"""
    macro = fetch_te_calendar_cached(days_ahead=1)
    today = datetime.utcnow().date()
    today_events = []
    for ev in macro:
        d = ev["date"] if isinstance(ev["date"], datetime) \
            else datetime.fromisoformat(ev["date"])
        if d.date() == today:
            today_events.append(ev)
    return sorted(today_events, key=lambda e: e["date"])


def get_week_events() -> List[Dict]:
    """أحداث الأسبوع"""
    return fetch_te_calendar_cached(days_ahead=7)


def is_high_impact_for_crypto(event_name: str) -> bool:
    """يحدد إذا الحدث يأثر على الكريبتو"""
    name_lower = event_name.lower()
    return any(k.lower() in name_lower for k in HIGH_IMPACT_EVENTS)


# ─────────────────────────────────────────────
# Display
# ─────────────────────────────────────────────

def fmt_event(ev: Dict) -> str:
    d = ev["date"] if isinstance(ev["date"], datetime) \
        else datetime.fromisoformat(ev["date"])
    time_str = d.strftime("%H:%M UTC")
    country_emoji = {
        "United States": "🇺🇸", "Euro Area": "🇪🇺", "China": "🇨🇳",
        "Japan": "🇯🇵", "United Kingdom": "🇬🇧", "Germany": "🇩🇪",
    }
    country = ev.get("country", "")
    flag = country_emoji.get(country, "🌍")
    impact = ev.get("importance", 1)
    impact_emoji = "🔥" if impact >= 3 else ("⚡" if impact >= 2 else "📅")

    forecast = ev.get("forecast")
    previous = ev.get("previous")
    actual = ev.get("actual")

    msg = f"{impact_emoji} {flag} *{ev.get('event', '')}*\n"
    msg += f"   ⏰ {time_str}"
    if actual is not None and actual != "":
        msg += f" | الفعلي: `{actual}`"
    elif forecast is not None and forecast != "":
        msg += f" | التوقع: `{forecast}`"
    if previous is not None and previous != "":
        msg += f" | السابق: `{previous}`"
    msg += "\n"
    return msg


def calendar_today_msg() -> str:
    """تقويم اليوم"""
    events = get_today_events()
    if not events:
        return ("📅 *تقويم اليوم*\n\n"
                "✅ لا توجد أحداث ماكرو عالية التأثير اليوم\n"
                "_السوق هادئ نسبياً_")
    msg = f"📅 *تقويم اليوم* — {datetime.utcnow().strftime('%Y-%m-%d')}\n\n"
    for ev in events:
        msg += fmt_event(ev) + "\n"
    msg += "_⚠️ الأحداث دي ممكن تسبب تقلبات قوية في الكريبتو_"
    return msg


def calendar_week_msg() -> str:
    """تقويم الأسبوع — مفصول حسب اليوم"""
    events = get_week_events()
    if not events:
        return "📅 لا توجد أحداث في الأسبوع القادم\n(أو فيه مشكلة في API التقويم)"

    by_day = {}
    for ev in events:
        d = ev["date"] if isinstance(ev["date"], datetime) \
            else datetime.fromisoformat(ev["date"])
        key = d.date().isoformat()
        by_day.setdefault(key, []).append(ev)

    msg = "📅 *تقويم الأسبوع* (Macro Events)\n\n"
    for day in sorted(by_day.keys()):
        d = datetime.fromisoformat(day).date()
        day_label = d.strftime("%A %d-%m")
        msg += f"━━━ *{day_label}* ━━━\n"
        for ev in sorted(by_day[day], key=lambda e: e["date"]):
            msg += fmt_event(ev)
        msg += "\n"
    return msg


def get_top_catalysts(n: int = 3) -> List[Dict]:
    """أهم 3 catalysts قادمة (الأقرب + الأعلى تأثير)"""
    events = get_week_events()
    today = datetime.utcnow()
    upcoming = []
    for ev in events:
        d = ev["date"] if isinstance(ev["date"], datetime) \
            else datetime.fromisoformat(ev["date"])
        if d > today and d < today + timedelta(days=7):
            upcoming.append(ev)
    # ترتيب: تأثير أعلى ثم أقرب
    upcoming.sort(key=lambda e: (-e.get("importance", 1),
                                  e["date"] if isinstance(e["date"], datetime)
                                  else datetime.fromisoformat(e["date"])))
    return upcoming[:n]


def fmt_top_catalysts() -> str:
    cats = get_top_catalysts(3)
    if not cats:
        return "🎯 *Top Catalysts*\n\nلا توجد أحداث ماكرو في الأسبوع القادم"

    msg = "🎯 *أهم 3 Catalysts قادمة:*\n\n"
    for i, ev in enumerate(cats, 1):
        d = ev["date"] if isinstance(ev["date"], datetime) \
            else datetime.fromisoformat(ev["date"])
        delta = d - datetime.utcnow().replace(tzinfo=d.tzinfo if d.tzinfo
                                              else None)
        hours = int(delta.total_seconds() / 3600)
        if hours < 24:
            when = f"خلال {hours}h"
        else:
            when = f"خلال {hours // 24}d"
        msg += f"*{i}. {ev.get('event', '')}*\n"
        msg += f"   {when} • {d.strftime('%Y-%m-%d %H:%M UTC')}\n"
        if ev.get("forecast"):
            msg += f"   التوقع: `{ev['forecast']}`"
            if ev.get("previous"):
                msg += f" | السابق: `{ev['previous']}`"
            msg += "\n"
        msg += "\n"
    return msg
