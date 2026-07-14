"""SQLite database layer — replaces JSON-file persistence with WAL-mode SQLite.

All write operations are dispatched to a background thread via run_in_executor
so they never block the asyncio event loop.  Reads use the same executor for
consistency (SQLite in WAL mode handles concurrent reads safely).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from config import config

logger = logging.getLogger(__name__)

_db_executor: Optional[ThreadPoolExecutor] = None
_db_path: str = ""
_db_ready: asyncio.Event = asyncio.Event()

SCHEMA = r"""
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS vip_users (
    user_id    INTEGER PRIMARY KEY,
    expiry     REAL,          -- None / NULL = permanent
    first_seen REAL NOT NULL DEFAULT (strftime('%s'))
);

CREATE TABLE IF NOT EXISTS all_users (
    user_id    INTEGER PRIMARY KEY,
    first_seen REAL NOT NULL DEFAULT (strftime('%s')),
    last_seen  REAL NOT NULL DEFAULT (strftime('%s'))
);

CREATE TABLE IF NOT EXISTS cards (
    code       TEXT PRIMARY KEY,
    card_type  TEXT NOT NULL DEFAULT 'forever',  -- month | quarter | year | forever | trial
    days       INTEGER,
    used       INTEGER NOT NULL DEFAULT 0,
    used_by    INTEGER,
    used_at    REAL,
    created_by INTEGER,
    created_at REAL NOT NULL DEFAULT (strftime('%s'))
);

CREATE TABLE IF NOT EXISTS invites (
    code       TEXT PRIMARY KEY,
    inviter_id INTEGER NOT NULL,
    created_at REAL NOT NULL DEFAULT (strftime('%s'))
);

CREATE TABLE IF NOT EXISTS favorites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    title      TEXT NOT NULL DEFAULT '',
    url        TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT '',
    added_at   REAL NOT NULL DEFAULT (strftime('%s')),
    UNIQUE(user_id, url)
);

CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_invites_inviter ON invites(inviter_id);
CREATE INDEX IF NOT EXISTS idx_cards_used ON cards(used);

CREATE TABLE IF NOT EXISTS stats_daily (
    date       TEXT PRIMARY KEY,  -- '2026-07-08'
    new_users  INTEGER NOT NULL DEFAULT 0,
    card_activations INTEGER NOT NULL DEFAULT 0,
    searches   INTEGER NOT NULL DEFAULT 0,
    clicks     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS search_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    keyword    TEXT NOT NULL,
    searched_at REAL NOT NULL DEFAULT (strftime('%s'))
);

CREATE INDEX IF NOT EXISTS idx_history_user ON search_history(user_id, searched_at DESC);

CREATE TABLE IF NOT EXISTS subscriptions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    keyword    TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT '',  -- '4khd' | 'xchina' | 'ehentai' | '' (all)
    last_checked_at REAL NOT NULL DEFAULT (strftime('%s')),
    created_at REAL NOT NULL DEFAULT (strftime('%s')),
    UNIQUE(user_id, keyword, source)
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_keyword ON subscriptions(keyword);

CREATE TABLE IF NOT EXISTS subscription_pushed (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    gallery_url TEXT NOT NULL,
    pushed_at  REAL NOT NULL DEFAULT (strftime('%s')),
    UNIQUE(user_id, gallery_url)
);

CREATE INDEX IF NOT EXISTS idx_pushed_user ON subscription_pushed(user_id, gallery_url);
"""


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def _init_db(path: str):
    """Called in the executor thread — creates / migrates tables."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = _dict_factory
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Public helpers — run SQL in the executor thread
# ---------------------------------------------------------------------------

def _conn() -> sqlite3.Connection:
    """Get a thread-local connection (created lazily per thread)."""
    assert _local is not None, "Database not initialized; call start_database() first"
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(_db_path, check_same_thread=False)
        conn.row_factory = _dict_factory
        _local.conn = conn
    return conn


_local: threading.local | None = None  # will be a threading.local once db is initialized


async def _run(fn, *args, **kwargs):
    """Dispatch a callable to the DB executor and await its result."""
    await _db_ready.wait()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_db_executor, fn, *args, **kwargs)


async def _exec(sql: str, params=()):
    def _do():
        c = _conn()
        c.execute(sql, params)
        c.commit()
    await _run(_do)
async def _exec_rowcount(sql: str, params=()) -> int:
    def _do():
        c = _conn()
        cur = c.execute(sql, params)
        rc = cur.rowcount
        c.commit()
        return rc
    return await _run(_do)



