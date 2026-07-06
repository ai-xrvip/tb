"""4KHD.com scraper - search galleries and extract images (async version)"""
import re
import asyncio
import random
import logging
import urllib.parse
from collections import defaultdict
from io import BytesIO
from typing import Optional, Any
from datetime import datetime
import httpx
from curl_cffi import requests as curl_req
from bs4 import BeautifulSoup
from config import config
from proxy_pool import get_random_proxy

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": config.USER_AGENT}

_httpx_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()

# Cache with size limit: {key: (timestamp, data)}
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = asyncio.Lock()

# Popularity tracking (with TTL)
keyword_popularity: dict[str, int] = defaultdict(int)
gallery_clicks: dict[str, int] = defaultdict(int)
gallery_titles: dict[str, str] = {}
_click_lock = asyncio.Lock()
_click_last_cleanup = 0.0
_CLICK_TTL = 86400 * 7  # keep click data for 7 days


async def _get_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client (connection pooling)."""
    global _httpx_client
    async with _client_lock:
        if _httpx_client is None:
            limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
            _httpx_client = httpx.AsyncClient(
                headers=HEADERS,
                timeout=httpx.Timeout(config.REQUEST_TIMEOUT),
                verify=config.SSL_VERIFY,
                limits=limits,
            )
        return _httpx_client


async def _cleanup_click_tracking():
    """Periodically trim click tracking to prevent unbounded growth."""
    global _click_last_cleanup
    now = datetime.now().timestamp()
    if now - _click_last_cleanup < 3600:  # once per hour max
        return
    _click_last_cleanup = now
    async with _click_lock:
        max_entries = 5000
        if len(gallery_clicks) > max_entries:
            sorted_items = sorted(gallery_clicks.items(), key=lambda x: x[1], reverse=True)
            gallery_clicks.clear()
            gallery_clicks.update(sorted_items[:max_entries])
            for url in list(gallery_titles.keys()):
                if url not in gallery_clicks:
                    del gallery_titles[url]
        if len(keyword_popularity) > 500:
            sorted_kw = sorted(keyword_popularity.items(), key=lambda x: x[1], reverse=True)
            keyword_popularity.clear()
            keyword_popularity.update(sorted_kw[:500])


async def track_search(keyword: str):
    await _cleanup_click_tracking()
    async with _click_lock:
        keyword_popularity[keyword.lower()] += 1


async def track_click(url: str, title: str = ""):
    await _cleanup_click_tracking()
    async with _click_lock:
        gallery_clicks[url] += 1
        if title:
            gallery_titles[url] = title


async def get_hot_keywords(top_n: int = 5) -> list[str]:
    async with _click_lock:
        if not keyword_popularity:
            return ["cosplay", "黑丝", "自拍", "写真", "jk"]
        sorted_kw = sorted(keyword_popularity.items(), key=lambda x: x[1], reverse=True)
        return [kw for kw, _ in sorted_kw[:top_n]]


async def _cache_get(key: str) -> Optional[Any]:
    """Get from cache if not expired. Returns None if miss."""
    async with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, data = entry
        if datetime.now().timestamp() - ts < config.CACHE_TTL:
            return data
        del _cache[key]
        return None


async def _cache_set(key: str, data: Any):
    """Set cache entry, evicting oldest if over limit."""
    async with _cache_lock:
        if len(_cache) >= config.CACHE_MAX_ENTRIES:
            # Evict oldest 20% of entries
            sorted_keys = sorted(_cache.keys(), key=lambda k: _cache[k][0])
            for k in sorted_keys[:max(1, len(sorted_keys) // 5)]:
                del _cache[k]
        _cache[key] = (datetime.now().timestamp(), data)


async def _cache_clear_all():
    """Clear entire cache."""
    async with _cache_lock:
        _cache.clear()


def _fix_image_url(src: str) -> Optional[str]:
    if not src:
        return None
    if src.startswith("//"):
        src = "https:" + src
    elif not src.startswith("http"):
        src = config.BASE_URL.rstrip("/") + "/" + src.lstrip("/")
    src = re.sub(r"https?://i\d+\.wp\.com/", "https://", src)
    # Preserve ssl=1 param, strip known resize/optimization params
    src = re.sub(r"[?&](?:w|h|width|height|resize|fit|quality|strip)=\d+", "", src)
    # Clean up trailing ? or &
    src = re.sub(r"[?&]$", "", src)
    return src


# Proxy client cache: {proxy_url: (client, last_used_timestamp)}
_proxy_clients: dict[str, tuple[httpx.AsyncClient, float]] = {}
_proxy_client_lock = asyncio.Lock()
_PROXY_CLIENT_TTL = 300  # 5 min cache


async def _get_proxy_client(proxy_url: str) -> httpx.AsyncClient:
    """Get or create a cached proxy client."""
    async with _proxy_client_lock:
        now = asyncio.get_event_loop().time()
        # Clean expired clients
        expired = [p for p, (_, t) in _proxy_clients.items() if now - t > _PROXY_CLIENT_TTL]
        for p in expired:
            try:
                await _proxy_clients[p][0].aclose()
            except Exception:
                pass
            del _proxy_clients[p]
        
        if proxy_url in _proxy_clients:
            client, _ = _proxy_clients[proxy_url]
            _proxy_clients[proxy_url] = (client, now)
            return client
        
        client = httpx.AsyncClient(
            proxy=proxy_url,
            headers=HEADERS,
            timeout=httpx.Timeout(config.REQUEST_TIMEOUT),
            verify=config.SSL_VERIFY,
            limits=httpx.Limits(max_keepalive_connections=3, max_connections=5),
        )
        _proxy_clients[proxy_url] = (client, now)
        return client


async def _fetch(url: str, retries: int = 2) -> Optional[str]:
    """Async HTTP GET, returns response text."""
    proxy_url = get_random_proxy() if "4khd.com" in url else None
    for attempt in range(retries):
        try:
            if proxy_url:
                client = await _get_proxy_client(proxy_url)
            else:
                client = await _get_client()
            r = await client.get(url, follow_redirects=True)
            if r.status_code == 200:
                if proxy_url:
                    from proxy_pool import report_proxy_result
                    report_proxy_result(proxy_url, True)
                return r.text
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", "10"))
                logger.warning(f"Rate limited on {url[:60]}, waiting {wait}s")
                await asyncio.sleep(wait)
            else:
                logger.warning(f"HTTP {r.status_code} for {url[:60]} (attempt {attempt+1})")
                await asyncio.sleep(1)
        except httpx.TimeoutException:
            logger.warning(f"Timeout for {url[:60]} (attempt {attempt+1})")
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"Request error for {url[:60]} (attempt {attempt+1}): {e}")
            await asyncio.sleep(1)
    if proxy_url:
        from proxy_pool import report_proxy_result
        report_proxy_result(proxy_url, False)
    return None


async def _fetch_bytes(url: str, referer: str = "") -> Optional[tuple[BytesIO, str]]:
    """Async HTTP GET returning BytesIO + content-type. Respects referer."""
    client = await _get_client()
    headers = {}
    if referer:
        headers["Referer"] = referer
    for attempt in range(2):
        try:
            r = await client.get(url, headers=headers, follow_redirects=True)
            r.raise_for_status()
            ct = r.headers.get("Content-Type", "image/jpeg")
            if not ct.startswith("image/"):
                return None
            result = BytesIO(r.content)
            cropped = crop_watermark(result)
            return cropped, ct
        except Exception as e:
            if attempt == 1:
                logger.warning(f"Download failed {url[:60]}: {e}")
            await asyncio.sleep(1)
    return None


def crop_watermark(img_bytes: BytesIO) -> BytesIO:
    try:
        from PIL import Image
        img = Image.open(img_bytes)
        w, h = img.size
        cl = int(w * 0.015)
        ct = int(h * 0.015)
        cr = int(w * 0.985)
        cb = int(h * 0.985)
        cropped = img.crop((cl, ct, cr, cb))
        output = BytesIO()
        img_format = img.format or "JPEG"
        cropped.save(output, format=img_format, quality=95)
        output.seek(0)
        return output
    except Exception as e:
        logger.warning(f"Watermark crop failed: {e}")
        img_bytes.seek(0)
        return img_bytes


def _extract_date(html_text: str) -> str:
    """Extract publish date from HTML string."""
    m = re.search(r'<meta\s+property="article:published_time"\s+content="([^"]+)"', html_text)
    if m:
        dt = m.group(1)
        try:
            parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            return parsed.strftime("%Y年%m月%d日")
        except Exception:
            m2 = re.search(r"(\d{4}-\d{2}-\d{2})", dt)
            if m2:
                parts = m2.group(1).split("-")
                return f"{parts[0]}年{parts[1]}月{parts[2]}日"
    return ""


async def search_galleries(keyword: str, max_results: int = None, max_pages: int = 3) -> list[dict]:
    """Search galleries by keyword. Returns up to max_results entries."""
    if max_results is None:
        max_results = config.MAX_SEARCH_RESULTS

    await track_search(keyword)

    cache_key = f"search:{keyword.lower()}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return list(cached)[:max_results]

    search_url = config.SEARCH_URL.format(keyword=urllib.parse.quote(keyword))
    logger.info(f"Searching: {search_url}")

    text = await _fetch(search_url)
    if not text:
        return []

    soup = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, text, "html.parser")

    # Collect pagination links from the first page
    search_pages = [search_url]
    for a in soup.select(".page-links a.page-numbers, .pagination a.page-numbers"):
        href = a.get("href")
        if href:
            full = href if href.startswith("http") else config.BASE_URL.rstrip("/") + href
            if full not in search_pages:
                search_pages.append(full)

    search_pages = search_pages[:max_pages]
    logger.info(f"Will scrape {len(search_pages)} search pages")

    all_results = []
    seen_urls = set()

    for sp_idx, sp_url in enumerate(search_pages):
        if sp_idx > 0:
            sp_text = await _fetch(sp_url)
            if not sp_text:
                continue
            soup = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, sp_text, "html.parser")
            await asyncio.sleep(0.3)

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

            if "/content/" not in link or link in seen_urls:
                continue

            cover = None
            if img_el:
                cover = _fix_image_url(
                    img_el.get("src") or img_el.get("data-src") or img_el.get("data-original") or ""
                )

            excerpt_el = article.find(["p", ".excerpt", ".entry-summary", ".description"])
            description = excerpt_el.text.strip()[:200] if excerpt_el else ""

            all_results.append({
                "title": title,
                "url": link,
                "cover": cover,
                "description": description,
            })
            seen_urls.add(link)

            if len(all_results) >= max_results:
                await _cache_set(cache_key, all_results)
                logger.info(f"Found {len(all_results)} results for {keyword!r} (capped)")
                return all_results

    await _cache_set(cache_key, all_results)
    logger.info(f"Found {len(all_results)} results for {keyword!r}")
    return all_results


async def get_gallery_images(post_url: str, max_pages: int = None, max_images: int = None) -> dict:
    """Get gallery images from a post URL. Returns dict with title, images, cover, etc."""
    if max_pages is None:
        max_pages = config.MAX_PAGES_PER_POST
    if max_images is None:
        max_images = config.MAX_IMAGES_PER_POST

    cache_key = f"gallery:{post_url}:p{max_pages}:i{max_images}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return cached

    logger.info(f"Fetching gallery: {post_url}")
    text = await _fetch(post_url)
    if not text:
        return {"title": "", "images": [], "cover": None, "cover_bytes": None, "publish_date": ""}

    soup = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, text, "html.parser")
    title = soup.find("title")
    title_text = title.text.strip() if title else "Unknown"
    title_text = re.sub(r"\s*[-|]\s*4KHD\s*$", "", title_text).strip()

    publish_date = _extract_date(text)

    page_urls = [post_url]
    for a in soup.select(".page-links a.page-numbers, div.page-link-box ul.page-links li a"):
        href = a.get("href")
        if href:
            full = href if href.startswith("http") else urllib.parse.urljoin(post_url, href)
            if full not in page_urls:
                page_urls.append(full)
    page_urls = page_urls[:max_pages]

    all_images = []
    seen = set()
    cover_url = None

    for idx, page_url in enumerate(page_urls):
        if idx > 0:
            page_text = await _fetch(page_url)
            if not page_text:
                continue
            soup = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, page_text, "html.parser")

        content = None
        for sel in ["article", ".entry-content", ".post-body", ".single-content", "main"]:
            content = soup.select_one(sel)
            if content:
                break
        if not content:
            content = soup.find("body")
        if not content:
            continue

        for ns in content.find_all("noscript"):
            if ns.text:
                inner = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, ns.text, "html.parser")
                for img in inner.find_all("img"):
                    src = _fix_image_url(img.get("src"))
                    if src and "4khd.com" in src and src not in seen:
                        all_images.append(src)
                        seen.add(src)
                        if cover_url is None:
                            cover_url = src

        for img in content.find_all("img"):
            src = _fix_image_url(
                img.get("src") or img.get("data-src") or img.get("data-original") or ""
            )
            if src and "4khd.com" in src and src not in seen:
                all_images.append(src)
                seen.add(src)
                if cover_url is None:
                    cover_url = src

        if len(all_images) >= max_images:
            all_images = all_images[:max_images]
            break

        if idx < len(page_urls) - 1:
            await asyncio.sleep(0.3)

    cover_bytes = None
    if cover_url:
        result = await _fetch_bytes(cover_url, referer=post_url)
        if result:
            cover_bytes = result

    result = {
        "title": title_text,
        "images": all_images,
        "cover": cover_url,
        "cover_bytes": cover_bytes,
        "publish_date": publish_date,
    }
    await _cache_set(cache_key, result)
    return result


async def extract_download_link(post_url: str) -> str:
    """Extract m.4khd.com download link from post page."""
    text = await _fetch(post_url)
    if not text:
        return ""

    soup = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, text, "html.parser")
    content_area = soup.select_one("article, .entry-content, .post-body, .single-content, main") or soup

    for a in content_area.find_all("a", href=True):
        if "m.4khd.com" in a["href"] and "faq" not in a["href"]:
            logger.info(f"Download link: {a['href']}")
            return a["href"]

    m = re.search(r"https?://m\.4khd\.com/([a-zA-Z0-9]+)", text)
    if m and m.group(1) != "faq":
        logger.info(f"Download link (regex): {m.group(0)}")
        return m.group(0)

    return ""


async def download_image(url: str, referer: str = config.BASE_URL) -> Optional[tuple[BytesIO, str]]:
    """Download image and crop watermark. Returns (BytesIO, content_type) or None."""
    return await _fetch_bytes(url, referer=referer)


async def get_random_gallery() -> Optional[dict]:
    """Get a random gallery from 4KHD + XChina + EH in parallel, preferring recent."""
    import random as _random
    from datetime import datetime as _dt

    results = []
    seen_urls = set()
    now_ts = _dt.now().timestamp()
    recent_cutoff = now_ts - 3 * 86400

    def _is_recent(r):
        pd = r.get("publish_date", "")
        parsed = _parse_date_for_sort(pd)
        if not parsed:
            return True  # unknown date = include (don't filter out)
        try:
            dt = _dt.strptime(parsed, "%Y-%m-%d")
            return dt.timestamp() > recent_cutoff
        except Exception:
            return True  # unparseable = include

    # 1. Top clicked galleries
    top_urls = []
    async with _click_lock:
        if gallery_clicks:
            sorted_clicks = sorted(gallery_clicks.items(), key=lambda x: x[1], reverse=True)
            top_urls = [url for url, _ in sorted_clicks[:5]]
    if top_urls:
        _random.shuffle(top_urls)
        for url in top_urls:
            async with _click_lock:
                title = gallery_titles.get(url, "")
            keywords = title.split()[:3] if title else []
            kw = " ".join(keywords) if keywords else ""
            if kw:
                similar = await search_galleries(kw, max_results=3, max_pages=1)
                for r in similar:
                    if r["url"] not in seen_urls:
                        results.append(r)
                        seen_urls.add(r["url"])

    # 2. Hot keywords — parallel search across all sources
    hot_kws = await get_hot_keywords(top_n=3)
    tasks = []
    # 4KHD
    for kw in hot_kws:
        tasks.append(search_galleries(kw, max_results=8, max_pages=1))
    # XChina
    for kw in hot_kws[:2]:
        tasks.append(search_xchina(kw, max_results=8, max_pages=1))
    # EH
    if config.EH_MEMBER_ID:
        from scraper_eh import search_ehentai
        for kw in hot_kws[:1]:
            tasks.append(search_ehentai(kw, max_results=5, max_pages=1))
    # Parallel gather
    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    for g in gathered:
        if isinstance(g, list):
            for r in g:
                if r["url"] not in seen_urls:
                    results.append(r)
                    seen_urls.add(r["url"])

    # 3. Prefer recent, fallback to all
    recent = [r for r in results if _is_recent(r)]
    pool = recent if len(recent) >= 3 else results  # need at least 3 recent to use that pool

    if pool:
        weighted = []
        for r in pool:
            async with _click_lock:
                weight = gallery_clicks.get(r["url"], 0) + 1
            weighted.extend([r] * min(weight, 5))
        return _random.choice(weighted)

    # 4. Ultimate fallback — just 4KHD
    results = await search_galleries("cosplay", max_results=30, max_pages=1)
    if not results:
        results = await search_galleries("", max_results=30, max_pages=1)
    return _random.choice(results) if results else None

# ========== XChina.co ==========

"""4KHD.com scraper - search galleries and extract images (async version)"""
import re
import asyncio
import random
import logging
import urllib.parse
from collections import defaultdict
from io import BytesIO
from typing import Optional, Any
from datetime import datetime
import httpx
from curl_cffi import requests as curl_req
from bs4 import BeautifulSoup
from config import config
from proxy_pool import get_random_proxy

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": config.USER_AGENT}

_httpx_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()

# Cache with size limit: {key: (timestamp, data)}
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = asyncio.Lock()

# Popularity tracking (with TTL)
keyword_popularity: dict[str, int] = defaultdict(int)
gallery_clicks: dict[str, int] = defaultdict(int)
gallery_titles: dict[str, str] = {}
_click_lock = asyncio.Lock()
_click_last_cleanup = 0.0
_CLICK_TTL = 86400 * 7  # keep click data for 7 days


async def _get_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client (connection pooling)."""
    global _httpx_client
    async with _client_lock:
        if _httpx_client is None:
            limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
            _httpx_client = httpx.AsyncClient(
                headers=HEADERS,
                timeout=httpx.Timeout(config.REQUEST_TIMEOUT),
                verify=config.SSL_VERIFY,
                limits=limits,
            )
        return _httpx_client


