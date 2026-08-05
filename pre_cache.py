"""Pre-cache: background gallery recommendation pool across 3 platforms, max 20."""
import asyncio
import random
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from config import config
from scraper import get_hot_keywords, get_gallery_images, _fix_image_url, HEADERS
import httpx

logger = logging.getLogger(__name__)

_pre_cache = []
_pre_cache_lock = asyncio.Lock()
_pre_cache_task = None
_pre_skip_count = {}
_pre_user_last = {}
PRE_CACHE_SIZE = 20
DAILY_FRESH = 10     # newest galleries refilled every day at 12:00
DAILY_POPULAR = 10   # most-clicked galleries refilled every day at 12:00
_CN_TZ = timezone(timedelta(hours=8))  # Asia/Shanghai

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

async def _fetch_latest_4khd(count: int = DAILY_FRESH) -> list:
    """Fetch the newest galleries from the 4KHD homepage."""
    results = []
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=HEADERS) as client:
            r = await client.get(config.BASE_URL)
            r.raise_for_status()
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            for article in soup.select("article, .post, .entry"):
                title_el = article.find(["h1", "h2", "h3", "h4"])
                link_el = article.find("a", href=True)
                img_el = article.find("img")
                if not (title_el and link_el):
                    continue
                title = title_el.text.strip()
                link = link_el["href"]
                if not link.startswith("http"):
                    link = config.BASE_URL.rstrip("/") + link
                if "/content/" not in link:
                    continue
                cover = None
                if img_el:
                    cover = _fix_image_url(
                        img_el.get("src") or img_el.get("data-src") or img_el.get("data-original") or ""
                    )
                results.append({
                    "title": title, "url": link, "cover": cover,
                    "description": "", "source": "4khd", "publish_date": "",
                })
                if len(results) >= count:
                    break
    except Exception as e:
        logger.warning(f"Pre-cache latest fetch failed: {e}")
    logger.info(f"Pre-cache latest: {len(results)} galleries")
    return results


async def _collect_popular(count: int = DAILY_POPULAR) -> list:
    """Most-clicked galleries (memory) + most-favorited (DB) to survive restarts."""
    from scraper import gallery_clicks as gc, gallery_titles as gt
    out = []
    seen = set()
    if gc:
        sorted_clicks = sorted(gc.items(), key=lambda x: x[1], reverse=True)
        for url, _clicks in sorted_clicks:
            title = gt.get(url, "")
            if not title:
                continue
            out.append({
                "title": title, "url": url, "cover": None,
                "description": "", "source": "popular", "publish_date": "",
            })
            seen.add(url)
            if len(out) >= count:
                return out
    # Fallback: most-favorited galleries (persisted in SQLite, so it survives restarts)
    try:
        from database import _fetch_all
        rows = await _fetch_all(
            "SELECT url, title, COUNT(*) c FROM favorites GROUP BY url ORDER BY c DESC LIMIT ?",
            (count - len(out),),
        )
        for r in rows:
            if r["url"] in seen:
                continue
            out.append({
                "title": r["title"] or r["url"][:60], "url": r["url"], "cover": None,
                "description": "", "source": "popular", "publish_date": "",
            })
            seen.add(r["url"])
            if len(out) >= count:
                break
    except Exception as e:
        logger.debug(f"Pre-cache popular DB fallback failed: {e}")
    return out


async def _rebuild_daily_pool():
    """Rebuild the pool: 10 newest + 10 most-clicked galleries."""
    fresh = await _fetch_latest_4khd(DAILY_FRESH)
    popular = await _collect_popular(DAILY_POPULAR)
    async with _pre_cache_lock:
        _pre_cache.clear()
        for g in fresh + popular:
            _pre_cache.append(g)
            asyncio.create_task(_prefetch_gallery_detail(g))
    logger.info(f"Pre-cache: rebuilt daily pool ({len(fresh)} fresh + {len(popular)} popular = {len(_pre_cache)})")





async def _prefetch_gallery_detail(entry: dict):
    """Background: pre-fetch gallery images and cover_bytes for faster display."""
    url = entry.get("url", "")
    if not url:
        return
    try:
        gallery_data = await get_gallery_images(url)
        if gallery_data and gallery_data.get("images"):
            entry["images"] = gallery_data["images"]
        if gallery_data and gallery_data.get("cover_bytes"):
            entry["cover_bytes"] = gallery_data["cover_bytes"]
        if gallery_data and gallery_data.get("publish_date"):
            entry["publish_date"] = gallery_data["publish_date"]
    except Exception as e:
        logger.debug(f"Pre-cache prefetch failed for {url[:60]}: {e}")


async def _fill_pre_cache():
    """Fill once at startup, then rebuild the pool at 12:00 (Asia/Shanghai) daily."""
    await asyncio.sleep(60)
    try:
        await _rebuild_daily_pool()
    except Exception as e:
        logger.warning(f"Pre-cache initial fill error: {e}")
    while True:
        now = datetime.now(_CN_TZ)
        next_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
        if next_noon <= now:
            next_noon += timedelta(days=1)
        await asyncio.sleep((next_noon - now).total_seconds())
        try:
            await _rebuild_daily_pool()
        except Exception as e:
            logger.warning(f"Pre-cache daily rebuild error: {e}")


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
    """Immediately fetch one latest gallery to fill a skipped slot."""
    try:
        galleries = await _fetch_latest_4khd(1)
        if galleries:
            async with _pre_cache_lock:
                _pre_cache.append(galleries[0])
                asyncio.create_task(_prefetch_gallery_detail(galleries[0]))
                logger.info("Pre-cache: +replacement")
    except Exception as e:
        logger.debug(f"Pre-cache replacement failed: {e}")


async def _keep_alive():
    """Self-ping health endpoint every 5 min to prevent Railway Hobby sleep."""
    port = int(__import__('os').environ.get("PORT", 8000))
    health_url = f"http://127.0.0.1:{port}/"
    while True:
        await asyncio.sleep(300)
        try:
            async with httpx.AsyncClient(timeout=5) as cl:
                await cl.get(health_url)
        except Exception:
            pass

async def start_pre_cache():
    asyncio.create_task(_keep_alive())  # anti-sleep self-ping
    global _pre_cache_task
    if _pre_cache_task is not None:
        return
    _pre_cache_task = asyncio.create_task(_fill_pre_cache())
    logger.info("Pre-cache: daily 12:00 pool (10 fresh + 10 popular)")


async def stop_pre_cache():
    global _pre_cache_task
    if _pre_cache_task:
        _pre_cache_task.cancel()
        try:
            await _pre_cache_task
        except asyncio.CancelledError:
            pass
        _pre_cache_task = None
