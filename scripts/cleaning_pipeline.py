#!/usr/bin/env python3
"""Data cleaning pipeline — Blueprint Section 5.

Sequential DAG: Dedup → Quality Filter → Toxicity Filter → Format Conversion.

Usage:
    python scripts/cleaning_pipeline.py --input data/processed/fashion_conversations.json
    python scripts/cleaning_pipeline.py --input data/processed/fashion_conversations.json --stats-only
"""

import argparse
import hashlib
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class CleaningConfig:
    min_tokens: int = 20
    max_tokens: int = 2000
    dedup_threshold: float = 0.85
    toxicity_threshold: float = 0.5
    min_turns: int = 4
    max_turns: int = 20


def _text_hash(text: str) -> str:
    """Simple text fingerprint for deduplication."""
    # Normalize whitespace, lowercase, remove punctuation
    normalized = re.sub(r"[^\w\s]", "", text.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def _token_count(text: str) -> int:
    """Approximate token count (word-based)."""
    return len(text.split())


def _conversation_text(conv: dict) -> str:
    """Extract all text from a conversation."""
    turns = conv.get("conversations", [])
    return " ".join(t.get("value", "") for t in turns)


def step_1_dedup(conversations: list[dict]) -> list[dict]:
    """Step 1: Remove duplicate and near-duplicate conversations."""
    seen_hashes = set()
    deduped = []

    for conv in conversations:
        text = _conversation_text(conv)
        h = _text_hash(text)
        if h not in seen_hashes:
            seen_hashes.add(h)
            deduped.append(conv)

    removed = len(conversations) - len(deduped)
    logger.info("Step 1 (Dedup): %d → %d (removed %d duplicates)", len(conversations), len(deduped), removed)
    return deduped


def step_2_quality_filter(conversations: list[dict], config: CleaningConfig) -> list[dict]:
    """Step 2: Filter by quality — token count, turn count, content checks."""
    filtered = []
    reasons = Counter()

    for conv in conversations:
        turns = conv.get("conversations", [])

        # Turn count check
        if len(turns) < config.min_turns:
            reasons["too_few_turns"] += 1
            continue
        if len(turns) > config.max_turns:
            reasons["too_many_turns"] += 1
            continue

        # Token count check
        total_text = _conversation_text(conv)
        tokens = _token_count(total_text)
        if tokens < config.min_tokens:
            reasons["too_short"] += 1
            continue
        if tokens > config.max_tokens:
            reasons["too_long"] += 1
            continue

        # Check for proper alternation (human/gpt/human/gpt)
        valid_alternation = True
        for i, turn in enumerate(turns):
            expected = "human" if i % 2 == 0 else "gpt"
            if turn.get("from") != expected:
                valid_alternation = False
                break

        if not valid_alternation:
            reasons["bad_alternation"] += 1
            continue

        # Check for non-empty responses
        if any(len(t.get("value", "").strip()) < 10 for t in turns):
            reasons["empty_turn"] += 1
            continue

        # Check for excessive non-alphanumeric characters
        non_alnum_ratio = sum(1 for c in total_text if not c.isalnum() and not c.isspace()) / (len(total_text) + 1)
        if non_alnum_ratio > 0.30:
            reasons["too_much_noise"] += 1
            continue

        filtered.append(conv)

    logger.info("Step 2 (Quality): %d → %d", len(conversations), len(filtered))
    for reason, count in reasons.most_common():
        logger.info("  Removed %d: %s", count, reason)
    return filtered


def step_3_toxicity_filter(conversations: list[dict], config: CleaningConfig) -> list[dict]:
    """Step 3: Filter toxic content."""
    try:
        import detoxify

        model = detoxify.Detoxify("original")
        filtered = []
        toxic_count = 0

        for conv in conversations:
            text = _conversation_text(conv)
            result = model.predict(text[:1000])  # Limit text length for speed
            if result.get("toxicity", 0) < config.toxicity_threshold:
                filtered.append(conv)
            else:
                toxic_count += 1

        logger.info("Step 3 (Toxicity): %d → %d (removed %d toxic)", len(conversations), len(filtered), toxic_count)
        return filtered

    except ImportError:
        logger.warning("Step 3 (Toxicity): Skipped — 'detoxify' not installed (pip install detoxify)")
        return conversations


def step_4_format_validate(conversations: list[dict]) -> list[dict]:
    """Step 4: Ensure proper ShareGPT format and add metadata."""
    validated = []

    for conv in conversations:
        turns = conv.get("conversations", [])

        # Ensure all turns have required fields
        valid = True
        for turn in turns:
            if "from" not in turn or "value" not in turn:
                valid = False
                break
            if turn["from"] not in ("human", "gpt", "system"):
                valid = False
                break

        if valid:
            validated.append(conv)

    logger.info("Step 4 (Format): %d → %d", len(conversations), len(validated))
    return validated


def compute_stats(conversations: list[dict]) -> dict:
    """Compute dataset statistics."""
    total_turns = sum(len(c.get("conversations", [])) for c in conversations)
    total_tokens = sum(_token_count(_conversation_text(c)) for c in conversations)
    turn_counts = [len(c.get("conversations", [])) for c in conversations]

    # Language detection (simple heuristic)
    lang_counts = Counter()
    for conv in conversations:
        text = _conversation_text(conv)
        if any(ord(c) >= 0x0C00 and ord(c) <= 0x0C7F for c in text):
            lang_counts["telugu"] += 1
        elif any(ord(c) >= 0x0900 and ord(c) <= 0x097F for c in text):
            lang_counts["hindi"] += 1
        else:
            lang_counts["english"] += 1

    return {
        "total_conversations": len(conversations),
        "total_turns": total_turns,
        "total_tokens": total_tokens,
        "avg_turns_per_conversation": round(total_turns / max(len(conversations), 1), 1),
        "avg_tokens_per_conversation": round(total_tokens / max(len(conversations), 1), 1),
        "min_turns": min(turn_counts, default=0),
        "max_turns": max(turn_counts, default=0),
        "language_distribution": dict(lang_counts),
    }


def run_pipeline(input_path: str, stats_only: bool = False) -> None:
    """Run the full cleaning pipeline."""
    input_file = Path(input_path)
    if not input_file.is_file():
        logger.error("Input file not found: %s", input_path)
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    logger.info("Loaded %d conversations from %s", len(data), input_path)

    if stats_only:
        stats = compute_stats(data)
        print(json.dumps(stats, indent=2))
        return

    config = CleaningConfig()

    # Run pipeline stages
    data = step_1_dedup(data)
    data = step_2_quality_filter(data, config)
    data = step_3_toxicity_filter(data, config)
    data = step_4_format_validate(data)

    # Compute final stats
    stats = compute_stats(data)
    logger.info("\n=== Final Dataset Stats ===")
    for k, v in stats.items():
        logger.info("  %s: %s", k, v)

    # Save cleaned dataset
    output_path = input_file.parent / f"{input_file.stem}_clean{input_file.suffix}"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info("Cleaned dataset saved to: %s", output_path)


def main():
    parser = argparse.ArgumentParser(description="Fashion dataset cleaning pipeline")
    parser.add_argument("--input", required=True, help="Input JSON file path")
    parser.add_argument("--stats-only", action="store_true", help="Only compute statistics, don't clean")
    args = parser.parse_args()

    run_pipeline(args.input, args.stats_only)


if __name__ == "__main__":
    main()
