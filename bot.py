"""Gallery Search Bot - Telegram Bot"""
import asyncio
import logging
import sys
import os
import traceback
import json
import re
import time
import gc
import html
from datetime import datetime
from collections import defaultdict
from logging.handlers import RotatingFileHandler
from threading import Lock

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    Message, InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)
from config import config
from scraper import (
    search_galleries, get_gallery_images, get_random_gallery,
    download_image, track_click, extract_download_link,
)

# ---- Logging ----
_log_handler = RotatingFileHandler(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log"),
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=2,
    encoding="utf-8",
)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout), _log_handler],
    force=True,
)
logger = logging.getLogger(__name__)

# ---- Constants ----
RESULTS_PER_PAGE = 5
URL_TTL = 3600  # URL store entries expire after 1 hour
USER_STATE_TTL = 1800  # User search state expires after 30 min
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = config.MAX_SEARCHES_PER_MINUTE

# ---- State (with TTL cleanup) ----
user_search_state: dict = {}       # {user_id: {"page": int, "keyword": str, "results": list, "ts": float}}
user_waiting_search: set = set()   # {user_id}
url_store: dict = {}               # {key: {"url": str, "ts": float}}
url_counter: int = 0
VIP_USERS: dict = {}               # {user_id: expiry_timestamp or None for permanent}
VIP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vip_users.json")
CARD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cards.json")
user_waiting_card: set = set()     # {user_id}
# Per-user rate limiting: {user_id: [timestamp, ...]}
_user_search_times: dict = defaultdict(list)
_user_search_lock = Lock()

ADMIN_IDS = {5405770555}

MENU_KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("🔍 搜索"), KeyboardButton("🎲 推荐"), KeyboardButton("👑 VIP"), KeyboardButton("👤 我的")],
], resize_keyboard=True)


# ========== State Helpers ==========

def _cleanup_url_store():
    """Remove URL entries older than URL_TTL to prevent memory leaks."""
    global url_store
    now = time.time()
    url_store = {k: v for k, v in url_store.items() if now - v.get("ts", 0) < URL_TTL}


def _cleanup_user_state(user_id):
    """Remove expired user search state."""
    if user_id in user_search_state:
        ts = user_search_state[user_id].get("ts", 0)
        if time.time() - ts > USER_STATE_TTL:
            del user_search_state[user_id]


def _cleanup_all():
    """Periodic cleanup of all state stores."""
    now = time.time()
    stale_users = [uid for uid, s in user_search_state.items() if now - s.get("ts", 0) > USER_STATE_TTL]
    for uid in stale_users:
        del user_search_state[uid]
    _cleanup_url_store()


def _save_vip():
    """Save VIP user list to file."""
    try:
        with open(VIP_FILE, "w", encoding="utf-8") as f:
            json.dump(VIP_USERS, f)
    except Exception as e:
        logger.error(f"Failed to save VIP: {e}")


