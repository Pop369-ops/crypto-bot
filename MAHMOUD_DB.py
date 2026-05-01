"""
MAHMOUD_DB.py
═════════════════════════════════════════════════
طبقة قاعدة بيانات SQLite للبوت
الجداول:
  • tracked_trades       — الصفقات اليدوية المتتبعة
  • trade_alerts_sent    — تنبيهات تم إرسالها (لمنع التكرار)
  • risk_protection      — إعدادات حماية المحفظة
  • trade_journal        — سجل الصفقات المغلقة (للإحصائيات)
═════════════════════════════════════════════════
"""

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

DB_PATH = os.environ.get("MAHMOUD_DB_PATH", "mahmoud_bot.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # ── الصفقات المتتبعة (يدخلها المستخدم يدوياً) ──
    c.execute("""
    CREATE TABLE IF NOT EXISTS tracked_trades (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id       INTEGER NOT NULL,
        symbol        TEXT    NOT NULL,
        action        TEXT    NOT NULL,            -- LONG / SHORT
        entry         REAL    NOT NULL,
        sl            REAL    NOT NULL,
        tp1           REAL,
        tp2           REAL,
        tp3           REAL,
        size_pct      REAL    DEFAULT 1.0,         -- نسبة من المحفظة
        leverage      INTEGER DEFAULT 1,
        notes         TEXT,
        status        TEXT    DEFAULT 'OPEN',      -- OPEN / CLOSED / CANCELLED
        tp1_hit       INTEGER DEFAULT 0,
        tp2_hit       INTEGER DEFAULT 0,
        tp3_hit       INTEGER DEFAULT 0,
        opened_at     TEXT    NOT NULL,
        closed_at     TEXT,
        exit_price    REAL,
        exit_reason   TEXT,
        pnl_pct       REAL,
        pnl_dollars   REAL
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_tt_chat ON tracked_trades(chat_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tt_sym  ON tracked_trades(symbol, status)")

    # ── التنبيهات المرسلة (مفتاح فريد عشان ما يتكرر التنبيه) ──
    c.execute("""
    CREATE TABLE IF NOT EXISTS trade_alerts_sent (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id    INTEGER NOT NULL,
        alert_type  TEXT    NOT NULL,
        sent_at     TEXT    NOT NULL,
        UNIQUE(trade_id, alert_type)
    )
    """)

    # ── إعدادات حماية المخاطر (لكل مستخدم) ──
    c.execute("""
    CREATE TABLE IF NOT EXISTS risk_protection (
        chat_id                    INTEGER PRIMARY KEY,
        max_daily_loss_pct         REAL    DEFAULT 8.0,
        max_weekly_loss_pct        REAL    DEFAULT 15.0,
        max_open_trades            INTEGER DEFAULT 5,
        max_consecutive_losses     INTEGER DEFAULT 3,
        cooldown_hours             INTEGER DEFAULT 24,
        daily_pnl_pct              REAL    DEFAULT 0,
        weekly_pnl_pct             REAL    DEFAULT 0,
        consecutive_losses         INTEGER DEFAULT 0,
        locked_until               TEXT,
        last_reset_daily           TEXT,
        last_reset_weekly          TEXT,
        enabled                    INTEGER DEFAULT 1
    )
    """)

    # ── دفتر التداول (الصفقات المغلقة) ──
    c.execute("""
    CREATE TABLE IF NOT EXISTS trade_journal (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id         INTEGER NOT NULL,
        symbol          TEXT    NOT NULL,
        action          TEXT    NOT NULL,
        entry           REAL,
        exit_price      REAL,
        sl              REAL,
        size_pct        REAL,
        leverage        INTEGER,
        pnl_pct         REAL,
        pnl_dollars     REAL,
        duration_hours  REAL,
        exit_reason     TEXT,
        notes           TEXT,
        opened_at       TEXT,
        closed_at       TEXT
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_j_chat ON trade_journal(chat_id, closed_at DESC)")

    # ── الأخبار المرئية (لمنع التكرار) ──
    c.execute("""
    CREATE TABLE IF NOT EXISTS seen_news (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        url_hash    TEXT    UNIQUE NOT NULL,
        url         TEXT,
        title       TEXT,
        source      TEXT,
        published   TEXT,
        seen_at     TEXT    NOT NULL,
        impact      INTEGER DEFAULT 0,        -- 0-10 (AI scored)
        coins       TEXT,                     -- مفصول بفاصلات: BTC,ETH
        sentiment   TEXT                      -- bullish/bearish/neutral
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_news_seen ON seen_news(seen_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_news_impact ON seen_news(impact DESC, seen_at DESC)")

    # ── المشتركون في تنبيهات الأخبار + التقرير اليومي ──
    c.execute("""
    CREATE TABLE IF NOT EXISTS news_subscribers (
        chat_id            INTEGER PRIMARY KEY,
        breaking_news      INTEGER DEFAULT 1,  -- تنبيه فوري للأخبار العاجلة
        daily_report       INTEGER DEFAULT 0,  -- التقرير الصباحي
        report_hour        INTEGER DEFAULT 8,
        report_minute      INTEGER DEFAULT 0,
        min_impact         INTEGER DEFAULT 7,  -- الحد الأدنى لإرسال خبر
        coins_filter       TEXT,               -- BTC,ETH (فاضي = الكل)
        subscribed_at      TEXT
    )
    """)

    # ── توصيات AI (للتتبع وقياس الدقة) ──
    c.execute("""
    CREATE TABLE IF NOT EXISTS ai_recommendations (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id         INTEGER NOT NULL,
        symbol          TEXT    NOT NULL,
        action          TEXT,                   -- LONG/SHORT/HOLD
        confidence      REAL,
        entry_price     REAL,
        sl              REAL,
        tp1             REAL,
        tp2             REAL,
        tp3             REAL,
        ai_used         TEXT,                   -- claude/gemini/openai/consensus
        reasoning       TEXT,
        consensus_data  TEXT,                   -- JSON من الـ3 AIs
        created_at      TEXT,
        validated_at    TEXT,                   -- تاريخ التحقق من النتيجة
        result          TEXT,                   -- WIN/LOSS/PENDING
        actual_pnl      REAL
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_ai_recs ON ai_recommendations(chat_id, created_at DESC)")

    # ── تخزين الكاش (للأخبار/الكاليندر/الأسعار) ──
    c.execute("""
    CREATE TABLE IF NOT EXISTS cache_store (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,
        expires_at  TEXT NOT NULL
    )
    """)

    # ── Whale alerts ──
    c.execute("""
    CREATE TABLE IF NOT EXISTS whale_alerts (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        tx_hash         TEXT UNIQUE,
        amount          REAL,
        amount_usd      REAL,
        symbol          TEXT,
        from_owner      TEXT,
        to_owner        TEXT,
        timestamp       INTEGER,
        seen_at         TEXT
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_whale_seen ON whale_alerts(seen_at DESC)")

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# Trade CRUD
# ─────────────────────────────────────────────

def insert_trade(chat_id: int, symbol: str, action: str,
                 entry: float, sl: float,
                 tp1: Optional[float] = None,
                 tp2: Optional[float] = None,
                 tp3: Optional[float] = None,
                 size_pct: float = 1.0,
                 leverage: int = 1,
                 notes: Optional[str] = None) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    INSERT INTO tracked_trades
    (chat_id, symbol, action, entry, sl, tp1, tp2, tp3, size_pct, leverage, notes, opened_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (chat_id, symbol, action.upper(), entry, sl, tp1, tp2, tp3,
          size_pct, leverage, notes, datetime.utcnow().isoformat()))
    tid = c.lastrowid
    conn.commit()
    conn.close()
    return tid


def get_open_trades(chat_id: Optional[int] = None) -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    if chat_id is not None:
        c.execute("SELECT * FROM tracked_trades WHERE status='OPEN' AND chat_id=? "
                  "ORDER BY opened_at DESC", (chat_id,))
    else:
        c.execute("SELECT * FROM tracked_trades WHERE status='OPEN' ORDER BY opened_at DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_trade_by_symbol(chat_id: int, symbol: str) -> Optional[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM tracked_trades WHERE status='OPEN' AND chat_id=? AND symbol=? "
              "ORDER BY opened_at DESC LIMIT 1",
              (chat_id, symbol.upper()))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_trade_by_id(trade_id: int) -> Optional[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM tracked_trades WHERE id=?", (trade_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def update_trade(trade_id: int, **fields):
    if not fields:
        return
    allowed = {"sl", "tp1", "tp2", "tp3", "size_pct", "leverage", "notes",
               "tp1_hit", "tp2_hit", "tp3_hit"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    conn = get_conn()
    c = conn.cursor()
    sets = ", ".join(f"{k}=?" for k in fields.keys())
    vals = list(fields.values()) + [trade_id]
    c.execute(f"UPDATE tracked_trades SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()


def close_trade(trade_id: int, exit_price: float, exit_reason: str,
                pnl_pct: Optional[float] = None,
                pnl_dollars: Optional[float] = None) -> Optional[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM tracked_trades WHERE id=?", (trade_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    trade = dict(row)

    closed_at = datetime.utcnow().isoformat()
    opened_at = trade["opened_at"]
    duration_hours = 0.0
    try:
        d1 = datetime.fromisoformat(opened_at)
        d2 = datetime.fromisoformat(closed_at)
        duration_hours = (d2 - d1).total_seconds() / 3600.0
    except Exception:
        pass

    # حساب pnl_pct تلقائياً لو ما اتمررش
    if pnl_pct is None and trade.get("entry"):
        if trade["action"] == "LONG":
            pnl_pct = (exit_price - trade["entry"]) / trade["entry"] * 100
        else:
            pnl_pct = (trade["entry"] - exit_price) / trade["entry"] * 100

    c.execute("""
    UPDATE tracked_trades
    SET status='CLOSED', closed_at=?, exit_price=?, exit_reason=?,
        pnl_pct=?, pnl_dollars=?
    WHERE id=?
    """, (closed_at, exit_price, exit_reason, pnl_pct, pnl_dollars, trade_id))

    c.execute("""
    INSERT INTO trade_journal
    (chat_id, symbol, action, entry, exit_price, sl, size_pct, leverage,
     pnl_pct, pnl_dollars, duration_hours, exit_reason, notes, opened_at, closed_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (trade["chat_id"], trade["symbol"], trade["action"], trade["entry"],
          exit_price, trade["sl"], trade["size_pct"], trade["leverage"],
          pnl_pct, pnl_dollars, duration_hours, exit_reason, trade.get("notes"),
          opened_at, closed_at))
    conn.commit()
    conn.close()
    return {**trade, "exit_price": exit_price, "exit_reason": exit_reason,
            "pnl_pct": pnl_pct, "duration_hours": duration_hours}


def cancel_trade(trade_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE tracked_trades SET status='CANCELLED', closed_at=? WHERE id=?",
              (datetime.utcnow().isoformat(), trade_id))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# Alerts (منع التكرار)
# ─────────────────────────────────────────────

def alert_was_sent(trade_id: int, alert_type: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM trade_alerts_sent WHERE trade_id=? AND alert_type=?",
              (trade_id, alert_type))
    found = c.fetchone() is not None
    conn.close()
    return found


def mark_alert_sent(trade_id: int, alert_type: str):
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO trade_alerts_sent (trade_id, alert_type, sent_at) VALUES (?,?,?)",
                  (trade_id, alert_type, datetime.utcnow().isoformat()))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()


def reset_repeating_alert(trade_id: int, alert_type: str):
    """مسح تنبيه — يستخدم للتنبيهات المتكررة (مثلاً NEAR_SL لما يبتعد السعر)"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM trade_alerts_sent WHERE trade_id=? AND alert_type=?",
              (trade_id, alert_type))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# Risk Protection
# ─────────────────────────────────────────────

def get_risk(chat_id: int) -> Dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM risk_protection WHERE chat_id=?", (chat_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO risk_protection (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        c.execute("SELECT * FROM risk_protection WHERE chat_id=?", (chat_id,))
        row = c.fetchone()
    conn.close()
    return dict(row)


def update_risk(chat_id: int, **fields):
    get_risk(chat_id)
    if not fields:
        return
    conn = get_conn()
    c = conn.cursor()
    sets = ", ".join(f"{k}=?" for k in fields.keys())
    vals = list(fields.values()) + [chat_id]
    c.execute(f"UPDATE risk_protection SET {sets} WHERE chat_id=?", vals)
    conn.commit()
    conn.close()


def record_trade_close(chat_id: int, pnl_pct: float):
    s = get_risk(chat_id)
    today = datetime.utcnow().date().isoformat()
    last_daily = s.get("last_reset_daily") or ""
    daily = s["daily_pnl_pct"] if last_daily == today else 0.0
    consec = s["consecutive_losses"] or 0

    daily += pnl_pct
    consec = consec + 1 if pnl_pct < 0 else 0

    update_risk(chat_id,
                daily_pnl_pct=daily,
                consecutive_losses=consec,
                last_reset_daily=today)


def check_can_trade(chat_id: int) -> tuple:
    """يرجع (can_trade: bool, reason: str)"""
    s = get_risk(chat_id)
    if not s.get("enabled", 1):
        return True, ""
    today = datetime.utcnow().date().isoformat()
    last_daily = s.get("last_reset_daily") or ""
    daily = s["daily_pnl_pct"] if last_daily == today else 0.0

    if daily <= -abs(s["max_daily_loss_pct"]):
        return False, f"⛔ تجاوزت الحد اليومي ({daily:.1f}% / -{s['max_daily_loss_pct']:.0f}%)"
    if (s["consecutive_losses"] or 0) >= s["max_consecutive_losses"]:
        return False, f"⛔ {s['consecutive_losses']} خسائر متتالية — استرح ثم استأنف"
    open_count = len(get_open_trades(chat_id))
    if open_count >= s["max_open_trades"]:
        return False, f"⛔ صفقات مفتوحة ({open_count}/{s['max_open_trades']})"
    return True, ""


# ─────────────────────────────────────────────
# Journal stats
# ─────────────────────────────────────────────

def journal_stats(chat_id: int, days: int = 30) -> Dict:
    conn = get_conn()
    c = conn.cursor()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    c.execute("""
    SELECT * FROM trade_journal
    WHERE chat_id=? AND closed_at >= ?
    ORDER BY closed_at DESC
    """, (chat_id, cutoff))
    trades = [dict(r) for r in c.fetchall()]
    conn.close()

    if not trades:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "total_pnl": 0.0, "profit_factor": 0.0,
                "avg_win": 0.0, "avg_loss": 0.0, "sharpe": 0.0,
                "best": None, "worst": None, "days": days}

    wins = [t for t in trades if (t["pnl_pct"] or 0) > 0]
    losses = [t for t in trades if (t["pnl_pct"] or 0) < 0]
    total_pnl = sum(t["pnl_pct"] or 0 for t in trades)

    gp = sum(t["pnl_pct"] for t in wins) if wins else 0.0
    gl = abs(sum(t["pnl_pct"] for t in losses)) if losses else 0.0
    pf = gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0)

    pnls = [t["pnl_pct"] or 0 for t in trades]
    if len(pnls) > 1:
        avg = sum(pnls) / len(pnls)
        var = sum((p - avg) ** 2 for p in pnls) / len(pnls)
        std = var ** 0.5
        sharpe = (avg / std) * (365 ** 0.5) if std > 0 else 0.0
    else:
        sharpe = 0.0

    return {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(trades) * 100) if trades else 0.0,
        "total_pnl": total_pnl,
        "profit_factor": round(pf, 2),
        "avg_win": (sum(t["pnl_pct"] for t in wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(t["pnl_pct"] for t in losses) / len(losses)) if losses else 0.0,
        "sharpe": round(sharpe, 2),
        "best": max(trades, key=lambda t: t["pnl_pct"] or -9999),
        "worst": min(trades, key=lambda t: t["pnl_pct"] or 9999),
        "days": days,
    }


# ─────────────────────────────────────────────
# News / Seen URLs
# ─────────────────────────────────────────────

def news_seen(url_hash: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM seen_news WHERE url_hash=?", (url_hash,))
    found = c.fetchone() is not None
    conn.close()
    return found


def insert_news(url_hash: str, url: str, title: str, source: str,
                published: str, impact: int = 0,
                coins: Optional[str] = None,
                sentiment: Optional[str] = None) -> int:
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("""
        INSERT INTO seen_news
        (url_hash, url, title, source, published, seen_at, impact, coins, sentiment)
        VALUES (?,?,?,?,?,?,?,?,?)
        """, (url_hash, url, title, source, published,
              datetime.utcnow().isoformat(), impact, coins, sentiment))
        nid = c.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        nid = 0
    conn.close()
    return nid


def get_recent_news(hours: int = 24, min_impact: int = 0,
                    coin: Optional[str] = None,
                    limit: int = 50) -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    if coin:
        c.execute("""
        SELECT * FROM seen_news
        WHERE seen_at >= ? AND impact >= ? AND coins LIKE ?
        ORDER BY impact DESC, seen_at DESC
        LIMIT ?
        """, (cutoff, min_impact, f"%{coin.upper()}%", limit))
    else:
        c.execute("""
        SELECT * FROM seen_news
        WHERE seen_at >= ? AND impact >= ?
        ORDER BY impact DESC, seen_at DESC
        LIMIT ?
        """, (cutoff, min_impact, limit))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ─────────────────────────────────────────────
# News Subscribers
# ─────────────────────────────────────────────

def get_subscriber(chat_id: int) -> Optional[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM news_subscribers WHERE chat_id=?", (chat_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def add_subscriber(chat_id: int, **fields):
    """Insert or update subscriber"""
    conn = get_conn()
    c = conn.cursor()
    existing = c.execute("SELECT 1 FROM news_subscribers WHERE chat_id=?",
                          (chat_id,)).fetchone()
    if existing:
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields.keys())
            vals = list(fields.values()) + [chat_id]
            c.execute(f"UPDATE news_subscribers SET {sets} WHERE chat_id=?", vals)
    else:
        defaults = {
            "breaking_news": 1, "daily_report": 0,
            "report_hour": 8, "report_minute": 0,
            "min_impact": 7, "coins_filter": None,
            "subscribed_at": datetime.utcnow().isoformat(),
        }
        defaults.update(fields)
        cols = ["chat_id"] + list(defaults.keys())
        vals = [chat_id] + list(defaults.values())
        c.execute(f"INSERT INTO news_subscribers ({','.join(cols)}) VALUES "
                  f"({','.join('?' * len(cols))})", vals)
    conn.commit()
    conn.close()


def remove_subscriber(chat_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM news_subscribers WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()


def get_breaking_subscribers(min_impact: int) -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    SELECT * FROM news_subscribers
    WHERE breaking_news=1 AND min_impact <= ?
    """, (min_impact,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_daily_report_subscribers(hour: int, minute: int) -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    SELECT * FROM news_subscribers
    WHERE daily_report=1 AND report_hour=? AND report_minute=?
    """, (hour, minute))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ─────────────────────────────────────────────
# AI Recommendations
# ─────────────────────────────────────────────

def insert_ai_rec(chat_id: int, symbol: str, action: str,
                  confidence: float, entry_price: float,
                  sl: Optional[float] = None,
                  tp1: Optional[float] = None,
                  tp2: Optional[float] = None,
                  tp3: Optional[float] = None,
                  ai_used: str = "consensus",
                  reasoning: str = "",
                  consensus_data: Optional[str] = None) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    INSERT INTO ai_recommendations
    (chat_id, symbol, action, confidence, entry_price, sl, tp1, tp2, tp3,
     ai_used, reasoning, consensus_data, created_at, result)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (chat_id, symbol, action, confidence, entry_price, sl, tp1, tp2, tp3,
          ai_used, reasoning, consensus_data,
          datetime.utcnow().isoformat(), "PENDING"))
    rid = c.lastrowid
    conn.commit()
    conn.close()
    return rid


def get_ai_recs(chat_id: int, days: int = 30, limit: int = 50) -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    c.execute("""
    SELECT * FROM ai_recommendations
    WHERE chat_id=? AND created_at >= ?
    ORDER BY created_at DESC
    LIMIT ?
    """, (chat_id, cutoff, limit))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ─────────────────────────────────────────────
# Cache (TTL)
# ─────────────────────────────────────────────

def cache_set(key: str, value: str, ttl_seconds: int = 300):
    expires = (datetime.utcnow() + timedelta(seconds=ttl_seconds)).isoformat()
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    INSERT OR REPLACE INTO cache_store (key, value, expires_at)
    VALUES (?, ?, ?)
    """, (key, value, expires))
    conn.commit()
    conn.close()


def cache_get(key: str) -> Optional[str]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value, expires_at FROM cache_store WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    expires = datetime.fromisoformat(row["expires_at"])
    if datetime.utcnow() >= expires:
        return None
    return row["value"]


def cache_cleanup():
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM cache_store WHERE expires_at < ?",
              (datetime.utcnow().isoformat(),))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# Whale Alerts
# ─────────────────────────────────────────────

def whale_seen(tx_hash: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM whale_alerts WHERE tx_hash=?", (tx_hash,))
    found = c.fetchone() is not None
    conn.close()
    return found


def insert_whale(tx_hash: str, amount: float, amount_usd: float,
                 symbol: str, from_owner: str, to_owner: str,
                 timestamp: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("""
        INSERT INTO whale_alerts
        (tx_hash, amount, amount_usd, symbol, from_owner, to_owner,
         timestamp, seen_at)
        VALUES (?,?,?,?,?,?,?,?)
        """, (tx_hash, amount, amount_usd, symbol, from_owner, to_owner,
              timestamp, datetime.utcnow().isoformat()))
        wid = c.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        wid = 0
    conn.close()
    return wid


def get_recent_whales(hours: int = 24, symbol: Optional[str] = None,
                      min_usd: float = 1_000_000, limit: int = 30) -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    if symbol:
        c.execute("""
        SELECT * FROM whale_alerts
        WHERE seen_at >= ? AND amount_usd >= ? AND symbol=?
        ORDER BY amount_usd DESC LIMIT ?
        """, (cutoff, min_usd, symbol.upper(), limit))
    else:
        c.execute("""
        SELECT * FROM whale_alerts
        WHERE seen_at >= ? AND amount_usd >= ?
        ORDER BY amount_usd DESC LIMIT ?
        """, (cutoff, min_usd, limit))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows
