"""
Image generation via Pollinations.ai (free, unlimited, no censorship).
Also supports optional OpenAI-compatible API as fallback.
"""
import base64
import random
import urllib.parse
import httpx
from pathlib import Path
from config import config
from utils.logger import logger

POLLINATIONS_URL = "https://image.pollinations.ai/prompt"
GEN_TIMEOUT = 45
REF_CACHE = {}


async def _pick_reference_photo(role_id):
    media_base = Path(__file__).parent / "media" / role_id
    ref_dir = media_base / "参考图"
    if ref_dir.is_dir():
        refs = [p for p in ref_dir.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
        if refs:
            return str(random.choice(refs))
    return None


def _build_visual_prompt(text, role_name=""):
    text = text.strip()[:400]
    base = (
        "high quality, photorealistic, soft natural lighting, "
        "beautiful Asian young woman, cute and charming, detailed skin, "
        "cinematic composition, 8k, masterpiece"
    )
    if role_name:
        base = role_name + ", " + base
    return base + " -- " + text


async def generate_image(prompt, role_name=""):
    if not config.IMAGE_GEN_ENABLED:
        return None
    visual_prompt = _build_visual_prompt(prompt, role_name)
    result = await _pollinations_gen(visual_prompt)
    if result:
        return result
    if config.IMAGE_GEN_API_KEY:
        result = await _openai_gen(visual_prompt)
        if result:
            return result
    return None


async def _pollinations_gen(prompt):
    try:
        encoded = urllib.parse.quote(prompt, safe="")
        url = POLLINATIONS_URL + "/" + encoded + "?nologo=true&width=1024&height=1024"
        async with httpx.AsyncClient(timeout=GEN_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) > 500:
                logger.info("Pollinations generated: " + str(len(resp.content)) + " bytes")
                return resp.content
            else:
                logger.warning("Pollinations failed: HTTP " + str(resp.status_code))
    except httpx.TimeoutException:
        logger.error("Pollinations timeout")
    except Exception as e:
        logger.error("Pollinations error: " + str(e))
    return None


async def _openai_gen(prompt):
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
