"""
Speech-to-text via Cloudflare Workers AI (free, ~3000 req/day)
"""
import io
import base64
import random
import httpx
from telegram import Update
from telegram.ext import ContextTypes
from config import config
from utils.logger import logger

# Max voice duration allowed (seconds)
MAX_VOICE_DURATION = 60
# API timeout (seconds)
STT_TIMEOUT = 10


async def _transcribe_cf(ogg_bytes: bytes) -> str | None:
    """Cloudflare Workers AI Whisper (free tier) — JSON + base64"""
    if not config.CF_ACCOUNT_ID or not config.CF_API_TOKEN:
        return None
    try:
        url = f"https://api.cloudflare.com/client/v4/accounts/{config.CF_ACCOUNT_ID}/ai/run/@cf/openai/whisper"
        audio_b64 = base64.b64encode(ogg_bytes).decode("ascii")
        async with httpx.AsyncClient(timeout=STT_TIMEOUT) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {config.CF_API_TOKEN}"},
                json={"audio": audio_b64},
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success", True):
                    text = data.get("result", {}).get("text", "")
                    if text:
                        logger.info(f"CF STT ok: {text[:80]}")
                        return text
            logger.warning(f"CF STT failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"CF STT error: {e}")
    return None


def _get_stt_error(role_id: str) -> str:
    from roles import get_role
    role = get_role(role_id)
    role_name = role.get("name", "?") if role else "?"
    return random.choice([
        f"😣 {role_name}没听清呢，可以打字再说一遍吗 (*^▽^*)",
        f"{role_name}信号不太好，发文字给我吧~",
        f"唔{role_name}没听懂~打字告诉我吧！",
    ])


def _get_stt_not_configured(role_id: str) -> str:
    from roles import get_role
    role = get_role(role_id)
    role_name = role.get("name", "?") if role else "?"
    return (
        f"😅 {role_name}的语音功能还没开通呢～\n\n"
        f"温馨提示：管理员配置 Cloudflare Workers AI 后即可使用语音聊天，完全免费！"
    )


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice message: download -> transcribe -> reply"""
    msg = update.message
    if not msg or not msg.voice:
        return

    user_id = update.effective_user.id
    role_id = context.bot_data.get("role_id", "xiaolu")

    # Duration check
    duration = msg.voice.duration
    if duration > MAX_VOICE_DURATION:
        await update.message.reply_text(
            f"🎤 语音太长啦（超过{MAX_VOICE_DURATION}秒），发短一点吧~"
        )
        return

    # Check if Cloudflare STT is configured
    if not config.CF_ACCOUNT_ID or not config.CF_API_TOKEN:
        await update.message.reply_text(_get_stt_not_configured(role_id))
        return

    try:
        voice_file = await msg.voice.get_file()
        buf = io.BytesIO()
        await voice_file.download_to_memory(buf)
        ogg_bytes = buf.getvalue()

        await update.message.chat.send_action(action="typing")

        # Transcribe via Cloudflare Workers AI
        text = await _transcribe_cf(ogg_bytes)

        if text and text.strip():
            msg.text = text
            from handlers.messages import handle_message
            await handle_message(update, context)
        else:
            await update.message.reply_text(_get_stt_error(role_id))
    except Exception as e:
        logger.error(f"voice error user_id={user_id}: {e}")
        await update.message.reply_text(_get_stt_error(role_id))
