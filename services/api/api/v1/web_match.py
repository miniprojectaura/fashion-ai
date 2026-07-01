"""Web garment matching route — POST /api/v1/design/web-match."""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.api.core.security import get_current_user_id
from services.retrieval.web_match import match_web_garments

logger = logging.getLogger(__name__)

router = APIRouter()


class WebMatchRequest(BaseModel):
    spec: dict = Field(..., description="Finalized outfit spec")
    limit: int = Field(default=5, ge=1, le=10)
    max_price_inr: float | None = None


@router.post("/web-match")
async def web_match(
    body: WebMatchRequest,
    _user_id: str = Depends(get_current_user_id),
):
    """Find real matching garments/fabrics from the web/catalog.

    Best-effort: always returns 200, even on failure (with empty results).
    """
    results = await match_web_garments(
        body.spec,
        limit=body.limit,
        max_price_inr=body.max_price_inr,
    )
    return {
        "matches": results,
        "count": len(results),
    }
