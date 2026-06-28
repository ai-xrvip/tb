"""
Image generation via OpenAI-compatible API (gpt-image-2 / DALL-E).
Call with AI reply text -> returns image bytes or None.
"""
import base64
import httpx
from config import config
from utils.logger import logger

GEN_TIMEOUT = 45


async def generate_image(prompt: str, role_name: str = "") -> bytes | None:
    """Generate image from text prompt via OpenAI-compatible API."""
    if not config.IMAGE_GEN_ENABLED or not config.IMAGE_GEN_API_KEY:
        return None

    # Build visual prompt from the text
    visual_prompt = _build_visual_prompt(prompt, role_name)

    try:
        async with httpx.AsyncClient(timeout=GEN_TIMEOUT) as client:
            resp = await client.post(
                f"{config.IMAGE_GEN_BASE_URL}/images/generations",
                headers={
                    "Authorization": f"Bearer {config.IMAGE_GEN_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.IMAGE_GEN_MODEL,
                    "prompt": visual_prompt,
                    "n": 1,
                    "size": config.IMAGE_GEN_SIZE,
                    "response_format": "b64_json",
                },
            )

            if resp.status_code == 200:
                data = resp.json()
                images = data.get("data", [])
                if images and "b64_json" in images[0]:
                    img_bytes = base64.b64decode(images[0]["b64_json"])
                    logger.info(f"Image generated: {len(img_bytes)} bytes")
                    return img_bytes
                # Some APIs return URL instead
                if images and "url" in images[0]:
                    url_resp = await client.get(images[0]["url"])
                    if url_resp.status_code == 200:
                        logger.info(f"Image downloaded: {len(url_resp.content)} bytes")
                        return url_resp.content
            else:
                logger.warning(f"Image API returned {resp.status_code}: {resp.text[:200]}")
    except httpx.TimeoutException:
        logger.error("Image generation timeout")
    except Exception as e:
        logger.error(f"Image generation error: {e}")

    return None


def _build_visual_prompt(text: str, role_name: str = "") -> str:
    """Build a visual prompt from the AI reply text."""
    # Keep it short and focused
    text = text.strip().replace("\n", " ")[:500]

    base = (
        "high quality, photorealistic, soft natural lighting, "
        "beautiful Asian young woman, cute and charming, "
        "trending on social media, detailed skin texture, "
        "cinematic composition, 8k"
    )

    if role_name:
        base = f"{role_name}, {base}"

    return f"{base} -- scene: {text}"


# Keep backward compatibility with old reference-based functions
REF_CACHE = {}

async def _pick_reference_photo(role_id: str) -> str | None:
    return None

def _extract_visual_prompt(reply_text: str, role_name: str = "") -> str:
    return _build_visual_prompt(reply_text, role_name)
