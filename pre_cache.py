"""Pre-cache: background gallery recommendation pool across 3 platforms, max 20."""
import asyncio
import random
import logging
from datetime import datetime, timezone
from typing import Optional
from config import config
from scraper import search_xchina, get_hot_keywords

logger = logging.getLogger(__name__)

_pre_cache = []
_pre_cache_lock = asyncio.Lock()
_pre_cache_task = None
_pre_skip_count = {}
_pre_user_last = {}
PRE_CACHE_SIZE = 20
FETCH_SLOTS = 15      # max slots from periodic fetches (12h)
POPULAR_SLOTS = 5      # max slots from popular galleries (2h)

_WEEK_SEC = 7 * 86400


def _is_recent(gallery: dict) -> bool:
    """Check if gallery's publish_date is within the last week."""
    pd = gallery.get("publish_date", "")
    if not pd:
        return False  # no date = skip for cache (avoid stale content)
    now = datetime.now(timezone.utc)
    try:
        # EH: 2026-07-05
        # XC: 2026.07.05
        # 4KHD: 2026年07月05日
        import re
        m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", pd)
        if m:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        else:
            m = re.match(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", pd)
            if m:
                dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
            else:
                return False
        return (now - dt).total_seconds() < _WEEK_SEC
    except Exception:
        return False


async def _fetch_latest_from(source: str, count: int = 6) -> list[dict]:
    """Fetch the latest galleries from one source (first page, hot keywords)."""
    results = []
    try:
        kws = await get_hot_keywords(top_n=5)
        kw = random.choice(kws) if kws else "cosplay"

        if source == "ehentai" and config.EH_MEMBER_ID:
            from scraper_eh import search_ehentai
            eh = await search_ehentai(kw, max_results=count, max_pages=1)
            results.extend(eh)
        elif source == "xchina":
            xc = await search_xchina(kw, max_results=count, max_pages=1)
            results.extend(xc)
        elif source == "4khd":
            from scraper import search_galleries
            hd = await search_galleries(kw, max_results=count, max_pages=1)
            results.extend(hd)
    except Exception as e:
        logger.warning(f"Pre-cache fetch {source}: {e}")

    # Only keep recent galleries
    recent = [g for g in results if _is_recent(g)]
    logger.info(f"Pre-cache {source}: {len(recent)}/{len(results)} recent")
    return recent


async def _refill_from_sources():
    """Refill cache from all 3 platforms (periodic, called every 12h)."""
    async with _pre_cache_lock:
        current_count = len(_pre_cache)
    if current_count >= FETCH_SLOTS:
        return

    sources = ["ehentai", "xchina", "4khd"]
    random.shuffle(sources)

    for source in sources:
        async with _pre_cache_lock:
            remaining = FETCH_SLOTS - len(_pre_cache)
        if remaining <= 0:
            break

        per_source = max(2, remaining // len(sources))
        galleries = await _fetch_latest_from(source, count=per_source)
        if galleries:
            async with _pre_cache_lock:
                cached_urls = {g.get("url", "") for g in _pre_cache}
                for g in galleries:
                    if g.get("url", "") in cached_urls:
                        continue
                    if len(_pre_cache) >= FETCH_SLOTS:
                        break
                    _pre_cache.append(g)
                    logger.info(f"Pre-cache: +{source} {g.get('title', '?')[:30]} ({len(_pre_cache)}/{PRE_CACHE_SIZE})")


async def _add_popular():
    """Every 2h: add popular galleries (≥2 clicks) from user searches, capped at POPULAR_SLOTS."""
    from scraper import gallery_clicks as gc, gallery_titles as gt
    if not gc:
        return
    sorted_clicks = sorted(gc.items(), key=lambda x: x[1], reverse=True)
    top_urls = [(u, c) for u, c in sorted_clicks if c >= 2]
    if not top_urls:
        return

    added = 0
    async with _pre_cache_lock:
        #