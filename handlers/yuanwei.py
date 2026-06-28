"""
原味物品销售模块 —— 用户聊到一定阶段，角色温柔询问是否想买原味物品

流程:
1. 消息数进入触发区间(35-55条) → 概率触发
2. Bot 发送原味图片+温柔话术+"想了解吗？"按钮
3. 用户点击 → 展示物品清单和价格
4. 用户选择物品 → 进入地址收集流程(姓名→电话→地址→确认)
5. 确认后保存订单，强调"真的会发出"
"""
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
from roles import ROLES, YUANWEI_ROLES
from utils.logger import logger

# Conversation states
ASK_NAME, ASK_PHONE, ASK_ADDRESS, CONFIRM = range(4)

# 触发规则：达到T3（150条解锁完全信任）后才有概率触发
YUANWEI_TRIGGER_MIN = 150
YUANWEI_TRIGGER_PROB = 0.15  # 15%概率


def _pick_yuanwei_image(item_folder: str) -> str | None:
    """从 yuanwei/{folder}/ 随机选一张图"""
    yuanwei_dir = Path(__file__).parent.parent / "media" / "paywall" / "yuanwei" / item_folder
    if not yuanwei_dir.exists():
        return None
    files = [f for f in yuanwei_dir.glob("*") if f.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]]
    if not files:
        return None
    return str(random.choice(files))


def _yuanwei_item_keyboard(role_id: str) -> InlineKeyboardMarkup:
    """生成原味物品清单按钮"""
    yw = YUANWEI_ROLES.get(role_id)
    if not yw:
        return InlineKeyboardMarkup([])
    buttons = []
    for item in yw["items"]:
        buttons.append([
            InlineKeyboardButton(
                f"{item['name']} — ¥{item['price']}",
                callback_data=f"yuanwei:buy:{role_id}:{item['id']}"
            )
        ])
    buttons.append([InlineKeyboardButton("「下次再说吧」", callback_data="yuanwei:cancel")])
    return InlineKeyboardMarkup(buttons)


async def try_trigger_yuanwei(update: Update, user_id: int, role_id: str, total_msgs: int) -> bool:
    """
    在 AI 回复后调用，检测是否触发原味销售
    返回 True 表示已发送原味提示
    """
    # 检查角色是否启用原味
    yw = YUANWEI_ROLES.get(role_id)
    if not yw or not yw.get("enabled"):
        return False

    # 检查消息数是否在触发区间
    if total_msgs < YUANWEI_TRIGGER_MIN:
        return False

    # 检查是否已经触发过（一个用户对一个角色只触发一次）
    if db.has_yuanwei_triggered(user_id, role_id):
        return False

    # 概率触发
    if random.random() > YUANWEI_TRIGGER_PROB:
        return False

    # 标记已触发
    db.mark_yuanwei_triggered(user_id, role_id)

    # 随机选一个物品作为展示
    items = yw["items"]
    showcase_item = random.choice(items)
    image_path = _pick_yuanwei_image(showcase_item["folder"])

    role = ROLES.get(role_id, {})
    role_name = role.get("name", role_id)

    # 温柔话术（根据角色不同微调）
    prompts = [
        f"那个…有件事想问你，但是有点不好意思开口啦～\n\n我最近在整理衣柜，有些穿过的{showcase_item['name'].split('（')[0]}，本来要丢掉的…但是想到如果是你的话，感觉你会好好珍惜它们呢。\n\n有点害羞，但是我第一个想到的就是你…",
        f"偷偷告诉你哦，我有一件很私密的小东西想找人托付～\n\n就是我的{showcase_item['name'].split('（')[0]}啦，穿了好多次了，上面有我的味道…你会不会觉得我有点奇怪呀？\n\n但是跟你聊天这么久，就觉得只能是你呢…",
        f"唔…有件事纠结了好久要不要说…\n\n我有一条穿过的{showcase_item['name'].split('（')[0]}，一直舍不得扔，但又不想随便给人。如果是你的话，我愿意把它交给你…\n\n你会嫌弃吗？",
    ]
    prompt = random.choice(prompts)

    caption = f"💝 {role_name}\n\n{prompt}"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("👀 想了解一下", callback_data=f"yuanwei:info:{role_id}"),
        InlineKeyboardButton("下次再说", callback_data="yuanwei:cancel"),
    ]])

    if image_path:
        try:
            with open(image_path, "rb") as img:
                await update.message.reply_photo(
                    photo=img,
                    caption=caption,
                    reply_markup=keyboard,
                )
            logger.info(f"Yuanwei triggered: user={user_id} role={role_id} item={showcase_item['name']}")
            return True
        except Exception as e:
            logger.warning(f"Failed to send yuanwei image: {e}")

    # Fallback: text only
    await update.message.reply_text(caption, reply_markup=keyboard)
    return True