def _load_vip():
    """Load VIP user list from file."""
    global VIP_USERS
    try:
        if os.path.exists(VIP_FILE):
            with open(VIP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    VIP_USERS = {uid: None for uid in data}
                else:
                    VIP_USERS = {int(k): v for k, v in data.items()}
    except Exception as e:
        logger.error(f"Failed to load VIP: {e}")
        VIP_USERS = {}


def _load_cards() -> dict:
    try:
        if os.path.exists(CARD_FILE):
            with open(CARD_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_cards(cards: dict):
    try:
        with open(CARD_FILE, "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save cards: {e}")


def _store_url(url):
    """Store URL with timestamp and return a short key."""
    global url_counter
    url_counter += 1
    key = str(url_counter)
    url_store[key] = {"url": url, "ts": time.time()}
    if url_counter % 1000 == 0:
        _cleanup_url_store()
    return key


def _get_url(key):
    entry = url_store.get(key)
    if not entry:
        return ""
    # Check TTL
    if time.time() - entry.get("ts", 0) > URL_TTL:
        del url_store[key]
        return ""
    return entry["url"]


def _check_rate_limit(user_id: int) -> bool:
    """Check if user has exceeded the rate limit. Returns True if allowed."""
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW
    with _user_search_lock:
        times = _user_search_times[user_id]
        # Remove old entries
        _user_search_times[user_id] = [t for t in times if t > cutoff]
        current_count = len(_user_search_times[user_id])
        if current_count >= RATE_LIMIT_MAX:
            return False
        _user_search_times[user_id].append(now)
        return True


def _parse_count_from_title(title):
    m = re.search(r"(\d+)\s*photos?", title, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*[pP张]", title)
    if m:
        return int(m.group(1))
    return 0


def _clean_title(title):
    return re.sub(r"\s*\[[^\]]*\].*$", "", title).strip()


def _is_vip(user_id):
    if user_id not in VIP_USERS:
        return False
    expiry = VIP_USERS[user_id]
    if expiry is None:
        return True  # permanent
    if time.time() > expiry:
        del VIP_USERS[user_id]
        _save_vip()
        return False
    return True


async def _edit_message(msg_or_query, text, reply_markup=None, parse_mode="HTML"):
    try:
        if isinstance(msg_or_query, Message):
            await msg_or_query.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await msg_or_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        # "Message is not modified" is common and harmless; log others
        err_str = str(e)
        if "not modified" not in err_str.lower():
            logger.warning(f"_edit_message failed: {err_str}")


# ========== Start Menu ==========

START_TEXT = """<b>✨ 美少女图集搜索姬 ✨</b>

👋 主人好呀～我是你的专属图集小助手！

🎀 <b>我能做什么？</b>
• 🔍 海量 Cosplay、写真、自拍图集随意搜
• 🎲 不知道看什么？试试随机推荐
• 👑 VIP 还能翻页浏览 + 下载原图压缩包

💕 资源每日更新，再也不怕片荒啦～

👇 点击下方按钮开始探索吧！"""

START_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔍 搜索图集", callback_data="menu_search")],
    [InlineKeyboardButton("🎲 随机推荐", callback_data="menu_random")],
    [InlineKeyboardButton("👑 开通VIP", callback_data="menu_vip")],
])

VIP_TEXT = """<b>👑 VIP 会员说明</b>

🎯 <b>VIP 特权：</b>
• 无限次搜索
• 查看完整大图集
• 翻页浏览所有图片
• 原图压缩包下载
• 优先体验新功能

🚧 功能开发中，敬请期待～"""


async def cmd_start(update, context):
    user_id = update.effective_user.id
    user_waiting_search.discard(user_id)
    user_waiting_card.discard(user_id)
    await update.message.reply_text(START_TEXT, reply_markup=START_KEYBOARD, parse_mode="HTML")
    await update.message.reply_text("💕 使用下方快捷按钮操作～", reply_markup=MENU_KEYBOARD)


async def cmd_setvip(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return  # silently ignore
    if not context.args:
        await update.message.reply_text("用法: /setvip <用户ID>")
        return
    try:
        target = int(context.args[0])
        VIP_USERS[target] = None  # permanent
        _save_vip()
        await update.message.reply_text(f"✅ 已将用户 {target} 设为VIP")
        logger.info(f"VIP added: {target}")
    except ValueError:
        await update.message.reply_text("用户ID必须是数字")


async def cmd_my(update, context):
    user_id = update.effective_user.id
    if _is_vip(user_id):
        expiry = VIP_USERS.get(user_id)
        if expiry is None:
            info = "永久会员 ♮️"
        else:
            exp_str = datetime.fromtimestamp(expiry).strftime("%Y年%m月%d日")
            remaining = max(0, int((expiry - time.time()) / 86400))
            info = f"到期：{exp_str}  (剩{remaining}天)"
        await update.message.reply_text(
            f"👑 <b>你的VIP信息</b>\n\n{info}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔑 续费/升级", callback_data="vip_activate"),
                InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home"),
            ]]))
    else:
        await update.message.reply_text(
            "👑 <b>VIP会员</b>\n\n你还不是VIP会员哦～\n开通后可以：\n• 查看全部搜索结果\n• 翻页浏览所有图片\n• 下载原图压缩包",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔑 输入卡密激活", callback_data="vip_activate")],
                [InlineKeyboardButton("💳 购买卡密", url="https://t.me/xiuren88bot?start=buy_524")],
                [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")],
            ]))


