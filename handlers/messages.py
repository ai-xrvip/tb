"""
消息处理器 —— 文本对话(多LLM提供商 + 流式输出) + 媒体消息 + 管理员上传对话

参考:
- karfly bot: 流式输出 + 多提供商架构
- chatgpt-on-wechat: 插件系统 + 多平台思路
- Openaibot: 角色预设 + 媒体标签
"""
import os
import re
import random
import json
import asyncio
import time as _time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode
from config import config
from database import db
from roles import ROLES, get_role
from utils.logger import logger
from handlers.payment import send_paywall_card
from handlers.yuanwei import try_trigger_yuanwei
from handlers.keepsake import try_trigger_keepsake
from roles import get_current_paywall, get_paywall
from media_tags import get_media_config, get_folder, get_tier, get_tags_for_role
from providers import get_provider, ProviderType
from providers.base import ProviderError, RateLimitError, TokenLimitError
from prompt_template import resolve_system_prompt
from providers.tts import generate_role_voice
from image_gen import generate_image


# ── 角色化等待/报错话术 ──

def _get_role_busy_message(role_id: str) -> str:
    """根据角色返回贴合人设的等待/报错话术"""
    role = get_role(role_id)
    role_name = role.get("name", "我") if role else "我"
    
    cute_messages = [
        f"哎呀～{role_name}在加班呢，等一下下哦，马上回你 (*^▽^*)",
        f"{role_name}刚在忙啦～等我一下下，马上就来找你 (*/ω＼*)",
        f"在呢在呢～刚在处理点事情，马上好好陪你聊！不许跑掉哦～",
        f"等一下下嘛～{role_name}这边有点小状况，很快就好 (｡>﹏<｡)",
    ]
    mature_messages = [
        f"{role_name}在忙，稍等一下，很快回来。",
        f"稍等片刻，{role_name}处理点事情，马上就好。",
        f"刚才在开个小差…等我一下，很快回你。",
    ]
    tsundere_messages = [
        f"哼，{role_name}才不是特意在等你呢…等一下啦！",
        f"催什么催～{role_name}也有自己的事要做啊，马上就来！",
    ]
    
    role_str = json.dumps(role, ensure_ascii=False) if role else ""
    if any(w in role_str for w in ["甜", "软", "可爱", "撒娇", "粘人", "JK", "学妹", "Cosplay"]):
        return random.choice(cute_messages)
    elif any(w in role_str for w in ["御姐", "总裁", "律师", "医生", "教师", "上司", "OL", "商务"]):
        return random.choice(mature_messages)
    elif any(w in role_str for w in ["傲娇", "毒舌", "高冷", "冷淡"]):
        return random.choice(tsundere_messages)
    else:
        return random.choice(cute_messages)


# ── 回复延迟系统（亲密度 + 时段感知）──