async def _cleanup_click_tracking():
    """Periodically trim click tracking to prevent unbounded growth."""
    global _click_last_cleanup
    now = datetime.now().timestamp()
    if now - _click_last_cleanup < 3600:  # once per hour max
        return
    _click_last_cleanup = now
    async with _click_lock:
        max_entries = 5000
        if len(gallery_clicks) > max_entries:
            sorted_items = sorted(gallery_clicks.items(), key=lambda x: x[1], reverse=True)
            gallery_clicks.clear()
            gallery_clicks.update(sorted_items[:max_entries])
            for url in list(gallery_titles.keys()):
                if url not in gallery_clicks:
                    del gallery_titles[url]
        if len(keyword_popularity) > 500:
            sorted_kw = sorted(keyword_popularity.items(), key=lambda x: x[1], reverse=True)
            keyword_popularity.clear()
            keyword_popularity.update(sorted_kw[:500])


async def track_search(keyword: str):
    await _cleanup_click_tracking()
    async with _click_lock:
        keyword_popularity[keyword.lower()] += 1


async def track_click(url: str, title: str = ""):
    await _cleanup_click_tracking()
    async with _click_lock:
        gallery_clicks[url] += 1
        if title:
            gallery_titles[url] = title


async def get_hot_keywords(top_n: int = 5) -> list[str]:
    async with _click_lock:
        if not keyword_popularity:
            return ["cosplay", "黑丝", "自拍", "写真", "jk"]
        sorted_kw = sorted(keyword_popularity.items(), key=lambda x: x[1], reverse=True)
        return [kw for kw, _ in sorted_kw[:top_n]]


