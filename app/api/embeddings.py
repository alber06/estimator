"""HTTP layer for the embedding pipeline.

Thin router: it delegates ingest persistence to :class:`EmbeddingIngestionService`
and maps failures to status codes. No business logic lives here.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    ALL_STRATEGIES,
    build_chunkers,
    get_embedder,
    get_embedding_ingestion_service,
    get_semantic_retriever,
)
from app.foundation.persistence.database import get_async_session
from app.generation.rag.analysis.comparison import (
    ChunkingComparator,
    CompareRequest,
    CompareResponse,
)
from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.ingestion_service import DocumentAlreadyIngestedError, EmbeddingIngestionService
from app.generation.rag.retriever import SemanticRetriever
from app.generation.rag.schemas import IngestRequest, IngestResponse, SearchRequest, SearchResponse

log = structlog.get_logger()

router = APIRouter(prefix="/embeddings", tags=["embeddings"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    request: IngestRequest,
    session: AsyncSession = Depends(get_async_session),
    service: EmbeddingIngestionService = Depends(get_embedding_ingestion_service),
) -> IngestResponse:
    """Chunk a budget, embed every chunk, and persist vectors in Postgres."""
    log.info(
        "embeddings_ingest_received",
        source_path=request.source_path,
        document_type=request.document_type,
        budget_id=request.content.budget_id,
    )

    try:
        outcome = await service.ingest(session, request)
    except DocumentAlreadyIngestedError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Document already ingested",
                "document_id": exc.document_id,
            },
        )
    except Exception as exc:  # noqa: BLE001 — any embedding-API failure becomes a 500.
        log.error(
            "embeddings_ingest_failed",
            reason="ingestion_error",
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        raise HTTPException(status_code=500, detail="Failed to ingest embeddings.") from exc

    return IngestResponse(
        document_id=outcome.document_id,
        chunks_created=outcome.chunks_created,
        embedding_dimension=outcome.embedding_dimension,
        ingestion_time_ms=outcome.ingestion_time_ms,
    )


@router.post("/search", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    session: AsyncSession = Depends(get_async_session),
    retriever: SemanticRetriever = Depends(get_semantic_retriever),
) -> SearchResponse:
    """Embed a query and return the nearest chunks by cosine distance."""
    log.info("embeddings_search_received", query_len=len(request.query), k=request.k)

    try:
        return await retriever.search(session, request.query, request.k)
    except Exception as exc:  # noqa: BLE001 — any embedding/DB failure becomes a 500.
        log.error(
            "embeddings_search_failed",
            reason="search_error",
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        raise HTTPException(status_code=500, detail="Failed to search embeddings.") from exc


@router.post("/compare", response_model=CompareResponse)
def compare(
    request: CompareRequest,
    embedder: OpenAIEmbedder | None = Depends(get_embedder),
) -> CompareResponse:
    """Run several chunking strategies over the same budgets and compare them.

    Returns per-strategy corpus stats and, if queries are given, the top-k
    chunks each strategy retrieves. Nothing is persisted (Session 8 territory).
    """
    if embedder is None:
        log.error("embeddings_compare_failed", reason="embedder_unavailable")
        raise HTTPException(status_code=500, detail="Embedding service is not available.")

    names = request.strategies or ALL_STRATEGIES
    try:
        chunkers = build_chunkers(names)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {exc.args[0]}") from exc
    except RuntimeError as exc:
        # A strategy needs an API key that is not configured.
        log.error("embeddings_compare_failed", reason="missing_api_key", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    comparator = ChunkingComparator(chunkers, embedder)
    log.info(
        "embeddings_compare_received",
        total_budgets=len(request.budgets),
        strategies=names,
        n_queries=len(request.queries),
    )
    try:
        stats = comparator.compute_stats(request.budgets)
        queries = comparator.run_queries(request.budgets, request.queries, request.top_k)
    except Exception as exc:  # noqa: BLE001 — any chunker/embedding failure becomes a 500.
        log.error(
            "embeddings_compare_failed",
            reason="comparison_error",
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        raise HTTPException(status_code=500, detail="Failed to run chunking comparison.") from exc

    return CompareResponse(stats_per_strategy=stats, queries_per_strategy=queries)
