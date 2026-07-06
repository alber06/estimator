"""Unit tests for stress eval metrics."""

from __future__ import annotations

from app.sessions.models import ProjectMetadata
from evals.stress.metrics import CostBudgetMetric, LatencyBudgetMetric, MemoryDriftMetric


def test_latency_budget_passes_under_budget() -> None:
    result = LatencyBudgetMetric(budget_ms=1_000).evaluate({"latency_ms": 400})
    assert result.passed
    assert result.score == 1.0


def test_cost_budget_fails_over_budget() -> None:
    result = CostBudgetMetric(budget_usd=0.05).evaluate({"cost_usd": 0.12})
    assert not result.passed
    assert result.score == 0.0
    assert "exceeds" in result.details


def test_latency_budget_passes_at_exact_budget() -> None:
    result = LatencyBudgetMetric(budget_ms=500).evaluate({"latency_ms": 500})
    assert result.passed
    assert result.score == 1.0


def test_memory_drift_finds_fact_in_summary_case_insensitive() -> None:
    metric = MemoryDriftMetric(fact="project name: NIMBUS")
    snapshot = {
        "turn_number": 5,
        "fact_turn": 1,
        "summary": "Early turns established project name: nimbus for the CRM.",
        "anchors": [],
        "metadata": ProjectMetadata(),
    }
    result = metric.evaluate(snapshot)
    assert result.passed
    assert "summary" in result.details


def test_memory_drift_matches_bare_value_in_metadata() -> None:
    # fact_to_remember is authored as "label: value" for eval readability, but
    # real ProjectMetadata never carries the label — only "Nimbus" itself.
    metric = MemoryDriftMetric(fact="project name: Nimbus")
    snapshot = {
        "turn_number": 5,
        "fact_turn": 1,
        "summary": "",
        "anchors": [],
        "metadata": ProjectMetadata(project_name="Nimbus"),
    }
    result = metric.evaluate(snapshot)
    assert result.passed
    assert "metadata" in result.details