async def cmd_help(update, context):
    await update.message.reply_text(
        "<b>📖 使用帮助</b>\n\n"
        "点击「🔍 搜索图集」后直接输入关键词即可\n"
        "/search 关键词 - 快速搜索\n"
        "/random - 随机推荐\n"
        "/start - 回到主菜单",
        parse_mode="HTML"
    )


async def cmd_search(update, context):
    user_id = update.effective_user.id
    if not context.args:
        user_waiting_search.add(user_id)
        await update.message.reply_text(
            "🔍 请直接输入搜索关键词～\n\n"
            "比如：jk、黑丝、萝莉、御姐、学妹、少妇、自拍...",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
            ]])
        )
        return
    keyword = " ".join(context.args)
    await _do_search(update, keyword)


async def cmd_random(update, context):
    user_id = update.effective_user.id
    user_waiting_search.discard(user_id)
    msg = await update.message.reply_text("🎲 正在随机推荐...")
    try:
        gallery = get_random_gallery()
    except Exception as e:
        logger.error(f"Random error: {traceback.format_exc()}")
        await _edit_message(msg, "😔 获取随机推荐失败，请稍后再试。")
        return
    if not gallery:
        await _edit_message(msg, "😔 获取随机推荐失败，请稍后再试。")
        return
    await msg.delete()
    await _send_gallery_detail(update, gallery["url"])


# ========== Handle Bottom Keyboard Buttons ==========

async def handle_text(update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == "🔍 搜索":
        user_waiting_search.add(user_id)
        await update.message.reply_text(
            "🔍 请直接输入搜索关键词～\n\n"
            "比如：jk、黑丝、萝莉、御姐、学妹、少妇、自拍...",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
            ]])
        )
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
                    [InlineKeyboardButton("💳 购买卡密", url="https://t.me/xiuren88bot?start=buy_524")],
                    [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")]
                ]))
        return
    elif text == "👤 我的":
        await cmd_my(update, context)
        return

    if user_id in user_waiting_card:
        user_waiting_card.discard(user_id)
        card_code = text.strip()
        cards = _load_cards()
        if card_code in cards:
            if cards[card_code].get("used"):
                await update.message.reply_text("❌ 该卡密已被使用过。")
            else:
                card_type = cards[card_code].get("type", "forever")
                days = {"month": 30, "quarter": 90, "year": 360, "forever": None, "trial": 1}
                day_names = {"month": "月卡(30天)", "quarter": "季卡(90天)", "year": "年卡(360天)", "forever": "永久", "trial": "体验卡(1天)"}
                d = days.get(card_type, None)
                expiry = None if d is None else time.time() + d * 86400
                # Mark card as used (including trial, to prevent reuse)
                cards[card_code]["used"] = True
                cards[card_code]["used_by"] = user_id
                cards[card_code]["activated_at"] = time.time()
                _save_cards(cards)
                VIP_USERS[user_id] = expiry
                _save_vip()
                name = day_names.get(card_type, card_type)
                if d:
                    exp_str = datetime.fromtimestamp(expiry).strftime("%Y-%m-%d")
                    msg = f"✅ 卡密激活成功！\n\n类型：{name}\n到期：{exp_str}\n\n返回主菜单即可享受VIP特权！"
                else:
                    msg = f"✅ 卡密激活成功！\n\n类型：{name}\n\n返回主菜单即可享受VIP特权！"
                await update.message.reply_text(
                    msg,
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

    if user_id not in user_waiting_search:
        return
    user_waiting_search.discard(user_id)
    keyword = text
    if not keyword:
        await update.message.reply_text("⚠️ 请输入搜索关键词～")
        user_waiting_search.add(user_id)
        return
    await _do_search(update, keyword)


async def _do_search(update, keyword):
    user_id = update.effective_user.id

    # Rate limiting
    if not _is_vip(user_id) and not _check_rate_limit(user_id):
        await update.message.reply_text(
            "⏱️ 操作太快了，请稍后再试～",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
            ]])
        )
        return

    _cleanup_user_state(user_id)
    msg = await update.message.reply_text(f"🔍 正在搜索: <b>{html.escape(keyword)}</b>...", parse_mode="HTML")
    try:
        results = search_galleries(keyword)
    except Exception as e:
        logger.error(f"Search error: {traceback.format_exc()}")
        await _edit_message(msg, "😔 搜索出错，请稍后再试。")
        return
    if not results:
        await _edit_message(msg,
            f"😔 没有找到与 <b>{html.escape(keyword)}</b> 相关的图集。\n\n换个关键词试试？",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔍 重新搜索", callback_data="menu_search"),
                InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home"),
            ]]))
        return
    user_search_state[user_id] = {
        "page": 0, "keyword": keyword, "results": results, "ts": time.time()
    }
    await _show_results_page(msg, user_id)


