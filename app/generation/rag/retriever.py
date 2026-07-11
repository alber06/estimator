"""Semantic retriever — cosine search over persisted chunk embeddings."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.foundation.persistence.models import ChunkRow
from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.schemas import SearchResponse, SearchResult


class SemanticRetriever:
    """Embed a query and return the nearest chunks from Postgres."""

    def __init__(self, embedder: OpenAIEmbedder) -> None:
        self._embedder = embedder

    async def search(self, session: AsyncSession, query: str, k: int) -> SearchResponse:
        t0 = time.perf_counter()
        query_vector = self._embedder.embed_one(query)

        distance = ChunkRow.embedding.cosine_distance(query_vector).label("distance")
        stmt = (
            select(
                ChunkRow.id,
                ChunkRow.document_id,
                ChunkRow.chunk_type,
                ChunkRow.content,
                ChunkRow.metadata_,
                distance,
            )
            .where(ChunkRow.embedding.is_not(None))
            .order_by(distance)
            .limit(k)
        )
        rows = (await session.execute(stmt)).all()
        search_time_ms = round((time.perf_counter() - t0) * 1000)

        return SearchResponse(
            query=query,
            k=k,
            search_time_ms=search_time_ms,
            results=[
                SearchResult(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    chunk_type=row.chunk_type,
                    content=row.content,
                    distance=round(float(row.distance), 3),
                    metadata=row.metadata_ or {},
                )
                for row in rows
            ],
        )
