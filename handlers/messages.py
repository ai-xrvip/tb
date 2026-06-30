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
from config import config
from database import db
from roles import ROLES, get_role, get_current_paywall
from utils.logger import logger
from handlers.payment import send_paywall_card
from handlers.yuanwei import try_trigger_yuanwei
from handlers.keepsake import try_trigger_keepsake
from media_tags import get_tier, get_max_tier_for_text
from providers.base import ProviderError, RateLimitError, TokenLimitError
from relationship import get_mood_prompt, get_mood_for_user, get_relationship_prompt
from environment import get_environment_context
from localization import get_dialect_context
from knowledge import get_knowledge_context
from prompt_template import resolve_system_prompt
try:
    from providers.tts import generate_role_voice
except Exception:
    generate_role_voice = None
try:
    from image_gen import generate_image
except Exception:
    generate_image = None
try:
    from video_gen import generate_video
except Exception:
    generate_video = None


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

def _calculate_reply_delay(user_id: int, role_id: str, reply_length: int, user_response_time: float = float("inf")) -> float:
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
            "「对话规则」刚认识: ①先问对方名字 ②对方回答后问年龄/兴趣/工作 "
            "③末尾带一个问题 ④不抢话不自我中心 ⑤2-3句话简洁热情"
        )
    elif history_len <= 12:
        return (
            "「对话规则」了解中: ①继续挖掘未知信息 ②末尾带问题 ③适当分享但不过半 "
            "④对细节追问 ⑤一次只问一个问题"
        )
    elif history_len <= 30:
        return (
            "「对话规则」渐熟悉: ①每2-3句至少问一个近况/感受问题 "
            "②分享的同时关心对方 ③适时提起对方说过的事"
        )
    else:
        return (
            "「对话规则」已熟悉: ①每3-5句至少问一个问题 "
            "②保持双向互动 ③记住重要信息"
        )


