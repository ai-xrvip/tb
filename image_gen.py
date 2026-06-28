# Image generation - Agnes AI img2img (free tier, 4000 images/day)
# Reference images scraped from per-role folder/page URLs
import os, re, time, random, base64, json, httpx, urllib.request, urllib.parse
from config import config
from utils.logger import logger

GEN_TIMEOUT = 120

NEGATIVE_PROMPT = (
    "bad hands, ugly hands, missing fingers, extra fingers, fused fingers, "
    "poorly drawn hands, deformed hands, mutated hands, disfigured fingers, "
    "bad anatomy, deformed anatomy, disfigured, mutated, extra limbs, "
    "blurry, low quality, jpeg artifacts, watermark, text, signature, "
    "ugly face, asymmetric eyes, distorted face, deformed face, "
    "bad proportions, long neck, cloned face, double face, "
    "worst quality, lowres, error, cropped, out of frame, "
    "poorly drawn feet, bad feet, extra toes, missing toes"
)

CHARACTER_PREFIX = {
    "xiaolu": "cute young Asian woman, sweet smile, cosplayer, JK uniform, twin tails, soft makeup, fair skin, perfect hands, slender fingers",
    "linxi": "elegant Asian woman, OL outfit, high heels, sharp eyes, mature beauty, black hair, red lips, perfect hands",
    "mia": "innocent Asian woman, sundress, long wavy hair, doe eyes, natural makeup, soft lighting, perfect hands",
    "sunian": "gentle Asian woman, traditional hanfu, classical beauty, long black hair, elegant posture, perfect hands, delicate fingers",
}
DEFAULT_CHARACTER = "beautiful young Asian woman, cute face, charming smile, trendy fashion, natural makeup, perfect hands"

ROLE_NEGATIVES = {
    "xiaolu": "nsfw, nude, revealing, skimpy, lingerie, bikini, muscular, tall",
}

ROLE_REF_FOLDERS = {
    "xiaolu": ["https://telegra.ph/miko3%E5%A4%8D%E6%B4%BB%E7%89%88-06-27"],
}

def _get_role_ref_folders(role_id):
    env_key = f"IMAGE_REF_FOLDERS_{role_id.upper()}"
    env_val = os.getenv(env_key, "")
    if env_val:
        return [u.strip() for u in env_val.split(",") if u.strip()]
    return ROLE_REF_FOLDERS.get(role_id, [])

_ref_cache = {}
_CACHE_TTL = 600

