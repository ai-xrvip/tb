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

# Popularity tracking
keyword_popularity: dict[str, int] = defaultdict(int)
gallery_clicks: dict[str, int] = defaultdict(int)
gallery_titles: dict[str, str] = {}


def track_search(keyword: str):
    keyword_popularity[keyword.lower()] += 1


def track_click(url: str, title: str = ""):
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
    src = src.replace("pic.4khd.com", "img.4khd.com")
    if "?" in src:
        src = src.split("?")[0]
    return src


def _fetch(url: str, retries: int = 2) -> Optional[requests.Response]:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=config.REQUEST_TIMEOUT)
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
            r = requests.get(url, headers=img_headers, timeout=15, verify=False)
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


def search_galleries(keyword: str, max_results: int = None, max_pages: int = 30) -> list[dict]:
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

    # Collect all search result page URLs
    search_pages = [search_url]
    for a in soup.select(".page-links a.page-numbers, .pagination a.page-numbers"):
        href = a.get("href")
        if href:
            full = href if href.startswith("http") else config.BASE_URL.rstrip("/") + href
            if full not in search_pages:
                search_pages.append(full)
    base = f"{config.BASE_URL}/search/{urllib.parse.quote(keyword)}"
    for p in range(2, max_pages + 1):
        page_url = f"{base}/page/{p}/"
        if page_url not in search_pages:
            search_pages.append(page_url)
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
    r = _fetch(post_url)
    if not r:
        return ""
    m = re.search(r"https?://m\.4khd\.com/([a-zA-Z0-9]+)", r.text)
    if not m:
        return ""
    short_code = m.group(1)
    short_url = f"https://m.4khd.com/{short_code}"
    logger.info(f"Found short link: {short_url}")
    r2 = requests.get(short_url, headers=HEADERS, allow_redirects=True, timeout=15)
    if r2.status_code != 200:
        return ""
    m2 = re.search(r"https?://www\.terabox\.com/[^\s\"'<>]+", r2.text)
    if m2:
        return m2.group(0).rstrip("'\"")
    return ""


def get_random_gallery() -> Optional[dict]:
    results = []
    seen_urls = set()
    if gallery_clicks:
        sorted_clicks = sorted(gallery_clicks.items(), key=lambda x: x[1], reverse=True)
        top_urls = [url for url, _ in sorted_clicks[:5]]
        random.shuffle(top_urls)
        for url in top_urls:
            title = gallery_titles.get(url, "")
            keywords = title.split()[:3] if title else []
            kw = " ".join(keywords) if keywords else ""
            if kw:
                similar = search_galleries(kw, max_results=3, max_pages=1)
                for r in similar:
                    if r["url"] not in seen_urls:
                        results.append(r)
                        seen_urls.add(r["url"])
    hot_kws = get_hot_keywords(top_n=3)
    for kw in hot_kws:
        search_results = search_galleries(kw, max_results=10, max_pages=1)
        for r in search_results:
            if r["url"] not in seen_urls:
                results.append(r)
                seen_urls.add(r["url"])
    if results:
        weighted = []
        for r in results:
            weight = gallery_clicks.get(r["url"], 0) + 1
            weighted.extend([r] * weight)
        return random.choice(weighted)
    results = search_galleries("cosplay", max_results=30, max_pages=1)
    if not results:
        results = search_galleries("", max_results=30, max_pages=1)
    return random.choice(results) if results else None
