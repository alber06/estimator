"""End-to-end tests for POST /sessions/{session_id}/estimate."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_estimation_service
from app.main import app
from app.schemas.estimation import EstimationResponse, EstimationResult
from app.schemas.session import Message, ProjectMetadata


def _canned_result() -> EstimationResult:
    return EstimationResult(
        summary="Mid-sized B2B SaaS for equipment loans across teams.",
        total_duration_weeks=8,
        total_cost_eur=30_000,
        confidence_pct=70,
        phases=[
            {
                "name": "Discovery",
                "duration_weeks": 1,
                "cost_eur": 5_000,
                "summary": "Workshops, scoping and tech spike.",
            },
            {
                "name": "Implementation",
                "duration_weeks": 6,
                "cost_eur": 20_000,
                "summary": "Build the core SaaS features.",
            },
            {
                "name": "QA + launch",
                "duration_weeks": 1,
                "cost_eur": 5_000,
                "summary": "Test pass and production rollout.",
            },
        ],
    )


class FakeEstimationService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def estimate_conversation(self, **kwargs) -> EstimationResponse:
        self.calls.append(kwargs)
        session = kwargs["session"]
        return EstimationResponse(
            result=_canned_result(),
            prompt_version="v2",
            cached=False,
            project_metadata=session.project_metadata,
            messages=[
                Message(role="user", content=kwargs["transcript"]),
                Message(role="assistant", content=_canned_result().model_dump_json()),
            ],
        )


@pytest.fixture
def fake_service() -> FakeEstimationService:
    svc = FakeEstimationService()
    app.dependency_overrides[get_estimation_service] = lambda: svc
    yield svc
    app.dependency_overrides.pop(get_estimation_service, None)


VALID_FORM = {
    "transcript": "A small B2B SaaS to manage employee equipment loans across teams.",
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "phases_table",
}


def test_session_estimate_forwards_to_estimate_conversation(
    client: TestClient,
    fake_service: FakeEstimationService,
) -> None:
    create = client.post("/sessions")
    assert create.status_code == 200
    session_id = create.json()["session_id"]

    response = client.post(f"/sessions/{session_id}/estimate", data=VALID_FORM)
    assert response.status_code == 200
    body = response.json()
    assert body["prompt_version"] == "v2"
    assert body["cached"] is False
    assert body["project_metadata"] == ProjectMetadata().model_dump()
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["role"] == "assistant"
    assert len(fake_service.calls) == 1
    call = fake_service.calls[0]
    assert call["transcript"] == VALID_FORM["transcript"]
    assert call["project_type"].value == "web_saas"
    assert call["session"].id == uuid.UUID(session_id)


def test_session_estimate_returns_404_for_unknown_session(
    client: TestClient,
    fake_service: FakeEstimationService,
) -> None:
    unknown_id = uuid.uuid4()
    response = client.post(f"/sessions/{unknown_id}/estimate", data=VALID_FORM)
    assert response.status_code == 404
    assert fake_service.calls == []
