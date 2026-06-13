# AGENTS.md

This file provides guidance to AI agents (including Cursor) when working with code in this repository. It mirrors `CLAUDE.md` so the same conventions apply across tooling.

## Repository layout

The repo root **is** the estimator project — run all commands from the repository root. The project is part of a Master en AI Engineering and is intended to evolve module-by-module (CAG → RAG with vector DB in later modules).

## Common commands

Dependency / runtime management uses **uv** (Astral) and Python 3.11.

```bash
# Install deps (creates .venv)
uv sync

# Run the API locally with hot reload (requires Redis at REDIS_URL)
uv run uvicorn app.main:app --reload

# Run the full test suite
uv run pytest

# Run a single test file or test
uv run pytest tests/test_health.py
uv run pytest tests/test_health.py::test_name -v

# Lint
uv run ruff check .
uv run ruff format .

# Docker (recommended dev path — API + Redis, bind-mounts app/ for live reload)
docker compose up --build

# Streamlit UI (runs outside Docker, talks to the API over HTTP)
uv run streamlit run streamlit_app.py
```

Service listens on `http://localhost:8000`; `/docs` (Swagger) and `/redoc` are enabled. Health probe at `GET /health`. Main endpoints:

- `POST /api/v1/estimate` — blocking estimation
- `POST /api/v1/estimate/stream` — SSE token streaming

## Architecture

The estimator is a FastAPI service implementing **Cache Augmented Generation (CAG)**: reference estimations are inlined as static text inside Jinja2 system prompts — no vector store, no retrieval step. Later modules will migrate to RAG.

Request flow:

1. `app/routers/estimations.py` — accepts an `EstimationRequest` (`description`, `project_type`, `detail_level`, `output_format`, optional `reference_projects`) plus query param `prompt_version` (`v1` | `v2`, default `v1`).
2. `app/prompts/loader.py::render_estimation_prompt` — renders `estimation/{version}/system.j2` and `estimation/{version}/user.j2` with the request context. Returns `(user_prompt, system_prompt)`.
3. `app/services/llm_wrapper.py::LLMWrapper` — `complete()` (blocking) or `complete_stream()` (generator) calls LiteLLM with cache lookup/store via `EstimationCache`. Returns a dict with `estimation`, `model`, `provider`, `usage`, `finish_reason`, `latency_ms`, `cost_usd`, `cache_hit`.
4. The router returns `EstimationResponse` (`estimation`, `prompt_version`). Extra fields from the wrapper dict are dropped by the Pydantic model.

Streaming flow is the same through step 2, then `complete_stream()` yields text chunks wrapped as SSE events (`token`, `done`, `error`) by the router.

Key design points future changes should respect:

- **LLM abstraction lives in one file** (`llm_wrapper.py`). LiteLLM Router handles primary→fallback; `model_override` bypasses the Router and calls `litellm.completion` directly (no fallback). Keep the internal dict shape stable so callers stay provider-agnostic.
- **Cached singletons** via `@lru_cache`: `get_settings()` (`config.py`), `get_cache()` and `get_llm_wrapper()` (`dependencies.py`). Because of the cache, **any change to `.env` requires restarting uvicorn** (a `--reload` is not enough).
- **CAG examples** live in `app/prompts/estimation/v1/examples.j2` and `v2/examples.j2`, included from each version's `system.j2`. When this graduates to RAG, the prompts module is the seam to replace.
- **Pricing assumptions** (62.50 EUR/h dev, 50 EUR/h designer) live in the `system.j2` templates. Edit there, not in examples.
- **Prompt versions** — add a new directory under `app/prompts/estimation/` and extend the `PromptVersion` enum. v2 adds `<reference_projects>` support in its system template.
- **Cache key** (`EstimationCache.make_key`) hashes `system_prompt`, `user_message`, `model`, `max_tokens`, and `thinking_budget`. Any prompt or knob change implicitly invalidates cached entries.
- **`thinking_budget` is Anthropic-only** — passed through `LLMWrapper.complete()`; the wrapper auto-pads `max_tokens` above the budget for Anthropic models.
- **Logging** is `structlog`, configured in `lifespan` (`main.py`): JSON in `production`, console in dev. Use `structlog.get_logger()` rather than stdlib `logging`.

## Project structure (key files)