async def _cache_get(key: str) -> Optional[Any]:
    """Get from cache if not expired. Returns None if miss."""
    async with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, data = entry
        if datetime.now().timestamp() - ts < config.CACHE_TTL:
            return data
        del _cache[key]
        return None


async def _cache_set(key: str, data: Any):
    """Set cache entry, evicting oldest if over limit."""
    async with _cache_lock:
        if len(_cache) >= config.CACHE_MAX_ENTRIES:
            # Evict oldest 20% of entries
            sorted_keys = sorted(_cache.keys(), key=lambda k: _cache[k][0])
            for k in sorted_keys[:max(1, len(sorted_keys) // 5)]:
                del _cache[k]
        _cache[key] = (datetime.now().timestamp(), data)


async def _cache_clear_all():
    """Clear entire cache."""
    async with _cache_lock:
        _cache.clear()


def _fix_image_url(src: str) -> Optional[str]:
    if not src:
        return None
    if src.startswith("//"):
        src = "https:" + src
    elif not src.startswith("http"):
        src = config.BASE_URL.rstrip("/") + "/" + src.lstrip("/")
    src = re.sub(r"https?://i\d+\.wp\.com/", "https://", src)
    # Preserve ssl=1 param, strip known resize/optimization params
    src = re.sub(r"[?&](?:w|h|width|height|resize|fit|quality|strip)=\d+", "", src)
    # Clean up trailing ? or &
    src = re.sub(r"[?&]$", "", src)
    return src


# Proxy client cache: {proxy_url: (client, last_used_timestamp)}
_proxy_clients: dict[str, tuple[httpx.AsyncClient, float]] = {}
_proxy_client_lock = asyncio.Lock()
_PROXY_CLIENT_TTL = 300  # 5 min cache


async def _get_proxy_client(proxy_url: str) -> httpx.AsyncClient:
    """Get or create a cached proxy client."""
    async with _proxy_client_lock:
        now = asyncio.get_event_loop().time()
        # Clean expired clients
        expired = [p for p, (_, t) in _proxy_clients.items() if now - t > _PROXY_CLIENT_TTL]
        for p in expired:
            try:
                await _proxy_clients[p][0].aclose()
            except Exception:
                pass
            del _proxy_clients[p]
        
        if proxy_url in _proxy_clients:
            client, _ = _proxy_clients[proxy_url]
            _proxy_clients[proxy_url] = (client, now)
            return client
        
        client = httpx.AsyncClient(
            proxy=proxy_url,
            headers=HEADERS,
            timeout=httpx.Timeout(config.REQUEST_TIMEOUT),
            verify=config.SSL_VERIFY,
            limits=httpx.Limits(max_keepalive_connections=3, max_connections=5),
        )
        _proxy_clients[proxy_url] = (client, now)
        return client


async def _fetch(url: str, retries: int = 2) -> Optional[str]:
    """Async HTTP GET, returns response text."""
    proxy_url = get_random_proxy() if "4khd.com" in url else None
    for attempt in range(retries):
        try:
            if proxy_url:
                client = await _get_proxy_client(proxy_url)
            else:
                client = await _get_client()
            r = await client.get(url, follow_redirects=True)
            if r.status_code == 200:
                if proxy_url:
                    from proxy_pool import report_proxy_result
                    report_proxy_result(proxy_url, True)
                return r.text
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", "10"))
                logger.warning(f"Rate limited on {url[:60]}, waiting {wait}s")
                await asyncio.sleep(wait)
            else:
                logger.warning(f"HTTP {r.status_code} for {url[:60]} (attempt {attempt+1})")
                await asyncio.sleep(1)
        except httpx.TimeoutException:
            logger.warning(f"Timeout for {url[:60]} (attempt {attempt+1})")
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"Request error for {url[:60]} (attempt {attempt+1}): {e}")
            await asyncio.sleep(1)
    if proxy_url:
        from proxy_pool import report_proxy_result
        report_proxy_result(proxy_url, False)
    return None


async def _fetch_bytes(url: str, referer: str = "") -> Optional[tuple[BytesIO, str]]:
    """Async HTTP GET returning BytesIO + content-type. Respects referer."""
    client = await _get_client()
    headers = {}
    if referer:
        headers["Referer"] = referer
    for attempt in range(2):
        try:
            r = await client.get(url, headers=headers, follow_redirects=True)
            r.raise_for_status()
            ct = r.headers.get("Content-Type", "image/jpeg")
            if not ct.startswith("image/"):
                return None
            result = BytesIO(r.content)
            cropped = crop_watermark(result)
            return cropped, ct
        except Exception as e:
            if attempt == 1:
                logger.warning(f"Download failed {url[:60]}: {e}")
            await asyncio.sleep(1)
    return None


def crop_watermark(img_bytes: BytesIO) -> BytesIO:
    try:
        from PIL import Image
        img = Image.open(img_bytes)
        w, h = img.size
        cl = int(w * 0.015)
        ct = int(h * 0.015)
        cr = int(w * 0.985)
        cb = int(h * 0.985)
        cropped = img.crop((cl, ct, cr, cb))
        output = BytesIO()
        img_format = img.format or "JPEG"
        cropped.save(output, format=img_format, quality=95)
        output.seek(0)
        return output
    except Exception as e:
        logger.warning(f"Watermark crop failed: {e}")
        img_bytes.seek(0)
        return img_bytes


def _extract_date(html_text: str) -> str:
    """Extract publish date from HTML string."""
    m = re.search(r'<meta\s+property="article:published_time"\s+content="([^"]+)"', html_text)
    if m:
        dt = m.group(1)
        try:
            parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            return parsed.strftime("%Y年%m月%d日")
        except Exception:
            m2 = re.search(r"(\d{4}-\d{2}-\d{2})", dt)
            if m2:
                parts = m2.group(1).split("-")
                return f"{parts[0]}年{parts[1]}月{parts[2]}日"
    return ""


async def search_galleries(keyword: str, max_results: int = None, max_pages: int = 3) -> list[dict]:
    """Search galleries by keyword. Returns up to max_results entries."""
    if max_results is None:
        max_results = config.MAX_SEARCH_RESULTS

    await track_search(keyword)

    cache_key = f"search:{keyword.lower()}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return list(cached)[:max_results]

    search_url = config.SEARCH_URL.format(keyword=urllib.parse.quote(keyword))
    logger.info(f"Searching: {search_url}")

    text = await _fetch(search_url)
    if not text:
        return []

    soup = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, text, "html.parser")

    # Collect pagination links from the first page
    search_pages = [search_url]
    for a in soup.select(".page-links a.page-numbers, .pagination a.page-numbers"):
        href = a.get("href")
        if href:
            full = href if href.startswith("http") else config.BASE_URL.rstrip("/") + href
            if full not in search_pages:
                search_pages.append(full)

    search_pages = search_pages[:max_pages]
    logger.info(f"Will scrape {len(search_pages)} search pages")

    all_results = []
    seen_urls = set()

    for sp_idx, sp_url in enumerate(search_pages):
        if sp_idx > 0:
            sp_text = await _fetch(sp_url)
            if not sp_text:
                continue
            soup = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, sp_text, "html.parser")
            await asyncio.sleep(0.3)

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

            if "/content/" not in link or link in seen_urls:
                continue

            cover = None
            if img_el:
                cover = _fix_image_url(
                    img_el.get("src") or img_el.get("data-src") or img_el.get("data-original") or ""
                )

            excerpt_el = article.find(["p", ".excerpt", ".entry-summary", ".description"])
            description = excerpt_el.text.strip()[:200] if excerpt_el else ""

            all_results.append({
                "title": title,
                "url": link,
                "cover": cover,
                "description": description,
            })
            seen_urls.add(link)

            if len(all_results) >= max_results:
                await _cache_set(cache_key, all_results)
                logger.info(f"Found {len(all_results)} results for {keyword!r} (capped)")
                return all_results

    await _cache_set(cache_key, all_results)
    logger.info(f"Found {len(all_results)} results for {keyword!r}")
    return all_results


