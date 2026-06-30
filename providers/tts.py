"""
TTS — Azure TTS (primary) + Edge TTS (fallback)
SSML with mood-aware express-as, prosody, and natural pauses.
Emoji/kaomoji stripped before synthesis so they are never spoken aloud.
"""
import random
import re
from typing import Optional
import httpx
from config import config
from utils.logger import logger

ROLE_VOICE_MAP: dict[str, str] = {
    "xiaolu": "zh-CN-XiaoyiNeural",
    "yui":    "zh-CN-XiaoyiNeural",
    "yuki":   "zh-CN-XiaobeiNeural",
    "momo":   "zh-CN-XiaobeiNeural",
    "linxi":  "zh-CN-XiaohanNeural",
    "aya":    "zh-CN-XiaohanNeural",
    "mizuki": "zh-CN-XiaomoNeural",
    "ruri":   "zh-CN-XiaomoNeural",
    "rio":    "zh-CN-XiaomoNeural",
    "sunian": "zh-CN-XiaoshuangNeural",
    "sora":   "zh-CN-XiaoshuangNeural",
    "sakura": "zh-CN-XiaoshuangNeural",
    "hana":   "zh-CN-XiaoshuangNeural",
    "akari":  "zh-CN-XiaoniNeural",
    "fumi":   "zh-CN-XiaoniNeural",
    "shiori": "zh-CN-XiaoniNeural",
    "yuna":   "zh-CN-XiaoxiaoNeural",
    "ren":    "zh-CN-XiaoxiaoNeural",
    "nozomi": "zh-CN-XiaoxiaoNeural",
    "reina":  "zh-CN-XiaoxuanNeural",
    "mai":    "zh-CN-XiaoxuanNeural",
    "chiyo":  "zh-CN-XiaozhenNeural",
    "koharu": "zh-CN-XiaozhenNeural",
    "mia":    "zh-CN-XiaoyanNeural",
    "nami":   "zh-CN-XiaoyanNeural",
    "mei":    "zh-CN-XiaoyanNeural",
    "nana":   "zh-CN-XiaoruiNeural",
    "kaede":  "zh-CN-XiaoruiNeural",
    "tsubaki":"zh-CN-XiaoruiNeural",
    "eri":    "zh-CN-XiaoruiNeural",
}

MOOD_SSML = {
    "happy":   {"style": "cheerful", "rate": "+15%",  "pitch": "+5Hz"},
    "tired":   {"style": "sad",      "rate": "-10%",  "pitch": "-8Hz"},
    "sleepy":  {"style": "sad",      "rate": "-20%",  "pitch": "-15Hz"},
    "sad":     {"style": "sad",      "rate": "-8%",   "pitch": "-5Hz"},
    "playful": {"style": "cheerful", "rate": "+10%",  "pitch": "+8Hz"},
    "sexy":    {"style": "warm",     "rate": "-5%",   "pitch": "-3Hz"},
    "angry":   {"style": "angry",    "rate": "+20%",  "pitch": "-5Hz"},
    "neutral": {"style": "friendly", "rate": "+0%",   "pitch": "+0Hz"},
    "period":  {"style": "sad",      "rate": "-10%",  "pitch": "-5Hz"},
}


def get_voice_for_role(role_id: str, role: dict = None) -> str:
    return ROLE_VOICE_MAP.get(role_id, "zh-CN-XiaochenNeural")


# ── Emoji / kaomoji stripping ──

_EMOJI_RANGES = [
    (0x1F600, 0x1F64F), (0x1F300, 0x1F5FF), (0x1F680, 0x1F6FF),
    (0x1F1E0, 0x1F1FF), (0x1F900, 0x1F9FF), (0x1FA00, 0x1FA6F),
    (0x1FA70, 0x1FAFF), (0x2600,  0x27BF),  (0xFE00,  0xFE0F),
    (0x2300,  0x23FF),  (0x2500,  0x25FF),  (0x2700,  0x27BF),
    (0x2B00,  0x2BFF),  (0x200D,  0x200D),
    (0x2190,  0x21FF),  (0x2B50,  0x2B55),
]


def _is_emoji(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)


_KAOMOJI_RE = re.compile(r'[\(（\[]?[^）\)\]\n]{1,15}[\)）\]]?')
_KAO_CHARS = set(">_<^/*☆★♥∀ω▽〃◕ﾉヮ✧ﾟ･:‿＼／°・ﾌヽヾ")
_DECORATIVE_SYMBOLS = "☆★♥♦♡♤♧♩♪♫♬☀☁☂☃★✶✷✸✹❀❁❃❄❅❆❇❈❉❊❋✿✤✥🌈🌙⚡🔥💫⭐🌟"


def _has_kao_char(s: str) -> bool:
    return any(c in _KAO_CHARS for c in s)


def _clean_tts_text(text: str) -> str:
    """Strip anything TTS would vocalize: emoji, kaomoji, decorative symbols."""
    text = re.sub(r'\[.*?\]', '', text)
    text = _KAOMOJI_RE.sub(lambda m: '' if _has_kao_char(m.group()) else m.group(), text)
    for c in _DECORATIVE_SYMBOLS:
        text = text.replace(c, '')
    text = ''.join(c for c in text if not _is_emoji(ord(c)))
    text = re.sub(r'[〜～~]', '', text)
    text = re.sub(r'\s+', '', text)
    return text.strip()


# ── SSML builder ──

def _build_ssml(text: str, voice: str, mood_id: str = "neutral") -> str:
    mood_cfg = MOOD_SSML.get(mood_id, MOOD_SSML["neutral"])
    text = re.sub(r'([。！？!?])', r'\1<break time="300ms"/>', text)
    text = re.sub(r'([，、,])', r'\1<break time="150ms"/>', text)
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="zh-CN">'
        f'<voice name="{voice}">'
        f'<mstts:express-as style="{mood_cfg["style"]}" styledegree="1.5">'
        f'<prosody rate="{mood_cfg["rate"]}" pitch="{mood_cfg["pitch"]}">'
        f'{text}'
        f'</prosody>'
        f'</mstts:express-as>'
        f'</voice>'
        f'</speak>'
    )


# ── TTS providers ──

async def _azure_tts(text: str, voice: str, mood_id: str = "neutral") -> Optional[bytes]:
    if not config.AZURE_SPEECH_KEY or not config.AZURE_SPEECH_REGION:
        return None
    ssml = _build_ssml(text, voice, mood_id)
    url = f"https://{config.AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers={
                "Ocp-Apim-Subscription-Key": config.AZURE_SPEECH_KEY,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "ogg-48khz-16bit-mono-opus",
            }, content=ssml.encode("utf-8"))
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
    text: str, role_id: str, role: dict = None,
    trigger_rate: float = None, mood_id: str = "neutral",
) -> Optional[bytes]:
    if trigger_rate is None:
        trigger_rate = config.TTS_TRIGGER_RATE
    if random.random() > trigger_rate:
        return None
    voice_text = _clean_tts_text(text)[:config.TTS_MAX_CHARS]
    if len(voice_text) < 1:
        return None
    voice = get_voice_for_role(role_id, role)
    if config.TTS_PROVIDER == "azure" and config.AZURE_SPEECH_KEY:
        return await _azure_tts(voice_text, voice, mood_id)
    return await _edge_tts(voice_text, voice)