def _calculate_reply_delay(user_id: int, role_id: str, reply_length: int, user_response_time: float = 999) -> float:
    """模拟真人回复延迟：打字+思考+亲密度×时段繁忙度+忙线概率+对话节奏"""
    import random as _rng

    # 1) 打字时间
    typing_delay = reply_length * _rng.uniform(0.3, 0.5)

    # 2) 思考时间
    think_delay = _rng.uniform(3.0, 10.0)

    # 3) 亲密度系数
    total_msgs = 0
    try:
        user_data = db.get_user(user_id)
        total_msgs = (user_data or {}).get("total_messages", 0) or 0
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    if total_msgs < 5:       intimacy_mult = 3.0
    elif total_msgs < 20:    intimacy_mult = 2.2
    elif total_msgs < 50:    intimacy_mult = 1.5
    elif total_msgs < 100:   intimacy_mult = 1.0
    elif total_msgs < 200:   intimacy_mult = 0.6
    else:                    intimacy_mult = 0.3

    # 4) 时段繁忙度
    now = datetime.now(timezone.utc) + timedelta(hours=8)  # 北京时间
    hour = now.hour
    weekday = now.weekday()
    is_weekend = weekday >= 5
    is_busy_mode = False  # 是否触发"正在忙"超长延迟

    if is_weekend:
        if 9 <= hour < 18:     busy_delay = _rng.uniform(2, 15)
        elif 18 <= hour < 23:  busy_delay = _rng.uniform(1, 8)
        elif hour >= 23:       busy_delay = _rng.uniform(20, 90)
        else:                  busy_delay = _rng.uniform(30, 180)
    else:
        if hour < 7:           busy_delay = _rng.uniform(30, 180)
        elif hour < 9:         busy_delay = _rng.uniform(8, 30)
        elif hour < 12:
            if _rng.random() < 0.3:  # 30% 概率：开会/忙线
                busy_delay = _rng.uniform(120, 300)
                is_busy_mode = True
            else:
                busy_delay = _rng.uniform(15, 90)
        elif hour < 14:        busy_delay = _rng.uniform(3, 18)
        elif hour < 18:
            if _rng.random() < 0.3:  # 30% 概率：开会/忙线
                busy_delay = _rng.uniform(120, 300)
                is_busy_mode = True
            else:
                busy_delay = _rng.uniform(10, 60)
        elif hour < 21:        busy_delay = _rng.uniform(2, 15)
        elif hour < 23:        busy_delay = _rng.uniform(1, 8)
        else:                  busy_delay = _rng.uniform(15, 90)

    total = typing_delay + think_delay + (busy_delay * intimacy_mult)

    # 5) 对话节奏适应：对方秒回则加速
    rhythm_mult = 1.0
    if user_response_time < 15:
        rhythm_mult = 0.5   # 对方15秒内回复 → 加速50%
    elif user_response_time < 30:
        rhythm_mult = 0.7   # 对方30秒内回复 → 加速30%
    elif user_response_time < 60:
        rhythm_mult = 0.85  # 对方1分钟内回复 → 小幅加速
    total *= rhythm_mult

    # 6) 上限：忙线模式 300s，正常模式 60s
    max_delay = 300.0 if is_busy_mode else 60.0
    return max(2.0, min(total, max_delay))


# ── 对话规则（代码级注入，所有角色生效）──

def _get_conversation_rules(history_len: int) -> str:
    """根据对话进度返回对话规则：先了解对方，再分享自己"""
    if history_len <= 4:
        return (
            "【对话规则 - 必须严格遵守】\n"
            "你刚刚认识对方。核心任务：了解他，而不是介绍自己。\n"
            "1. 先问对方怎么称呼 / 叫什么名字\n"
            "2. 对方回答后表达开心，然后自然地问年龄、兴趣爱好、做什么工作\n"
            "3. 每次回复末尾必须带一个关于对方的问题\n"
            "4. 永远不要自顾自长篇大论说自己的事\n"
            "5. 回复控制在2-3句话，保持简洁热情"
        )
    elif history_len <= 12:
        return (
            "【对话规则 - 必须遵守】\n"
            "你在了解对方的过程中：\n"
            "1. 继续挖掘对方还没告诉你的信息：年龄、职业、兴趣、来自哪里等\n"
            "2. 每次回复末尾必须带一个关于对方的问题\n"
            "3. 可以根据对方的回答适当分享自己的相关经历，但不超过回复的一半\n"
            "4. 表现好奇心和热情，追问对方回答中的细节\n"
            "5. 一次只问一个问题，不要像查户口"
        )
    elif history_len <= 30:
        return (
            "【对话规则 - 必须遵守】\n"
            "你们已经慢慢熟悉了：\n"
            "1. 每2-3句话至少问一个关于对方感受或近况的问题\n"
            "2. 分享自己的同时要关心对方\n"
            "3. 适时提起对方说过的事情，展示你在认真听他说话\n"
        )
    else:
        return (
            "【对话规则】\n"
            "你们已经比较熟悉了：\n"
            "1. 每3-5句话至少问一个对方的问题\n"
            "2. 保持双向互动，不要冷落对方\n"
            "3. 记住对方说过的重要信息"
        )


# ── 媒体标签系统 ──
# 由 media_tags.py 统一管理，支持全局标签 + 角色个性化标签
# 每个标签定义：folder(从哪个文件夹取图) + tier(需要的解锁级别)
# 别名支持：多个标签可指向同一个folder（重复利用图池）
MEDIA_TAG_RE = re.compile(r'\[media:([^\]]+)\]')

