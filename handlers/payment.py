"""渐进式付费解锁 —— 图片卡片+文字+点击送出按钮

支付流程:
1. 用户消息达到阈值 → Bot 发送图片卡片（角色照片+付费话术+点击送出按钮）
2. 用户点击「点击送出」→ 测试模式直接解锁 / 生产模式调用支付API
3. 解锁后 → 继续聊天 → 媒体照片随之开放

模式切换: .env 中 PAYMENT_MODE=test 或 production
"""
import os
import uuid
import hashlib
import time
from pathlib import Path
from urllib.parse import urlencode
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import config
from database import db
from roles import get_current_paywall, get_paywall, ROLES
from utils.logger import logger


# ── 模式配置 ──
PAYMENT_MODE = os.getenv("PAYMENT_MODE", "test")  # test / production

# 易支付配置（production 模式时使用）
EPAY_PID = os.getenv("EPAY_PID", "")
EPAY_KEY = os.getenv("EPAY_KEY", "")
EPAY_URL = os.getenv("EPAY_URL", "https://pay.example.com/submit.php")
EPAY_NOTIFY_URL = os.getenv("EPAY_NOTIFY_URL", "")


def _generate_order_id() -> str:
    return f"TG{int(time.time())}{uuid.uuid4().hex[:6].upper()}"


def _pick_paywall_image(role_id: str, item_name: str = "") -> str | None:
    """从角色 media 目录或 paywall 通用图库随机选一张作为付费卡片配图"""
    import random
    media_base = Path(__file__).parent.parent / "media"

    # 1. 优先从角色自己的照片目录选
    role_dir = media_base / role_id
    if role_dir.exists():
        for category in ["日常", "自拍", "穿搭", "表情", "通勤"]:
            cat_dir = role_dir / category
            if cat_dir.exists():
                files = [f for f in cat_dir.glob("*") if f.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]]
                if files:
                    return str(random.choice(files))

    # 2. 根据礼物名称匹配 paywall 通用图
    paywall_dir = media_base / "paywall"
    keyword_map = {
        "奶茶": "milk_tea", "咖啡": "coffee", "拿铁": "coffee",
        "啤酒": "beer", "原浆": "beer", "鸡尾酒": "cocktail", "威士忌": "cocktail",
        "花": "flowers", "玫瑰": "flowers", "鲜花": "flowers",
        "蛋糕": "cake", "甜点": "cake", "甜品": "cake", "可丽露": "cake",
        "火锅": "hotpot", "美食": "hotpot", "海鲜": "hotpot", "面": "hotpot",
        "礼物": "gift_box", "礼盒": "gift_box",
        "书": "book", "教材": "book", "古籍": "book",
        "香水": "perfume",
        "甑糕": "cake", "巧克力": "cake", "冰淇淋": "cake",
        "蛋白粉": "milk_tea",  # generic drink
    }
    for keyword, img_name in keyword_map.items():
        if keyword in item_name:
            img_path = paywall_dir / f"{img_name}.jpg"
            if img_path.exists():
                return str(img_path)

    # 3. 随机选一张 paywall 通用图
    paywall_files = list(paywall_dir.glob("*.jpg"))
    if paywall_files:
        return str(random.choice(paywall_files))

    return None


async def send_paywall_card(update: Update, user_id: int, role_id: str, total_msgs: int) -> bool:
    """
    发送付费卡片 —— 图片+文字+点击送出按钮
    这是付费提示的统一入口，消息处理器和AI回复后触发都调用此函数
    """
    current_tier = db.get_unlock_tier(user_id, role_id)
    pw = get_current_paywall(role_id, total_msgs, current_tier)

    if not pw:
        return False

    role = ROLES.get(role_id, {})
    role_name = role.get("name", role_id)
    item_name = pw["item_name"]
    price = pw["price"]
    tier = pw["tier"]

    # 构建按钮
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"🎁 点击送出",
            callback_data=f"pay:{role_id}:{tier}"
        )
    ]])

    # 构建文字内容
    caption = (
        f"{pw['paywall_prompt']}\n\n"
        f"━━━━━━━━━━━━━\n"
        f"🎁 {item_name}\n"
        f"💰 ¥{price}"
    )
    if PAYMENT_MODE == "test":
        caption += "\n🔬 测试模式：点击即送，免费解锁～"

    # 尝试发送图片卡片
    image_path = _pick_paywall_image(role_id, item_name)
    if image_path:
        try:
            with open(image_path, "rb") as img:
                await update.message.reply_photo(
                    photo=img,
                    caption=caption,
                    reply_markup=keyboard,
                )
            return True
        except Exception as e:
            logger.warning(f"Failed to send paywall image for {role_id}: {e}")

    # 没有图片则发送纯文字卡片
    await update.message.reply_text(
        caption,
        reply_markup=keyboard,
    )
    return True