# ========== Menu Callbacks ==========

async def _handle_menu_search(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    user_waiting_search.add(user_id)
    await query.edit_message_text(
        "🔍 请直接输入搜索关键词～\n\n"
        "比如：jk、黑丝、萝莉、御姐、学妹、少妇、自拍...",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
        ]]))


async def _handle_menu_random(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    user_waiting_search.discard(user_id)
    await query.edit_message_text("🎲 正在为你随机推荐...")
    try:
        gallery = get_random_gallery()
    except Exception:
        await query.edit_message_text("😔 获取随机推荐失败，请稍后再试。")
        return
    if not gallery:
        await query.edit_message_text("😔 获取随机推荐失败，请稍后再试。")
        return
    await _send_gallery_detail(update, gallery["url"])


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
            [InlineKeyboardButton("💳 购买卡密", url="https://t.me/xiuren88bot?start=buy_524")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")]
        ]))


async def _handle_menu_home(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    user_waiting_search.discard(user_id)
    user_waiting_card.discard(user_id)
    await query.edit_message_text(START_TEXT, reply_markup=START_KEYBOARD, parse_mode="HTML")


# ========== Main Callback Handler ==========

async def handle_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"Callback: user={user_id} data={data[:50]}")

    try:
        if data == "menu_search":
            await _handle_menu_search(update, context)
        elif data == "menu_random":
            await _handle_menu_random(update, context)
        elif data == "menu_vip":
            await _handle_menu_vip(update, context)
        elif data == "menu_home":
            await _handle_menu_home(update, context)
        elif data == "noop":
            return
        elif data == "vip_activate":
            user_waiting_card.add(user_id)
            await query.edit_message_text(
                "🔑 请输入你的卡密：\n\n格式：直接输入卡密即可",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
                ]]))
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
            try:
                await loading_msg.delete()
            except Exception:
                pass
        elif data.startswith("f_"):
            url = _get_url(data[2:])
            if not url:
                await query.message.reply_text("⏳ 链接已过期，请重新搜索。")
                return
            loading_msg = await query.message.reply_text("⏳ 正在加载图片，请稍候...")
            await _send_gallery_full(update, url)
            try:
                await loading_msg.delete()
            except Exception:
                pass
        elif data.startswith("g_"):
            parts = data[2:].split("_")
            url_key = parts[0]
            page = int(parts[1]) if len(parts) > 1 else 0
            url = _get_url(url_key)
            if not url:
                await query.message.reply_text("⏳ 链接已过期。")
                return
            if not _is_vip(user_id):
                await query.answer("👑 请先开通VIP会员", show_alert=True)
                return
            loading_msg = await query.message.reply_text(f"⏳ 正在加载第{page+1}页，请稍候...")
            await _send_gallery_page(update, url, page)
            try:
                await loading_msg.delete()
            except Exception:
                pass
        elif data.startswith("zip_"):
            url = _get_url(data[4:])
            if not url:
                await query.edit_message_text("⏳ 链接已过期。")
                return
            if not _is_vip(user_id):
                await query.answer("👑 请先开通VIP会员", show_alert=True)
                return
            loading_msg = await query.message.reply_text("⏳ 正在获取下载链接...")
            dl_link = extract_download_link(url)
            try:
                await loading_msg.delete()
            except Exception:
                pass
            if dl_link:
                text = f'📦 <b>原图压缩包</b>\n\n🔗 <a href="{dl_link}">TeraBox 下载</a>\n\n🔑 解压密码：<code>4KHD</code>'
            else:
                text = f'📦 <b>原图压缩包</b>\n\n🔗 <a href="{url}">点击打开原网页</a>\n\n⚠️ 未找到下载链接，请从原网页提取'
            await query.edit_message_text(
                text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
                ]]))
        elif data == "vip_upgrade":
            user_id = update.effective_user.id
            if _is_vip(user_id):
                await query.edit_message_text(
                    "<b>👑 你已是VIP会员</b>\n\n🎉 享受所有特权～",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
                    ]]))
            else:
                await query.edit_message_text(VIP_TEXT, parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔑 输入卡密激活", callback_data="vip_activate")],
                        [InlineKeyboardButton("💳 购买卡密", url="https://t.me/xiuren88bot?start=buy_524")],
                        [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")]
                    ]))
    except Exception as e:
        logger.error(f"Callback error: {traceback.format_exc()}")
        try:
            await query.edit_message_text("❌ 操作失败，请重试。")
        except Exception:
            pass