# ── 流式更新间隔（秒） ──
STREAM_UPDATE_INTERVAL = 0.8
# ── 流式累计最小字符数才更新 ──
STREAM_MIN_CHARS = 20


def _media_allowed(role_id: str, category: str, user_id: int) -> bool:
    """检查用户是否有权限看该类媒体（从 media_tags 读取tier）"""
    required_tier = get_tier(role_id, category)
    if required_tier == 0:
        return True
    user_tier = db.get_unlock_tier(user_id, role_id)
    return user_tier >= required_tier

def _pick_media(role_id: str, tag: str, user_id: int) -> str | None:
    """Pick a random image from a media folder. Supports tag + keyword fallback."""
    import random
    media_base = Path(__file__).parent.parent / "media"
    role_dir = media_base / role_id
    if not role_dir.exists():
        return None
    folder = get_folder(role_id, tag)
    if not folder:
        folder = _smart_folder_match(role_id, tag)
    if not folder:
        return None
    folder_path = role_dir / folder
    if not folder_path.exists():
        return None
    files = [p for p in folder_path.glob("*") if p.suffix.lower() in (".jpg",".jpeg",".png",".webp")]
    if not files:
        return None
    return str(random.choice(files))


def _smart_folder_match(role_id: str, text: str) -> str | None:
    """Match conversation text to best available media folder by keyword scoring."""
    media_base = Path(__file__).parent.parent / "media"
    role_dir = media_base / role_id
    text_lower = text.lower()
    best_folder = None
    best_score = 0
    folder_keywords = {
        "JK": ["jk", "??", "??", "???", "???"],
        "Cos": ["cos", "cosplay", "??", "??"],
        "??": ["??", "??", "??", "??"],
        "??": ["??", "??", "??", "??", "ootd", "look"],
        "??": ["??", "??", "??", "??", "??"],
        "??": ["??", "??", "??", "??", "?"],
        "??": ["??", "??", "??", "??"],
        "??": ["??", "??", "??"],
        "??": ["??", "?", "??"],
        "??": ["??", "??"],
        "??": ["??", "?"],
        "??": ["??", "?", "?", "??", "??"],
        "??": ["??", "??", "??", "??"],
    }
    for folder_name, keywords in folder_keywords.items():
        score = sum(len(kw) for kw in keywords if kw in text_lower)
        if score > best_score and (role_dir / folder_name).is_dir():
            best_score = score
            best_folder = folder_name
    return best_folder


def _pick_media_by_context(role_id: str, reply_text: str) -> str | None:
    """Pick a relevant image based on what the AI said."""
    import random
    folder = _smart_folder_match(role_id, reply_text)
    if folder:
        media_base = Path(__file__).parent.parent / "media"
        folder_path = media_base / role_id / folder
        files = [p for p in folder_path.glob("*") if p.suffix.lower() in (".jpg",".jpeg",".png",".webp")]
        if files:
            return str(random.choice(files))
    return None

