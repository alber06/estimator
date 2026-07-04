#!/usr/bin/env python3
"""Embed two texts and print their cosine similarity.

Usage::

    uv run python scripts/compare.py --text-a "..." --text-b "..."
    docker compose exec estimator python scripts/compare.py --text-a "..." --text-b "..."
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.embedding_pipeline.embedder import OpenAIEmbedder  # noqa: E402


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute the cosine similarity between two embeddings."""
    
    if len(a) != len(b):
        raise ValueError("embedding dimensions do not match")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        raise ValueError("zero-norm embedding")
    return dot / (norm_a * norm_b)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cosine similarity between two embedded texts.")
    parser.add_argument("--text-a", required=True, help="First text")
    parser.add_argument("--text-b", required=True, help="Second text")
    args = parser.parse_args()

    settings = get_settings()
    embedder = OpenAIEmbedder(model=settings.EMBEDDING_MODEL)

    vec_a = embedder.embed_one(args.text_a)
    vec_b = embedder.embed_one(args.text_b)
    similarity = cosine_similarity(vec_a, vec_b)

    print(f"Text A: {args.text_a}")
    print(f"Text B: {args.text_b}")
    print(f"Cosine similarity: {similarity:.4f}")


if __name__ == "__main__":
    main()
