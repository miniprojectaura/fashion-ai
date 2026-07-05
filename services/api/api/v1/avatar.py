"""Avatar endpoints — body photo analysis, quality validation, measurement storage."""

import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.core.database import get_db
from services.api.core.models import BodyProfile
from services.api.core.security import get_current_user_id
from services.api.core.image_utils import compress_image
from services.api.core.moderation import moderate_image_bytes
from services.api.core.storage import get_storage
from services.vision.body_reconstruct import (
    reconstruct_body,
    validate_image_quality,
)

router = APIRouter()
MAX_UPLOAD = 10 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


# ── Response Models ─────────────────────────────────────────────────────────

class QualityCheckResponse(BaseModel):
    acceptable: bool
    blur_score: float
    brightness: float
    resolution_ok: bool
    issues: list[str]
    suggestion: str


class AnalyzeResponse(BaseModel):
    profile_id: str
    measurements: dict
    mesh_url: str | None
    confidence: float
    build_type: str
    quality_info: dict | None


class MeasurementsResponse(BaseModel):
    has_profile: bool
    profile_id: str | None = None
    measurements: dict | None = None
    build_type: str | None = None
    confidence: float | None = None


# ── Quality Check ───────────────────────────────────────────────────────────

@router.post("/check-quality", response_model=QualityCheckResponse)
async def check_image_quality(
    photo: UploadFile = File(...),
    _user_id: str = Depends(get_current_user_id),
):
    """Check photo quality BEFORE full analysis. Returns issues and suggestions."""
    data = await _read_validated_image(photo)
    result = validate_image_quality(data, label="photo")
    return QualityCheckResponse(
        acceptable=result.is_acceptable,
        blur_score=round(result.blur_score, 1),
        brightness=round(result.brightness_score, 1),
        resolution_ok=result.resolution_ok,
        issues=result.issues,
        suggestion=result.suggestion,
    )