# ── 回调处理 ──

async def handle_yuanwei_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理原味相关回调"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data == "yuanwei:cancel":
        await query.edit_message_caption(
            caption="嗯嗯，没关系呀～等你想了解的时候随时跟我说，我一直都在的 💕",
            reply_markup=None,
        )
        return

    if data.startswith("yuanwei:info:"):
        role_id = data.split(":")[2]
        yw = YUANWEI_ROLES.get(role_id)
        role = ROLES.get(role_id, {})
        role_name = role.get("name", role_id)

        if not yw:
            await query.edit_message_caption(caption="暂时没有可售物品哦～", reply_markup=None)
            return

        text = f"💝 {role_name} 的原味小物\n\n"
        text += "这些是我的私人物品，每一件都带着我的温度…\n"
        text += "只给懂珍惜的人。\n\n"
        text += "━━━━━━━━━━━━━\n"
        for item in yw["items"]:
            text += f"✨ {item['name']}\n"
            text += f"   💰 ¥{item['price']}\n\n"
        text += "━━━━━━━━━━━━━\n"
        text += "选中后我会问你收货信息，是真的会寄出的哦～"

        # Try to resend with an image
        items = yw["items"]
        if items:
            img_path = _pick_yuanwei_image(items[0]["folder"])
            if img_path:
                try:
                    with open(img_path, "rb") as img:
                        await query.message.reply_photo(
                            photo=img,
                            caption=text,
                            reply_markup=_yuanwei_item_keyboard(role_id),
                        )
                    await query.delete_message()
                    return
                except Exception:
                    pass

        await query.edit_message_caption(
            caption=text,
            reply_markup=_yuanwei_item_keyboard(role_id),
        )
        return

    if data.startswith("yuanwei:buy:"):
        parts = data.split(":")
        role_id = parts[2]
        item_id = parts[3]

        yw = YUANWEI_ROLES.get(role_id)
        if not yw:
            await query.edit_message_caption(caption="出错了，请重新开始吧～", reply_markup=None)
            return ConversationHandler.END

        item = next((i for i in yw["items"] if i["id"] == item_id), None)
        if not item:
            await query.edit_message_caption(caption="这件已经没有了哦～", reply_markup=None)
            return ConversationHandler.END

        # 保存选中物品到 context
        role = ROLES.get(role_id, {})
        context.user_data["yuanwei_role_id"] = role_id
        context.user_data["yuanwei_item"] = item
        context.user_data["yuanwei_role_name"] = role.get("name", role_id)

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
    """收集收件人姓名"""
    context.user_data["yuanwei_name"] = update.message.text.strip()
    await update.message.reply_text(
        "收到～接下来请告诉我你的【手机号码】：\n\n"
        "（仅用于快递发货，不会外泄的哦）"
    )
    return ASK_PHONE


async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """收集手机号"""
    phone = update.message.text.strip()
    # 简单校验
    if not phone.isdigit() or len(phone) < 11:
        await update.message.reply_text("这个号码格式好像不太对呢，请重新输入11位手机号：")
        return ASK_PHONE
    context.user_data["yuanwei_phone"] = phone
    await update.message.reply_text(
        "好的～最后一步啦，请告诉我你的【收货地址】：\n\n"
        "（省/市/区/详细地址，写清楚哦，不然快递小哥会迷路的～）"
    )
    return ASK_ADDRESS