async def _fetch_all(sql: str, params=()) -> list[dict]:
    def _do():
        c = _conn()
        return c.execute(sql, params).fetchall()
    return await _run(_do)


async def _fetch_one(sql: str, params=()) -> Optional[dict]:
    def _do():
        c = _conn()
        return c.execute(sql, params).fetchone()
    return await _run(_do)


async def _fetch_val(sql: str, params=()):
    def _do():
        c = _conn()
        row = c.execute(sql, params).fetchone()
        return row and next(iter(row.values()))
    return await _run(_do)


async def _exec_many(sql: str, seq):
    def _do():
        c = _conn()
        c.executemany(sql, seq)
        c.commit()
    await _run(_do)


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

async def start_database():
    global _db_executor, _db_path, _local
    _local = threading.local()
    _db_path = config.DB_PATH
    _db_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="db")
    # Ensure data directory exists
    Path(_db_path).parent.mkdir(parents=True, exist_ok=True)
    # Initialise the database on the executor thread
    await asyncio.get_running_loop().run_in_executor(_db_executor, _init_db, _db_path)
    _db_ready.set()
    logger.info("Database started (SQLite WAL mode): %s", _db_path)


async def stop_database():
    global _db_executor
    _db_ready.clear()
    if _db_executor:
        _db_executor.shutdown(wait=True)
        _db_executor = None
    logger.info("Database stopped")


# ---------------------------------------------------------------------------
# VIP users
# ---------------------------------------------------------------------------

async def db_load_vip() -> dict[int, Optional[float]]:
    rows = await _fetch_all("SELECT user_id, expiry FROM vip_users")
    return {r["user_id"]: r["expiry"] for r in rows}


async def db_save_vip(user_id: int, expiry: Optional[float]):
    await _exec(
        "INSERT INTO vip_users (user_id, expiry, first_seen) VALUES (?, ?, strftime('%s')) "
        "ON CONFLICT(user_id) DO UPDATE SET expiry=excluded.expiry",
        (user_id, expiry),
    )


async def db_delete_expired_vip() -> int:
    now = time.time()
    def _do():
        c = _conn()
        c.execute("DELETE FROM vip_users WHERE expiry IS NOT NULL AND expiry < ?", (now,))
        c.commit()
        return c.rowcount
    return await _run(_do)


async def db_vip_count() -> int:
    return await _fetch_val("SELECT COUNT(*) FROM vip_users") or 0


async def db_vip_permanent_count() -> int:
    return await _fetch_val("SELECT COUNT(*) FROM vip_users WHERE expiry IS NULL") or 0


async def db_vip_expiring_soon(days: int = 7) -> list[dict]:
    now = time.time()
    cutoff = now + days * 86400
    return await _fetch_all(
        "SELECT user_id, expiry FROM vip_users WHERE expiry IS NOT NULL AND expiry > ? AND expiry <= ?",
        (now, cutoff),
    )


async def db_vip_expiring_today() -> list[dict]:
    return await _fetch_all(
        "SELECT user_id, expiry FROM vip_users WHERE expiry IS NOT NULL AND expiry > ? AND expiry <= ?",
        (time.time(), time.time() + 86400),
    )


# ---------------------------------------------------------------------------
# All users
# ---------------------------------------------------------------------------

async def db_load_users() -> set[int]:
    rows = await _fetch_all("SELECT user_id FROM all_users")
    return {r["user_id"] for r in rows}


async def db_add_user(user_id: int):
    await _exec(
        "INSERT OR IGNORE INTO all_users (user_id, first_seen, last_seen) VALUES (?, strftime('%s'), strftime('%s'))",
        (user_id,),
    )


async def db_touch_user(user_id: int):
    await _exec("UPDATE all_users SET last_seen = strftime('%s') WHERE user_id = ?", (user_id,))


async def db_user_count() -> int:
    return await _fetch_val("SELECT COUNT(*) FROM all_users") or 0


async def db_regular_user_count() -> int:
    return await _fetch_val(
        "SELECT COUNT(*) FROM all_users WHERE user_id NOT IN (SELECT user_id FROM vip_users)"
    ) or 0


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

async def db_load_cards() -> dict:
    rows = await _fetch_all("SELECT * FROM cards")
    return {
        r["code"]: {
            "type": r["card_type"], "days": r["days"],
            "used": bool(r["used"]), "used_by": r["used_by"],
            "used_at": r["used_at"], "created_by": r["created_by"],
        }
        for r in rows
    }


