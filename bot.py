"""Gallery Search Bot - Telegram Bot (async)"""
import asyncio
import httpx
import logging
import sys
import os
import traceback
import json
import re
import html
import secrets
import string
import gc
from datetime import datetime
from collections import defaultdict

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    Message, InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)
from config import config
from seed_cards import SEED_CARDS
from scraper import (
    search_galleries, get_gallery_images, get_random_gallery,
    download_image, track_click,
    search_xchina, get_xchina_gallery,
)
from proxy_pool import start_proxy_pool, stop_proxy_pool
from pre_cache import (
    pop_pre_cached, start_pre_cache, track_pre_served,
    track_pre_clicked, track_pre_skipped,
)
from scraper_eh import (
    search_ehentai, get_eh_gallery, get_eh_magnet,
)
EH_ENABLED = bool(config.EH_MEMBER_ID and config.EH_PASS_HASH)

# ---- Logging ----
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger(__name__)

# ---- Constants ----
RESULTS_PER_PAGE = 5
URL_TTL = 3600
USER_STATE_TTL = 1800
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = config.MAX_SEARCHES_PER_MINUTE
SEARCH_TIMEOUT = 6.0

# ---- State ----
user_search_state: dict = {}
user_waiting_search: set = set()
url_store: dict = {}
admin_setvip_state: dict = {}
url_counter: int = 0
VIP_USERS: dict = {}
VIP_FILE = os.path.join(DATA_DIR, "vip_users.json")
CARD_FILE = os.path.join(DATA_DIR, "cards.json")
user_waiting_card: set = set()
ALL_USERS: set = set()
USERS_FILE = os.path.join(DATA_DIR, "users.json")
INVITES_FILE = os.path.join(DATA_DIR, "invites.json")
FAVORITES_FILE = os.path.join(DATA_DIR, "favorites.json")

# Async locks
_url_store_lock = None
_url_counter_lock = None
_user_search_lock = None
_download_sem = None

def _init_locks():
    global _url_store_lock, _url_counter_lock, _user_search_lock, _download_sem
    if _url_store_lock is None:
        _url_store_lock = asyncio.Lock()
        _url_counter_lock = asyncio.Lock()
        _user_search_lock = asyncio.Lock()
        _download_sem = asyncio.Semaphore(12)

_user_search_times: dict = defaultdict(list)
ADMIN_IDS = config.ADMIN_IDS

MENU_KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("🔍 搜索"), KeyboardButton("🎲 推荐"), KeyboardButton("👑 VIP"), KeyboardButton("👤 我的")],
    [KeyboardButton("📖 帮助")],
], resize_keyboard=True)

_ONE_DAY = 86400
PURCHASE_URL = "https://t.me/xiuren88bot?start=buy_524"

INVITES: dict = {}
FAVORITES: dict = {}

# ========== Helpers ==========

def _now():
    return datetime.now().timestamp()

async def _cleanup_url_store():
    global url_store
    now = _now()
    async with _url_store_lock:
        url_store = {k: v for k, v in url_store.items() if now - v.get("ts", 0) < URL_TTL}

def _cleanup_user_state(user_id):
    if user_id in user_search_state:
        ts = user_search_state[user_id].get("ts", 0)
        if _now() - ts > USER_STATE_TTL:
            del user_search_state[user_id]

async def _cleanup_all():
    now = _now()
    stale_users = [uid for uid, s in user_search_state.items() if now - s.get("ts", 0) > USER_STATE_TTL]
    for uid in stale_users:
        del user_search_state[uid]
    await _cleanup_url_store()
    _clean_expired_vip()
    # Clean stale rate-limit entries
    cutoff = now - RATE_LIMIT_WINDOW * 2
    for uid in list(_user_search_times.keys()):
        _user_search_times[uid] = [t for t in _user_search_times[uid] if t > cutoff]
        if not _user_search_times[uid]:
            del _user_search_times[uid]

def _save_vip():
    try:
        with open(VIP_FILE, "w", encoding="utf-8") as f:
            json.dump(VIP_USERS, f)
    except Exception as e:
        logger.error(f"Failed to save VIP: {e}")

def _load_vip():
    global VIP_USERS
    try:
        if os.path.exists(VIP_FILE):
            with open(VIP_FILE, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                if isinstance(data, list):
                    VIP_USERS = {int(uid): None for uid in data}
                else:
                    VIP_USERS = {int(k): v for k, v in data.items()}
    except Exception as e:
        logger.error(f"Failed to load VIP: {e}")
        VIP_USERS = {}

def _load_users():
    global ALL_USERS
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding="utf-8-sig") as f:
                ALL_USERS = set(json.load(f))
    except Exception:
        ALL_USERS = set()

def _save_users():
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(ALL_USERS), f)
    except Exception:
        pass

def _load_invites():
    global INVITES
    try:
        if os.path.exists(INVITES_FILE):
            with open(INVITES_FILE, "r", encoding="utf-8-sig") as f:
                INVITES = json.load(f)
    except Exception:
        INVITES = {}

def _save_invites():
    try:
        with open(INVITES_FILE, "w", encoding="utf-8") as f:
            json.dump(INVITES, f)
    except Exception:
        pass

