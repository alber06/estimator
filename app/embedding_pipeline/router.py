from fastapi import APIRouter, HTTPException
import structlog

from app.embedding_pipeline.chunker import JSONStructuralChunker
from app.embedding_pipeline.embedder import OpenAIEmbedder
from app.embedding_pipeline.schemas import IngestRequest, IngestResponse

log = structlog.get_logger()

router = APIRouter(prefix="/embeddings", tags=["embeddings"])


@router.post("/ingest", response_model=IngestResponse)
def ingest_embeddings(
    request: IngestRequest,
    chunker: JSONStructuralChunker = JSONStructuralChunker(),
    embedder: OpenAIEmbedder = OpenAIEmbedder(),
) -> IngestResponse:
    """Ingest a list of embeddings into the database."""
    chunks = chunker.chunk(request.budgets)
    try:
        embedded_chunks, stats = embedder.embed_many(chunks)
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