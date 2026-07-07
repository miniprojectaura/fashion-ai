"""Voice conversation endpoint — Groq Whisper ASR → Stylist LLM → Sarvam TTS.

POST /api/v1/voice/converse: Full voice loop for outfit negotiation.
POST /api/v1/voice/converse-text: Text-based fallback.
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
from services.api.core.models import BodyProfile, Conversation, Session, WardrobeItem
from services.api.core.security import get_current_user_id
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
    reply_audio_b64: str | None
    detected_language: str
    asr_engine: str
    tts_engine: str
    outfit_state: dict


@router.post("/converse", response_model=ConverseResponse)
async def voice_converse(
    audio: UploadFile = File(...),
    session_id: str = Form("default"),
    language: str = Form(""),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Full voice conversation loop: ASR → LLM stylist → TTS → response.

    Accepts audio blob + session_id, returns transcript, reply text,
    reply audio as base64, detected language, and engine info.
    Language is auto-detected if not provided.
    """
    # Read and validate audio
    audio_bytes = await audio.read()
    if len(audio_bytes) < 100:
        raise HTTPException(status_code=400, detail="Audio too short")
    if len(audio_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Audio too large (max 10MB)")

    # Step 1: ASR — Groq Whisper (primary) → Sarvam → HF Whisper
    try:
        transcript, detected_lang, asr_engine = await transcribe_with_fallback(
            audio_bytes, language=language if language else None,
        )
    except RuntimeError:
        raise HTTPException(status_code=500, detail="All ASR engines failed — could not transcribe")

    if not transcript or len(transcript.strip()) < 2:
        raise HTTPException(status_code=400, detail="Could not transcribe audio")

    logger.info("[voice/converse] ASR engine=%s, lang=%s, transcript=%s...",
                asr_engine, detected_lang, transcript[:60])

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

    # Step 3: Stylist LLM — negotiate outfit (with detected language)
    reply_text, outfit_state = await stylist_respond(
        transcript=transcript,
        body_profile=body_profile,
        session_id=session_id,
        detected_language=detected_lang,
    )

    # Step 4: TTS — Sarvam Bulbul v3 (primary) → HF MMS (fallback)
    reply_audio_b64 = None
    tts_engine = "none"
    try:
        audio_out, tts_engine = await synthesize_with_fallback(reply_text, language=detected_lang)
        if audio_out and len(audio_out) > 100:
            reply_audio_b64 = base64.b64encode(audio_out).decode("ascii")
            logger.info("[voice/converse] TTS engine=%s, audio_size=%d bytes",
                        tts_engine, len(audio_out))
    except Exception as exc:
        logger.warning("[voice/converse] TTS failed: %s", exc)

    return ConverseResponse(
        transcript=transcript,
        reply_text=reply_text,
        reply_audio_b64=reply_audio_b64,
        detected_language=detected_lang,
        asr_engine=asr_engine,
        tts_engine=tts_engine,
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
    """Text-based stylist conversation — also generates TTS audio for the reply."""
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
        detected_language=body.language,
    )

    # Generate TTS for text conversations too (app should speak)
    reply_audio_b64 = None
    tts_engine = "none"
    try:
        audio_out, tts_engine = await synthesize_with_fallback(reply_text, language=body.language)
        if audio_out and len(audio_out) > 100:
            reply_audio_b64 = base64.b64encode(audio_out).decode("ascii")
    except Exception as exc:
        logger.warning("[voice/converse-text] TTS failed: %s", exc)

    # Persist messages to DB for chat history
    try:
        # Ensure session exists
        existing = await db.execute(
            select(Session).where(Session.id == body.session_id)
        )
        if not existing.scalar_one_or_none():
            db.add(Session(id=body.session_id, user_id=user_id))

        db.add(Conversation(
            session_id=body.session_id, role="user",
            content=body.message, language=body.language,
        ))
        db.add(Conversation(
            session_id=body.session_id, role="assistant",
            content=reply_text, language=body.language,
        ))
        await db.commit()
    except Exception as exc:
        logger.warning("[voice] Chat persistence failed: %s", exc)

    return {
        "transcript": body.message,
        "reply_text": reply_text,
        "reply_audio_b64": reply_audio_b64,
        "detected_language": body.language,
        "asr_engine": "text_input",
        "tts_engine": tts_engine,
        "outfit_state": outfit_state,
    }


# ── Chat History Endpoints ───────────────────────────────────────

class SessionInfo(BaseModel):
    id: str
    created_at: str
    last_message: str | None = None
    message_count: int = 0


@router.get("/sessions")
async def list_sessions(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """List all chat sessions for the current user, newest first."""
    from sqlalchemy import func as sqlfunc

    try:
        result = await db.execute(
            select(Session)
            .where(Session.user_id == user_id)
            .order_by(Session.created_at.desc())
            .limit(50)
        )
        sessions = result.scalars().all()

        session_list = []
        for s in sessions:
            # Get last message and count for this session
            msg_result = await db.execute(
                select(Conversation)
                .where(Conversation.session_id == s.id)
                .order_by(Conversation.created_at.desc())
                .limit(1)
            )
            last_msg = msg_result.scalar_one_or_none()

            count_result = await db.execute(
                select(sqlfunc.count())
                .select_from(Conversation)
                .where(Conversation.session_id == s.id)
            )
            count = count_result.scalar() or 0

            session_list.append({
                "id": s.id,
                "created_at": s.created_at.isoformat() if s.created_at else "",
                "last_message": (last_msg.content[:80] + "...") if last_msg and len(last_msg.content) > 80 else (last_msg.content if last_msg else None),
                "message_count": count,
            })

        return {"sessions": session_list}
    except Exception as exc:
        logger.warning("[voice] List sessions failed: %s", exc)
        return {"sessions": []}


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Load all messages for a specific session."""
    try:
        # Verify session belongs to user
        sess_result = await db.execute(
            select(Session).where(
                Session.id == session_id,
                Session.user_id == user_id,
            )
        )
        session = sess_result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        result = await db.execute(
            select(Conversation)
            .where(Conversation.session_id == session_id)
            .order_by(Conversation.created_at.asc())
            .limit(200)
        )
        messages = result.scalars().all()

        return {
            "session_id": session_id,
            "messages": [
                {
                    "role": m.role,
                    "text": m.content,
                    "language": m.language,
                    "created_at": m.created_at.isoformat() if m.created_at else "",
                }
                for m in messages
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[voice] Get messages failed: %s", exc)
        return {"session_id": session_id, "messages": []}


class CreateSessionRequest(BaseModel):
    display_name: str | None = None


@router.post("/sessions")
async def create_session(
    body: CreateSessionRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new chat session."""
    new_id = str(uuid.uuid4())
    db.add(Session(id=new_id, user_id=user_id))
    await db.commit()
    return {"session_id": new_id}


class FinalizeRequest(BaseModel):
    session_id: str


class FinalizeResponse(BaseModel):
    spec: dict
    image_url: str | None
    outfit_image_b64: str | None = None
    wardrobe_item_id: str | None
    web_matches: list[dict]
    tryon_image_b64: str | None = None
    tailoring: dict | None = None
    reasoning: str | None = None


@router.post("/finalize", response_model=FinalizeResponse)
async def finalize_outfit(
    body: FinalizeRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Finalize outfit: lock spec → generate image → tailoring → web search → try-on.

    Enhanced pipeline:
    1. Generate outfit image (HF SDXL)
    2. Compute tailoring measurements (deterministic)
    3. Real product search (DuckDuckGo)
    4. Virtual try-on (HF Spaces)
    5. Save to wardrobe
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

    # Fetch body profile for tailoring + try-on
    body_profile = None
    body_analysis = None
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

    # Phase D: Generate outfit image — Pollinations.ai (free) → HF SDXL → placeholder
    image_url = None
    outfit_image_b64 = None
    try:
        from services.vision.generate_outfit import generate_outfit_image, generate_from_spec

        img_bytes, img_engine = await generate_outfit_image(spec)
        if img_bytes and len(img_bytes) > 500:
            outfit_image_b64 = base64.b64encode(img_bytes).decode('ascii')
            logger.info('[finalize] Outfit image generated via %s (%d bytes)',
                        img_engine, len(img_bytes))

        # Also try to get a stored URL (best-effort)
        try:
            image_url = await generate_from_spec(spec=spec, user_id=user_id)
        except Exception:
            pass
    except Exception as exc:
        logger.warning('Outfit image generation failed: %s', exc)

    # Phase E: Compute tailoring measurements (deterministic)
    tailoring_data = None
    body_analysis = None
    if body_profile:
        try:
            from services.agent.tailoring_calc import compute as compute_tailoring
            from services.agent.body_analyzer import analyze as analyze_body

            body_analysis_result = analyze_body(body_profile)
            body_analysis = body_analysis_result.to_dict()

            tailoring = compute_tailoring(
                garment_type=spec.get("garment_type", "kurta"),
                fabric=spec.get("fabric", "cotton"),
                measurements=body_profile,
                body_type=body_analysis_result.body_type,
            )
            tailoring_data = tailoring.to_dict()
            logger.info("[finalize] Tailoring computed for %s, body_type=%s",
                        spec.get("garment_type"), body_analysis_result.body_type)
        except Exception as exc:
            logger.warning("Tailoring calculation failed: %s", exc)

    # Phase F: Real product search (DuckDuckGo — real URLs)
    web_matches: list[dict] = []
    try:
        from services.retrieval.web_search import search_products as real_search
        web_matches = await real_search(
            spec,
            limit=5,
            max_price_inr=spec.get("budget_inr"),
        )
        logger.info("[finalize] Found %d real products via web search", len(web_matches))
    except Exception as exc:
        logger.warning("Real web search failed, trying legacy: %s", exc)
        # Fallback to legacy product match
        try:
            from services.retrieval.web_match import match_web_garments
            web_matches = await match_web_garments(spec, limit=5)
        except Exception as exc2:
            logger.warning("Legacy web match also failed: %s", exc2)

    # Phase G: Virtual try-on (HF Spaces — with user's actual photo if available)
    tryon_image_b64 = None
    try:
        from services.vision.virtual_tryon import generate_tryon_image

        # Extract user's front photo from BodyProfile (stored by avatar.py)
        person_image_bytes = None
        if body_profile and isinstance(body_profile, dict):
            front_b64 = body_profile.get('_front_photo_b64')
            if front_b64:
                try:
                    person_image_bytes = base64.b64decode(front_b64)
                except Exception:
                    pass

        tryon_bytes, tryon_engine = await generate_tryon_image(
            spec=spec,
            person_image_bytes=person_image_bytes,
            body_analysis=body_analysis,
        )
        if tryon_bytes and len(tryon_bytes) > 500:
            tryon_image_b64 = base64.b64encode(tryon_bytes).decode('ascii')
            logger.info('[finalize] Try-on image generated via %s (%d bytes)',
                        tryon_engine, len(tryon_bytes))
    except Exception as exc:
        logger.warning('Virtual try-on failed (non-blocking): %s', exc)

    # Phase H: Auto-save to wardrobe (with full metadata for wardrobe display)
    wardrobe_item_id = None
    try:
        wardrobe_meta = {
            **spec,
            '_tailoring': tailoring_data,
            '_outfit_image_b64': outfit_image_b64[:200] if outfit_image_b64 else None,  # Truncated ref
            '_has_tryon': tryon_image_b64 is not None,
        }
        item = WardrobeItem(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=f"{spec.get('color', '')} {spec.get('fabric', '')} {spec.get('garment_type', 'Outfit')}".strip(),
            image_url=image_url,
            category=spec.get('garment_type', 'custom'),
            metadata_json=wardrobe_meta,
        )
        db.add(item)
        await db.commit()
        wardrobe_item_id = item.id
    except Exception as exc:
        logger.warning('Wardrobe save failed: %s', exc)

    # Extract reasoning from the last session history if available
    reasoning = None
    if session.history:
        for msg in reversed(session.history):
            if msg.get('role') == 'assistant' and '<think>' in (msg.get('content') or ''):
                reasoning = msg['content']
                break

    return FinalizeResponse(
        spec=spec,
        image_url=image_url,
        outfit_image_b64=outfit_image_b64,
        wardrobe_item_id=wardrobe_item_id,
        web_matches=web_matches,
        tryon_image_b64=tryon_image_b64,
        tailoring=tailoring_data,
        reasoning=reasoning,
    )
