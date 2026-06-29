"""
Speech-to-text via Cloudflare Workers AI (free, ~3000 req/day)
Sends raw WAV bytes as u8 int array (Cloudflare Whisper speaks this format)
"""
import io
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
STT_TIMEOUT = 20


async def _ogg_to_wav_u8(ogg_bytes: bytes) -> list[int] | None:
    """Convert OGG -> 16kHz mono WAV (bitexact, no extra chunks) -> raw u8 int array"""
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as inf, \
         tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as outf:
        inf.write(ogg_bytes)
        inf.flush()
        inf_path = inf.name
        out_path = outf.name

    try:
        # -bitexact ensures clean WAV header without extra metadata chunks
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-fflags", "+bitexact",
            "-i", inf_path,
            "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000",
            "-f", "wav", out_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"ffmpeg failed: {stderr.decode()[:200]}")
            return None

        wav_bytes = Path(out_path).read_bytes()
        if len(wav_bytes) < 100:
            logger.error("ffmpeg: empty output")
            return None

        logger.info(f"OGG {len(ogg_bytes)}B -> WAV {len(wav_bytes)}B (16kHz mono, bitexact)")
        # Send raw WAV bytes as u8 int array (0-255 range)
        return list(wav_bytes)
    except FileNotFoundError:
        logger.error("ffmpeg not found!")
        return None
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
    """Send raw WAV bytes to Cloudflare Whisper"""
    if not config.CF_ACCOUNT_ID or not config.CF_API_TOKEN:
        return None

    audio_array = await _ogg_to_wav_u8(ogg_bytes)
    if not audio_array:
        return None

    url = f"https://api.cloudflare.com/client/v4/accounts/{config.CF_ACCOUNT_ID}/ai/run/@cf/openai/whisper"

    try:
        async with httpx.AsyncClient(timeout=STT_TIMEOUT) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {config.CF_API_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={"audio": audio_array},
            )
            logger.info(f"CF STT: HTTP {resp.status_code}")

            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    result = data.get("result", {})
                    text = result.get("text", "") if isinstance(result, dict) else str(result)
                    text = text.strip()
                    logger.info(f"CF STT ok: [{text[:100]}]")
                    return text if text else None
                else:
                    logger.warning(f"CF STT errors: {data.get('errors')}")
            else:
                logger.warning(f"CF STT HTTP {resp.status_code}: {resp.text[:400]}")
    except httpx.TimeoutException:
        logger.error("CF STT timeout")
    except Exception as e:
        logger.error(f"CF STT exception: {type(e).__name__}: {e}")

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
        f"管理员配置 Cloudflare Workers AI 后即可使用语音聊天，完全免费！"
    )


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice message"""
    msg = update.message
    if not msg or not msg.voice:
        return

    role_id = context.bot_data.get("role_id", "xiaolu")
    user_id = update.effective_user.id if update.effective_user else 0

    duration = msg.voice.duration
    if duration > MAX_VOICE_DURATION:
        await update.message.reply_text(f"🎤 语音太长啦（超过{MAX_VOICE_DURATION}秒），发短一点吧~")
        return

    if not config.CF_ACCOUNT_ID or not config.CF_API_TOKEN:
        await update.message.reply_text(_get_stt_not_configured(role_id))
        return

    try:
        voice_file = await msg.voice.get_file()
        buf = io.BytesIO()
        await voice_file.download_to_memory(buf)
        ogg_bytes = buf.getvalue()

        if len(ogg_bytes) < 100:
            logger.warning(f"Voice too small: {len(ogg_bytes)} bytes")
            await update.message.reply_text(_get_stt_error(role_id))
            return

        logger.info(f"Voice recv: user={user_id}, size={len(ogg_bytes)}B, dur={duration}s")

        text = await _transcribe_cf(ogg_bytes)

        if text:
            logger.info(f"Voice -> text: [{text[:100]}]")
            # Store transcribed text in context, safe way (no __setattr__ injection)
            context.user_data["voice_text"] = text
            from handlers.messages import process_voice_text
            await process_voice_text(update, context, text)
        else:
            logger.warning(f"Voice transcribe returned None for user={user_id}")
            await update.message.reply_text(_get_stt_error(role_id))
    except Exception as e:
        logger.error(f"Voice handler error user={user_id}: {type(e).__name__}: {e}", exc_info=True)
        await update.message.reply_text(_get_stt_error(role_id))

