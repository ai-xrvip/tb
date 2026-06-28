"""
Image generation via Pollinations.ai (free, unlimited, no API key)
Supports img2img: use reference photo + AI description to generate consistent character images
"""
import asyncio
import base64
import random
import re
from pathlib import Path
from typing import Optional
import httpx
from utils.logger import logger

POLLINATIONS_URL = "https://image.pollinations.ai/prompt"
GEN_TIMEOUT = 30  # seconds


async def _pick_reference_photo(role_id: str) -> str | None:
    """Pick the best reference photo for this character. Prefers 参考图 folder."""
    media_base = Path(__file__).parent.parent / "media" / role_id
    if not media_base.exists():
        return None

    # Priority 1: 参考图 folder
    ref_dir = media_base / "参考图"
    if ref_dir.is_dir():
        refs = [p for p in ref_dir.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
        if refs:
            return str(random.choice(refs))

    # Priority 2: Any image from any folder
    for folder in media_base.iterdir():
        if folder.is_dir():
            imgs = [p for p in folder.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
            if imgs:
                return str(random.choice(imgs))
    return None


def _extract_visual_prompt(reply_text: str, role_name: str = "") -> str:
    """Extract the most visual description from AI reply for image generation."""
    # Remove [media:xxx] tags
    clean = re.sub(r'\[media:[^\]]+\]', '', reply_text).strip()
    # Remove emoji-heavy lines and keep descriptive sentences
    sentences = re.split(r'[。！？\n!?]', clean)
    visual_keywords = ['穿', '戴', '在', '去', '坐', '站', '躺', '拍', '泳', '裙', '衣', '照', '装', 'JK', '丝袜', '运动', 'cos', '游泳', '健身', '约会', '出门', '海边', '家里']
    best = ""
    best_score = 0
    for s in sentences:
        s = s.strip()
        if len(s) < 5:
            continue
        score = sum(2 for kw in visual_keywords if kw in s)
        if score > best_score:
            best_score = score
            best = s
    if not best:
        best = clean.split("。")[0].strip()
    # Add quality prompt
    if role_name:
        best = f"{role_name}, {best}"
    return best + ", high quality, photorealistic, soft lighting, cute"


async def generate_image(reply_text: str, role_id: str, role_name: str = "") -> bytes | None:
    """
    Generate an image using Pollinations.ai img2img.
    1. Pick reference photo for this character
    2. Extract visual prompt from AI's reply
    3. Call Pollinations with reference + prompt
    """
    ref_path = await _pick_reference_photo(role_id)
    if not ref_path:
        logger.warning(f"No reference photo for {role_id}, skipping img2img")
        return None

    # Read and encode reference photo
    try:
        with open(ref_path, "rb") as f:
            ref_bytes = f.read()
        ref_b64 = base64.b64encode(ref_bytes).decode("ascii")
    except Exception as e:
        logger.error(f"Failed to read reference photo {ref_path}: {e}")
        return None

    # Build prompt
    prompt = _extract_visual_prompt(reply_text, role_name)
    logger.info(f"Img2img prompt: {prompt[:100]}")

    # Build URL with reference image as base64 data URI
    ref_uri = f"data:image/jpeg;base64,{ref_b64}"
    url = f"{POLLINATIONS_URL}/{prompt}?image={ref_uri}&strength=0.5&nologo=true"

    try:
        async with httpx.AsyncClient(timeout=GEN_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) > 500:
                logger.info(f"Img2img generated: {len(resp.content)} bytes")
                return resp.content
            else:
                logger.warning(f"Img2img failed: HTTP {resp.status_code}, size={len(resp.content)}")
    except httpx.TimeoutException:
        logger.error("Img2img timeout")
    except Exception as e:
        logger.error(f"Img2img error: {e}")

    return None
