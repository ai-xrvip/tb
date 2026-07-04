"""E-Hentai scraper: search, gallery images, magnet links."""
import asyncio, hashlib, logging, re, time
from io import BytesIO
from typing import Optional
from bs4 import BeautifulSoup
import httpx

import config

logger = logging.getLogger(__name__)

EH_BASE = "https://e-hentai.org"
EH_SEARCH = f"{EH_BASE}/?f_cats=959&f_search={{keyword}}"
MAX_EH_PAGES = 3

def _eh_cookies():
    return {
        "ipb_member_id": config.EH_MEMBER_ID,
        "ipb_pass_hash": config.EH_PASS_HASH,
        "sk": config.EH_SK,
        "event": config.EH_EVENT,
    }

EH_HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Referer": f"{EH_BASE}/",
}


def _compute_info_hash(torrent_data: bytes) -> Optional[str]:
    """Compute BT info_hash from .torrent file bytes."""
    idx = torrent_data.find(b"4:info")
    if idx == -1:
        return None
    rest = torrent_data[idx + 6:]
    depth = 0
    end = 0
    for i in range(len(rest)):
        ch = rest[i]
        if ch == 0x64:
            depth += 1
        elif ch == 0x65:
            depth -= 1
        elif ch == 0x6C:
            depth += 1
        if depth == 0 and i > 0:
            end = i + 1
            break
    if end == 0:
        return None
    info_bytes = rest[:end]
    return hashlib.sha1(info_bytes).hexdigest()


def _get_name(torrent_data: bytes) -> str:
    """Extract torrent name from .torrent file."""
    idx = torrent_data.find(b"4:name")
    if idx == -1:
        return ""
    rest = torrent_data[idx + 6:]
    colon = rest.find(b":")
    if colon == -1 or colon > 5:
        return ""
    try:
        length = int(rest[:colon])
    except ValueError:
        return ""
    start = colon + 1
    name = rest[start:start + length]
    return name.decode("utf-8", errors="replace")


async def _eh_fetch(url: str, timeout: int = 30) -> Optional[str]:
    """Fetch E-Hentai page with cookies."""
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(
                headers=EH_HEADERS, cookies=_eh_cookies(), timeout=timeout, follow_redirects=True
            ) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    return r.text
                logger.warning(f"EH fetch {url[:80]}: HTTP {r.status_code}")
        except Exception as e:
            logger.warning(f"EH fetch attempt {attempt+1}: {e}")
        await asyncio.sleep(2)
    return None


async def search_ehentai(keyword: str, max_results: int = 20, max_pages: int = MAX_EH_PAGES) -> list[dict]:
    """Search E-Hentai cosplay galleries."""
    results = []
    seen = set()

    for page in range(max_pages):
        url = EH_SEARCH.format(keyword=keyword)
        if page > 0:
            url += f"&page={page}"

        text = await _eh_fetch(url)
        if not text:
            continue

        soup = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, text, "html.parser")

        for row in soup.select("tr.gtr0, tr.gtr1"):
            a_tag = row.select_one("a[href*='/g/']")
            if not a_tag:
                continue
            href = a_tag.get("href", "")
            m = re.search(r"/g/(\d+)/([a-f0-9]+)", href)
            if not m:
                continue
            if href in seen:
                continue
            seen.add(href)

            title_el = row.select_one(".glink")
            title = title_el.text.strip() if title_el else "Untitled"

            cover = None
            img = row.select_one("img")
            if img:
                src = img.get("src") or img.get("data-src", "")
                if src and not src.startswith("data:"):
                    cover = src

            category = ""
            cat_el = row.select_one(".cn, .cs, .ic")
            if cat_el:
                category = cat_el.text.strip()

            torrent_link = row.select_one("a[href*='gallerytorrents.php']")
            has_torrent = bool(torrent_link)

            results.append({
                "title": title,
                "url": href,
                "cover": cover,
                "source": "ehentai",
                "category": category,
                "has_torrent": has_torrent,
                "gid": m.group(1),
                "token": m.group(2),
            })

            if len(results) >= max_results:
                return results

        if not soup.select("tr.gtr0, tr.gtr1"):
            break
        await asyncio.sleep(1)

    return results


