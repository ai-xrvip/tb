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
# Per-role voice mapping (Azure zh-CN neural voices)
ROLE_VOICE_MAP: dict[str, str] = {
    # Cute / loli
    "xiaolu": "zh-CN-XiaoyiNeural",     # 小鹿🦌 cosplayer JK 可爱
    "yui":    "zh-CN-XiaoyiNeural",     # 结衣🏠 女仆咖啡 甜美

    # Playful / cute
    "yuki":   "zh-CN-XiaobeiNeural",    # 阿雪🎀 大学生 清纯可爱
    "momo":   "zh-CN-XiaobeiNeural",    # 桃子🍰 甜点师 甜美

    # Mature / professional
    "linxi":  "zh-CN-XiaohanNeural",    # 林夕💼 投行VP 成熟御姐
    "aya":    "zh-CN-XiaohanNeural",    # 阿彩💼 总裁助理 干练

    # Tsundere / sharp / cool
    "mizuki": "zh-CN-XiaomoNeural",     # 美月👠 CEO 高冷傲娇
    "ruri":   "zh-CN-XiaomoNeural",     # 琉璃⚖️ 律师 冷静锐利
    "rio":    "zh-CN-XiaomoNeural",     # 阿央🏎️ 赛车手 帅气冷酷

    # Gentle / soft
    "sunian": "zh-CN-XiaoshuangNeural", # 苏念🎨 美术老师 温柔文艺
    "sora":   "zh-CN-XiaoshuangNeural", # 小空✈️ 空乘 温柔甜美
    "sakura": "zh-CN-XiaoshuangNeural", # 小樱🐾 兽医 温柔有爱心
    "hana":   "zh-CN-XiaoshuangNeural", # 小花🌷 花艺师 温柔

    # Caring / soft-spoken
    "akari":  "zh-CN-XiaoniNeural",     # 明丽💉 护士 温柔体贴
    "fumi":   "zh-CN-XiaoniNeural",     # 阿文📖 图书管理员 安静柔和
    "shiori": "zh-CN-XiaoniNeural",     # 诗织📚 文学研究生 文静

    # Warm / charming
    "yuna":   "zh-CN-XiaoxiaoNeural",   # 由奈💋 模特 温暖性感
    "ren":    "zh-CN-XiaoxiaoNeural",   # 阿莲🍸 调酒师 温暖迷人
    "nozomi": "zh-CN-XiaoxiaoNeural",   # 阿望🎙️ 配音演员 温暖多变

    # Elegant / refined
    "reina":  "zh-CN-XiaoxuanNeural",   # 玲奈👑 富豪千金 优雅
    "mai":    "zh-CN-XiaoxuanNeural",   # 小舞🩰 芭蕾首席 优雅

    # Natural / down-to-earth
    "chiyo":  "zh-CN-XiaozhenNeural",   # 阿代🌸 海鲜餐厅 接地气
    "koharu": "zh-CN-XiaozhenNeural",   # 小春📷 自由摄影师 自然洒脱

    # Energetic / youthful
    "mia":    "zh-CN-XiaoyanNeural",    # Mia⚡️ 健身私教 阳光活力
    "nami":   "zh-CN-XiaoyanNeural",    # 阿波🏄‍♀️ 冲浪教练 阳光
    "mei":    "zh-CN-XiaoyanNeural",    # 芽衣🎤 独立音乐人 个性活力

    # Crisp / smart
    "nana":   "zh-CN-XiaoruiNeural",    # 娜娜🎮 游戏主播 爽朗
    "kaede":  "zh-CN-XiaoruiNeural",    # 阿枫🚔 刑警 干脆利落
    "tsubaki":"zh-CN-XiaoruiNeural",    # 阿椿📰 调查记者 干练
    "eri":    "zh-CN-XiaoruiNeural",    # 惠里🔬 AI研究员 智慧干练
}

def get_voice_for_role(role_id: str, role: dict = None) -> str:
    """Return the Azure neural voice for a given role_id."""
    return ROLE_VOICE_MAP.get(role_id, "zh-CN-XiaochenNeural")



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
        trigger_rate = config.TTS_TRIGGER_RATE
    if random.random() > trigger_rate:
        return None
    voice_text = _clean_tts_text(text)[:config.TTS_MAX_CHARS]
    if len(voice_text) < 10:
        return None
    voice = get_voice_for_role(role_id, role)
    if config.TTS_PROVIDER == "azure" and config.AZURE_SPEECH_KEY:
        return await _azure_tts(voice_text, voice)
    return await _edge_tts(voice_text, voice)
