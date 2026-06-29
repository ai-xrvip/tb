# -*- coding: utf-8 -*-
"""
礼物/支付模块 —— /gifts 查看 + 内联按钮购买
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import config
from database import db
from utils.logger import logger

# 礼物清单
GIFTS = [
    {"id": "flower", "name": "\U0001f339 玫瑰花束", "price": 9.9, "desc": "一束鲜红的玫瑰，表达你温柔的心意"},
    {"id": "chocolate", "name": "\U0001f36b 手工巧克力", "price": 19.9, "desc": "精致的比利时手工巧克力"},
    {"id": "perfume", "name": "\U0001f490 香水礼盒", "price": 49.9, "desc": "法国进口香水，优雅迷人"},
    {"id": "necklace", "name": "\U0001f48e 水晶项链", "price": 99.9, "desc": "闪耀的水晶，配得上她的美丽"},
    {"id": "dress", "name": "\U0001f457 设计师连衣裙", "price": 199.9, "desc": "限量款连衣裙，让她成为最耀眼的存在"},
    {"id": "diamond", "name": "\U0001f48d 钻戒", "price": 520.0, "desc": "永恒的承诺，非她莫属"},
]


def _gift_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for g in GIFTS:
        buttons.append([
            InlineKeyboardButton(
                f"{g['name']} - \U000000a5{g['price']}",
                callback_data=f"gift:{g['id']}",
            )
        ])
    return InlineKeyboardMarkup(buttons)


async def cmd_gift_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看礼物清单"""
    user = update.effective_user
    user_id = user.id
    db.create_user(user_id)

    owned = db.get_user_gifts(user_id)
    owned_ids = {g["gift_id"] for g in owned}

    text = "\U0001f381 **商城**\n\n"
    for g in GIFTS:
        status = " ✅ 已拥有" if g["id"] in owned_ids else ""
        text += f"{g['name']} - \U000000a5{g['price']}{status}\n  _{g['desc']}_\n\n"

    text += "点击下方按钮购买礼物~"

    await update.message.reply_text(text, reply_markup=_gift_keyboard())


async def gift_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理礼物购买：测试模式免费，生产模式走易支付"""
    query = update.callback_query
    await query.answer()

    gift_id = query.data.replace("gift:", "")
    gift = next((g for g in GIFTS if g["id"] == gift_id), None)
    if not gift:
        await query.edit_message_text("❌ 礼物不存在")
        return

    user_id = query.from_user.id
    db.create_user(user_id)

    if db.has_gift(user_id, gift_id):
        await query.answer("你已经拥有这个礼物啦~", show_alert=True)
        return

    gift_name = gift["name"]
    gift_price = gift["price"]

    # 测试模式：免费
    if config.PAYMENT_MODE == "test":
        import uuid, time
        oid = f"GF{int(time.time())}{uuid.uuid4().hex[:6].upper()}"
        db.create_payment_order(oid, user_id, "gift", gift_name, gift_price, 0)
        db.mark_order_paid(oid)
        db.add_gift_purchase(user_id, gift_id, gift_name, gift_price)
        logger.info(f"TEST gift: user={user_id} gift={gift_id}")
        await query.edit_message_text(
            f"\U0001f389 送出 {gift_name}\n"
            f"\U0001f4b0 \U000000a5{gift_price}\n\n"
            f"她收到你的礼物啦~\n\n"
            f"\U0001f52c 测试模式：免费送出，尽情体验~"
        )
        return

    # 生产模式：易支付
    import hashlib
    from urllib.parse import urlencode
    from handlers.payment import _generate_order_id
    from config import config as _cfg

    oid = _generate_order_id()
    db.create_payment_order(oid, user_id, "gift", gift_name, gift_price, 0)

    params = {
        "pid": _cfg.EPAY_PID,
        "type": "alipay",
        "out_trade_no": oid,
        "notify_url": _cfg.EPAY_NOTIFY_URL,
        "name": gift_name,
        "money": str(gift_price),
    }
    # EPay 标准签名: k=v&k=v&key=SECRET
    sign_str = "&".join(f"{k}={v}" for k, v in sorted(params.items())) + "&key=" + _cfg.EPAY_KEY
    params["sign"] = hashlib.md5(sign_str.encode()).hexdigest()
    params["sign_type"] = "MD5"
    pay_url = f"{_cfg.EPAY_URL}?{urlencode(params)}"

    await query.edit_message_text(
        f"\U0001f49d {gift_name}\n"
        f"\U0001f4b0 \U000000a5{gift_price}\n\n"
        f"\U0001f449 [点击这里支付]({pay_url})\n\n"
        f"支付完成后自动解锁，无需手动操作。"
    )