```
app/
├── main.py                 # FastAPI app, CORS, static files, logging setup
├── config.py               # Pydantic Settings
├── dependencies.py         # get_cache(), get_llm_wrapper()
├── routers/estimations.py  # /estimate and /estimate/stream
├── prompts/
│   ├── loader.py           # Jinja2 render_estimation_prompt()
│   └── estimation/v1|v2/   # system.j2, user.j2, examples.j2
├── schemas/estimation.py   # Request/response models and enums
├── services/
│   ├── llm_wrapper.py      # LiteLLM Router, fallback, cost, streaming
│   └── cache.py            # Redis exact-match cache
└── static/sse_demo.html    # Browser SSE demo
streamlit_app.py            # Form UI (HTTP client of /api/v1/estimate)
tests/                      # pytest suite (fakeredis + mocked LiteLLM)
```

## How to compare in live demos

The endpoint supports side-by-side comparisons via request fields and query params. Useful response metrics from the wrapper (when inspected in logs or tests): `usage`, `latency_ms`, `finish_reason`, `cost_usd`, `cache_hit`.

```bash
DESC=$(jq -Rs . < app/fixtures/long_description.txt)

# Prompt versions
for V in v1 v2; do
  curl -s "localhost:8000/api/v1/estimate?prompt_version=$V" \
    -H 'Content-Type: application/json' \
    -d "{\"description\": $DESC, \"project_type\": \"web_saas\", \"detail_level\": \"medium\", \"output_format\": \"phases_table\"}" \
    | jq "{version:\"$V\", prompt_version, estimation: .estimation[:80]}"
done

# Detail levels
for LEVEL in summary medium detailed; do
  curl -s localhost:8000/api/v1/estimate \
    -H 'Content-Type: application/json' \
    -d "{\"description\": $DESC, \"project_type\": \"mobile_app\", \"detail_level\": \"$LEVEL\", \"output_format\": \"phases_table\"}" \
    | jq "{detail_level:\"$LEVEL\", latency_ms, cost_usd, cache_hit}"
done

# Cache hit on repeat
curl -s localhost:8000/api/v1/estimate -H 'Content-Type: application/json' \
  -d '{"description": "We need a small CRM with auth, contacts and roles. MVP six weeks.", "project_type": "web_saas", "detail_level": "medium", "output_format": "phases_table"}' \
  | jq '{cache_hit, cost_usd}'
```

## Configuration

`.env` (copied from `.env.example`) drives everything via `pydantic-settings`. Notable vars:

- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` — at least one is required (LiteLLM may use either via fallback).
- `PRIMARY_MODEL` — primary model for the LiteLLM Router (default `gpt-4o-mini`).
- `FALLBACK_MODEL` — fallback model (default `claude-haiku-4-5-20251001`).
- `LLM_TIMEOUT` / `LLM_RETRIES` — Router timeout and retry count.
- `REDIS_URL` — Redis connection (default `redis://localhost:6379`; Docker Compose overrides to `redis://redis:6379`).
- `CACHE_TTL` — cache entry TTL in seconds (default `86400`).
- `ESTIMATOR_API_BASE_URL` — backend URL for Streamlit (default `http://localhost:8000`).
- `APP_ENV` — `development` | `staging` | `production` (controls log renderer).

Legacy fields `LLM_PROVIDER` and `LLM_MODEL` remain in `Settings` for backwards compatibility but are **not used** by the current estimation flow.

## Docker

Multi-stage Dockerfile: `builder` installs prod-only deps with `uv sync --no-install-project --no-dev`, `runtime` is a clean `python:3.11-slim` that only carries `/app/.venv` and `app/`, runs as non-root `appuser`. There is a Docker-native HEALTHCHECK against `/health`.

`docker-compose.yml` runs two services:

- **estimator** — API on port 8000, bind-mounts `./app`, `--reload` for dev
- **redis** — Redis 7 on port 6379 with a persistent volume

Strip the bind mount and `--reload` for production deployments.

## Tests

Tests live under `tests/` and use `fakeredis` plus mocked LiteLLM responses — no real API keys or Redis required for most of the suite:

- `test_health.py` — health endpoint
- `test_cache.py` — cache keying and round-trip
- `test_llm_wrapper.py` — wrapper contract, caching, cost, streaming
- `test_estimate_stream.py` — SSE endpoint (uses dependency overrides)
- `prompts/test_estimation_v1.py` — prompt rendering

Some older tests (e.g. `test_estimate_endpoint.py`) may still reference removed Session 2 modules and need updating.