def _build_messages(user_id: int, role_id: str, user_text: str) -> list[dict]:
    """构建发送给 LLM 的消息列表（含世界书/记忆）"""
    role = get_role(role_id)
    system_prompt_raw = role["system_prompt"] if role else ""
    system_prompt = resolve_system_prompt(role, user_name="用户") if role else ""

    messages = [{"role": "system", "content": system_prompt}]

    # 加载世界书/记忆（关键词匹配 + 永久记忆）
    try:
        from lore import get_lore_context, get_lore_entries
        lore_ctx = get_lore_context(user_id, role_id)
        # 关键词匹配：根据用户消息触发相关世界条目
        keyword_lore = get_lore_entries(role_id, user_text)
        if keyword_lore:
            lore_ctx = (lore_ctx or "") + "\n" + keyword_lore
        if lore_ctx:
            messages.append({"role": "system", "content": f"[世界设定/记忆]\n{lore_ctx}"})
    except ImportError:
        pass

    # 注入关系等级 + 心情
    try:
        rel_prompt = get_relationship_prompt(role_id, user_id)
        if rel_prompt:
            messages.append({"role": "system", "content": rel_prompt})
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    try:
        mood_prompt = get_mood_prompt(user_id, role_id)
        if mood_prompt:
            messages.append({"role": "system", "content": mood_prompt})
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    # 注入环境感知（天气+时间）
    try:
        env_ctx = get_environment_context(role_id)
        if env_ctx:
            messages.append({"role": "system", "content": env_ctx})
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    # 注入知识图谱（用户记忆）
    try:
        knowledge_ctx = get_knowledge_context(user_id, role_id)
        if knowledge_ctx:
            messages.append({"role": "system", "content": knowledge_ctx})

        # Inject Deep Dream conversation summaries
        from deep_dream import get_summary_context
        summary_ctx = get_summary_context(user_id, role_id)
        if summary_ctx:
            messages.append({"role": "system", "content": summary_ctx})
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    # 注入对话规则（核心：先了解用户再分享自己）
    conv_rules = _get_conversation_rules(len(db.get_chat_history(user_id)))

    # ?? Inject available media tags ??
    try:
        from media_tags import get_tags_for_role
        role_tags = get_tags_for_role(role_id)
        available = []
        import os
        media_dir = Path(__file__).parent.parent / "media" / role_id
        for tag, cfg in role_tags.items():
            folder = media_dir / cfg["folder"]
            if folder.is_dir() and any(f.suffix.lower() in (".jpg",".jpeg",".png",".webp") for f in folder.iterdir()):
                available.append(f"{tag}({cfg['folder']})")
        if available:
            media_instruction = "\n\n??????????\n????????????????????? [media:JK] ? [media:??]?\n????????" + ", ".join(available) + "\n????????????????????"
            messages.append({"role": "system", "content": media_instruction})
    except Exception:
        pass
    messages.append({"role": "system", "content": conv_rules})

    # ?? Inject available media tags ??
    try:
        from media_tags import get_tags_for_role
        role_tags = get_tags_for_role(role_id)
        available = []
        media_dir = Path(__file__).parent.parent / "media" / role_id
        for tag, cfg in role_tags.items():
            folder = media_dir / cfg["folder"]
            has_files = folder.is_dir() and any(f.suffix.lower() in (".jpg",".jpeg",".png",".webp") for f in folder.iterdir())
            if has_files:
                available.append(tag)
        if available:
            media_instruction = "\n\n????????????????????????? [media:???]?\n?????" + ", ".join(available) + "\n???????????????????"
            messages.append({"role": "system", "content": media_instruction})
    except Exception:
        pass

        # 加载旧的摘要
    summaries = db.get_chat_summaries(user_id)
    for s in summaries:
        messages.append({
            "role": "system",
            "content": f"[历史对话摘要] {s['summary_text']}",
        })

    # 加载最近的对话历史
    history = db.get_chat_history(user_id)
    max_rounds = config.MAX_HISTORY_ROUNDS
    recent = history[-(max_rounds * 2):]
    messages.extend(recent)

    # 添加当前用户消息
    messages.append({"role": "user", "content": user_text})
    return messages


