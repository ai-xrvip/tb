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
    MAX_SEARCH_RESULTS: int = int(os.getenv("MAX_SEARCH_RESULTS", "50"))
    MAX_PAGES_PER_POST: int = int(os.getenv("MAX_PAGES_PER_POST", "5"))
    MAX_IMAGES_PER_POST: int = int(os.getenv("MAX_IMAGES_PER_POST", "30"))
    
    # Site settings
    BASE_URL: str = "https://www.4khd.com"
    SEARCH_URL: str = "https://www.4khd.com/?s={keyword}"
    
    # HTTP
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "15"))
    
    # Webhook (leave empty for polling mode)
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
    
    USER_AGENT: str = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"
    )
    
    # Cache
    CACHE_TTL: int = int(os.getenv("CACHE_TTL", "300"))

    @classmethod
    def validate(cls) -> list[str]:
        errors = []
        if not cls.BOT_TOKEN:
            errors.append("BOT_TOKEN not set in .env")
        elif "your-" in cls.BOT_TOKEN.lower() or "placeholder" in cls.BOT_TOKEN.lower():
            errors.append("BOT_TOKEN looks like a placeholder")
        return errors

config = Config()