async def handle_paywall_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理「点击送出」按钮回调 —— pattern: pay:{role_id}:{tier}"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data.replace("pay:", "").split(":", 1)
    role_id = data[0]
    try:
        tier = int(data[1])
    except (ValueError, IndexError):
        await query.answer("? ???????", show_alert=True)
        return

    paywalls = get_paywall(role_id)
    pw = next((p for p in paywalls if p["tier"] == tier), None)
    if not pw:
        await query.answer("❌ 付费项目不存在。", show_alert=True)
        return

    db.create_user(user_id)

    # 检查是否已经解锁
    current_tier = db.get_unlock_tier(user_id, role_id)
    if current_tier >= tier:
        await query.answer("✅ 你已经解锁过啦～", show_alert=True)
        return

    role = ROLES.get(role_id, {})
    role_name = role.get("name", role_id)

    if PAYMENT_MODE == "test":
        # ── 测试模式：直接解锁 ──
        order_id = _generate_order_id()
        db.create_payment_order(order_id, user_id, role_id, pw["item_name"], pw["price"], tier)
        db.mark_order_paid(order_id)

        # 解锁后解锁了什么内容
        unlock_hints = {
            1: "💬 继续无限畅聊\n📸 解锁：姿态/旅游/夜景/起床/派对",
            2: "💬 继续无限畅聊\n🔞 解锁：性感/泳装/沐浴/情趣",
            3: "💬 继续无限畅聊\n🔓 解锁：全部私密内容",
        }

        new_text = (
            f"🎉 送出成功！\n\n"
            f"💝 {role_name} 收到你的{ pw['item_name'] }啦～\n"
            f"她看起来很开心呢！\n\n"
            f"{unlock_hints.get(tier, '💬 继续无限畅聊')}\n\n"
            f"🔬 测试模式：免费解锁，尽情体验吧～"
        )

        try:
            await query.edit_message_caption(
                caption=new_text,
                reply_markup=None,  # 移除按钮
            )
        except Exception:
            # 如果原消息是纯文字（没有图片）
            await query.edit_message_text(
                text=new_text,
            )

        logger.info(f"TEST: user {user_id} unlocked {role_id} tier {tier}")

    else:
        # ── 生产模式：调用易支付 ──
        order_id = _generate_order_id()
        db.create_payment_order(order_id, user_id, role_id, pw["item_name"], pw["price"], tier)

        params = {
            "pid": EPAY_PID,
            "type": "alipay",
            "out_trade_no": order_id,
            "notify_url": EPAY_NOTIFY_URL,
            "name": pw["item_name"],
            "money": str(pw["price"]),
        }
        sign_str = "&".join(f"{k}={v}" for k, v in sorted(params.items())) + EPAY_KEY
        params["sign"] = hashlib.md5(sign_str.encode()).hexdigest()
        params["sign_type"] = "MD5"
        pay_url = f"{EPAY_URL}?{urlencode(params)}"

        new_text = (
            f"💝 {role_name} 期待你的心意～\n\n"
            f"🎁 {pw['item_name']}\n"
            f"💰 ¥{pw['price']}\n\n"
            f"👉 [点击这里支付]({pay_url})\n\n"
            f"支付完成后自动解锁，无需手动操作。"
        )
        try:
            await query.edit_message_caption(caption=new_text, reply_markup=None)
        except Exception:
            await query.edit_message_text(text=new_text)


# ── Webhook: 易支付回调 ──
async def handle_epay_callback(order_id: str, trade_status: str):
    """处理易支付异步回调"""
    if trade_status != "TRADE_SUCCESS":
        logger.warning(f"epay callback: order {order_id} status={trade_status}")
        return
    db.mark_order_paid(order_id)
    logger.info(f"epay callback: order {order_id} paid and unlocked")
