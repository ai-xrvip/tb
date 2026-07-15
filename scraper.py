"""4KHD.com scraper - search galleries and extract images (async version)"""
import re
import asyncio
import hashlib
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
        # Filter out non-search keywords (card codes, single chars, etc.)
        result = []
        for kw, cnt in sorted_kw:
            kw = kw.strip()
            # Skip card codes (start with Y-, J-, N-, S-)
            if re.match(r'^[YJNS]-[A-Z0-9]{10,}

    # Live fallback: search 4KHD with hot keywords
    hot_kws = await get_hot_keywords(top_n=5)
    logger.info("Random: hot_kws=%s", hot_kws)
    kw = _random.choice(hot_kws) if hot_kws else "cosplay"
    logger.info("Random: searching 4KHD kw=%s", kw)
    candidates = []

    # 4KHD
    try:
        hd = await search_galleries(kw, max_results=10, max_pages=1)
        logger.info("Random: 4KHD returned %d results", len(hd))
        candidates.extend(hd)
    except Exception as e:
        logger.warning("Random: 4KHD search error: %s", e)

    if candidates:
        picked = _random.choice(candidates)
        logger.info("Random: picked %s", picked.get('url', '?')[:60])
        return picked
    logger.warning("Random: no candidates found, returning None")
    return None# ========== XChina.co ==========

XC_BASE = "https://xchina.co"
XC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


_xc_sem = asyncio.Semaphore(2)

async def _xc_fetch(url: str, retries: int = 2) -> str | None:
    """Fetch xchina.co page with curl_cffi to bypass Cloudflare.
    Falls back to httpx+standard headers if curl_cffi fails."""
    async with _xc_sem:
        await asyncio.sleep(random.uniform(0.5, 1.5))
    # Try curl_cffi first (Cloudflare bypass)
    for attempt in range(retries):
        try:
            r = await asyncio.to_thread(
                curl_req.get,
                url,
                headers=XC_HEADERS,
                impersonate="chrome131",
                timeout=15,
            )
            if r.status_code == 200:
                return r.text
            logger.warning(f"XC curl_cffi HTTP {r.status_code} for {url[:60]} (attempt {attempt+1})")
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"XC curl_cffi error {url[:60]}: {e}")
            await asyncio.sleep(1)
    # Fallback to httpx (works when Cloudflare is relaxed or IP is trusted)
    logger.info("XC curl_cffi failed, falling back to httpx for %s", url[:60])
    try:
        async with httpx.AsyncClient(
            headers=XC_HEADERS,
            timeout=httpx.Timeout(15),
            follow_redirects=True,
        ) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return r.text
            logger.warning(f"XC httpx fallback HTTP {r.status_code} for {url[:60]}")
    except Exception as e:
        logger.warning(f"XC httpx fallback error {url[:60]}: {e}")
    return None


async def _xc_fetch_bytes(url: str, referer: str = "") -> Optional[tuple[BytesIO, str]]:
    """Download an XChina image with curl_cffi to bypass Cloudflare."""
    headers = dict(XC_HEADERS)
    if referer:
        headers["Referer"] = referer
    for attempt in range(2):
        try:
            r = await asyncio.to_thread(
                curl_req.get,
                url,
                headers=headers,
                impersonate="chrome131",
                timeout=20,
            )
            if r.status_code == 200 and len(r.content) > 500:
                ct = r.headers.get("Content-Type", "image/jpeg")
                if not ct.startswith("image/"):
                    return None
                result = BytesIO(r.content)
                cropped = crop_watermark(result)
                return cropped, ct
            logger.warning(f"XC img HTTP {r.status_code} size={len(r.content)} for {url[:60]}")
        except Exception as e:
            if attempt == 1:
                logger.warning(f"XC img download failed {url[:60]}: {e}")
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
            # XChina keyword-search pages don't support ?page= — skip pagination
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
                # Author/studio signals: 2-15 chars, contains CJK or Latin, not a date/count/title fragment
                if not txt or len(txt) < 2 or len(txt) > 15:
                    continue
                if txt == title[:len(txt)]:
                    continue
                if txt.startswith("20") and re.search(r"^20\d{2}", txt):
                    continue
                if re.search(r"^\d+\s*P", txt):
                    continue
                # Garbage noise: single English letters, "US", junk tokens
                if re.search(r"^[a-zA-Z]{1,2}$", txt):
                    continue
                # Valid: contains CJK, or is a recognizable Latin name (2+ words or starts with uppercase)
                if re.search(r"[一-鿿]", txt):
                    author = txt
                    break
                if re.search(r"^[A-Z][a-z]", txt) and not re.search(r"^\d", txt):
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
        if not txt or len(txt) < 2 or len(txt) > 15:
            continue
        if txt == result["title"][:len(txt)]:
            continue
        if txt.startswith("20") and re.search(r"^20\d{2}", txt):
            continue
        if re.search(r"^\d+\s*P", txt):
            continue
        if re.search(r"^[a-zA-Z]{1,2}$", txt):
            continue
        if re.search(r"[一-鿿]", txt):
            result["author"] = txt
            break
        if re.search(r"^[A-Z][a-z]", txt) and not re.search(r"^\d", txt):
            result["author"] = txt
            break

    # Extract all image URLs from background-image styles
    img_urls = re.findall(r"https://img\.xchina\.io/photos/[^/]+/\d+_600x0\.webp", text)
    if not img_urls:
        img_urls = re.findall(r"https://img\.xchina\.io/photos/[^/]+/\d+\.webp", text)
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
        # Download cover via curl_cffi to bypass Cloudflare
        img_result = await _xc_fetch_bytes(images[0], referer=url)
        if img_result:
            result["cover_bytes"] = img_result

    await _cache_set(cache_key, result)
    return result
