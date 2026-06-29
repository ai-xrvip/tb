"""
数据库模块 —— SQLite，线程安全，自动建表
使用全局单连接 + threading.Lock 确保线程安全
"""
import sqlite3
import os
import time as _time
import threading
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from utils.logger import logger
from config import config

_db_lock = threading.Lock()
_global_conn: sqlite3.Connection = None


def _ensure_db_dir(db_path: str):
    """确保数据库文件所在目录存在"""
    parent = os.path.dirname(db_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def _get_conn(db_path: str) -> sqlite3.Connection:
    """获取全局单连接，线程安全"""
    global _global_conn
    if _global_conn is None:
        _ensure_db_dir(db_path)
        _global_conn = sqlite3.connect(db_path, check_same_thread=False)
        _global_conn.row_factory = sqlite3.Row
        _global_conn.execute("PRAGMA journal_mode=WAL")
        _global_conn.execute("PRAGMA busy_timeout=5000")
    return _global_conn


class Database:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DB_PATH
        self.lock = _db_lock
        self._init_tables()

    @property
    def conn(self) -> sqlite3.Connection:
        return _get_conn(self.db_path)

    def _init_tables(self):
        try:
            with self.lock:
                c = self.conn.cursor()
                c.executescript("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id        INTEGER PRIMARY KEY,
                        current_role   TEXT DEFAULT 'xiaolu',
                        free_count     INTEGER DEFAULT 20,
                        vip_expire     TEXT,
                        total_messages INTEGER DEFAULT 0,
                        erotic_mode    INTEGER DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS blocked_users (
                        user_id      INTEGER PRIMARY KEY,
                        blocked_at   TEXT NOT NULL DEFAULT (datetime('now'))
                    );

                    CREATE TABLE IF NOT EXISTS user_unlocks (
                        user_id      INTEGER NOT NULL,
                        role_id      TEXT NOT NULL,
                        unlock_tier  INTEGER NOT NULL DEFAULT 0,
                        total_paid   REAL NOT NULL DEFAULT 0,
                        unlocked_at  TEXT,
                        PRIMARY KEY (user_id, role_id)
                    );

                    CREATE TABLE IF NOT EXISTS payment_orders (
                        order_id     TEXT PRIMARY KEY,
                        user_id      INTEGER NOT NULL,
                        role_id      TEXT NOT NULL,
                        item_name    TEXT NOT NULL,
                        amount       REAL NOT NULL,
                        unlock_tier  INTEGER NOT NULL,
                        status       TEXT NOT NULL DEFAULT 'pending',
                        created_at   TEXT NOT NULL,
                        paid_at      TEXT
                    );

                    CREATE TABLE IF NOT EXISTS activation_codes (
                        code     TEXT PRIMARY KEY,
                        type     TEXT NOT NULL,
                        days     INTEGER NOT NULL,
                        is_used  INTEGER DEFAULT 0,
                        used_by  INTEGER,
                        used_at  TEXT
                    );

                    CREATE TABLE IF NOT EXISTS chat_history (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id    INTEGER NOT NULL UNIQUE,
                        messages   TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS sent_media (
                        id        INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id   INTEGER NOT NULL,
                        role_id   TEXT NOT NULL,
                        category  TEXT NOT NULL,
                        filename  TEXT NOT NULL,
                        sent_at   TEXT NOT NULL,
                        UNIQUE(user_id, role_id, category, filename)
                    );

                    CREATE TABLE IF NOT EXISTS gift_purchases (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id      INTEGER NOT NULL,
                        gift_id      TEXT NOT NULL,
                        gift_name    TEXT NOT NULL,
                        price        REAL NOT NULL,
                        purchased_at TEXT NOT NULL,
                        UNIQUE(user_id, gift_id)
                    );

                    CREATE TABLE IF NOT EXISTS user_profiles (
                        user_id        INTEGER PRIMARY KEY,
                        display_name   TEXT DEFAULT '',
                        interests      TEXT DEFAULT '',
                        facts          TEXT DEFAULT '[]',
                        total_messages INTEGER DEFAULT 0,
                        vip_tier       INTEGER DEFAULT 0,
                        updated_at     TEXT
                    );

                    CREATE TABLE IF NOT EXISTS chat_summaries (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id      INTEGER NOT NULL,
                        summary_text TEXT NOT NULL,
                        msg_count    INTEGER NOT NULL,
                        created_at   TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS role_announcements (
                        role_id      TEXT PRIMARY KEY,
                        announced_at TEXT NOT NULL,
                        channel_id   TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS daily_checkins (
                        user_id      INTEGER NOT NULL,
                        checkin_date TEXT NOT NULL,
                        PRIMARY KEY (user_id, checkin_date)
                    );

                    CREATE TABLE IF NOT EXISTS yuanwei_triggers (
                        user_id      INTEGER NOT NULL,
                        role_id      TEXT NOT NULL,
                        triggered_at TEXT NOT NULL DEFAULT (datetime('now')),
                        PRIMARY KEY (user_id, role_id)
                    );

                    CREATE TABLE IF NOT EXISTS yuanwei_orders (
                        order_id     TEXT PRIMARY KEY,
                        user_id      INTEGER NOT NULL,
                        role_id      TEXT NOT NULL,
                        item_id      TEXT NOT NULL,
                        item_name    TEXT NOT NULL,
                        amount       REAL NOT NULL,
                        recipient_name  TEXT NOT NULL,
                        recipient_phone TEXT NOT NULL,
                        recipient_address TEXT NOT NULL,
                        status       TEXT NOT NULL DEFAULT 'pending',
                        created_at   TEXT NOT NULL,
                        paid_at      TEXT
                    );

                    CREATE TABLE IF NOT EXISTS keepsake_triggers (
                        user_id      INTEGER NOT NULL,
                        role_id      TEXT NOT NULL,
                        triggered_at TEXT NOT NULL DEFAULT (datetime('now')),
                        PRIMARY KEY (user_id, role_id)
                    );

                    CREATE TABLE IF NOT EXISTS keepsake_orders (
                        order_id     TEXT PRIMARY KEY,
                        user_id      INTEGER NOT NULL,
                        role_id      TEXT NOT NULL,
                        item_id      TEXT NOT NULL,
                        item_name    TEXT NOT NULL,
                        amount       REAL NOT NULL,
                        recipient_name  TEXT NOT NULL,
                        recipient_phone TEXT NOT NULL,
                        recipient_address TEXT NOT NULL,
                        status       TEXT NOT NULL DEFAULT 'pending',
                        created_at   TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS proactive_messages (
                        user_id      INTEGER NOT NULL,
                        role_id      TEXT NOT NULL,
                        sent_at      REAL NOT NULL,
                        PRIMARY KEY (user_id, role_id)
                    );

                    CREATE TABLE IF NOT EXISTS user_last_message (
                        user_id      INTEGER PRIMARY KEY,
                        last_message_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS knowledge_graph (
                        user_id      INTEGER NOT NULL,
                        role_id      TEXT NOT NULL,
                        key          TEXT NOT NULL,
                        value        TEXT NOT NULL,
                        updated_at   REAL NOT NULL,
                        PRIMARY KEY (user_id, role_id, key)
                    );
                """)
                # ── Performance indexes ──
                c.executescript("""
                    CREATE INDEX IF NOT EXISTS idx_chat_history_user ON chat_history(user_id);
                    CREATE INDEX IF NOT EXISTS idx_chat_history_updated ON chat_history(updated_at);
                    CREATE INDEX IF NOT EXISTS idx_users_role ON users(current_role);
                    CREATE INDEX IF NOT EXISTS idx_payment_orders_user ON payment_orders(user_id);
                    CREATE INDEX IF NOT EXISTS idx_payment_orders_status ON payment_orders(status);
                    CREATE INDEX IF NOT EXISTS idx_yuanwei_orders_user ON yuanwei_orders(user_id);
                    CREATE INDEX IF NOT EXISTS idx_keepsake_orders_user ON keepsake_orders(user_id);
                    CREATE INDEX IF NOT EXISTS idx_knowledge_graph_lookup ON knowledge_graph(user_id, role_id);
                    CREATE INDEX IF NOT EXISTS idx_sent_media_lookup ON sent_media(user_id, role_id, category);
                    CREATE INDEX IF NOT EXISTS idx_proactive_lookup ON proactive_messages(user_id, role_id);
                    CREATE INDEX IF NOT EXISTS idx_daily_checkins_date ON daily_checkins(checkin_date);
                """)
                self.conn.commit()
                # Migration: add erotic_mode column if missing
                try:
                    c.execute("ALTER TABLE users ADD COLUMN erotic_mode INTEGER DEFAULT 0")
                except Exception:
                    pass  # column already exists

                self.conn.commit()
                logger.info("All database tables initialized")
        except Exception as e:
            logger.error(f"DB init failed: {e}", exc_info=True)
            raise

    def get_user(self, user_id: int) -> Optional[dict]:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return dict(row) if row else None

    def create_user(self, user_id: int, role: str = "xiaolu"):
        with self.lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO users (user_id, current_role, free_count) VALUES (?, ?, ?)",
                (user_id, role, int(os.getenv('FREE_TRIAL_COUNT', '20'))),
            )
            self.conn.commit()

    def update_role(self, user_id: int, role: str):
        with self.lock:
            self.conn.execute(
                "UPDATE users SET current_role = ? WHERE user_id = ?", (role, user_id)
            )
            self.conn.commit()

    def is_vip(self, user_id: int) -> bool:
        """VIP is permanent - check vip_tier in user_profiles."""
        with self.lock:
            row = self.conn.execute(
                "SELECT vip_tier FROM user_profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
            return row is not None and (row["vip_tier"] or 0) > 0

    def set_vip(self, user_id: int, days: int = 0):
        """Set user as VIP permanently. days param kept for compatibility."""
        with self.lock:
            self.conn.execute(
                "INSERT INTO user_profiles (user_id, vip_tier) VALUES (?, 1) "
                "ON CONFLICT(user_id) DO UPDATE SET vip_tier = 1",
                (user_id,),
            )
            self.conn.commit()

    def deduct_free_count(self, user_id: int) -> bool:
        """原子减一，无需先读取再写入"""
        with self.lock:
            try:
                cur = self.conn.execute(
                    "UPDATE users SET free_count = free_count - 1 WHERE user_id = ? AND free_count > 0",
                    (user_id,),
                )
                self.conn.commit()
                return cur.rowcount > 0
            except Exception:
                logger.error(f"deduct error user_id={user_id}", exc_info=True)
                return False

    def add_free_count(self, user_id: int, count: int = 50):
        with self.lock:
            self.conn.execute(
                "UPDATE users SET free_count = COALESCE(free_count, 0) + ? WHERE user_id = ?",
                (count, user_id),
            )
            self.conn.commit()

    def increment_messages(self, user_id: int) -> int:
        with self.lock:
            self.conn.execute(
                "UPDATE users SET total_messages = COALESCE(total_messages, 0) + 1 WHERE user_id = ?",
                (user_id,),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT total_messages FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return row["total_messages"] if row else 0

    def get_total_messages(self, user_id: int) -> int:
        with self.lock:
            row = self.conn.execute(
                "SELECT total_messages FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return row["total_messages"] if row else 0

    def set_erotic_mode(self, user_id: int, enabled: bool = True):
        val = 1 if enabled else 0
        with self.lock:
            self.conn.execute(
                "UPDATE users SET erotic_mode = ? WHERE user_id = ?", (val, user_id)
            )
            self.conn.commit()

    def get_erotic_mode(self, user_id: int) -> bool:
        with self.lock:
            row = self.conn.execute(
                "SELECT erotic_mode FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return bool(row and row["erotic_mode"])

    def get_code(self, code: str) -> Optional[dict]:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM activation_codes WHERE code = ?", (code.strip().upper(),)
            ).fetchone()
            return dict(row) if row else None

    def use_code(self, code: str, user_id: int):
        with self.lock:
            self.conn.execute(
                "UPDATE activation_codes SET is_used = 1, used_by = ?, used_at = ? WHERE code = ?",
                (user_id, datetime.now(timezone.utc).isoformat(), code.strip().upper()),
            )
            self.conn.commit()

    def import_code(self, code: str, code_type: str, days: int):
        with self.lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO activation_codes (code, type, days) VALUES (?, ?, ?)",
                (code.strip().upper(), code_type, days),
            )
            self.conn.commit()

    def get_all_codes(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT code, type, days, is_used FROM activation_codes ORDER BY code"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_chat_history(self, user_id: int) -> list:
        with self.lock:
            row = self.conn.execute(
                "SELECT messages FROM chat_history WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row:
                try:
                    return json.loads(row["messages"])
                except (json.JSONDecodeError, TypeError):
                    return []
            return []

    def update_chat_history(self, user_id: int, messages: list):
        with self.lock:
            now = datetime.now(timezone.utc).isoformat()
            raw = json.dumps(messages, ensure_ascii=False)
            self.conn.execute(
                "INSERT INTO chat_history (user_id, messages, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET messages = ?, updated_at = ?",
                (user_id, raw, now, raw, now),
            )
            self.conn.commit()

    def get_sent_media(self, user_id: int, role_id: str, category: str) -> set:
        with self.lock:
            rows = self.conn.execute(
                "SELECT filename FROM sent_media WHERE user_id = ? AND role_id = ? AND category = ?",
                (user_id, role_id, category),
            ).fetchall()
            return {r["filename"] for r in rows}

    def mark_media_sent(self, user_id: int, role_id: str, category: str, filename: str):
        try:
            with self.lock:
                self.conn.execute(
                    "INSERT OR IGNORE INTO sent_media (user_id, role_id, category, filename, sent_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, role_id, category, filename, datetime.now(timezone.utc).isoformat()),
                )
                self.conn.commit()
        except Exception as e:
            logger.error(f"mark_media_sent failed: {e}")

    def get_user_gifts(self, user_id: int) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM gift_purchases WHERE user_id = ?", (user_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def has_gift(self, user_id: int, gift_id: str) -> bool:
        with self.lock:
            row = self.conn.execute(
                "SELECT 1 FROM gift_purchases WHERE user_id = ? AND gift_id = ?",
                (user_id, gift_id),
            ).fetchone()
            return row is not None

    def add_gift_purchase(self, user_id: int, gift_id: str, gift_name: str, price: float):
        with self.lock:
            now = datetime.now(timezone.utc).isoformat()
            self.conn.execute(
                "INSERT OR IGNORE INTO gift_purchases (user_id, gift_id, gift_name, price, purchased_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, gift_id, gift_name, price, now),
            )
            self.conn.commit()

    def get_chat_summaries(self, user_id: int, limit: int = 3) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM chat_summaries WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def add_chat_summary(self, user_id: int, summary: str, msg_count: int):
        with self.lock:
            now = datetime.now(timezone.utc).isoformat()
            self.conn.execute(
                "INSERT INTO chat_summaries (user_id, summary_text, msg_count, created_at) VALUES (?, ?, ?, ?)",
                (user_id, summary, msg_count, now),
            )
            self.conn.commit()
            logger.info(f"chat summary saved user_id={user_id} msgs={msg_count}")

    def use_free_count(self, user_id: int) -> bool:
        return self.deduct_free_count(user_id)

    def increment_message_count(self, user_id: int) -> int:
        return self.increment_messages(user_id)

    def get_all_users(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT user_id, current_role, free_count, vip_expire, total_messages FROM users ORDER BY user_id"
            ).fetchall()
            return [dict(r) for r in rows]

    def is_blocked(self, user_id: int) -> bool:
        with self.lock:
            row = self.conn.execute(
                "SELECT 1 FROM blocked_users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return row is not None

    def block_user(self, user_id: int):
        with self.lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO blocked_users (user_id) VALUES (?)", (user_id,)
            )
            self.conn.commit()

    def unblock_user(self, user_id: int):
        with self.lock:
            self.conn.execute(
                "DELETE FROM blocked_users WHERE user_id = ?", (user_id,)
            )
            self.conn.commit()

    def get_unlock_tier(self, user_id: int, role_id: str) -> int:
        with self.lock:
            row = self.conn.execute(
                "SELECT unlock_tier FROM user_unlocks WHERE user_id = ? AND role_id = ?",
                (user_id, role_id),
            ).fetchone()
            return row["unlock_tier"] if row else 0

    def set_unlock_tier(self, user_id: int, role_id: str, tier: int, amount: float = 0):
        with self.lock:
            now = datetime.now(timezone.utc).isoformat()
            self.conn.execute(
                "INSERT INTO user_unlocks (user_id, role_id, unlock_tier, total_paid, unlocked_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, role_id) DO UPDATE SET "
                "unlock_tier = ?, total_paid = total_paid + ?, unlocked_at = ?",
                (user_id, role_id, tier, amount, now, tier, amount, now),
            )
            self.conn.commit()

    def create_payment_order(self, order_id: str, user_id: int, role_id: str,
                              item_name: str, amount: float, unlock_tier: int) -> str:
        with self.lock:
            now = datetime.now(timezone.utc).isoformat()
            self.conn.execute(
                "INSERT INTO payment_orders (order_id, user_id, role_id, item_name, amount, unlock_tier, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                (order_id, user_id, role_id, item_name, amount, unlock_tier, now),
            )
            self.conn.commit()
            return order_id

    def get_payment_order(self, order_id: str) -> dict | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM payment_orders WHERE order_id = ?", (order_id,)
            ).fetchone()
            return dict(row) if row else None

    def mark_order_paid(self, order_id: str):
        with self.lock:
            order = self.get_payment_order(order_id)
            if not order or order["status"] != "pending":
                return
            now = datetime.now(timezone.utc).isoformat()
            self.conn.execute(
                "UPDATE payment_orders SET status = 'paid', paid_at = ? WHERE order_id = ?",
                (now, order_id),
            )
            self.set_unlock_tier(order["user_id"], order["role_id"], order["unlock_tier"], order["amount"])
            self.conn.commit()
            logger.info(f"order paid and unlocked: {order_id} user={order['user_id']} tier={order['unlock_tier']}")

    def get_user_orders(self, user_id: int) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM payment_orders WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def is_announced(self, role_id: str, channel_id: str = "") -> bool:
        with self.lock:
            row = self.conn.execute(
                "SELECT 1 FROM role_announcements WHERE role_id = ? AND channel_id = ?", (role_id, channel_id)
            ).fetchone()
            return row is not None

    def mark_announced(self, role_id: str, channel_id: str):
        with self.lock:
            now = datetime.now(timezone.utc).isoformat()
            self.conn.execute(
                "INSERT OR IGNORE INTO role_announcements (role_id, announced_at, channel_id) VALUES (?, ?, ?)",
                (role_id, now, channel_id),
            )
            self.conn.commit()
            logger.info(f"Role announced: {role_id} -> {channel_id}")

    def get_all_yuanwei_orders(self):
        with self.lock:
            rows = self.conn.execute("SELECT * FROM yuanwei_orders ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def has_yuanwei_triggered(self, user_id, role_id):
        with self.lock:
            row = self.conn.execute("SELECT 1 FROM yuanwei_triggers WHERE user_id=? AND role_id=?", (user_id, role_id)).fetchone()
            return row is not None

    def mark_yuanwei_triggered(self, user_id, role_id):
        with self.lock:
            now = datetime.now(timezone.utc).isoformat()
            self.conn.execute("INSERT OR IGNORE INTO yuanwei_triggers (user_id, role_id, triggered_at) VALUES (?,?,?)", (user_id, role_id, now))
            self.conn.commit()

    def create_yuanwei_order(self, order_id, user_id, role_id, item_id, item_name, amount, name, phone, address):
        with self.lock:
            now = datetime.now(timezone.utc).isoformat()
            self.conn.execute("INSERT INTO yuanwei_orders (order_id,user_id,role_id,item_id,item_name,amount,recipient_name,recipient_phone,recipient_address,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,'pending',?)", (order_id, user_id, role_id, item_id, item_name, amount, name, phone, address, now))
            self.conn.commit()

    def get_yuanwei_orders(self, user_id):
        with self.lock:
            rows = self.conn.execute("SELECT * FROM yuanwei_orders WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_all_keepsake_orders(self):
        with self.lock:
            rows = self.conn.execute("SELECT * FROM keepsake_orders ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def has_keepsake_triggered(self, user_id, role_id):
        with self.lock:
            row = self.conn.execute("SELECT 1 FROM keepsake_triggers WHERE user_id=? AND role_id=?", (user_id, role_id)).fetchone()
            return row is not None

    def mark_keepsake_triggered(self, user_id, role_id):
        with self.lock:
            now = datetime.now(timezone.utc).isoformat()
            self.conn.execute("INSERT OR IGNORE INTO keepsake_triggers (user_id, role_id, triggered_at) VALUES (?,?,?)", (user_id, role_id, now))
            self.conn.commit()

    def create_keepsake_order(self, order_id, user_id, role_id, item_id, item_name, amount, name, phone, address):
        with self.lock:
            now = datetime.now(timezone.utc).isoformat()
            self.conn.execute("INSERT INTO keepsake_orders (order_id,user_id,role_id,item_id,item_name,amount,recipient_name,recipient_phone,recipient_address,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,'pending',?)", (order_id, user_id, role_id, item_id, item_name, amount, name, phone, address, now))
            self.conn.commit()

    def get_keepsake_orders(self, user_id):
        with self.lock:
            rows = self.conn.execute("SELECT * FROM keepsake_orders WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def has_checked_in_today(self, user_id):
        with self.lock:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            row = self.conn.execute(
                "SELECT 1 FROM daily_checkins WHERE user_id=? AND checkin_date=?",
                (user_id, today),
            ).fetchone()
            return row is not None

    def do_checkin(self, user_id):
        with self.lock:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            self.conn.execute(
                "INSERT OR IGNORE INTO daily_checkins (user_id, checkin_date) VALUES (?,?)",
                (user_id, today),
            )
            self.conn.execute(
                "UPDATE users SET free_count = COALESCE(free_count, 0) + 5 WHERE user_id=?",
                (user_id,),
            )
            self.conn.commit()

    def get_active_users_for_role(self, role_id: str) -> list[int]:
        with self.lock:
            rows = self.conn.execute("SELECT DISTINCT user_id FROM chat_history").fetchall()
            return [r["user_id"] for r in rows]

    def get_last_proactive(self, user_id: int, role_id: str) -> float | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT sent_at FROM proactive_messages WHERE user_id=? AND role_id=?",
                (user_id, role_id),
            ).fetchone()
            return row["sent_at"] if row else None

    def set_last_proactive(self, user_id: int, role_id: str):
        with self.lock:
            now = _time.time()
            self.conn.execute(
                "INSERT INTO proactive_messages (user_id, role_id, sent_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, role_id) DO UPDATE SET sent_at = ?",
                (user_id, role_id, now, now),
            )
            self.conn.commit()

    def clear_announcement(self, role_id: str):
        with self.lock:
            self.conn.execute("DELETE FROM role_announcements WHERE role_id=?", (role_id,))
            self.conn.commit()

    # -- User Profile --
    def get_profile(self, user_id):
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row:
                return {
                    "user_id": row["user_id"],
                    "display_name": row["display_name"] or "",
                    "interests": row["interests"] or "",
                    "facts": json.loads(row["facts"] or "[]"),
                    "total_messages": row["total_messages"] or 0,
                    "vip_tier": row["vip_tier"] or 0,
                }
            return {"user_id": user_id, "display_name": "", "interests": "", "facts": [], "total_messages": 0, "vip_tier": 0}

    def upsert_profile(self, user_id, display_name="", interests="", facts=None, total_messages=0):
        import json
        with self.lock:
            now = datetime.now(timezone.utc).isoformat()
            facts_json = json.dumps(facts or [], ensure_ascii=False)
            self.conn.execute(
                "INSERT INTO user_profiles (user_id, display_name, interests, facts, total_messages, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "display_name = CASE WHEN ? != '' THEN ? ELSE display_name END, "
                "interests = CASE WHEN ? != '' THEN ? ELSE interests END, "
                "facts = ?, total_messages = ?, updated_at = ?",
                (user_id, display_name, interests, facts_json, total_messages, now,
                 display_name, display_name, interests, interests,
                 facts_json, total_messages, now),
            )
            self.conn.commit()

    def update_profile_tier(self, user_id, tier):
        with self.lock:
            self.conn.execute(
                "UPDATE user_profiles SET vip_tier = ?, updated_at = ? WHERE user_id = ?",
                (tier, datetime.now(timezone.utc).isoformat(), user_id),
            )
            self.conn.commit()

    def cleanup_inactive_users(self, days: int = 180) -> int:
        """Delete records of users inactive for more than N days. Returns count."""
        import time
        with self.lock:
            cutoff = time.time() - (days * 86400)
            rows = self.conn.execute(
                "SELECT user_id FROM user_last_message WHERE last_message_at < ?", (cutoff,)
            ).fetchall()
            count = 0
            for row in rows:
                uid = row["user_id"]
                vip = self.conn.execute(
                    "SELECT vip_tier FROM user_profiles WHERE user_id = ?", (uid,)
                ).fetchone()
                if vip and vip["vip_tier"] > 0:
                    continue
                self.conn.execute("DELETE FROM users WHERE user_id = ?", (uid,))
                self.conn.execute("DELETE FROM chat_history WHERE user_id = ?", (uid,))
                self.conn.execute("DELETE FROM user_profiles WHERE user_id = ?", (uid,))
                self.conn.execute("DELETE FROM user_last_message WHERE user_id = ?", (uid,))
                count += 1
            self.conn.commit()
            if count:
                logger.info(f"Cleanup: removed {count} inactive users (> {days} days, non-VIP)")
            return count

    def backup_database(self) -> str | None:
        """Backup database to backups/ directory, returns path or None"""
        import shutil as _shutil
        from datetime import datetime as _dt
        with self.lock:
            backup_dir = os.path.join(os.path.dirname(self.db_path) or ".", "backups")
            os.makedirs(backup_dir, exist_ok=True)
            timestamp = _dt.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(backup_dir, f"bot_{timestamp}.db")
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                _shutil.copy2(self.db_path, backup_path)
                all_backups = sorted(
                    [f for f in os.listdir(backup_dir) if f.endswith(".db")],
                    reverse=True
                )
                for old in all_backups[48:]:
                    os.remove(os.path.join(backup_dir, old))
                logger.info(f"DB backup: {backup_path}")
                return backup_path
            except Exception as e:
                logger.error(f"DB backup failed: {e}")
                return None

    def get_last_message_time(self, user_id: int) -> float | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT last_message_at FROM user_last_message WHERE user_id=?", (user_id,)
            ).fetchone()
            return row["last_message_at"] if row else None

    def update_last_message_time(self, user_id: int):
        with self.lock:
            now = _time.time()
            self.conn.execute(
                "INSERT INTO user_last_message (user_id, last_message_at) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET last_message_at = ?",
                (user_id, now, now),
            )
            self.conn.commit()

    # ── Knowledge Graph (thread-safe wrappers) ──
    def get_knowledge(self, user_id: int, role_id: str) -> dict[str, str]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT key, value FROM knowledge_graph WHERE user_id=? AND role_id=?",
                (user_id, role_id),
            ).fetchall()
            return {r["key"]: r["value"] for r in rows}

    def set_knowledge(self, user_id: int, role_id: str, key: str, value: str):
        with self.lock:
            now = _time.time()
            self.conn.execute(
                "INSERT INTO knowledge_graph (user_id, role_id, key, value, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, role_id, key) DO UPDATE SET value=?, updated_at=?",
                (user_id, role_id, key, value, now, value, now),
            )
            self.conn.commit()

    def delete_knowledge(self, user_id: int, role_id: str, key: str):
        with self.lock:
            self.conn.execute(
                "DELETE FROM knowledge_graph WHERE user_id=? AND role_id=? AND key=?",
                (user_id, role_id, key),
            )
            self.conn.commit()


db = Database()
