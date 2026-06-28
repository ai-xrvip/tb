"""
TTS - Azure TTS (primary, 500K chars/month free) + Edge TTS (fallback)
Each character gets a voice matched to their personality.
"""
import os
import asyncio
import random
import re
from typing import Optional
import httpx
from config import config
from utils.logger import logger

# Azure neural voices
VOICE_MAP = {
    "cute": "zh-CN-XiaoyiNeural",
    "mature": "zh-CN-XiaohanNeural",
    "tsundere": "zh-CN-XiaomoNeural",
    "gentle": "zh-CN-XiaoyiNeural",
    "sexy": "zh-CN-XiaoxiaoNeural",
    "default": "zh-CN-XiaochenNeural",
}

TTS_TRIGGER_RATE = float(os.getenv("TTS_TRIGGER_RATE", "0.15"))
ROLE_VOICE_MAP: dict[str, str] = {}


def get_voice_for_role(role_id: str, role: dict = None) -> str:
    if role_id in ROLE_VOICE_MAP:
        return ROLE_VOICE_MAP[role_id]
    if role is None:
        return VOICE_MAP["default"]
    role_str = str(role).lower()
    if any(w in role_str for w in ["cute", "lovely", "sweet", "jk", "student", "cosplay"]):
        return VOICE_MAP["cute"]
    elif any(w in role_str for w in ["mature", "ceo", "lawyer", "doctor", "boss", "ol", "business"]):
        return VOICE_MAP["mature"]
    elif any(w in role_str for w in ["tsundere", "cold", "aloof", "sharp"]):
        return VOICE_MAP["tsundere"]
    elif any(w in role_str for w in ["gentle", "soft", "warm", "shy"]):
        return VOICE_MAP["gentle"]
    elif any(w in role_str for w in ["sexy", "seductive"]):
        return VOICE_MAP["sexy"]
    return VOICE_MAP["default"]


# ---- Emoji / kaomoji stripping ----

def _is_emoji(cp: int) -> bool:
    return (
        0x1F600 <= cp <= 0x1F64F or
        0x1F300 <= cp <= 0x1F5FF or
        0x1F680 <= cp <= 0x1F6FF or
        0x1F1E0 <= cp <= 0x1F1FF or
        0x1F900 <= cp <= 0x1F9FF or
        0x1FA00 <= cp <= 0x1FA6F or
        0x1FA70 <= cp <= 0x1FAFF or
        0x2600  <= cp <= 0x27BF  or
        0xFE00  <= cp <= 0xFE0F  or
        cp == 0x200D
    )


# Known kaomoji special characters (not regular text/punctuation)
_KAO_CHARS = set(">_<^*/\u2606\u2605\u2665\u2200\u03c9\u25bd\u3003\u25d5\uff89\u30ee\u2727\uff9f\uff65:\u203f\uff3c\uff0f\u00b0\u30fb\uff8c")

# Match short parenthetical expressions containing kaomoji chars
_KAOMOJI_RE = re.compile(r'[(\uff08][^)\uff09]{2,12}[)\uff09]')


def _has_kao_char(s: str) -> bool:
    return any(c in _KAO_CHARS for c in s)


def _clean_tts_text(text: str) -> str:
    """Strip emoji, kaomoji, action brackets, and mood particles."""
    # Remove all bracket content: [media:xxx], [??], [?], etc.
    text = re.sub(r'\[.*?\]', '', text)
    # Remove emoji
    text = ''.join(c for c in text if not _is_emoji(ord(c)))
    # Remove kaomoji
    text = _KAOMOJI_RE.sub(lambda m: '' if _has_kao_char(m.group()) else m.group(), text)
    # Remove standalone mood particles at end of sentences (before punctuation)
    # ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? ? not stripped (they have meaning)
    # Strip trailing ? (wave dash used as decorative)
    text = text.replace('\uff5e', '').replace('~', '')
    # Collapse spaces
    text = re.sub(r' +', ' ', text).strip()
    # Strip decorative edge chars
    text = text.strip(' \uff5e~\uff65*:\u2727\u2606\u2605\u2665\u2666\u30fb')
    return text


# ---- TTS providers ----

async def _azure_tts(text: str, voice: str) -> Optional[bytes]:
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
            resp = await client.post(url, headers={
                "Ocp-Apim-Subscription-Key": config.AZURE_SPEECH_KEY,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "ogg-48khz-16bit-mono-opus",
            }, content=ssml)
            if resp.status_code == 200:
                logger.info(f"Azure TTS ok: {voice} [{text[:40]}...]")
                return resp.content
            logger.warning(f"Azure TTS {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Azure TTS error: {e}")
    return None


async def _edge_tts(text: str, voice: str) -> Optional[bytes]:
    try:
        import edge_tts
    except ImportError:
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
    text: str, role_id: str, role: dict = None, trigger_rate: float = None
) -> Optional[bytes]:
    if trigger_rate is None:
        trigger_rate = TTS_TRIGGER_RATE
    if random.random() > trigger_rate:
        return None
    voice_text = _clean_tts_text(text)[:config.TTS_MAX_CHARS]
    if len(voice_text) < 10:
        return None
    voice = get_voice_for_role(role_id, role)
    if config.TTS_PROVIDER == "azure" and config.AZURE_SPEECH_KEY:
        return await _azure_tts(voice_text, voice)
    return await _edge_tts(voice_text, voice)