, kw, re.I):
                continue
            # Skip single char or very short
            if len(kw) < 2:
                continue
            result.append(kw)
            if len(result) >= top_n:
                break
        return result if result else ["cosplay", "黑丝", "自拍", "写真", "jk"]

    # Live fallback: search 4KHD with hot keywords
    hot_kws = await get_hot_keywords(top_n=5)
    logger.info("Random: hot_kws=%s", hot_kws)
    kw = _random.choice(hot_kws) if hot_kws else "cosplay"
    logger.info("Random: searching 4KHD kw=%s", kw)
    candidates = []

    # 4KHD
    try:
        hd = await search_galleries(kw, max_results=10, max_pages=1)
        logger.info("Random: 4KHD returned %d results", len(hd))
        candidates.extend(hd)
    except Exception as e:
        logger.warning("Random: 4KHD search error: %s", e)

    if candidates:
        picked = _random.choice(candidates)
        logger.info("Random: picked %s", picked.get('url', '?')[:60])
        return picked
    logger.warning("Random: no candidates found, returning None")
    return None# ========== XChina.co ==========

XC_BASE = "https://xchina.co"
XC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


_xc_sem = asyncio.Semaphore(2)

async def _xc_fetch(url: str, retries: int = 2) -> str | None:
    """Fetch xchina.co page with curl_cffi to bypass Cloudflare.
    Falls back to httpx+standard headers if curl_cffi fails."""
    async with _xc_sem:
        await asyncio.sleep(random.uniform(0.5, 1.5))
    # Try curl_cffi first (Cloudflare bypass)
    for attempt in range(retries):
        try:
            r = await asyncio.to_thread(
                curl_req.get,
                url,
                headers=XC_HEADERS,
                impersonate="chrome131",
                timeout=15,
            )
            if r.status_code == 200:
                return r.text
            logger.warning(f"XC curl_cffi HTTP {r.status_code} for {url[:60]} (attempt {attempt+1})")
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"XC curl_cffi error {url[:60]}: {e}")
            await asyncio.sleep(1)
    # Fallback to httpx (works when Cloudflare is relaxed or IP is trusted)
    logger.info("XC curl_cffi failed, falling back to httpx for %s", url[:60])
    try:
        async with httpx.AsyncClient(
            headers=XC_HEADERS,
            timeout=httpx.Timeout(15),
            follow_redirects=True,
        ) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return r.text
            logger.warning(f"XC httpx fallback HTTP {r.status_code} for {url[:60]}")
    except Exception as e:
        logger.warning(f"XC httpx fallback error {url[:60]}: {e}")
    return None


async def _xc_fetch_bytes(url: str, referer: str = "") -> Optional[tuple[BytesIO, str]]:
    """Download an XChina image with curl_cffi to bypass Cloudflare."""
    headers = dict(XC_HEADERS)
    if referer:
        headers["Referer"] = referer
    for attempt in range(2):
        try:
            r = await asyncio.to_thread(
                curl_req.get,
                url,
                headers=headers,
                impersonate="chrome131",
                timeout=20,
            )
            if r.status_code == 200 and len(r.content) > 500:
                ct = r.headers.get("Content-Type", "image/jpeg")
                if not ct.startswith("image/"):
                    return None
                result = BytesIO(r.content)
                cropped = crop_watermark(result)
                return cropped, ct
            logger.warning(f"XC img HTTP {r.status_code} size={len(r.content)} for {url[:60]}")
        except Exception as e:
            if attempt == 1:
                logger.warning(f"XC img download failed {url[:60]}: {e}")
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
            # XChina keyword-search pages don't support ?page= — skip pagination
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
                # Author/studio signals: 2-15 chars, contains CJK or Latin, not a date/count/title fragment
                if not txt or len(txt) < 2 or len(txt) > 15:
                    continue
                if txt == title[:len(txt)]:
                    continue
                if txt.startswith("20") and re.search(r"^20\d{2}", txt):
                    continue
                if re.search(r"^\d+\s*P", txt):
                    continue
                # Garbage noise: single English letters, "US", junk tokens
                if re.search(r"^[a-zA-Z]{1,2}$", txt):
                    continue
                # Valid: contains CJK, or is a recognizable Latin name (2+ words or starts with uppercase)
                if re.search(r"[一-鿿]", txt):
                    author = txt
                    break
                if re.search(r"^[A-Z][a-z]", txt) and not re.search(r"^\d", txt):
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
        if not txt or len(txt) < 2 or len(txt) > 15:
            continue
        if txt == result["title"][:len(txt)]:
            continue
        if txt.startswith("20") and re.search(r"^20\d{2}", txt):
            continue
        if re.search(r"^\d+\s*P", txt):
            continue
        if re.search(r"^[a-zA-Z]{1,2}$", txt):
            continue
        if re.search(r"[一-鿿]", txt):
            result["author"] = txt
            break
        if re.search(r"^[A-Z][a-z]", txt) and not re.search(r"^\d", txt):
            result["author"] = txt
            break

    # Extract all image URLs from background-image styles
    img_urls = re.findall(r"https://img\.xchina\.io/photos/[^/]+/\d+_600x0\.webp", text)
    if not img_urls:
        img_urls = re.findall(r"https://img\.xchina\.io/photos/[^/]+/\d+\.webp", text)
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
        # Download cover via curl_cffi to bypass Cloudflare
        img_result = await _xc_fetch_bytes(images[0], referer=url)
        if img_result:
            result["cover_bytes"] = img_result

    await _cache_set(cache_key, result)
    return result
