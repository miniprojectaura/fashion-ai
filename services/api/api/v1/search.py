import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.api.core.security import get_current_user_id

router = APIRouter()
logger = logging.getLogger(__name__)


class ProductSearchRequest(BaseModel):
    query: str = Field(..., min_length=2)
    category: str | None = None
    max_price_inr: float | None = None
    limit: int = Field(default=5, ge=1, le=20)


@router.post("/products")
async def search_products(body: ProductSearchRequest, _user_id: str = Depends(get_current_user_id)):
    """Search for real products via DuckDuckGo. Falls back to legacy match."""
    # Primary: real web search via DuckDuckGo
    try:
        from services.retrieval.web_search import search_products as real_search
        spec = {
            "garment_type": body.query,
            "fabric": "",
            "color": "",
            "budget_inr": body.max_price_inr,
        }
        hits = await real_search(spec, limit=body.limit, max_price_inr=body.max_price_inr)
        if hits:
            return {"results": hits, "count": len(hits), "engine": "duckduckgo"}
    except Exception as exc:
        logger.warning("Real web search failed: %s", exc)

    # Fallback: legacy product match
    try:
        from services.retrieval.product_match import match_products
        hits = await match_products(
            outfit_description=body.query,
            category=body.category,
            max_price_inr=body.max_price_inr,
            limit=body.limit,
        )
        return {"results": hits, "count": len(hits), "engine": "legacy"}
    except Exception as exc:
        logger.warning("Legacy search also failed: %s", exc)
        return {"results": [], "count": 0, "engine": "none"}