# ========== Display ==========

async def _show_results_page(msg_or_query, user_id):
    state = user_search_state.get(user_id)
    if not state:
        return
    results = state["results"]
    page = state["page"]
    keyword = state["keyword"]
    total = len(results)
    full_pages = max(1, (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)
    is_vip = _is_vip(user_id)
    total_pages = full_pages if is_vip else min(full_pages, 2)
    start = page * RESULTS_PER_PAGE
    end = min(start + RESULTS_PER_PAGE, total)
    page_results = results[start:end]

    text = f"🔍 <b>{html.escape(keyword)}</b> 共 {total} 个结果（第{page+1}/{full_pages}页）"
    if not is_vip and full_pages > 2:
        text += f"\n\n👑 开通VIP可查看全部{total}条结果"
    text += "\n\n"
    buttons = []
    for i, r in enumerate(page_results):
        idx = start + i + 1
        clean_title = _clean_title(r["title"])
        text += f"{idx}. {html.escape(clean_title)}\n"
        btn_label = clean_title[:24] + ".." if len(clean_title) > 26 else clean_title[:26]
        url_key = _store_url(r["url"])
        buttons.append([InlineKeyboardButton(f"📷 {idx}. {btn_label}", callback_data=f"d_{url_key}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"p_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"p_{page+1}"))
    buttons.append(nav_buttons)
    if not is_vip and full_pages > 2:
        buttons.append([InlineKeyboardButton("👑 VIP查看全部搜索结果", callback_data="menu_vip")])
    buttons.append([
        InlineKeyboardButton("👑 开通VIP", callback_data="menu_vip"),
        InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home"),
    ])
    await _edit_message(msg_or_query, text, reply_markup=InlineKeyboardMarkup(buttons))


async def _send_gallery_detail(update, url, gallery_data=None):
    user_id = update.effective_user.id
    logger.info(f"Fetching gallery: {url[:80]}")

    if gallery_data is None:
        try:
            gallery_data = get_gallery_images(url)
        except Exception as e:
            logger.error(f"Gallery fetch error: {traceback.format_exc()}")
            await update.effective_message.reply_text("😔 获取图集详情失败，请稍后再试。")
            return

    title = gallery_data["title"]
    cover = gallery_data["cover"]
    cover_bytes = gallery_data.get("cover_bytes")
    publish_date = gallery_data.get("publish_date", "")
    all_images = gallery_data["images"]

    track_click(url, title)
    original_count = _parse_count_from_title(title)
    display_count = original_count if original_count > 0 else len(all_images)
    clean_title = _clean_title(title)

    text = f"🎀 {html.escape(clean_title)}\n📸 {display_count}张"
    if publish_date:
        text += f"\n🕐 {publish_date}"

    url_key = _store_url(url)
    buttons = [[InlineKeyboardButton("🖼️ 查看完整图集", callback_data=f"f_{url_key}")]]
    buttons.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")])
    keyboard = InlineKeyboardMarkup(buttons)

    sent = False
    if cover_bytes:
        img_data, img_ct = cover_bytes
        try:
            img_data.seek(0)
            await update.effective_message.reply_photo(
                photo=img_data, caption=text, reply_markup=keyboard, parse_mode="HTML")
            sent = True
        except Exception as e:
            logger.error(f"Cover send failed: {traceback.format_exc()}")

    if not sent and cover:
        try:
            await update.effective_message.reply_photo(
                photo=cover, caption=text, reply_markup=keyboard, parse_mode="HTML")
            sent = True
        except Exception as e:
            logger.error(f"Cover url send failed: {traceback.format_exc()}")

    if not sent:
        await update.effective_message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


async def _send_gallery_full(update, url):
    user_id = update.effective_user.id
    try:
        gallery_data = get_gallery_images(url)
    except Exception as e:
        logger.error(f"Full gallery error: {traceback.format_exc()}")
        await update.effective_message.reply_text("😔 加载失败，请稍后再试。")
        return

    all_images = gallery_data["images"]
    total_pages = (len(all_images) + 9) // 10
    preview = all_images[:10]

    media = []
    downloaded = 0
    for img_url in preview:
        result = download_image(img_url, referer=url)
        if result:
            img_data, ct = result
            img_data.seek(0)
            media.append(InputMediaPhoto(media=img_data))
            downloaded += 1
    if media:
        try:
            await update.effective_message.reply_media_group(media=media)
        except Exception as e:
            logger.error(f"Media group failed: {traceback.format_exc()}")

    url_key = _store_url(url)
    buttons = []
    if _is_vip(user_id):
        if total_pages > 1:
            buttons.append([InlineKeyboardButton("➡️ 下一页", callback_data=f"g_{url_key}_1")])
    else:
        buttons.append([InlineKeyboardButton("👑 VIP查看完整图集", callback_data="vip_upgrade")])
    if _is_vip(user_id):
        buttons.append([InlineKeyboardButton("📦 原图压缩包", callback_data=f"zip_{url_key}")])
    buttons.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")])
    keyboard = InlineKeyboardMarkup(buttons)
    await update.effective_message.reply_text(
        f"📸 第1/{total_pages}页（{downloaded}张）", reply_markup=keyboard)


async def _send_gallery_page(update, url, page=0):
    user_id = update.effective_user.id
    if not _is_vip(user_id):
        return
    try:
        gallery_data = get_gallery_images(url)
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
    for img_url in page_images:
        result = download_image(img_url, referer=url)
        if result:
            img_data, ct = result
            img_data.seek(0)
            media.append(InputMediaPhoto(media=img_data))
            downloaded += 1
    if media:
        try:
            await update.effective_message.reply_media_group(media=media)
        except Exception as e:
            logger.error(f"Page media failed: {traceback.format_exc()}")

    url_key = _store_url(url)
    buttons = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"g_{url_key}_{page-1}"))
    nav.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"g_{url_key}_{page+1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton("📦 原图压缩包", callback_data=f"zip_{url_key}")])
    buttons.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")])
    keyboard = InlineKeyboardMarkup(buttons)
    await update.effective_message.reply_text(
        f"📸 第{page+1}/{total_pages}页（{downloaded}张）", reply_markup=keyboard)


