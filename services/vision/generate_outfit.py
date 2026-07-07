"""Outfit image generation — Pollinations.ai (free, no API key) → HF SDXL → placeholder.

Pollinations.ai is a free, open-source AI image generation service that requires
no API key, no account, and no rate limits for reasonable usage. It wraps Flux
models and returns high-quality fashion images via simple HTTP GET.

Fallback chain:
  1. Pollinations.ai (free, no key) — primary, most reliable
  2. HuggingFace SDXL (needs API key) — secondary
  3. Deterministic placeholder PNG — last resort
"""

import base64
import hashlib
import logging
import urllib.parse
from dataclasses import dataclass

import httpx

from services.api.core.config import get_settings
from services.api.core.resilience import hf_breaker

logger = logging.getLogger(__name__)


@dataclass
class OutfitVariant:
    image_base64: str
    prompt: str
    clip_score: float


@dataclass
class OutfitGenerationResult:
    variants: list[OutfitVariant]
    preview_ready_ms: int
    full_ready_ms: int


# Fashion-optimized prompt templates
_PROMPT_TEMPLATES = [
    "{brief}, high fashion editorial photography, studio lighting, full body, 4k, detailed fabric texture",
    "{brief}, Indian ethnic wear collection, vibrant colors, professional fashion shoot, bokeh background",
    "{brief}, fashion magazine cover style, elegant draping, rich embroidery detail, 8k quality",
    "{brief}, runway fashion presentation, dramatic lighting, detailed stitching, luxury fashion",
]


async def _pollinations_generate(prompt: str, width: int = 512, height: int = 768) -> bytes | None:
    """Generate image via Pollinations.ai — free, no API key needed.

    Uses a simple HTTP GET request. The service runs Flux models and returns
    a PNG image directly. Highly reliable with no authentication required.
    """
    # URL-encode the prompt for the GET request
    encoded_prompt = urllib.parse.quote(prompt, safe='')
    # Use a deterministic seed from the prompt for consistency
    seed = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % 999999
    url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        f"?width={width}&height={height}&seed={seed}&nologo=true&model=flux"
    )

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) > 1000:
                content_type = resp.headers.get("content-type", "")
                if "image" in content_type or len(resp.content) > 5000:
                    logger.info("[pollinations] Generated image: %d bytes", len(resp.content))
                    return resp.content
            logger.warning("[pollinations] Unexpected response: status=%d, size=%d",
                          resp.status_code, len(resp.content))
            return None
    except Exception as exc:
        logger.warning("[pollinations] Generation failed: %s", exc)
        return None


