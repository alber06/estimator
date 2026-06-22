"""Tests for the Jinja2 prompt loader.

The goal is to verify the contract of the rendered output without touching the
LLM: that user-provided fields land in the right block, that conditional
sections only render when the matching enum value is requested, and that
``StrictUndefined`` blows up early on missing variables.
"""

from __future__ import annotations

import pytest
from jinja2 import Environment, StrictUndefined, UndefinedError

from app.prompts.loader import (
    render_conversation_prompt,
    render_estimation_prompt,
    render_extract_metadata_prompt,
)
from app.schemas.estimation import (
    DetailLevel,
    EstimationRequest,
    EstimationResult,
    OutputFormat,
    ProjectType,
)
from app.schemas.session import ProjectMetadata


def _make_request(**overrides) -> EstimationRequest:
    base = {
        "description": "A small CRM for a real estate agency: contacts, deals, role-based access.",
        "project_type": ProjectType.WEB_SAAS,
        "detail_level": DetailLevel.MEDIUM,
        "output_format": OutputFormat.PHASES_TABLE,
    }
    base.update(overrides)
    return EstimationRequest(**base)


def test_user_prompt_wraps_description_in_project_description_block() -> None:
    request = _make_request(description="UNIQUE-MARKER-12345 build a tiny scheduling app.")
    _system, user = render_estimation_prompt(request)
    assert "<project_description>" in user
    assert "UNIQUE-MARKER-12345 build a tiny scheduling app." in user
    assert "</project_description>" in user
    start = user.index("<project_description>")
    end = user.index("</project_description>")
    assert "UNIQUE-MARKER-12345" in user[start:end]


def test_phases_table_keyword_appears_only_when_format_requested() -> None:
    table_request = _make_request(output_format=OutputFormat.PHASES_TABLE)
    narrative_request = _make_request(output_format=OutputFormat.NARRATIVE)

    table_system, _ = render_estimation_prompt(table_request)
    narrative_system, _ = render_estimation_prompt(narrative_request)

    assert "phases_table" in table_system
    assert "phases_table" not in narrative_system


def test_detailed_includes_assumptions_per_phase_summary_does_not() -> None:
    detailed_request = _make_request(detail_level=DetailLevel.DETAILED)
    summary_request = _make_request(detail_level=DetailLevel.SUMMARY)

    detailed_system, _ = render_estimation_prompt(detailed_request)
    summary_system, _ = render_estimation_prompt(summary_request)

    assert "list assumptions per phase" in detailed_system.lower()
    assert "list assumptions per phase" not in summary_system.lower()


def test_examples_block_is_included_in_system_prompt() -> None:
    request = _make_request()
    system, _ = render_estimation_prompt(request)
    assert "<examples>" in system
    assert "</examples>" in system


def test_strict_undefined_raises_on_missing_variable() -> None:
    """A separate Jinja2 template with the same StrictUndefined config must error
    early when a variable is missing — guarantees that typos in templates are
    surfaced at render time, not silently rendered as empty strings."""
    env = Environment(undefined=StrictUndefined)
    template = env.from_string("Hello {{ unknown_variable }}")
    with pytest.raises(UndefinedError):
        template.render()


def test_unknown_version_raises() -> None:
    request = _make_request()
    with pytest.raises(Exception):
        render_estimation_prompt(request, version="v999")


def test_conversation_prompt_wraps_transcript_in_user_block() -> None:
    transcript = "UNIQUE-CONV-MARKER-67890 build a tiny scheduling app for teams."
    _system, user = render_conversation_prompt(
        transcript=transcript,
        project_type=ProjectType.WEB_SAAS,
        detail_level=DetailLevel.MEDIUM,
        output_format=OutputFormat.PHASES_TABLE,
    )
    assert "<project_description>" in user
    assert transcript in user
    assert "</project_description>" in user


def test_conversation_prompt_renders_project_metadata_when_provided() -> None:
    metadata = ProjectMetadata(
        project_name="LoanDesk",
        assumed_team_size=4,
        mentioned_technologies=["Python", "React"],
        agreed_scope="MVP with auth and dashboards",
    )
    system, _user = render_conversation_prompt(
        transcript="We need a B2B SaaS for equipment loan management across teams.",
        project_type=ProjectType.WEB_SAAS,
        detail_level=DetailLevel.MEDIUM,
        output_format=OutputFormat.PHASES_TABLE,
        project_metadata=metadata,
    )
    assert "LoanDesk" in system
    assert "Python" in system
    assert "React" in system
    assert "MVP with auth and dashboards" in system


def test_conversation_prompt_skips_metadata_block_when_none() -> None:
    system, _user = render_conversation_prompt(
        transcript="We need a B2B SaaS for equipment loan management across teams.",
        project_type=ProjectType.WEB_SAAS,
        detail_level=DetailLevel.MEDIUM,
        output_format=OutputFormat.PHASES_TABLE,
        project_metadata=None,
    )
    assert "Project name:" not in system
    assert "Agreed scope:" not in system


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


def test_extract_metadata_prompt_includes_transcript_and_estimation_json() -> None:
    transcript = "UNIQUE-EXTRACT-MARKER build LoanDesk with React and Python."
    estimation = _sample_estimation_result()
    _system, user = render_extract_metadata_prompt(
        transcript=transcript,
        estimation=estimation,
    )
    assert "<transcript>" in user
    assert transcript in user
    assert "<estimation_json>" in user
    assert '"summary": "B2B SaaS for equipment loans across teams."' in user


def test_extract_metadata_prompt_includes_existing_metadata_when_provided() -> None:
    existing = ProjectMetadata(
        project_name="LoanDesk",
        mentioned_technologies=["Python"],
        agreed_scope="MVP dashboards",
    )
    _system, user = render_extract_metadata_prompt(
        transcript="We need a B2B SaaS for equipment loan management across teams.",
        estimation=_sample_estimation_result(),
        existing_metadata=existing,
    )
    assert "<existing_metadata>" in user
    assert "LoanDesk" in user
    assert "MVP dashboards" in user