# ========== Error Handler ==========

async def error_handler(update, context):
    logger.error(f"Global error: {context.error}", exc_info=True)
    if update and isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("❌ 出错了，请稍后再试。")
        except Exception:
            pass


# ========== Main ==========

async def shutdown(app, signal_str=None):
    """Graceful shutdown handler."""
    if signal_str:
        logger.info(f"Received signal {signal_str}, shutting down...")
    else:
        logger.info("Shutting down...")
    try:
        await app.stop()
        await app.shutdown()
    except Exception as e:
        logger.error(f"Shutdown error: {e}")
    logger.info("Bot stopped.")


def main():
    errors = config.validate()
    if errors:
        for e in errors:
            logger.error(f"Config error: {e}")
        sys.exit(1)

    _load_vip()
    logger.info(f"Loaded {len(VIP_USERS)} VIP users")

    async def _setup_commands(app):
        from telegram import BotCommand
        await app.bot.set_my_commands([
            BotCommand("start", "🏠 主菜单"),
            BotCommand("search", "🔍 搜索图集"),
            BotCommand("random", "🎲 随机推荐"),
            BotCommand("my", "👑 我的VIP"),
        ])
        logger.info("Bot commands set")

    app = Application.builder().token(config.BOT_TOKEN).post_init(_setup_commands).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("random", cmd_random))
    app.add_handler(CommandHandler("my", cmd_my))
    app.add_handler(CommandHandler("setvip", cmd_setvip))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(error_handler)

    # Periodic cleanup + VIP expiry reminder
    async def _periodic_cleanup(application):
        last_reminder_day = 0
        while True:
            await asyncio.sleep(600)  # every 10 minutes
            _cleanup_all()
            gc.collect()
            # Check VIP expiry reminders once per day
            today = time.strftime("%Y%m%d")
            if today != last_reminder_day:
                last_reminder_day = today
                now = time.time()
                three_days = 3 * 86400
                for uid, expiry in list(VIP_USERS.items()):
                    if expiry is not None and 0 < expiry - now <= three_days:
                        exp_str = datetime.fromtimestamp(expiry).strftime("%Y-%m-%d")
                        try:
                            await application.bot.send_message(
                                chat_id=uid,
                                text=f"⏰ <b>VIP即将到期提醒</b>\n\n你的VIP会员将于 <b>{exp_str}</b> 到期，请及时续费哦～\n\n点击下方按钮续费：",
                                parse_mode="HTML",
                                reply_markup=InlineKeyboardMarkup([[
                                    InlineKeyboardButton("💳 购买卡密", url="https://t.me/xiuren88bot?start=buy_524")
                                ]])
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send reminder to {uid}: {e}")

    if config.WEBHOOK_URL:
        logger.info(f"Starting in webhook mode: {config.WEBHOOK_URL}")

        async def _start_webhook():
            await app.initialize()
            await app.start()
            asyncio.create_task(_periodic_cleanup(app))
            await app.bot.set_webhook(url=f"{config.WEBHOOK_URL}/webhook")
            logger.info("Webhook set. Waiting...")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await shutdown(app)

        try:
            asyncio.run(_start_webhook())
        except KeyboardInterrupt:
            asyncio.run(shutdown(app, "SIGINT"))
    else:
        logger.info("Starting in polling mode")

        async def _run_polling():
            cleanup_task = asyncio.create_task(_periodic_cleanup(app))
            try:
                await app.run_polling(
                    allowed_updates=["message", "callback_query"],
                    close_loop=False,
                    stop_signals=[],
                )
            except asyncio.CancelledError:
                pass
            finally:
                cleanup_task.cancel()
                try:
                    await cleanup_task
                except asyncio.CancelledError:
                    pass
                await shutdown(app)

        try:
            asyncio.run(_run_polling())
        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt")
            # The asyncio.run() already handles cancellation


if __name__ == "__main__":
    main()