async def _hf_sdxl_generate(prompt: str, settings) -> bytes | None:
    """Call HF Inference API for SDXL image generation."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0",
            headers={"Authorization": f"Bearer {settings.huggingface_api_key}"},
            json={
                "inputs": prompt,
                "parameters": {
                    "num_inference_steps": 25,
                    "guidance_scale": 7.5,
                    "width": 512,
                    "height": 768,
                },
            },
        )
        if resp.status_code == 503:
            hf_breaker.fail()
            logger.info("HF SDXL model loading (cold start)")
            return None
        if resp.status_code == 429:
            hf_breaker.fail()
            logger.warning("HF rate limited")
            return None
        if resp.status_code != 200:
            logger.warning("HF SDXL returned %d: %s", resp.status_code, resp.text[:200])
            return None
        hf_breaker.success()
        return resp.content


def _placeholder_png_base64(seed: str) -> str:
    """Generate a deterministic placeholder fashion preview PNG."""
    from PIL import Image, ImageDraw

    import io

    hue = int(seed[:6], 16) % 360
    r = 40 + hue % 80
    g = 20 + (hue * 3) % 60
    b = 60 + hue % 100
    img = Image.new("RGB", (512, 768), color=(r, g, b))
    draw = ImageDraw.Draw(img)

    # Garment silhouette outline
    draw.rectangle([80, 100, 432, 668], outline=(220, 180, 80), width=3)
    draw.line([(256, 100), (256, 668)], fill=(220, 180, 80), width=1)
    draw.ellipse([206, 40, 306, 100], outline=(220, 180, 80), width=2)

    # Label
    draw.text((120, 700), "AURA AI Preview", fill=(255, 255, 255))
    draw.text((120, 720), f"Seed: {seed[:8]}", fill=(180, 180, 180))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _build_fashion_prompt(spec: dict) -> str:
    """Build an optimized fashion prompt from outfit spec."""
    garment = spec.get("garment_type", "outfit")
    fabric = spec.get("fabric", "silk")
    color = spec.get("color", "red")
    silhouette = spec.get("silhouette", "")
    occasion = spec.get("occasion", "")
    style_notes = spec.get("style_notes", "")

    parts = [
        f"{color} {fabric} {garment}",
        f"{silhouette} silhouette" if silhouette else "",
        f"for {occasion}" if occasion else "",
        style_notes,
        "high fashion editorial photography, studio lighting, full body",
        "detailed fabric texture, professional fashion shoot, 4k quality",
        "on a clean background, no text, no watermark",
    ]
    return ", ".join(p for p in parts if p).strip()


async def generate_outfit_image(spec: dict) -> tuple[bytes | None, str]:
    """Generate a single outfit image from spec using the most reliable method.

    Returns:
        Tuple of (image_bytes, engine_name). image_bytes is None only if all
        engines fail (very unlikely since Pollinations requires no API key).
    """
    prompt = _build_fashion_prompt(spec)
    settings = get_settings()

    # Tier 1: Pollinations.ai (free, no API key, most reliable)
    image_bytes = await _pollinations_generate(prompt)
    if image_bytes and len(image_bytes) > 1000:
        return image_bytes, "pollinations"

    # Tier 2: HuggingFace SDXL (needs API key)
    if settings.huggingface_api_key and hf_breaker.current_state != "open":
        try:
            image_bytes = await _hf_sdxl_generate(prompt, settings)
            if image_bytes and len(image_bytes) > 500:
                return image_bytes, "hf_sdxl"
        except Exception as exc:
            logger.warning("HF SDXL fallback failed: %s", exc)

    # Tier 3: Deterministic placeholder (always works)
    seed = hashlib.sha256(prompt.encode()).hexdigest()
    placeholder_b64 = _placeholder_png_base64(seed)
    return base64.b64decode(placeholder_b64), "placeholder"


async def generate_outfits(
    *,
    design_brief: str,
    smplx_params: dict | None = None,
    num_variants: int = 4,
    clip_threshold: float = 0.28,
) -> OutfitGenerationResult:
    """Generate outfit image variants using the tiered generation chain."""
    variants: list[OutfitVariant] = []

    for i in range(min(num_variants, len(_PROMPT_TEMPLATES))):
        prompt = _PROMPT_TEMPLATES[i].format(brief=design_brief)

        # Try Pollinations first (free, reliable)
        image_bytes = await _pollinations_generate(prompt)
        if image_bytes and len(image_bytes) > 1000:
            variants.append(OutfitVariant(
                image_base64=base64.b64encode(image_bytes).decode("ascii"),
                prompt=prompt,
                clip_score=0.0,
            ))
            continue

        # Try HF SDXL
        settings = get_settings()
        if settings.huggingface_api_key and hf_breaker.current_state != "open":
            try:
                image_bytes = await _hf_sdxl_generate(prompt, settings)
                if image_bytes and len(image_bytes) > 500:
                    variants.append(OutfitVariant(
                        image_base64=base64.b64encode(image_bytes).decode("ascii"),
                        prompt=prompt,
                        clip_score=0.0,
                    ))
                    continue
            except Exception as exc:
                logger.warning("HF SDXL variant %d failed: %s", i, exc)

        # Placeholder fallback
        seed_base = hashlib.sha256(design_brief.encode()).hexdigest()
        variants.append(OutfitVariant(
            image_base64=_placeholder_png_base64(f"{seed_base}-{i}"),
            prompt=prompt,
            clip_score=0.0,
        ))

    if not variants:
        seed_base = hashlib.sha256(design_brief.encode()).hexdigest()
        variants.append(OutfitVariant(
            image_base64=_placeholder_png_base64(seed_base),
            prompt=design_brief,
            clip_score=0.0,
        ))

    return OutfitGenerationResult(
        variants=variants[:num_variants],
        preview_ready_ms=5000,
        full_ready_ms=15000,
    )


async def generate_from_spec(
    *,
    spec: dict,
    user_id: str = "anonymous",
) -> str | None:
    """Generate an outfit image from spec, store it, return URL."""
    import uuid
    from services.api.core.storage import get_storage

    image_bytes, engine = await generate_outfit_image(spec)
    logger.info("[generate_from_spec] engine=%s, bytes=%d",
                engine, len(image_bytes) if image_bytes else 0)

    if not image_bytes:
        return None

    # Store to object storage
    try:
        storage = get_storage()
        image_key = f"outfits/{user_id}/{uuid.uuid4().hex}.png"
        url = await storage.upload_bytes(
            image_bytes,
            key=image_key,
            content_type="image/png",
        )
        return url
    except Exception as exc:
        logger.warning("Outfit image storage failed: %s", exc)
        return None
