# Image generation via Pollinations.ai img2img using CDN reference URLs
import os, random, urllib.request, urllib.parse, httpx
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

# Per-role extra negative prompts (merged with global NEGATIVE_PROMPT)
ROLE_NEGATIVES = {
    'xiaolu': 'nsfw, nude, revealing, skimpy, lingerie, bikini, muscular, tall',
}

# Fallback reference URLs when GitHub CDN is unavailable (e.g. ImgBB / telegraph)
FALLBACK_REF_URLS = {}

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

_REF_CDN_BASE = 'https://raw.githubusercontent.com/ai-xrvip/tb/main/refs'

_REF_MANIFEST = {
    'akari': ['reference.jpg'],
    'aya': ['reference.jpg'],
    'chiyo': ['reference.jpg'],
    'eri': ['reference.jpg'],
    'fumi': ['reference.jpg'],
    'hana': ['reference.jpg'],
    'kaede': ['reference.jpg'],
    'koharu': ['reference.jpg'],
    'linxi': ['reference.jpg'],
    'mai': ['reference.jpg'],
    'mei': ['reference.jpg'],
    'mia': ['reference.jpg'],
    'mizuki': ['reference.jpg'],
    'momo': ['reference.jpg'],
    'nami': ['reference.jpg'],
    'nana': ['reference.jpg'],
    'nozomi': ['reference.jpg'],
    'reina': ['reference.jpg'],
    'ren': ['reference.jpg'],
    'rio': ['reference.jpg'],
    'ruri': ['reference.jpg'],
    'sakura': ['reference.jpg'],
    'shiori': ['reference.jpg'],
    'sora': ['reference.jpg'],
    'sunian': ['reference.jpg'],
    'tsubaki': ['reference.jpg'],
    'yui': ['reference.jpg'],
    'yuki': ['reference.jpg'],
    'yuna': ['reference.jpg'],
    'xiaolu': ['201.jpg', '279.jpg'],
}
_DEFAULT_REF_FILE = 'reference.jpg'

def _get_reference_urls(role_id):
    filenames = _REF_MANIFEST.get(role_id, [_DEFAULT_REF_FILE])
    return [f'{_REF_CDN_BASE}/{role_id}/{fn}' for fn in filenames]

def _get_reference_url(role_id):
    urls = _get_reference_urls(role_id)
    random.shuffle(urls)
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Bot/1.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200 and 500 < len(resp.read()) < 300_000:
                    logger.info(f'Reference CDN OK: {url}')
                    return url
        except Exception:
            continue
    return None

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
        ref_url = _get_reference_url(role_id)
        if not ref_url:
            fallback_url = FALLBACK_REF_URLS.get(role_id)
            if fallback_url:
                ref_url = fallback_url
                logger.info(f'Using fallback ref for {role_id}: {ref_url[:60]}...')
            else:
                logger.warning(f'No reference URL for {role_id}')
                return None
        logger.info(f'img2img with ref: {ref_url[:80]}...')
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
