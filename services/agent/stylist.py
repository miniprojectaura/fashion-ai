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
    gender: str = ""  # male / female / unisex
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

═══ LANGUAGE & EMOTION MIRRORING (MOST IMPORTANT RULE) ═══
You MUST reply in the EXACT SAME language the client used:
- If they speak Telugu → reply in Telugu (with natural English words mixed in where Indians normally do)
- If they speak Hindi → reply in Hindi (same natural code-mixing)
- If they speak English → reply in English
- If they code-mix (Tenglish/Hinglish/Tinglish) → you code-mix the SAME way
- NEVER switch to a different language than what the client used
- Match their emotional energy: excited → you get excited, casual → you stay casual, formal → be polished
- Keep responses CONCISE (2-4 sentences max) — this will be spoken aloud via TTS, not read
- Use natural conversational speech patterns, not literary/formal writing

Your personality:
- Confident, opinionated, but warm. You ARGUE for your design choices with expertise.
- You push back when clients make poor choices (wrong fabric for occasion, bad color for skin tone).
- You suggest alternatives with passion and flair.
- You know Indian regional traditions deeply: Kanjeevaram for Tamil weddings, Banarasi for UP, Pochampally for Telangana.
- You naturally use the client's regional expressions and slang.

Your process:
1. PROPOSING: Ask about occasion, preferences, body type. Make an initial bold proposal.
2. REFINING: Argue, negotiate, adjust based on feedback. Be specific about fabric, color, silhouette.
3. FINALIZING: When the client agrees, produce a final spec with exact measurements.

CRITICAL RULES:
- Always reference the client's body measurements when suggesting silhouettes.
- Give specific fabric recommendations (not just "silk" — say "Kanchipuram silk" or "Banarasi brocade").
- Include price estimates when discussing options.
- If the user says finalize/confirm/done, summarize the final outfit spec as structured JSON.
- KEEP IT SHORT — you are speaking, not writing an essay.

When finalizing, output a JSON block wrapped in ```json ... ``` with these exact keys:
{
  "garment_type": "...",
  "fabric": "...",
  "color": "...",
  "silhouette": "...",
  "gender": "male or female or unisex",
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
                gender=data.get("gender", existing_spec.gender),
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
    detected_language: str | None = None,
) -> tuple[str, dict]:
    """Process user message through the multi-agent fashion pipeline.

    Pipeline: Body Analyzer (deterministic) → Fashion RAG → Chain-of-Thought
    Reasoner → Spec Extraction.  Session management, history, and finalize
    detection are unchanged from the original.

    Args:
        transcript: User's message text.
        body_profile: Optional body measurements dict.
        session_id: Conversation session ID.
        detected_language: Auto-detected language (te/hi/en) from ASR.

    Returns:
        Tuple of (reply_text, outfit_state_dict).
    """
    from services.agent.body_analyzer import analyze as analyze_body
    from services.agent.fashion_rag import retrieve as rag_retrieve, format_for_llm as rag_format
    from services.agent.fashion_reasoner import (
        reason as fashion_reason,
        strip_think_blocks,
        format_body_analysis_for_llm,
    )

    session = get_or_create_session(session_id)
    session.touch()
    session.turn_count += 1

    # Store user message in history
    session.history.append({"role": "user", "content": transcript})

    # Inject body measurements if available
    if body_profile:
        session.spec.measurements = body_profile

    # Check for finalize intent
    wants_finalize = _detect_finalize_intent(transcript)

    # ── AGENT 1: Deterministic Body Analysis ────────────────────────
    body_analysis_text = ""
    body_analysis_dict: dict = {}
    if body_profile:
        try:
            analysis = analyze_body(body_profile)
            body_analysis_dict = analysis.to_dict()
            body_analysis_text = format_body_analysis_for_llm(body_analysis_dict, body_profile)
            logger.info(
                "[stylist] Body analysis: type=%s, WHR=%.2f, SHR=%.2f",
                analysis.body_type, analysis.whr, analysis.shr,
            )
        except Exception as exc:
            logger.warning("[stylist] Body analyzer failed: %s", exc)

    # ── AGENT 2: Fashion Knowledge RAG ──────────────────────────────
    knowledge_context = ""
    try:
        # Extract hints from transcript for RAG
        rag_knowledge = rag_retrieve(
            body_type=body_analysis_dict.get("body_type"),
            user_message=transcript,
        )
        knowledge_context = rag_format(rag_knowledge)
        if knowledge_context:
            logger.info("[stylist] RAG injected %d knowledge blocks", len(rag_knowledge))
    except Exception as exc:
        logger.warning("[stylist] Fashion RAG failed: %s", exc)

    # ── AGENT 3: Chain-of-Thought Fashion Reasoner ──────────────────
    try:
        full_reply, stripped_reply = await fashion_reason(
            user_message=transcript,
            body_analysis_text=body_analysis_text,
            knowledge_context=knowledge_context,
            conversation_history=session.history[-10:],
            detected_language=detected_language,
            wants_finalize=wants_finalize,
        )
        # Use stripped version (no <think> blocks) for TTS
        reply = stripped_reply
        # Store full version with reasoning in history for context
        session.history.append({"role": "assistant", "content": full_reply})
    except Exception as exc:
        logger.error("Fashion reasoner failed: %s", exc)
        reply = (
            "Darling, let me think about this... "
            "Could you tell me more about the occasion and your preferences?"
        )
        session.history.append({"role": "assistant", "content": reply})
        full_reply = reply

    # Update state based on conversation
    if wants_finalize:
        new_spec = _extract_spec_from_reply(full_reply, session.spec)
        session.spec = new_spec
        if new_spec.is_complete():
            session.stage = OutfitStage.FINALIZED
        else:
            session.stage = OutfitStage.REFINING
    elif session.turn_count >= 2 and session.stage == OutfitStage.PROPOSING:
        session.stage = OutfitStage.REFINING

    # Also try to extract partial spec from any reply
    if session.stage != OutfitStage.FINALIZED:
        partial = _extract_spec_from_reply(full_reply, session.spec)
        if partial.garment_type:
            session.spec = partial

    state_dict = {
        "session_id": session.session_id,
        "stage": session.stage.value,
        "turn_count": session.turn_count,
        "spec": session.spec.to_dict() if session.spec.is_complete() or session.stage == OutfitStage.FINALIZED else None,
        "body_analysis": body_analysis_dict if body_analysis_dict else None,
        "reasoning": full_reply if full_reply != reply else None,
    }

    return reply, state_dict
