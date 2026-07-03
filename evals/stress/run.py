"""CLI runner for multi-turn stress evals.

Default transport is the in-process ``TestClient`` (no external server).
``--http BASE`` switches to a live HTTP target, mirroring ``evals/run.py``.

Usage::

    uv run python -m evals.stress.run --http http://localhost:8000 \\
        --scenarios growing,pivot,contradiction \\
        --attachment-sizes 0,5,20,50,100 \\
        --repeats 3 \\
        --output evals/stress/results.csv

Each completed turn writes one CSV row with all ``turn_observed`` columns plus
one binary column per stress metric (``latency_budget``, ``cost_budget``,
``memory_drift``).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
from fastapi.testclient import TestClient

from app.dependencies import get_session_store
from app.main import app
from app.sessions.store import SessionStore
from evals.stress.metrics import CostBudgetMetric, LatencyBudgetMetric, MemoryDriftMetric
from evals.stress.scenarios import StressScenario, load_scenario

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pdfs"

SCENARIO_ALIASES: dict[str, str] = {
    "grow": "grow",
    "growing": "grow",
    "pivot": "pivot",
    "contradict": "contradict",
    "contradiction": "contradict",
}

ATTACHMENT_PDFS: dict[int, Path | None] = {
    0: None,
    5: _FIXTURES / "attach_5kb.pdf",
    20: _FIXTURES / "attach_20kb.pdf",
    50: _FIXTURES / "attach_50kb.pdf",
    100: _FIXTURES / "attach_100kb.pdf",
}

TURN_OBSERVED_FIELDS: tuple[str, ...] = (
    "turn_index",
    "session_id",
    "enriched_transcript_chars",
    "attachments_total_chars",
    "messages_in_window",
    "anchors_count",
    "summary_chars",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "latency_ms",
    "cache_hit_kind",
    "last_resolved_tier",
)

METRIC_FIELDS: tuple[str, ...] = (
    "latency_budget_passed",
    "cost_budget_passed",
    "memory_drift_passed",
)

RUN_META_FIELDS: tuple[str, ...] = (
    "scenario_id",
    "profile_id",
    "attachment_size_kb",
    "repeat",
    "turn",
)


class SessionClient(Protocol):
    async def create_session(self) -> str: ...

    async def estimate_turn(
        self,
        session_id: str,
        *,
        transcript: str,
        project_type: str,
        detail_level: str,
        output_format: str,
        attachment_path: Path | None,
    ) -> None: ...

    async def get_session(self, session_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RunConfig:
    scenarios: list[StressScenario]
    attachment_sizes_kb: list[int]
    repeats: int
    latency_budget_ms: int
    cost_budget_usd: float
    turn_count: int


def _parse_csv_ints(raw: str) -> list[int]:
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _parse_scenario_names(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _resolve_profile_id(name: str) -> str:
    key = name.lower()
    try:
        return SCENARIO_ALIASES[key]
    except KeyError as exc:
        known = ", ".join(sorted(SCENARIO_ALIASES))
        raise ValueError(f"Unknown scenario {name!r}; choose from: {known}") from exc


def _load_scenarios(names: list[str], turn_count: int) -> list[StressScenario]:
    return [load_scenario(_resolve_profile_id(name), turn_count) for name in names]


def _attachment_path(size_kb: int) -> Path | None:
    try:
        path = ATTACHMENT_PDFS[size_kb]
    except KeyError as exc:
        known = ", ".join(str(k) for k in sorted(ATTACHMENT_PDFS))
        raise ValueError(f"Unknown attachment size {size_kb} KB; choose from: {known}") from exc
    if path is not None and not path.is_file():
        msg = f"Attachment fixture missing: {path} (run evals/stress/fixtures/build_pdfs.py)"
        raise FileNotFoundError(msg)
    return path


def _memory_drift_snapshot(session: dict[str, Any], *, fact_turn: int) -> dict[str, Any]:
    last_turn = session.get("last_turn") or {}
    return {
        "turn_number": last_turn.get("turn_index", 0),
        "fact_turn": fact_turn,
        "summary": session.get("summary"),
        "anchors": session.get("anchors") or [],
        "metadata": session.get("metadata"),
    }


def _evaluate_turn(
    *,
    turn_observed: dict[str, Any],
    session_snapshot: dict[str, Any],
    anchor_fact: str,
    latency_budget_ms: int,
    cost_budget_usd: float,
) -> dict[str, int]:
    latency = LatencyBudgetMetric(budget_ms=latency_budget_ms).evaluate(turn_observed)
    cost = CostBudgetMetric(budget_usd=cost_budget_usd).evaluate(turn_observed)
    drift = MemoryDriftMetric(fact=anchor_fact).evaluate(
        _memory_drift_snapshot(session_snapshot, fact_turn=1)
    )
    return {
        "latency_budget_passed": int(latency.passed),
        "cost_budget_passed": int(cost.passed),
        "memory_drift_passed": int(drift.passed),
    }


def _build_row(
    *,
    scenario: StressScenario,
    attachment_size_kb: int,
    repeat: int,
    turn_index: int,
    turn_observed: dict[str, Any],
    metrics: dict[str, int],
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "scenario_id": scenario.scenario_id,
        "profile_id": scenario.profile_id,
        "attachment_size_kb": attachment_size_kb,
        "repeat": repeat,
        "turn": turn_index,
    }
    row.update({field: turn_observed.get(field) for field in TURN_OBSERVED_FIELDS})
    row.update(metrics)
    return row


class _InProcessClient:
    def __init__(self, test_client: TestClient) -> None:
        self._client = test_client

    async def create_session(self) -> str:
        response = self._client.post("/sessions")
        response.raise_for_status()
        return response.json()["session_id"]

    async def estimate_turn(
        self,
        session_id: str,
        *,
        transcript: str,
        project_type: str,
        detail_level: str,
        output_format: str,
        attachment_path: Path | None,
    ) -> None:
        form = {
            "transcript": transcript,
            "project_type": project_type,
            "detail_level": detail_level,
            "output_format": output_format,
        }
        if attachment_path is None:
            response = self._client.post(f"/sessions/{session_id}/estimate", data=form)
        else:
            with attachment_path.open("rb") as handle:
                files = {
                    "attachments": (
                        attachment_path.name,
                        handle,
                        "application/pdf",
                    )
                }
                response = self._client.post(
                    f"/sessions/{session_id}/estimate",
                    data=form,
                    files=files,
                )
        response.raise_for_status()

    async def get_session(self, session_id: str) -> dict[str, Any]:
        response = self._client.get(f"/sessions/{session_id}")
        response.raise_for_status()
        return response.json()


class _HttpClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> _HttpClient:
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=300.0)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def create_session(self) -> str:
        assert self._client is not None
        response = await self._client.post("/sessions")
        response.raise_for_status()
        return response.json()["session_id"]

    async def estimate_turn(
        self,
        session_id: str,
        *,
        transcript: str,
        project_type: str,
        detail_level: str,
        output_format: str,
        attachment_path: Path | None,
    ) -> None:
        assert self._client is not None
        form = {
            "transcript": transcript,
            "project_type": project_type,
            "detail_level": detail_level,
            "output_format": output_format,
        }
        files = None
        if attachment_path is not None:
            files = {
                "attachments": (
                    attachment_path.name,
                    attachment_path.read_bytes(),
                    "application/pdf",
                )
            }
        response = await self._client.post(
            f"/sessions/{session_id}/estimate",
            data=form,
            files=files,
        )
        response.raise_for_status()

    async def get_session(self, session_id: str) -> dict[str, Any]:
        assert self._client is not None
        response = await self._client.get(f"/sessions/{session_id}")
        response.raise_for_status()
        return response.json()


async def _run_matrix(client: SessionClient, config: RunConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    anchor_fact_by_profile = {
        scenario.profile_id: scenario.turns[0].fact_to_remember
        for scenario in config.scenarios
    }

    for scenario in config.scenarios:
        attachment_path_cache: dict[int, Path | None] = {}
        for size_kb in config.attachment_sizes_kb:
            attachment_path_cache[size_kb] = _attachment_path(size_kb)
        anchor_fact = anchor_fact_by_profile[scenario.profile_id]

        for size_kb in config.attachment_sizes_kb:
            pdf_path = attachment_path_cache[size_kb]
            for repeat in range(1, config.repeats + 1):
                session_id = await client.create_session()
                for turn_spec in scenario.turns:
                    await client.estimate_turn(
                        session_id,
                        transcript=turn_spec.transcript,
                        project_type=scenario.project_type,
                        detail_level=scenario.detail_level,
                        output_format=scenario.output_format,
                        attachment_path=pdf_path,
                    )
                    snapshot = await client.get_session(session_id)
                    turn_observed = snapshot.get("last_turn")
                    if not turn_observed:
                        msg = f"session {session_id} missing last_turn after turn {turn_spec.turn}"
                        raise RuntimeError(msg)

                    metrics = _evaluate_turn(
                        turn_observed=turn_observed,
                        session_snapshot=snapshot,
                        anchor_fact=anchor_fact,
                        latency_budget_ms=config.latency_budget_ms,
                        cost_budget_usd=config.cost_budget_usd,
                    )
                    rows.append(
                        _build_row(
                            scenario=scenario,
                            attachment_size_kb=size_kb,
                            repeat=repeat,
                            turn_index=turn_spec.turn,
                            turn_observed=turn_observed,
                            metrics=metrics,
                        )
                    )
                    print(
                        f"{scenario.scenario_id} | attach={size_kb}KB | "
                        f"repeat={repeat} | turn={turn_spec.turn} | "
                        f"latency={turn_observed.get('latency_ms')}ms | "
                        f"cost=${turn_observed.get('cost_usd', 0):.4f} | "
                        f"metrics={metrics}"
                    )
    return rows


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(RUN_META_FIELDS) + list(TURN_OBSERVED_FIELDS) + list(METRIC_FIELDS)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


async def _main_async(args: argparse.Namespace) -> int:
    scenario_names = _parse_scenario_names(args.scenarios)
    attachment_sizes = _parse_csv_ints(args.attachment_sizes)
    scenarios = _load_scenarios(scenario_names, args.turns)
    config = RunConfig(
        scenarios=scenarios,
        attachment_sizes_kb=attachment_sizes,
        repeats=args.repeats,
        latency_budget_ms=args.latency_budget_ms,
        cost_budget_usd=args.cost_budget_usd,
        turn_count=args.turns,
    )

    print(
        f"Running {len(scenarios)} scenario(s) × {len(attachment_sizes)} attachment sizes "
        f"× {args.repeats} repeat(s) (turns={args.turns})"
    )
    t0 = time.perf_counter()

    if args.http:
        async with _HttpClient(args.http) as client:
            rows = await _run_matrix(client, config)
    else:
        eval_store = SessionStore(max_turns=6)
        app.dependency_overrides[get_session_store] = lambda: eval_store
        try:
            with TestClient(app) as test_client:
                rows = await _run_matrix(_InProcessClient(test_client), config)
        finally:
            app.dependency_overrides.pop(get_session_store, None)

    elapsed = time.perf_counter() - t0
    _write_csv(rows, args.output)
    print(f"\nWrote {len(rows)} rows to {args.output} in {elapsed:.1f}s")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenarios",
        default="growing,pivot,contradiction",
        help="Comma-separated profile names (aliases: growing→grow, contradiction→contradict).",
    )
    parser.add_argument(
        "--attachment-sizes",
        default="0,5,20,50,100",
        help="Comma-separated attachment sizes in KB (0 = no attachment).",
    )
    parser.add_argument("--repeats", type=int, default=3, help="Independent session runs per cell.")
    parser.add_argument(
        "--turns",
        type=int,
        default=20,
        choices=(1, 3, 6, 10, 20),
        help="Turn count slice per profile (default: full 20-turn script).",
    )
    parser.add_argument(
        "--latency-budget-ms",
        type=int,
        default=120_000,
        help="Per-turn latency budget for latency_budget metric.",
    )
    parser.add_argument(
        "--cost-budget-usd",
        type=float,
        default=1.0,
        help="Per-turn cost budget for cost_budget metric.",
    )
    parser.add_argument(
        "--http",
        default=None,
        help="Base URL for HTTP mode (e.g. http://localhost:8000).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/stress/results.csv"),
        help="CSV output path.",
    )
    args = parser.parse_args()

    try:
        return asyncio.run(_main_async(args))
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
