"""群聊 @提及 处理器 —— 参考 Openaibot 的群聊设计

Bot 在群聊中被 @ 时自动回复，支持上下文隔离。
"""
import re
from telegram import Update
from telegram.ext import ContextTypes
from config import config
from database import db
from roles import ROLES, get_role
from utils.logger import logger
from providers import get_provider, ProviderType
from providers.base import ProviderError, RateLimitError, TokenLimitError


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理群聊中的 @提及 消息"""
    msg = update.message
    if not msg or not msg.text:
        return

    bot_username = context.bot.username
    # 检查是否 @了 bot
    if f"@{bot_username}" not in msg.text:
        return

    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id
    user_text = msg.text.strip()

    # 移除 @bot 部分
    user_text = re.sub(rf'@{bot_username}\s*', '', user_text).strip()
    if not user_text:
        user_text = "你好呀～"

    # 确保用户存在
    db.create_user(user_id)
    user_data = db.get_user(user_id)
    role_id = user_data.get("current_role", "xiaolu")
    role = get_role(role_id)

    # 构建 messages（群聊上下文精简，不带历史）
    system_prompt = role["system_prompt"] if role else ""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": f"当前在群聊中，用户是 {user.first_name}，请简短回复（200字以内）。"},
        {"role": "user", "content": user_text},
    ]

    await update.message.chat.send_action(action="typing")

    try:
        provider_type = config.LLM_PROVIDER or "deepseek"
        if provider_type == "openai":
            provider = get_provider(
                ProviderType.OPENAI, api_key=config.OPENAI_API_KEY,
                base_url=config.OPENAI_BASE_URL, model=config.OPENAI_MODEL,
            )
        else:
            provider = get_provider(
                ProviderType.DEEPSEEK, api_key=config.DEEPSEEK_API_KEY,
                base_url=config.DEEPSEEK_BASE_URL, model=config.DEEPSEEK_MODEL,
            )

        reply = await provider.chat(messages=messages, max_tokens=400, temperature=0.9)
        if reply:
            # 回复时引用原消息
            await update.message.reply_text(reply, reply_to_message_id=msg.message_id)
    except RateLimitError:
        await update.message.reply_text("⏳ 太频繁啦～", reply_to_message_id=msg.message_id)
    except ProviderError as e:
        logger.error(f"group chat error user_id={user_id}: {e}")
        await update.message.reply_text("😢 稍等一下～", reply_to_message_id=msg.message_id)
