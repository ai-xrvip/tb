"""
TTS — Azure TTS (primary, 500K chars/month free) + Edge TTS (fallback)
Each character gets a voice matched to their personality.
"""
import io
import asyncio
import random
import re
from typing import Optional
import httpx
from config import config
from utils.logger import logger

# ── Voice map per character type ──
VOICE_MAP = {
    "cute": "zh-CN-XiaoxiaoNeural",      # 活泼可爱
    "mature": "zh-CN-XiaohanNeural",      # 温柔御姐
    "tsundere": "zh-CN-YunxiNeural",      # 傲娇元气
    "gentle": "zh-CN-XiaoyiNeural",       # 温柔邻家
    "sexy": "zh-CN-XiaomoNeural",         # 性感磁性
    "default": "zh-CN-XiaochenNeural",    # 元气少女
}

TTS_TRIGGER_RATE = 0.15
ROLE_VOICE_MAP: dict[str, str] = {}


def get_voice_for_role(role_id: str, role: dict = None) -> str:
    if role_id in ROLE_VOICE_MAP:
        return ROLE_VOICE_MAP[role_id]
    if role is None:
        return VOICE_MAP["default"]
    role_str = str(role).lower()
    if any(w in role_str for w in ["可爱", "撒娇", "粘人", "jk", "学生", "cosplay", "天真"]):
        return VOICE_MAP["cute"]
    elif any(w in role_str for w in ["御姐", "总裁", "律师", "医生", "教师", "上司", "ol", "商务", "成熟"]):
        return VOICE_MAP["mature"]
    elif any(w in role_str for w in ["傲娇", "毒舌", "高冷", "冷淡"]):
        return VOICE_MAP["tsundere"]
    elif any(w in role_str for w in ["温柔", "邻家", "软妹"]):
        return VOICE_MAP["gentle"]
    elif any(w in role_str for w in ["性感", "御姐", "诱惑"]):
        return VOICE_MAP["sexy"]
    return VOICE_MAP["default"]


async def _azure_tts(text: str, voice: str) -> Optional[bytes]:
    """Azure TTS — best quality, 500K chars/month free"""
    if not config.AZURE_SPEECH_KEY or not config.AZURE_SPEECH_REGION:
        return None

    ssml = (
        f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='zh-CN'>"
        f"<voice name='{voice}'>{text}</voice>"
        f"</speak>"
    )
    url = f"https://{config.AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                headers={
                    "Ocp-Apim-Subscription-Key": config.AZURE_SPEECH_KEY,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": "ogg-48khz-16bit-mono-opus",
                },
                content=ssml,
            )
            if resp.status_code == 200:
                logger.info(f"Azure TTS ok: {voice} [{text[:40]}...]")
                return resp.content
            else:
                logger.warning(f"Azure TTS {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Azure TTS error: {e}")
    return None


async def _edge_tts(text: str, voice: str) -> Optional[bytes]:
    """Edge TTS — free, decent quality"""
    try:
        import edge_tts
    except ImportError:
        logger.error("edge-tts not installed")
        return None

    try:
        communicate = edge_tts.Communicate(text, voice)
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        result = b"".join(chunks)
        if result:
            logger.info(f"Edge TTS ok: {voice} [{text[:40]}...]")
        return result or None
    except Exception as e:
        logger.warning(f"Edge TTS error: {e}")
    return None


async def generate_role_voice(
    text: str,
    role_id: str,
    role: dict = None,
    trigger_rate: float = None,
) -> Optional[bytes]:
    """Generate voice for a character. Returns OGG bytes or None."""
    if trigger_rate is None:
        trigger_rate = TTS_TRIGGER_RATE

    # Probability gate
    if random.random() > trigger_rate:
        return None

    # Clean text
    voice_text = re.sub(r'\[.*?\]', '', text).strip()
    voice_text = voice_text[:config.TTS_MAX_CHARS]
    if len(voice_text) < 10:
        return None

    voice = get_voice_for_role(role_id, role)
    provider = config.TTS_PROVIDER

    # Try Azure first, fall back to Edge
    if provider == "azure":
        result = await _azure_tts(voice_text, voice)
        if result:
            return result
        logger.info("Azure TTS failed, falling back to Edge...")
        return await _edge_tts(voice_text, voice)
    else:
        return await _edge_tts(voice_text, voice)
