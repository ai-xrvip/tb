"""bot_utils.py — Shared state, constants, and helper functions used by all bot modules."""
import asyncio
import html
import logging
import re
import sys
import time as _time
from collections import defaultdict
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from config import config
from database import (
    db_load_vip, db_save_vip, db_delete_expired_vip,
    db_load_users, db_add_user,
    db_load_invites, db_save_invite,
    db_get_user_history,
)

logger = logging.getLogger(__name__)

# ---- Logging (configured once by bot.py, re-used here) ----
# ---- Constants ----
RESULTS_PER_PAGE: int = 5
URL_TTL: int = 3600
USER_STATE_TTL: int = 1800
RATE_LIMIT_WINDOW: int = 60
RATE_LIMIT_MAX: int = config.MAX_SEARCHES_PER_MINUTE

_SEARCH_TIMEOUTS: dict[str, float] = {
    "4KHD": config.SEARCH_TIMEOUT_4KHD,
    "XChina": config.SEARCH_TIMEOUT_XC,
    "EH": config.SEARCH_TIMEOUT_EH,
}

EH_ENABLED: bool = bool(config.EH_MEMBER_ID and config.EH_PASS_HASH)

# ---- State ----
user_search_state: dict = {}
user_waiting_search: set[int] = set()
url_store: dict = {}
admin_setvip_state: dict[int, bool] = {}
url_counter: int = 0
VIP_USERS: dict[int, float | None] = {}
ALL_USERS: set[int] = set()
user_waiting_card: set[int] = set()
INVITES: dict[str, str] = {}
_user_search_times: dict[int, list[float]] = defaultdict(list)

# Async locks
_url_store_lock: asyncio.Lock | None = None
_url_counter_lock: asyncio.Lock | None = None
_user_search_lock: asyncio.Lock | None = None
_download_sem: asyncio.Semaphore | None = None
_invite_lock: asyncio.Lock | None = None
_vip_lock: asyncio.Lock | None = None


def init_locks() -> None:
    global _url_store_lock, _url_counter_lock, _user_search_lock, _download_sem, _invite_lock, _vip_lock
    if _url_store_lock is None:
        _url_store_lock = asyncio.Lock()
        _url_counter_lock = asyncio.Lock()
        _user_search_lock = asyncio.Lock()
        _download_sem = asyncio.Semaphore(12)
        _invite_lock = asyncio.Lock()
        _vip_lock = asyncio.Lock()


def get_download_sem() -> asyncio.Semaphore:
    assert _download_sem is not None
    return _download_sem


def get_url_store_lock() -> asyncio.Lock:
    assert _url_store_lock is not None
    return _url_store_lock


def get_url_counter_lock() -> asyncio.Lock:
    assert _url_counter_lock is not None
    return _url_counter_lock


def get_user_search_lock() -> asyncio.Lock:
    assert _user_search_lock is not None
    return _user_search_lock


def get_invite_lock() -> asyncio.Lock:
    assert _invite_lock is not None
    return _invite_lock


def get_vip_lock() -> asyncio.Lock:
    assert _vip_lock is not None
    return _vip_lock


ADMIN_IDS: set[int] = config.ADMIN_IDS

MENU_KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("🔍 搜索"), KeyboardButton("🎲 推荐"), KeyboardButton("👑 VIP"), KeyboardButton("👤 我的")],
    [KeyboardButton("📖 帮助")],
], resize_keyboard=True)

START_TEXT: str = """<b>✨ 美少女图集搜索姬 ✨</b>

👋 主人好呀～我是你的专属图集小助手！

🎀 <b>我能做什么？</b>
• 🔍 海量 Cosplay、写真、自拍图集随意搜
• 🎲 不知道看什么？试试随机推荐

💕 资源每日更新，再也不怕片荒啦～

👇 点击下方按钮开始探索吧！"""

START_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔍 搜索图集", callback_data="menu_search")],
    [InlineKeyboardButton("🎲 随机推荐", callback_data="menu_random")],
    [InlineKeyboardButton("👑 开通VIP", callback_data="menu_vip")],
    [InlineKeyboardButton("📖 使用帮助", callback_data="menu_help")],
])

