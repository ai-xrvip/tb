"""
礼物/支付模块 —— /gifts 查看 + 内联按钮购买
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import config
from database import db
from utils.logger import logger

# ── 礼物清单 ──
GIFTS = [
    {"id": "flower", "name": "🌹 玫瑰花束", "price": 9.9, "desc": "一束鲜红的玫瑰，表达你温柔的心意"},
    {"id": "chocolate", "name": "🍫 手工巧克力", "price": 19.9, "desc": "精致的比利时手工巧克力"},
    {"id": "perfume", "name": "💐 香水礼盒", "price": 49.9, "desc": "法国进口香水，优雅迷人"},
    {"id": "necklace", "name": "💎 水晶项链", "price": 99.9, "desc": "闪耀的水晶，配得上她的美丽"},
    {"id": "dress", "name": "👗 设计师连衣裙", "price": 199.9, "desc": "限量款连衣裙，让她成为最耀眼的存在"},
    {"id": "diamond", "name": "💍 钻戒", "price": 520.0, "desc": "永恒的承诺，非她莫属"},
]


def _gift_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for g in GIFTS:
        buttons.append([
            InlineKeyboardButton(
                f"{g['name']} — ¥{g['price']}",
                callback_data=f"gift:{g['id']}",
            )
        ])
    return InlineKeyboardMarkup(buttons)


async def cmd_gift_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /gifts —— 查看礼物清单 """
    user = update.effective_user
    user_id = user.id
    db.create_user(user_id)

    owned = db.get_user_gifts(user_id)
    owned_ids = {g["gift_id"] for g in owned}

    text = "🎁 **礼物商城**\n\n"
    for g in GIFTS:
        status = "✅ 已拥有" if g["id"] in owned_ids else ""
        text += f"{g['name']} — ¥{g['price']}\n  _{g['desc']}_ {status}\n\n"

    text += "点击下方按钮购买礼物～"

    await update.message.reply_text(
        text,
        reply_markup=_gift_keyboard(),
    )


async def gift_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理礼物购买回调"""
    query = update.callback_query
    await query.answer()

    gift_id = query.data.replace("gift:", "")
    gift = next((g for g in GIFTS if g["id"] == gift_id), None)
    if not gift:
        await query.edit_message_text("❌ 未知礼物。")
        return

    user_id = query.from_user.id
    db.create_user(user_id)

    if db.has_gift(user_id, gift_id):
        await query.answer("你已经拥有这个礼物了～", show_alert=True)
        return

    # 记录购买（实际支付接口预留）
    db.add_gift_purchase(user_id, gift_id, gift["name"], gift["price"])
    logger.info(f"gift purchased user_id={user_id} gift={gift_id} price={gift['price']}")

    await query.edit_message_text(
        f"🎁 购买成功！\n\n"
        f"礼物：{gift['name']}\n"
        f"金额：¥{gift['price']}\n\n"
        f"💝 她收到你的心意一定会很开心的～"
    )
