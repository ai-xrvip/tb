"""4KHD.com scraper - search galleries and extract images"""
import re
import time
import random
import logging
import urllib.parse
from collections import defaultdict
from io import BytesIO
from typing import Optional, Any
import requests
from bs4 import BeautifulSoup
from config import config
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": config.USER_AGENT}

_cache: dict[str, tuple[float, Any]] = {}

# Popularity tracking (with TTL)
keyword_popularity: dict[str, int] = defaultdict(int)
gallery_clicks: dict[str, int] = defaultdict(int)
gallery_titles: dict[str, str] = {}
_click_last_cleanup = 0.0
_CLICK_TTL = 86400 * 7  # keep click data for 7 days


def _cleanup_click_tracking():
    """Periodically trim click tracking to prevent unbounded growth."""
    global _click_last_cleanup
    now = time.time()
    if now - _click_last_cleanup < 3600:  # once per hour max
        return
    _click_last_cleanup = now
    # Just cap the size - if we have too many entries, trim the least popular
    max_entries = 5000
    if len(gallery_clicks) > max_entries:
        sorted_items = sorted(gallery_clicks.items(), key=lambda x: x[1], reverse=True)
        gallery_clicks.clear()
        gallery_clicks.update(sorted_items[:max_entries])
        # Also clean gallery_titles
        for url in list(gallery_titles.keys()):
            if url not in gallery_clicks:
                del gallery_titles[url]
    if len(keyword_popularity) > 500:
        sorted_kw = sorted(keyword_popularity.items(), key=lambda x: x[1], reverse=True)
        keyword_popularity.clear()
        keyword_popularity.update(sorted_kw[:500])


def track_search(keyword: str):
    _cleanup_click_tracking()
    keyword_popularity[keyword.lower()] += 1


def track_click(url: str, title: str = ""):
    _cleanup_click_tracking()
    gallery_clicks[url] += 1
    if title:
        gallery_titles[url] = title


def get_hot_keywords(top_n: int = 5) -> list[str]:
    if not keyword_popularity:
        return ["cosplay", "黑丝", "自拍", "写真", "jk"]
    sorted_kw = sorted(keyword_popularity.items(), key=lambda x: x[1], reverse=True)
    return [kw for kw, _ in sorted_kw[:top_n]]


def _fix_image_url(src: str) -> Optional[str]:
    if not src:
        return None
    if src.startswith("//"):
        src = "https:" + src
    elif not src.startswith("http"):
        src = config.BASE_URL.rstrip("/") + "/" + src.lstrip("/")
    src = re.sub(r"https?://i\d+\.wp\.com/", "https://", src)
    # Only strip known WordPress resize/optimization params, keep other query strings
    src = re.sub(r"[?&](?:w|h|width|height|resize|fit|quality|ssl|strip)=\d+", "", src)
    # Clean up trailing ? or &
    src = re.sub(r"[?&]$", "", src)
    return src


def _fetch(url: str, retries: int = 2) -> Optional[requests.Response]:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=config.REQUEST_TIMEOUT, verify=config.SSL_VERIFY)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 10))
                logger.warning(f"Rate limited, waiting {wait}s")
                time.sleep(wait)
            else:
                logger.warning(f"HTTP {r.status_code} for {url[:80]} (attempt {attempt+1})")
                time.sleep(1)
        except Exception as e:
            logger.warning(f"Request error (attempt {attempt+1}): {e}")
            time.sleep(1)
    return None


def download_image(url: str, referer: str = config.BASE_URL) -> Optional[tuple[BytesIO, str]]:
    img_headers = {**HEADERS, "Referer": referer}
    for attempt in range(2):
        try:
            r = requests.get(url, headers=img_headers, timeout=15, verify=config.SSL_VERIFY)
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
            time.sleep(1)
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