async def get_eh_gallery(url: str, max_images: int = 30) -> dict:
    """Get E-Hentai gallery details: title, cover, image list."""
    result = {
        "title": "", "cover": None, "cover_bytes": None,
        "images": [], "count": 0, "source": "ehentai", "url": url,
        "gid": "", "token": "", "tags": [],
    }

    text = await _eh_fetch(url)
    if not text:
        return result

    soup = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, text, "html.parser")

    h1 = soup.select_one("h1#gn, h1#gj")
    if h1:
        result["title"] = h1.text.strip()

    m = re.search(r"/g/(\d+)/([a-f0-9]+)", url)
    if m:
        result["gid"] = m.group(1)
        result["token"] = m.group(2)

    for tag_a in soup.select("#taglist a, .gt"):
        tag_text = tag_a.text.strip()
        if tag_text and ":" in tag_text:
            result["tags"].append(tag_text)

    count_el = soup.select_one(".gpc")
    if count_el:
        count_text = count_el.text.strip()
        m_count = re.search(r"(\d+)\s*pages", count_text, re.IGNORECASE)
        if m_count:
            result["count"] = int(m_count.group(1))

    thumbs = []
    gdt = soup.select_one("#gdt")
    if gdt:
        for a in gdt.select("a"):
            thumb_href = a.get("href", "")
            if thumb_href and "/s/" in thumb_href:
                thumbs.append(thumb_href)

    images = []
    sem = asyncio.Semaphore(3)

    async def _fetch_img_url(thumb_url):
        async with sem:
            for attempt in range(2):
                try:
                    t = await _eh_fetch(thumb_url)
                    if not t:
                        continue
                    s = await asyncio.get_running_loop().run_in_executor(None, BeautifulSoup, t, "html.parser")
                    img = s.select_one("#img")
                    if img and img.get("src"):
                        return img["src"]
                except Exception:
                    pass
                await asyncio.sleep(1)
        return None

    if thumbs:
        limit = min(len(thumbs), max_images)
        results_list = await asyncio.gather(*[_fetch_img_url(u) for u in thumbs[:limit]])
        images = [u for u in results_list if u]

    if not result["count"] and images:
        result["count"] = len(thumbs)

    result["images"] = images

    if images:
        result["cover"] = images[0]

    return result


async def get_eh_magnet(url: str) -> Optional[str]:
    """Get magnet link from E-Hentai gallery. Returns None if no torrent."""
    text = await _eh_fetch(url)
    if not text:
        return None

    m = re.search(r"gallerytorrents\.php\?gid=(\d+)&(?:amp;)?t=([a-f0-9]+)", text)
    if not m:
        return None

    gid = m.group(1)
    token = m.group(2)
    torrent_url = f"{EH_BASE}/gallerytorrents.php?gid={gid}&t={token}"

    t_text = await _eh_fetch(torrent_url)
    if not t_text:
        return None

    m_tor = re.search(r'https?://[^"\s]+\.torrent', t_text)
    if not m_tor:
        return None

    tor_dl = m_tor.group(0)

    try:
        async with httpx.AsyncClient(headers=EH_HEADERS, cookies=_eh_cookies(), timeout=30) as client:
            r = await client.get(tor_dl)
            if r.status_code != 200:
                return None
            tor_data = r.content
    except Exception as e:
        logger.warning(f"Torrent download failed: {e}")
        return None

    info_hash = _compute_info_hash(tor_data)
    if not info_hash:
        return None

    name = _get_name(tor_data) or f"EH_{gid}"
    from urllib.parse import quote
    magnet = f"magnet:?xt=urn:btih:{info_hash}&dn={quote(name)}"
    return magnet
