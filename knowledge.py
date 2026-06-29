"""
知识图谱系统 —— 存储和检索用户记忆，让 AI 角色记住用户说过的事情

存储结构: (user_id, role_id, key, value, updated_at)
通过简单的键值对存储用户事实，在对话中自然引用
"""
import json
import time
from datetime import datetime, timezone
from typing import Optional

from database import db
from utils.logger import logger


def get_user_knowledge(user_id: int, role_id: str) -> dict[str, str]:
    """获取用户的所有知识条目，返回 {key: value}"""
    rows = db.conn.execute(
        "SELECT key, value FROM knowledge_graph WHERE user_id=? AND role_id=?",
        (user_id, role_id),
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


def set_user_knowledge(user_id: int, role_id: str, key: str, value: str):
    """设置一条知识条目"""
    now = time.time()
    db.conn.execute(
        "INSERT INTO knowledge_graph (user_id, role_id, key, value, updated_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id, role_id, key) DO UPDATE SET value=?, updated_at=?",
        (user_id, role_id, key, value, now, value, now),
    )
    db.conn.commit()


def delete_user_knowledge(user_id: int, role_id: str, key: str):
    """删除一条知识条目"""
    db.conn.execute(
        "DELETE FROM knowledge_graph WHERE user_id=? AND role_id=? AND key=?",
        (user_id, role_id, key),
    )
    db.conn.commit()


def get_knowledge_context(user_id: int, role_id: str) -> str:
    """获取注入 prompt 的知识上下文"""
    knowledge = get_user_knowledge(user_id, role_id)
    if not knowledge:
        return ""

    lines = ["[关于用户的记忆：以下是你在对话中了解到的关于对方的信息，可以自然地融入对话中]"]
    for key, value in knowledge.items():
        lines.append(f"- {key}: {value}")

    return "\n".join(lines)


# ── 自动知识提取（通过 LLM） ──

EXTRACTION_PROMPT = """你是一个信息提取助手。分析以下对话片段，提取关于"用户"的新事实。
只提取具体、客观的事实，例如：姓名、职业、爱好、喜欢的食物、宠物名、所在地等。
不要提取泛泛的闲聊内容。

请以JSON格式输出，每个事实一行：
{"key": "事实类别", "value": "事实内容"}

如果没有值得记录的新事实，输出空对象 {}。
只输出JSON，不要其他文字。

对话片段：
---
{conversation}
---"""


async def extract_knowledge_from_conversation(
    user_id: int,
    role_id: str,
    messages: list[dict],
) -> list[dict]:
    """从对话中提取新知识（通过 LLM）"""
    recent = messages[-20:] if len(messages) > 20 else messages
    if len(recent) < 2:
        return []

    conv_text = "\n".join(
        f"{'用户' if m['role'] == 'user' else 'AI'}: {m['content']}"
        for m in recent
    )
    if len(conv_text) > 2000:
        conv_text = conv_text[-2000:]

    try:
        from providers.factory import get_provider_from_config

        provider = get_provider_from_config()
        response = await provider.chat(
            messages=[
                {"role": "system", "content": "你只输出JSON，不要其他内容。"},
                {"role": "user", "content": EXTRACTION_PROMPT.format(conversation=conv_text)},
            ],
            max_tokens=300,
            temperature=0.1,
        )

        facts = []
        for line in response.strip().split("\n"):
            line = line.strip()
            if not line or line == "{}":
                continue
            try:
                fact = json.loads(line)
                if "key" in fact and "value" in fact:
                    facts.append(fact)
            except json.JSONDecodeError:
                continue

        for fact in facts:
            set_user_knowledge(user_id, role_id, fact["key"], fact["value"])

        if facts:
            logger.info(f"Knowledge extracted for user={user_id}: {facts}")

        return facts

    except Exception as e:
        logger.debug(f"Knowledge extraction failed (non-critical): {e}")
        return []


# ── 简洁版：基于规则的知识提取 ──

KNOWLEDGE_PATTERNS = {
    "我叫": "名字",
    "我是": "身份",
    "我的名字是": "名字",
    "我在": "所在地",
    "我住在": "所在地",
    "我喜欢吃": "喜欢的食物",
    "我爱吃": "喜欢的食物",
    "我养了": "宠物",
    "我的工作是": "职业",
    "我是一名": "职业",
    "我是一个": "身份",
    "我今年": "年龄",
    "我的生日是": "生日",
    "我是做": "职业",
    "我的爱好是": "爱好",
    "我喜欢": "爱好",
    "我家里有": "家庭信息",
    "我有": "个人信息",
    "我老家在": "家乡",
    "我来自": "家乡",
}


def extract_knowledge_simple(user_id: int, role_id: str, user_text: str):
    """基于规则的简单知识提取（不调用 LLM）"""
    stored = 0
    for pattern, key_name in KNOWLEDGE_PATTERNS.items():
        if pattern in user_text:
            idx = user_text.find(pattern) + len(pattern)
            rest = user_text[idx:]
            value = ""
            for ch in rest:
                if ch in "，。！？、；,.;!? \t\n":
                    break
                value += ch
                if len(value) >= 10:
                    break
            if value and len(value) >= 1:
                set_user_knowledge(user_id, role_id, key_name, value.strip())
                stored += 1
                logger.debug(f"Simple knowledge: user={user_id} {key_name}={value.strip()}")

    return stored > 0
