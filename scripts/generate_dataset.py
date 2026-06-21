#!/usr/bin/env python3
"""Synthetic fashion dataset generator — generates training conversations via Groq.

Blueprint Section 5: Generate 10,000 conversations via Groq free tier.
Generates ~500/day within Groq rate limits (30 RPM).

Usage:
    python scripts/generate_dataset.py --count 500 --output data/processed/fashion_conversations.json
    python scripts/generate_dataset.py --count 50 --dry-run  # Preview without API calls
"""

import argparse
import asyncio
import json
import logging
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Persona Templates (Blueprint: diverse user profiles) ─────────────────

USER_PERSONAS = [
    {"age": 22, "gender": "woman", "city": "Hyderabad", "language": "te", "context": "college student"},
    {"age": 25, "gender": "woman", "city": "Hyderabad", "language": "te", "context": "IT professional"},
    {"age": 28, "gender": "woman", "city": "Vijayawada", "language": "te", "context": "newly married"},
    {"age": 35, "gender": "woman", "city": "Tirupati", "language": "te", "context": "temple devotee"},
    {"age": 45, "gender": "woman", "city": "Warangal", "language": "te", "context": "school teacher"},
    {"age": 30, "gender": "man", "city": "Hyderabad", "language": "te", "context": "software engineer"},
    {"age": 24, "gender": "woman", "city": "Mumbai", "language": "hi", "context": "fashion blogger"},
    {"age": 32, "gender": "woman", "city": "Delhi", "language": "hi", "context": "working mother"},
    {"age": 27, "gender": "man", "city": "Jaipur", "language": "hi", "context": "startup founder"},
    {"age": 40, "gender": "woman", "city": "Lucknow", "language": "hi", "context": "homemaker"},
    {"age": 20, "gender": "woman", "city": "Bangalore", "language": "en", "context": "design student"},
    {"age": 33, "gender": "woman", "city": "Chennai", "language": "en", "context": "corporate lawyer"},
    {"age": 29, "gender": "man", "city": "Pune", "language": "en", "context": "gym enthusiast"},
    {"age": 50, "gender": "woman", "city": "Kochi", "language": "en", "context": "boutique owner"},
    {"age": 38, "gender": "woman", "city": "Kolkata", "language": "en", "context": "artist"},
]

# ── Occasion Templates ───────────────────────────────────────────────────

OCCASIONS = [
    "wedding (bride/groom)", "wedding (guest)", "reception", "engagement",
    "mehendi ceremony", "haldi ceremony", "sangeet night", "baby shower",
    "temple visit", "puja / religious ceremony", "Diwali party", "Holi celebration",
    "Eid celebration", "Christmas party", "New Year's Eve", "Durga Puja",
    "office formal", "office casual Friday", "job interview", "board meeting",
    "college farewell", "college fest", "first date", "anniversary dinner",
    "beach vacation", "hill station trip", "casual shopping trip",
    "gym / workout", "yoga class", "evening cocktail party",
    "art gallery opening", "music concert", "friend's birthday party",
    "family get-together", "house warming ceremony", "graduation ceremony",
]

# ── Fashion Topics ───────────────────────────────────────────────────────

TOPICS = [
    "color theory for {skin_tone} skin tone",
    "body type dressing for {body_type} shape",
    "fabric guide for {season} season in {region}",
    "accessory styling for {garment}",
    "draping styles for {garment}",
    "budget outfit under ₹{budget}",
    "color combinations with {color}",
    "wardrobe capsule for {lifestyle}",
    "sustainable fashion choices",
    "mix-and-match existing wardrobe",
    "traditional vs fusion styling",
    "jewelry pairing with {garment}",
    "footwear selection for {occasion}",
    "makeup coordination with {color} outfit",
    "seasonal trend adaptation for Indian wear",
]

SKIN_TONES = ["fair", "wheatish", "dusky", "dark", "medium"]
BODY_TYPES = ["pear", "apple", "hourglass", "rectangle", "inverted triangle", "plus size", "petite", "tall"]
SEASONS = ["summer", "monsoon", "winter", "spring"]
REGIONS = ["South India", "North India", "Western India", "Eastern India"]
GARMENTS = ["saree", "lehenga", "kurta", "salwar kameez", "anarkali", "sherwani", "dhoti"]
COLORS = ["red", "blue", "green", "gold", "pink", "black", "white", "maroon", "teal", "purple"]
BUDGETS = ["2000", "3000", "5000", "8000", "10000", "15000", "20000"]
LIFESTYLES = ["working professional", "college student", "stay-at-home mom", "freelancer"]

# ── System Prompt (Blueprint: expert Telugu fashion stylist) ─────────────

SYSTEM_PROMPT = """You are AURA, an elite AI fashion stylist specializing in Indian ethnic and contemporary fashion. You have the wisdom of an experienced fashion designer with 20+ years of expertise.

Your knowledge covers:
- 40+ Indian fabric types (Banarasi silk, Kanjeevaram, Chanderi, Tussar, Georgette, Chiffon, etc.)
- 25+ garment categories with regional variations
- Color theory for all Indian skin tones (Fitzpatrick II-VI)
- Body type dressing for 8 body shapes
- 12+ draping styles for saree and dupatta
- Regional fashion traditions (South Indian, North Indian, Western Indian, Eastern Indian)
- Budget-conscious recommendations (₹1,000 to ₹50,000+ range)
- Occasion-appropriate dressing for 35+ Indian occasions
- Seasonal fashion adaptation for Indian climate
- Jewelry, footwear, and accessory pairing
- Tailoring measurements and fabric yardage calculations

Response style:
- Warm, encouraging, culturally sensitive
- Use code-mixed language naturally when the user speaks in Telugu or Hindi
- Give specific, actionable advice (not generic)
- Include budget breakdowns when relevant
- Mention specific brands/platforms (Myntra, AJIO, FabIndia, Nalli, etc.)
- Explain the "why" behind fashion choices (body shape flattering, color psychology, cultural significance)
- Use emoji sparingly but naturally"""


