'''
Image generation via Pollinations.ai (free, unlimited, no censorship).
Supports img2img with reference photos from refs/<role_id>/.
FORCE IMG2IMG ONLY - no txt2img fallback.
'''
import os
import base64
import random
import urllib.request
import urllib.parse
import httpx
from pathlib import Path
from config import config
from utils.logger import logger

POLLINATIONS_URL = 'https://image.pollinations.ai/prompt'
GEN_TIMEOUT = 45


# Fixed character visual descriptions (NOT role names - these describe appearance)
CHARACTER_PREFIX = {
    'xiaolu': 'cute young Asian woman, sweet smile, cosplayer, JK uniform, twin tails, soft makeup, fair skin',
    'linxi': 'elegant Asian woman, OL outfit, high heels, sharp eyes, mature beauty, black hair, red lips',
    'mia': 'innocent Asian woman, sundress, long wavy hair, doe eyes, natural makeup, soft lighting',
    'sunian': 'gentle Asian woman, traditional hanfu, classical beauty, long black hair, elegant posture',
}

DEFAULT_CHARACTER = 'beautiful young Asian woman, cute face, charming smile, trendy fashion, natural makeup'


def _get_character_desc(role_name: str) -> str:
    '''Get the visual character description, NOT the role name.'''
    for key, desc in CHARACTER_PREFIX.items():
        if key in role_name.lower() or role_name in key:
            return desc
    return DEFAULT_CHARACTER

# CDN base URL for reference photos (GitHub raw)
_REF_CDN_BASE = 'https://raw.githubusercontent.com/ai-xrvip/tb/main/refs'

# Per-role reference photo manifest (ALL 30 roles)
_REF_MANIFEST: dict[str, list[str]] = {
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
    'xiaolu': ['201.jpg', '279.jpg'],
    'yui': ['reference.jpg'],
    'yuki': ['reference.jpg'],
    'yuna': ['reference.jpg'],
}
_DEFAULT_REF_FILE = 'reference.jpg'


def _get_reference_urls(role_id: str) -> list[str]:
    '''Get CDN URLs for a role reference photos.'''
    filenames = _REF_MANIFEST.get(role_id, [_DEFAULT_REF_FILE])
    return [f'{_REF_CDN_BASE}/{role_id}/{fn}' for fn in filenames]


def _get_reference_b64(role_id: str) -> str | None:
    '''Get base64-encoded reference photo (CDN first, local fallback).'''
    # Try CDN first
    urls = _get_reference_urls(role_id)
    random.shuffle(urls)
    logger.info(f'Trying {len(urls)} reference URLs for role {role_id}')
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Bot/1.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            if resp.status == 200 and len(data) > 500 and len(data) < 300_000:
                logger.info(f'Reference loaded from CDN: {url} ({len(data)} bytes)')
                return base64.b64encode(data).decode('ascii')
            else:
                logger.warning(f'CDN ref {url}: status={resp.status} size={len(data)}')
        except Exception:
            continue

    # Fallback: local refs/<role_id>/
    local_base = Path(__file__).parent / 'refs' / role_id
    if local_base.is_dir():
        refs = [p for p in local_base.glob('*') if p.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')]
        if refs:
            ref_path = random.choice(refs)
            try:
                with open(ref_path, 'rb') as f:
                    data = f.read()
                if 500 < len(data) <= 300_000:
                    logger.info(f'Reference loaded from local: {ref_path} ({len(data)} bytes)')
                    return base64.b64encode(data).decode('ascii')
            except Exception as e:
                logger.error('Failed to read local ref: ' + str(e))

    return None


def _build_visual_prompt(text: str, role_id: str = '') -> str:
    '''Build visual prompt with fixed character description + scene from AI reply.'''
    role_name = ''
    if role_id:
        from roles import ROLES
        role = ROLES.get(role_id, {})
        role_name = role.get('name', '')
    char_desc = _get_character_desc(role_name)
    text = text.strip()[:300]
    quality = (
        'high quality, photorealistic, soft natural lighting, '
        'detailed skin texture, cinematic composition, 8k, masterpiece'
    )
    return char_desc + ', ' + quality + ' -- scene: ' + text


async def generate_image(prompt: str, role_id: str = '') -> bytes | None:
    '''Generate image using Pollinations.ai img2img ONLY (no txt2img fallback).'''
    if not config.IMAGE_GEN_ENABLED:
        logger.debug('Image gen disabled by config')
        return None

    visual_prompt = _build_visual_prompt(prompt, role_id)
    logger.info(f'Image gen requested for {role_id}, prompt: {prompt[:80]}...')

    # img2img ONLY - must have reference photo
    try:
        ref_b64 = _get_reference_b64(role_id)
        if not ref_b64:
            logger.warning(f'No reference photo available for {role_id}, img2img skipped')
            return None
        logger.info(f'img2img with reference ({len(ref_b64)} chars)')
        result = await _pollinations_img2img(visual_prompt, ref_b64)
        if result:
            logger.info(f'img2img success: {len(result)} bytes')
            return result
        logger.warning(f'img2img returned no result for {role_id}')
    except Exception as e:
        logger.error(f'img2img exception: {e}')

    return None


async def _pollinations_img2img(prompt: str, ref_b64: str) -> bytes | None:
    '''Generate via Pollinations.ai with reference image.'''
    try:
        encoded = urllib.parse.quote(prompt, safe='')
        ref_uri = 'data:image/jpeg;base64,' + ref_b64
        url = (
            POLLINATIONS_URL + '/' + encoded
            + '?image=' + urllib.parse.quote(ref_uri, safe='')
            + '&strength=0.75&nologo=true&width=1024&height=1024'
        )
        async with httpx.AsyncClient(timeout=GEN_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) > 500:
                logger.info('Pollinations img2img: ' + str(len(resp.content)) + ' bytes')
                return resp.content
            else:
                logger.warning('Pollinations img2img failed: HTTP ' + str(resp.status_code))
    except httpx.TimeoutException:
        logger.error('Pollinations img2img timeout')
    except Exception as e:
        logger.error('Pollinations img2img error: ' + str(e))
    return None


def _extract_visual_prompt(reply_text, role_name=''):
    return _build_visual_prompt(reply_text, role_name)
