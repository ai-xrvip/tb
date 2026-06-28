# Image generation - Multi-provider: Hugging Face (primary) or Pollinations (fallback)
# Reference images scraped from per-role folder/page URLs (Telegraph, ImgBB, etc.)
import os, re, time, random, base64, urllib.request, urllib.parse, httpx
from config import config
from utils.logger import logger

POLLINATIONS_URL = 'https://image.pollinations.ai/prompt'
GEN_TIMEOUT = 90

# ── Negative prompt ──
NEGATIVE_PROMPT = (
    'bad hands, ugly hands, missing fingers, extra fingers, fused fingers, '
    'poorly drawn hands, deformed hands, mutated hands, disfigured fingers, '
    'bad anatomy, deformed anatomy, disfigured, mutated, extra limbs, '
    'blurry, low quality, jpeg artifacts, watermark, text, signature, '
    'ugly face, asymmetric eyes, distorted face, deformed face, '
    'bad proportions, long neck, cloned face, double face, '
    'worst quality, lowres, error, cropped, out of frame, '
    'poorly drawn feet, bad feet, extra toes, missing toes'
)

CHARACTER_PREFIX = {
    'xiaolu': 'cute young Asian woman, sweet smile, cosplayer, JK uniform, twin tails, soft makeup, fair skin, perfect hands, slender fingers',
    'linxi': 'elegant Asian woman, OL outfit, high heels, sharp eyes, mature beauty, black hair, red lips, perfect hands',
    'mia': 'innocent Asian woman, sundress, long wavy hair, doe eyes, natural makeup, soft lighting, perfect hands',
    'sunian': 'gentle Asian woman, traditional hanfu, classical beauty, long black hair, elegant posture, perfect hands, delicate fingers',
}
DEFAULT_CHARACTER = 'beautiful young Asian woman, cute face, charming smile, trendy fashion, natural makeup, perfect hands'

ROLE_NEGATIVES = {
    'xiaolu': 'nsfw, nude, revealing, skimpy, lingerie, bikini, muscular, tall',
}

# ── Hugging Face config (free tier, ~30s cold start) ──
# Get free token at https://huggingface.co/settings/tokens
HF_TOKEN = os.getenv('HF_TOKEN', '')
HF_IMG2IMG_MODEL = os.getenv('HF_IMG2IMG_MODEL', 'stabilityai/stable-diffusion-xl-base-1.0')

# ── Per-role reference image folders ──
ROLE_REF_FOLDERS = {
    'xiaolu': ['https://telegra.ph/miko3%E5%A4%8D%E6%B4%BB%E7%89%88-06-27'],
}

def _get_role_ref_folders(role_id):
    env_key = f'IMAGE_REF_FOLDERS_{role_id.upper()}'
    env_val = os.getenv(env_key, '')
    if env_val:
        return [u.strip() for u in env_val.split(',') if u.strip()]
    return ROLE_REF_FOLDERS.get(role_id, [])