VIP_TEXT: str = """<b>👑 VIP 会员说明</b>

🎯 <b>VIP 特权：</b>
• 无限次搜索
• 查看完整大图集
• 翻页浏览所有图片
• 收藏喜欢的图集
• 优先体验新功能

🚧 功能开发中，敬请期待～"""

_ONE_DAY: int = 86400
PURCHASE_URL: str = "https://t.me/xiuren88bot?start=buy_524"

# ── Context sync helper ─────────────────────────────────────────
# Called by bot.py after loading data from DB into BotContext.
# Syncs module globals so existing imports (from bot_utils import VIP_USERS) work.

from bot_context import get_ctx as _get_ctx

def sync_from_context() -> None:
    ctx = _get_ctx()
    globals()['VIP_USERS'] = ctx.vip_users
    globals()['ALL_USERS'] = ctx.all_users
    globals()['INVITES'] = ctx.invites



# ========== Helper functions ==========

def now_ts() -> float:
    return datetime.now().timestamp()


async def cleanup_url_store() -> None:
    global url_store
    now = now_ts()
    async with get_url_store_lock():
        url_store = {k: v for k, v in url_store.items() if now - v.get("ts", 0) < URL_TTL}


def cleanup_user_state(user_id: int) -> None:
    if user_id in user_search_state:
        ts = user_search_state[user_id].get("ts", 0)
        if now_ts() - ts > USER_STATE_TTL:
            del user_search_state[user_id]


async def cleanup_all() -> None:
    now = now_ts()
    stale_users = [uid for uid, s in user_search_state.items() if now - s.get("ts", 0) > USER_STATE_TTL]
    for uid in stale_users:
        del user_search_state[uid]
    await cleanup_url_store()
    await _clean_expired_vip()
    cutoff = now - RATE_LIMIT_WINDOW * 2
    for uid in list(_user_search_times.keys()):
        _user_search_times[uid] = [t for t in _user_search_times[uid] if t > cutoff]
        if not _user_search_times[uid]:
            del _user_search_times[uid]


async def save_vip_db(user_id: int, expiry: float | None) -> None:
    await db_save_vip(user_id, expiry)

# Backward-compatible alias used by some modules
_save_vip = save_vip_db


async def load_vip_db() -> dict[int, float | None]:
    return await db_load_vip()


async def load_users_db() -> set[int]:
    return await db_load_users()


async def load_invites_db() -> dict[str, str]:
    return await db_load_invites()


async def save_invite_db(code: str, inviter_id: int) -> None:
    await db_save_invite(code, inviter_id)


async def store_url(url: str, **kwargs: object) -> str:
    global url_counter
    async with get_url_counter_lock():
        url_counter += 1
        key = str(url_counter)
    async with get_url_store_lock():
        entry: dict[str, object] = {"url": url, "ts": now_ts()}
        entry.update(kwargs)
        url_store[key] = entry
        if url_counter % 1000 == 0:
            await cleanup_url_store()
    return key


def get_url(key: str) -> str:
    entry = url_store.get(key)
    if not entry:
        return ""
    if now_ts() - entry.get("ts", 0) > URL_TTL:
        return ""
    return str(entry["url"])


async def check_rate_limit(user_id: int) -> bool:
    now = now_ts()
    cutoff = now - RATE_LIMIT_WINDOW
    async with get_user_search_lock():
        times = _user_search_times[user_id]
        _user_search_times[user_id] = [t for t in times if t > cutoff]
        current_count = len(_user_search_times[user_id])
        if current_count >= RATE_LIMIT_MAX:
            return False
        _user_search_times[user_id].append(now)
        return True


def parse_count_from_title(title: str) -> int:
    m = re.search(r"(\d+)\s*photos?", title, re.IGNORECASE)
    if m: return int(m.group(1))
    m = re.search(r"(\d+)\s*[pP张]", title)
    if m: return int(m.group(1))
    return 0


def clean_title(title: str) -> str:
    title = re.sub(r"\s*\[\d+[^\]]*(?:MB|GB|photos?|张|P\b)[^\]]*\]", "", title)
    title = re.sub(r"\s*f:[a-z ]+$", "", title)
    title = title.replace("·", " ").replace("•", " ").replace("・", " ")
    title = re.sub(r" {2,}", " ", title)
    title = title.strip(" -|/\t\n\r")
    return title


