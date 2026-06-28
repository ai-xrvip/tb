"""
Image generation via Pollinations.ai (free, unlimited, no censorship).
Supports img2img with reference photos from media/<role_id>/参考图/.
"""
import os
import base64
import random
import urllib.parse
import httpx
from pathlib import Path
from config import config
from utils.logger import logger

POLLINATIONS_URL = "https://image.pollinations.ai/prompt"
GEN_TIMEOUT = 45


# Fixed character visual descriptions (NOT role names - these describe appearance)
CHARACTER_PREFIX = {
    "xiaolu": "cute young Asian woman, sweet smile, cosplayer, JK uniform, twin tails, soft makeup, fair skin",
    "linxi": "elegant Asian woman, OL outfit, high heels, sharp eyes, mature beauty, black hair, red lips",
    "mia": "innocent Asian woman, sundress, long wavy hair, doe eyes, natural makeup, soft lighting",
    "sunian": "gentle Asian woman, traditional hanfu, classical beauty, long black hair, elegant posture",
}

DEFAULT_CHARACTER = "beautiful young Asian woman, cute face, charming smile, trendy fashion, natural makeup"


def _get_character_desc(role_name: str) -> str:
    """Get the visual character description, NOT the role name."""
    for key, desc in CHARACTER_PREFIX.items():
        if key in role_name.lower() or role_name in key:
            return desc
    return DEFAULT_CHARACTER


def _get_reference_b64(role_id: str) -> str | None:
    """Get base64-encoded reference photo for img2img."""
    media_base = Path(__file__).parent / "media" / role_id
    ref_dir = media_base / "参考图"
    if not ref_dir.is_dir():
        return None

    refs = [p for p in ref_dir.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    if not refs:
        return None

    ref_path = random.choice(refs)
    try:
        with open(ref_path, "rb") as f:
            data = f.read()
        if len(data) > 300_000:  # Too large, skip
            return None
        return base64.b64encode(data).decode("ascii")
    except Exception as e:
        logger.error("Failed to read reference: " + str(e))
        return None


def _build_visual_prompt(text: str, role_name: str = "") -> str:
    """Build visual prompt with fixed character description + scene from AI reply."""
    char_desc = _get_character_desc(role_name)
    text = text.strip()[:300]
    quality = (
        "high quality, photorealistic, soft natural lighting, "
        "detailed skin texture, cinematic composition, 8k, masterpiece"
    )
    return char_desc + ", " + quality + " -- scene: " + text


async def generate_image(prompt: str, role_name: str = "") -> bytes | None:
    """Generate image from text using Pollinations.ai img2img."""
    if not config.IMAGE_GEN_ENABLED:
        return None

    visual_prompt = _build_visual_prompt(prompt, role_name)

    # Try with reference photo first (img2img)
    ref_b64 = _get_reference_b64(role_name)
    if ref_b64:
        result = await _pollinations_img2img(visual_prompt, ref_b64)
        if result:
            return result

    # Fallback: text-to-image without reference
    result = await _pollinations_txt2img(visual_prompt)
    if result:
        return result

    # Last resort: OpenAI API if configured
    if config.IMAGE_GEN_API_KEY:
        result = await _openai_gen(visual_prompt)
        if result:
            return result

    return None


async def _pollinations_img2img(prompt: str, ref_b64: str) -> bytes | None:
    """Generate via Pollinations.ai with reference image."""
    try:
        encoded = urllib.parse.quote(prompt, safe="")
        ref_uri = "data:image/jpeg;base64," + ref_b64
        url = (
            POLLINATIONS_URL + "/" + encoded
            + "?image=" + urllib.parse.quote(ref_uri, safe="")
            + "&strength=0.5&nologo=true&width=1024&height=1024"
        )
        async with httpx.AsyncClient(timeout=GEN_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) > 500:
                logger.info("Pollinations img2img: " + str(len(resp.content)) + " bytes")
                return resp.content
            else:
                logger.warning("Pollinations img2img failed: HTTP " + str(resp.status_code))
    except httpx.TimeoutException:
        logger.error("Pollinations img2img timeout")
    except Exception as e:
        logger.error("Pollinations img2img error: " + str(e))
    return None


async def _pollinations_txt2img(prompt: str) -> bytes | None:
    """Generate via Pollinations.ai text-to-image (no reference)."""
    try:
        encoded = urllib.parse.quote(prompt, safe="")
        url = POLLINATIONS_URL + "/" + encoded + "?nologo=true&width=1024&height=1024"
        async with httpx.AsyncClient(timeout=GEN_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) > 500:
                logger.info("Pollinations txt2img: " + str(len(resp.content)) + " bytes")
                return resp.content
            else:
                logger.warning("Pollinations txt2img failed: HTTP " + str(resp.status_code))
    except Exception as e:
        logger.error("Pollinations txt2img error: " + str(e))
    return None


async def _openai_gen(prompt: str) -> bytes | None:
    """Generate via OpenAI-compatible API (fallback)."""
    try:
        async with httpx.AsyncClient(timeout=GEN_TIMEOUT) as client:
            resp = await client.post(
                config.IMAGE_GEN_BASE_URL + "/images/generations",
                headers={
                    "Authorization": "Bearer " + config.IMAGE_GEN_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.IMAGE_GEN_MODEL,
                    "prompt": prompt,
                    "n": 1,
                    "size": config.IMAGE_GEN_SIZE,
                    "response_format": "b64_json",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                images = data.get("data", [])
                if images and "b64_json" in images[0]:
                    return base64.b64decode(images[0]["b64_json"])
            else:
                logger.warning("OpenAI image API: " + str(resp.status_code))
    except Exception as e:
        logger.error("OpenAI image error: " + str(e))
    return None


def _extract_visual_prompt(reply_text, role_name=""):
    return _build_visual_prompt(reply_text, role_name)