async def get_gallery_images(post_url: str, max_pages: int = None, max_images: int = None) -> dict:
    """Get gallery images from a post URL. Returns dict with title, images, cover, etc."""
    if max_pages is None:
        max_pages = config.MAX_PAGES_PER_POST
    if max_images is None:
        max_images = config.MAX_IMAGES_PER_POST

    cache_key = f"gallery:{post_url}:p{max_pages}:i{max_images}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return cached

    logger.info(f"Fetching gallery: {post_url}")
    text = await _fetch(post_url)
    if not text:
        return {"title": "", "images": [], "cover": None, "cover_bytes": None, "publish_date": ""}

    soup = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, text, "html.parser")
    title = soup.find("title")
    title_text = title.text.strip() if title else "Unknown"
    title_text = re.sub(r"\s*[-|]\s*4KHD\s*$", "", title_text).strip()

    publish_date = _extract_date(text)

    page_urls = [post_url]
    for a in soup.select(".page-links a.page-numbers, div.page-link-box ul.page-links li a"):
        href = a.get("href")
        if href:
            full = href if href.startswith("http") else urllib.parse.urljoin(post_url, href)
            if full not in page_urls:
                page_urls.append(full)
    page_urls = page_urls[:max_pages]

    all_images = []
    seen = set()
    cover_url = None

    for idx, page_url in enumerate(page_urls):
        if idx > 0:
            page_text = await _fetch(page_url)
            if not page_text:
                continue
            soup = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, page_text, "html.parser")

        content = None
        for sel in ["article", ".entry-content", ".post-body", ".single-content", "main"]:
            content = soup.select_one(sel)
            if content:
                break
        if not content:
            content = soup.find("body")
        if not content:
            continue

        for ns in content.find_all("noscript"):
            if ns.text:
                inner = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, ns.text, "html.parser")
                for img in inner.find_all("img"):
                    src = _fix_image_url(img.get("src"))
                    if src and "4khd.com" in src and src not in seen:
                        all_images.append(src)
                        seen.add(src)
                        if cover_url is None:
                            cover_url = src

        for img in content.find_all("img"):
            src = _fix_image_url(
                img.get("src") or img.get("data-src") or img.get("data-original") or ""
            )
            if src and "4khd.com" in src and src not in seen:
                all_images.append(src)
                seen.add(src)
                if cover_url is None:
                    cover_url = src

        if len(all_images) >= max_images:
            all_images = all_images[:max_images]
            break

        if idx < len(page_urls) - 1:
            await asyncio.sleep(0.3)

    cover_bytes = None
    if cover_url:
        result = await _fetch_bytes(cover_url, referer=post_url)
        if result:
            cover_bytes = result

    result = {
        "title": title_text,
        "images": all_images,
        "cover": cover_url,
        "cover_bytes": cover_bytes,
        "publish_date": publish_date,
    }
    await _cache_set(cache_key, result)
    return result


