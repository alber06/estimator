"""Tests for session project metadata extraction and merge."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.schemas.estimation import EstimationResult
from app.schemas.session import ProjectMetadata
from app.services.session import (
    Session,
    merge_project_metadata,
    update_project_metadata_from_estimation,
)


def _sample_estimation_result() -> EstimationResult:
    return EstimationResult(
        summary="B2B SaaS for equipment loans across teams.",
        total_duration_weeks=1,
        total_cost_eur=5_000,
        confidence_pct=70,
        phases=[
            {
                "name": "Discovery",
                "duration_weeks": 1,
                "cost_eur": 5_000,
                "summary": "Workshops, scoping and tech spike.",
            }
        ],
    )


def test_merge_project_metadata_replaces_scalars_and_deduplicates_technologies() -> None:
    existing = ProjectMetadata(
        project_name="OldName",
        assumed_team_size=2,
        mentioned_technologies=["Python", "React"],
        agreed_scope="Old scope",
    )
    extracted = ProjectMetadata(
        project_name="LoanDesk",
        assumed_team_size=4,
        mentioned_technologies=["react", "PostgreSQL"],
        agreed_scope="MVP with auth",
    )

    merged = merge_project_metadata(existing, extracted)

    assert merged.project_name == "LoanDesk"
    assert merged.assumed_team_size == 4
    assert merged.agreed_scope == "MVP with auth"
    assert merged.mentioned_technologies == ["Python", "React", "PostgreSQL"]


def test_merge_project_metadata_keeps_existing_when_extracted_fields_are_empty() -> None:
    existing = ProjectMetadata(
        project_name="LoanDesk",
        assumed_team_size=3,
        mentioned_technologies=["Python"],
        agreed_scope="Keep this scope",
    )
    extracted = ProjectMetadata()

    merged = merge_project_metadata(existing, extracted)

    assert merged == existing


@patch("app.services.session.render_extract_metadata_prompt")
def test_update_project_metadata_from_estimation_merges_llm_output(
    mock_render: MagicMock,
) -> None:
    mock_render.return_value = ("system", "user")
    llm_wrapper = MagicMock()
    llm_wrapper.complete_structured.return_value = (
        ProjectMetadata(
            project_name="LoanDesk",
            assumed_team_size=5,
            mentioned_technologies=["FastAPI"],
            agreed_scope="Auth and dashboards",
        ),
        {"model": "gpt-4o-mini"},
    )
    session = Session(project_metadata=ProjectMetadata(mentioned_technologies=["Python"]))

    update_project_metadata_from_estimation(
        session,
        transcript="Build LoanDesk with FastAPI for equipment loans.",
        estimation_result=_sample_estimation_result(),
        llm_wrapper=llm_wrapper,
    )

    mock_render.assert_called_once()
    llm_wrapper.complete_structured.assert_called_once()
    assert session.project_metadata.project_name == "LoanDesk"
    assert session.project_metadata.assumed_team_size == 5
    assert session.project_metadata.agreed_scope == "Auth and dashboards"
    assert session.project_metadata.mentioned_technologies == ["Python", "FastAPI"]


@patch("app.services.session.render_extract_metadata_prompt")
def test_update_project_metadata_from_estimation_swallows_llm_failures(
    mock_render: MagicMock,
) -> None:
    mock_render.return_value = ("system", "user")
    llm_wrapper = MagicMock()
    llm_wrapper.complete_structured.side_effect = RuntimeError("upstream failed")
    session = Session(project_metadata=ProjectMetadata(project_name="KeepMe"))

    update_project_metadata_from_estimation(
        session,
        transcript="Build LoanDesk with FastAPI for equipment loans.",
        estimation_result=_sample_estimation_result(),
        llm_wrapper=llm_wrapper,
    )

    assert session.project_metadata.project_name == "KeepMe"