async def db_save_card(code: str, card_type: str, days: Optional[int], created_by: int):
    await _exec(
        "INSERT OR IGNORE INTO cards (code, card_type, days, created_by) VALUES (?, ?, ?, ?)",
        (code, card_type, days, created_by),
    )


async def db_activate_card(code: str, user_id: int) -> bool:
    """Activate a card. Returns True if activation succeeded, False if card not found or already used.
    Atomic: the UPDATE WHERE used=0 ensures no race condition."""
    return (await _exec_rowcount(
        "UPDATE cards SET used=1, used_by=?, used_at=strftime('%s') WHERE code=? AND used=0",
        (user_id, code),
    )) > 0


async def db_card_count_used() -> int:
    return await _fetch_val("SELECT COUNT(*) FROM cards WHERE used=1") or 0


async def db_card_count_total() -> int:
    return await _fetch_val("SELECT COUNT(*) FROM cards") or 0


async def db_list_unused_cards() -> list[dict]:
    return await _fetch_all("SELECT code, card_type, days FROM cards WHERE used=0 ORDER BY code")


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------

async def db_load_invites() -> dict[str, str]:
    rows = await _fetch_all("SELECT code, inviter_id FROM invites")
    return {r["code"]: str(r["inviter_id"]) for r in rows}


async def db_save_invite(code: str, inviter_id: int):
    await _exec(
        "INSERT OR IGNORE INTO invites (code, inviter_id) VALUES (?, ?)",
        (code, inviter_id),
    )


async def db_find_invite(code: str) -> Optional[str]:
    row = await _fetch_one("SELECT inviter_id FROM invites WHERE code = ?", (code,))
    return str(row["inviter_id"]) if row else None


async def db_invite_count() -> int:
    return await _fetch_val("SELECT COUNT(*) FROM invites") or 0


async def db_user_invites(user_id: int) -> list[str]:
    rows = await _fetch_all("SELECT code FROM invites WHERE inviter_id = ?", (user_id,))
    return [r["code"] for r in rows]


# ---------------------------------------------------------------------------
# Favorites
# ---------------------------------------------------------------------------

async def db_add_favorite(user_id: int, title: str, url: str, source: str) -> bool:
    """Returns True if added, False if already exists."""
    try:
        await _exec(
            "INSERT OR IGNORE INTO favorites (user_id, title, url, source) VALUES (?, ?, ?, ?)",
            (user_id, title, url, source),
        )
        return True
    except Exception:
        return False


async def db_get_favorites(user_id: int) -> list[dict]:
    return await _fetch_all(
        "SELECT title, url, source, added_at FROM favorites WHERE user_id=? ORDER BY added_at DESC LIMIT 20",
        (user_id,),
    )


async def db_delete_favorite(user_id: int, url: str) -> bool:
    """Delete one favorite entry by url. Returns True if any row was deleted."""
    return bool(await _exec_rowcount(
        "DELETE FROM favorites WHERE user_id=? AND url=?",
        (user_id, url),
    ))


async def db_clear_favorites(user_id: int) -> int:
    """Clear all favorites for a user. Returns number of deleted rows."""
    return await _exec_rowcount("DELETE FROM favorites WHERE user_id=?", (user_id,))


# ---------------------------------------------------------------------------
# Daily stats
# ---------------------------------------------------------------------------

async def db_bump_stat(date_str: str, column: str, delta: int = 1):
    await _exec(
        f"INSERT INTO stats_daily (date, {column}) VALUES (?, ?) "
        f"ON CONFLICT(date) DO UPDATE SET {column} = {column} + excluded.{column}",
        (date_str, delta),
    )


async def db_get_stats_last_days(days: int = 7) -> list[dict]:
    return await _fetch_all(
        "SELECT * FROM stats_daily WHERE date >= date('now', ?) ORDER BY date DESC",
        (f"-{days} days",),
    )


async def db_get_daily_report() -> dict:
    """Return a summary dict for the admin report."""
    today = time.strftime("%Y-%m-%d")
    yesterday_rows = await _fetch_all(
        "SELECT * FROM stats_daily WHERE date = date('now', '-1 days')"
    )
    today_rows = await _fetch_all(
        "SELECT * FROM stats_daily WHERE date = date('now')"
    )
    return {"today": today_rows[0] if today_rows else {}, "yesterday": yesterday_rows[0] if yesterday_rows else {}}