async def extract_download_link(post_url: str) -> str:
    """Extract m.4khd.com download link from post page."""
    text = await _fetch(post_url)
    if not text:
        return ""

    soup = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, text, "html.parser")
    content_area = soup.select_one("article, .entry-content, .post-body, .single-content, main") or soup

    for a in content_area.find_all("a", href=True):
        if "m.4khd.com" in a["href"] and "faq" not in a["href"]:
            logger.info(f"Download link: {a['href']}")
            return a["href"]

    m = re.search(r"https?://m\.4khd\.com/([a-zA-Z0-9]+)", text)
    if m and m.group(1) != "faq":
        logger.info(f"Download link (regex): {m.group(0)}")
        return m.group(0)

    return ""


async def download_image(url: str, referer: str = config.BASE_URL) -> Optional[tuple[BytesIO, str]]:
    """Download image and crop watermark. Returns (BytesIO, content_type) or None."""
    return await _fetch_bytes(url, referer=referer)


async def get_random_gallery() -> Optional[dict]:
    """Get a random gallery recommendation based on popular clicks and hot keywords."""
    results = []
    seen_urls = set()
    top_urls = []
    async with _click_lock:
        if gallery_clicks:
            sorted_clicks = sorted(gallery_clicks.items(), key=lambda x: x[1], reverse=True)
            top_urls = [url for url, _ in sorted_clicks[:5]]
    if top_urls:
        random.shuffle(top_urls)
        for url in top_urls:
            async with _click_lock:
                title = gallery_titles.get(url, "")
            keywords = title.split()[:3] if title else []
            kw = " ".join(keywords) if keywords else ""
            if kw:
                similar = await search_galleries(kw, max_results=3, max_pages=1)
                for r in similar:
                    if r["url"] not in seen_urls:
                        results.append(r)
                        seen_urls.add(r["url"])
    hot_kws = await get_hot_keywords(top_n=3)
    for kw in hot_kws:
        search_results = await search_galleries(kw, max_results=10, max_pages=1)
        for r in search_results:
            if r["url"] not in seen_urls:
                results.append(r)
                seen_urls.add(r["url"])
    if results:
        weighted = []
        for r in results:
            async with _click_lock:
                weight = gallery_clicks.get(r["url"], 0) + 1
            weighted.extend([r] * weight)
        return random.choice(weighted)
    results = await search_galleries("cosplay", max_results=30, max_pages=1)
    if not results:
        results = await search_galleries("", max_results=30, max_pages=1)
    return random.choice(results) if results else None


