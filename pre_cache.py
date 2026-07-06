"""Pre-cache: background gallery recommendation pool (EH + XC, max 20)."""
import asyncio
import random
import logging
from typing import Optional
from config import config
from scraper import search_xchina, get_hot_keywords, keyword_popularity, gallery_clicks, gallery_titles

logger = logging.getLogger(__name__)

_pre_cache = []
_pre_cache_lock = asyncio.Lock()
_pre_cache_task = None
_pre_skip_count = {}
_pre_user_last = {}
PRE_CACHE_SIZE = 20


async def _refill_cache():
    async with _pre_cache_lock:
        if len(_pre_cache) >= PRE_CACHE_SIZE:
            return
    try:
        from scraper import keyword_popularity as kp
        kws = await get_hot_keywords(top_n=5) if kp else ["cosplay"]
        kw = random.choice(kws)
        gallery = None
        if config.EH_MEMBER_ID:
            try:
                from scraper_eh import search_ehentai
                eh = await search_ehentai(kw, max_results=5, max_pages=1)
                if eh: gallery = random.choice(eh)
            except Exception: pass
        if not gallery:
            try:
                xc = await search_xchina(kw, max_results=5, max_pages=1)
                if xc: gallery = random.choice(xc)
            except Exception: pass
        if gallery:
            async with _pre_cache_lock:
                if len(_pre_cache) < PRE_CACHE_SIZE:
                    _pre_cache.append(gallery)
                    logger.info(f"Pre-cache: +1 ({len(_pre_cache)}/{PRE_CACHE_SIZE})")
    except Exception as e:
        logger.warning(f"Pre-cache refill: {e}")


async def _fill_pre_cache():
    while True:
        await asyncio.sleep(14400)
        await _refill_cache()


async def _add_popular():
    from scraper import gallery_clicks as gc, gallery_titles as gt
    sorted_clicks = sorted(gc.items(), key=lambda x: x[1], reverse=True) if gc else []
    top_urls = [(u, c) for u, c in sorted_clicks[:10] if c >= 2]
    async with _pre_cache_lock:
        cached = {g.get("url", "") for g in _pre_cache}
        for url, count in top_urls:
            if url in cached: continue
            title = gt.get(url, "")
            if title:
                _pre_cache.append({"title": title, "url": url, "cover": None, "source": "popular", "publish_date": ""})
                cached.add(url)
                logger.info(f"Pre-cache: +popular {title[:30]}")
                if len(_pre_cache) >= PRE_CACHE_SIZE: break


async def pop_pre_cached():
    async with _pre_cache_lock:
        return _pre_cache.pop(0) if _pre_cache else None


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
                del _pre_skip_count[prev_url]
                asyncio.create_task(_refill_cache())


async def start_pre_cache():
    global _pre_cache_task
    if _pre_cache_task is not None: return
    _pre_cache_task = asyncio.create_task(_fill_pre_cache())
    async def _popular_loop():
        await asyncio.sleep(600)
        while True:
            await _add_popular()
            await asyncio.sleep(7200)
    asyncio.create_task(_popular_loop())
    logger.info("Pre-cache started (20 slots, 4h refill)")


async def stop_pre_cache():
    global _pre_cache_task
    if _pre_cache_task:
        _pre_cache_task.cancel()
        try: await _pre_cache_task
        except asyncio.CancelledError: pass
        _pre_cache_task = None
