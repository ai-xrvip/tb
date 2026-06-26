"""
纪念品销售模块 —— 未启用原味的15个角色卖专属定制周边
完全复刻 yuanwei.py 的流程，只改商品描述和图片目录

流程:
1. 消息数达到20+ → 概率触发
2. Bot 发送商品图+话术+"看看吗？"按钮
3. 用户点击 → 展示清单+价格
4. 用户选择 → 地址收集(姓名→电话→地址→确认)
5. 确认后保存订单到 keepsake_orders 表
"""
import os
import random
import uuid
import time
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from config import config
from database import db
from roles import ROLES, KEEPSAKE_ROLES
from utils.logger import logger

# Conversation states
ASK_NAME, ASK_PHONE, ASK_ADDRESS, CONFIRM = range(4, 8)

# ── 触发规则 ──
# 达到T3后（150条解锁完全信任）才有概率触发，忠诚度收割
TRIGGER_MIN = 150     # 150条后才触发
TRIGGER_PROB = 0.10   # 10%概率


def _pick_keepsake_image(folder: str) -> str | None:
    """从 keepsake/{folder}/ 随机选一张图"""
    k_dir = Path(__file__).parent.parent / "media" / "paywall" / "keepsake" / folder
    if not k_dir.exists():
        return None
    files = [f for f in k_dir.glob("*") if f.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]]
    if not files:
        return None
    return str(random.choice(files))


def _keepsake_item_keyboard(role_id: str) -> InlineKeyboardMarkup:
    """生成商品清单按钮"""
    ks = KEEPSAKE_ROLES.get(role_id)
    if not ks:
        return InlineKeyboardMarkup([])
    buttons = []
    for item in ks["items"]:
        buttons.append([
            InlineKeyboardButton(
                f"{item['name']} — ¥{item['price']}",
                callback_data=f"keepsake:buy:{role_id}:{item['id']}"
            )
        ])
    buttons.append([InlineKeyboardButton("「下次再说吧」", callback_data="keepsake:cancel")])
    return InlineKeyboardMarkup(buttons)


async def try_trigger_keepsake(update: Update, user_id: int, role_id: str, total_msgs: int) -> bool:
    """
    在 AI 回复后调用，检测是否触发纪念品销售
    """
    ks = KEEPSAKE_ROLES.get(role_id)
    if not ks or not ks.get("enabled"):
        return False

    if total_msgs < TRIGGER_MIN:
        return False

    if db.has_keepsake_triggered(user_id, role_id):
        return False

    if random.random() > TRIGGER_PROB:
        return False

    db.mark_keepsake_triggered(user_id, role_id)

    items = ks["items"]
    showcase_item = random.choice(items)
    # 每个角色独立配图文件夹：keepsake/{role_id}/
    image_path = _pick_keepsake_image(role_id)

    role = ROLES.get(role_id, {})
    role_name = role.get("name", role_id)

    # 话术（不同角色语气）
    prompts = [
        f"悄悄跟你说哦，我最近做了点小东西——{showcase_item['name']}，是专门为特别的人准备的！你要不要看看呀？",
        f"那个…我做了一样东西，觉得你会喜欢的💕 是一种特别定制的{showcase_item['name']}，只限量的哦～",
        f"嘿嘿，有件好玩的事告诉你！我弄了一批{showcase_item['name']}，上面有我的小心思…想知道是什么吗？",
    ]
    prompt = random.choice(prompts)

    caption = f"🎁 {role_name}\n\n{prompt}"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("👀 看看是什么", callback_data=f"keepsake:info:{role_id}"),
        InlineKeyboardButton("下次再说", callback_data="keepsake:cancel"),
    ]])

    if image_path:
        try:
            with open(image_path, "rb") as img:
                await update.message.reply_photo(
                    photo=img, caption=caption, reply_markup=keyboard,
                )
            logger.info(f"Keepsake triggered: user={user_id} role={role_id} item={showcase_item['name']}")
            return True
        except Exception as e:
            logger.warning(f"Keepsake image failed: {e}")

    await update.message.reply_text(caption, reply_markup=keyboard)
    return True


# ── 回调处理 ──

async def handle_keepsake_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理纪念品相关回调"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data == "keepsake:cancel":
        await query.edit_message_caption(
            caption="好呀～不着急，等你想看的时候随时告诉我哦～",
            reply_markup=None,
        )
        return

    if data.startswith("keepsake:info:"):
        role_id = data.split(":")[2]
        ks = KEEPSAKE_ROLES.get(role_id)
        role = ROLES.get(role_id, {})
        role_name = role.get("name", role_id)

        if not ks:
            await query.edit_message_caption(caption="暂时没货了哦～", reply_markup=None)
            return

        text = f"🎁 {role_name} 的专属周边\n\n"
        text += "这些都是我特意为你准备的小礼物～\n"
        text += "每一份都带着我的心思，只给懂的人。\n\n"
        text += "━━━━━━━━━━━━━\n"
        for item in ks["items"]:
            text += f"✨ {item['name']}\n"
            text += f"   💰 ¥{item['price']}\n\n"
        text += "━━━━━━━━━━━━━\n"
        text += "选好后告诉我收货信息，真的会寄出的哦～"

        items = ks["items"]
        if items:
            img_path = _pick_keepsake_image(role_id)
            if img_path:
                try:
                    with open(img_path, "rb") as img:
                        await query.message.reply_photo(
                            photo=img, caption=text,
                            reply_markup=_keepsake_item_keyboard(role_id),
                        )
                    await query.delete_message()
                    return
                except Exception:
                    pass

        await query.edit_message_caption(caption=text, reply_markup=_keepsake_item_keyboard(role_id))
        return

    if data.startswith("keepsake:buy:"):
        parts = data.split(":")
        role_id = parts[2]
        item_id = parts[3]

        ks = KEEPSAKE_ROLES.get(role_id)
        if not ks:
            await query.edit_message_caption(caption="出错了，重新试试吧～", reply_markup=None)
            return ConversationHandler.END

        item = next((i for i in ks["items"] if i["id"] == item_id), None)
        if not item:
            await query.edit_message_caption(caption="这个已经没有了～", reply_markup=None)
            return ConversationHandler.END

        role = ROLES.get(role_id, {})
        context.user_data["keepsake_role_id"] = role_id
        context.user_data["keepsake_item"] = item
        context.user_data["keepsake_role_name"] = role.get("name", role_id)

        await query.edit_message_caption(
            caption=(
                f"你选择了：{item['name']}\n"
                f"价格：¥{item['price']}\n\n"
                f"这个是真的会寄给你的哦～\n"
                f"请告诉我你的【收件人姓名】："
            ),
            reply_markup=None,
        )
        return ASK_NAME

    return ConversationHandler.END