# ========== XChina.co ==========

XC_BASE = "https://xchina.co"
XC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


_xc_sem = asyncio.Semaphore(2)

async def _xc_fetch(url: str, retries: int = 2) -> str | None:
    """Fetch xchina.co page with curl_cffi to bypass Cloudflare."""
    async with _xc_sem:
        await asyncio.sleep(random.uniform(0.5, 1.5))
    for attempt in range(retries):
        try:
            r = await asyncio.to_thread(
                curl_req.get,
                url,
                headers=XC_HEADERS,
                impersonate="chrome124",
                timeout=15,
            )
            if r.status_code == 200:
                return r.text
            logger.warning(f"XC HTTP {r.status_code} for {url[:60]} (attempt {attempt+1})")
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"XC fetch error {url[:60]}: {e}")
            await asyncio.sleep(1)
    return None


def _extract_xc_gallery_id(url: str) -> str:
    """Extract gallery ID from xchina photo URL like /photo/id-6a4383664c43b.html"""
    m = re.search(r"/id-([a-f0-9]+)\.html", url)
    return m.group(1) if m else ""


def _parse_xc_count(count_str: str) -> int:
    """Parse '1128P' or '294P + 1V' into integer photo count."""
    m = re.search(r"(\d+)\s*P", count_str)
    return int(m.group(1)) if m else 0


