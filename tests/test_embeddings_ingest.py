"""Tests for POST /embeddings/ingest."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_embedding_ingestion_service
from app.generation.rag.ingestion_service import (
    DocumentAlreadyIngestedError,
    EmbeddingIngestionService,
    IngestOutcome,
)
from app.generation.rag.schemas import Budget, IngestRequest
from app.main import app

SAMPLE_BUDGET = json.loads(
    Path(__file__).resolve().parents[1].joinpath("data/budgets_sample.json").read_text()
)[0]


@pytest.fixture
def ingest_payload() -> dict:
    return {
        "source_path": "data/budgets/budget_2024_q1_fintech.json",
        "document_type": "historical_budget",
        "content": SAMPLE_BUDGET,
    }


class FakeIngestionService:
    def __init__(self, *, outcome: IngestOutcome | None = None, conflict_id: int | None = None):
        self.outcome = outcome or IngestOutcome(
            document_id=42,
            chunks_created=4,
            embedding_dimension=1536,
            ingestion_time_ms=120,
        )
        self.conflict_id = conflict_id
        self.last_request: IngestRequest | None = None

    async def ingest(self, session, request: IngestRequest) -> IngestOutcome:
        self.last_request = request
        if self.conflict_id is not None:
            raise DocumentAlreadyIngestedError(self.conflict_id)
        return self.outcome


@pytest.fixture
def ingest_client():
    fake = FakeIngestionService()
    app.dependency_overrides[get_embedding_ingestion_service] = lambda: fake
    with TestClient(app) as client:
        yield client, fake
    app.dependency_overrides.clear()


def test_ingest_returns_identifiers_and_metrics(ingest_client, ingest_payload):
    client, fake = ingest_client
    response = client.post("/embeddings/ingest", json=ingest_payload)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "document_id": 42,
        "chunks_created": 4,
        "embedding_dimension": 1536,
        "ingestion_time_ms": 120,
    }
    assert fake.last_request is not None
    assert fake.last_request.source_path == ingest_payload["source_path"]
    assert isinstance(fake.last_request.content, Budget)


def test_ingest_conflict_returns_409_with_document_id(ingest_client, ingest_payload):
    client, fake = ingest_client
    fake.conflict_id = 99

    response = client.post("/embeddings/ingest", json=ingest_payload)

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Document already ingested",
        "document_id": 99,
    }


def test_ingest_validates_budget_content(client: TestClient):
    payload = {
        "source_path": "data/budgets/bad.json",
        "document_type": "historical_budget",
        "content": {"budget_id": "X"},
    }
    response = client.post("/embeddings/ingest", json=payload)
    assert response.status_code == 422


def _async_session_mock(*, existing_id: int | None = None) -> AsyncMock:
    session = AsyncMock()
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=tx)
    session.scalar = AsyncMock(return_value=existing_id)
    return session
@pytest.mark.asyncio
async def test_service_persists_document_and_chunks():
    chunker = MagicMock()
    chunker.chunk.return_value = [
        MagicMock(
            chunk_id="BUD-2024-001::AUTH-001",
            text="chunk text",
            metadata={"budget_id": "BUD-2024-001"},
            token_count=12,
        )
    ]
    embedder = MagicMock()
    embedder.embed_texts.return_value = [[0.1] * 1536]

    session = _async_session_mock()

    document_holder: dict = {}

    def _capture_document(row):
        document_holder["row"] = row
        row.id = 7

    session.add = MagicMock(side_effect=_capture_document)
    session.flush = AsyncMock()
    session.add_all = MagicMock()

    service = EmbeddingIngestionService(chunker=chunker, embedder=embedder)
    request = IngestRequest(
        source_path="data/budgets/budget_2024_q1_fintech.json",
        document_type="historical_budget",
        content=Budget.model_validate(SAMPLE_BUDGET),
    )

    outcome = await service.ingest(session, request)

    assert outcome.document_id == 7
    assert outcome.chunks_created == 1
    assert outcome.embedding_dimension == 1536
    chunker.chunk.assert_called_once()
    embedder.embed_texts.assert_called_once_with(["chunk text"])
    session.add_all.assert_called_once()
    added_chunks = session.add_all.call_args.args[0]
    assert len(added_chunks) == 1
    assert added_chunks[0].document_id == 7
    assert added_chunks[0].embedding == [0.1] * 1536


@pytest.mark.asyncio
async def test_service_raises_when_source_path_exists():
    session = _async_session_mock(existing_id=55)

    service = EmbeddingIngestionService(
        chunker=MagicMock(),
        embedder=MagicMock(),
    )
    request = IngestRequest(
        source_path="data/budgets/budget_2024_q1_fintech.json",
        document_type="historical_budget",
        content=Budget.model_validate(SAMPLE_BUDGET),
    )

    with pytest.raises(DocumentAlreadyIngestedError) as exc:
        await service.ingest(session, request)

    assert exc.value.document_id == 55
