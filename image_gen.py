# Image generation via Pollinations.ai img2img
# Reference images scraped from configurable folder/page URLs (Telegraph, ImgBB, etc.)
import os, re, time, random, urllib.request, urllib.parse, httpx
from pathlib import Path
from config import config
from utils.logger import logger

POLLINATIONS_URL = 'https://image.pollinations.ai/prompt'
GEN_TIMEOUT = 60

# ── Negative prompt: fix bad hands, anatomy, quality ──
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

# ── Reference image scraping from folder/page URLs ──

# Default: user-provided Telegraph folder. Set IMAGE_REF_FOLDERS env var to override/add.
_DEFAULT_REF_FOLDERS = [
    'https://telegra.ph/miko3%E5%A4%8D%E6%B4%BB%E7%89%88-06-27',
]
_REF_FOLDERS = os.getenv('IMAGE_REF_FOLDERS', '')
if _REF_FOLDERS:
    _REF_FOLDERS = [u.strip() for u in _REF_FOLDERS.split(',') if u.strip()]
else:
    _REF_FOLDERS = list(_DEFAULT_REF_FOLDERS)

# Cache: {page_url: (timestamp, [image_urls])}
_ref_cache = {}
_CACHE_TTL = 600  # 10 min, avoid re-scraping every request

def _scrape_images_from_page(page_url: str) -> list[str]:
    """Fetch a Telegraph/page URL and extract all image URLs."""
    now = time.time()
    if page_url in _ref_cache:
        ts, urls = _ref_cache[page_url]
        if now - ts < _CACHE_TTL and urls:
            return urls

    try:
        client = httpx.Client(timeout=15, follow_redirects=True)
        resp = client.get(page_url, headers={'User-Agent': 'Bot/1.0'})
        if resp.status_code != 200:
            logger.warning(f'Scrape {page_url}: HTTP {resp.status_code}')
            return []
        html = resp.text
    except Exception as e:
        logger.warning(f'Scrape {page_url} failed: {e}')
        return []

    # Extract <img src="...">
    img_urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if not img_urls:
        # Also try markdown image syntax: ![...](url)
        img_urls = re.findall(r'!\[.*?\]\(([^)]+)\)', html)

    parsed_base = urllib.parse.urlparse(page_url)
    base_host = f'{parsed_base.scheme}://{parsed_base.host}'

    resolved = []
    for u in img_urls:
        if u.startswith('/'):
            u = base_host + u
        elif u.startswith('//'):
            u = 'https:' + u
        elif u.startswith('data:'):
            continue  # skip data URIs
        elif not u.startswith('http'):
            u = urllib.parse.urljoin(page_url, u)

        # Only keep actual image URLs
        low = u.lower().split('?')[0]  # strip query params for extension check
        if any(low.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')):
            resolved.append(u)
            if len(resolved) >= 20:  # cap per page
                break

    logger.info(f'Scraped {len(resolved)} images from {page_url[:60]}...')
    _ref_cache[page_url] = (now, resolved)
    return resolved

def _get_all_scraped_images() -> list[str]:
    """Collect images from all configured folder URLs."""
    all_images = []
    for folder_url in _REF_FOLDERS:
        imgs = _scrape_images_from_page(folder_url)
        all_images.extend(imgs)
    return all_images

def _get_random_ref_url() -> str | None:
    """Pick a random image URL from scraped folders."""
    all_images = _get_all_scraped_images()
    if not all_images:
        logger.warning('No reference images scraped from any folder')
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
    if extra:
        return base + ', ' + extra
    return base

def _build_visual_prompt(text, role_id=''):
    role_name = ''
    if role_id:
        from roles import ROLES
        role = ROLES.get(role_id, {})
        role_name = role.get('name', '')
    char_desc = _get_character_desc(role_name)
    text = text.strip()[:300]
    quality = 'high quality, photorealistic, soft natural lighting, detailed skin texture, perfect hands, detailed fingers, cinematic composition, 8k, masterpiece'
    return char_desc + ', ' + quality + ' -- scene: ' + text

async def generate_image(prompt, role_id=''):
    if not config.IMAGE_GEN_ENABLED:
        return None
    visual_prompt = _build_visual_prompt(prompt, role_id)
    negative = _get_negative_prompt(role_id)
    logger.info(f'Image gen requested for {role_id}, prompt: {prompt[:80]}...')

    try:
        ref_url = _get_random_ref_url()
        if not ref_url:
            logger.warning(f'No reference image available for {role_id}')
            return None
        logger.info(f'img2img with random ref: {ref_url[:80]}...')
        result = await _pollinations_img2img(visual_prompt, ref_url, negative)
        if result:
            logger.info(f'img2img success: {len(result)} bytes')
            return result
        logger.warning(f'img2img returned no result for {role_id}')
    except Exception as e:
        logger.error(f'img2img exception: {e}')
    return None

async def _pollinations_img2img(prompt, ref_url, negative=''):
    try:
        encoded = urllib.parse.quote(prompt, safe='')
        params = (
            '?image=' + urllib.parse.quote(ref_url, safe='')
            + '&strength=0.75&nologo=true&width=1024&height=1024'
            + '&seed=' + str(random.randint(1, 2147483647))
        )
        if negative:
            params += '&negative=' + urllib.parse.quote(negative, safe='')
        url = POLLINATIONS_URL + '/' + encoded + params
        logger.info(f'img2img URL: {len(url)} chars, negative: {len(negative)} chars')
        async with httpx.AsyncClient(timeout=GEN_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) > 500:
                logger.info('Pollinations img2img: ' + str(len(resp.content)) + ' bytes')
                return resp.content
            else:
                logger.warning('Pollinations img2img failed: HTTP ' + str(resp.status_code) + ', body: ' + str(len(resp.content)) + ' bytes')
    except Exception as e:
        logger.error('Pollinations img2img error: ' + str(e))
    return None

def _extract_visual_prompt(reply_text, role_name=''):
    return _build_visual_prompt(reply_text, role_name)