def _extract_xc_date(text: str) -> str:
    """Extract date like 2026.07.03 or 2026-07-03 from text."""
    m = re.search(r"(20\d{2}[./-]\d{1,2}[./-]\d{1,2})", text)
    if m:
        return m.group(1).replace("-", ".").replace("/", ".")
    return ""


async def search_xchina(keyword: str, max_results: int = None, max_pages: int = 3) -> list[dict]:
    """Search xchina.co photo galleries."""
    if max_results is None:
        max_results = config.MAX_SEARCH_RESULTS

    cache_key = f"xc:{keyword.lower()}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return list(cached)[:max_results]

    if keyword.strip():
        search_url = f"{XC_BASE}/photos/keyword-{urllib.parse.quote(keyword)}.html"
    else:
        search_url = f"{XC_BASE}/photos.html"

    logger.info(f"XC search: {search_url}")
    all_results = []
    seen_urls = set()

    for page in range(1, max_pages + 1):
        url = search_url if page == 1 else f"{XC_BASE}/photos.html?page={page}"
        if page > 1 and keyword.strip():
            # Search results might not support ?page=, skip pagination for search
            break

        text = await _xc_fetch(url)
        if not text:
            continue

        soup = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, text, "html.parser")
        items = soup.select(".item.photo")
        if not items:
            break

        for item in items:
            # Title & URL
            title_a = item.select_one(".title a")
            if not title_a:
                continue
            title = title_a.text.strip()
            href = title_a.get("href", "")
            if not href.startswith("http"):
                href = XC_BASE + href

            if href in seen_urls:
                continue
            seen_urls.add(href)

            # Thumbnail from background-image style
            cover = None
            img_div = item.select_one(".img")
            if img_div:
                style = img_div.get("style", "")
                m = re.search(r"url\('([^']+)'\)", style)
                if m:
                    cover = m.group(1)

            # Photo count
            count_str = ""
            tags_div = item.select_one(".tags")
            if tags_div:
                first_div = tags_div.find("div")
                if first_div:
                    count_str = first_div.text.strip()

            # Extract date from item text
            item_text = item.get_text(" ", strip=True)
            publish_date = _extract_xc_date(item_text)

            # Extract author/studio from short text divs (exclude date, title, count)
            author = ""
            for div in item.select("div"):
                txt = div.text.strip()
                # Author is typically a short name (< 20 chars), not a number, not the title
                if txt and len(txt) < 20 and txt != title[:len(txt)] and not txt.startswith("20"):
                    # Skip count patterns like "155P"
                    if re.search(r"^\d+P", txt):
                        continue
                    # If we find a short text that looks like a name/studio (Chinese/English)
                    if re.search(r"[一-鿿]|[a-zA-Z]", txt):
                        author = txt
                        break

            all_results.append({
                "title": title,
                "url": href,
                "cover": cover,
                "count": count_str,
                "source": "xchina",
                "publish_date": publish_date,
                "author": author,
            })

            if len(all_results) >= max_results:
                await _cache_set(cache_key, all_results)
                logger.info(f"XC found {len(all_results)} results for {keyword!r}")
                return all_results

        if len(items) < 20:  # Fewer items = last page
            break
        await asyncio.sleep(0.3)

    await _cache_set(cache_key, all_results)
    logger.info(f"XC found {len(all_results)} results for {keyword!r}")
    return all_results


