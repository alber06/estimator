"""Deterministic metrics for multi-turn stress evals.

Latency/cost budgets operate on per-turn observations (``latency_ms``,
``cost_usd``). Memory drift checks whether a fact declared at turn *k*
survives in the session snapshot at turn *N* (> *k*) via exact,
case-insensitive substring match — no embeddings, no LLM judge.
"""

from __future__ import annotations

from typing import Any

from app.sessions.models import Message, ProjectMetadata
from evals.metrics import MetricResult

_DEFAULT_WHERE = ("summary", "anchors", "metadata")


def _field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _anchors_text(anchors: list[Any]) -> str:
    parts: list[str] = []
    for item in anchors:
        if isinstance(item, Message):
            parts.append(item.content)
        elif isinstance(item, dict):
            parts.append(str(item.get("content", "")))
        else:
            parts.append(str(item))
    return " ".join(parts)


def _metadata_text(metadata: ProjectMetadata | dict[str, Any] | None) -> str:
    if metadata is None:
        return ""
    if isinstance(metadata, dict):
        metadata = ProjectMetadata.model_validate(metadata)
    parts: list[str] = []
    if metadata.project_name:
        parts.append(metadata.project_name)
    if metadata.agreed_scope:
        parts.append(metadata.agreed_scope)
    parts.extend(metadata.mentioned_technologies)
    if metadata.assumed_team_size is not None:
        parts.append(str(metadata.assumed_team_size))
    return " ".join(parts)


class LatencyBudgetMetric:
    """1.0 si latency_ms ≤ budget_ms; 0.0 si no."""

    name = "latency_budget"

    def __init__(self, budget_ms: int) -> None:
        self.budget_ms = budget_ms

    def evaluate(self, observation: Any) -> MetricResult:
        latency_ms = int(_field(observation, "latency_ms", 0))
        passed = latency_ms <= self.budget_ms
        score = 1.0 if passed else 0.0
        details = (
            f"latency_ms={latency_ms} within budget_ms={self.budget_ms}"
            if passed
            else f"latency_ms={latency_ms} exceeds budget_ms={self.budget_ms}"
        )
        return MetricResult(
            name=self.name,
            score=score,
            passed=passed,
            details=details,
        )


class CostBudgetMetric:
    """1.0 si cost_usd ≤ budget_usd; 0.0 si no."""

    name = "cost_budget"

    def __init__(self, budget_usd: float) -> None:
        self.budget_usd = budget_usd

    def evaluate(self, observation: Any) -> MetricResult:
        cost_usd = float(_field(observation, "cost_usd", 0.0))
        passed = cost_usd <= self.budget_usd
        score = 1.0 if passed else 0.0
        details = (
            f"cost_usd={cost_usd:.6f} within budget_usd={self.budget_usd:.6f}"
            if passed
            else f"cost_usd={cost_usd:.6f} exceeds budget_usd={self.budget_usd:.6f}"
        )
        return MetricResult(
            name=self.name,
            score=score,
            passed=passed,
            details=details,
        )


class MemoryDriftMetric:
    """1.0 si el fact declarado del turno k aparece en summary,
    anchors, o ProjectMetadata del turno N (con N > k); 0.0 si no."""

    name = "memory_drift"

    def __init__(
        self,
        fact: str,
        where: list[str] | None = None,
    ) -> None:
        self.fact = fact
        self.where = list(where if where is not None else _DEFAULT_WHERE)

    def evaluate(self, session_snapshot: Any) -> MetricResult:
        turn_n = _field(session_snapshot, "turn_number")
        fact_turn = _field(session_snapshot, "fact_turn")
        if turn_n is not None and fact_turn is not None and turn_n <= fact_turn:
            return MetricResult(
                name=self.name,
                score=0.0,
                passed=False,
                details=(
                    f"turn_number={turn_n} must be > fact_turn={fact_turn} "
                    "to evaluate memory drift"
                ),
            )

        # fact_to_remember is authored as "label: value" for readability
        # (e.g. "project name: Nimbus"); only the value is expected to
        # literally surface in summary/anchors/metadata text.
        needle = self.fact.split(":", 1)[-1].strip().lower()
        haystacks: dict[str, str] = {}
        if "summary" in self.where:
            haystacks["summary"] = str(_field(session_snapshot, "summary") or "")
        if "anchors" in self.where:
            haystacks["anchors"] = _anchors_text(
                _field(session_snapshot, "anchors") or []
            )
        if "metadata" in self.where:
            haystacks["metadata"] = _metadata_text(
                _field(session_snapshot, "metadata")
            )

        found_in = [field for field, text in haystacks.items() if needle in text.lower()]
        passed = bool(found_in)
        score = 1.0 if passed else 0.0
        if passed:
            details = f"fact found in {found_in}"
        else:
            searched = ", ".join(self.where)
            details = f"fact not found in [{searched}] (case-insensitive match)"
        return MetricResult(
            name=self.name,
            score=score,
            passed=passed,
            details=details,
        )
