from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException
import structlog

from app.embedding_pipeline.chunker import JSONStructuralChunker
from app.embedding_pipeline.embedder import OpenAIEmbedder
from app.embedding_pipeline.schemas import IngestRequest, IngestResponse

log = structlog.get_logger()

router = APIRouter(prefix="/embeddings", tags=["embeddings"])


@lru_cache
def get_chunker() -> JSONStructuralChunker:
    return JSONStructuralChunker()


@lru_cache
def get_embedder() -> OpenAIEmbedder:
    return OpenAIEmbedder()


@router.post("/ingest", response_model=IngestResponse)
def ingest_embeddings(
    request: IngestRequest,
    chunker: JSONStructuralChunker = Depends(get_chunker),
    embedder: OpenAIEmbedder = Depends(get_embedder),
) -> IngestResponse:
    """Ingest a list of embeddings into the database."""
    chunks = chunker.chunk(request.budgets)
    try:
        embedded_chunks, stats = embedder.embed_many(chunks)
        stats.total_budgets = len(request.budgets)
    except Exception as exc:
        log.error(
            "embedding_ingest_failed",
            error=str(exc)[:400],
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="Upstream embedding call failed",
        ) from exc

    return IngestResponse(chunks=embedded_chunks, stats=stats)