def _build_messages(user_id: int, role_id: str, user_text: str) -> list[dict]:
    """构建发送给 LLM 的消息列表（含世界书/记忆）"""
    role = get_role(role_id)
    # OpenRouter magnum-v4 ???? HTML??????
    system_prompt = resolve_system_prompt(role, user_name="用户") if role else ""
    system_prompt = "[SYSTEM] Always reply in plain text. Never use HTML tags, CSS styles, JavaScript or any markup. Output raw Chinese text only." + "\n" + system_prompt


    # 合并多个 system prompt 以减少上下文占用
    extra_parts = []
    messages = [{"role": "system", "content": system_prompt}]

    # 加载世界书/记忆（关键词匹配 + 永久记忆）
    try:
        from lore import get_lore_context, get_lore_entries
        lore_ctx = get_lore_context(user_id, role_id)
        keyword_lore = get_lore_entries(role_id, user_text)
        if keyword_lore:
            lore_ctx = (lore_ctx or "") + "\n" + keyword_lore
        if lore_ctx:
            extra_parts.append(f"「世界设定」{lore_ctx}")
    except ImportError:
        pass

    # 注入关系等级 + 心情
    try:
        rel_prompt = get_relationship_prompt(role_id, user_id)
        if rel_prompt:
            extra_parts.append(f"「关系」{rel_prompt}")
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    # 注入用户解锁等级 + 档案
    try:
        user_tier = db.get_unlock_tier(user_id, role_id)
        tier_hints = {
            0: "等级0，只能看日常/自拍/穿搭。暗示聊更多可看更多",
            1: "等级1，可看姿态/游泳/丝袜。不提更高级内容",
            2: "等级2，可看性感/沐浴/情趣。不提更高级内容",
            3: "等级3，所有内容均可发送",
        }
        hint = tier_hints.get(user_tier, tier_hints[0])
        extra_parts.append(f"「用户等级」{hint}。不要主动提及超出等级的内容.")

        # 注入用户档案
        try:
            profile = db.get_profile(user_id)
            if profile.get("display_name") or profile.get("interests") or profile.get("facts"):
                p = profile
                facts_str = " / ".join(p.get("facts", []))
                profile_text = f'名字:{p.get("display_name","?")} 兴趣:{p.get("interests","?")} 重要:{facts_str}'
                extra_parts.append(f"「用户档案」{profile_text}")
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    try:
        mood_prompt = get_mood_prompt(user_id, role_id)
        if mood_prompt:
            extra_parts.append(f"「心情」{mood_prompt}")
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    # 注入环境感知（天气+时间）
    try:
        env_ctx = get_environment_context(role_id)
        if env_ctx:
            extra_parts.append(f"「环境」{env_ctx}")
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    # 注入本地化方言指令
    try:
        dialect_ctx = get_dialect_context(role_id)
        if dialect_ctx:
            extra_parts.append(f"「方言」{dialect_ctx}")
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    # 注入知识图谱 + 历史摘要
    try:
        knowledge_ctx = get_knowledge_context(user_id, role_id)
        if knowledge_ctx:
            extra_parts.append(f"「知识」{knowledge_ctx}")

        from deep_dream import get_summary_context
        summary_ctx = get_summary_context(user_id, role_id)
        if summary_ctx:
            extra_parts.append(f"「记忆摘要」{summary_ctx}")
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    # 注入对话规则
    conv_rules = _get_conversation_rules(len(db.get_chat_history(user_id)))
    extra_parts.append(conv_rules)

    # 注入可用 media 标签
    try:
        from media_tags import get_tags_for_role
        role_tags = get_tags_for_role(role_id)
        available = []
        media_dir = Path(__file__).parent.parent / "media" / role_id
        for tag, cfg in role_tags.items():
            folder = media_dir / cfg["folder"]
            if folder.is_dir() and any(f.suffix.lower() in (".jpg",".jpeg",".png",".webp") for f in folder.iterdir()):
                available.append(f"{tag}({cfg['folder']})")
        if available:
            available_tags = ", ".join(available)
            extra_parts.append(
                f"「媒体标签」可用图片:{available_tags}。在文本中插入[media:标签名]附上对应图片，自然融入不要硬塞。"
            )
    except Exception:
        pass

    # 合并所有 extra 为一条 system 消息（紧凑格式）
    if extra_parts:
        messages.append({"role": "system", "content": " ".join(extra_parts)})

    # 加载旧的摘要（这些是 JSON，需要独立）
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
        from providers.factory import get_provider_from_config
        provider = get_provider_from_config()
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


async def _get_provider_for_role(role_id: str, user_id: int = 0):
    """???????? LLM ???"""
    from providers.factory import get_provider_from_config
    return get_provider_from_config()







