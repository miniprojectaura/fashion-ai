"""Culturally warm multilingual responses with fashion domain expertise injection."""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.llm import complete
from services.agent.schemas import AgentState
from services.api.core.models import StyleProfile

logger = logging.getLogger(__name__)

KNOWLEDGE_PATH = Path(__file__).resolve().parents[2] / "data" / "knowledge" / "fashion_knowledge_base.json"


@lru_cache(maxsize=1)
def _load_knowledge() -> dict:
    """Load fashion knowledge base (cached in memory)."""
    if KNOWLEDGE_PATH.is_file():
        with open(KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _extract_relevant_knowledge(state: AgentState) -> str:
    """Extract fashion knowledge relevant to the current query."""
    kb = _load_knowledge()
    if not kb:
        return ""

    snippets = []
    msg = state.message.lower()
    params = state.params

    # Body type knowledge
    if params.body_type or any(w in msg for w in ["body type", "body shape", "figure", "curvy", "petite", "plus size"]):
        bt = params.body_type or "hourglass"
        guide = kb.get("body_type_guide", {}).get(bt.lower().replace(" ", "_"), {})
        if guide:
            snippets.append(f"Body type ({bt}): Best garments: {guide.get('best_garments', [])}. "
                          f"Saree tip: {guide.get('saree_tips', '')}. "
                          f"Avoid: {guide.get('avoid', [])}.")

    # Fabric knowledge
    fabric_keywords = ["silk", "cotton", "georgette", "chiffon", "linen", "net", "organza", "banarasi", "kanjeevaram", "chanderi", "tussar"]
    for fabric in fabric_keywords:
        if fabric in msg:
            fb = kb.get("fabric_encyclopedia", {}).get(fabric.replace(" ", "_"), {})
            if not fb:
                fb = kb.get("fabric_encyclopedia", {}).get(f"{fabric}_silk", {})
            if fb:
                snippets.append(f"Fabric ({fabric}): {fb.get('characteristics', '')}. "
                              f"Occasions: {fb.get('ideal_occasions', [])}. "
                              f"Price: {fb.get('price_range_inr', 'varies')} INR. "
                              f"Tip: {fb.get('draping_tip', '')}.")
                break

    # Color theory
    if any(w in msg for w in ["color", "colour", "skin tone", "complexion", "dusky", "fair", "wheatish"]):
        tone_map = {"fair": "fair", "wheatish": "wheatish", "dusky": "dusky", "dark": "dark"}
        for keyword, tone in tone_map.items():
            if keyword in msg:
                guide = kb.get("color_theory", {}).get("skin_tone_guide", {}).get(tone, {})
                if guide:
                    snippets.append(f"Color guide ({tone} skin): Best colors: {guide.get('best_colors', [])}. "
                                  f"Avoid: {guide.get('avoid_colors', [])}. "
                                  f"Tip: {guide.get('tip', '')}.")
                break

    # Occasion colors
    occasion = (params.occasion or "").lower()
    if occasion:
        occ_colors = kb.get("color_theory", {}).get("occasion_colors", {})
        for occ_key, colors in occ_colors.items():
            if any(w in occasion for w in occ_key.split("_")):
                snippets.append(f"Occasion colors ({occ_key}): {colors}")
                break

    # Budget tier
    if params.budget:
        try:
            budget = int(params.budget)
            tiers = kb.get("budget_tiers", {})
            for tier_name, tier in tiers.items():
                range_str = tier.get("range", "")
                # Parse range
                nums = [int(n.replace(",", "").replace("₹", "").replace("+", "")) for n in range_str.split("-") if n.strip().replace(",", "").replace("₹", "").replace("+", "").isdigit()]
                if nums and budget <= nums[-1] * 1.5:
                    snippets.append(f"Budget tier ({tier_name}): {tier.get('tips', '')} "
                                  f"Platforms: {tier.get('platforms', [])}.")
                    break
        except (ValueError, TypeError):
            pass

    # Regional fashion
    region_keywords = {"south": "south_india", "north": "north_india", "bengali": "eastern_india", "gujarati": "western_india"}
    for keyword, region in region_keywords.items():
        if keyword in msg:
            reg = kb.get("regional_fashion", {}).get(region, {})
            if reg:
                snippets.append(f"Regional ({region}): Signature: {reg.get('signature_garments', [])}. "
                              f"Jewelry: {reg.get('jewelry', '')}.")
            break

    # Tailoring knowledge
    if any(w in msg for w in ["stitch", "tailor", "fabric needed", "yard", "measurement"]):
        garment_map = {"blouse": "saree_blouse", "kurta": "kurta", "lehenga": "lehenga", "salwar": "salwar"}
        for keyword, garment_key in garment_map.items():
            if keyword in msg:
                tg = kb.get("tailoring_guide", {}).get(garment_key, {})
                if tg:
                    snippets.append(f"Tailoring ({garment_key}): Fabric needed: {tg.get('fabric_needed', '')}. "
                                  f"Cost: {tg.get('stitch_cost_range', '')}. "
                                  f"Styles: {tg.get('common_styles', [])}.")
                break

    if snippets:
        return "\n\nFashion Expert Knowledge:\n" + "\n".join(snippets[:3])  # Max 3 snippets
    return ""


async def load_style_context(db: AsyncSession, user_id: str) -> str:
    result = await db.execute(select(StyleProfile).where(StyleProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        return ""
    tags = profile.liked_tags or []
    vec = profile.preference_vector or []
    return f"User likes: {tags}. Preference strength: {vec[:3] if vec else 'neutral'}."


async def synthesize_with_profile(
    state: AgentState,
    *,
    style_context: str = "",
    history: list[dict[str, Any]] | None = None,
) -> str:
    lang_hint = {"te": "Telugu code-mixed", "hi": "Hindi", "en": "English"}.get(state.language, "Telugu")

    # Inject domain knowledge
    knowledge = _extract_relevant_knowledge(state)

    system = (
        f"You are AURA, an elite AI fashion stylist with 20+ years of expertise in Indian ethnic "
        f"and contemporary fashion. You know 40+ fabric types, color theory for all skin tones, "
        f"body type dressing, regional traditions, and budget-conscious recommendations. "
        f"Respond in {lang_hint}. Be warm, specific, actionable. Under 150 words. "
        f"{style_context}{knowledge}"
    )

    # Build history context for multi-turn conversation
    history_text = ""
    if history:
        recent = history[-6:]  # Last 3 exchanges (6 messages)
        history_lines = []
        for msg in recent:
            role = msg.get("role", "user")
            content = msg.get("content", "")[:200]
            history_lines.append(f"{role}: {content}")
        history_text = "Conversation so far:\n" + "\n".join(history_lines) + "\n\n"

    prompt = (
        f"{history_text}"
        f"Message: {state.message}\nIntent: {state.intent}\nParams: {state.params.model_dump_json()}\n"
        "Give specific recommendations with brands, price ranges, and styling tips. Include a clear next step."
    )
    try:
        return await complete(prompt, system=system, temperature=0.5)
    except Exception:
        return (
            f"{state.params.occasion or 'Outfit'} ki red/gold ethnic wear suggest chestanu. "
            "Avatar kosam photos upload cheyandi."
        )