# ── Body Analysis ───────────────────────────────────────────────────────────

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_body(
    front: UploadFile = File(...),
    side: UploadFile | None = File(None),
    height_cm: float = Form(165.0),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Analyze body photos + height → precise measurements + mesh.

    - Validates image quality (rejects blurry/dark images)
    - Uses VLM (Groq Vision) for precise body shape analysis
    - Side photo significantly improves accuracy (92% vs 85%)
    - Stores measurements in user's body profile
    """
    front_bytes = compress_image(await _read_validated_image(front), max_px=1024)
    ok, reason = moderate_image_bytes(front_bytes)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    # Validate front quality
    front_quality = validate_image_quality(front_bytes, "front")
    if not front_quality.is_acceptable and front_quality.issues:
        # Return quality issues instead of failing silently
        critical = [i for i in front_quality.issues if "blurry" in i.lower() or "dark" in i.lower()]
        if critical:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "poor_image_quality",
                    "issues": front_quality.issues,
                    "suggestion": front_quality.suggestion,
                },
            )

    side_bytes = None
    if side:
        side_bytes = compress_image(await _read_validated_image(side), max_px=1024)
        ok2, reason2 = moderate_image_bytes(side_bytes)
        if not ok2:
            raise HTTPException(status_code=400, detail=reason2)

    # Clamp height
    height_cm = max(100.0, min(250.0, height_cm))

    # Run analysis
    result = await reconstruct_body(front_bytes, side_bytes, height_cm=height_cm)

    # Hard-reject if confidence is too low (< 80%)
    if result.confidence < 0.80:
        pipeline = result.measurements.get("_pipeline", "unknown")
        raise HTTPException(
            status_code=422,
            detail={
                "error": "low_measurement_confidence",
                "confidence": round(result.confidence * 100),
                "pipeline": pipeline,
                "issues": [
                    f"Measurement confidence is only {round(result.confidence * 100)}%.",
                    "For accurate tailoring, we need at least 80% confidence.",
                ],
                "suggestion": (
                    "Please retake your photo:\n"
                    "• Stand upright with arms slightly away from body\n"
                    "• Ensure good, even lighting (no harsh shadows)\n"
                    "• Wear form-fitting clothes (avoid baggy/loose outfits)\n"
                    "• Include full body from head to feet\n"
                    "• Add a side photo for best results"
                ),
            },
        )

    # Store mesh
    storage = get_storage()
    mesh_url = None
    try:
        glb_data = base64.b64decode(result.glb_base64)
        mesh_url = await storage.upload_bytes(
            glb_data,
            key=f"avatars/{user_id}/body.glb",
            content_type="model/gltf-binary",
        )
    except Exception:
        pass

    # Clean measurements for storage (remove _vlm_ metadata keys for DB)
    clean_measurements = {k: v for k, v in result.measurements.items() if not k.startswith("_")}
    meta = {k: v for k, v in result.measurements.items() if k.startswith("_")}

    # Store compressed front photo for virtual try-on reuse
    # Compress to ~50KB JPEG to keep DB payload reasonable
    front_photo_b64 = None
    try:
        small_front = compress_image(front_bytes, max_px=512)
        front_photo_b64 = base64.b64encode(small_front).decode("ascii")
    except Exception:
        pass

    store_data = {
        **clean_measurements,
        "_meta": meta,
        "_build_type": result.build_type,
        "_confidence": result.confidence,
        "_front_photo_b64": front_photo_b64,
    }

    # Upsert body profile — replace existing profile for this user
    existing = await db.execute(
        select(BodyProfile)
        .where(BodyProfile.user_id == user_id)
        .order_by(BodyProfile.created_at.desc())
        .limit(1)
    )
    old_profile = existing.scalars().first()
    if old_profile:
        old_profile.smplx_params = result.smplx_params
        old_profile.glb_url = mesh_url
        old_profile.measurements = store_data
        profile = old_profile
    else:
        profile = BodyProfile(
            user_id=user_id,
            smplx_params=result.smplx_params,
            glb_url=mesh_url,
            measurements=store_data,
        )
        db.add(profile)

    await db.commit()
    await db.refresh(profile)

    return AnalyzeResponse(
        profile_id=profile.id,
        measurements=result.measurements,
        mesh_url=mesh_url,
        confidence=result.confidence,
        build_type=result.build_type,
        quality_info=result.quality_info,
    )


# ── Measurement Retrieval ───────────────────────────────────────────────────

@router.get("/measurements", response_model=MeasurementsResponse)
async def get_measurements(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve stored body measurements for the current user.

    These measurements are used by the design/tailor endpoints for precise fitting.
    """
    result = await db.execute(
        select(BodyProfile)
        .where(BodyProfile.user_id == user_id)
        .order_by(BodyProfile.created_at.desc())
        .limit(1)
    )
    profile = result.scalars().first()

    if not profile or not profile.measurements:
        return MeasurementsResponse(has_profile=False)

    measurements = profile.measurements
    build_type = measurements.pop("_build_type", "average") if isinstance(measurements, dict) else "average"
    meta = measurements.pop("_meta", {}) if isinstance(measurements, dict) else {}
    stored_confidence = measurements.pop("_confidence", None) if isinstance(measurements, dict) else None

    # Re-add VLM metadata to response
    full_measurements = {**measurements, **meta}

    return MeasurementsResponse(
        has_profile=True,
        profile_id=profile.id,
        measurements=full_measurements,
        build_type=build_type,
        confidence=stored_confidence,
    )


# ── Legacy Upload ───────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_avatar_photos(
    front: UploadFile = File(...),
    side: UploadFile | None = File(None),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Legacy upload endpoint — redirects to analyze."""
    return await analyze_body(front=front, side=side, height_cm=165.0, user_id=user_id, db=db)


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _read_validated_image(upload: UploadFile) -> bytes:
    if upload.content_type and upload.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Invalid content type. Use JPEG, PNG, or WebP.")
    data = await upload.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")
    if len(data) < 100:
        raise HTTPException(status_code=400, detail="File too small or empty")
    return data