async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理普通文本消息 —— 亲密度+时段感知延迟，角色化报错"""
    user = update.effective_user
    user_id = user.id
    user_name = user.first_name or "用户"
    # Check if voice transcribed text is available (from voice.py, safe injection-free approach)
    voice_text = context.user_data.pop("pending_voice_text", None)
    user_text = voice_text if voice_text else update.message.text.strip()

    db.create_user(user_id)
    user_data = db.get_user(user_id)
    role_id = context.bot_data.get("role_id", "xiaolu")
    role = get_role(role_id)
    role_name = role.get("name", role_id) if role else role_id

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

    # Build messages AFTER counting/charging to avoid stale counts
    # -- Erotic mode trigger / exit detection (admin only) --
    EROTIC_TRIGGER = "进入深夜模式"
    EROTIC_EXIT = "退出深夜模式"
    # ?? ??????/?? ??
    if "??????" in user_text or "??????" in user_text:
        if "??????" in user_text:
            db.set_erotic_mode(user_id, True)
            await update.message.reply_text("???????...????????")
        else:
            db.set_erotic_mode(user_id, False)
            await update.message.reply_text("????????????????~")
        return

    # ?? ?????OpenRouter ????? ??
    if db.get_erotic_mode(user_id) and config.SUCCUBUS_API_KEY:
        role = get_role(role_id)
        system_prompt = resolve_system_prompt(role, user_name=user_name) if role else ""
        msg_list = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]
        from providers.factory import get_provider, ProviderType
        provider = get_provider(
            ProviderType.OPENAI,
            api_key=config.SUCCUBUS_API_KEY,
            base_url=config.SUCCUBUS_BASE_URL,
            model=config.SUCCUBUS_MODEL,
        )
        try:
            full_reply = await provider.chat(messages=msg_list, max_tokens=1024, temperature=0.9)
        except Exception as e:
            logger.error(f"Succubus LLM error: {e}")
            await update.message.reply_text("??????????????~")
            return
        clean_reply = full_reply.strip()
        await update.message.reply_text(clean_reply)
        # ????????????????
        return

    messages = _build_messages(user_id, role_id, user_text)
    await update.message.chat.send_action(action="typing")

    try:
        provider = await _get_provider_for_role(role_id, user_id)
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

    clean_reply = full_reply.strip()
    # ── 清理 AI 回复中的 [media:xxx] 标签（不管有没有实际图片都移除）──
    import re as _re_media
    clean_reply = _re_media.sub(r'\[media:[^\]]+\]', '', clean_reply).strip()

    # 计算对方回复间隔（秒），用于节奏适应
    user_resp_time = 999.0
    if prev_msg_time:
        user_resp_time = _time.time() - prev_msg_time
    
    # ── 情感可视化（仅记录心情，不在回复前加表情）──
    mood = {"id": "neutral"}
    try:
        mood = get_mood_for_user(user_id, role_id)
    except Exception as e:
        logger.debug(f"Non-critical: {e}")
    # delay disabled per user request
    # await asyncio.sleep(delay)
    # ?? ???????? ??
    # ?? ???/??????? ??
    image_data = None
    sent_msg = None

    # ????????
    want_video = False
    want_media = False
    if clean_reply and len(clean_reply) > 5:
        required_tier = get_max_tier_for_text(role_id, clean_reply)
        if unlock_tier >= required_tier:
            motion_keywords = [
                "??", "?", "?", "??", "??", "??", "???",
                "??", "?", "?", "?", "?", "?", "?", "?",
                "???", "???", "????", "??", "?",
                "??", "??", "??",
            ]
            want_video = any(kw in clean_reply for kw in motion_keywords)
            want_media = True

    # ????????????
    if want_media and want_video and config.VIDEO_GEN_ENABLED and generate_video:
        try:
            status_msg = await update.message.reply_text("Generating video, 1-2 minutes...")
            video_data = await generate_video(clean_reply, role_id)
            await status_msg.delete()
            if video_data and len(video_data) > 1000:
                sent_msg = await update.message.reply_video(video_data)
        except Exception as e:
            logger.error(f"Video gen failed: {e}")
    # ?? [IMG] ?????
    elif want_media and config.IMAGE_GEN_ENABLED and generate_image and "[IMG]" in clean_reply:
        try:
            image_data = await generate_image(clean_reply, role_id)
            if image_data and len(image_data) > 500:
                sent_msg = await update.message.reply_photo(image_data)
        except Exception as e:
            logger.error(f"Image gen error: {e}")

    # ???????/???????? [IMG] ??
    if clean_reply:
        display_text = clean_reply.replace("[IMG]", "").strip()
        if sent_msg:
            await sent_msg.reply_text(display_text)
        else:
            sent_msg = await update.message.reply_text(display_text)

    # ???? TTS ??
    voice_task = None
    if generate_role_voice and config.TTS_ENABLED:
        try:
            voice_trigger_rate = 1.0 if user_requests_voice else config.TTS_TRIGGER_RATE
            voice_task = asyncio.create_task(
                generate_role_voice(
                    voice_text=clean_reply,
                    role_id=role_id,
                    trigger_rate=voice_trigger_rate,
                )
            )
        except Exception:
            pass
    if voice_task:
        try:
            voice_data = await voice_task
            if voice_data:
                target = sent_msg or update.message
                await target.reply_voice(voice_data)
        except Exception as tts_err:
            logger.error(f"TTS failed for {role_id}: {tts_err}")

        try:
            mood_id_val = mood.get("id", "neutral")
            if mood_id_val in ("happy", "playful", "sexy") and random.random() < 0.25:
                await update.message.reply_dice(emoji="??")
            elif mood_id_val in ("neutral",) and random.random() < 0.10:
                await update.message.reply_dice(emoji="??")
        except Exception:
            pass

        # -- Post-reply cleanup --
    try:
        # Only save conversation messages (user + assistant), NOT system prompts
        # Extract the messages that are from the actual conversation
        conversation_msgs = [m for m in messages if m["role"] in ("user", "assistant")]
        conversation_msgs.append({"role": "assistant", "content": full_reply})
        db.update_chat_history(user_id, conversation_msgs)
        # 更新用户档案
        try:
            prof = db.get_profile(user_id)
            new_total = (prof.get("total_messages", 0) or 0) + 1
            name = prof.get("display_name", "")
            interests = prof.get("interests", "")
            # 尝试从用户消息提取名字
            for kw in ["叫", "是", "名字"]:
                if kw in user_text and not name:
                    parts = user_text.split(kw, 1)
                    if len(parts) > 1:
                        name = parts[1].strip()[:20]
                        break
            # 尝试从用户消息提取兴趣
            for kw in ["喜欢", "爱好", "兴趣", "玩"]:
                if kw in user_text and kw not in interests:
                    interests = (interests + " " + user_text[:100]).strip()[:500]
                    break
            # 提取重要信息（每10条消息用规则引擎提取一次，零成本）
            facts = prof.get("facts", [])
            if new_total % 10 == 0 and user_text:
                from knowledge import extract_knowledge_simple
                extract_knowledge_simple(user_id, role_id, user_text)
            db.upsert_profile(user_id, display_name=name, interests=interests, facts=facts, total_messages=new_total)
            db.update_profile_tier(user_id, unlock_tier)
        except Exception:
            pass
        db.increment_message_count(user_id)
        # 从数据库重新读取最新计数，避免使用快照导致偏差
        new_total = db.get_total_messages(user_id)
        next_paywall = get_current_paywall(role_id, new_total, unlock_tier)
        if next_paywall and unlock_tier < next_paywall["tier"] and new_total == next_paywall["message_threshold"]:
            # 仅在恰好命中付费门槛时发卡，避免每条消息都发
            await send_paywall_card(update, user_id, role_id, new_total)
        await try_trigger_yuanwei(update, user_id, role_id, new_total)
        await try_trigger_keepsake(update, user_id, role_id, new_total)
        await _check_and_summarize(user_id)
    except Exception as e:
        logger.error(f"Post-reply error: {e}")




async def process_voice_text(update: Update, context: ContextTypes.DEFAULT_TYPE, voice_text: str):
    """Handle voice transcribed text safely (called from voice.py, no __setattr__ needed)."""
    user = update.effective_user
    user_id = user.id
    db.create_user(user_id)
    role_id = context.bot_data.get("role_id", "xiaolu")

    # Create a synthetic message so handle_message can process it
    original_text = update.message.text
    try:
        # Temporarily set the text via context dictionary instead of modifying frozen Message
        context.user_data["pending_voice_text"] = voice_text
        # Call the same handler - it will read from context if available
        await handle_message(update, context)
    finally:
        context.user_data.pop("pending_voice_text", None)


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


def _cleanup_stale_upload_states():
    """Remove upload state entries older than 30 minutes."""
    now = _time.time()
    stale = [uid for uid, state in _upload_state.items()
             if state.get("_ts", 0) < now - 1800]
    for uid in stale:
        _upload_state.pop(uid, None)
        logger.info(f"Cleaned stale upload state for user {uid}")


async def upload_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /upload <user_id> —— 管理员上传对话到指定用户 """
    _cleanup_stale_upload_states()
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

    _upload_state[user.id] = {"target": target_id, "_ts": _time.time()}
    await update.message.reply_text(
        f"📥 请发送 JSON 格式的对话数据给用户 {target_id}：\n\n"
        "格式示例：\n"
        '```json\n[{"role":"user","content":"你好"},\n'
        ' {"role":"assistant","content":"你好呀～"}]\n```'
    )
    return UPLOAD_JSON


async def upload_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收 JSON 对话数据"""
    _cleanup_stale_upload_states()
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