def is_vip(user_id: int) -> bool:
    if user_id not in VIP_USERS:
        return False
    expiry = VIP_USERS[user_id]
    if expiry is None:
        return True
    if now_ts() > expiry:
        return False
    return True


def _clean_expired_vip() -> None:
    """Schedule async expired VIP cleanup with lock protection."""
    async def _locked_cleanup():
        async with get_vip_lock():
            await _async_clean_expired_vip()
    asyncio.create_task(_locked_cleanup())


async def _async_clean_expired_vip() -> None:
    """Remove expired VIP users. Caller must hold _vip_lock."""
    now = now_ts()
    expired = [uid for uid, exp in list(VIP_USERS.items()) if exp is not None and now > exp]
    if expired:
        for uid in expired:
            del VIP_USERS[uid]
        await db_delete_expired_vip()
        logger.info(f"Cleaned {len(expired)} expired VIP users")


def parse_date_for_sort(date_str: str) -> str:
    if not date_str:
        return ""
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", date_str)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


async def send_or_edit(msg_or_query, text: str, reply_markup=None, parse_mode: str = "HTML") -> None:
    from telegram import Message  # noqa: F811
    try:
        if isinstance(msg_or_query, Message):
            await msg_or_query.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await msg_or_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        err_str = str(e)
        if "not modified" not in err_str.lower():
            logger.warning(f"send_or_edit failed: {err_str}")


async def safe_search_wrapper(name: str, coro):
    timeout = _SEARCH_TIMEOUTS.get(name, 6.0)
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"{name} search timed out after {timeout}s")
        return []
    except Exception as e:
        logger.error(f"{name} search error: {e}")
        return []


# ========== Title dedup ==========

def dedup_results(results: list[dict], threshold: float = 0.80) -> list[dict]:
    import difflib
    kept: list[dict] = []
    for r in results:
        duplicate = None
        for existing in kept:
            ratio = difflib.SequenceMatcher(None, r["title"].lower(), existing["title"].lower()).ratio()
            if ratio >= threshold:
                duplicate = existing
                break
        if duplicate:
            if r.get("publish_date") and not duplicate.get("publish_date"):
                kept[kept.index(duplicate)] = r
        else:
            kept.append(r)
    return kept


# ========== Quality Ranking ==========

def quality_score(r: dict) -> float:
    from scraper import gallery_clicks
    clicks = gallery_clicks.get(r.get("url", ""), 0)
    click_score = min(clicks / 10.0, 1.0)
    count = 0
    count_str = r.get("count", "")
    if isinstance(count_str, str) and count_str:
        cm = re.search(r"(\d+)", str(count_str))
        if cm:
            count = int(cm.group(1))
    if count == 0:
        count = parse_count_from_title(r.get("title", ""))
    count_score = min(count / 50.0, 1.0)
    date_str = parse_date_for_sort(r.get("publish_date", ""))
    date_score = 0.3
    if date_str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            days_ago = (datetime.now().timestamp() - dt.timestamp()) / 86400
            date_score = max(0.0, 1.0 - days_ago / 30.0)
        except Exception:
            pass
    return 0.4 * click_score + 0.3 * count_score + 0.3 * date_score


# ========== Hot keyword keyboard ==========

async def build_hot_keyword_keyboard(extra_buttons=None, user_id: int | None = None):
    from scraper import get_hot_keywords
    buttons: list[list] = []
    if user_id is not None:
        history = await db_get_user_history(user_id, limit=6)
        if history:
            hist_row = [InlineKeyboardButton(f"🕐 {kw}", callback_data=f"hot_{html.escape(kw)}") for kw in history[:3]]
            if hist_row:
                buttons.append(hist_row)
    hot = await get_hot_keywords(top_n=8)
    row: list = []
    for kw in hot:
        row.append(InlineKeyboardButton(kw, callback_data=f"hot_{html.escape(kw)}"))
        if len(row) >= 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if extra_buttons:
        buttons.extend(extra_buttons)
    return InlineKeyboardMarkup(buttons)
