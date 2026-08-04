"""handlers_text.py — Free-form text message handler."""
from bot_utils import (
    user_search_prompt_msg,
    now_ts, is_vip, check_rate_limit, user_waiting_search, user_waiting_card,
    ADMIN_IDS, VIP_USERS, ALL_USERS, INVITES, admin_setvip_state,
    PURCHASE_URL, _ONE_DAY, VIP_TEXT, build_hot_keyword_keyboard,
    save_vip_db,
)
from handlers_commands import cmd_random, cmd_help, cmd_my
from handlers_search import _do_search
from config import config
from database import (
    db_add_user, db_load_cards, db_activate_card, db_save_vip,
    db_bump_stat,
)
import asyncio, html, logging, re, traceback
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
logger = logging.getLogger(__name__)

# ========== Handle Text ==========

CARD_CODE_RE = re.compile(r"^(?:Y|S|N|J)-[A-Za-z0-9]{10,13}$|^xy[A-Za-z0-9]{5,20}$", re.IGNORECASE)


def _normalize_card_code(raw: str) -> str:
    """Strip all whitespace and uppercase - users paste codes with stray
    spaces/line breaks or in lowercase, while codes are stored uppercase."""
    return "".join(raw.split()).upper()


async def _try_activate_card(update, user_id: int, raw: str) -> bool:
    """Try to activate a card code; always replies to the user.
    Returns True if the message was consumed as a card-code message."""
    card_code = _normalize_card_code(raw)
    if not card_code:
        return False
    is_current_vip = user_id in VIP_USERS
    current_expiry = VIP_USERS.get(user_id)
    if is_current_vip and current_expiry is None:
        await update.message.reply_text(
            "👑 你已是永久会员，无需再激活卡密。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
            ]]))
        return True

    # Atomic activate - no full-table load, no race condition
    card = await db_activate_card(card_code, user_id)
    if not card:
        await update.message.reply_text(
            "❌ 卡密无效或已被使用。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔑 重新输入", callback_data="vip_activate"),
                InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
            ]]))
        return True

    # Card type/days come from the DB - never infer from the code prefix
    card_type = card["card_type"]
    days = card["days"]
    day_names = {"month": "月卡(30天)", "quarter": "季卡(90天)", "year": "年卡(360天)", "forever": "永久", "trial": "体验卡"}
    name = day_names.get(card_type, card_type)
    expiry = None if days is None or int(days) <= 0 else now_ts() + int(days) * 86400
    # 已有VIP（试用/未到期卡）激活新卡 -> 从当前到期日顺延，不损失剩余时长
    if expiry is not None and is_current_vip and current_expiry and current_expiry > now_ts():
        expiry = current_expiry + int(days) * 86400

    asyncio.create_task(db_bump_stat(datetime.now().strftime("%Y-%m-%d"), "card_activations"))
    VIP_USERS[user_id] = expiry
    await save_vip_db(user_id, expiry)
    if days:
        exp_str = datetime.fromtimestamp(expiry).strftime("%Y-%m-%d")
        msg = f"✅ 卡密激活成功！\n\n类型：{name}\n到期：{exp_str}\n\n返回主菜单即可享受VIP特权！"
    else:
        msg = f"✅ 卡密激活成功！\n\n类型：{name}\n\n返回主菜单即可享受VIP特权！"
    await update.message.reply_text(msg,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
        ]]))
    return True

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
                VIP_USERS[target_id] = now_ts() + days * 86400
                label = f"{days}天"
            else:
                VIP_USERS[target_id] = None
                label = "永久"
            await save_vip_db(target_id, VIP_USERS[target_id])
            if target_id not in ALL_USERS:
                ALL_USERS.add(target_id)
                asyncio.create_task(db_add_user(target_id))
            await update.message.reply_text(
                f"✅ 已将用户 <code>{target_id}</code> 设置为VIP（{label}）",
                parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ 请输入有效的用户ID（数字）")
        return

    if text == "🔍 搜索":
        user_waiting_search.add(user_id)
        keyboard = await build_hot_keyword_keyboard([
            [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")],
        ], user_id=user_id)
        sent = await update.message.reply_text(
            "🔍 请直接输入搜索关键词～\n\n🔥 <b>热门搜索：</b>",
            parse_mode="HTML",
            reply_markup=keyboard)
        user_search_prompt_msg[user_id] = sent.message_id
        return
    elif text == "🎲 推荐":
        await cmd_random(update, context)
        return
    elif text == "👑 VIP":
        if is_vip(user_id):
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

    # Card activation flow (user tapped the "我有卡密，输入激活" button)
    if user_id in user_waiting_card:
        user_waiting_card.discard(user_id)
        if not is_vip(user_id) and not await check_rate_limit(user_id):
            await update.message.reply_text("⏱ 操作太频繁，请稍后再试。")
            return
        await _try_activate_card(update, user_id, text)
        return


    # Default: any other text → treat as search keyword
    if user_id in user_waiting_search:
        user_waiting_search.discard(user_id)
        prompt_msg_id = user_search_prompt_msg.pop(user_id, None)
        if prompt_msg_id:
            try:
                await update.message.delete()
                await update.message.chat.delete_message(prompt_msg_id)
            except Exception:
                pass
    # Auto-activate: users often paste a card code directly without tapping the
    # activation button; if the message looks like a card code, try to activate it.
    if CARD_CODE_RE.match(text):
        if not is_vip(user_id) and not await check_rate_limit(user_id):
            await update.message.reply_text("⏱ 操作太频繁，请稍后再试。")
            return
        if await _try_activate_card(update, user_id, text):
            return


    keyword = text
    if not keyword:
        return
    await _do_search(update, keyword)
