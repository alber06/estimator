"""Persist embedded chunks for the RAG corpus.

All DB writes for ``POST /embeddings/ingest`` live here. The router only maps
exceptions to HTTP status codes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.foundation.persistence.models import ChunkRow, DocumentRow
from app.generation.rag.chunking.structural import JSONStructuralChunker
from app.generation.rag.embedding.embedder import EMBEDDING_DIM, OpenAIEmbedder
from app.generation.rag.schemas import Budget, IngestRequest

log = structlog.get_logger()


class DocumentAlreadyIngestedError(Exception):
    """Raised when ``source_path`` is already present in ``documents``."""

    def __init__(self, document_id: int) -> None:
        self.document_id = document_id
        super().__init__(f"Document already ingested (id={document_id})")


@dataclass(frozen=True)
class IngestOutcome:
    document_id: int
    chunks_created: int
    embedding_dimension: int
    ingestion_time_ms: int


class EmbeddingIngestionService:
    """Chunk, embed and persist a single budget document in one transaction."""

    def __init__(
        self,
        *,
        chunker: JSONStructuralChunker,
        embedder: OpenAIEmbedder,
    ) -> None:
        self._chunker = chunker
        self._embedder = embedder

    async def ingest(self, session: AsyncSession, request: IngestRequest) -> IngestOutcome:
        """Run the full ingest pipeline inside the caller's async session."""
        t0 = time.perf_counter()

        async with session.begin():
            existing = await session.scalar(
                select(DocumentRow.id).where(DocumentRow.source_path == request.source_path)
            )
            if existing is not None:
                raise DocumentAlreadyIngestedError(existing)

            budget = request.content
            document = DocumentRow(
                source_path=request.source_path,
                document_type=request.document_type,
                metadata_=_document_metadata(budget),
            )
            session.add(document)
            await session.flush()

            chunks = self._chunker.chunk([budget])
            vectors = self._embedder.embed_texts([chunk.text for chunk in chunks])

            chunk_rows = [
                ChunkRow(
                    document_id=document.id,
                    chunk_type="structural",
                    content=chunk.text,
                    embedding=vector,
                    metadata_={
                        **chunk.metadata,
                        "chunk_id": chunk.chunk_id,
                        "token_count": chunk.token_count,
                    },
                )
                for chunk, vector in zip(chunks, vectors)
            ]
            session.add_all(chunk_rows)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        log.info(
            "embeddings_ingest_done",
            document_id=document.id,
            chunks_created=len(chunk_rows),
            ingestion_time_ms=elapsed_ms,
        )
        return IngestOutcome(
            document_id=document.id,
            chunks_created=len(chunk_rows),
            embedding_dimension=EMBEDDING_DIM,
            ingestion_time_ms=elapsed_ms,
        )


def _document_metadata(budget: Budget) -> dict:
    return {
        "budget_id": budget.budget_id,
        "client_name": budget.client_metadata.name,
        "client_sector": budget.client_metadata.sector,
        "year": budget.year,
        "main_technology": budget.main_technology,
    }
