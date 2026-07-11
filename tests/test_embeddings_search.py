"""Tests for POST /embeddings/search."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_semantic_retriever
from app.generation.rag.retriever import SemanticRetriever
from app.generation.rag.schemas import SearchResponse, SearchResult
from app.main import app


class FakeRetriever:
    def __init__(self, response: SearchResponse | None = None):
        self.response = response or SearchResponse(
            query="REST API with OAuth authentication for fintech sector",
            k=5,
            search_time_ms=87,
            results=[
                SearchResult(
                    chunk_id=156,
                    document_id=12,
                    chunk_type="budget_component",
                    content="Backend service implementation with JWT-based authentication...",
                    distance=0.231,
                    metadata={"scope": "backend", "technologies": ["python", "fastapi"]},
                )
            ],
        )
        self.last_query: str | None = None
        self.last_k: int | None = None

    async def search(self, session, query: str, k: int) -> SearchResponse:
        self.last_query = query
        self.last_k = k
        return self.response


@pytest.fixture
def search_client():
    fake = FakeRetriever()
    app.dependency_overrides[get_semantic_retriever] = lambda: fake
    with TestClient(app) as client:
        yield client, fake
    app.dependency_overrides.clear()


def test_search_returns_ranked_chunks(search_client):
    client, fake = search_client
    payload = {
        "query": "REST API with OAuth authentication for fintech sector",
        "k": 5,
    }

    response = client.post("/embeddings/search", json=payload)

    assert response.status_code == 200
    assert response.json() == {
        "query": payload["query"],
        "k": 5,
        "search_time_ms": 87,
        "results": [
            {
                "chunk_id": 156,
                "document_id": 12,
                "chunk_type": "budget_component",
                "content": "Backend service implementation with JWT-based authentication...",
                "distance": 0.231,
                "metadata": {"scope": "backend", "technologies": ["python", "fastapi"]},
            }
        ],
    }
    assert fake.last_query == payload["query"]
    assert fake.last_k == 5


def test_search_defaults_k_to_five(search_client):
    client, fake = search_client
    response = client.post(
        "/embeddings/search",
        json={"query": "OAuth fintech API"},
    )

    assert response.status_code == 200
    assert response.json()["k"] == 5
    assert fake.last_k == 5


def test_search_validates_empty_query(client: TestClient):
    response = client.post("/embeddings/search", json={"query": ""})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_retriever_executes_cosine_distance_query():
    embedder = MagicMock()
    embedder.embed_one.return_value = [0.2] * 1536

    session = AsyncMock()
    row = SimpleNamespace(
        id=156,
        document_id=12,
        chunk_type="budget_component",
        content="Backend service implementation with JWT-based authentication...",
        metadata_={"scope": "backend", "technologies": ["python", "fastapi"]},
        distance=0.2314,
    )
    session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[row])))

    retriever = SemanticRetriever(embedder=embedder)
    response = await retriever.search(session, "REST API with OAuth authentication for fintech sector", 5)

    embedder.embed_one.assert_called_once_with(
        "REST API with OAuth authentication for fintech sector"
    )
    session.execute.assert_awaited_once()
    assert response.k == 5
    assert len(response.results) == 1
    assert response.results[0].chunk_id == 156
    assert response.results[0].distance == 0.231
    assert response.results[0].metadata == {
        "scope": "backend",
        "technologies": ["python", "fastapi"],
    }
    assert response.search_time_ms >= 0
