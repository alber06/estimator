#!/usr/bin/env python3
"""Exercise ``POST /embeddings/search`` with five representative queries.

Each query probes the ingested corpus from a different angle: near-duplicate,
semantic reformulation, out-of-domain, ambiguous, and highly specific.

Usage::

    # API running locally (default http://localhost:8000):
    uv run python query_examples.py

    # Stack up — inside the running API container (localhost works):
    docker compose exec estimator python query_examples.py

    # One-off container (no uvicorn here — script auto-falls back to estimator:8000):
    docker compose run --rm estimator python query_examples.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

DOCKER_SERVICE_URL = "http://estimator:8000"
DEFAULT_URL = "http://localhost:8000"

QUERIES: list[tuple[str, str, str]] = [
    (
        "direct",
        "Componente directo conocido",
        "REST API development with JWT authentication for financial sector",
    ),
    (
        "reformulation",
        "Reformulación semántica",
        "secure backend service with token-based access control for banking applications",
    ),
    (
        "out_of_domain",
        "Dominio distinto",
        "mobile application for restaurant reservations",
    ),
    (
        "ambiguous",
        "Consulta ambigua",
        "integration with external system",
    ),
    (
        "specific",
        "Consulta muy específica",
        "migration from monolith to microservices architecture using Kubernetes",
    ),
]

SEARCH_PATH = "/embeddings/search"
CONTENT_PREVIEW_CHARS = 120
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output_examples.txt"


class _Output:
    def __init__(self) -> None:
        self._lines: list[str] = []

    def line(self, text: str = "") -> None:
        print(text)
        self._lines.append(f"{text}\n")

    def save(self, path: Path) -> None:
        path.write_text("".join(self._lines), encoding="utf-8")


def _preview(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= CONTENT_PREVIEW_CHARS:
        return one_line
    return one_line[: CONTENT_PREVIEW_CHARS - 1] + "…"


def _print_results(data: dict, out: _Output) -> None:
    results = data.get("results", [])
    if not results:
        out.line("  (no results)")
        return

    for rank, hit in enumerate(results, start=1):
        preview = _preview(hit["content"])
        out.line(
            f"  #{rank:<2} chunk_id={hit['chunk_id']:<6} "
            f"distance={hit['distance']:.4f}  chunk_type={hit['chunk_type']}"
        )
        out.line(f"      {preview}")


def _base_url_candidates(explicit: str | None) -> list[str]:
    """Host default first; inside Docker also try the compose service name."""
    if explicit:
        return [explicit.rstrip("/")]
    env = os.environ.get("ESTIMATOR_HTTP_URL")
    if env:
        return [env.rstrip("/")]

    candidates = [DEFAULT_URL]
    if Path("/.dockerenv").is_file() and DOCKER_SERVICE_URL not in candidates:
        candidates.append(DOCKER_SERVICE_URL)
    return candidates


def _run_searches(base_urls: list[str], k: int, out: _Output) -> int:
    last_url = base_urls[-1]
    for index, base_url in enumerate(base_urls):
        try:
            with httpx.Client(base_url=base_url, timeout=60.0) as client:
                for q_index, (slug, label, query) in enumerate(QUERIES, start=1):
                    out.line("=" * 80)
                    out.line(f"[{q_index}/{len(QUERIES)}] {label} ({slug})")
                    out.line(f"Query: {query}")
                    out.line("-" * 80)

                    response = client.post(SEARCH_PATH, json={"query": query, "k": k})
                    if response.status_code != 200:
                        print(
                            f"ERROR {response.status_code}: {response.text[:300]}",
                            file=sys.stderr,
                        )
                        return 1

                    data = response.json()
                    out.line(f"search_time_ms: {data.get('search_time_ms', '?')}")
                    _print_results(data, out)
                    out.line()
            return 0
        except httpx.ConnectError:
            if index < len(base_urls) - 1:
                print(
                    f"Cannot reach {base_url}{SEARCH_PATH}, trying {base_urls[index + 1]}...",
                    file=sys.stderr,
                )
                continue

    print(
        f"ERROR: cannot reach {last_url}{SEARCH_PATH} — is the API running?",
        file=sys.stderr,
    )
    if Path("/.dockerenv").is_file():
        print(
            "Hint: start the stack with `docker compose up -d`, then either\n"
            "  docker compose exec estimator python query_examples.py\n"
            "  docker compose run --rm estimator python query_examples.py",
            file=sys.stderr,
        )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--http",
        default=None,
        help=(
            "Estimator base URL (default: localhost:8000 on host; "
            "inside Docker also tries http://estimator:8000)."
        ),
    )
    parser.add_argument(
        "-k",
        type=int,
        default=5,
        help="Number of nearest chunks per query (default: 5).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Write results to this file (default: {DEFAULT_OUTPUT.name}).",
    )
    args = parser.parse_args()

    out = _Output()
    code = _run_searches(_base_url_candidates(args.http), args.k, out)
    if code == 0:
        out.save(args.output)
        print(f"Wrote {args.output}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
