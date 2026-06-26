"""
TTS 语音生成模块 —— 基于 Microsoft Edge TTS（免费，自然中文语音）
支持为不同角色配置不同声线，撒娇/御姐/冷淡各有对应音色
"""
import os
import io
import asyncio
import random
import tempfile
from pathlib import Path
from typing import Optional

from utils.logger import logger

# 用 import 方式延迟检查，不放在顶层避免必须安装
# import edge_tts


# 音色映射 —— 根据角色性格匹配
# Edge TTS 中文女声一览：
# zh-CN-XiaoxiaoNeural - 活泼可爱（默认）
# zh-CN-XiaoyiNeural - 温柔邻家
# zh-CN-YunxiNeural - 元气少年感（偏中性，适合活泼角色）
# zh-CN-YunjianNeural - 成熟知性
# zh-CN-XiaochenNeural - 元气少女
# zh-CN-XiaohanNeural - 温柔御姐
# zh-CN-XiaomengNeural - 可爱萝莉
# zh-CN-XiaomoNeural - 成熟磁性
# zh-CN-XiaoruiNeural - 成熟女声

# 角色类型 -> 推荐音色
VOICE_MAP = {
    "cute": "zh-CN-XiaoxiaoNeural",      # 小鹿、小樱、桃子等可爱系
    "mature": "zh-CN-XiaohanNeural",      # 总裁、律师、医生等成熟系
    "tsundere": "zh-CN-YunxiNeural",      # 傲娇、毒舌系
    "gentle": "zh-CN-XiaoyiNeural",       # 温柔邻家
    "sexy": "zh-CN-XiaomoNeural",         # 性感磁性
    "default": "zh-CN-XiaochenNeural",    # 元气少女默认
}

# 每个角色的语音触发概率（0.0 - 1.0）
TTS_TRIGGER_RATE = 0.15  # 15% 概率发语音

# 角色语音映射（可在 config 覆盖）
ROLE_VOICE_MAP: dict[str, str] = {}


def get_voice_for_role(role_id: str, role: dict = None) -> str:
    """根据角色获取对应的 TTS 音色"""
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


async def generate_voice(text: str, voice: str, output_path: Optional[str] = None) -> Optional[bytes]:
    """使用 Edge TTS 生成语音，返回 OGG bytes 或保存到文件"""
    try:
        import edge_tts
    except ImportError:
        logger.error("edge-tts not installed. Run: pip install edge-tts")
        return None

    try:
        communicate = edge_tts.Communicate(text, voice)

        if output_path:
            await communicate.save(output_path)
            return None  # 文件模式

        # 内存模式 —— 收集 bytes
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)

    except Exception as e:
        logger.error(f"Edge TTS failed: {e}")
        return None


async def generate_role_voice(
    text: str,
    role_id: str,
    role: dict = None,
    trigger_rate: float = None,
) -> Optional[bytes]:
    """为指定角色生成语音，自动选择音色（带概率控制）

    返回:
        bytes: OGG 音频数据，用于 send_voice
        None: 本次不发语音（概率或失败）
    """
    if trigger_rate is None:
        trigger_rate = TTS_TRIGGER_RATE

    # 概率控制
    if random.random() > trigger_rate:
        return None

    # 语音最短长度限制（太短没意义）
    if len(text) < 10:
        return None

    # 语音最长截断（太长发语音体验差）
    voice_text = text[:300]  # 最多300字

    # 去掉方括号标记（如 [media:xxx]）
    import re
    voice_text = re.sub(r'\[.*?\]', '', voice_text).strip()
    if len(voice_text) < 5:
        return None

    voice = get_voice_for_role(role_id, role)
    logger.info(f"TTS generating voice for {role_id} with {voice}: {voice_text[:50]}...")

    return await generate_voice(voice_text, voice)


async def text_to_ogg_file(text: str, voice: str, filepath: str) -> bool:
    """生成语音并保存到指定文件路径"""
    await generate_voice(text, voice, output_path=filepath)
    return Path(filepath).exists() and Path(filepath).stat().st_size > 0
