"""
角色定义 —— 30 个中国各地区特色 AI 女友，每人一个独立 Bot
每个角色包含：基本信息、welcome 文案、media_dir、media_manifest、system_prompt

数据已迁移至 roles_config.json，本文件仅提供加载和查询接口。
"""

import json
from pathlib import Path

# ── 加载配置 ──
_config_path = Path(__file__).parent / "roles_config.json"
with open(_config_path, "r", encoding="utf-8") as f:
    _data = json.load(f)

ROLES = _data["ROLES"]
PAYWALLS = _data["PAYWALLS"]
YUANWEI_ROLES = _data["YUANWEI_ROLES"]
KEEPSAKE_ROLES = _data["KEEPSAKE_ROLES"]
DEFAULT_PAYWALL = _data["DEFAULT_PAYWALL"]


# ── 查询函数 ──


def get_role(role_id: str):
    """获取角色配置"""
    return ROLES.get(role_id)


def get_paywall(role_id: str) -> list[dict]:
    """获取角色的付费配置"""
    return PAYWALLS.get(role_id, DEFAULT_PAYWALL)


def get_current_paywall(role_id: str, message_count: int, current_tier: int) -> dict | None:
    """根据消息数和当前层级，返回下一个付费门槛（如果有）"""
    paywalls = get_paywall(role_id)
    for pw in paywalls:
        if pw["tier"] > current_tier and message_count >= pw["message_threshold"]:
            return pw
    return None
