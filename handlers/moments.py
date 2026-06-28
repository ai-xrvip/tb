"""
AI Moment broadcast system - dynamic text + img2img image, no buttons.

Once per day (22-26h jitter), sends a personalized life update to
users who chatted with the role and haven't been silent for 2+ days.
Text is AI-generated based on weather, time, user interests.
Image is generated via img2img matching the text.
"""
import random
import asyncio
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes
from config import config
from database import db
from roles import ROLES
from utils.logger import logger

MOMENTS_INTERVAL_MIN = 22 * 3600
MOMENTS_INTERVAL_MAX = 26 * 3600
SILENCE_CUTOFF = 48 * 3600

async def _generate_moment_text(role_id, role, user_id):
    from prompt_template import resolve_system_prompt
    from providers.factory import get_provider_from_config
    try:
        profile = db.conn.execute(
            "SELECT interests, facts FROM user_profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
        interests = profile["interests"] if profile else ""
    except Exception:
        interests = ""
    role_name = role.get("name", role_id)
    moment_prompt = f'你是{role_name}，发一条朋友圈。写1-2句话，自然可爱，符合人设。对方兴趣爱好：{interests}。可以结合当前时间、天气、城市。只用Telegram原生emoji，禁止颜文字。像真人一样随意自然。只输出朋友圈文字，不要任何前缀。'
    system = role.get("system_prompt", "")[:500]
    full = resolve_system_prompt({"id": role_id, "system_prompt": system}, '大家', "", "")
    try:
        provider = get_provider_from_config()
        text = await provider.chat(
            messages=[
                {"role": "system", "content": full},
                {"role": "user", "content": moment_prompt},
            ],
            max_tokens=120,
            temperature=0.95,
        )
        if text and len(text.strip()) > 5:
            return text.strip()
    except Exception as e:
        logger.error(f"Moment text gen failed: {e}")
    return random.choice([
        '今天突然想到你，就过来看看～你在干嘛呢？\ud83d\udc95',
        '生活里的小美好，第一个就想告诉你。✨',
        '没什么，就是想你了。\ud83d\udf19',
    ])

async def _generate_moment_photo(text, role_id):
    try:
        from image_gen import generate_image
        return await generate_image(text, role_id)
    except Exception as e:
        logger.error(f"Moment photo gen failed: {e}")
        return None

async def _send_moment_to_user(bot, user_id, role_name, text):
    actual_role_id = ""
    for rid, r in ROLES.items():
        if r.get("name", "") == role_name:
            actual_role_id = rid
            break
    if not actual_role_id:
        actual_role_id = "xiaolu"
    photo_data = await _generate_moment_photo(text, actual_role_id)
    caption = f'\ud83d\udc9d {role_name}的日常\\n\\n{text}'
    try:
        if photo_data and len(photo_data) > 500:
            await bot.send_photo(chat_id=user_id, photo=photo_data, caption=caption)
        else:
            await bot.send_message(chat_id=user_id, text=caption)
        return True
    except Exception as e:
        logger.error(f"Moment send failed to {user_id}: {e}")
        return False

async def send_moment_broadcast(context):
    role_id = context.bot_data.get("role_id", "")
    role = ROLES.get(role_id, {})
    role_name = role.get("name", role_id)
    try:
        users = db.conn.execute(
            "SELECT DISTINCT user_id FROM users WHERE total_messages > 0 AND current_role = ?",
            (role_id,)
        ).fetchall()
    except Exception as e:
        logger.error(f"Moment: failed to get users: {e}")
        return
    if not users:
        return
    import time
    now = time.time()
    user_ids = []
    for u in users:
        uid = u["user_id"]
        try:
            last_msg = db.get_last_message_time(uid)
            if last_msg is None or (now - last_msg) < SILENCE_CUTOFF:
                user_ids.append(uid)
        except Exception:
            user_ids.append(uid)
    skipped = len(users) - len(user_ids)
    if skipped:
        logger.info(f"Moment: {role_name} skipping {skipped} silent users")
    if not user_ids:
        return
    logger.info(f"Moment: {role_name} broadcasting to {len(user_ids)} users")
    text = await _generate_moment_text(role_id, role, user_ids[0])
    success = 0
    for user_id in user_ids:
        if await _send_moment_to_user(context.bot, user_id, role_name, text):
            success += 1
        if success % 30 == 0:
            await asyncio.sleep(1)
    logger.info(f"Moment: {role_name} sent to {success}/{len(user_ids)} users")