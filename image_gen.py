# Image generation - Agnes AI img2img
# IMAGE_REF_{ROLE} = a page URL containing images, randomly picks one as reference.
import base64, json, os, random, re, time, urllib.parse
import httpx
from config import config
from utils.logger import logger
from utils.web_scrape import pick_random_ref as _pick_ref

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

_ROLE_CHARACTER_V2 = {
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

# For backward compatibility, reference the shared dict
_ROLE_CHARACTER = _ROLE_CHARACTER_V2

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




def _build_visual_prompt(text: str, role_id: str = "") -> str:
    """Build img2img prompt. Reference image handles identity. Only add quality tags — NO character description."""
    text = text.strip()[:400]
    quality = "same person as reference photo, photorealistic, 8k, masterpiece, perfect hands, soft lighting"
    return f"{quality} -- scene: {text}"



async def translate_to_img_prompt(user_text: str, ai_reply: str) -> str:
    """Combine user request + AI reply into a short English img2img scene prompt.
    Reference image handles the person's identity, so the prompt should ONLY describe:
    clothing, pose, setting, lighting, camera angle. Do NOT describe face/identity."""
    import httpx
    prompt_msg = f"""Translate this conversation into a short English img2img prompt (max 40 words).
Describe ONLY: clothing/outfit (be specific!), pose, setting, lighting, camera distance (full-body/half-body/close-up).
CRITICAL: Do NOT describe the person's face, race, hair, or identity — the reference photo handles that.
If the user requests specific clothing (e.g. stockings, swimsuit, camisole), INCLUDE it in the prompt.
Output ONLY the prompt text, no explanations.

User said: {user_text}
AI replied: {ai_reply}

English prompt:"""
    try:
        api_key = config.DEEPSEEK_API_KEY
        if not api_key:
            return ai_reply[:400]
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt_msg}],
                    "max_tokens": 120,
                    "temperature": 0.3,
                },
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                result = resp.json()["choices"][0]["message"]["content"].strip()
                logger.info(f"Translated prompt: {result[:100]}")
                return result
    except Exception as e:
        logger.error(f"Prompt translation failed: {e}")
    return ai_reply[:400]


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
        "guidance_scale": 18,
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
