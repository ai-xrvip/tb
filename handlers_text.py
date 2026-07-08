"""handlers_text.py — Free-form text message handler."""
from bot_utils import (
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
        await update.message.reply_text(
            "🔍 请直接输入搜索关键词～\n\n🔥 <b>热门搜索：</b>",
            parse_mode="HTML",
            reply_markup=keyboard)
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

    # Card activation flow
    if user_id in user_waiting_card:
        user_waiting_card.discard(user_id)
        if not is_vip(user_id) and not await check_rate_limit(user_id):
            await update.message.reply_text("⏱ 操作太频繁，请稍后再试。")
            return

        card_code = text.strip()
        if is_vip(user_id):
            await update.message.reply_text(
                "❗ 你已经是VIP会员了。如需续费请使用新卡密。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
                ]]))
            return

        # Atomic activate — no full-table load, no race condition
        activated = await db_activate_card(card_code, user_id)
        if not activated:
            await update.message.reply_text(
                "❌ 卡密无效或已被使用。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔑 重新输入", callback_data="vip_activate"),
                    InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
                ]]))
            return

        # Determine card type and expiry from the code prefix
        prefix = card_code.split("-")[0] if "-" in card_code else ""
        prefix_type = {"Y": "month", "J": "quarter", "N": "year", "S": "forever"}
        card_type = prefix_type.get(prefix, "forever")
        days_map = {"month": 30, "quarter": 90, "year": 360, "forever": None}
        day_names = {"month": "月卡(30天)", "quarter": "季卡(90天)", "year": "年卡(360天)", "forever": "永久"}
        days = days_map.get(card_type)
        expiry = None if days is None else now_ts() + days * 86400

        asyncio.create_task(db_bump_stat(datetime.now().strftime("%Y-%m-%d"), "card_activations"))
        VIP_USERS[user_id] = expiry
        await save_vip_db(user_id, expiry)
        name = day_names.get(card_type, card_type)
        if days:
            exp_str = datetime.fromtimestamp(expiry).strftime("%Y-%m-%d")
            msg = f"✅ 卡密激活成功！\n\n类型：{name}\n到期：{exp_str}\n\n返回主菜单即可享受VIP特权！"
        else:
            msg = f"✅ 卡密激活成功！\n\n类型：{name}\n\n返回主菜单即可享受VIP特权！"
        await update.message.reply_text(msg,
            reply_markup=InlineKeyboardMarkup([[
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
