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
from bs4 import BeautifulSoup
from config import config

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


async def _fetch(url: str, retries: int = 2) -> Optional[str]:
    """Async HTTP GET, returns response text."""
    client = await _get_client()
    for attempt in range(retries):
        try:
            r = await client.get(url, follow_redirects=True)
            if r.status_code == 200:
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

    soup = BeautifulSoup(text, "html.parser")

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
            soup = BeautifulSoup(sp_text, "html.parser")
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

    cache_key = f"gallery:{post_url}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return cached

    logger.info(f"Fetching gallery: {post_url}")
    text = await _fetch(post_url)
    if not text:
        return {"title": "", "images": [], "cover": None, "cover_bytes": None, "publish_date": ""}

    soup = BeautifulSoup(text, "html.parser")
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
            soup = BeautifulSoup(page_text, "html.parser")

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
                inner = BeautifulSoup(ns.text, "html.parser")
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

    soup = BeautifulSoup(text, "html.parser")
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


# ========== E-Hentai ==========

EH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}
EH_COOKIES = {"nw": "1", "skip_warning": "1"}
EH_BASE = "https://e-hentai.org"

_eh_client: Optional[httpx.AsyncClient] = None
_eh_client_lock = asyncio.Lock()
_EH_REQUEST_DELAY = 1.5  # seconds between EH requests to avoid rate limiting
_eh_last_request = 0.0
_eh_delay_lock = asyncio.Lock()


async def _get_eh_client() -> httpx.AsyncClient:
    """Get or create the E-Hentai specific client."""
    global _eh_client
    async with _eh_client_lock:
        if _eh_client is None:
            _eh_client = httpx.AsyncClient(
                headers=EH_HEADERS,
                cookies=EH_COOKIES,
                timeout=httpx.Timeout(config.REQUEST_TIMEOUT),
                verify=config.SSL_VERIFY,
            )
        return _eh_client


async def _eh_fetch(url: str) -> Optional[str]:
    """Fetch EH page with rate limiting between requests."""
    global _eh_last_request
    async with _eh_delay_lock:
        now = datetime.now().timestamp()
        wait = _EH_REQUEST_DELAY - (now - _eh_last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        _eh_last_request = datetime.now().timestamp()

    client = await _get_eh_client()
    try:
        r = await client.get(url, follow_redirects=True)
        if r.status_code == 200:
            return r.text
        logger.warning(f"EH fetch returned {r.status_code} for {url[:60]}")
        return None
    except Exception as e:
        logger.warning(f"EH fetch error for {url[:60]}: {e}")
        return None


async def _eh_fetch_bytes(url: str, referer: str = "") -> Optional[tuple[BytesIO, str]]:
    """Fetch EH image bytes. Reuses EH client for cookie context."""
    async with _eh_delay_lock:
        now = datetime.now().timestamp()
        wait = _EH_REQUEST_DELAY - (now - _eh_last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        _eh_last_request = now

    client = await _get_eh_client()
    headers = {}
    if referer:
        headers["Referer"] = referer
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
        logger.warning(f"EH image fetch error {url[:60]}: {e}")
        return None


async def search_ehentai(keyword: str, max_results: int = 20) -> list[dict]:
    """Search E-Hentai and return gallery list."""
    if max_results is None:
        max_results = config.MAX_SEARCH_RESULTS

    cache_key = f"eh:{keyword.lower()}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return list(cached)[:max_results]

    search_url = f"{EH_BASE}/?f_search={urllib.parse.quote(keyword)}"
    logger.info(f"EH search: {search_url}")

    text = await _eh_fetch(search_url)
    if not text:
        return []

    soup = BeautifulSoup(text, "html.parser")
    results = []
    seen = set()

    for a in soup.select(".itg a[href*='/g/']"):
        href = a.get("href", "")
        if not re.match(r'.*/g/\d+/[a-f0-9]+/?$', href):
            continue
        if href in seen:
            continue
        seen.add(href)

        title = a.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        results.append({
            "title": title,
            "url": href,
            "cover": None,
            "source": "ehentai",
            "date": "",
        })

        if len(results) >= max_results:
            break

    await _cache_set(cache_key, results)
    logger.info(f"EH found {len(results)} results for {keyword!r}")
    return results


async def get_ehentai_gallery(gallery_url: str) -> dict:
    """Get E-Hentai gallery details including torrent/magnet links."""
    cache_key = f"eh_gallery:{gallery_url}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return cached

    logger.info(f"EH gallery: {gallery_url}")
    result = {
        "title": "", "cover": None, "cover_bytes": None,
        "date": "", "file_size": "", "pages": "",
        "magnets": [], "source": "ehentai", "url": gallery_url,
    }

    text = await _eh_fetch(gallery_url)
    if not text:
        return result

    soup = BeautifulSoup(text, "html.parser")

    # Title
    title_el = soup.select_one("#gn") or soup.select_one("#gj") or soup.select_one("h1")
    if title_el:
        result["title"] = title_el.text.strip()

    # Date and info
    for td in soup.select("#gdd td"):
        text_val = td.text.strip()
        if text_val and ":" in text_val:
            key, val = text_val.split(":", 1)
            key = key.strip().lower()
            val = val.strip()
            if key == "posted":
                result["date"] = val
            elif key == "file size":
                result["file_size"] = val.split("<")[0].strip()
            elif key == "length":
                result["pages"] = val.split(" ")[0]

    # Cover image
    cover_el = soup.select_one("#gd1 img") or soup.select_one(".gm img")
    if cover_el:
        src = cover_el.get("src") or cover_el.get("data-src")
        if src and src.startswith("http"):
            result["cover"] = src
            img_result = await _eh_fetch_bytes(src, referer=gallery_url)
            if img_result:
                result["cover_bytes"] = img_result

    # Check torrent count
    torrent_text = ""
    for p in soup.select("p.g2"):
        text_p = p.text
        if "Torrent Download" in text_p:
            torrent_text = text_p
            break

    torrent_count = 0
    m = re.search(r'\((\d+)\)', torrent_text)
    if m:
        torrent_count = int(m.group(1))

    # Get magnet links from torrent page
    if torrent_count > 0:
        match = re.search(r'/g/(\d+)/([a-f0-9]+)', gallery_url)
        if match:
            gid = match.group(1)
            token = match.group(2)
            torrent_url = f"{EH_BASE}/gallerytorrents.php?gid={gid}&t={token}"
            r2_text = await _eh_fetch(torrent_url)
            if r2_text:
                seen_hashes = set()
                for t_link in re.finditer(r'https?://ehtracker\.org/get/\d+/([a-f0-9]{40})\.torrent', r2_text):
                    info_hash = t_link.group(1)
                    if info_hash not in seen_hashes:
                        seen_hashes.add(info_hash)
                        result["magnets"].append(f"magnet:?xt=urn:btih:{info_hash}")

    await _cache_set(cache_key, result)
    return result