async def _check_and_summarize(user_id: int):
    """当历史消息超过阈值时，自动摘要"""
    history = db.get_chat_history(user_id)
    threshold = config.MAX_HISTORY_ROUNDS * 2  # 降低摘要阈值，保持长期记忆
    if len(history) < threshold:
        return

    to_summarize = history[: len(history) // 2]
    if len(to_summarize) < 10:
        return

    summary_prompt = "请用2-3句话简洁总结以下对话的核心内容和情感走向：\n\n"
    summary_prompt += "\n".join(
        f"{'用户' if m['role']=='user' else 'AI'}: {m['content']}"
        for m in to_summarize
    )

    try:
        provider = get_provider(
            ProviderType.DEEPSEEK,
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
            model=config.DEEPSEEK_MODEL,
        )
        summary = await provider.chat(
            messages=[{"role": "user", "content": summary_prompt}],
            max_tokens=300,
            temperature=0.3,
        )
        db.add_chat_summary(user_id, summary, len(to_summarize))
        remaining = history[len(history) // 2:]
        db.update_chat_history(user_id, remaining)
        logger.info(f"chat summarized user_id={user_id}")
    except Exception as e:
        logger.error(f"summarize failed user_id={user_id}: {e}")


async def _get_provider_for_role(role_id: str):
    """根据角色配置获取 LLM 提供商"""
    provider_type_str = config.LLM_PROVIDER or "deepseek"

    if provider_type_str == "deepseek":
        return get_provider(
            ProviderType.DEEPSEEK,
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
            model=config.DEEPSEEK_MODEL,
        )
    elif provider_type_str == "openai":
        return get_provider(
            ProviderType.OPENAI,
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL,
            model=config.OPENAI_MODEL,
        )
    else:
        raise ValueError(f"Unsupported provider: {provider_type_str}")



async def _generate_and_send(update, reply_text, role_id, role_name):
    try:
        img_data = await generate_image(reply_text, role_id, role_name)
        if img_data:
            await update.message.reply_photo(img_data)
    except Exception as e:
        logger.error(f"img2img failed: {e}")


async def _pregenerate_photo(update, user_id, reply_text, role_id, role_name, pending_dict):
    """Pre-generate photo in background, store for next user confirmation."""
    try:
        img_data = await generate_image(reply_text, role_id, role_name)
        if img_data and len(img_data) > 500:
            pending_dict[user_id] = img_data
            logger.info(f"Pre-generated photo for user {user_id}, waiting for confirmation")
    except Exception as e:
        logger.error(f"Pre-generation failed: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理普通文本消息 —— 亲密度+时段感知延迟，角色化报错"""
    user = update.effective_user
    user_id = user.id
    user_name = user.first_name or "用户"
    user_text = update.message.text.strip()

    db.create_user(user_id)
    user_data = db.get_user(user_id)
    role_id = context.bot_data.get("role_id", "xiaolu")
    role = get_role(role_id)

    # 获取上次消息时间（用于计算对方回复速度）
    prev_msg_time = None
    try:
        prev_msg_time = db.get_last_message_time(user_id)
    except Exception as e:
        logger.debug(f"Non-critical: {e}")
    try:
        db.update_last_message_time(user_id)
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    unlock_tier = db.get_unlock_tier(user_id, role_id)
    free_count = user_data.get("free_count", 0)
    total_msgs = user_data.get("total_messages", 0)

    next_pw = get_current_paywall(role_id, total_msgs, unlock_tier)
    if unlock_tier == 0 and free_count <= 0 and next_pw:
        await send_paywall_card(update, user_id, role_id, total_msgs)
        return

    if unlock_tier == 0 and free_count > 0:
        db.use_free_count(user_id)

    messages = _build_messages(user_id, role_id, user_text)
    await update.message.chat.send_action(action="typing")

    try:
        provider = await _get_provider_for_role(role_id)
        if config.ENABLE_STREAMING:
            full_reply = ""
            async for token in provider.chat_stream(
                messages=messages, max_tokens=1024, temperature=0.9,
            ):
                full_reply += token
        else:
            full_reply = await provider.chat(messages=messages, max_tokens=1024, temperature=0.9)
    except RateLimitError:
        await update.message.reply_text(_get_role_busy_message(role_id))
        return
    except TokenLimitError:
        await update.message.reply_text(
            f"对话太长啦～{role.get('name', '我') if role else '我'}的脑子装不下了，试试 /clear 清空再来聊好不好 (*/ω＼*)"
        )
        return
    except ProviderError as e:
        logger.error(f"LLM error user_id={user_id}: {e}")
        await update.message.reply_text(_get_role_busy_message(role_id))
        return

    if not full_reply:
        await update.message.reply_text(_get_role_busy_message(role_id))
        return

    clean_reply = MEDIA_TAG_RE.sub("", full_reply).strip()
        # 计算对方回复间隔（秒），用于节奏适应
    user_resp_time = 999.0
    if prev_msg_time:
        user_resp_time = _time.time() - prev_msg_time
    
    # ── 情感可视化：根据心情附加表情前缀 ──
    mood_emoji = ""
    try:
        mood = get_mood_for_user(user_id, role_id)
        mood_map = {
            "happy": "😊", "tired": "😮‍💨", "sleepy": "😴", "sad": "😢",
            "playful": "😝", "sexy": "😏", "angry": "😤", "neutral": "",
            "period": "😣",
        }
        mood_emoji = mood_map.get(mood.get("id", ""), "")
        if mood_emoji:
            clean_reply = mood_emoji + " " + clean_reply
    except Exception as e:
        logger.debug(f"Non-critical: {e}")
        mood = {"id": "neutral"}
    # delay disabled per user request
    # await asyncio.sleep(delay)

    # ?? TTS voice (check first, skip text if voice sent) ??
    voice_sent = False
    if config.TTS_ENABLED and clean_reply:
        try:
            voice_data = await generate_role_voice(
                clean_reply, role_id, role,
                trigger_rate=config.TTS_TRIGGER_RATE,
            )
            if voice_data:
                await update.message.reply_voice(voice_data)
                voice_sent = True
        except Exception as tts_err:
            logger.error(f"TTS failed for {role_id}: {tts_err}")

    if clean_reply:
        if not voice_sent:
            await update.message.reply_text(clean_reply)

        # Mood-aware sticker injection
        try:
            mood_id_val = mood.get("id", "neutral")
            if mood_id_val in ("happy", "playful", "sexy") and random.random() < 0.25:
                await update.message.reply_dice(emoji="??")
            elif mood_id_val in ("neutral",) and random.random() < 0.10:
                await update.message.reply_dice(emoji="??")
        except Exception:
            pass

        # -- Photo logic: 3 modes (explicit request / active inquiry / local match) --
    try:
        _pending_gen = context.bot_data.setdefault("_pending_photo", {})

        # Mode 1: User explicitly asking for photos -> generate + send now
        request_kw = [
            "发张", "看看你",
            "照片", "自拍", "写真",
            "jk照", "泳装", "泳衣",
            "丝袜", "cos", "拍一张",
        ]
        if any(kw in user_text for kw in request_kw):
            asyncio.create_task(_generate_and_send(update, "", role_id, role.get("name", "")))

        # Mode 2: Pending photo confirmation
        elif user_id in _pending_gen:
            affirm_kw = ["好", "要", "看", "发", "可以",
                         "行", "来", "yes", "ok", "嗯", "快", "show"]
            if any(kw in user_text for kw in affirm_kw):
                pending = _pending_gen.pop(user_id)
                try:
                    await update.message.reply_text(random.choice([
                        "稍等哦～我找找啊...",
                        "等一下下～翻箱倒柜中...",
                        "嘿嘿，让我找找...",
                    ]))
                    await update.message.reply_photo(pending)
                except Exception:
                    pass
            else:
                _pending_gen.pop(user_id, None)

        # Mode 3: Local media match (fast, no generation)
        else:
            media_path = _pick_media_by_context(role_id, full_reply)
            if media_path:
                try:
                    with open(media_path, "rb") as _mf:
                        await update.message.reply_photo(_mf.read())
                except Exception:
                    pass

        # Background pre-generation: AI offers photo -> generate for next turn
        if clean_reply:
            offer_kw = ["要看吗", "想看吗",
                        "给你看", "发你看",
                        "给你拍"]
            if any(kw in clean_reply for kw in offer_kw):
                asyncio.create_task(_pregenerate_photo(update, user_id, clean_reply, role_id, role.get("name", ""), _pending_gen))

    except Exception as e:
        logger.error(f"Photo flow error: {e}")

# -- Post-reply cleanup (wrapped to prevent error propagation) --
    try:
        messages.append({"role": "assistant", "content": full_reply})
        db.update_chat_history(user_id, messages)
        db.increment_message_count(user_id)
        new_total = (user_data.get("total_messages", 0) or 0) + 1
        next_paywall = get_current_paywall(role_id, new_total, unlock_tier)
        if next_paywall:
            await send_paywall_card(update, user_id, role_id, new_total)
        await try_trigger_yuanwei(update, user_id, role_id, new_total)
        await try_trigger_keepsake(update, user_id, role_id, new_total)
        await _check_and_summarize(user_id)
    except Exception as e:
        logger.error(f"Post-reply error: {e}")




async def handle_media_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理媒体消息（图片/视频/语音/文件/贴纸）"""
    user = update.effective_user
    user_id = user.id
    db.create_user(user_id)

    captions = {
        "photo": "📸 照片我收到啦～",
        "video": "🎬 视频看到了呢～",
        "voice": "🎤 语音消息...（可惜我还不能听语音呢，发文字给我叭～）",
        "audio": "🎵 音乐我收到了～",
        "document": "📎 文件已收到～",
        "sticker": "😊 贴纸好可爱～",
    }

    msg = update.message
    if msg.photo:
        reply = captions["photo"]
    elif msg.video:
        reply = captions["video"]
    elif msg.voice:
        reply = captions["voice"]
    elif msg.audio:
        reply = captions["audio"]
    elif msg.document:
        reply = captions["document"]
    elif msg.sticker:
        reply = captions["sticker"]
    else:
        reply = "收到啦～"

    await update.message.reply_text(reply)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """全局错误处理 —— 角色化报错"""
    logger.error(f"Update {update} caused error: {context.error}", exc_info=True)
    if update and isinstance(update, Update) and update.effective_message:
        try:
            role_id = "xiaolu"
            try:
                if hasattr(context, "bot_data"):
                    role_id = context.bot_data.get("role_id", "xiaolu")
            except Exception:
                pass
            await update.effective_message.reply_text(_get_role_busy_message(role_id))
        except Exception:
            pass


# ── 管理员上传对话 ──
UPLOAD_CHOOSE, UPLOAD_JSON = range(2)

_upload_state: dict[int, dict] = {}


async def upload_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /upload <user_id> —— 管理员上传对话到指定用户 """
    user = update.effective_user
    if user.id not in config.ADMIN_IDS:
        await update.message.reply_text("⛔ 此命令仅限管理员。")
        return ConversationHandler.END

    if not context.args:
        await update.message.reply_text("用法：`/upload <用户ID>`")
        return ConversationHandler.END

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("用户ID必须是数字。")
        return ConversationHandler.END

    _upload_state[user.id] = {"target": target_id}
    await update.message.reply_text(
        f"📥 请发送 JSON 格式的对话数据给用户 {target_id}：\n\n"
        "格式示例：\n"
        '```json\n[{"role":"user","content":"你好"},\n'
        ' {"role":"assistant","content":"你好呀～"}]\n```'
    )
    return UPLOAD_JSON


async def upload_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收 JSON 对话数据"""
    user = update.effective_user
    state = _upload_state.pop(user.id, None)

    if not state:
        await update.message.reply_text("会话已过期，请重新 `/upload <用户ID>`。")
        return ConversationHandler.END

    target_id = state["target"]
    raw = update.message.text.strip()

    try:
        messages = json.loads(raw)
    except json.JSONDecodeError:
        await update.message.reply_text("❌ JSON 格式错误，请检查后重新发送 `/upload`。")
        return ConversationHandler.END

    if not isinstance(messages, list):
        await update.message.reply_text("❌ 数据必须是 JSON 数组。")
        return ConversationHandler.END

    for m in messages:
        if not isinstance(m, dict) or "role" not in m or "content" not in m:
            await update.message.reply_text("❌ 每条消息必须包含 role 和 content 字段。")
            return ConversationHandler.END

    db.create_user(target_id)
    db.update_chat_history(target_id, messages)
    logger.info(f"admin {user.id} uploaded conversation for user {target_id} ({len(messages)} msgs)")

    await update.message.reply_text(
        f"✅ 已上传 {len(messages)} 条对话到用户 {target_id}。"
    )
    return ConversationHandler.END


async def upload_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("已取消上传。")
    _upload_state.pop(update.effective_user.id, None)
    return ConversationHandler.END


def get_upload_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("upload", upload_start)],
        states={
            UPLOAD_JSON: [MessageHandler(filters.TEXT & ~filters.COMMAND, upload_receive)],
        },
        fallbacks=[CommandHandler("cancel", upload_cancel)],
    )