def _scrape_images_from_page(page_url: str) -> list[str]:
    now = time.time()
    if page_url in _ref_cache:
        ts, urls = _ref_cache[page_url]
        if now - ts < _CACHE_TTL and urls:
            return urls
    try:
        client = httpx.Client(timeout=15, follow_redirects=True)
        resp = client.get(page_url, headers={"User-Agent": "Bot/1.0"})
        if resp.status_code != 200:
            return []
        html = resp.text
    except Exception:
        return []
    img_urls = re.findall(r'<img[^>]+src=["\x27]([^"\x27]+)["\x27]', html, re.IGNORECASE)
    if not img_urls:
        img_urls = re.findall(r'!\[.*?\]\(([^)]+)\)', html)
    parsed_base = urllib.parse.urlparse(page_url)
    base_host = f"{parsed_base.scheme}://{parsed_base.hostname}"
    resolved = []
    for u in img_urls:
        if u.startswith("/"): u = base_host + u
        elif u.startswith("//"): u = "https:" + u
        elif u.startswith("data:"): continue
        elif not u.startswith("http"): u = urllib.parse.urljoin(page_url, u)
        low = u.lower().split("?")[0]
        if any(low.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")):
            resolved.append(u)
            if len(resolved) >= 20: break
    logger.info(f"Scraped {len(resolved)} images from {page_url[:60]}...")
    _ref_cache[page_url] = (now, resolved)
    return resolved

def _get_random_ref_url(role_id="") -> str | None:
    folders = _get_role_ref_folders(role_id)
    all_images = []
    for url in folders:
        all_images.extend(_scrape_images_from_page(url))
    if not all_images:
        for urls in ROLE_REF_FOLDERS.values():
            for url in urls:
                all_images.extend(_scrape_images_from_page(url))
        if not all_images:
            return None
    return random.choice(all_images)

def _get_character_desc(role_name):
    for key, desc in CHARACTER_PREFIX.items():
        if key in role_name.lower() or role_name in key:
            return desc
    return DEFAULT_CHARACTER

_COMPOSITIONS = [
    "full body shot, standing pose, dynamic posture, detailed outfit, wide angle lens, environmental background, city street",
    "medium shot, waist up, natural pose, soft smile, bokeh background, outdoor cafe",
    "three-quarter body, sitting pose, casual elegance, indoor natural light, cozy room",
    "full body, walking pose, candid moment, street photography, urban background",
    "medium full shot, leaning pose, fashion editorial, dramatic lighting, architectural background",
    "wide shot, playful pose, outdoor park, golden hour sunlight, full outfit visible",
    "half body, over shoulder glance, moody atmosphere, window light, intimate framing",
    "full body, dynamic action pose, hair flowing, wind effect, nature background, scenic view",
    "kneeling pose, close-medium shot, soft focus background, delicate expression, detailed clothing",
    "full body portrait, confident stance, studio lighting, clean background, fashion catalog style",
    "three-quarter shot, relaxed sitting, reading or drinking, lifestyle photography, home interior",
    "wide environmental portrait, small figure in frame, atmospheric, storytelling composition",
]

def _get_composition():
    return random.choice(_COMPOSITIONS)

def _build_visual_prompt(text, role_id=""):
    role_name = ""
    if role_id:
        from roles import ROLES
        role = ROLES.get(role_id, {})
        role_name = role.get("name", "")
    char_desc = _get_character_desc(role_name)
    text = text.strip()[:300]
    quality = "high quality, photorealistic, soft natural lighting, detailed skin texture, perfect hands, detailed fingers, cinematic composition, 8k, masterpiece"
    return char_desc + ", " + quality + " -- same person as reference photo, identical face, identical features, cosplay photography, " + _get_composition() + " -- scene: " + text

async def generate_image(prompt, role_id=""):
    if not config.IMAGE_GEN_ENABLED:
        return None
    if not config.IMAGE_GEN_API_KEY:
        logger.warning("IMAGE_GEN_API_KEY not set, cannot generate image")
        return None

    visual_prompt = _build_visual_prompt(prompt, role_id)
    logger.info(f"Image gen requested for {role_id}, prompt: {prompt[:80]}...")

    ref_url = _get_random_ref_url(role_id)
    if not ref_url:
        logger.warning(f"No reference image available for {role_id}")
        return None

    try:
        result = await _agnes_img2img(visual_prompt, ref_url)
        if result:
            logger.info(f"Agnes img2img success: {len(result)} bytes")
            return result
        logger.warning("Agnes img2img returned no result")
    except Exception as e:
        logger.error(f"img2img exception: {type(e).__name__}: {e}")
    return None

async def _agnes_img2img(prompt: str, ref_url: str) -> bytes | None:
    payload = {
        "model": config.IMAGE_GEN_MODEL,
        "prompt": prompt,
        "image": ref_url,
        "n": 1,
        "size": config.IMAGE_GEN_SIZE,
        "response_format": "b64_json",
    }

    api_url = f"{config.IMAGE_GEN_BASE_URL}/images/generations"
    logger.info(f"Agnes img2img: ref {ref_url[:60]}...")

    try:
        async with httpx.AsyncClient(timeout=GEN_TIMEOUT, follow_redirects=True) as client:
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
                images = data.get("data", [])
                if images:
                    b64 = images[0].get("b64_json", "")
                    if b64:
                        img_bytes = base64.b64decode(b64)
                        logger.info(f"Agnes img2img: {len(img_bytes)} bytes")
                        return img_bytes
                    url = images[0].get("url", "")
                    if url:
                        dl_resp = await client.get(url)
                        if dl_resp.status_code == 200:
                            logger.info(f"Agnes img2img: {len(dl_resp.content)} bytes (URL)")
                            return dl_resp.content
                logger.warning(f"Agnes empty response: {resp.text[:200]}")
            elif resp.status_code == 429:
                logger.error("Agnes rate limited (429)")
            else:
                logger.warning(f"Agnes HTTP {resp.status_code}: {resp.text[:300]}")
    except httpx.TimeoutException:
        logger.error("Agnes img2img timeout")
    except Exception as e:
        logger.error(f"Agnes img2img error: {type(e).__name__}: {e}")
    return None

def _extract_visual_prompt(reply_text, role_name=""):
    return _build_visual_prompt(reply_text, role_name)

