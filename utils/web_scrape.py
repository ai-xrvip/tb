"""
Shared web scraping utilities for image/video generation.
"""
import re
import time
import urllib.parse
import httpx
from utils.logger import logger

_REF_CACHE = {}
_CACHE_TTL = 600
IMG_TAG_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)
MD_IMG_RE = re.compile(r'!\[.*?\]\(([^)]+)\)')


async def scrape_page_images(page_url: str) -> list:
    """Scrape image URLs from a page (telegra.ph etc). Results cached for 10 min."""
    now = time.time()
    if page_url in _REF_CACHE:
        ts, urls = _REF_CACHE[page_url]
        if now - ts < _CACHE_TTL and urls:
            return urls
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(page_url, headers={"User-Agent": "Bot/1.0"})
            if resp.status_code != 200:
                return []
            html = resp.text
    except Exception:
        return []

    img_urls = IMG_TAG_RE.findall(html)
    img_urls += MD_IMG_RE.findall(html)

    parsed = urllib.parse.urlparse(page_url)
    base = f"{parsed.scheme}://{parsed.hostname}"
    resolved = []
    for u in img_urls:
        if u.startswith("/"):
            u = base + u
        elif u.startswith("//"):
            u = "https:" + u
        elif u.startswith("data:"):
            continue
        elif not u.startswith("http"):
            u = urllib.parse.urljoin(page_url, u)
        resolved.append(u)
        if len(resolved) >= 30:
            break

    _REF_CACHE[page_url] = (now, resolved)
    logger.info(f"Scraped {len(resolved)} images from {page_url[:60]}...")
    return resolved


async def pick_random_ref(page_url: str):
    """Scrape page and return a random image URL as reference."""
    import random
    urls = await scrape_page_images(page_url)
    return random.choice(urls) if urls else None