async def db_add_search_history(user_id: int, keyword: str):
    await _exec(
        "INSERT OR IGNORE INTO search_history (user_id, keyword) VALUES (?, ?)",
        (user_id, keyword.lower()),
    )

async def db_get_user_history(user_id: int, limit: int = 6) -> list[str]:
    rows = await _fetch_all(
        "SELECT keyword, MAX(searched_at) AS last_search FROM search_history WHERE user_id = ? GROUP BY keyword ORDER BY last_search DESC LIMIT ?",
        (user_id, limit),
    )
    return [r["keyword"] for r in rows]

async def db_subscribe(user_id: int, keyword: str, source: str = "") -> bool:
    try:
        await _exec(
            "INSERT OR IGNORE INTO subscriptions (user_id, keyword, source) VALUES (?, ?, ?)",
            (user_id, keyword.lower(), source),
        )
        return True
    except Exception:
        return False

async def db_unsubscribe(user_id: int, keyword: str, source: str = ""):
    await _exec(
        "DELETE FROM subscriptions WHERE user_id = ? AND keyword = ? AND source = ?",
        (user_id, keyword.lower(), source),
    )

async def db_get_subscriptions(user_id: int) -> list[dict]:
    return await _fetch_all(
        "SELECT * FROM subscriptions WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    )

async def db_get_all_subscriptions() -> list[dict]:
    return await _fetch_all("SELECT * FROM subscriptions ORDER BY user_id")

async def db_touch_subscription(sub_id: int):
    await _exec("UPDATE subscriptions SET last_checked_at = strftime('%s') WHERE id = ?", (sub_id,))

async def db_was_pushed(user_id: int, gallery_url: str) -> bool:
    row = await _fetch_one(
        "SELECT 1 FROM subscription_pushed WHERE user_id = ? AND gallery_url = ?",
        (user_id, gallery_url),
    )
    return row is not None

async def db_mark_pushed(user_id: int, gallery_url: str):
    await _exec(
        "INSERT OR IGNORE INTO subscription_pushed (user_id, gallery_url) VALUES (?, ?)",
        (user_id, gallery_url),
    )

async def db_prune_pushed(days: int = 30):
    cutoff = time.time() - days * 86400
    def _do():
        c = _conn()
        c.execute("DELETE FROM subscription_pushed WHERE pushed_at < ?", (cutoff,))
        c.commit()
    await _run(_do)

async def db_migrate_from_json(data_dir: str) -> dict:
    """Migrate old JSON data files into SQLite tables.

    Looks for vip_users.json, users.json, invites.json, cards.json in
    *data_dir* and migrates them if the corresponding SQLite table is empty.
    Migrated files are renamed to *.migrated so they are only processed once.
    """
    import json as _json
    import os as _os
    stats = {"vip": 0, "users": 0, "cards": 0, "invites": 0, "favorites": 0, "skipped": []}

    # VIP users
    vip_path = _os.path.join(data_dir, "vip_users.json")
    if _os.path.exists(vip_path) and not _os.path.exists(vip_path + ".migrated"):
        if await db_vip_count() == 0:
            try:
                with open(vip_path, "r", encoding="utf-8-sig") as f:
                    data = _json.load(f)
                if isinstance(data, list):
                    data = {int(uid): None for uid in data}
                else:
                    data = {int(k): v for k, v in data.items()}
                for user_id, expiry in data.items():
                    await db_save_vip(user_id, expiry)
                    stats["vip"] += 1
                _os.rename(vip_path, vip_path + ".migrated")
                logger.info("Migrated %d VIP users from %s", stats["vip"], vip_path)
            except Exception as e:
                logger.warning("VIP migration failed: %s", e)
                stats["skipped"].append("vip_users.json")
        else:
            logger.info("Skipping VIP migration - DB already has data")

    # All users
    users_path = _os.path.join(data_dir, "users.json")
    if _os.path.exists(users_path) and not _os.path.exists(users_path + ".migrated"):
        if await db_user_count() == 0:
            try:
                with open(users_path, "r", encoding="utf-8-sig") as f:
                    data = _json.load(f)
                for uid in data:
                    await db_add_user(int(uid))
                    stats["users"] += 1
                _os.rename(users_path, users_path + ".migrated")
                logger.info("Migrated %d users from %s", stats["users"], users_path)
            except Exception as e:
                logger.warning("Users migration failed: %s", e)
                stats["skipped"].append("users.json")
        else:
            logger.info("Skipping users migration - DB already has data")

    # Invites
    invites_path = _os.path.join(data_dir, "invites.json")
    if _os.path.exists(invites_path) and not _os.path.exists(invites_path + ".migrated"):
        if await db_invite_count() == 0:
            try:
                with open(invites_path, "r", encoding="utf-8-sig") as f:
                    data = _json.load(f)
                for code, inviter_id in data.items():
                    await db_save_invite(code, int(inviter_id))
                    stats["invites"] += 1
                _os.rename(invites_path, invites_path + ".migrated")
                logger.info("Migrated %d invites from %s", stats["invites"], invites_path)
            except Exception as e:
                logger.warning("Invites migration failed: %s", e)
                stats["skipped"].append("invites.json")
        else:
            logger.info("Skipping invites migration - DB already has data")

    # Cards from cards.json
    cards_path = _os.path.join(data_dir, "cards.json")
    if _os.path.exists(cards_path) and not _os.path.exists(cards_path + ".migrated"):
        if await db_card_count_total() == 0:
            try:
                with open(cards_path, "r", encoding="utf-8-sig") as f:
                    data = _json.load(f)
                if isinstance(data, dict):
                    # Filter out label entries (Chinese descriptions in seed data)
                    clean = {k: v for k, v in data.items() if not any(
                        label in k for label in ("月卡", "季卡", "年卡", "永久", "体验卡")
                    )}
                    if clean:
                        await db_seed_from_dict(clean)
                        stats["cards"] = len(clean)
                _os.rename(cards_path, cards_path + ".migrated")
                logger.info("Migrated %d cards from %s", stats["cards"], cards_path)
            except Exception as e:
                logger.warning("Cards migration failed: %s", e)
                stats["skipped"].append("cards.json")
        else:
            logger.info("Skipping cards migration - DB already has data")

    # Fallback: if cards.json doesn't exist (excluded by .dockerignore), seed from seed_cards.py
    if stats["cards"] == 0 and await db_card_count_total() == 0:
        try:
            from seed_cards import SEED_CARDS
            if SEED_CARDS:
                clean = {k: v for k, v in SEED_CARDS.items() if not any(
                    label in k for label in ("月卡", "季卡", "年卡", "永久", "体验")
                )}
                if clean:
                    await db_seed_from_dict(clean)
                    stats["cards"] = len(clean)
                    logger.info("Seeded %d cards from seed_cards.py (fallback)", stats["cards"])
        except Exception as e:
            logger.warning("Cards seed fallback failed: %s", e)
            stats.setdefault("skipped", []).append("seed_cards.py")

    # Favorites
    fav_path = _os.path.join(data_dir, "favorites.json")
    if _os.path.exists(fav_path) and not _os.path.exists(fav_path + ".migrated"):
        try:
            with open(fav_path, "r", encoding="utf-8-sig") as f:
                data = _json.load(f)
            for uid_str, favs in data.items():
                for f_item in favs:
                    await db_add_favorite(
                        int(uid_str),
                        f_item.get("title", ""),
                        f_item.get("url", ""),
                        f_item.get("source", ""),
                    )
                    stats["favorites"] += 1
            _os.rename(fav_path, fav_path + ".migrated")
            logger.info("Migrated %d favorites from %s", stats["favorites"], fav_path)
        except Exception as e:
            logger.warning("Favorites migration failed: %s", e)
            stats["skipped"].append("favorites.json")

    # Log card count for diagnostics
    try:
        total = await db_card_count_total()
        used = await db_card_count_used()
        logger.info("Card DB stats: %d total, %d used", total, used)
    except Exception as e:
        logger.debug("Card stats logging failed: %s", e)

    return stats


async def db_seed_from_dict(cards: dict[str, dict]):
    """Migrate seed cards from the old Python dict into the DB (idempotent)."""
    rows = [
        (
            code,
            info.get("type", "forever"),
            info.get("days"),
            int(info.get("used", False)),
            info.get("used_by"),
            info.get("used_at"),
            info.get("created_by"),
        )
        for code, info in cards.items()
    ]
    def _do():
        c = _conn()
        c.executemany(
            "INSERT OR IGNORE INTO cards (code, card_type, days, used, used_by, used_at, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        c.commit()
    await _run(_do)
    logger.info(f"Seeded {len(rows)} cards from old dictionary")