def _build_generation_prompt(persona: dict, occasion: str, topic: str) -> str:
    """Build a prompt for conversation generation."""
    lang_instruction = {
        "te": "The user speaks in code-mixed Telugu-English. Respond naturally in Telugu-English mix. Use Telugu script for common words.",
        "hi": "The user speaks in code-mixed Hindi-English. Respond naturally in Hindi-English mix. Use Devanagari for common words.",
        "en": "The user speaks in English. Respond in clear, warm English.",
    }

    return f"""Generate a realistic fashion consultation conversation between a user and AURA (AI fashion stylist).

USER PROFILE:
- {persona['age']}-year-old {persona['gender']} from {persona['city']}
- Context: {persona['context']}
- Language: {lang_instruction.get(persona['language'], lang_instruction['en'])}

CONVERSATION TOPIC: {topic}
OCCASION: {occasion}

REQUIREMENTS:
1. Generate exactly 4-6 conversation turns (alternating human/gpt)
2. The user should ask natural, specific questions (not generic)
3. AURA should give detailed, expert advice with specific recommendations
4. Include at least one budget mention, one fabric/material recommendation, and one styling tip
5. Make the conversation feel natural and warm, not robotic
6. If the user is Telugu/Hindi speaking, use natural code-mixing

OUTPUT FORMAT (strict JSON):
{{
  "conversations": [
    {{"from": "human", "value": "user message here"}},
    {{"from": "gpt", "value": "AURA's detailed response here"}},
    ...more turns...
  ]
}}

Output ONLY the JSON object, nothing else."""


async def generate_conversation(persona: dict, occasion: str, topic: str) -> dict | None:
    """Generate a single conversation via Groq API directly."""
    import os

    prompt = _build_generation_prompt(persona, occasion, topic)
    api_key = os.environ.get("GROQ_API_KEY", "")

    if not api_key:
        logger.error("GROQ_API_KEY not set — cannot generate training data")
        return None

    try:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 2000,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            result = resp.json()

        response = result["choices"][0]["message"]["content"].strip()

        # Extract JSON from response (handle markdown wrapping)
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]

        data = json.loads(response)
        if "conversations" in data and len(data["conversations"]) >= 4:
            return data
        else:
            logger.warning("Generated conversation too short (%d turns), skipping", len(data.get("conversations", [])))
            return None

    except json.JSONDecodeError as e:
        logger.warning("Failed to parse JSON response: %s", str(e)[:100])
        return None
    except Exception as e:
        logger.warning("Generation failed: %s", str(e)[:100])
        return None


def _fill_topic(topic_template: str) -> str:
    """Fill in topic template variables."""
    return topic_template.format(
        skin_tone=random.choice(SKIN_TONES),
        body_type=random.choice(BODY_TYPES),
        season=random.choice(SEASONS),
        region=random.choice(REGIONS),
        garment=random.choice(GARMENTS),
        color=random.choice(COLORS),
        budget=random.choice(BUDGETS),
        lifestyle=random.choice(LIFESTYLES),
        occasion=random.choice(OCCASIONS),
    )


async def generate_batch(count: int, output_path: str, dry_run: bool = False) -> None:
    """Generate a batch of conversations."""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Load existing conversations if file exists
    existing = []
    if output_file.is_file():
        with open(output_file, "r", encoding="utf-8") as f:
            existing = json.load(f)
        logger.info("Loaded %d existing conversations", len(existing))

    conversations = list(existing)
    generated = 0
    failed = 0

    for i in range(count):
        persona = random.choice(USER_PERSONAS)
        occasion = random.choice(OCCASIONS)
        topic = _fill_topic(random.choice(TOPICS))

        if dry_run:
            prompt = _build_generation_prompt(persona, occasion, topic)
            logger.info(
                "[DRY RUN %d/%d] Persona: %s %s from %s | Occasion: %s | Topic: %s",
                i + 1, count, persona["age"], persona["gender"], persona["city"],
                occasion, topic,
            )
            if i == 0:
                print("\n--- Sample Prompt ---")
                print(prompt[:500])
                print("---\n")
            continue

        logger.info("[%d/%d] Generating: %s from %s — %s", i + 1, count, persona["context"], persona["city"], occasion)

        result = await generate_conversation(persona, occasion, topic)
        if result:
            conversations.append(result)
            generated += 1

            # Save incrementally every 10 conversations
            if generated % 10 == 0:
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(conversations, f, ensure_ascii=False, indent=2)
                logger.info("Saved %d conversations (total: %d)", generated, len(conversations))
        else:
            failed += 1

        # Rate limiting: 2s between calls to stay within 30 RPM
        await asyncio.sleep(2.5)

    # Final save
    if not dry_run:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(conversations, f, ensure_ascii=False, indent=2)

    logger.info("\n=== Generation Complete ===")
    logger.info("Generated: %d | Failed: %d | Total in file: %d", generated, failed, len(conversations))


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic fashion training data via Groq")
    parser.add_argument("--count", type=int, default=50, help="Number of conversations to generate")
    parser.add_argument("--output", default="data/processed/fashion_conversations.json", help="Output file path")
    parser.add_argument("--dry-run", action="store_true", help="Preview prompts without API calls")
    args = parser.parse_args()

    asyncio.run(generate_batch(args.count, args.output, args.dry_run))


if __name__ == "__main__":
    main()
