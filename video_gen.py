# Video generation - Agnes AI image-to-video / text-to-video
# IMAGE_REF_{ROLE} = a page URL containing images, randomly picks one as reference.
import asyncio, base64, json, os, random, re, time, urllib.parse
import httpx
from config import config
from utils.logger import logger

VIDEO_GEN_TIMEOUT = 120
_REF_CACHE = {}
_CACHE_TTL = 600
_VIDEO_COMPOSITIONS = [
    "gentle smile and wave, soft breeze blowing hair, natural light, cinematic slow motion",
    "walking towards camera, confident stride, city background, golden hour lighting, smooth camera",
    "turning head and laughing, candid moment, outdoor cafe, warm afternoon light",
    "sitting and looking up, soft eye contact, cozy room, window light, gentle movement",
    "hair flip and smile, slow motion, studio lighting, fashion video style",
    "looking over shoulder, mysterious glance, moody lighting, cinematic film grain",
    "dancing softly, flowing dress, sunset beach, romantic atmosphere, dreamy filter",
    "reading a book then looking up, library setting, soft focus background, intellectual vibe",
    "playing with hair, flirty smile, bedroom setting, warm lamp light, intimate mood",
    "walking in rain with umbrella, neon city lights, reflective puddles, cinematic mood",
    "blowing a kiss, romantic gesture, soft bokeh background, slow motion close-up",
    "stretching and yawning, morning sunlight, bedroom, cute casual outfit, cozy feeling",
]

VIDEO_NEGATIVE_PROMPT = (
    "blurry, low quality, jpeg artifacts, watermark, text, signature, "
    "distorted face, deformed face, ugly face, asymmetric eyes, "
    "bad anatomy, deformed anatomy, disfigured, mutated, extra limbs, "
    "bad hands, ugly hands, missing fingers, extra fingers, fused fingers, "
    "poorly drawn hands, deformed hands, mutated hands, "
    "worst quality, lowres, error, cropped, out of frame, "
    "flickering, jittery, unstable, warping, morphing artifacts, "
    "poorly drawn feet, bad feet, extra toes, missing toes"
)

IMG_TAG_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)
MD_IMG_RE = re.compile(r'!\[.*?\]\(([^)]+)\)')


async def _scrape_page(page_url: str) -> list:
    """Scrape image URLs from a page (telegra.ph etc). Results cached for 10 min."""
    now = time.time()
    if page_url in _REF_CACHE:
        ts, urls = _REF_CACHE[page_url]
        if now - ts < _CACHE_TTL and urls:
            return urls
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(page_url, headers={"User-Agent": "Bot/1.0"})
            if resp.status_code != 200:
                return []
            html = resp.text
    except Exception:
        return []

    img_urls = IMG_TAG_RE.findall(html)
    img_urls += MD_IMG_RE.findall(html)

    parsed = urllib.parse.urlparse(page_url)
    base = f"{parsed.scheme}://{parsed.hostname}"
    resolved = []
    for u in img_urls:
        if u.startswith("/"): u = base + u
        elif u.startswith("//"): u = "https:" + u
        elif u.startswith("data:"): continue
        elif not u.startswith("http"): u = urllib.parse.urljoin(page_url, u)
        resolved.append(u)
        if len(resolved) >= 30:
            break

    _REF_CACHE[page_url] = (now, resolved)
    logger.info(f"Scraped {len(resolved)} images from {page_url[:60]}...")
    return resolved


async def _pick_ref(page_url: str) -> str | None:
    """Scrape page and return a random image URL as reference."""
    urls = await _scrape_page(page_url)
    return random.choice(urls) if urls else None