async def get_xchina_gallery(url: str, max_images: int = None) -> dict:
    """Get xchina gallery details and image list."""
    if max_images is None:
        max_images = config.MAX_IMAGES_PER_POST

    cache_key = f"xc_gallery:{url}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return cached

    gallery_id = _extract_xc_gallery_id(url)
    logger.info(f"XC gallery: {url} (id={gallery_id})")

    text = await _xc_fetch(url)
    result = {
        "title": "", "cover": None, "cover_bytes": None,
        "images": [], "count": 0, "source": "xchina", "url": url,
        "publish_date": "",
    }

    if not text:
        return result

    soup = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, text, "html.parser")

    # Title & date
    h1 = soup.find("h1")
    if h1:
        result["title"] = h1.text.strip()
    # Extract date from page text
    result["publish_date"] = _extract_xc_date(text)
    # Try to find author/studio
    result["author"] = ""
    for div in soup.select("div"):
        txt = div.text.strip()
        if txt and len(txt) < 20 and txt != result["title"][:len(txt)] and re.search(r"[一-鿿]|[a-zA-Z]", txt):
            if not txt.startswith("20") and not re.search(r"^\d+P", txt):
                result["author"] = txt
                break

    # Extract all image URLs from background-image styles
    import re as re_mod
    img_urls = re_mod.findall(r"https://img\.xchina\.io/photos/[^/]+/\d+_600x0\.webp", text)
    if not img_urls:
        img_urls = re_mod.findall(r"https://img\.xchina\.io/photos/[^/]+/\d+\.webp", text)
        if img_urls:
            img_urls = [u.replace(".webp", "_600x0.webp") if "_600x0" not in u else u for u in img_urls]
    images = []
    seen = set()
    for u in img_urls:
        if u not in seen:
            seen.add(u)
            images.append(u)

    # If no images found from HTML, generate from pattern
    if not images and gallery_id:
        # Try without leading zeros first (common format)
        for i in range(1, min(max_images + 1, 21)):
            images.append(f"https://img.xchina.io/photos/{gallery_id}/{i:05d}_600x0.webp")

    result["images"] = images[:max_images]

    # Photo count
    count_text = ""
    tags_div = soup.select_one(".tags, .photo-info")
    if tags_div:
        count_text = tags_div.text.strip()
    count = _parse_xc_count(count_text)
    if count == 0:
        count = len(images)
    result["count"] = count

    # Cover = first image
    if images:
        result["cover"] = images[0]
        # Download cover
        img_result = await _fetch_bytes(images[0], referer=url)
        if img_result:
            result["cover_bytes"] = img_result

    await _cache_set(cache_key, result)
    return result
