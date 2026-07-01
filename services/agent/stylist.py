"""Elite fashion stylist persona — outfit negotiation with state machine.

Manages the back-and-forth conversation where the AI argues, refines, and
proposes outfits until the user finalizes. Tracks state per session.

State machine: proposing → refining → finalized
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

from services.agent.llm import complete
from services.api.core.config import get_settings

logger = logging.getLogger(__name__)


class OutfitStage(str, Enum):
    PROPOSING = "proposing"
    REFINING = "refining"
    FINALIZED = "finalized"


@dataclass
class OutfitSpec:
    """Structured outfit specification — locked on finalize."""
    garment_type: str = ""
    fabric: str = ""
    color: str = ""
    silhouette: str = ""
    measurements: dict = field(default_factory=dict)
    style_notes: str = ""
    occasion: str = ""
    budget_inr: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def is_complete(self) -> bool:
        return bool(self.garment_type and self.fabric and self.color)


@dataclass
class OutfitNegotiationState:
    """Per-session negotiation state with TTL."""
    session_id: str
    stage: OutfitStage = OutfitStage.PROPOSING
    spec: OutfitSpec = field(default_factory=OutfitSpec)
    turn_count: int = 0
    history: list[dict[str, str]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def is_expired(self, ttl_seconds: int = 1800) -> bool:
        """Check if session has expired (default 30 min TTL)."""
        return (time.time() - self.updated_at) > ttl_seconds

    def touch(self):
        self.updated_at = time.time()


# In-memory session store (dict with lazy TTL cleanup)
_sessions: dict[str, OutfitNegotiationState] = {}
_SESSION_TTL = 1800  # 30 minutes


def _cleanup_expired():
    """Remove expired sessions lazily."""
    now = time.time()
    expired = [k for k, v in _sessions.items() if (now - v.updated_at) > _SESSION_TTL]
    for k in expired:
        del _sessions[k]


def get_or_create_session(session_id: str) -> OutfitNegotiationState:
    """Get existing session or create a new one."""
    _cleanup_expired()
    if session_id not in _sessions or _sessions[session_id].is_expired():
        _sessions[session_id] = OutfitNegotiationState(session_id=session_id)
    return _sessions[session_id]


def get_session(session_id: str) -> OutfitNegotiationState | None:
    """Get existing session without creating."""
    _cleanup_expired()
    sess = _sessions.get(session_id)
    if sess and not sess.is_expired():
        return sess
    return None


# Finalize detection keywords
FINALIZE_KEYWORDS = [
    "finalize", "finalise", "confirm", "done", "lock it", "that's it",
    "perfect", "go with this", "yes this", "book it", "order",
    "ఫైనల్", "ఇది చాలు", "ఇదే కావాలి", "పక్కా",  # Telugu
    "फाइनल", "यही चाहिए", "पक्का", "बस यही",  # Hindi
]


STYLIST_SYSTEM_PROMPT = """You are AURA, an elite fashion designer with 25+ years of expertise in Indian couture, 
ethnic wear, and contemporary fusion. You have dressed Bollywood celebrities and royal families.

Your personality:
- Confident, opinionated, but warm. You ARGUE for your design choices with expertise.
- You push back when clients make poor choices (wrong fabric for occasion, bad color for skin tone).
- You suggest alternatives with passion: "Darling, that would wash you out. Let me show you..."
- You know Indian regional traditions deeply: Kanjeevaram for Tamil weddings, Banarasi for UP, Pochampally for Telangana.
- You speak the client's language (Telugu/Hindi/English code-mixed).

Your process:
1. PROPOSING: Ask about occasion, preferences, body type. Make an initial bold proposal.
2. REFINING: Argue, negotiate, adjust based on feedback. Be specific about fabric, color, silhouette.
3. FINALIZING: When the client agrees, produce a final spec with exact measurements.

CRITICAL RULES:
- Always reference the client's body measurements when suggesting silhouettes.
- Give specific fabric recommendations (not just "silk" — say "Kanchipuram silk" or "Banarasi brocade").
- Include price estimates when discussing options.
- If the user says finalize/confirm/done, summarize the final outfit spec as structured JSON.