def _get_character_desc(role_id: str) -> str:
    """Get character description for video prompt."""
    _ROLE_CHARACTER = {
        "xiaolu": "cute young Asian woman, sweet smile, cosplayer, JK uniform, twin tails, soft makeup, fair skin, perfect hands, slender fingers",
        "linxi": "beautiful Chinese woman, elegant professional, dark suit, high ponytail, sharp eyes, CEO aura, tall slender, fair skin, perfect hands",
        "mia": "sporty Chinese-American woman, athletic build, ponytail, yoga wear, happy smile, muscular legs, abs, perfect hands",
        "sunian": "graceful Chinese woman, gentle eyes, long wavy hair, linen dress, artistic temperament, slender figure, pale skin, perfect hands",
        "yuki": "delicate Chinese girl, soft features, hanfu style, long straight black hair, porcelain skin, elegant posture, gentle smile, perfect hands",
        "reina": "wealthy Japanese-Chinese young woman, designer clothes, luxury handbag, elegant jewelry, perfect makeup, tsundere look, perfect hands",
        "chiyo": "gentle Chinese woman, apron over casual clothes, warm smile, slightly tired eyes, full figure, caring expression, perfect hands",
        "nana": "fun Chinese girl, gaming headset, casual hoodie, short skirt, playful smile, colorful hair, energetic look, perfect hands",
        "mizuki": "powerful Chinese CEO, sharp business suit, high heels, cold expression, elegant updo, intimidating aura, perfect hands",
        "akari": "cute Chinese nurse, white uniform, gentle smile, natural makeup, round glasses, soft features, cute face, perfect hands",
        "yuna": "tall Chinese fashion model, runway walk, designer clothes, perfect figure, long legs, elegant pose, high cheekbones, perfect hands",
        "shiori": "introspective Chinese girl, glasses, book in hand, scholarly look, long braid, soft expression, vintage cardigan, perfect hands",
        "sora": "elegant Chinese flight attendant, airline uniform, professional smile, perfect posture, gentle eyes, hair in bun, perfect hands",
        "kaede": "strong Chinese policewoman, uniform, sharp eyes, athletic build, short hair, confident stance, perfect hands",
        "ruri": "sharp Chinese lawyer, business suit, tote bag, confident expression, glasses, sleek bun, elegant heels, perfect hands",
        "ren": "mysterious Chinese bartender, elegant black dress, cocktail shaker, smoky eyes, long hair, perfect hands",
        "hana": "gentle Chinese florist, flower crown, linen apron, soft smile, tanned skin, natural look, perfect hands",
        "mai": "elegant Chinese ballet dancer, leotard, tutu, pointe shoes, graceful posture, delicate features, perfect hands",
        "momo": "sweet Taiwanese dessert chef, cute apron, flour on cheek, big eyes, short hair, happy expression, perfect hands",
        "sakura": "gentle Chinese veterinarian, white coat, stethoscope, warm smile, soft eyes, caring hands, perfect hands",
        "aya": "efficient Chinese secretary, office suit, glasses, smart bun, typing pose, professional smile, perfect hands",
        "mei": "creative Chinese musician, guitar, bohemian dress, artistic look, messy bun, creative expression, perfect hands",
        "koharu": "adventurous Chinese photographer, camera around neck, rugged boots, sun-kissed skin, free spirit, perfect hands",
        "tsubaki": "determined Chinese journalist, trench coat, notepad, determined eyes, urban professional, perfect hands",
        "rio": "cool Chinese female racer, racing suit, helmet under arm, lean athletic build, focused eyes, perfect hands",
        "nozomi": "cute Chinese voice actress, microphone, headphones, cosplay accessories, expressive face, perfect hands",
        "nami": "free-spirited Chinese surfer girl, wetsuit, surfboard, tan skin, wet hair, strong arms, perfect hands",
        "fumi": "quiet Chinese librarian, vintage cardigan, glasses, serene expression, soft features, perfect hands",
        "eri": "smart Chinese AI researcher, hoodie, glasses, messy ponytail, focused expression, perfect hands",
        "yui": "cute Chinese maid cafe girl, maid uniform, cat ears, coffee tray, bright smile, perfect hands",
    }
    return _ROLE_CHARACTER.get(role_id, "beautiful young Asian woman, cute face, charming smile, trendy fashion, natural makeup, perfect hands")


def _build_video_prompt(text: str, role_id: str = "") -> str:
    """Build video generation prompt with character + motion description."""
    char_desc = _get_character_desc(role_id)
    text = text.strip()[:200]
    motion = random.choice(_VIDEO_COMPOSITIONS)
    quality = "high quality, photorealistic, smooth motion, consistent face, cinematic, 24fps, masterpiece"
    return f"{char_desc}, {motion}, {quality} -- scene: {text}"


