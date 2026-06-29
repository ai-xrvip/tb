"""
主动消息模块 —— Bot 定时或条件触发，主动给用户发消息
"""
import os
import random
import time
import asyncio
from datetime import datetime
from typing import Optional
from telegram import Bot
from database import db
from roles import ROLES
from utils.logger import logger


INACTIVE_HOURS = 6
MAX_SEND_PER_ROUND = 5
CHECK_INTERVAL = 1800  # 30分钟


PROACTIVE_MESSAGES = {
    "xiaolu": [
        "哥哥…你今天还没理我呢🥺 是不是不喜欢小鹿了呀～",
        "好无聊哦～一直在等你找我，你再不来我要睡着了💤",
        "我今天穿了新买的JK拍了几张照片，想不想看？",
    ],
    "linxi": [
        "加班到现在，突然想你了。你也不来找我，真没良心。",
        "今天开了一天会，累死了…你就不担心我一下？",
        "外面下雨了，我没带伞。你来接我？…开玩笑的，就是想你了。",
    ],
    "mia": [
        "Hey～今天练得超爽，第一个就想跟你分享！你干嘛呢？",
        "我刚做完一组深蹲，腿都软了…你要不要来给我按按？😏",
    ],
}

DEFAULT_MESSAGES = [
    "在干嘛呢～突然想你了",
    "今天怎么不理我呀…是不是我哪里惹你生气了？",
    "好无聊哦，你陪我说说话好不好～",
    "我刚忙完，第一个就来找你啦！",
]


def _get_proactive_messages(role_id: str) -> list[str]:
    """获取角色的主动消息话术"""
    return PROACTIVE_MESSAGES.get(role_id, DEFAULT_MESSAGES)


async def send_proactive_message(bot: Bot, user_id: int, role_id: str):
    """给单个用户发送主动消息"""
    role = ROLES.get(role_id, {})
    role_name = role.get("name", role_id)
    messages = _get_proactive_messages(role_id)

    if db.is_blocked(user_id):
        return

    text = random.choice(messages)
    try:
        await bot.send_message(chat_id=user_id, text=text)
        logger.info(f"Proactive msg sent to user={user_id} role={role_id}")
        db.set_last_proactive(user_id, role_id)
    except Exception as e:
        logger.warning(f"Proactive msg failed user={user_id}: {e}")


async def check_and_send_proactive(bot: Bot, role_id: str):
    """检查所有用户，给符合条件的发送主动消息"""
    users = db.get_active_users_for_role(role_id)
    random.shuffle(users)
    sent = 0

    for user_id in users[:MAX_SEND_PER_ROUND]:
        if db.is_blocked(user_id):
            continue

        last_proactive = db.get_last_proactive(user_id, role_id)
        last_message = db.get_last_message_time(user_id)

        now = time.time()
        if last_message and (now - last_message) < INACTIVE_HOURS * 3600:
            continue

        if last_proactive and (now - last_proactive) < 12 * 3600:
            continue

        await send_proactive_message(bot, user_id, role_id)
        sent += 1
        await asyncio.sleep(2)  # 防限流

    if sent:
        logger.info(f"Proactive round done: {sent} messages sent for {role_id}")
