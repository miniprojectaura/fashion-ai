"""Web garment matching — find real products matching a finalized outfit spec.

Best-effort, non-blocking. Wraps existing product_match.py with spec-to-query
conversion and a strict 5s timeout. Returns empty list on any failure.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Timeout for web matching (seconds)
WEB_MATCH_TIMEOUT = 5.0


def _spec_to_search_query(spec: dict) -> str:
    """Convert outfit spec to a search-friendly query string."""
    parts = []
    if spec.get("garment_type"):
        parts.append(spec["garment_type"])
    if spec.get("fabric"):
        parts.append(spec["fabric"])
    if spec.get("color"):
        parts.append(spec["color"])
    if spec.get("occasion"):
        parts.append(f"for {spec['occasion']}")
    if spec.get("silhouette"):
        parts.append(spec["silhouette"])
    return " ".join(parts) if parts else "Indian ethnic wear"


async def match_web_garments(
    spec: dict,
    *,
    limit: int = 5,
    max_price_inr: float | None = None,
) -> list[dict[str, Any]]:
    """Find 2-5 real matching products from the catalog/web.

    Wraps existing product matching with a strict timeout.
    On ANY failure or timeout, returns empty list — never blocks the main flow.

    Args:
        spec: Finalized outfit spec dict.
        limit: Max number of results.
        max_price_inr: Optional price filter.

    Returns:
        List of matching product dicts, or [] on failure.
    """
    try:
        query = _spec_to_search_query(spec)
        category = spec.get("garment_type")
        budget = max_price_inr or spec.get("budget_inr")

        from services.retrieval.product_match import match_products

        results = await asyncio.wait_for(
            match_products(
                outfit_description=query,
                category=category,
                max_price_inr=budget,
                limit=limit,
            ),
            timeout=WEB_MATCH_TIMEOUT,
        )
        return results or []

    except asyncio.TimeoutError:
        logger.warning("Web garment matching timed out after %.1fs", WEB_MATCH_TIMEOUT)
        return []
    except Exception as exc:
        logger.warning("Web garment matching failed (non-blocking): %s", exc)
        return []
