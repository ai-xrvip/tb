"""对话管理命令 —— /clear /export /reset /retry"""
import json
import io
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes
from config import config
from database import db
from roles import ROLES
from utils.logger import logger


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /clear —— 清空当前对话历史 """
    user = update.effective_user
    user_id = user.id
    db.create_user(user_id)
    db.update_chat_history(user_id, [])
    await update.message.reply_text("🗑️ 对话历史已清空，我们重新开始吧～")


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /export —— 导出对话历史为 JSON 文件 """
    user = update.effective_user
    user_id = user.id
    db.create_user(user_id)

    history = db.get_chat_history(user_id)
    if not history:
        await update.message.reply_text("📝 暂无对话历史。")
        return

    user_data = db.get_user(user_id)
    role_id = user_data.get("current_role", "xiaolu")
    role_name = ROLES.get(role_id, {}).get("name", role_id)

    export_data = {
        "user_id": user_id,
        "role": role_name,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "message_count": len(history),
        "messages": history,
    }

    json_str = json.dumps(export_data, ensure_ascii=False, indent=2)
    file_obj = io.BytesIO(json_str.encode("utf-8"))
    file_obj.name = f"chat_history_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    await update.message.reply_document(
        document=file_obj,
        caption=f"📤 {role_name} 的对话历史 ({len(history)} 条消息)",
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /reset —— 完全重置用户数据（清空历史 + 重置角色） """
    user = update.effective_user
    user_id = user.id
    db.create_user(user_id)
    db.update_chat_history(user_id, [])
    db.update_role(user_id, "xiaolu")
    await update.message.reply_text(
        "🔄 已完全重置！\n"
        "💬 对话历史已清空\n"
        "🎭 角色已恢复默认\n"
        "试试 `/start` 重新选择角色吧～"
    )


async def cmd_retry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /retry —— 重试上一次对话（移除最后一条 AI 回复重新生成） """
    user = update.effective_user
    user_id = user.id
    db.create_user(user_id)

    history = db.get_chat_history(user_id)
    if not history:
        await update.message.reply_text("📝 没有可重试的对话～")
        return

    # 移除最后一条 assistant 消息
    if history and history[-1]["role"] == "assistant":
        history.pop()

    # 找到最后一条 user 消息
    last_user_msg = None
    for m in reversed(history):
        if m["role"] == "user":
            last_user_msg = m["content"]
            break

    if last_user_msg is None:
        await update.message.reply_text("📝 没有找到可重试的消息～")
        return

    # 保存修改后的历史
    db.update_chat_history(user_id, history)

    # Prompt user to resend (avoids rate-limit bypass)
    prompt = last_user_msg[:200]
    await update.message.reply_text(
        "Message undone! Send it again:\n\n" + prompt
    )