When finalizing, output a JSON block wrapped in ```json ... ``` with these exact keys:
{
  "garment_type": "...",
  "fabric": "...",
  "color": "...",
  "silhouette": "...",
  "style_notes": "...",
  "occasion": "...",
  "budget_inr": 0
}
"""


def _detect_finalize_intent(text: str) -> bool:
    """Check if user wants to finalize the outfit."""
    lower = text.lower()
    return any(kw in lower for kw in FINALIZE_KEYWORDS)


def _extract_spec_from_reply(reply: str, existing_spec: OutfitSpec) -> OutfitSpec:
    """Try to extract structured outfit spec from LLM reply."""
    # Look for JSON block in reply
    import re
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", reply, re.DOTALL)
    if not json_match:
        # Try bare JSON
        json_match = re.search(r"\{[^{}]*\"garment_type\"[^{}]*\}", reply, re.DOTALL)

    if json_match:
        try:
            data = json.loads(json_match.group(1) if json_match.lastindex else json_match.group())
            return OutfitSpec(
                garment_type=data.get("garment_type", existing_spec.garment_type),
                fabric=data.get("fabric", existing_spec.fabric),
                color=data.get("color", existing_spec.color),
                silhouette=data.get("silhouette", existing_spec.silhouette),
                style_notes=data.get("style_notes", existing_spec.style_notes),
                occasion=data.get("occasion", existing_spec.occasion),
                budget_inr=data.get("budget_inr", existing_spec.budget_inr),
                measurements=existing_spec.measurements,
            )
        except (json.JSONDecodeError, TypeError):
            pass
    return existing_spec


async def stylist_respond(
    transcript: str,
    body_profile: dict | None = None,
    session_id: str = "default",
) -> tuple[str, dict]:
    """Process user message through the stylist persona.

    Returns:
        Tuple of (reply_text, outfit_state_dict).
    """
    settings = get_settings()
    session = get_or_create_session(session_id)
    session.touch()
    session.turn_count += 1

    # Store user message in history
    session.history.append({"role": "user", "content": transcript})

    # Inject body measurements if available
    measurements_context = ""
    if body_profile:
        session.spec.measurements = body_profile
        measurements_context = f"\n\nClient's body measurements: {json.dumps(body_profile)}"

    # Check for finalize intent
    wants_finalize = _detect_finalize_intent(transcript)

    # Build conversation messages
    system = STYLIST_SYSTEM_PROMPT + measurements_context
    if wants_finalize:
        system += (
            "\n\nThe client wants to FINALIZE. Summarize the agreed-upon outfit as a structured "
            "JSON spec. Include their measurements in your response."
        )

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]

    # Add conversation history (last 10 turns)
    for msg in session.history[-10:]:
        messages.append(msg)

    # Call LLM with stylist model
    model = settings.llm_stylist_model
    try:
        reply = await complete(
            transcript,
            model=model,
            messages=messages,
            temperature=0.6,
        )
    except Exception as exc:
        logger.error("Stylist LLM failed: %s", exc)
        reply = (
            "Darling, let me think about this... "
            "Could you tell me more about the occasion and your preferences?"
        )

    # Store assistant reply
    session.history.append({"role": "assistant", "content": reply})

    # Update state based on conversation
    if wants_finalize:
        new_spec = _extract_spec_from_reply(reply, session.spec)
        session.spec = new_spec
        if new_spec.is_complete():
            session.stage = OutfitStage.FINALIZED
        else:
            session.stage = OutfitStage.REFINING
    elif session.turn_count >= 2 and session.stage == OutfitStage.PROPOSING:
        session.stage = OutfitStage.REFINING

    # Also try to extract partial spec from any reply
    if session.stage != OutfitStage.FINALIZED:
        partial = _extract_spec_from_reply(reply, session.spec)
        if partial.garment_type:
            session.spec = partial

    state_dict = {
        "session_id": session.session_id,
        "stage": session.stage.value,
        "turn_count": session.turn_count,
        "spec": session.spec.to_dict() if session.spec.is_complete() or session.stage == OutfitStage.FINALIZED else None,
    }

    return reply, state_dict
