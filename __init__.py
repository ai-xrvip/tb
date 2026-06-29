"""ai-xrvip-tgbot — re-exports for cleaner imports

Usage:
    from bot import config, db, ROLES, logger
"""

from config import config
from database import db
from roles import ROLES, get_role
from utils.logger import logger
from knowledge import get_knowledge_context, extract_knowledge_simple
from image_gen import generate_image
from video_gen import generate_video
from deep_dream import summarize_user_conversation
from media_tags import get_tags_for_role
from prompt_template import resolve_system_prompt
from localization import get_locale, get_dialect_context

__all__ = [
    "config",
    "db",
    "ROLES",
    "get_role",
    "logger",
    "get_knowledge_context",
    "extract_knowledge_simple",
    "generate_image",
    "generate_video",
    "summarize_user_conversation",
    "get_tags_for_role",
    "resolve_system_prompt",
    "get_locale",
    "get_dialect_context",
]
