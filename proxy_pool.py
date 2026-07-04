"""Proxy pool manager - auto-refresh from free proxy sources"""
import asyncio
import logging
import random
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

PROXY_SOURCES = [
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=protocolipport&format=text&timeout=5000",
]

REFRESH_INTERVAL = 600  # Refresh every 10 minutes
PROXY_TIMEOUT = 8.0
VALIDATE_URLS = ["https://www.4khd.com", "https://www.baidu.com"]

_proxy_pool: list[str] = []
_pool_lock = asyncio.Lock()
_last_refresh = 0.0
_refresh_task: Optional[asyncio.Task] = None


async def _fetch_proxies() -> list[str]:
    """Fetch proxy list from all sources."""
    all_proxies = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        for src in PROXY_SOURCES:
            try:
                r = await client.get(src)
                if r.status_code == 200:
                    lines = [l.strip() for l in r.text.splitlines() if l.strip().startswith("http")]
                    all_proxies.extend(lines)
                    logger.info(f"Fetched {len(lines)} proxies from source")
            except Exception as e:
                logger.warning(f"Failed to fetch proxies from {src[:50]}: {e}")
    return list(set(all_proxies))  # Deduplicate


async def _validate_proxy(proxy: str) -> bool:
    """Test if a proxy can reach target sites."""
    async with httpx.AsyncClient(
        proxy=proxy,
        timeout=httpx.Timeout(PROXY_TIMEOUT),
        follow_redirects=True,
    ) as client:
        for url in VALIDATE_URLS:
            try:
                r = await client.get(url)
                if r.status_code not in (200, 302):
                    return False
            except Exception:
                return False
    return True


async def _validate_pool(proxies: list[str], max_workers: int = 10) -> list[str]:
    """Validate proxies concurrently."""
    sem = asyncio.Semaphore(max_workers)

    async def validate_one(p: str) -> Optional[str]:
        async with sem:
            if await _validate_proxy(p):
                return p
        return None

    tasks = [validate_one(p) for p in proxies[:50]]  # Limit to 50 candidates
    results = await asyncio.gather(*tasks)
    valid = [r for r in results if r is not None]
    return valid


async def refresh_proxy_pool():
    """Refresh the proxy pool (called periodically)."""
    global _proxy_pool, _last_refresh
    async with _pool_lock:
        proxies = await _fetch_proxies()
        if proxies:
            logger.info(f"Validating {len(proxies)} proxies...")
            valid = await _validate_pool(proxies)
            if valid:
                _proxy_pool = valid
                _last_refresh = asyncio.get_event_loop().time()
                logger.info(f"Proxy pool refreshed: {len(valid)} working proxies")
            else:
                logger.warning("No working proxies found, keeping old pool")
        else:
            logger.warning("Failed to fetch any proxies")


def get_random_proxy() -> Optional[str]:
    """Get a random proxy from the pool (non-blocking)."""
    if _proxy_pool:
        return random.choice(_proxy_pool)
    return None


async def get_proxy_pool_size() -> int:
    """Get current pool size."""
    async with _pool_lock:
        return len(_proxy_pool)


async def start_proxy_pool():
    """Start background proxy pool refresh task."""
    global _refresh_task
    if _refresh_task is not None:
        return
    
    # Initial refresh
    await refresh_proxy_pool()
    
    async def _periodic_refresh():
        while True:
            await asyncio.sleep(REFRESH_INTERVAL)
            await refresh_proxy_pool()
    
    _refresh_task = asyncio.create_task(_periodic_refresh())
    logger.info("Proxy pool background refresh started")


async def stop_proxy_pool():
    """Stop the proxy pool refresh task."""
    global _refresh_task
    if _refresh_task:
        _refresh_task.cancel()
        try:
            await _refresh_task
        except asyncio.CancelledError:
            pass
        _refresh_task = None
