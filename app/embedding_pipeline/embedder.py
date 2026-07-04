from __future__ import annotations

import time

import structlog
from openai import OpenAI, RateLimitError

from app.embedding_pipeline.schemas import Chunk, EmbeddedChunk, IngestStats

log = structlog.get_logger()

BATCH_SIZE = 100
_RATE_LIMIT_BACKOFF_S = (1, 2, 4)  # waits between retries on RateLimitError

# USD per 1M input tokens for text-embedding-3-small. Update as pricing changes.
_EMBEDDING_INPUT_COST_PER_MILLION_USD = 0.02


def _estimate_embedding_cost_usd(total_tokens: int) -> float:
    return round(total_tokens * _EMBEDDING_INPUT_COST_PER_MILLION_USD / 1_000_000, 6)


class OpenAIEmbedder:
    """An embedder for OpenAI."""

    def __init__(self, model: str = "text-embedding-3-small", *, client: OpenAI | None = None):
        self._model = model
        self._client = client or OpenAI()

    def embed_one(self, text: str) -> list[float]:
        response = self._client.embeddings.create(
            model=self._model,
            input=text,
            dimensions=1536,
        )
        return response.data[0].embedding

    def embed_many(self, chunks: list[Chunk]) -> tuple[list[EmbeddedChunk], IngestStats]:
        if not chunks:
            return [], IngestStats(
                total_budgets=0,
                total_chunks=0,
                total_tokens=0,
                estimated_cost_usd=0.0,
            )

        embedded: list[EmbeddedChunk] = []
        total_tokens = 0

        for batch_start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[batch_start : batch_start + BATCH_SIZE]
            texts = [chunk.text for chunk in batch]

            t0 = time.perf_counter()
            response = self._create_embeddings_with_retry(texts)
            latency_ms = int((time.perf_counter() - t0) * 1000)

            batch_tokens = (
                response.usage.total_tokens
                if response.usage is not None
                else sum(chunk.token_count for chunk in batch)
            )
            total_tokens += batch_tokens

            log.info(
                "embedding_batch_completed",
                model=self._model,
                batch_chunks=len(batch),
                total_tokens=batch_tokens,
                latency_ms=latency_ms,
            )

            for item in sorted(response.data, key=lambda row: row.index):
                chunk = batch[item.index]
                embedded.append(
                    EmbeddedChunk(
                        **chunk.model_dump(),
                        embedding=item.embedding,
                    )
                )

        stats = IngestStats(
            total_budgets=0,
            total_chunks=len(chunks),
            total_tokens=total_tokens,
            estimated_cost_usd=_estimate_embedding_cost_usd(total_tokens),
        )
        return embedded, stats

    def _create_embeddings_with_retry(self, texts: list[str]):
        for attempt in range(len(_RATE_LIMIT_BACKOFF_S) + 1):
            try:
                return self._client.embeddings.create(
                    model=self._model,
                    input=texts,
                    dimensions=1536,
                )
            except RateLimitError:
                if attempt == len(_RATE_LIMIT_BACKOFF_S):
                    raise
                wait_s = _RATE_LIMIT_BACKOFF_S[attempt]
                log.warning(
                    "embedding_batch_rate_limited",
                    model=self._model,
                    attempt=attempt + 1,
                    wait_s=wait_s,
                )
                time.sleep(wait_s)