# Cache: {page_url: (timestamp, [image_urls])}
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
        resp = client.get(page_url, headers={'User-Agent': 'Bot/1.0'})
        if resp.status_code != 200:
            return []
        html = resp.text
    except Exception:
        return []

    img_urls = re.findall(r'<img[^>]+src=[\"\x27]([^\"\x27]+)[\"\x27]', html, re.IGNORECASE)
    if not img_urls:
        img_urls = re.findall(r'!\[.*?\]\(([^)]+)\)', html)

    parsed_base = urllib.parse.urlparse(page_url)
    base_host = f'{parsed_base.scheme}://{parsed_base.hostname}'

    resolved = []
    for u in img_urls:
        if u.startswith('/'):
            u = base_host + u
        elif u.startswith('//'):
            u = 'https:' + u
        elif u.startswith('data:'):
            continue
        elif not u.startswith('http'):
            u = urllib.parse.urljoin(page_url, u)
        low = u.lower().split('?')[0]
        if any(low.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')):
            resolved.append(u)
            if len(resolved) >= 20:
                break

    logger.info(f'Scraped {len(resolved)} images from {page_url[:60]}...')
    _ref_cache[page_url] = (now, resolved)
    return resolved

def _get_random_ref_url(role_id='') -> str | None:
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

def _get_negative_prompt(role_id=''):
    base = NEGATIVE_PROMPT
    extra = ROLE_NEGATIVES.get(role_id, '')
    return base + ', ' + extra if extra else base

def _build_visual_prompt(text, role_id=''):
    role_name = ''
    if role_id:
        from roles import ROLES
        role = ROLES.get(role_id, {})
        role_name = role.get('name', '')
    char_desc = _get_character_desc(role_name)
    text = text.strip()[:300]
    quality = 'high quality, photorealistic, soft natural lighting, detailed skin texture, perfect hands, detailed fingers, cinematic composition, 8k, masterpiece'
    return char_desc + ', ' + quality + ' -- same person as reference photo, identical face, identical features, cosplay photography -- scene: ' + text

async def generate_image(prompt, role_id=''):
    if not config.IMAGE_GEN_ENABLED:
        return None
    visual_prompt = _build_visual_prompt(prompt, role_id)
    negative = _get_negative_prompt(role_id)
    logger.info(f'Image gen requested for {role_id}, prompt: {prompt[:80]}...')

    ref_url = _get_random_ref_url(role_id)
    if not ref_url:
        logger.warning(f'No reference image available for {role_id}')
        return None

    try:
        # 1) Try Hugging Face img2img (free, better quality)
        if HF_TOKEN:
            logger.info(f'Trying HF img2img for {role_id}')
            result = await _hf_img2img(visual_prompt, ref_url, negative)
            if result:
                logger.info(f'HF img2img success: {len(result)} bytes')
                return result
            logger.warning('HF img2img failed, falling back to Pollinations')

        # 2) Fallback: Pollinations
        logger.info(f'img2img with Pollinations, ref: {ref_url[:80]}...')
        result = await _pollinations_img2img(visual_prompt, ref_url, negative)
        if result:
            logger.info(f'Pollinations img2img success: {len(result)} bytes')
            return result
        logger.warning(f'Pollinations img2img returned no result for {role_id}')
    except Exception as e:
        logger.error(f'img2img exception: {e}')
    return None

# ── Hugging Face Serverless Inference (free tier) ──

async def _hf_img2img(prompt: str, ref_url: str, negative: str) -> bytes | None:
    """Hugging Face img2img via Serverless Inference API (free, ~30s cold start)."""
    try:
        # Download reference image
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as dl:
            ref_resp = await dl.get(ref_url, headers={'User-Agent': 'Bot/1.0'})
            if ref_resp.status_code != 200 or len(ref_resp.content) < 500:
                logger.warning(f'HF: cannot download ref from {ref_url[:60]}')
                return None
            ref_bytes = ref_resp.content
            ref_b64 = base64.b64encode(ref_bytes).decode('utf-8')

        api_url = f'https://api-inference.huggingface.co/models/{HF_IMG2IMG_MODEL}'
        payload = {
            'inputs': prompt,
            'parameters': {
                'negative_prompt': negative,
                'image': ref_b64,
                'strength': 0.35,  # lower = closer to reference
                'guidance_scale': 7.5,
                'num_inference_steps': 30,
            }
        }

        async with httpx.AsyncClient(timeout=GEN_TIMEOUT, follow_redirects=True) as client:
            resp = await client.post(
                api_url,
                json=payload,
                headers={
                    'Authorization': f'Bearer {HF_TOKEN}',
                    'Content-Type': 'application/json',
                },
            )

            if resp.status_code == 200 and len(resp.content) > 500:
                content_type = resp.headers.get('content-type', '')
                if 'image' in content_type or resp.content[:4].hex() in ('89504e47', 'ffd8ffe0', '52494646', 'ffd8ffe1'):
                    logger.info(f'HF img2img: {len(resp.content)} bytes, model={HF_IMG2IMG_MODEL}')
                    return resp.content
                else:
                    logger.warning(f'HF returned non-image: {content_type}, body={resp.text[:200]}')
            elif resp.status_code == 503:
                logger.info('HF model loading (cold start), will retry next time')
            else:
                logger.warning(f'HF img2img HTTP {resp.status_code}: {resp.text[:200]}')
    except httpx.TimeoutException:
        logger.error('HF img2img timeout')
    except Exception as e:
        logger.error(f'HF img2img error: {type(e).__name__}: {e}')
    return None

# ── Pollinations (free fallback) ──

async def _pollinations_img2img(prompt, ref_url, negative=''):
    try:
        encoded = urllib.parse.quote(prompt, safe='')
        params = (
            '?image=' + urllib.parse.quote(ref_url, safe='')
            + '&strength=0.25&nologo=true&width=1024&height=1024'
            + '&seed=' + str(random.randint(1, 2147483647))
        )
        if negative:
            params += '&negative=' + urllib.parse.quote(negative, safe='')
        url = POLLINATIONS_URL + '/' + encoded + params
        logger.info(f'Pollinations URL: {len(url)} chars')
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) > 500:
                return resp.content
    except Exception as e:
        logger.error(f'Pollinations error: {e}')
    return None

def _extract_visual_prompt(reply_text, role_name=''):
    return _build_visual_prompt(reply_text, role_name)
