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

_WEEK_SEC = 5 * 86400


def _is_recent(gallery: dict) -> bool:
    """Check if gallery's publish_date is within 5 days.
    Returns True for unknown dates (search results have no dates).
    """
    pd = gallery.get("publish_date", "")
    if not pd:
        return True
    now = datetime.now(timezone.utc)
    try:
        import re
        m = re.match(r"(\d{4})\u5e74(\d{1,2})\u6708(\d{1,2})\u65e5", pd)
        if m:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        else:
            m = re.match(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", pd)
            if m:
                dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
            else:
                return True
        return (now - dt).total_seconds() < _WEEK_SEC
    except Exception:
        return True

async def _fetch_latest_from(source: str, count: int = 6) -> list:
    """Fetch the latest galleries from one source."""
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

    recent = [g for g in results if _is_recent(g)]
    logger.info(f"Pre-cache {source}: {len(recent)}/{len(results)} recent")
    return recent


async def _refill_from_sources():
    """Refill cache from all 3 platforms (periodic)."""
    async with _pre_cache_lock:
        current_count = len(_pre_cache)
    if current_count >= FETCH_SLOTS:
        return

    sources = ["4khd"]
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
    """Every 2h: add popular galleries (>=2 clicks), capped at POPULAR_SLOTS."""
    from scraper import gallery_clicks as gc, gallery_titles as gt
    if not gc:
        return
    sorted_clicks = sorted(gc.items(), key=lambda x: x[1], reverse=True)
    top_urls = [(u, c) for u, c in sorted_clicks if c >= 2]
    if not top_urls:
        return

    added = 0
    async with _pre_cache_lock:
        popular_in_cache = sum(1 for g in _pre_cache if g.get("source") == "popular")
        remaining = POPULAR_SLOTS - popular_in_cache
        if remaining <= 0:
            return

        cached_urls = {g.get("url", "") for g in _pre_cache}
        for url, count in top_urls:
            if url in cached_urls:
                continue
            title = gt.get(url, "")
            if title:
                _pre_cache.append({
                    "title": title, "url": url, "cover": None,
                    "source": "popular", "publish_date": "",
                })
                cached_urls.add(url)
                added += 1
                logger.info(f"Pre-cache: +popular {title[:30]}")
                if added >= remaining:
                    break


async def _fill_pre_cache():
    """Background loop: refill every 12h."""
    await asyncio.sleep(300)
    while True:
        try:
            await _refill_from_sources()
        except Exception as e:
            logger.warning(f"Pre-cache refill error: {e}")
        await asyncio.sleep(43200)


async def pop_pre_cached():
    """Get one gallery from the cache. Returns None if empty."""
    async with _pre_cache_lock:
        if _pre_cache:
            return _pre_cache.pop(0)
        return None


async def get_pre_cache_size():
    async with _pre_cache_lock:
        return len(_pre_cache)


async def track_pre_served(user_id, gallery_url):
    async with _pre_cache_lock:
        _pre_user_last[user_id] = gallery_url


async def track_pre_clicked(user_id):
    async with _pre_cache_lock:
        _pre_user_last.pop(user_id, None)


async def track_pre_skipped(user_id):
    """Track skip: 3 skips -> remove gallery + trigger refill."""
    async with _pre_cache_lock:
        prev_url = _pre_user_last.pop(user_id, None)
        if prev_url:
            _pre_skip_count[prev_url] = _pre_skip_count.get(prev_url, 0) + 1
            if _pre_skip_count[prev_url] >= 3:
                for i, g in enumerate(_pre_cache):
                    if g.get("url") == prev_url:
                        _pre_cache.pop(i)
                        logger.info(f"Pre-cache: removed {prev_url[:60]} (3+ skips)")
                        break
                _pre_skip_count.pop(prev_url, None)
                asyncio.create_task(_fetch_replacement())


async def _fetch_replacement():
    """Immediately fetch one gallery from a random source to fill the gap."""
    source = "4khd"
    galleries = await _fetch_latest_from(source, count=3)
    if galleries:
        async with _pre_cache_lock:
            cached_urls = {g.get("url", "") for g in _pre_cache}
            for g in galleries:
                if g.get("url", "") in cached_urls:
                    continue
                _pre_cache.append(g)
                logger.info(f"Pre-cache: +replace {source}")
                return


async def start_pre_cache():
    global _pre_cache_task
    if _pre_cache_task is not None:
        return
    _pre_cache_task = asyncio.create_task(_fill_pre_cache())

    async def _popular_loop():
        await asyncio.sleep(600)
        while True:
            try:
                await _add_popular()
            except Exception as e:
                logger.warning(f"Popular loop error: {e}")
            await asyncio.sleep(7200)

    asyncio.create_task(_popular_loop())
    logger.info("Pre-cache: 20 slots (15 fetch + 5 popular, 12h/2h)")


async def stop_pre_cache():
    global _pre_cache_task
    if _pre_cache_task:
        _pre_cache_task.cancel()
        try:
            await _pre_cache_task
        except asyncio.CancelledError:
            pass
        _pre_cache_task = None