# ── ConversationHandler 各步骤 ──

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["keepsake_name"] = update.message.text.strip()
    await update.message.reply_text(
        "收到～接下来请告诉我你的【手机号码】：\n"
        "（仅用于发货，不会外泄的哦）"
    )
    return ASK_PHONE


async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not phone.isdigit() or len(phone) < 11:
        await update.message.reply_text("格式好像不太对呢，请重新输入11位手机号：")
        return ASK_PHONE
    context.user_data["keepsake_phone"] = phone
    await update.message.reply_text(
        "好的～最后一步啦，请告诉我你的【收货地址】：\n"
        "（省/市/区/详细地址，不然快递小哥会迷路的～）"
    )
    return ASK_ADDRESS


async def ask_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    context.user_data["keepsake_address"] = address

    item = context.user_data["keepsake_item"]
    name = context.user_data["keepsake_name"]
    phone = context.user_data["keepsake_phone"]
    role_name = context.user_data.get("keepsake_role_name", "")

    confirm_text = (
        f"📦 订单确认\n\n"
        f"物品：{item['name']}\n"
        f"价格：¥{item['price']}\n"
        f"━━━━━━━━━━━━━\n"
        f"收件人：{name}\n"
        f"电话：{phone}\n"
        f"地址：{address}\n"
        f"━━━━━━━━━━━━━\n\n"
        f"确认无误的话，{role_name}会包装好寄出哦～\n"
        f"（目前测试阶段，不会真的扣款，信息会保留～）"
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ 确认下单", callback_data="keepsake:confirm"),
        InlineKeyboardButton("❌ 取消", callback_data="keepsake:cancel_order"),
    ]])

    await update.message.reply_text(confirm_text, reply_markup=keyboard)
    return CONFIRM


async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "keepsake:cancel_order":
        await query.edit_message_text("好的，订单已取消。想看的时候再告诉我呀～")
        _cleanup(context)
        return ConversationHandler.END

    user_id = query.from_user.id
    item = context.user_data["keepsake_item"]
    name = context.user_data["keepsake_name"]
    phone = context.user_data["keepsake_phone"]
    address = context.user_data["keepsake_address"]
    role_id = context.user_data["keepsake_role_id"]

    order_id = f"KS{int(time.time())}{uuid.uuid4().hex[:4].upper()}"
    db.create_keepsake_order(order_id, user_id, role_id, item["id"], item["name"], item["price"],
                             name, phone, address)

    role_name = context.user_data.get("keepsake_role_name", "")

    await query.edit_message_text(
        f"🎉 下单成功！\n\n"
        f"订单号：{order_id}\n"
        f"物品：{item['name']}\n"
        f"━━━━━━━━━━━━━\n\n"
        f"{role_name}说马上给你准备，包好就寄出～\n"
        f"请耐心等待哦 💝\n\n"
        f"（测试阶段免费体验，正式上线后会通知支付～）"
    )

    logger.info(f"Keepsake order created: {order_id} user={user_id} role={role_id} item={item['name']}")
    _cleanup(context)
    return ConversationHandler.END


async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("好的，订单已取消～什么时候想看了，随时找我呀 💕")
    _cleanup(context)
    return ConversationHandler.END


def _cleanup(context: ContextTypes.DEFAULT_TYPE):
    for key in ["keepsake_role_id", "keepsake_item", "keepsake_role_name",
                "keepsake_name", "keepsake_phone", "keepsake_address"]:
        context.user_data.pop(key, None)


def get_keepsake_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_keepsake_callback, pattern="^keepsake:"),
        ],
        states={
            ASK_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name),
                CallbackQueryHandler(handle_keepsake_callback, pattern="^keepsake:"),
            ],
            ASK_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone),
                CallbackQueryHandler(handle_keepsake_callback, pattern="^keepsake:"),
            ],
            ASK_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_address),
                CallbackQueryHandler(handle_keepsake_callback, pattern="^keepsake:"),
            ],
            CONFIRM: [
                CallbackQueryHandler(confirm_order, pattern="^keepsake:(confirm|cancel_order)$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_order),
            MessageHandler(filters.ALL, cancel_order),
        ],
        per_message=False,
    )
