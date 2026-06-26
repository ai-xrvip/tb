"""世界书/记忆系统 —— 参考 SillyTavern 的 Lore Book 设计

角色可以有多个"世界条目"(lore entries)，包含触发关键词和记忆内容。
当用户消息匹配到触发词时，相关记忆会被注入到 system prompt 中。
"""
import json
import os
from pathlib import Path
from typing import Optional
from utils.logger import logger

# 世界书存储路径
LORE_DIR = Path(__file__).parent.parent / "lore" / "books"


def _get_book_path(role_id: str) -> Path:
    return LORE_DIR / f"{role_id}.json"


def get_lore_context(user_id: int, role_id: str) -> Optional[str]:
    """根据用户消息和角色获取匹配的记忆上下文"""
    book_path = _get_book_path(role_id)
    if not book_path.exists():
        return None

    try:
        with open(book_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    if not entries:
        return None

    # 返回永久记忆（always_active = true 的条目）
    active = [e for e in entries if e.get("always_active", False)]
    if active:
        return "\n".join(e["content"] for e in active)

    return None


def get_lore_for_message(user_id: int, role_id: str, user_text: str) -> Optional[str]:
    """根据用户消息匹配触发词，返回匹配的记忆"""
    book_path = _get_book_path(role_id)
    if not book_path.exists():
        return None

    try:
        with open(book_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    matched = []
    text_lower = user_text.lower()

    for entry in entries:
        if entry.get("always_active"):
            continue  # 永久记忆由 get_lore_context 处理
        keywords = entry.get("keywords", [])
        if any(kw.lower() in text_lower for kw in keywords):
            matched.append(entry["content"])

    return "\n".join(matched) if matched else None


def set_lore_book(role_id: str, entries: list[dict]) -> bool:
    """设置角色的世界书"""
    LORE_DIR.mkdir(parents=True, exist_ok=True)
    book_path = _get_book_path(role_id)
    try:
        with open(book_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        logger.info(f"Lore book saved for role={role_id} ({len(entries)} entries)")
        return True
    except IOError as e:
        logger.error(f"Failed to save lore book for {role_id}: {e}")
        return False


def get_lore_book(role_id: str) -> list[dict]:
    """获取角色的世界书"""
    book_path = _get_book_path(role_id)
    if not book_path.exists():
        return []
    try:
        with open(book_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def get_lore_entries(role_id: str, user_text: str) -> Optional[str]:
    """根据用户消息中的关键词匹配世界书条目"""
    book_path = _get_book_path(role_id)
    if not book_path.exists():
        return None

    try:
        with open(book_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    if not entries or not user_text:
        return None

    # 关键词匹配
    matched = []
    user_lower = user_text.lower()
    for e in entries:
        keywords = e.get("keywords", [])
        if keywords and any(kw.lower() in user_lower for kw in keywords):
            matched.append(e["content"])

    return "\n".join(matched) if matched else None


