# Image generation - Agnes AI img2img
# IMAGE_REF_{ROLE} = a page URL containing images, randomly picks one as reference.
import base64, json, os, random, re, time, urllib.parse
import httpx
from config import config
from utils.logger import logger

GEN_TIMEOUT = 120
_REF_CACHE = {}
_CACHE_TTL = 600

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

_ROLE_CHARACTER = {
    "xiaolu": "cute young Asian woman, sweet smile, cosplayer, JK uniform, twin tails, soft makeup, fair skin, perfect hands, slender fingers",
    "linxi": "beautiful Chinese woman, elegant and professional, dark suit, high ponytail, sharp eyes, CEO aura, tall and slender, fair skin, perfect hands",
    "mia": "sporty Chinese-American woman, athletic build, ponytail, yoga wear, happy smile, muscular legs, abs, perfect hands, fit body",
    "sunian": "graceful Chinese woman, gentle eyes, long wavy hair, linen dress, artistic temperament, slender figure, pale skin, perfect hands",
    "yuki": "delicate Chinese girl, soft features, hanfu style, long straight black hair, porcelain skin, elegant posture, gentle smile, perfect hands",
    "reina": "wealthy Japanese-Chinese young woman, designer clothes, luxury handbag, elegant jewelry, perfect makeup, long hair, tsundere look, perfect hands",
    "chiyo": "gentle Chinese woman, apron over casual clothes, warm smile, slightly tired eyes, full figure, caring expression, perfect hands",
    "nana": "fun Chinese girl, gaming headset, casual hoodie, short skirt, playful smile, colorful hair tips, energetic look, perfect hands",
    "mizuki": "powerful Chinese CEO woman, sharp business suit, high heels, cold expression, elegant updo, intimidating aura, perfect hands",
    "akari": "cute Chinese nurse, white uniform, gentle smile, natural makeup, round glasses, soft features, cute face, perfect hands",
    "yuna": "tall Chinese fashion model, runway walk, designer clothes, perfect figure, long legs, elegant pose, high cheekbones, perfect hands",
    "shiori": "introspective Chinese girl, glasses, book in hand, scholarly appearance, long braid, soft expression, vintage cardigan, perfect hands",
    "sora": "elegant Chinese flight attendant, airline uniform, professional smile, perfect posture, gentle eyes, hair in bun, warm expression, perfect hands",
    "kaede": "strong Chinese policewoman, uniform, sharp eyes, athletic build, short hair, confident stance, hand on belt, perfect hands",
    "ruri": "sharp Chinese lawyer, business suit, tote bag, confident expression, glasses, sleek bun, elegant heels, perfect hands",
    "ren": "mysterious Chinese bartender, elegant black dress, cocktail shaker, smoky eyes, confident smile, long hair, perfect hands",
    "hana": "gentle Chinese florist, flower crown, linen apron, soft smile, tanned skin, natural look, earthy tones, perfect hands",
    "mai": "elegant Chinese ballet dancer, leotard, tutu, pointe shoes, graceful posture, bun, delicate features, intense eyes, perfect hands",
    "momo": "sweet Taiwanese dessert chef, cute apron, flour on cheek, big eyes, short hair, happy expression, holding whisk, perfect hands",
    "sakura": "gentle Chinese veterinarian, white coat, stethoscope, warm smile, soft eyes, animal prints, caring hands, perfect hands",
    "aya": "efficient Chinese secretary, office suit, glasses, smart bun, typing pose, professional smile, perfect posture, perfect hands",
    "mei": "creative Chinese musician, guitar over shoulder, bohemian dress, artistic look, messy bun, creative expression, perfect hands",
    "koharu": "adventurous Chinese photographer, camera around neck, safari vest, rugged boots, sun-kissed skin, free spirit, perfect hands",
    "tsubaki": "determined Chinese journalist, trench coat, notepad, determined eyes, sharp suit, urban professional, perfect hands",
    "rio": "cool Chinese female racer, racing suit, helmet under arm, confident walk, lean athletic build, focused eyes, perfect hands",
    "nozomi": "cute Chinese voice actress, microphone, headphones, cosplay accessories, expressive face, playful eyes, perfect hands",
    "nami": "free-spirited Chinese surfer girl, wetsuit, surfboard, tan skin, wet hair, bikini top, strong arms, perfect hands",
    "fumi": "quiet Chinese librarian, vintage cardigan, glasses, book under arm, serene expression, soft features, perfect hands",
    "eri": "smart Chinese AI researcher, hoodie, glasses, laptop, messy ponytail, focused expression, lab coat, perfect hands",
    "yui": "cute Chinese maid cafe girl, maid uniform, cat ears, holding coffee tray, bright smile, bow in hair, perfect hands",
}

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

    img_urls = re.findall(r'<img[^>]+src="([^"]+)"', html, re.IGNORECASE)
    img_urls += re.findall(r'!\[.*?\]\(([^)]+)\)', html)

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


def _build_visual_prompt(text: str, role_id: str = "") -> str:
    text = text.strip()[:400]
    quality = "high quality, photorealistic, soft natural lighting, detailed skin texture, perfect hands, detailed fingers, cinematic composition, 8k, masterpiece"
    return quality + ", " + random.choice(_COMPOSITIONS) + " -- scene: " + text


async def generate_image(prompt: str, role_id: str = "", page_url: str = "") -> bytes | None:
    """Generate via Agnes img2img only. Requires reference image URL."""
    if not config.IMAGE_GEN_ENABLED:
        return None
    if not config.IMAGE_GEN_API_KEY:
        logger.warning("IMAGE_GEN_API_KEY not set")
        return None
    if not page_url:
        page_url = config.get_image_ref(role_id)
    if not page_url:
        logger.warning(f"No image page URL for role={role_id}")
        return None

    ref_url = await _pick_ref(page_url)
    if not ref_url:
        logger.warning(f"No images found on {page_url[:60]}")
        return None

    visual_prompt = _build_visual_prompt(prompt, role_id)
    logger.info(f"Image gen [img2img]: role={role_id} prompt={prompt[:80]}...")
    return await _call_agnes_api(visual_prompt, ref_url)


async def _call_agnes_api(prompt: str, ref_url: str) -> bytes | None:
    payload = {
        "model": config.IMAGE_GEN_MODEL,
        "prompt": prompt,
        "negative_prompt": NEGATIVE_PROMPT,
        "image": ref_url,
        "n": 1,
        "size": config.IMAGE_GEN_SIZE,
    }

    api_url = f"{config.IMAGE_GEN_BASE_URL}/images/generations"
    logger.info(f"Agnes img2img: ref={ref_url[:60]}...")

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
                    url = images[0].get("url", "")
                    if url:
                        dl_resp = await client.get(url)
                        if dl_resp.status_code == 200:
                            logger.info(f"Agnes img2img: {len(dl_resp.content)} bytes")
                            return dl_resp.content
                    b64 = images[0].get("b64_json", "")
                    if b64:
                        logger.info(f"Agnes img2img: {len(b64)} chars (b64)")
                        return base64.b64decode(b64)
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
