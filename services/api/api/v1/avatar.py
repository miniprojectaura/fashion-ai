import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.core.database import get_db
from services.api.core.models import BodyProfile
from services.api.core.security import get_current_user_id
from services.api.core.encryption import encrypt_bytes
from services.api.core.image_utils import compress_image
from services.api.core.moderation import moderate_image_bytes
from services.api.core.storage import get_storage
from services.vision.body_reconstruct import reconstruct_body

router = APIRouter()
MAX_UPLOAD = 10 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


class AvatarResponse(BaseModel):
    profile_id: str
    glb_base64: str
    confidence: float
    measurements: dict


class AnalyzeResponse(BaseModel):
    profile_id: str
    measurements: dict
    mesh_url: str | None
    confidence: float


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_body(
    front: UploadFile = File(...),
    side: UploadFile | None = File(None),
    height_cm: float = Form(165.0),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Analyze body photos + user height → measurements + parametric mesh."""
    front_bytes = compress_image(await _read_validated_image(front))
    ok, reason = moderate_image_bytes(front_bytes)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    side_bytes = None
    if side:
        side_bytes = compress_image(await _read_validated_image(side))
        ok2, reason2 = moderate_image_bytes(side_bytes)
        if not ok2:
            raise HTTPException(status_code=400, detail=reason2)

    # Clamp height to sane range
    height_cm = max(100.0, min(250.0, height_cm))

    result = await reconstruct_body(front_bytes, side_bytes, height_cm=height_cm)

    # Store mesh to object storage
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
        pass  # mesh storage is best-effort

    # Persist body profile
    profile = BodyProfile(
        user_id=user_id,
        smplx_params=result.smplx_params,
        glb_url=mesh_url,
        measurements=result.measurements,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    return AnalyzeResponse(
        profile_id=profile.id,
        measurements=result.measurements,
        mesh_url=mesh_url,
        confidence=result.confidence,
    )


@router.post("/upload", response_model=AvatarResponse)
async def upload_avatar_photos(
    front: UploadFile = File(...),
    side: UploadFile | None = File(None),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    front_bytes = compress_image(await _read_validated_image(front))
    ok, reason = moderate_image_bytes(front_bytes)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    side_bytes = None
    if side:
        side_bytes = compress_image(await _read_validated_image(side))
        ok2, reason2 = moderate_image_bytes(side_bytes)
        if not ok2:
            raise HTTPException(status_code=400, detail=reason2)

    result = await reconstruct_body(front_bytes, side_bytes)

    storage = get_storage()
    front_url = await storage.upload_bytes(
        encrypt_bytes(front_bytes),
        key=f"avatars/{user_id}/front.jpg.enc",
        content_type="application/octet-stream",
    )
    glb_url = await storage.upload_bytes(
        base64.b64decode(result.glb_base64),
        key=f"avatars/{user_id}/body.glb",
        content_type="model/gltf-binary",
    )

    profile = BodyProfile(
        user_id=user_id,
        smplx_params=result.smplx_params,
        glb_url=glb_url or front_url,
        measurements=result.measurements,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    return AvatarResponse(
        profile_id=profile.id,
        glb_base64=result.glb_base64,
        confidence=result.confidence,
        measurements=result.measurements,
    )


async def _read_validated_image(upload: UploadFile) -> bytes:
    if upload.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Invalid content type")
    data = await upload.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status_code=400, detail="File too large")
    return data
