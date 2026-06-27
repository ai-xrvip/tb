"""
Speech-to-text via Cloudflare Workers AI (free, ~3000 req/day)
Converts OGG (Telegram voice) -> WAV (ffmpeg) -> Cloudflare Whisper
"""
import io
import base64
import random
import asyncio
import tempfile
from pathlib import Path
import httpx
from telegram import Update
from telegram.ext import ContextTypes
from config import config
from utils.logger import logger

MAX_VOICE_DURATION = 60
STT_TIMEOUT = 15


async def _ogg_to_wav(ogg_bytes: bytes) -> bytes:
    """Convert OGG/Opus to WAV using ffmpeg"""
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as inf, \
         tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as outf:
        inf.write(ogg_bytes)
        inf.flush()
        inf_path = inf.name
        out_path = outf.name

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", inf_path,
            "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000",
            "-f", "wav", out_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"ffmpeg convert failed: {stderr.decode()[:200]}")
            return b""

        wav_bytes = Path(out_path).read_bytes()
        if len(wav_bytes) < 100:
            logger.error("ffmpeg produced empty WAV")
            return b""
        return wav_bytes
    finally:
        try:
            Path(inf_path).unlink(missing_ok=True)
        except Exception:
            pass
        try:
            Path(out_path).unlink(missing_ok=True)
        except Exception:
            pass


async def _transcribe_cf(ogg_bytes: bytes) -> str | None:
    """Cloudflare Workers AI Whisper — auto-converts OGG to WAV first"""
    if not config.CF_ACCOUNT_ID or not config.CF_API_TOKEN:
        return None

    # Convert OGG -> WAV
    wav_bytes = await _ogg_to_wav(ogg_bytes)
    if not wav_bytes:
        logger.error("STT: OGG->WAV conversion produced empty output")
        return None

    audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
    url = f"https://api.cloudflare.com/client/v4/accounts/{config.CF_ACCOUNT_ID}/ai/run/@cf/openai/whisper"

    try:
        async with httpx.AsyncClient(timeout=STT_TIMEOUT) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {config.CF_API_TOKEN}"},
                json={"audio": audio_b64},
            )
            logger.info(f"CF STT response: HTTP {resp.status_code}, body={resp.text[:300]}")

            if resp.status_code == 200:
                data = resp.json()
                if data.get("success", True):
                    result = data.get("result", {})
                    text = result.get("text", "") if isinstance(result, dict) else ""
                    if text:
                        logger.info(f"CF STT ok: {text[:80]}")
                        return text
                    else:
                        logger.warning(f"CF STT: empty text in response. Full result: {result}")
                else:
                    logger.warning(f"CF STT: success=false, errors={data.get('errors')}")
            else:
                logger.warning(f"CF STT HTTP {resp.status_code}: {resp.text[:300]}")
    except Exception as e:
        logger.error(f"CF STT exception: {e}")

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
    """Handle voice message: download OGG -> convert to WAV -> transcribe via Cloudflare -> reply"""
    msg = update.message
    if not msg or not msg.voice:
        return

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

        logger.info(f"Voice received: user={update.effective_user.id}, size={len(ogg_bytes)} bytes, duration={duration}s")

        # Transcribe (type indicator removed per user request)
        text = await _transcribe_cf(ogg_bytes)

        if text and text.strip():
            msg.text = text
            from handlers.messages import handle_message
            await handle_message(update, context)
        else:
            await update.message.reply_text(_get_stt_error(role_id))
    except Exception as e:
        logger.error(f"voice error: {e}")
        await update.message.reply_text(_get_stt_error(role_id))
