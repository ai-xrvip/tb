"""
閰嶇疆绠＄悊 鈥斺€?澶?Bot Token + 澶?LLM 鎻愪緵鍟?+ 鏀粯 + 鎻掍欢绯荤粺

鍙傝€?
- chatgpt-on-wechat: 澶氬钩鍙?+ 鎻掍欢
- karfly bot: 澶氳瑷€ + 娴佸紡
- Openaibot: 瑙掕壊棰勮 + 澶氭ā鍨?
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
    """鍔ㄦ€佸姞杞芥墍鏈?*_BOT_TOKEN 鐜鍙橀噺"""
    tokens = {}
    pattern = re.compile(r'^(.+)_BOT_TOKEN$')
    for key, value in os.environ.items():
        m = pattern.match(key)
        if m and value:
            role_id = m.group(1).lower()
            tokens[role_id] = value
    return tokens


class Config:
    # 鈹€鈹€ LLM 鎻愪緵鍟嗛€夋嫨 鈹€鈹€
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "deepseek")  # deepseek / openai

    # 鈹€鈹€ DeepSeek 鈹€鈹€
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # 鈹€鈹€ OpenAI 鈹€鈹€
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str | None = os.getenv("OPENAI_BASE_URL") or None
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")

    # 鈹€鈹€ 娴佸紡杈撳嚭 鈹€鈹€
    ENABLE_STREAMING: bool = os.getenv("ENABLE_STREAMING", "true").lower() == "true"

    # 鈹€鈹€ 鍔ㄦ€佸姞杞芥墍鏈?Bot Token 鈹€鈹€
    BOT_TOKENS: dict[str, str] = _load_bot_tokens()

    # 鈹€鈹€ Admin 鈹€鈹€
    ADMIN_IDS: list[int] = [
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
    ]

    # 鈹€鈹€ 鏁版嵁搴?鈹€鈹€
    DB_PATH: str = os.getenv("DB_PATH", str(Path(__file__).parent / "bot.db"))

    # 鈹€鈹€ 瀵硅瘽 鈹€鈹€
    MAX_HISTORY_ROUNDS: int = int(os.getenv("MAX_HISTORY_ROUNDS", "100"))
    FREE_TRIAL_COUNT: int = int(os.getenv("FREE_TRIAL_COUNT", "20"))

    # 鈹€鈹€ Webhook 鈹€鈹€
    WEBHOOK_URL: str | None = os.getenv("WEBHOOK_URL") or None

    # 鈹€鈹€ 鏀粯锛堥鐣欙級 鈹€鈹€
    DONATION_API_TOKEN: str = os.getenv("DONATION_API_TOKEN", "")
    PAYMENT_MODE: str = os.getenv("PAYMENT_MODE", "test")  # test / production

    # 鈹€鈹€ 閫熺巼闄愬埗 鈹€鈹€
    RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
    RATE_LIMIT_MAX: int = int(os.getenv("RATE_LIMIT_MAX", "15"))
    RATE_LIMIT_WINDOW: int = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

    # 鈹€鈹€ 璇煶杞枃瀛?鈹€鈹€
    ENABLE_STT: bool = os.getenv("ENABLE_STT", "false").lower() == "true"
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "tiny")  # tiny / small / medium
    WHISPER_LANGUAGE: str | None = os.getenv("WHISPER_LANGUAGE") or "zh"  # zh / auto / en

    # 鈹€鈹€ 鎻掍欢 鈹€鈹€
    ENABLED_PLUGINS: list[str] = [
        x.strip() for x in os.getenv("ENABLED_PLUGINS", "greetings,mood_plugin").split(",") if x.strip()
    ]

    # 鈹€鈹€ 棰戦亾鍏憡 鈹€鈹€
    ANNOUNCEMENT_CHANNEL: str | None = os.getenv("ANNOUNCEMENT_CHANNEL") or None  # @棰戦亾鍚?鎴?-100xxx

    # 鈹€鈹€ 淇濇椿锛圧ailway 闃蹭紤鐪狅級 鈹€鈹€
    ENABLE_KEEPALIVE: bool = os.getenv("ENABLE_KEEPALIVE", "true").lower() == "true"
    KEEPALIVE_INTERVAL: int = int(os.getenv("KEEPALIVE_INTERVAL", "240"))  # 绉掞紝榛樿4鍒嗛挓

    # 鈹€鈹€ TTS 璇煶 鈹€鈹€
    # ?? TTS ?? ??
    TTS_ENABLED: bool = os.getenv("TTS_ENABLED", "true").lower() == "true"
    TTS_PROVIDER: str = os.getenv("TTS_PROVIDER", "azure")  # azure / edge
    TTS_TRIGGER_RATE: float = float(os.getenv("TTS_TRIGGER_RATE", "0.15"))
    TTS_MAX_CHARS: int = int(os.getenv("TTS_MAX_CHARS", "300"))

    # ?? Azure TTS (?? 50???/?, ????) ??
    AZURE_SPEECH_KEY: str = os.getenv("AZURE_SPEECH_KEY", "")
    AZURE_SPEECH_REGION: str = os.getenv("AZURE_SPEECH_REGION", "eastasia")

    # ?? Edge TTS (????) ??
    TTS_VOICE: str = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")

    # ── STT 语音转文字 (Cloudflare Workers AI, 免费 ~3000次/天) ──
    STT_PROVIDER: str = os.getenv("STT_PROVIDER", "cloudflare")
    CF_ACCOUNT_ID: str = os.getenv("CF_ACCOUNT_ID", "")
    CF_API_TOKEN: str = os.getenv("CF_API_TOKEN", "")




    # 鈹€鈹€ 缇よ亰 鈹€鈹€
    ENABLE_GROUP_CHAT: bool = os.getenv("ENABLE_GROUP_CHAT", "true").lower() == "true"

    # 鈹€鈹€ 璇█ 鈹€鈹€
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




