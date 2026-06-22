"""HTTP integration tests for multi-turn session estimation."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_estimation_service, get_session_store
from app.main import app
from app.schemas.estimation import (
    DetailLevel,
    EstimationResult,
    OutputFormat,
    ProjectType,
)
from app.schemas.session import ProjectMetadata
from app.services.estimation import EstimationService
from app.services.session import SessionStore


def _canned_result(*, total_cost_eur: int = 30_000) -> EstimationResult:
    return EstimationResult(
        summary="Mid-sized B2B SaaS for equipment loans across teams.",
        total_duration_weeks=8,
        total_cost_eur=total_cost_eur,
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
                "cost_eur": total_cost_eur - 10_000,
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


def _minimal_pdf_with_text(text: str) -> bytes:
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        + f"4 0 obj<</Length {len(content)}>>stream\n".encode()
        + content.encode()
        + b"\nendstream\nendobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"xref\n0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000266 00000 n \n"
        b"0000000370 00000 n \n"
        b"trailer<</Size 6/Root 1 0 R>>\n"
        b"startxref\n438\n%%EOF"
    )


VALID_FORM = {
    "transcript": "A small B2B SaaS to manage employee equipment loans across teams.",
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "phases_table",
}


@pytest.fixture
async def async_client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def fresh_store() -> SessionStore:
    store = SessionStore()
    app.dependency_overrides[get_session_store] = lambda: store
    yield store
    app.dependency_overrides.pop(get_session_store, None)


def _install_estimation_service(
    *,
    on_complete_structured: Callable[..., tuple[Any, dict[str, str]]],
) -> MagicMock:
    llm_wrapper = MagicMock()

    def _route(**kwargs: Any) -> tuple[Any, dict[str, str]]:
        if "messages" in kwargs:
            last_user = next(
                message["content"]
                for message in reversed(kwargs["messages"])
                if message["role"] == "user"
            )
            return on_complete_structured(
                response_model=kwargs["response_model"],
                user_message=last_user,
            )
        return on_complete_structured(**kwargs)

    llm_wrapper.complete_structured.side_effect = on_complete_structured
    llm_wrapper.complete_structured_with_messages.side_effect = _route
    service = EstimationService(
        llm_wrapper=llm_wrapper,
        exact_cache=MagicMock(),
        semantic_cache=None,
        openai_client=None,
    )
    app.dependency_overrides[get_estimation_service] = lambda: service
    return llm_wrapper


@pytest.fixture
def estimation_service_override() -> Callable[..., MagicMock]:
    installed: list[MagicMock] = []

    def _install(**kwargs: Any) -> MagicMock:
        llm_wrapper = _install_estimation_service(**kwargs)
        installed.append(llm_wrapper)
        return llm_wrapper

    yield _install
    app.dependency_overrides.pop(get_estimation_service, None)


def _count_conversation_turns(messages: list[dict[str, str]]) -> int:
    return sum(1 for message in messages if message["role"] in {"user", "assistant"}) // 2


@pytest.mark.asyncio
async def test_project_metadata_verification(
    async_client: AsyncClient,
    fresh_store: SessionStore,
    estimation_service_override: Callable[..., MagicMock],
) -> None:
    metadata_queue = [
        ProjectMetadata(project_name="LoanDesk", mentioned_technologies=["Python"]),
        ProjectMetadata(assumed_team_size=5, agreed_scope="Auth and dashboards"),
    ]

    def complete_structured(**kwargs: Any) -> tuple[Any, dict[str, str]]:
        response_model = kwargs["response_model"]
        if response_model is EstimationResult:
            return _canned_result(), {"model": "test"}
        if response_model is ProjectMetadata:
            return metadata_queue.pop(0), {"model": "test"}
        raise AssertionError(f"Unexpected response_model: {response_model}")

    estimation_service_override(on_complete_structured=complete_structured)

    create = await async_client.post("/sessions")
    assert create.status_code == 200
    session_id = create.json()["session_id"]

    first = await async_client.post(f"/sessions/{session_id}/estimate", data=VALID_FORM)
    assert first.status_code == 200
    first_metadata = first.json()["project_metadata"]
    assert first_metadata["project_name"] == "LoanDesk"
    assert first_metadata["mentioned_technologies"] == ["Python"]
    assert first_metadata["assumed_team_size"] is None

    second_form = {
        **VALID_FORM,
        "transcript": "Add role-based dashboards and SSO for the LoanDesk MVP rollout.",
    }
    second = await async_client.post(f"/sessions/{session_id}/estimate", data=second_form)
    assert second.status_code == 200
    second_metadata = second.json()["project_metadata"]
    assert second_metadata["project_name"] == "LoanDesk"
    assert second_metadata["assumed_team_size"] == 5
    assert second_metadata["agreed_scope"] == "Auth and dashboards"
    assert second_metadata["mentioned_technologies"] == ["Python"]

    session = fresh_store.get(uuid.UUID(session_id))
    assert session is not None
    assert session.project_metadata.project_name == "LoanDesk"
    assert session.project_metadata.assumed_team_size == 5


@pytest.mark.asyncio
async def test_pdf_attachment(
    async_client: AsyncClient,
    estimation_service_override: Callable[..., MagicMock],
) -> None:
    marker = "REQUIRES_BLOCKCHAIN_MODULE"

    def complete_structured(**kwargs: Any) -> tuple[Any, dict[str, str]]:
        response_model = kwargs["response_model"]
        if response_model is EstimationResult:
            user_message = kwargs["user_message"]
            total_cost = 55_000 if marker in user_message else 30_000
            return _canned_result(total_cost_eur=total_cost), {"model": "test"}
        if response_model is ProjectMetadata:
            return ProjectMetadata(), {"model": "test"}
        raise AssertionError(f"Unexpected response_model: {response_model}")

    estimation_service_override(on_complete_structured=complete_structured)

    create = await async_client.post("/sessions")
    session_id = create.json()["session_id"]

    without_pdf = await async_client.post(f"/sessions/{session_id}/estimate", data=VALID_FORM)
    assert without_pdf.status_code == 200
    assert without_pdf.json()["result"]["total_cost_eur"] == 30_000

    pdf_bytes = _minimal_pdf_with_text(marker)
    with_pdf = await async_client.post(
        f"/sessions/{session_id}/estimate",
        data=VALID_FORM,
        files=[("attachments", ("spec.pdf", BytesIO(pdf_bytes), "application/pdf"))],
    )
    assert with_pdf.status_code == 200
    assert with_pdf.json()["result"]["total_cost_eur"] == 55_000


@pytest.mark.asyncio
async def test_eight_turn_session(
    async_client: AsyncClient,
    fresh_store: SessionStore,
    estimation_service_override: Callable[..., MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    max_turns = 6
    monkeypatch.setenv("SESSION_MAX_TURNS", str(max_turns))
    from app.config import get_settings

    get_settings.cache_clear()

    llm_history_snapshots: list[list[dict[str, str]]] = []

    def complete_structured(**kwargs: Any) -> tuple[Any, dict[str, str]]:
        response_model = kwargs["response_model"]
        if response_model is EstimationResult:
            return _canned_result(), {"model": "test"}
        if response_model is ProjectMetadata:
            return ProjectMetadata(), {"model": "test"}
        raise AssertionError(f"Unexpected response_model: {response_model}")

    estimation_service_override(on_complete_structured=complete_structured)

    create = await async_client.post("/sessions")
    session_id = create.json()["session_id"]

    for turn in range(1, 9):
        response = await async_client.post(
            f"/sessions/{session_id}/estimate",
            data={
                **VALID_FORM,
                "transcript": (
                    f"Turn {turn}: we need a B2B SaaS for equipment loan management "
                    "across distributed teams."
                ),
            },
        )
        assert response.status_code == 200
        body = response.json()
        stored_messages = body["messages"]
        assert len(stored_messages) <= max_turns * 2

        session = fresh_store.get(uuid.UUID(session_id))
        assert session is not None
        llm_messages = session.conversation_history.to_messages_list(
            project_metadata=session.project_metadata,
            project_type=ProjectType.WEB_SAAS,
            detail_level=DetailLevel.MEDIUM,
            output_format=OutputFormat.PHASES_TABLE,
        )
        llm_history_snapshots.append(llm_messages)
        non_system = [m for m in llm_messages if m["role"] != "system"]
        assert len(non_system) <= max_turns * 2
        assert _count_conversation_turns(non_system) <= max_turns

    final_messages = llm_history_snapshots[-1]
    non_system_final = [m for m in final_messages if m["role"] != "system"]
    user_messages = [m for m in non_system_final if m["role"] == "user"]
    assert len(non_system_final) == max_turns * 2
    assert len(user_messages) == max_turns
    assert "Turn 3:" in user_messages[0]["content"]
    assert "Turn 8:" in user_messages[-1]["content"]

    get_settings.cache_clear()
