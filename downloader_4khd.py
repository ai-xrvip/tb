"""downloader_4khd.py — Hybrid: httpx for content page + Playwright for m.4khd.com interaction (v5)."""
import asyncio
import logging
import re

logger = logging.getLogger(__name__)

_download_sem = asyncio.Semaphore(1)
_BROWSER_TIMEOUT = 30000
_MAX_AD_STEPS = 10
_PLAYWRIGHT_HARD_TIMEOUT = 60  # seconds — hard cap for the entire Playwright block


async def get_4khd_download(content_url: str) -> dict:
    async with _download_sem:
        return await _do_extract(content_url)


async def _do_extract(content_url: str) -> dict:
    result = {"title": "", "terabox_url": "", "password": "", "error": ""}

    # ---- Step 1: Extract shortcode via httpx (proven working on Railway) ----
    short_code = None
    try:
        from scraper import _fetch
        html = await _fetch(content_url)
        if html:
            m = re.search(r'm\.4khd\.com/(?:linkurl/)?([a-zA-Z\d]+)', html)
            if m and m.group(1) not in ("faq", "linkurl"):
                short_code = m.group(1)
            if not short_code:
                m = re.search(r'linkurl/([a-zA-Z\d]+)', html)
                if m and m.group(1) not in ("faq", "linkurl"):
                    short_code = m.group(1)
            pm = re.search(r'Extracting passwords?:\s*(\S+)', html, re.IGNORECASE)
            if pm:
                result["password"] = pm.group(1)
    except Exception as e:
        logger.warning("4KHD download: httpx fetch failed: %s", e)

    if not short_code:
        result["error"] = "Could not find download shortcode on content page"
        return result

    if not result["password"]:
        result["password"] = "4KHD"

    logger.info("4KHD download [1] Shortcode=%s  Password=%s", short_code, result["password"])

    # ---- Step 2+: Playwright for m.4khd.com interaction ----
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        result["error"] = "Playwright not installed"
        return result

    try:
        async with asyncio.timeout(_PLAYWRIGHT_HARD_TIMEOUT):
            await _run_playwright(short_code, result)
    except asyncio.TimeoutError:
        logger.warning("4KHD download: Playwright hard timeout (%ds)", _PLAYWRIGHT_HARD_TIMEOUT)
        result["error"] = f"Download timed out ({_PLAYWRIGHT_HARD_TIMEOUT}s)"

    return result


async def _run_playwright(short_code: str, result: dict) -> None:
    """Run the Playwright interaction to extract the TeraBox link."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        try:
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
            )
            await ctx.add_init_script("""
                Object.defineProperty(navigator, "webdriver", { get: () => false });
                Object.defineProperty(navigator, "plugins", { get: () => [1,2,3,4,5] });
                Object.defineProperty(navigator, "languages", { get: () => ["zh-CN", "zh", "en"] });
                window.chrome = { runtime: {} };
            """)
            page = await ctx.new_page()

            short_url = "https://m.4khd.com/linkurl/" + short_code
            logger.info("4KHD download [2] Opening %s", short_url)
            await page.goto(short_url, wait_until="domcontentloaded", timeout=_BROWSER_TIMEOUT)

            for step in range(_MAX_AD_STEPS):
                state = "waiting"
                for _w in range(15):
                    await asyncio.sleep(2)
                    state = await _check_page_state(page)
                    if state != "waiting":
                        break

                if state == "terabox":
                    logger.info("4KHD download [%d] -> Terabox", step + 3)
                    break

                if state == "getlink":
                    logger.info("4KHD download [%d] Clicking GET LINK", step + 3)
                    await _click_get_link(page)
                    await asyncio.sleep(5)

                    if await _check_page_state(page) == "terabox":
                        logger.info("4KHD download [%d] -> Terabox", step + 3)
                        break
                    continue

                direct = await page.evaluate("""() => {
                    const links = document.querySelectorAll("a");
                    for (const a of links) {
                        if (a.href && a.href.includes("terabox.com") && a.href.includes("surl=")) return a.href;
                    }
                    return null;
                }""")
                if direct:
                    logger.info("4KHD download [%d] -> Direct link", step + 3)
                    await page.goto(direct, wait_until="domcontentloaded", timeout=15000)
                    break

                result["error"] = f"Stuck at ad step {step} (state: {state})"
                break

            result["terabox_url"] = page.url
            logger.info("4KHD download done: %s", result["terabox_url"][:80])

        except Exception as e:
            logger.warning("4KHD download Playwright failed: %s", e)
            result["error"] = str(e)
        finally:
            await browser.close()


async def _check_page_state(page) -> str:
    try:
        if "terabox.com" in page.url:
            return "terabox"
        has_get_link = await page.evaluate(
            """() => [...document.querySelectorAll("a")].some(a => a.textContent.trim() === "GET LINK")"""
        )
        if has_get_link:
            return "getlink"
        has_tb = await page.evaluate("""() => {
            const links = document.querySelectorAll("a");
            for (const a of links) {
                if (a.href && a.href.includes("terabox.com") && a.href.includes("surl=")) return true;
            }
            return false;
        }""")
        if has_tb:
            return "terabox"
        return "waiting"
    except Exception:
        return "waiting"


async def _click_get_link(page) -> None:
    await page.evaluate("""() => {
        const links = document.querySelectorAll("a");
        for (const a of links) {
            if (a.textContent.trim() === "GET LINK") { a.click(); return; }
        }
    }""")