"""Proxy pool manager - auto-refresh from free proxy sources"""
import asyncio
import logging
import random
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

PROXY_SOURCES = [
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=protocolipport&format=text&timeout=5000",
    "https://www.proxy-list.download/api/v1/get?type=http",
]

REFRESH_INTERVAL = 600
PROXY_TIMEOUT = 5.0
VALIDATE_URLS = ["https://www.4khd.com"]

_proxy_pool: list[str] = []
_pool_lock = asyncio.Lock()
_last_refresh = 0.0
_refresh_task: Optional[asyncio.Task] = None
_proxy_stats: dict[str, int] = {}
_total_requests = 0
_total_failures = 0


async def _fetch_proxies() -> list[str]:
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
                logger.warning(f"Failed to fetch proxies: {e}")
    return list(set(all_proxies))


async def _validate_proxy(proxy: str) -> bool:
    async with httpx.AsyncClient(
        proxy=proxy, timeout=httpx.Timeout(PROXY_TIMEOUT), follow_redirects=True,
    ) as client:
        for url in VALIDATE_URLS:
            try:
                r = await client.get(url)
                if r.status_code not in (200, 302):
                    return False
            except Exception:
                return False
    return True


async def _validate_pool(proxies: list[str], max_workers: int = 20) -> list[str]:
    sem = asyncio.Semaphore(max_workers)

    async def validate_one(p: str) -> Optional[str]:
        async with sem:
            if await _validate_proxy(p):
                return p
        return None

    tasks = [validate_one(p) for p in proxies]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


async def _do_refresh() -> int:
    global _proxy_pool, _last_refresh
    proxies = await _fetch_proxies()
    if proxies:
        logger.info(f"Validating {len(proxies)} proxies...")
        valid = await _validate_pool(proxies)
        if valid:
            _proxy_pool = valid
            _last_refresh = time.time()
            logger.info(f"Proxy pool refreshed: {len(valid)} working proxies")
        else:
            logger.warning("No working proxies found, keeping old pool")
    else:
        logger.warning("Failed to fetch any proxies")
    return len(_proxy_pool)


async def refresh_proxy_pool():
    async with _pool_lock:
        await _do_refresh()


def get_random_proxy() -> Optional[str]:
    if _proxy_pool:
        return random.choice(_proxy_pool)
    return None


def report_proxy_result(proxy: str, success: bool):
    global _total_requests, _total_failures
    _total_requests += 1
    if success:
        _proxy_stats[proxy] = _proxy_stats.get(proxy, 0) + 1
    else:
        _total_failures += 1


async def get_pool_stats() -> dict:
    async with _pool_lock:
        now = time.time()
        age = now - _last_refresh if _last_refresh else 0
        return {
            "pool_size": len(_proxy_pool),
            "last_refresh_secs_ago": int(age),
            "total_requests": _total_requests,
            "total_failures": _total_failures,
            "top_proxies": sorted(_proxy_stats.items(), key=lambda x: x[1], reverse=True)[:5],
        }


async def get_proxy_pool_size() -> int:
    async with _pool_lock:
        return len(_proxy_pool)


async def health_check() -> dict:
    async with _pool_lock:
        if not _proxy_pool:
            logger.warning("Health check: pool empty, forcing refresh")
            return {"pool_size": 0, "sample_alive": 0, "sample_total": 0, "healthy": False}

        sample = random.sample(_proxy_pool, min(5, len(_proxy_pool)))
        sem = asyncio.Semaphore(5)

        async def check_one(p):
            async with sem:
                return await _validate_proxy(p)

        results = await asyncio.gather(*[check_one(p) for p in sample])
        alive = sum(1 for r in results if r)

        logger.info(f"Health check: {alive}/{len(sample)} sample proxies alive, pool={len(_proxy_pool)}")
        return {
            "pool_size": len(_proxy_pool),
            "sample_alive": alive,
            "sample_total": len(sample),
            "healthy": alive >= len(sample) * 0.3,
        }


async def start_proxy_pool():
    global _refresh_task
    if _refresh_task is not None:
        return

    await refresh_proxy_pool()

    async def _periodic_refresh():
        await asyncio.sleep(REFRESH_INTERVAL)
        while True:
            await _do_refresh()
            stats = await get_pool_stats()
            hc = await health_check()
            logger.info(
                f"Proxy status: {stats['pool_size']} proxies, "
                f"{stats['total_requests']} reqs/{stats['total_failures']} fails, "
                f"health={hc['sample_alive']}/{hc['sample_total']}"
            )
            await asyncio.sleep(REFRESH_INTERVAL)

    _refresh_task = asyncio.create_task(_periodic_refresh())
    logger.info("Proxy pool started (health check every 10min)")


async def stop_proxy_pool():
    global _refresh_task
    if _refresh_task:
        _refresh_task.cancel()
        try:
            await _refresh_task
        except asyncio.CancelledError:
            pass
        _refresh_task = None