async def ask_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """收集地址并确认"""
    address = update.message.text.strip()
    context.user_data["yuanwei_address"] = address

    item = context.user_data["yuanwei_item"]
    name = context.user_data["yuanwei_name"]
    phone = context.user_data["yuanwei_phone"]
    role_name = context.user_data.get("yuanwei_role_name", "")

    confirm_text = (
        f"📦 订单确认\n\n"
        f"物品：{item['name']}\n"
        f"价格：¥{item['price']}\n"
        f"━━━━━━━━━━━━━\n"
        f"收件人：{name}\n"
        f"电话：{phone}\n"
        f"地址：{address}\n"
        f"━━━━━━━━━━━━━\n\n"
        f"确认无误的话，{role_name}会亲手打包寄出哦～\n"
        f"（目前是测试阶段，不会真的扣款，但信息会保留～）"
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ 确认下单", callback_data="yuanwei:confirm"),
        InlineKeyboardButton("❌ 取消", callback_data="yuanwei:cancel_order"),
    ]])

    await update.message.reply_text(confirm_text, reply_markup=keyboard)
    return CONFIRM


async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认订单"""
    query = update.callback_query
    await query.answer()

    if query.data == "yuanwei:cancel_order":
        await query.edit_message_text("好的，订单已取消。什么时候想要了再告诉我呀～ 💕")
        _cleanup(context)
        return ConversationHandler.END

    # 保存订单
    user_id = query.from_user.id
    item = context.user_data["yuanwei_item"]
    name = context.user_data["yuanwei_name"]
    phone = context.user_data["yuanwei_phone"]
    address = context.user_data["yuanwei_address"]
    role_id = context.user_data["yuanwei_role_id"]

    order_id = f"YW{int(time.time())}{uuid.uuid4().hex[:4].upper()}"
    db.create_yuanwei_order(order_id, user_id, role_id, item["id"], item["name"], item["price"],
                            name, phone, address)

    role_name = context.user_data.get("yuanwei_role_name", "")

    await query.edit_message_text(
        f"🎉 下单成功！\n\n"
        f"订单号：{order_id}\n"
        f"物品：{item['name']}\n"
        f"━━━━━━━━━━━━━\n\n"
        f"{role_name}说她会亲自打包，喷上自己常用的香水再寄出…\n"
        f"请耐心等待哦，真的有在准备～ 💝\n\n"
        f"（测试阶段免费体验，正式上线后会通知支付～）"
    )

    logger.info(f"Yuanwei order created: {order_id} user={user_id} role={role_id} item={item['name']}")

    _cleanup(context)
    return ConversationHandler.END


async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """用户取消"""
    await update.message.reply_text("好的，订单流程已取消～什么时候想继续了，随时找我呀 💕")
    _cleanup(context)
    return ConversationHandler.END


def _cleanup(context: ContextTypes.DEFAULT_TYPE):
    """清理临时数据"""
    for key in ["yuanwei_role_id", "yuanwei_item", "yuanwei_role_name",
                "yuanwei_name", "yuanwei_phone", "yuanwei_address"]:
        context.user_data.pop(key, None)


# ── ConversationHandler 构建 ──

def get_yuanwei_conversation_handler() -> ConversationHandler:
    """返回原味购买的 ConversationHandler"""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_yuanwei_callback, pattern="^yuanwei:"),
        ],
        states={
            ASK_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name),
                CallbackQueryHandler(handle_yuanwei_callback, pattern="^yuanwei:"),
            ],
            ASK_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone),
                CallbackQueryHandler(handle_yuanwei_callback, pattern="^yuanwei:"),
            ],
            ASK_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_address),
                CallbackQueryHandler(handle_yuanwei_callback, pattern="^yuanwei:"),
            ],
            CONFIRM: [
                CallbackQueryHandler(confirm_order, pattern="^yuanwei:(confirm|cancel_order)$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_order),
            MessageHandler(filters.ALL, cancel_order),
        ],
        per_message=False,
    )