async def generate_video(prompt: str, role_id: str = "", page_url: str = "") -> bytes | None:
    """Generate video via Agnes AI. Supports image-to-video when page_url is provided."""
    if not config.VIDEO_GEN_ENABLED:
        return None
    if not config.IMAGE_GEN_API_KEY:
        logger.warning("IMAGE_GEN_API_KEY not set (used for video gen too)")
        return None

    ref_url = None
    if not page_url:
        page_url = config.get_image_ref(role_id)
    if page_url:
        ref_url = await _pick_ref(page_url)

    video_prompt = _build_video_prompt(prompt, role_id)
    logger.info(f"Video gen: role={role_id} prompt={prompt[:80]}... ref={bool(ref_url)}")

    task_id = await _submit_video_task(video_prompt, ref_url)
    if not task_id:
        return None

    video_url = await _poll_video_task(task_id)
    if not video_url:
        return None

    return await _download_video(video_url)


async def _submit_video_task(prompt: str, ref_url: str | None = None) -> str | None:
    """Submit a video generation task. Returns task_id."""
    payload = {
        "model": config.VIDEO_GEN_MODEL,
        "prompt": prompt,
        "negative_prompt": VIDEO_NEGATIVE_PROMPT,
        "n": 1,
        "size": config.VIDEO_GEN_SIZE,
        "seconds": config.VIDEO_GEN_SECONDS,
    }
    if ref_url:
        payload["image"] = ref_url

    api_url = f"{config.IMAGE_GEN_BASE_URL}/video/generations"
    logger.info(f"Agnes video submit: model={config.VIDEO_GEN_MODEL} ref={bool(ref_url)}")

    try:
        async with httpx.AsyncClient(timeout=VIDEO_GEN_TIMEOUT, follow_redirects=True) as client:
            resp = await client.post(
                api_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {config.IMAGE_GEN_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                task_id = data.get("task_id", "") or data.get("id", "")
                if task_id:
                    logger.info(f"Video task submitted: {task_id}")
                    return task_id
                logger.warning(f"Video submit: no task_id in response: {str(data)[:200]}")
            elif resp.status_code == 429:
                logger.error("Video gen rate limited (429)")
            else:
                logger.warning(f"Video submit HTTP {resp.status_code}: {resp.text[:300]}")
    except httpx.TimeoutException:
        logger.error("Video submit timeout")
    except Exception as e:
        logger.error(f"Video submit error: {type(e).__name__}: {e}")
    return None


async def _poll_video_task(task_id: str) -> str | None:
    """Poll video task until complete. Returns video download URL."""
    api_url = f"{config.IMAGE_GEN_BASE_URL}/video/generations/{task_id}"
    poll_interval = config.VIDEO_GEN_POLL_INTERVAL
    timeout = config.VIDEO_GEN_POLL_TIMEOUT
    elapsed = 0

    logger.info(f"Polling video task {task_id} (timeout={timeout}s, interval={poll_interval}s)")

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            try:
                resp = await client.get(
                    api_url,
                    headers={
                        "Authorization": f"Bearer {config.IMAGE_GEN_API_KEY}",
                    },
                )
                if resp.status_code != 200:
                    logger.warning(f"Video poll HTTP {resp.status_code}")
                    continue

                data = resp.json()
                inner = data.get("data", data)
                status = inner.get("status", "").lower()

                if status in ("completed", "succeeded", "done"):
                    video_url = inner.get("video_url", "") or inner.get("url", "")
                    if not video_url:
                        nested = inner.get("data", {})
                        video_url = nested.get("video_url", "") or nested.get("url", "")
                    if not video_url:
                        results = inner.get("result", [])
                        if results and isinstance(results, list):
                            video_url = results[0].get("url", "") or results[0].get("video_url", "")
                    if video_url:
                        logger.info(f"Video task completed: {task_id}")
                        return video_url
                    logger.warning(f"Video completed but no URL found: {str(inner)[:300]}")

                elif status in ("failed", "error", "cancelled"):
                    error_msg = inner.get("error", "") or inner.get("fail_reason", "")
                    logger.error(f"Video task failed: {error_msg}")
                    return None

                else:
                    progress = inner.get("progress", "?")
                    logger.info(f"Video task {task_id}: {status} ({progress})")

            except httpx.TimeoutException:
                logger.warning("Video poll timeout (will retry)")
            except Exception as e:
                logger.error(f"Video poll error: {type(e).__name__}: {e}")

    logger.error(f"Video task {task_id} timed out after {timeout}s")
    return None


async def _download_video(video_url: str) -> bytes | None:
    """Download the generated video."""
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(video_url)
            if resp.status_code == 200:
                logger.info(f"Video downloaded: {len(resp.content)} bytes")
                return resp.content
            logger.warning(f"Video download HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"Video download error: {type(e).__name__}: {e}")
    return None