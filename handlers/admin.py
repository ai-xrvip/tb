"""管理员面板 —— 广播、统计、用户管理

参考 chatgpt-on-wechat 和 karfly bot 的管理功能
"""
import asyncio
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes
from config import config
from database import db
from utils.logger import logger


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /broadcast <消息> —— 向所有用户广播消息 """
    user = update.effective_user
    if user.id not in config.ADMIN_IDS:
        await update.message.reply_text("⛔ 此命令仅限管理员使用。")
        return

    if not context.args:
        await update.message.reply_text("用法：`/broadcast <要广播的消息>`")
        return

    broadcast_text = " ".join(context.args)
    users = db.get_all_users()
    success_count = 0
    fail_count = 0

    status_msg = await update.message.reply_text(f"📢 开始广播给 {len(users)} 个用户...")

    for u in users:
        try:
            await context.bot.send_message(
                chat_id=u["user_id"],
                text=f"📢 **系统通知**\n\n{broadcast_text}",
            )
            success_count += 1
        except Exception as e:
            logger.warning(f"broadcast failed to {u['user_id']}: {e}")
            fail_count += 1
        # 速率控制
        if (success_count + fail_count) % 30 == 0:
            await asyncio.sleep(1)

    await status_msg.edit_text(
        f"📢 广播完成！\n"
        f"✅ 成功：{success_count}\n"
        f"❌ 失败：{fail_count}\n"
        f"📊 总计：{len(users)}"
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /stats —— 查看 Bot 统计信息 """
    user = update.effective_user
    if user.id not in config.ADMIN_IDS:
        await update.message.reply_text("⛔ 此命令仅限管理员使用。")
        return

    users = db.get_all_users()
    total_users = len(users)
    total_messages = sum(u.get("total_messages", 0) for u in users)
    vip_count = sum(1 for u in users if db.is_vip(u["user_id"]))

    codes = db.get_all_codes()
    total_codes = len(codes)
    used_codes = sum(1 for c in codes if c["is_used"])
    unused_codes = total_codes - used_codes

    # 今日新增
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_users = sum(1 for u in users if u.get("created_at", "").startswith(today)) if users else 0

    await update.message.reply_text(
        f"📊 **Bot 统计**\n\n"
        f"👥 总用户数：{total_users}\n"
        f"💬 总消息数：{total_messages}\n"
        f"💎 VIP 用户：{vip_count}\n"
        f"🆕 今日新增：{today_users}\n\n"
        f"🔑 激活码统计：\n"
        f"   总数：{total_codes}\n"
        f"   已用：{used_codes}\n"
        f"   剩余：{unused_codes}"
    )


async def cmd_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /user <user_id> —— 查看用户详情 """
    admin = update.effective_user
    if admin.id not in config.ADMIN_IDS:
        await update.message.reply_text("⛔ 此命令仅限管理员使用。")
        return

    if not context.args:
        await update.message.reply_text("用法：`/user <用户ID>`")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("用户ID必须是数字。")
        return

    u = db.get_user(target_id)
    if not u:
        await update.message.reply_text(f"❌ 未找到用户 {target_id}")
        return

    is_vip = db.is_vip(target_id)
    vip_text = f"✅ VIP 到期: {u.get('vip_expire', 'N/A')}" if is_vip else "❌ 非VIP"

    history = db.get_chat_history(target_id)
    history_count = len(history)

    gifts = db.get_user_gifts(target_id)

    await update.message.reply_text(
        f"👤 **用户详情**\n\n"
        f"🆔 ID: `{target_id}`\n"
        f"🎭 当前角色: {u.get('current_role', 'N/A')}\n"
        f"💬 总消息数: {u.get('total_messages', 0)}\n"
        f"🆓 剩余免费次数: {u.get('free_count', 0)}\n"
        f"💎 {vip_text}\n"
        f"📝 历史消息数: {history_count}\n"
        f"🎁 礼物数: {len(gifts)}"
    )


async def cmd_set_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /setvip <user_id> <days> —— 直接设置用户 VIP """
    admin = update.effective_user
    if admin.id not in config.ADMIN_IDS:
        await update.message.reply_text("⛔ 此命令仅限管理员使用。")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text("用法：`/setvip <用户ID> <天数>`")
        return

    try:
        target_id = int(context.args[0])
        days = int(context.args[1])
    except ValueError:
        await update.message.reply_text("参数必须是数字。")
        return

    db.create_user(target_id)
    db.set_vip(target_id, days)
    logger.info(f"admin {admin.id} set VIP for user {target_id}, {days} days")

    await update.message.reply_text(
        f"✅ 已为用户 `{target_id}` 设置 VIP {days} 天。"
    )


async def cmd_yuanwei_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /yworders —— 管理员查看原味订单 """
    user = update.effective_user
    if user.id not in config.ADMIN_IDS:
        await update.message.reply_text("⛔ 此命令仅限管理员使用。")
        return

    orders = db.get_all_yuanwei_orders()
    if not orders:
        await update.message.reply_text("📭 暂无原味订单。")
        return

    lines = []
    for o in orders[:20]:  # 最多显示20条
        status_icon = {"pending": "⏳", "paid": "✅", "shipped": "📦", "cancelled": "❌"}.get(o["status"], "❓")
        lines.append(
            f"{status_icon} `{o['order_id'][:8]}...` "
            f"用户:{o['user_id']} "
            f"角色:{o['role_id']} "
            f"物品:{o['item_name']} "
            f"¥{o['amount']} "
            f"状态:{o['status']}"
        )

    await update.message.reply_text(
        f"📋 **原味订单列表**（共 {len(orders)} 单，显示最近 20 单）\n\n" + "\n".join(lines)
    )
