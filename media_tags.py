"""
智能媒体标签路由表
每个标签独立定义：图从哪个文件夹找(folder) + 需要什么解锁级别(tier)
支持全局默认 + 角色个性化标签
"""
from typing import Optional

# ── 全局默认标签（所有角色通用） ──
# tier: 0=免费 1=20条付费 2=70条付费 3=150条付费
DEFAULT_MEDIA_TAGS = {
    # Tier 0: 免费，随时可发
    "日常":   {"folder": "日常", "tier": 0},
    "自拍":   {"folder": "自拍", "tier": 0},
    "表情":   {"folder": "表情", "tier": 0},
    "通勤":   {"folder": "通勤", "tier": 0},
    "穿搭":   {"folder": "穿搭", "tier": 0},
    "美食":   {"folder": "美食", "tier": 0},
    "宠物":   {"folder": "宠物", "tier": 0},
    "工作":   {"folder": "工作", "tier": 0},
    "运动":   {"folder": "运动", "tier": 0},
    # Tier 1: 聊熟了(20条)
    "姿态":   {"folder": "姿态", "tier": 1},
    "旅游":   {"folder": "旅游", "tier": 1},
    "夜景":   {"folder": "夜景", "tier": 1},
    "起床":   {"folder": "起床", "tier": 1},
    "派对":   {"folder": "派对", "tier": 1},
    # Tier 2: 关系升温(70条)
    "性感":   {"folder": "性感", "tier": 2},
    "泳装":   {"folder": "泳装", "tier": 2},
    "沐浴":   {"folder": "沐浴", "tier": 2},
    "情趣":   {"folder": "情趣", "tier": 2},
    # Tier 3: 亲密关系(150条)
    "亲密":   {"folder": "亲密", "tier": 3},
    "裸露":   {"folder": "裸露", "tier": 3},
    "露点":   {"folder": "露点", "tier": 3},
    "全裸":   {"folder": "全裸", "tier": 3},
}

# ── 角色个性化标签 ──
# 继承全局标签，额外增加角色专属的分类
# 如果标签名与全局重复，角色版会覆盖全局版（比如tier不同）

# Role-specific tags (extend/override defaults per role)
ROLE_MEDIA_TAGS: dict[str, dict] = {}

def get_media_config(role_id: str, tag: str) -> dict | None:
    """Look up tag config: role-specific first, then global default."""
    role_tags = ROLE_MEDIA_TAGS.get(role_id, {})
    if tag in role_tags:
        return role_tags[tag]
    return DEFAULT_MEDIA_TAGS.get(tag)

def get_tags_for_role(role_id: str) -> dict:
    """Return merged tags for a role: global defaults + role overrides."""
    merged = dict(DEFAULT_MEDIA_TAGS)
    role_tags = ROLE_MEDIA_TAGS.get(role_id, {})
    merged.update(role_tags)
    return merged

def get_folder(role_id: str, tag: str) -> str | None:
    """Get the folder name for a tag. Role-specific first, then default."""
    cfg = get_media_config(role_id, tag)
    return cfg["folder"] if cfg else None

def get_tier(role_id: str, tag: str) -> int:
    """获取标签需要的解锁级别"""
    cfg = get_media_config(role_id, tag)
    if cfg:
        return cfg["tier"]
    return 0  # 默认免费

def get_max_tier_for_text(role_id, text):
    """Check AI reply text against all tags, return highest tier required."""
    all_tags = get_tags_for_role(role_id)
    max_tier = 0
    for tag, cfg in all_tags.items():
        if tag in text and cfg.get("tier", 0) > max_tier:
            max_tier = cfg["tier"]
    return max_tier

