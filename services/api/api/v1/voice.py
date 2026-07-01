"""Voice conversation endpoint — Sarvam ASR → Stylist LLM → Sarvam TTS.

POST /api/v1/voice/converse: Full voice loop for outfit negotiation.
POST /api/v1/voice/finalize: Finalize outfit → generate image → save to wardrobe.
"""

import base64
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.core.database import get_db
from services.api.core.models import BodyProfile, WardrobeItem
from services.api.core.security import get_current_user_id
from services.api.core.storage import get_storage
from services.api.services.sarvam_client import (
    synthesize_with_fallback,
    transcribe_with_fallback,
)
from services.agent.stylist import (
    OutfitStage,
    get_or_create_session,
    get_session,
    stylist_respond,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class ConverseResponse(BaseModel):
    transcript: str
    reply_text: str
    reply_audio_url: str | None
    outfit_state: dict


@router.post("/converse", response_model=ConverseResponse)
async def voice_converse(
    audio: UploadFile = File(...),
    session_id: str = Form("default"),
    language: str = Form("te"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Full voice conversation loop: ASR → LLM stylist → TTS → response.

    Accepts audio blob + session_id, returns transcript, reply text,
    reply audio URL, and current outfit negotiation state.
    """
    # Read and validate audio
    audio_bytes = await audio.read()
    if len(audio_bytes) < 100:
        raise HTTPException(status_code=400, detail="Audio too short")
    if len(audio_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Audio too large (max 10MB)")

    # Step 1: ASR — Sarvam Saarika (fallback: Whisper)
    transcript = await transcribe_with_fallback(audio_bytes, language)
    if not transcript or len(transcript.strip()) < 2:
        raise HTTPException(status_code=400, detail="Could not transcribe audio")

    # Step 2: Fetch body profile for this user (if exists)
    body_profile = None
    try:
        result = await db.execute(
            select(BodyProfile)
            .where(BodyProfile.user_id == user_id)
            .order_by(BodyProfile.created_at.desc())
            .limit(1)
        )
        profile = result.scalar_one_or_none()
        if profile and profile.measurements:
            body_profile = profile.measurements
    except Exception:
        pass  # body profile is optional

    # Step 3: Stylist LLM — negotiate outfit
    reply_text, outfit_state = await stylist_respond(
        transcript=transcript,
        body_profile=body_profile,
        session_id=session_id,
    )

    # Step 4: TTS — Sarvam Bulbul (fallback: Kokoro/HF MMS)
    reply_audio_url = None
    try:
        audio_out = await synthesize_with_fallback(reply_text, language)
        if audio_out and len(audio_out) > 100:
            storage = get_storage()
            audio_key = f"voice/{user_id}/{session_id}/{uuid.uuid4().hex}.wav"
            reply_audio_url = await storage.upload_bytes(
                audio_out,
                key=audio_key,
                content_type="audio/wav",
            )
    except Exception as exc:
        logger.warning("TTS/storage failed: %s", exc)

    return ConverseResponse(
        transcript=transcript,
        reply_text=reply_text,
        reply_audio_url=reply_audio_url,
        outfit_state=outfit_state,
    )


class TextConverseRequest(BaseModel):
    """Text-based conversation (for testing / text-chat fallback)."""
    message: str
    session_id: str = "default"
    language: str = "te"


@router.post("/converse-text")
async def voice_converse_text(
    body: TextConverseRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Text-based stylist conversation (no audio, for testing/fallback)."""
    # Fetch body profile
    body_profile = None
    try:
        result = await db.execute(
            select(BodyProfile)
            .where(BodyProfile.user_id == user_id)
            .order_by(BodyProfile.created_at.desc())
            .limit(1)
        )
        profile = result.scalar_one_or_none()
        if profile and profile.measurements:
            body_profile = profile.measurements
    except Exception:
        pass

    reply_text, outfit_state = await stylist_respond(
        transcript=body.message,
        body_profile=body_profile,
        session_id=body.session_id,
    )

    return {
        "transcript": body.message,
        "reply_text": reply_text,
        "reply_audio_url": None,
        "outfit_state": outfit_state,
    }


class FinalizeRequest(BaseModel):
    session_id: str


class FinalizeResponse(BaseModel):
    spec: dict
    image_url: str | None
    wardrobe_item_id: str | None
    web_matches: list[dict]


@router.post("/finalize", response_model=FinalizeResponse)
async def finalize_outfit(
    body: FinalizeRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Finalize outfit: lock spec → generate image → save to wardrobe → web match.

    Call this after the stylist conversation reaches 'finalized' stage.
    """
    session = get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    if session.stage != OutfitStage.FINALIZED:
        # Try to finalize via one more LLM call
        reply_text, outfit_state = await stylist_respond(
            transcript="Please finalize this outfit now.",
            session_id=body.session_id,
        )
        session = get_session(body.session_id)
        if not session or session.stage != OutfitStage.FINALIZED:
            raise HTTPException(
                status_code=400,
                detail="Outfit not yet finalized. Continue the conversation first.",
            )

    spec = session.spec.to_dict()

    # Phase D: Generate outfit image
    image_url = None
    try:
        from services.vision.generate_outfit import generate_from_spec
        image_url = await generate_from_spec(
            spec=spec,
            user_id=user_id,
        )
    except Exception as exc:
        logger.warning("Outfit image generation failed: %s", exc)

    # Phase E: Auto-save to wardrobe
    wardrobe_item_id = None
    try:
        item = WardrobeItem(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=f"{spec.get('color', '')} {spec.get('fabric', '')} {spec.get('garment_type', 'Outfit')}".strip(),
            image_url=image_url,
            category=spec.get("garment_type", "custom"),
            metadata_json=spec,
        )
        db.add(item)
        await db.commit()
        wardrobe_item_id = item.id
    except Exception as exc:
        logger.warning("Wardrobe save failed: %s", exc)

    # Phase F: Web garment matching (best-effort, non-blocking)
    web_matches: list[dict] = []
    try:
        from services.retrieval.web_match import match_web_garments
        web_matches = await match_web_garments(spec, limit=5)
    except Exception as exc:
        logger.warning("Web match failed (non-blocking): %s", exc)

    return FinalizeResponse(
        spec=spec,
        image_url=image_url,
        wardrobe_item_id=wardrobe_item_id,
        web_matches=web_matches,
    )
