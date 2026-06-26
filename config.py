"""
配置管理 —— 多 Bot Token + 多 LLM 提供商 + 支付 + 插件系统

参考:
- chatgpt-on-wechat: 多平台 + 插件
- karfly bot: 多语言 + 流式
- Openaibot: 角色预设 + 多模型
"""
import os
import re
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv()


def _load_bot_tokens() -> dict[str, str]:
    """动态加载所有 *_BOT_TOKEN 环境变量"""
    tokens = {}
    pattern = re.compile(r'^(.+)_BOT_TOKEN$')
    for key, value in os.environ.items():
        m = pattern.match(key)
        if m and value:
            role_id = m.group(1).lower()
            tokens[role_id] = value
    return tokens


class Config:
    # ── LLM 提供商选择 ──
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "deepseek")  # deepseek / openai

    # ── DeepSeek ──
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # ── OpenAI ──
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str | None = os.getenv("OPENAI_BASE_URL") or None
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")

    # ── 流式输出 ──
    ENABLE_STREAMING: bool = os.getenv("ENABLE_STREAMING", "true").lower() == "true"

    # ── 动态加载所有 Bot Token ──
    BOT_TOKENS: dict[str, str] = _load_bot_tokens()

    # ── Admin ──
    ADMIN_IDS: list[int] = [
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
    ]

    # ── 数据库 ──
    DB_PATH: str = os.getenv("DB_PATH", str(Path(__file__).parent / "bot.db"))

    # ── 对话 ──
    MAX_HISTORY_ROUNDS: int = int(os.getenv("MAX_HISTORY_ROUNDS", "100"))
    FREE_TRIAL_COUNT: int = int(os.getenv("FREE_TRIAL_COUNT", "20"))

    # ── Webhook ──
    WEBHOOK_URL: str | None = os.getenv("WEBHOOK_URL") or None

    # ── 支付（预留） ──
    DONATION_API_TOKEN: str = os.getenv("DONATION_API_TOKEN", "")
    PAYMENT_MODE: str = os.getenv("PAYMENT_MODE", "test")  # test / production

    # ── 速率限制 ──
    RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
    RATE_LIMIT_MAX: int = int(os.getenv("RATE_LIMIT_MAX", "15"))
    RATE_LIMIT_WINDOW: int = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

    # ── 语音转文字 ──
    ENABLE_STT: bool = os.getenv("ENABLE_STT", "false").lower() == "true"
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "tiny")  # tiny / small / medium
    WHISPER_LANGUAGE: str | None = os.getenv("WHISPER_LANGUAGE") or "zh"  # zh / auto / en

    # ── 插件 ──
    ENABLED_PLUGINS: list[str] = [
        x.strip() for x in os.getenv("ENABLED_PLUGINS", "greetings,mood_plugin").split(",") if x.strip()
    ]

    # ── 频道公告 ──
    ANNOUNCEMENT_CHANNEL: str | None = os.getenv("ANNOUNCEMENT_CHANNEL") or None  # @频道名 或 -100xxx

    # ── 保活（Railway 防休眠） ──
    ENABLE_KEEPALIVE: bool = os.getenv("ENABLE_KEEPALIVE", "true").lower() == "true"
    KEEPALIVE_INTERVAL: int = int(os.getenv("KEEPALIVE_INTERVAL", "240"))  # 秒，默认4分钟

    # ── TTS 语音 ──
    TTS_ENABLED: bool = os.getenv("TTS_ENABLED", "true").lower() == "true"
    TTS_TRIGGER_RATE: float = float(os.getenv("TTS_TRIGGER_RATE", "0.15"))
    TTS_VOICE: str = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    TTS_MAX_CHARS: int = int(os.getenv("TTS_MAX_CHARS", "300"))

    # ── STT 语音转文字 ──
    STT_PROVIDER: str = os.getenv("STT_PROVIDER", "groq")  # groq (free) or openai
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_STT_MODEL: str = os.getenv("GROQ_STT_MODEL", "whisper-large-v3")

    # ── Cloudflare STT (免费) ──
    CF_ACCOUNT_ID: str = os.getenv("CF_ACCOUNT_ID", "")
    CF_API_TOKEN: str = os.getenv("CF_API_TOKEN", "")




    # ── 群聊 ──
    ENABLE_GROUP_CHAT: bool = os.getenv("ENABLE_GROUP_CHAT", "true").lower() == "true"

    # ── 语言 ──
    DEFAULT_LANG: str = os.getenv("DEFAULT_LANG", "zh")

    @classmethod
    def get_active_bots(cls) -> dict[str, str]:
        """返回所有配置了 Token 的角色"""
        return {k: v for k, v in cls.BOT_TOKENS.items() if v}

    @classmethod
    def validate(cls) -> list[str]:
        errors = []
        provider = cls.LLM_PROVIDER

        _placeholder_keys = ("sk-your-", "your-key-here", "your-deepseek", "your-openai", "example", "placeholder")
        def _is_placeholder(val: str) -> bool:
            if not val:
                return False
            return any(p in val.lower() for p in _placeholder_keys)

        if provider == "deepseek":
            if not cls.DEEPSEEK_API_KEY:
                errors.append("LLM_PROVIDER=deepseek but DEEPSEEK_API_KEY not set")
            elif _is_placeholder(cls.DEEPSEEK_API_KEY):
                errors.append("DEEPSEEK_API_KEY looks like a placeholder, please set real key")
        elif provider == "openai":
            if not cls.OPENAI_API_KEY:
                errors.append("LLM_PROVIDER=openai but OPENAI_API_KEY not set")
            elif _is_placeholder(cls.OPENAI_API_KEY):
                errors.append("OPENAI_API_KEY looks like a placeholder, please set real key")

        active = cls.get_active_bots()
        if not active:
            errors.append("At least one Bot Token required (format: {ROLE_ID}_BOT_TOKEN)")
        else:
            for role_id, token in active.items():
                if _is_placeholder(token):
                    errors.append(f"{role_id.upper()}_BOT_TOKEN looks like a placeholder, please set real Token")

        return errors

config = Config()