def _extract_date(soup: BeautifulSoup) -> str:
    date_meta = soup.find("meta", property="article:published_time")
    if date_meta:
        dt = date_meta.get("content", "")
        try:
            from datetime import datetime
            parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            return parsed.strftime("%Y年%m月%d日")
        except Exception:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", dt)
            if m:
                parts = m.group(1).split("-")
                return f"{parts[0]}年{parts[1]}月{parts[2]}日"
    return ""


def search_galleries(keyword: str, max_results: int = None, max_pages: int = 3) -> list[dict]:
    """Search galleries by keyword. Defaults to 3 search pages to limit requests."""
    if max_results is None:
        max_results = config.MAX_SEARCH_RESULTS

    track_search(keyword)

    cache_key = f"search:{keyword.lower()}"
    now = time.time()
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if now - ts < config.CACHE_TTL:
            return list(data)[:max_results]

    search_url = config.SEARCH_URL.format(keyword=urllib.parse.quote(keyword))
    logger.info(f"Searching: {search_url}")

    r = _fetch(search_url)
    if not r:
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    # Collect pagination links from the first page
    search_pages = [search_url]
    for a in soup.select(".page-links a.page-numbers, .pagination a.page-numbers"):
        href = a.get("href")
        if href:
            full = href if href.startswith("http") else config.BASE_URL.rstrip("/") + href
            if full not in search_pages:
                search_pages.append(full)

    # Only paginate if first page had enough results to warrant it
    # and respect max_pages parameter (reduced to 3 default from 30)
    search_pages = search_pages[:max_pages]
    logger.info(f"Will scrape {len(search_pages)} search pages")

    all_results = []
    seen_urls = set()

    for sp_idx, sp_url in enumerate(search_pages):
        if sp_idx > 0:
            r = _fetch(sp_url)
            if not r:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            time.sleep(0.3)

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
                _cache[cache_key] = (now, all_results)
                logger.info(f"Found {len(all_results)} results for {keyword!r} (capped)")
                return all_results

    _cache[cache_key] = (now, all_results)
    logger.info(f"Found {len(all_results)} results for {keyword!r}")
    return all_results


def get_gallery_images(post_url: str, max_pages: int = None, max_images: int = None) -> dict:
    if max_pages is None:
        max_pages = config.MAX_PAGES_PER_POST
    if max_images is None:
        max_images = config.MAX_IMAGES_PER_POST

    cache_key = f"gallery:{post_url}"
    now = time.time()
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if now - ts < config.CACHE_TTL:
            return data

    logger.info(f"Fetching gallery: {post_url}")
    r = _fetch(post_url)
    if not r:
        return {"title": "", "images": [], "cover": None, "cover_bytes": None, "publish_date": ""}

    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.find("title")
    title_text = title.text.strip() if title else "Unknown"
    title_text = re.sub(r"\s*[-|]\s*4KHD\s*$", "", title_text).strip()

    publish_date = _extract_date(soup)

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
            r = _fetch(page_url)
            if not r:
                continue
            soup = BeautifulSoup(r.text, "html.parser")

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
            time.sleep(0.3)

    cover_bytes = None
    if cover_url:
        result = download_image(cover_url, referer=post_url)
        if result:
            cover_bytes = result

    result = {
        "title": title_text,
        "images": all_images,
        "cover": cover_url,
        "cover_bytes": cover_bytes,
        "publish_date": publish_date,
    }
    _cache[cache_key] = (now, result)
    return result


def extract_download_link(post_url: str) -> str:
    """Extract download link from post page.

    m.4khd.com is behind Cloudflare JS challenge, so plain requests
    cannot resolve it. Return the m.4khd short link directly and
    let the user's browser handle the challenge.
    """
    r = _fetch(post_url)
    if not r:
        return ""

    soup = BeautifulSoup(r.text, "html.parser")
    content_area = soup.select_one("article, .entry-content, .post-body, .single-content, main") or soup

    for a in content_area.find_all("a", href=True):
        if "m.4khd.com" in a["href"] and "faq" not in a["href"]:
            logger.info(f"Download link: {a['href']}")
            return a["href"]

    m = re.search(r"https?://m\.4khd\.com/([a-zA-Z0-9]+)", r.text)
    if m and m.group(1) != "faq":
        logger.info(f"Download link (regex): {m.group(0)}")
        return m.group(0)

    return ""


