"""Unit tests for EstimationService.estimate_conversation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.schemas.estimation import (
    DetailLevel,
    EstimationResponse,
    EstimationResult,
    OutputFormat,
    ProjectType,
)
from app.schemas.session import Message, ProjectMetadata
from app.services.estimation import EstimationService
from app.services.session import Session


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


@patch("app.services.estimation.update_project_metadata_from_estimation")
@patch("app.services.estimation.render_conversation_prompt")
@patch("app.services.estimation.check_input")
def test_estimate_conversation_skips_cache_and_uses_v2(
    mock_check_input: MagicMock,
    mock_render: MagicMock,
    mock_update_metadata: MagicMock,
) -> None:
    mock_render.return_value = ("system", "user")
    llm_wrapper = MagicMock()
    llm_wrapper.complete_structured_with_messages.return_value = (
        _canned_result(),
        {"model": "gpt-4o-mini"},
    )
    exact_cache = MagicMock()
    semantic_cache = MagicMock()

    session = Session(project_metadata=ProjectMetadata(project_name="LoanDesk"))
    service = EstimationService(
        llm_wrapper=llm_wrapper,
        exact_cache=exact_cache,
        semantic_cache=semantic_cache,
    )

    response = service.estimate_conversation(
        transcript="We need a B2B SaaS for equipment loan management across teams.",
        project_type=ProjectType.WEB_SAAS,
        detail_level=DetailLevel.MEDIUM,
        output_format=OutputFormat.PHASES_TABLE,
        session=session,
    )

    mock_check_input.assert_called_once()
    mock_render.assert_called_once_with(
        transcript="We need a B2B SaaS for equipment loan management across teams.",
        project_type=ProjectType.WEB_SAAS,
        detail_level=DetailLevel.MEDIUM,
        output_format=OutputFormat.PHASES_TABLE,
        project_metadata=session.project_metadata,
    )
    llm_wrapper.complete_structured_with_messages.assert_called_once()
    call_kwargs = llm_wrapper.complete_structured_with_messages.call_args.kwargs
    messages = call_kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert "LoanDesk" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "user"}
    assert len(messages) == 2
    llm_wrapper.complete_structured.assert_not_called()
    mock_update_metadata.assert_called_once()
    exact_cache.get.assert_not_called()
    exact_cache.set.assert_not_called()
    semantic_cache.lookup.assert_not_called()
    semantic_cache.store.assert_not_called()

    assert isinstance(response, EstimationResponse)
    assert response.prompt_version == "v2"
    assert response.cached is False
    assert response.result.total_cost_eur == 30_000
    assert response.project_metadata == session.project_metadata
    assert response.messages is not None
    assert len(response.messages) == 2
    assert response.messages[0] == Message(role="user", content="user")
    assert response.messages[1].role == "assistant"
    assert "30_000" in response.messages[1].content or "30000" in response.messages[1].content
