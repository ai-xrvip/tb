"""
Configuration manager — Multi Bot Token + Multi LLM Provider + Payment + Plugin system

References:
- chatgpt-on-wechat: Multi-platform + plugins
- karfly bot: Multi-language + streaming
- Openaibot: Role presets + multi-model
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
    """Load all *_BOT_TOKEN env vars dynamically"""
    tokens = {}
    pattern = re.compile(r'^(.+)_BOT_TOKEN$')
    for key, value in os.environ.items():
        m = pattern.match(key)
        if m and value:
            role_id = m.group(1).lower()
            tokens[role_id] = value
    return tokens


# If /data (Railway persistent volume) exists, default DB there
_data_dir = Path("/data")
_default_db = str(_data_dir / "bot.db") if _data_dir.exists() and os.access(str(_data_dir), os.W_OK) else str(Path(__file__).parent / "bot.db")

class Config:
    # ── LLM Provider ──
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "deepseek")  # deepseek / openai

    # ── DeepSeek ──
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # ── OpenAI ──
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str | None = os.getenv("OPENAI_BASE_URL") or None
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")

    # ── Streaming ──
    ENABLE_STREAMING: bool = os.getenv("ENABLE_STREAMING", "true").lower() == "true"

    # Image Generation (OpenAI-compatible)
    IMAGE_GEN_ENABLED: bool = os.getenv("IMAGE_GEN_ENABLED", "true").lower() == "true"
    IMAGE_GEN_API_KEY: str = os.getenv("IMAGE_GEN_API_KEY", "")
    IMAGE_GEN_BASE_URL: str = os.getenv("IMAGE_GEN_BASE_URL", "https://apihub.agnes-ai.com/v1")
    IMAGE_GEN_MODEL: str = os.getenv("IMAGE_GEN_MODEL", "agnes-image-2.1-flash")
    IMAGE_GEN_SIZE: str = os.getenv("IMAGE_GEN_SIZE", "1024x1024")
    # ?? Erotic Mode LLM (OpenRouter uncensored model) ??
    EROTIC_API_KEY: str = os.getenv("EROTIC_API_KEY", "")
    EROTIC_BASE_URL: str = os.getenv("EROTIC_BASE_URL", "https://openrouter.ai/api/v1")
    EROTIC_MODEL: str = os.getenv("EROTIC_MODEL", "anthracite-org/magnum-v4-72b")


    # Video Generation (Agnes AI, image-to-video / text-to-video)
    VIDEO_GEN_ENABLED: bool = os.getenv("VIDEO_GEN_ENABLED", "true").lower() == "true"
    VIDEO_GEN_MODEL: str = os.getenv("VIDEO_GEN_MODEL", "agnes-video-v2.0")
    VIDEO_GEN_SIZE: str = os.getenv("VIDEO_GEN_SIZE", "1280x704")
    VIDEO_GEN_SECONDS: str = os.getenv("VIDEO_GEN_SECONDS", "5")
    VIDEO_GEN_POLL_INTERVAL: int = int(os.getenv("VIDEO_GEN_POLL_INTERVAL", "5"))
    VIDEO_GEN_POLL_TIMEOUT: int = int(os.getenv("VIDEO_GEN_POLL_TIMEOUT", "600"))

    # Reference image URL per role (set IMAGE_REF_{ROLE_ID} env var)
    @classmethod
    def get_image_ref(cls, role_id: str) -> str:
        return os.getenv(f"IMAGE_REF_{role_id.upper()}", "")

    # ── Dynamic Bot Token loader ──
    BOT_TOKENS: dict[str, str] = _load_bot_tokens()

    # ── Owner (Auto VIP) ──
    OWNER_ID: int = int(os.getenv("OWNER_ID", "5405770555"))

    # ── Admin ──
    ADMIN_IDS: list[int] = [
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
    ]

    # ── Database ──
    DB_PATH: str = os.getenv("DB_PATH", _default_db)

    # ── Conversation ──
    MAX_HISTORY_ROUNDS: int = int(os.getenv("MAX_HISTORY_ROUNDS", "100"))
    FREE_TRIAL_COUNT: int = int(os.getenv("FREE_TRIAL_COUNT", "20"))

    # ── Webhook ──
    WEBHOOK_URL: str | None = os.getenv("WEBHOOK_URL") or None

    # ── Payment (EPay) ──
    DONATION_API_TOKEN: str = os.getenv("DONATION_API_TOKEN", "")
    PAYMENT_MODE: str = os.getenv("PAYMENT_MODE", "test")  # test / production
    EPAY_PID: str = os.getenv("EPAY_PID", "")
    EPAY_KEY: str = os.getenv("EPAY_KEY", "")
    EPAY_URL: str = os.getenv("EPAY_URL", "https://pay.example.com/submit.php")
    EPAY_NOTIFY_URL: str = os.getenv("EPAY_NOTIFY_URL", "")

    # ── Rate Limit ──
    RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
    RATE_LIMIT_MAX: int = int(os.getenv("RATE_LIMIT_MAX", "15"))
    RATE_LIMIT_WINDOW: int = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

    # ── STT (Speech-to-Text) ──
    ENABLE_STT: bool = os.getenv("ENABLE_STT", "false").lower() == "true"
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "tiny")  # tiny / small / medium
    WHISPER_LANGUAGE: str | None = os.getenv("WHISPER_LANGUAGE") or "zh"  # zh / auto / en

    # ── Plugins ──
    ENABLED_PLUGINS: list[str] = [
        x.strip() for x in os.getenv("ENABLED_PLUGINS", "greetings,mood_plugin").split(",") if x.strip()
    ]

    # ── Channel Announcement ──
    ANNOUNCEMENT_CHANNEL: str | None = os.getenv("ANNOUNCEMENT_CHANNEL") or None  # @channel or -100xxx

    # ── Keepalive (Railway anti-sleep) ──
    ENABLE_KEEPALIVE: bool = os.getenv("ENABLE_KEEPALIVE", "true").lower() == "true"
    KEEPALIVE_INTERVAL: int = int(os.getenv("KEEPALIVE_INTERVAL", "240"))  # seconds, default 4 min

    # ── TTS ──
    TTS_ENABLED: bool = os.getenv("TTS_ENABLED", "true").lower() == "true"
    TTS_PROVIDER: str = os.getenv("TTS_PROVIDER", "azure")  # azure / edge
    TTS_TRIGGER_RATE: float = float(os.getenv("TTS_TRIGGER_RATE", "0.15"))
    TTS_MAX_CHARS: int = int(os.getenv("TTS_MAX_CHARS", "300"))

    # Azure TTS (500K chars/month free)
    AZURE_SPEECH_KEY: str = os.getenv("AZURE_SPEECH_KEY", "")
    AZURE_SPEECH_REGION: str = os.getenv("AZURE_SPEECH_REGION", "eastasia")

    # Edge TTS (free fallback)
    TTS_VOICE: str = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")

    # ── STT: Cloudflare Workers AI ──
    STT_PROVIDER: str = os.getenv("STT_PROVIDER", "cloudflare")
    CF_ACCOUNT_ID: str = os.getenv("CF_ACCOUNT_ID", "")
    CF_API_TOKEN: str = os.getenv("CF_API_TOKEN", "")

    # ── Group Chat ──
    ENABLE_GROUP_CHAT: bool = os.getenv("ENABLE_GROUP_CHAT", "true").lower() == "true"

    # ── Language ──
    DEFAULT_LANG: str = os.getenv("DEFAULT_LANG", "zh")

    @classmethod
    def get_active_bots(cls) -> dict[str, str]:
        """Return all roles that have a configured Bot Token."""
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