# ========== E-Hentai ==========

EH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}
EH_COOKIES = {"nw": "1", "skip_warning": "1"}
EH_BASE = "https://e-hentai.org"


def search_ehentai(keyword: str, max_results: int = 20) -> list[dict]:
    """Search E-Hentai and return gallery list with dates."""
    if max_results is None:
        max_results = config.MAX_SEARCH_RESULTS

    cache_key = f"eh:{keyword.lower()}"
    now = time.time()
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if now - ts < config.CACHE_TTL:
            return list(data)[:max_results]

    search_url = f"{EH_BASE}/?f_search={urllib.parse.quote(keyword)}"
    logger.info(f"EH search: {search_url}")

    try:
        r = requests.get(search_url, headers=EH_HEADERS, cookies=EH_COOKIES,
                        timeout=config.REQUEST_TIMEOUT, verify=config.SSL_VERIFY)
        if r.status_code != 200:
            logger.warning(f"EH search returned {r.status_code}")
            return []
    except Exception as e:
        logger.warning(f"EH search error: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    results = []
    seen = set()

    for a in soup.select(".itg a[href*='/g/']"):
        href = a.get("href", "")
        # Only match actual gallery links: /g/{gid}/{token}/
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
            "date": "",  # filled in by sorting
        })
        
        if len(results) >= max_results:
            break

    _cache[cache_key] = (now, results)
    logger.info(f"EH found {len(results)} results for {keyword!r}")
    return results


def get_ehentai_gallery(gallery_url: str) -> dict:
    """Get E-Hentai gallery details including torrent/magnet links."""
    cache_key = f"eh_gallery:{gallery_url}"
    now = time.time()
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if now - ts < config.CACHE_TTL:
            return data

    logger.info(f"EH gallery: {gallery_url}")
    result = {
        "title": "", "cover": None, "cover_bytes": None,
        "date": "", "file_size": "", "pages": "",
        "magnets": [], "source": "ehentai", "url": gallery_url,
    }

    try:
        r = requests.get(gallery_url, headers=EH_HEADERS, cookies=EH_COOKIES,
                        timeout=config.REQUEST_TIMEOUT, verify=config.SSL_VERIFY)
        if r.status_code != 200:
            return result
    except Exception as e:
        logger.warning(f"EH gallery error: {e}")
        return result

    soup = BeautifulSoup(r.text, "html.parser")

    # Title
    title_el = soup.select_one("#gn") or soup.select_one("#gj") or soup.select_one("h1")
    if title_el:
        result["title"] = title_el.text.strip()

    # Date and info
    for td in soup.select("#gdd td"):
        text = td.text.strip()
        if text and ":" in text:
            key, val = text.split(":", 1)
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
            img_result = download_image(src, referer=gallery_url)
            if img_result:
                result["cover_bytes"] = img_result

    # Check torrent count
    torrent_text = ""
    for p in soup.select("p.g2"):
        text = p.text
        if "Torrent Download" in text:
            torrent_text = text
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
            try:
                r2 = requests.get(torrent_url, headers=EH_HEADERS, cookies=EH_COOKIES,
                                timeout=config.REQUEST_TIMEOUT, verify=config.SSL_VERIFY)
                if r2.status_code == 200:
                    # Extract torrent download links and construct magnet URIs
                    seen_hashes = set()
                    for t_link in re.finditer(r'https?://ehtracker\.org/get/\d+/([a-f0-9]{40})\.torrent', r2.text):
                        info_hash = t_link.group(1)
                        if info_hash not in seen_hashes:
                            seen_hashes.add(info_hash)
                            result["magnets"].append(f"magnet:?xt=urn:btih:{info_hash}")
            except Exception as e:
                logger.warning(f"EH torrent page error: {e}")

    _cache[cache_key] = (now, result)
    return result