def _load_favorites():
    global FAVORITES
    try:
        if os.path.exists(FAVORITES_FILE):
            with open(FAVORITES_FILE, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
                FAVORITES = {int(k): v for k, v in raw.items()}
    except Exception:
        FAVORITES = {}

def _save_favorites():
    try:
        with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
            json.dump(FAVORITES, f, ensure_ascii=False)
    except Exception:
        pass


def _load_cards() -> dict:
    try:
        if os.path.exists(CARD_FILE):
            with open(CARD_FILE, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                if data:
                    return data
    except Exception:
        pass
    logger.info("Seeding cards from built-in list")
    try:
        with open(CARD_FILE, "w", encoding="utf-8") as f:
            json.dump(SEED_CARDS, f, ensure_ascii=False)
    except Exception:
        pass
    return dict(SEED_CARDS)

def _save_cards(cards: dict):
    try:
        with open(CARD_FILE, "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save cards: {e}")

async def _store_url(url, **kwargs):
    global url_counter
    async with _url_counter_lock:
        url_counter += 1
        key = str(url_counter)
    async with _url_store_lock:
        entry = {"url": url, "ts": _now()}
        entry.update(kwargs)
        url_store[key] = entry
        if url_counter % 1000 == 0:
            await _cleanup_url_store()
    return key

def _get_url(key):
    entry = url_store.get(key)
    if not entry:
        return ""
    if _now() - entry.get("ts", 0) > URL_TTL:
        return ""
    return entry["url"]

async def _check_rate_limit(user_id: int) -> bool:
    now = _now()
    cutoff = now - RATE_LIMIT_WINDOW
    async with _user_search_lock:
        times = _user_search_times[user_id]
        _user_search_times[user_id] = [t for t in times if t > cutoff]
        current_count = len(_user_search_times[user_id])
        if current_count >= RATE_LIMIT_MAX:
            return False
        _user_search_times[user_id].append(now)
        return True

def _parse_count_from_title(title):
    m = re.search(r"(\d+)\s*photos?", title, re.IGNORECASE)
    if m: return int(m.group(1))
    m = re.search(r"(\d+)\s*[pP张]", title)
    if m: return int(m.group(1))
    return 0

def _clean_title(title):
    title = re.sub(r"\s*\[\d+[^\]]*(?:MB|GB|photos?|张|P\b)[^\]]*\]", "", title)
    title = re.sub(r"\s*f:[a-z ]+$", "", title)
    title = title.replace("·", " ").replace("•", " ").replace("・", " ")
    title = re.sub(r" {2,}", " ", title)
    title = title.strip(" -|/\t\n\r")
    return title

def _is_vip(user_id):
    if user_id not in VIP_USERS:
        return False
    expiry = VIP_USERS[user_id]
    if expiry is None:
        return True
    if _now() > expiry:
        return False  # expired, cleaned by periodic task
    return True

def _clean_expired_vip():
    """Remove expired VIP users. Called by periodic cleanup only."""
    now = _now()
    expired = [uid for uid, exp in list(VIP_USERS.items()) if exp is not None and now > exp]
    if expired:
        for uid in expired:
            del VIP_USERS[uid]
        _save_vip()

def _parse_date_for_sort(date_str):
    if not date_str:
        return ""
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", date_str)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""

async def _send_or_edit(msg_or_query, text, reply_markup=None, parse_mode="HTML"):
    try:
        if isinstance(msg_or_query, Message):
            await msg_or_query.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await msg_or_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        err_str = str(e)
        if "not modified" not in err_str.lower():
            logger.warning(f"_send_or_edit failed: {err_str}")

async def _safe_search_wrapper(name, coro):
    try:
        return await asyncio.wait_for(coro, timeout=SEARCH_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning(f"{name} search timed out after {SEARCH_TIMEOUT}s")
        return []
    except Exception as e:
        logger.error(f"{name} search error: {e}")
        return []

# ========== Start Menu ==========

START_TEXT = """<b>✨ 美少女图集搜索姬 ✨</b>

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

VIP_TEXT = """<b>👑 VIP 会员说明</b>

🎯 <b>VIP 特权：</b>
• 无限次搜索
• 查看完整大图集
• 翻页浏览所有图片
• 收藏喜欢的图集
• 优先体验新功能

🚧 功能开发中，敬请期待～"""

# ========== Commands ==========

async def cmd_start(update, context):
    user_id = update.effective_user.id
    user_waiting_search.discard(user_id)
    user_waiting_card.discard(user_id)
    if user_id not in ALL_USERS:
        ALL_USERS.add(user_id)
        _save_users()
        # Check invite: if started with /start INVITE_CODE, grant reward
        if context.args:
            code = context.args[0]
            inviter = INVITES.get(code)
            if inviter and int(inviter) != user_id:
                # Grant 1 day VIP to inviter
                existing = VIP_USERS.get(int(inviter))
                if existing is not None:
                    VIP_USERS[int(inviter)] = max(existing or _now(), _now()) + _ONE_DAY
                else:
                    if _is_vip(int(inviter)):
                        VIP_USERS[int(inviter)] = max(VIP_USERS.get(int(inviter), _now()), _now()) + _ONE_DAY
                    else:
                        VIP_USERS[int(inviter)] = _now() + _ONE_DAY
                _save_vip()
                try:
                    await context.bot.send_message(
                        chat_id=int(inviter),
                        text=f"🎉 恭喜！你邀请的用户已加入～\nVIP 已延长 1 天！"
                    )
                except Exception:
                    pass
    await update.message.reply_text(START_TEXT, reply_markup=START_KEYBOARD, parse_mode="HTML")
    await update.message.reply_text("💕 使用下方快捷按钮操作～", reply_markup=MENU_KEYBOARD)

async def cmd_setvip(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("用法: /setvip <用户ID> [天数]\n例如: /setvip 123456 30")
        return
    try:
        target = int(context.args[0])
        days = int(context.args[1]) if len(context.args) > 1 else 0
        if days > 0:
            VIP_USERS[target] = _now() + days * 86400
            await update.message.reply_text(f"✅ 已将用户 {target} 设为VIP（{days}天）")
        else:
            VIP_USERS[target] = None
            await update.message.reply_text(f"✅ 已将用户 {target} 设为永久VIP")
        _save_vip()
        logger.info(f"VIP added: {target}")
    except ValueError:
        await update.message.reply_text("用户ID必须是数字")

async def cmd_admin(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    args = context.args
    if args and args[0] == "setvip" and len(args) > 1:
        try:
            target = int(args[1])
            days = int(args[2]) if len(args) > 2 else 0
            if days > 0:
                VIP_USERS[target] = _now() + days * 86400
                await update.message.reply_text(f"✅ 已将用户 {target} 设为VIP（{days}天）")
            else:
                VIP_USERS[target] = None
                await update.message.reply_text(f"✅ 已将用户 {target} 设为永久VIP")
            _save_vip()
        except ValueError:
            await update.message.reply_text("用户ID必须是数字")
        return

    _load_vip()
    now = _now()
    expired = [uid for uid, exp in list(VIP_USERS.items()) if exp is not None and now > exp]
    for uid in expired:
        del VIP_USERS[uid]
    if expired:
        _save_vip()
    total_vip = len(VIP_USERS)
    permanent = sum(1 for v in VIP_USERS.values() if v is None)
    timed = total_vip - permanent
    cards = _load_cards()
    total_cards = len(cards)
    used_cards = sum(1 for c in cards.values() if c.get("used"))

    from scraper import gallery_clicks, keyword_popularity
    regular_users = [uid for uid in ALL_USERS if uid not in VIP_USERS]
    vip_users_list = [uid for uid in VIP_USERS if uid not in ADMIN_IDS]

    # Dashboard stats
    stats_text = (
        "📊 <b>管理员面板</b>\n\n"
        f"👥 总用户: {len(ALL_USERS)}\n"
        f"   普通用户: {len(regular_users)}\n"
        f"   VIP用户: {total_vip} ({permanent}永久 + {timed}限时)\n\n"
        f"🔑 卡密: 已用{used_cards}/总计{total_cards}\n"
        f"🔍 搜索热词: {len(keyword_popularity)}\n"
        f"📈 点击记录: {len(gallery_clicks)}\n"
        f"🔗 邀请码: {len(INVITES)}"
    )

    # Weekly trends
    stats_text += "\n\n<b>📅 最近7天趋势:</b>\n"
    stats_text += f"  VIP到期(7天内): {sum(1 for v in VIP_USERS.values() if v is not None and 0 < v - now < 7*86400)}\n"

    if vip_users_list:
        stats_text += "\n\n<b>👑 VIP用户:</b>\n"
        for uid in vip_users_list[:5]:
            exp = VIP_USERS.get(uid)
            exp_str = "永久" if exp is None else datetime.fromtimestamp(exp).strftime("%m-%d")
            stats_text += f"  • {uid} ({exp_str})\n"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 设置VIP用户", callback_data="admin_setvip_prompt")],
        [InlineKeyboardButton("🔫 生成卡密", callback_data="admin_gencode")],
        [InlineKeyboardButton("📥 导出卡密TXT", callback_data="admin_exportcards")],
        [InlineKeyboardButton("🔍 查看全部用户", callback_data="admin_listusers")],
    ])
    await update.message.reply_text(stats_text, parse_mode="HTML", reply_markup=keyboard)

async def cmd_stats(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    _load_vip()
    total_vip = len(VIP_USERS)
    permanent = sum(1 for v in VIP_USERS.values() if v is None)
    timed = total_vip - permanent
    cards = _load_cards()
    total_cards = len(cards)
    used_cards = sum(1 for c in cards.values() if c.get("used"))
    from scraper import gallery_clicks, keyword_popularity
    stats = (
        "📊 <b>统计数据</b>\n\n"
        f"👥 用户: {len(ALL_USERS)} (普通 {len(ALL_USERS - set(VIP_USERS.keys()))})\n"
        f"👑 VIP: {total_vip} ({permanent}永久 + {timed}限时)\n"
        f"🔑 卡密: 已用{used_cards}/总计{total_cards}\n"
        f"🔍 搜索热词: {len(keyword_popularity)}\n"
        f"📈 点击记录: {len(gallery_clicks)}\n"
    )
    await update.message.reply_text(stats, parse_mode="HTML")

async def cmd_my(update, context):
    user_id = update.effective_user.id
    if _is_vip(user_id):
        expiry = VIP_USERS.get(user_id)
        if expiry is None:
            info = "永久会员 ♾️"
        else:
            exp_str = datetime.fromtimestamp(expiry).strftime("%Y年%m月%d日")
            remaining = max(0, int((expiry - _now()) / 86400))
            info = f"到期：{exp_str}  (剩{remaining}天)"
        # First check invite info
        my_invites = [code for code, inviter in INVITES.items() if inviter == str(user_id)]
        inv_text = f"\n\n🔗 你的邀请码: <code>{my_invites[0]}</code>\n发送: /start {my_invites[0]} 给好友" if my_invites else ""
        await update.message.reply_text(
            f"👑 <b>你的VIP信息</b>\n\n{info}{inv_text}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⭐ 收藏夹", callback_data="fav_list")],
                [InlineKeyboardButton("🔗 生成邀请码", callback_data="invite_gen")],
                [InlineKeyboardButton("🔑 续费/升级", callback_data="vip_activate")],
                [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")],
            ]))
    else:
        await update.message.reply_text(
            "👑 <b>VIP会员</b>\n\n你还不是VIP会员哦～\n开通后可以：\n• 查看全部搜索结果\n• 翻页浏览所有图片\n• 收藏喜欢的图集",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔑 输入卡密激活", callback_data="vip_activate")],
                [InlineKeyboardButton("💳 购买卡密", url=PURCHASE_URL)],
                [InlineKeyboardButton("🔗 邀请好友得VIP", callback_data="invite_info")],
                [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")],
            ]))

async def cmd_help(update, context):
    await update.message.reply_text(
        "<b>📖 使用帮助</b>\n\n"
        "点击「🔍 搜索图集」后直接输入关键词即可\n"
        "/search 关键词 - 快速搜索\n"
        "/random - 随机推荐\n"
        "/my - 查看VIP & 邀请\n"
        "/start - 回到主菜单",
        parse_mode="HTML"
    )

async def cmd_search(update, context):
    user_id = update.effective_user.id
    if not context.args:
        user_waiting_search.add(user_id)
        from scraper import get_hot_keywords
        hot = await get_hot_keywords(top_n=8)
        buttons = []
        row = []
        for kw in hot:
            row.append(InlineKeyboardButton(kw, callback_data=f"hot_{html.escape(kw)}"))
            if len(row) >= 4:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        buttons.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")])
        await update.message.reply_text(
            "🔍 请直接输入搜索关键词～\n\n🔥 <b>热门搜索：</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons))
        return
    keyword = " ".join(context.args)
    await _do_search(update, keyword)

async def cmd_random(update, context):
    user_id = update.effective_user.id
    user_waiting_search.discard(user_id)
    msg = await update.message.reply_text("🎲 正在随机推荐...")
    try:
        gallery = await get_random_gallery()
    except Exception as e:
        logger.error(f"Random error: {traceback.format_exc()}")
        await _send_or_edit(msg, "😔 获取随机推荐失败，请稍后再试。")
        return
    if not gallery:
        await _send_or_edit(msg, "😔 获取随机推荐失败，请稍后再试。")
        return
    await msg.delete()
    await _route_random_gallery(update, gallery)

# ========== Handle Text ==========

async def handle_text(update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Admin setting VIP user via text input
    if user_id in admin_setvip_state and user_id in ADMIN_IDS:
        del admin_setvip_state[user_id]
        try:
            parts = text.split()
            target_id = int(parts[0])
            days = int(parts[1]) if len(parts) > 1 else 0
            if days > 0:
                VIP_USERS[target_id] = _now() + days * 86400
                label = f"{days}天"
            else:
                VIP_USERS[target_id] = None
                label = "永久"
            _save_vip()
            if target_id not in ALL_USERS:
                ALL_USERS.add(target_id)
                _save_users()
            await update.message.reply_text(
                f"✅ 已将用户 <code>{target_id}</code> 设置为VIP（{label}）",
                parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ 请输入有效的用户ID（数字）")
        return

    if text == "🔍 搜索":
        user_waiting_search.add(user_id)
        from scraper import get_hot_keywords
        hot = await get_hot_keywords(top_n=8)
        buttons = []
        row = []
        for kw in hot:
            row.append(InlineKeyboardButton(kw, callback_data=f"hot_{html.escape(kw)}"))
            if len(row) >= 4:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        buttons.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")])
        await update.message.reply_text(
            "🔍 请直接输入搜索关键词～\n\n🔥 <b>热门搜索：</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons))
        return
    elif text == "🎲 推荐":
        await cmd_random(update, context)
        return
    elif text == "👑 VIP":
        if _is_vip(user_id):
            await update.message.reply_text(
                "<b>👑 你已是VIP会员</b>\n\n🎉 享受所有特权～",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
                ]]))
        else:
            await update.message.reply_text(VIP_TEXT, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔑 输入卡密激活", callback_data="vip_activate")],
                    [InlineKeyboardButton("💳 购买卡密", url=PURCHASE_URL)],
                    [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")]
                ]))
        return
    elif text == "👤 我的":
        await cmd_my(update, context)
        return
    elif text == "📖 帮助":
        await cmd_help(update, context)
        return

    # Card activation flow
    if user_id in user_waiting_card:
        user_waiting_card.discard(user_id)
        if not _is_vip(user_id) and not await _check_rate_limit(user_id):
            await update.message.reply_text("⏱ 操作太频繁，请稍后再试。")
            return
        card_code = text.strip()
        cards = _load_cards()
        if card_code in cards:
            if cards[card_code].get("used"):
                await update.message.reply_text("❌ 该卡密已被使用过。")
            else:
                if _is_vip(user_id):
                    await update.message.reply_text(
                        "❗ 你已经是VIP会员了。如需续费请使用新卡密。",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
                        ]]))
                    return
                card_type = cards[card_code].get("type", "forever")
                days = {"month": 30, "quarter": 90, "year": 360, "forever": None, "trial": 1}
                day_names = {"month": "月卡(30天)", "quarter": "季卡(90天)", "year": "年卡(360天)", "forever": "永久", "trial": "体验卡(1天)"}
                d = days.get(card_type, None)
                expiry = None if d is None else _now() + d * 86400
                cards[card_code]["used"] = True
                cards[card_code]["used_by"] = user_id
                cards[card_code]["activated_at"] = _now()
                _save_cards(cards)
                VIP_USERS[user_id] = expiry
                _save_vip()
                name = day_names.get(card_type, card_type)
                if d:
                    exp_str = datetime.fromtimestamp(expiry).strftime("%Y-%m-%d")
                    msg = f"✅ 卡密激活成功！\n\n类型：{name}\n到期：{exp_str}\n\n返回主菜单即可享受VIP特权！"
                else:
                    msg = f"✅ 卡密激活成功！\n\n类型：{name}\n\n返回主菜单即可享受VIP特权！"
                await update.message.reply_text(msg,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
                    ]]))
        else:
            await update.message.reply_text(
                "❌ 卡密无效，请检查后重试。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔑 重新输入", callback_data="vip_activate"),
                    InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
                ]]))
        return

    # Default: any other text → treat as search keyword
    if user_id in user_waiting_search:
        user_waiting_search.discard(user_id)
    elif user_id in user_waiting_card:
        user_waiting_card.discard(user_id)
        await update.message.reply_text(
            "❌ 卡密无效，请检查后重试。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔑 重新输入", callback_data="vip_activate"),
                InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
            ]]))
        return
    keyword = text
    if not keyword:
        return
    await _do_search(update, keyword)

# ========== Search ==========

async def _do_search(update, keyword):
    msg = update.message
    loading = await msg.reply_text("🔍 正在搜索中，请稍候...")
    user_id = update.effective_user.id
    if not _is_vip(user_id) and not await _check_rate_limit(user_id):
        await loading.delete()
        await msg.reply_text("⏱ 搜索太频繁了，请稍后再试～",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
            ]]))
        return
    await _run_search_and_display(msg, keyword, user_id, loading)

async def _do_search_callback(query, keyword):
    user_id = query.from_user.id
    msg = query.message
    loading = await msg.reply_text("🔍 正在搜索中，请稍候...")
    await _run_search_and_display(msg, keyword, user_id, loading, query)

async def _run_search_and_display(msg, keyword, user_id, loading, query=None):
    hd_task = asyncio.create_task(_safe_search_wrapper("4KHD", search_galleries(keyword, max_results=config.MAX_SEARCH_RESULTS)))
    xc_task = asyncio.create_task(_safe_search_wrapper("XChina", search_xchina(keyword, max_results=config.MAX_SEARCH_RESULTS)))
    eh_task = asyncio.create_task(_safe_search_wrapper("EH", search_ehentai(keyword, max_results=config.MAX_SEARCH_RESULTS))) if EH_ENABLED else None
    tasks = [hd_task, xc_task]
    if eh_task: tasks.append(eh_task)
    await asyncio.gather(*tasks)
    hd_results = hd_task.result()
    xc_results = xc_task.result()
    eh_results = eh_task.result() if eh_task else []
    merged = hd_results + xc_results + eh_results
    merged.sort(key=lambda r: _parse_date_for_sort(r.get('publish_date', '')), reverse=True)
    try:
        await loading.delete()
    except Exception:
        pass
    if not merged:
        from scraper import get_hot_keywords
        hot = await get_hot_keywords(top_n=5)
        suggest_btns = [[InlineKeyboardButton(kw, callback_data=f"hot_{html.escape(kw)}")] for kw in hot]
        suggest_btns.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")])
        await msg.reply_text(
            f"😔 没有找到「{html.escape(keyword)}」相关图集\n\n🔥 试试热门搜索：",
            reply_markup=InlineKeyboardMarkup(suggest_btns))
        return
    user_search_state[user_id] = {"page": 0, "keyword": keyword, "results": merged, "ts": _now()}
    await _show_results_page(query if query else msg, user_id)

# ========== Menu Handlers ==========

async def _handle_menu_search(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    user_waiting_search.add(user_id)
    from scraper import get_hot_keywords
    hot = await get_hot_keywords(top_n=8)
    buttons = []
    row = []
    for kw in hot:
        row.append(InlineKeyboardButton(kw, callback_data=f"hot_{html.escape(kw)}"))
        if len(row) >= 4:
            buttons.append(row)
            row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")])
    await query.edit_message_text(
        "🔍 请直接输入搜索关键词～\n\n🔥 <b>热门搜索：</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons))

async def _route_random_gallery(update, gallery):
    url = gallery.get("url", "")
    source = gallery.get("source", "")
    pd = gallery.get("publish_date", "")
    if source == "ehentai" or "e-hentai.org" in url:
        await _send_eh_detail(update, url, publish_date=pd, from_random=True)
    elif source == "xchina" or "xchina.co" in url or "/photo/id-" in url:
        await _send_xchina_detail(update, url, author=gallery.get("author", ""), publish_date=pd, from_random=True)
    else:
        await _send_gallery_detail(update, url, from_random=True)

async def _handle_random_next(update, context):
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    msg = await update.effective_message.reply_text("🎲 正在为你随机推荐...")
    try:
        gallery = await get_random_gallery()
    except Exception:
        await _send_or_edit(msg, "😔 获取随机推荐失败，请稍后再试。")
        return
    if not gallery:
        await _send_or_edit(msg, "😔 获取随机推荐失败，请稍后再试。")
        return
    await msg.delete()
    await _route_random_gallery(update, gallery)

async def _handle_menu_random(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    user_waiting_search.discard(user_id)
    await query.edit_message_text("🎲 正在为你随机推荐...")
    try:
        gallery = await get_random_gallery()
    except Exception:
        await query.edit_message_text("😔 获取随机推荐失败，请稍后再试。")
        return
    if not gallery:
        await query.edit_message_text("😔 获取随机推荐失败，请稍后再试。")
        return
    await _route_random_gallery(update, gallery)

async def _handle_menu_vip(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    if _is_vip(user_id):
        await query.edit_message_text(
            "<b>👑 你已是VIP会员</b>\n\n🎉 享受所有特权～",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
            ]]))
        return
    await query.edit_message_text(VIP_TEXT, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 输入卡密激活", callback_data="vip_activate")],
            [InlineKeyboardButton("💳 购买卡密", url=PURCHASE_URL)],
            [InlineKeyboardButton("🔗 邀请好友得VIP", callback_data="invite_info")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")]
        ]))

async def _handle_menu_home(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    user_waiting_search.discard(user_id)
    user_waiting_card.discard(user_id)
    try:
        await query.edit_message_text(START_TEXT, reply_markup=START_KEYBOARD, parse_mode="HTML")
    except Exception:
        try: await query.delete_message()
        except Exception: pass
        await query.message.reply_text(START_TEXT, reply_markup=START_KEYBOARD, parse_mode="HTML")

# ========== Main Callback Handler ==========

async def handle_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"Callback: user={user_id} data={data[:80]}")

    try:
        if data == "menu_search":
            await _handle_menu_search(update, context)
        elif data == "menu_random":
            await _handle_menu_random(update, context)
        elif data == "random_next":
            await _handle_random_next(update, context)
        elif data == "menu_vip":
            await _handle_menu_vip(update, context)
        elif data == "menu_help":
            await query.edit_message_text(
                "<b>📖 使用帮助</b>\n\n"
                "🔍 <b>搜索图集</b> — 点击后直接输入关键词\n"
                "🎲 <b>随机推荐</b> — 每日新鲜图集随机推荐\n"
                "👑 <b>VIP会员</b> — 解锁无限搜索、完整图集浏览\n"
                "👤 <b>我的VIP</b> — 查看会员状态、续费\n"
                "🔗 <b>邀请好友</b> — 生成邀请码，好友加入双方各得VIP\n\n"
                "<b>快捷命令：</b>\n"
                "/search 关键词 — 快速搜索\n"
                "/random — 随机推荐\n"
                "/my — 查看VIP\n"
                "/start — 返回主菜单",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
                ]]))
        elif data == "menu_home":
            await _handle_menu_home(update, context)
        elif data == "noop":
            return
        # Invite flows
        elif data == "invite_gen":
            code = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
            INVITES[code] = str(user_id)
            _save_invites()
            await query.edit_message_text(
                f"🔗 <b>你的专属邀请码</b>\n\n<code>{code}</code>\n\n"
                f"好友通过 @{context.bot.username}?start={code} 加入后，你获得 <b>1天VIP</b>！\n\n"
                f"直接分享：\nhttps://t.me/{context.bot.username}?start={code}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
                ]]))
        elif data == "invite_info":
            await query.edit_message_text(
                "🔗 <b>邀请好友得VIP</b>\n\n"
                "每成功邀请一位新用户加入，你获得 <b>1天VIP</b>！\n\n"
                "方法：\n1. 生成邀请码\n2. 分享给好友\n3. 好友点击链接开始使用\n\n"
                "👑 VIP用户才能生成邀请码哦～",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 生成邀请码" if _is_vip(user_id) else "👑 开通VIP", callback_data="invite_gen" if _is_vip(user_id) else "menu_vip")],
                    [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")]
                ]))
        elif data == "vip_activate":
            user_waiting_card.add(user_id)
            await query.edit_message_text(
                "🔑 请输入你的卡密：\n\n格式：直接输入卡密即可",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
                ]]))
        elif data.startswith("hot_"):
            kw = data[4:]
            user_waiting_search.discard(user_id)
            await _do_search_callback(query, kw)
        elif data.startswith("p_"):
            page = int(data.split("_")[1])
            state = user_search_state.get(user_id)
            if not state:
                await query.edit_message_text("⏳ 会话已过期，请重新搜索。")
                return
            state["page"] = page
            await _show_results_page(query, user_id)
        elif data.startswith("d_"):
            url = _get_url(data[2:])
            if not url:
                await query.edit_message_text("⏳ 链接已过期，请重新搜索。")
                return
            loading_msg = await query.message.reply_text("⏳ 正在获取图集详情，请稍候...")
            await _send_gallery_detail(update, url)
            try: await loading_msg.delete()
            except Exception: pass
        elif data.startswith("x_"):
            url = _get_url(data[2:])
            if not url:
                await query.edit_message_text("❌ 链接已过期，请重新搜索。")
                return
            loading_msg = await query.message.reply_text("⏳ 正在获取图集详情...")
            entry = url_store.get(data[2:])
            await _send_xchina_detail(update, url, author=entry.get("author", ""), publish_date=entry.get("publish_date", ""))
            try: await loading_msg.delete()
            except Exception: pass
        elif data.startswith("e_"):
            url = _get_url(data[2:])
            if not url:
                await query.edit_message_text("❌ 链接已过期")
                return
            loading_msg = await query.message.reply_text("⏳ 正在获取图集详情，请稍候...")
            await _send_eh_detail(update, url)
            try: await loading_msg.delete()
            except Exception: pass
        elif data.startswith("m_"):
            url = _get_url(data[2:])
            if not url:
                await query.answer("❌ 链接已过期", show_alert=True)
                return
            if not _is_vip(user_id):
                await query.answer("👑 请先开通VIP会员", show_alert=True)
                return
            await query.answer()
            loading_msg = await query.message.reply_text("🧲 正在获取磁力链接...")
            magnet = await get_eh_magnet(url)
            await loading_msg.delete()
            if magnet:
                await query.message.reply_text(f"🧲 <b>磁力链接</b>\n\n<code>{magnet}</code>", parse_mode="HTML")
            else:
                await query.message.reply_text("❌ 该图集暂无磁力链接")
        elif data.startswith("f_"):
            url = _get_url(data[2:])
            if not url:
                await query.message.reply_text("⏳ 链接已过期，请重新搜索。")
                return
            loading_msg = await query.message.reply_text("⏳ 正在加载图片，请稍候...")
            await _send_gallery_full(update, url)
            try: await loading_msg.delete()
            except Exception: pass
        elif data.startswith("g_"):
            payload = data[2:]
            underscore_pos = payload.rfind("_")
            if underscore_pos == -1:
                url_key = payload; page = 0
            else:
                url_key = payload[:underscore_pos]
                try: page = int(payload[underscore_pos + 1:])
                except ValueError: page = 0
            url = _get_url(url_key)
            if not url:
                await query.message.reply_text("⏳ 链接已过期。")
                return
            if not _is_vip(user_id):
                await query.answer("👑 请先开通VIP会员", show_alert=True)
                return
            loading_msg = await query.message.reply_text(f"⏳ 正在加载第{page+1}页，请稍候...")
            await _send_gallery_page(update, url, page)
            try: await loading_msg.delete()
            except Exception: pass
        elif data == "vip_upgrade":
            if _is_vip(user_id):
                await query.edit_message_text("<b>👑 你已是VIP会员</b>\n\n🎉 享受所有特权～", parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
                    ]]))
            else:
                await query.edit_message_text(VIP_TEXT, parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔑 输入卡密激活", callback_data="vip_activate")],
                        [InlineKeyboardButton("💳 购买卡密", url=PURCHASE_URL)],
                        [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")]
                    ]))
        # Favorites
        elif data.startswith("fav_"):
            if data == "fav_list":
                favs = FAVORITES.get(user_id, [])
                if not favs:
                    await query.edit_message_text("⭐ <b>收藏夹</b>\n\n还没有收藏任何图集哦～",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
                        ]]))
                else:
                    fav_text = "⭐ <b>收藏夹</b>\n\n"
                    fav_buttons = []
                    for i, f in enumerate(favs[-20:]):
                        fav_text += f"{i+1}. {html.escape(f['title'][:40])}\n"
                        fav_buttons.append([InlineKeyboardButton(
                            f"{i+1}. {f['title'][:35]}",
                            url=f['url'] if f['source'] != '4khd' else f['url'],
                            callback_data=f"noop"
                        )])
                    fav_buttons.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")])
                    await query.edit_message_text(fav_text, parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(fav_buttons))
            elif data.startswith("fav_add_"):
                entry = url_store.get(data[8:])
                if entry:
                    if user_id not in FAVORITES:
                        FAVORITES[user_id] = []
                    # Check duplicate
                    target_url = entry.get("url", "")
                    if not any(f["url"] == target_url for f in FAVORITES[user_id]):
                        FAVORITES[user_id].append({
                            "title": entry.get("title", "Unknown"),
                            "url": target_url,
                            "source": entry.get("source", ""),
                            "added_at": _now()
                        })
                        _save_favorites()
                        await query.answer("⭐ 已收藏", show_alert=True)
                    else:
                        await query.answer("⭐ 已收藏过", show_alert=True)
        # Admin flows
        elif data == "admin_gencode":
            if user_id not in ADMIN_IDS:
                await query.answer("❌ 无权限", show_alert=True)
                return
            cards = _load_cards()
            generated = []
            types = [
                ("📅 月卡(Y)", "month", 30),
                ("📅 季卡(J)", "quarter", 90),
                ("📅 年卡(N)", "year", 360),
                ("📅 永久(S)", "forever", 0),
            ]
            for label, tname, days_val in types:
                prefix_map = {"month": "Y", "quarter": "J", "year": "N", "forever": "S"}
                prefix = prefix_map[tname]
                for _ in range(10):
                    code = prefix + "-" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
                    cards[code] = {"used": False, "used_by": None, "used_at": None, "type": tname, "days": days_val, "created_by": user_id}
                    generated.append(code)
            _save_cards(cards)
            gen_lines = ["🔫 <b>已生成 40 张卡密</b>", ""]
            for label, tname, days_val in types:
                prefix = {"month": "Y", "quarter": "J", "year": "N", "forever": "S"}[tname]
                type_codes = [c for c in generated if c.startswith(prefix)]
                gen_lines.append(f"{label}: {len(type_codes)}张")
            gen_lines.append("")
            gen_lines.append("点击下方导出全部卡密TXT")
            gen_text = "\n".join(gen_lines)
            await query.edit_message_text(gen_text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📥 导出卡密TXT", callback_data="admin_exportcards")],
                    [InlineKeyboardButton("⬅️ 返回管理员面板", callback_data="admin_back")]
                ]))
        elif data == "admin_exportcards":
            if user_id not in ADMIN_IDS:
                await query.answer("❌ 无权限", show_alert=True)
                return
            cards = _load_cards()
            lines = []
            for code, info in cards.items():
                if not info.get("used"):
                    t = info.get("type", "?")
                    type_names = {"month": "月卡", "quarter": "季卡", "year": "年卡", "forever": "永久", "trial": "体验卡"}
                    lines.append(f"{code}  [{type_names.get(t, t)}]")
            if lines:
                txt_content = "\n".join(lines)
                if len(txt_content) > 4000:
                    txt_content = txt_content[:4000] + "\n... 已截断"
                await query.message.reply_text(
                    f"<b>📥 未使用卡密 ({len(lines)}张)</b>\n\n<code>{html.escape(txt_content)}</code>",
                    parse_mode="HTML")
            else:
                await query.answer("没有未使用的卡密", show_alert=True)
        elif data == "admin_back":
            if user_id not in ADMIN_IDS: return
            total_vip = len(VIP_USERS)
            permanent = sum(1 for v in VIP_USERS.values() if v is None)
            timed = total_vip - permanent
            cards = _load_cards()
            total_cards = len(cards)
            used_cards = sum(1 for c in cards.values() if c.get("used"))
            from scraper import gallery_clicks, keyword_popularity
            regular_users = [uid for uid in ALL_USERS if uid not in VIP_USERS]
            vip_users_list = [uid for uid in VIP_USERS if uid not in ADMIN_IDS]
            now = _now()
            stats_text = (
                "📊 <b>管理员面板</b>\n\n"
                f"👥 总用户: {len(ALL_USERS)}\n"
                f"   普通用户: {len(regular_users)}\n"
                f"   VIP用户: {total_vip} ({permanent}永久 + {timed}限时)\n\n"
                f"🔑 卡密: 已用{used_cards}/总计{total_cards}\n"
                f"🔍 搜索热词: {len(keyword_popularity)}\n"
                f"📈 点击记录: {len(gallery_clicks)}\n"
                f"🔗 邀请码: {len(INVITES)}\n\n"
                f"📅 VIP到期(7天内): {sum(1 for v in VIP_USERS.values() if v is not None and 0 < v - now < 7*86400)}"
            )
            await query.edit_message_text(stats_text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ 设置VIP用户", callback_data="admin_setvip_prompt")],
                    [InlineKeyboardButton("🔫 生成卡密", callback_data="admin_gencode")],
                    [InlineKeyboardButton("📥 导出卡密TXT", callback_data="admin_exportcards")],
                    [InlineKeyboardButton("🔍 查看全部用户", callback_data="admin_listusers")],
                ]))
        elif data == "admin_setvip_prompt":
            if user_id not in ADMIN_IDS:
                await query.answer("❌ 无权限", show_alert=True)
                return
            admin_setvip_state[user_id] = True
            await query.edit_message_text(
                "✅ 请输入要设置为VIP的用户ID：\n\n格式: <用户ID> [天数]\n例如: 123456789 30\n不写天数则为永久",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ 取消", callback_data="admin_back")
                ]]))
        elif data == "admin_listusers":
            if user_id not in ADMIN_IDS: return
            vip_data = [(uid, VIP_USERS[uid]) for uid in VIP_USERS if uid not in ADMIN_IDS]
            regular = [uid for uid in ALL_USERS if uid not in VIP_USERS]
            text = "📋 <b>全部用户列表</b>\n\n"
            text += f"👑 <b>VIP用户 ({len(vip_data)}):</b>\n"
            if vip_data:
                for uid, exp in vip_data:
                    if exp is None: exp_str = "永久"
                    else:
                        rem = max(0, int((exp - _now()) / 86400))
                        exp_str = f"剩{rem}天"
                    text += f"  • <code>{uid}</code> - {exp_str}\n"
            else: text += "  暂无\n"
            text += f"\n👥 <b>普通用户 ({len(regular)}):</b>\n"
            if regular:
                for uid in regular:
                    text += f"  • <code>{uid}</code>\n"
            else: text += "  暂无\n"
            if len(text) > 4000:
                text = text[:4000] + "\n\n... 列表过长已截断"
            await query.edit_message_text(text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ 返回管理员面板", callback_data="admin_back")
                ]]))
    except Exception as e:
        logger.error(f"Callback error: {traceback.format_exc()}")
        try: await query.edit_message_text("操作失败，请重试。")
        except Exception: pass

# ========== Display ==========

async def _show_results_page(msg_or_query, user_id):
    state = user_search_state.get(user_id)
    if not state: return
    results = state["results"]
    page = state["page"]
    keyword = state["keyword"]
    total = len(results)
    full_pages = max(1, (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)
    is_vip = _is_vip(user_id)
    max_accessible_pages = full_pages if is_vip else min(full_pages, 2)
    start = page * RESULTS_PER_PAGE
    end = min(start + RESULTS_PER_PAGE, total)
    page_results = results[start:end]
    if not is_vip and full_pages > 2:
        text = f"🔍 <b>{html.escape(keyword)}</b> 共 {total} 个结果（第{page+1}/{full_pages}页）\n\n👑 开通VIP可查看全部{total}条结果\n\n"
    else:
        text = f"🔍 <b>{html.escape(keyword)}</b> 共 {total} 个结果（第{page+1}/{full_pages}页）\n\n"
    buttons = []
    for i, r in enumerate(page_results):
        idx = start + i + 1
        raw_title = r["title"]
        author = r.get("author", "")
        publish_date = r.get("publish_date", "")
        if author and author not in raw_title:
            display_title = f"{author} - {_clean_title(raw_title)}"
        else:
            display_title = _clean_title(raw_title)
        text += f"{idx}. 📷 {html.escape(display_title)}\n"
        btn_label = display_title[:32] + ".." if len(display_title) > 35 else display_title[:35]
        url_key = await _store_url(r["url"], author=author, publish_date=publish_date,
            title=display_title, source=r.get("source", ""))
        prefix = "e_" if r.get("source") == "ehentai" else ("x_" if r.get("source") == "xchina" else "d_")
        buttons.append([InlineKeyboardButton(f"📷 {idx}. {btn_label}", callback_data=prefix + url_key)])
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"p_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"📋 {page+1}/{full_pages}", callback_data="noop"))
    if page < max_accessible_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"p_{page+1}"))
    buttons.append(nav_buttons)
    if not is_vip and full_pages > 2:
        buttons.append([InlineKeyboardButton("👑 VIP查看全部搜索结果", callback_data="menu_vip")])
    buttons.append([
        InlineKeyboardButton("👑 开通VIP", callback_data="menu_vip"),
        InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home"),
    ])
    await _send_or_edit(msg_or_query, text, reply_markup=InlineKeyboardMarkup(buttons))

async def _send_xchina_detail(update, url, author="", publish_date="", from_random=False):
    user_id = update.effective_user.id
    await track_pre_clicked(user_id)
    try:
        detail = await get_xchina_gallery(url)
    except Exception as e:
        logger.error(f"XC detail error: {traceback.format_exc()}")
        await update.effective_message.reply_text("❌ 获取图集失败，请稍后再试。")
        return
    title = detail.get("title", "Unknown")
    cover = detail.get("cover")
    cover_bytes = detail.get("cover_bytes")
    count = detail.get("count", 0)
    images = detail.get("images", [])
    final_author = author
    final_date = detail.get("publish_date", "") or publish_date
    clean_title = _clean_title(title)
    clean_title = re.sub(r"\s*[-|]\s*XChina.*$", "", clean_title, flags=re.IGNORECASE)
    clean_title = re.sub(r"\s*\([^)]*免费[^)]*\)", "", clean_title)
    clean_title = clean_title.strip()
    display_title = f"{final_author} - {clean_title}" if final_author else clean_title
    text = f"🎀 {html.escape(display_title)}"
    if count: text += f"\n📸 {count}P"
    if final_date: text += f"\n🕐 {final_date}"
    url_key = await _store_url(url, title=display_title, source="xchina")
    buttons = []
    if images:
        buttons.append([InlineKeyboardButton("🖼️ 查看完整图集", callback_data="f_" + url_key)])
    if from_random:
        buttons.append([InlineKeyboardButton("🔄 换一个", callback_data="random_next")])
    if _is_vip(user_id):
        buttons.append([InlineKeyboardButton("⭐ 收藏", callback_data="fav_add_" + url_key)])
    buttons.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")])
    keyboard = InlineKeyboardMarkup(buttons)
    sent = False
    if cover_bytes:
        img_data, img_ct = cover_bytes
        try:
            img_data.seek(0)
            await update.effective_message.reply_photo(photo=img_data, caption=text, reply_markup=keyboard, parse_mode="HTML")
            sent = True
        except Exception:
            logger.error("XC cover send failed: " + traceback.format_exc())
    if not sent and cover:
        try:
            await update.effective_message.reply_photo(photo=cover, caption=text, reply_markup=keyboard, parse_mode="HTML")
            sent = True
        except Exception:
            logger.error("XC cover url send failed: " + traceback.format_exc())
    if not sent:
        await update.effective_message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

async def _send_eh_detail(update, url, publish_date="", from_random=False):
    user_id = update.effective_user.id
    await track_pre_clicked(user_id)
    try:
        detail = await get_eh_gallery(url)
    except Exception:
        logger.error("EH detail error: " + traceback.format_exc())
        await update.effective_message.reply_text("❌ 获取EH图集失败")
        return
    title = detail.get("title", "Unknown")
    cover = detail.get("cover")
    images = detail.get("images", [])
    count = detail.get("count", 0)
    tags = detail.get("tags", [])
    clean_title = _clean_title(title)
    text = f"📖 {html.escape(clean_title)}"
    if count: text += f"\n📸 {count}P"
    if publish_date: text += f"\n🕐 {publish_date}"
    if tags: text += "\n🏷 " + ", ".join(tags[:8])
    url_key = await _store_url(url, title=clean_title, source="ehentai")
    buttons = []
    if images:
        buttons.append([InlineKeyboardButton("🖼️ 查看图集预览", callback_data="f_" + url_key)])
    if from_random:
        buttons.append([InlineKeyboardButton("🔄 换一个", callback_data="random_next")])
    if _is_vip(user_id):
        buttons.append([InlineKeyboardButton("🧲 获取磁力链", callback_data="m_" + url_key)])
        buttons.append([InlineKeyboardButton("⭐ 收藏", callback_data="fav_add_" + url_key)])
    buttons.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")])
    keyboard = InlineKeyboardMarkup(buttons)
    cover_bytes = None
    if cover:
        try:
            async with httpx.AsyncClient(timeout=20, verify=False, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://e-hentai.org/"}) as cl:
                cr = await cl.get(cover)
                if cr.status_code == 200 and len(cr.content) > 1000:
                    cover_bytes = cr.content
                else:
                    logger.warning(f"EH cover bad: status={cr.status_code} size={len(cr.content)}")
        except Exception as ex:
            logger.warning(f"EH cover download failed: {ex}")
    sent = False
    if cover_bytes:
        try:
            await update.effective_message.reply_photo(photo=cover_bytes, caption=text, reply_markup=keyboard, parse_mode="HTML")
            sent = True
        except Exception: pass
    if not sent and cover:
        try:
            await update.effective_message.reply_photo(photo=cover, caption=text, reply_markup=keyboard, parse_mode="HTML")
            sent = True
        except Exception: pass
    if not sent:
        await update.effective_message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

async def _send_gallery_detail(update, url, gallery_data=None, from_random=False):
    user_id = update.effective_user.id
    await track_pre_clicked(user_id)
    logger.info("Fetching gallery: " + url[:80])
    if gallery_data is None:
        try:
            gallery_data = await get_gallery_images(url)
        except Exception:
            logger.error("Gallery fetch error: " + traceback.format_exc())
            await update.effective_message.reply_text("😔 获取图集详情失败，请稍后再试。")
            return
    title = gallery_data["title"]
    cover = gallery_data["cover"]
    cover_bytes = gallery_data.get("cover_bytes")
    publish_date = gallery_data.get("publish_date", "")
    all_images = gallery_data["images"]
    await track_click(url, title)
    original_count = _parse_count_from_title(title)
    display_count = original_count if original_count > 0 else len(all_images)
    clean_title = _clean_title(title)
    text = f"🎀 {html.escape(clean_title)}\n📸 {display_count}张"
    if publish_date: text += f"\n🕐 {publish_date}"
    url_key = await _store_url(url, title=clean_title, source="4khd")
    buttons = [[InlineKeyboardButton("🖼️ 查看完整图集", callback_data="f_" + url_key)]]
    if from_random:
        buttons.append([InlineKeyboardButton("🔄 换一个", callback_data="random_next")])
    if _is_vip(user_id):
        buttons.append([InlineKeyboardButton("⭐ 收藏", callback_data="fav_add_" + url_key)])
    buttons.append([InlineKeyboardButton("🏠 主菜单", callback_data="menu_home")])
    keyboard = InlineKeyboardMarkup(buttons)
    sent = False
    if cover_bytes:
        img_data, img_ct = cover_bytes
        try:
            img_data.seek(0)
            await update.effective_message.reply_photo(photo=img_data, caption=text, reply_markup=keyboard, parse_mode="HTML")
            sent = True
        except Exception:
            logger.error("Cover send failed: " + traceback.format_exc())
    if not sent and cover:
        try:
            await update.effective_message.reply_photo(photo=cover, caption=text, reply_markup=keyboard, parse_mode="HTML")
            sent = True
        except Exception:
            logger.error("Cover url send failed: " + traceback.format_exc())
    if not sent:
        await update.effective_message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

async def _send_gallery_full(update, url):
    user_id = update.effective_user.id
    is_ehentai = "e-hentai.org" in url
    is_xchina = "/photo/id-" in url
    if is_ehentai:
        try:
            max_imgs = 200 if _is_vip(user_id) else config.MAX_IMAGES_PER_POST
            eh_data = await get_eh_gallery(url, max_images=max_imgs)
        except Exception:
            logger.error("EH full gallery error: " + traceback.format_exc())
            await update.effective_message.reply_text("❌ 加载EH图集失败")
            return
        all_images = eh_data["images"]
    elif is_xchina:
        gid = re.search(r"/id-([a-f0-9]+)", url)
        if gid:
            gallery_id = gid.group(1)
            max_imgs = 200 if _is_vip(user_id) else config.MAX_IMAGES_PER_POST
            all_images = [f"https://img.xchina.io/photos/{gallery_id}/{i:05d}_600x0.webp" for i in range(1, max_imgs + 1)]
        else:
            await update.effective_message.reply_text("😔 加载失败，请稍后再试。")
            return
    else:
        try:
            max_imgs = 200 if _is_vip(user_id) else config.MAX_IMAGES_PER_POST
            gallery_data = await get_gallery_images(url, max_pages=20, max_images=max_imgs)
        except Exception:
            logger.error("Full gallery error: " + traceback.format_exc())
            await update.effective_message.reply_text("😔 加载失败，请稍后再试。")
            return
        all_images = gallery_data["images"]
    total_pages = (len(all_images) + 9) // 10
    preview = all_images[:10]
    media = []
    downloaded = 0
    async def _dl_one(img_url):
        async with _download_sem:
            return await download_image(img_url, referer=url)
    tasks = [_dl_one(u) for u in preview]
    results_list = await asyncio.gather(*tasks)
    for result in results_list:
        if result:
            img_data, ct = result
            img_data.seek(0)
            media.append(InputMediaPhoto(media=img_data))
            downloaded += 1
    if media:
        try:
            await update.effective_message.reply_media_group(media=media)
        except Exception:
            logger.error("Media group failed: " + traceback.format_exc())
    url_key = await _store_url(url)
    buttons = []
    if _is_vip(user_id):
        if total_pages > 1:
            buttons.append([InlineKeyboardButton("➡️ 下一页", callback_data=f"g_{url_key}_1")])
    else:
        buttons.append([InlineKeyboardButton("👑 VIP查看完整图集", callback_data="vip_upgrade")])
    buttons.append([InlineKeyboardButton("🏠 主菜单", callback_data="menu_home")])
    keyboard = InlineKeyboardMarkup(buttons)
    await update.effective_message.reply_text(f"📸 第1/{total_pages}页（{downloaded}张）", reply_markup=keyboard)

async def _send_gallery_page(update, url, page=0):
    user_id = update.effective_user.id
    if not _is_vip(user_id): return
    is_ehentai = "e-hentai.org" in url
    is_xchina = "/photo/id-" in url
    if is_ehentai:
        try:
            max_imgs = 200 if _is_vip(user_id) else config.MAX_IMAGES_PER_POST
            eh_data = await get_eh_gallery(url, max_images=max_imgs)
        except Exception:
            await update.effective_message.reply_text("❌ 加载EH图集失败")
            return
        all_images = eh_data["images"]
    elif is_xchina:
        gid = re.search(r"/id-([a-f0-9]+)", url)
        if gid:
            gallery_id = gid.group(1)
            max_imgs = 200 if _is_vip(user_id) else config.MAX_IMAGES_PER_POST
            all_images = [f"https://img.xchina.io/photos/{gallery_id}/{i:05d}_600x0.webp" for i in range(1, max_imgs + 1)]
        else:
            await update.effective_message.reply_text("😔 加载失败，请稍后再试。")
            return
    else:
        try:
            max_imgs = 200 if _is_vip(user_id) else config.MAX_IMAGES_PER_POST
            gallery_data = await get_gallery_images(url, max_pages=20, max_images=max_imgs)
        except Exception:
            await update.effective_message.reply_text("😔 加载失败，请稍后再试。")
            return
        all_images = gallery_data["images"]
    total_pages = (len(all_images) + 9) // 10
    start = page * 10
    end = start + 10
    page_images = all_images[start:end]
    if not page_images:
        await update.effective_message.reply_text("已经是最后一页了～")
        return
    media = []
    downloaded = 0
    async def _dl_one(img_url):
        async with _download_sem:
            return await download_image(img_url, referer=url)
    tasks = [_dl_one(u) for u in page_images]
    results_list = await asyncio.gather(*tasks)
    for result in results_list:
        if result:
            img_data, ct = result
            img_data.seek(0)
            media.append(InputMediaPhoto(media=img_data))
            downloaded += 1
    if media:
        try:
            await update.effective_message.reply_media_group(media=media)
        except Exception:
            logger.error("Page media failed: " + traceback.format_exc())
    url_key = await _store_url(url)
    buttons = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"g_{url_key}_{page-1}"))
    nav.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"g_{url_key}_{page+1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton("🏠 主菜单", callback_data="menu_home")])
    keyboard = InlineKeyboardMarkup(buttons)
    await update.effective_message.reply_text(f"📸 第{page+1}/{total_pages}页（{downloaded}张）", reply_markup=keyboard)

# ========== Error Handler ==========

async def error_handler(update, context):
    logger.error("Global error: " + str(context.error), exc_info=True)
    if update and isinstance(update, Update) and update.effective_message:
        try: await update.effective_message.reply_text("❌ 出错了，请稍后再试。")
        except Exception: pass

# ========== VIP Daily Push ==========

async def _vip_daily_push(application):
    """Daily push of latest galleries to VIP users."""
    await asyncio.sleep(3600)  # wait 1h after startup
    while True:
        try:
            now = datetime.now()
            # Push at 10:00 and 20:00
            next_hour = 10 if now.hour < 10 else (20 if now.hour < 20 else 10)
            wait_secs = ((next_hour - now.hour) % 24) * 3600 - now.minute * 60 - now.second
            if wait_secs < 0:
                wait_secs += 86400
            await asyncio.sleep(wait_secs)

            # Get recent galleries
            from scraper import search_xchina, get_hot_keywords
            candidates = []
            kws = await get_hot_keywords(top_n=3)
            for kw in kws:
                try:
                    xc = await search_xchina(kw, max_results=3, max_pages=1)
                    candidates.extend(xc)
                except Exception: pass
            if not candidates:
                continue

            import random as _rand
            picks = _rand.sample(candidates, min(3, len(candidates)))

            for uid in list(VIP_USERS.keys()):
                try:
                    pick = _rand.choice(picks)
                    await application.bot.send_photo(
                        chat_id=uid,
                        photo=pick.get("cover", ""),
                        caption=f"📬 <b>VIP每日精选</b>\n\n{pick['title']}\n\n点击查看详情 →",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("👀 查看详情", callback_data=f"x_{await _store_url(pick['url'], source='xchina')}")
                        ]])
                    )
                except Exception:
                    pass
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"VIP push error: {e}")
        await asyncio.sleep(3600)

# ========== Main ==========

async def shutdown(app, signal_str=None):
    if signal_str: logger.info(f"Received signal {signal_str}, shutting down...")
    else: logger.info("Shutting down...")
    try:
        await stop_proxy_pool()
        await app.stop()
        await app.shutdown()
    except Exception: pass
    logger.info("Bot stopped.")

def main():
    _init_locks()
    errors = config.validate()
    if errors:
        for e in errors:
            logger.error("Config error: " + str(e))
        sys.exit(1)
    _load_vip()
    _load_users()
    _load_invites()
    _load_favorites()
    if not VIP_USERS:
        VIP_USERS[5405770555] = None
        _save_vip()
    logger.info(f"Loaded {len(VIP_USERS)} VIP users, {len(ALL_USERS)} total users")

    async def _setup_commands(app):
        from telegram import BotCommand
        await app.bot.set_my_commands([
            BotCommand("start", "🏠 主菜单"),
            BotCommand("search", "🔍 搜索图集"),
            BotCommand("random", "🎲 随机推荐"),
            BotCommand("my", "👤 我的VIP"),
            BotCommand("help", "📖 使用帮助"),
        ])
        logger.info("Bot commands set")

    app = Application.builder().token(config.BOT_TOKEN).post_init(_setup_commands).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("random", cmd_random))
    app.add_handler(CommandHandler("my", cmd_my))
    app.add_handler(CommandHandler("setvip", cmd_setvip))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(error_handler)

    async def _periodic_cleanup(application):
        last_reminder_day = 0
        while True:
            await asyncio.sleep(600)
            await _cleanup_all()
            gc.collect()
            today = datetime.now().strftime("%Y%m%d")
            if today != last_reminder_day:
                last_reminder_day = today
                now = _now()
                for uid, expiry in list(VIP_USERS.items()):
                    if expiry is not None and 0 < expiry - now <= _ONE_DAY:
                        exp_str = datetime.fromtimestamp(expiry).strftime("%Y-%m-%d")
                        try:
                            await application.bot.send_message(
                                chat_id=uid,
                                text=f"⏰ <b>VIP即将到期提醒</b>\n\n你的VIP会员将于 <b>{exp_str}</b> 到期，请及时续费哦～",
                                parse_mode="HTML",
                                reply_markup=InlineKeyboardMarkup([[
                                    InlineKeyboardButton("💳 购买卡密", url=PURCHASE_URL)
                                ]]))
                        except Exception: pass

    if config.WEBHOOK_URL:
        logger.info("Starting in webhook mode: " + config.WEBHOOK_URL)
        async def _pre_init():
            await app.initialize()
            await app.start()
            await start_proxy_pool()
            await start_pre_cache()
            asyncio.create_task(_periodic_cleanup(app))
            asyncio.create_task(_vip_daily_push(app))
            await app.bot.set_webhook(url=config.WEBHOOK_URL + "/webhook")
            logger.info("Webhook set. Starting HTTP server...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_pre_init())
        try:
            app.run_webhook(
                listen="0.0.0.0",
                port=config.WEBHOOK_PORT,
                url_path="webhook",
                webhook_url=config.WEBHOOK_URL + "/webhook",
            )
        except KeyboardInterrupt:
            loop.run_until_complete(shutdown(app, "SIGINT"))
    else:
        logger.info("Starting in polling mode")
        from http.server import HTTPServer, BaseHTTPRequestHandler
        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"OK")
            def log_message(self, format, *args): pass
        port = int(os.environ.get("PORT", 8000))
        health_srv = HTTPServer(("0.0.0.0", port), HealthHandler)
        import threading
        t = threading.Thread(target=health_srv.serve_forever, daemon=True)
        t.start()
        logger.info(f"Health server on port {port}")
        async def _start_polling():
            await app.initialize()
            await app.start()
            await start_proxy_pool()
            await start_pre_cache()
            asyncio.create_task(_periodic_cleanup(app))
            asyncio.create_task(_vip_daily_push(app))
            await app.updater.start_polling(allowed_updates=["message", "callback_query"])
            try:
                while True: await asyncio.sleep(60)
            except asyncio.CancelledError:
                await shutdown(app)
        try:
            asyncio.run(_start_polling())
        except KeyboardInterrupt:
            asyncio.run(shutdown(app, "SIGINT"))

if __name__ == "__main__":
    main()