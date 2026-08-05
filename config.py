"""Configuration for 4KHD Search Bot"""
import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv()

class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    # Search settings
    MAX_SEARCH_RESULTS: int = int(os.getenv("MAX_SEARCH_RESULTS", "30"))
    MAX_PAGES_PER_POST: int = int(os.getenv("MAX_PAGES_PER_POST", "3"))
    MAX_IMAGES_PER_POST: int = int(os.getenv("MAX_IMAGES_PER_POST", "10"))

    # Site settings
    BASE_URL: str = "https://www.4khd.com"
    SEARCH_URL: str = "https://www.4khd.com/?s={keyword}"

    # HTTP 鈥?per-source timeouts (seconds)
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "8"))
    SEARCH_TIMEOUT_4KHD: float = float(os.getenv("SEARCH_TIMEOUT_4KHD", "8.0"))
    SEARCH_TIMEOUT_XC: float = float(os.getenv("SEARCH_TIMEOUT_XC", "6.0"))
    SEARCH_TIMEOUT_EH: float = float(os.getenv("SEARCH_TIMEOUT_EH", "12.0"))

    # Proxy pool (set PROXY_ENABLED=false to skip free proxies)
    PROXY_ENABLED: bool = os.getenv("PROXY_ENABLED", "true").lower() in ("true", "1", "yes")

    # Webhook (leave empty for polling mode)
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
    WEBHOOK_PORT: int = int(os.getenv("PORT", "8000"))

    USER_AGENT: str = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"
    )

    # Cache
    CACHE_TTL: int = int(os.getenv("CACHE_TTL", "300"))
    CACHE_MAX_ENTRIES: int = int(os.getenv("CACHE_MAX_ENTRIES", "500"))

    # SSL verification (disable for sites with problematic certs)
    SSL_VERIFY: bool = os.getenv("SSL_VERIFY", "true").lower() in ("true", "1", "yes")

    # Proxy pool: free-proxy rotation for 4khd.com. Off by default - direct
    # connection is stable and faster. Enable only if the datacenter IP gets
    # blocked (symptom: mass 403/429 on direct fetches).
    ENABLE_PROXY_POOL: bool = os.getenv("ENABLE_PROXY_POOL", "false").lower() in ("true", "1", "yes")

    # Rate limiting
    MAX_SEARCHES_PER_MINUTE: int = int(os.getenv("MAX_SEARCHES_PER_MINUTE", "10"))

    # Free tier: daily search quota for non-VIP users (0 = unlimited)
    FREE_DAILY_SEARCHES: int = int(os.getenv("FREE_DAILY_SEARCHES", "10"))
    # Free trial days granted on first /start (0 = disabled)
    FREE_TRIAL_DAYS: int = int(os.getenv("FREE_TRIAL_DAYS", "0"))
    # Free tier: images visible per gallery for non-VIP users
    FREE_PREVIEW_IMAGES: int = int(os.getenv("FREE_PREVIEW_IMAGES", "5"))
    # Scale/marketing line shown on the start screen (marketing copy, can be tuned)
    SCALE_TEXT: str = os.getenv("SCALE_TEXT", "📚 已收录 90万+ 套图集 · 3800万+ 张高清图片 · 每日更新")
    # VIP pricing line shown in paywall copy (e.g. "?? ?29.9 / ?? ?69 / ?? ?499")
    VIP_PRICE_TEXT: str = os.getenv("VIP_PRICE_TEXT", "")

    # E-Hentai cookies
    EH_MEMBER_ID: str = os.getenv("EH_MEMBER_ID", "")
    EH_PASS_HASH: str = os.getenv("EH_PASS_HASH", "")
    EH_SK: str = os.getenv("EH_SK", "")
    EH_EVENT: str = os.getenv("EH_EVENT", "")
    EH_IQ: str = os.getenv("EH_IQ", "")

    # Admin IDs (comma-separated)
    ADMIN_IDS: set[int] = {
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
    }

    # Database path
    DB_PATH: str = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "bot.db"))

    # Web admin dashboard token
    ADMIN_WEB_TOKEN: str = os.getenv("ADMIN_WEB_TOKEN", "")

    @classmethod
    def validate(cls) -> list[str]:
        errors = []
        if not cls.BOT_TOKEN:
            errors.append("BOT_TOKEN not set in .env")
        elif "your-" in cls.BOT_TOKEN.lower() or "placeholder" in cls.BOT_TOKEN.lower():
            errors.append("BOT_TOKEN looks like a placeholder")
        if not cls.ADMIN_IDS:
            errors.append("ADMIN_IDS is empty")
        return errors

config = Config()
