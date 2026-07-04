# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Repository layout

Two-project monorepo for the Master en AI Engineering programme:

- `estimator/` — FastAPI service. The AI side: prompts, LLM calls, structured output, guardrails, semantic cache. All AI logic lives here; the rest of the programme evolves this codebase module by module.
- `estimator-web/` — Rails 8 frontend + business backend (Postgres + Tailwind + Hotwire). Reference implementation of the cliente; each student is free to use a different stack. The live sessions invoke `estimator` directly via httpie/curl (stack-agnostic).

A root-level `docker-compose.yml` orchestrates both via the `include:` directive (Compose v2.20+). Running `docker compose up` from the repo root brings up all 5 services (`estimator`, `redis`, `estimator-postgres`, `estimator-web`, `postgres`) on a shared network so Rails can call the FastAPI estimator at `http://estimator:8000`. Note there are **two** Postgres instances on purpose: `estimator-postgres` (pgvector image, host port 5433, used by the FastAPI service) and `postgres` (alpine, host port 5432, used by Rails). `include:` forbids two included files from declaring the same resource name, so the FastAPI one is named `estimator-postgres` (not plain `postgres`) and its volume is `estimator_postgres_data` — renaming either back to `postgres`/`postgres_data` re-introduces the `services.postgres conflicts with imported resource` error at the root.

**Trap to be aware of**: launching from the root vs from a subdirectory creates *different* Compose projects, which means the named volumes (`postgres_data`, `estimator_postgres_data`, `bundle_cache`, `redis_data`) are not shared between the two modes. Pick a mode per workflow and stay with it.

Session guides for the instructor live in `guides/` (git-ignored). `guides/session-6-live-guide.md` is the most recent; `guides/session-06-reference/` holds optional parsers (XLSX/DOCX/PDF) not wired into this branch.

## Common commands (estimator)

Dependency / runtime management uses **uv** (Astral) and Python 3.11.

```bash
cd estimator

# Run the API locally with hot reload
uv run uvicorn app.main:app --reload

# Tests
uv run pytest -v
uv run pytest tests/test_schemas.py::test_phases_sum_must_equal_total_cost -v

# Lint
uv run ruff check .
uv run ruff format .

# Session 6 pre-flight (spaCy model, catalog, Postgres, deps)
uv run python scripts/preflight_s06.py

# Session 6 demos (PII pseudonymization, budget cleaning)
uv run python scripts/demo_pii_s06.py
uv run python scripts/demo_cleaning_s06.py

# CAG vs RAG decision CLI (Article 1)
uv run python -m app.ingestion.architecture

# Alembic (host against estimator-postgres on :5433)
uv run alembic upgrade head

# Docker (recommended dev path — bind-mounts app/, tests/, data/, alembic/)
docker compose up --build
```

Service listens on `http://localhost:8000`; `/docs` (Swagger) and `/redoc` are enabled. Health probe at `GET /health`.

Main API endpoints:

- `POST /api/v1/estimate` — single-shot structured estimation (Session 4).
- `POST /api/v1/sessions` + `POST /api/v1/sessions/{id}/estimate` — multi-turn conversational estimation with optional attachments (Session 5).
- `POST /api/v1/ingestion/runs` + `GET /api/v1/ingestion/jobs/{job_id}` — async data ingestion (Session 6).

## Architecture (post-Session 4)

The estimator is a typed estimation service implementing a five-layer pipeline. Free-text in, validated structured JSON out.

```
POST /api/v1/estimate
  └→ app/routers/estimations.py    (thin HTTP layer, error mapping)
       └→ app/services/estimation.py::EstimationService.estimate()
            1. app/guardrails/input.py::check_input()         (moderation + injection + PII)
            2. app/services/cache.py::EstimationCache.get()   (exact-match SHA-256)
            3. app/cache/semantic.py::EstimationSemanticCache.lookup()
                                                                (redisvl vector similarity)
            4. app/prompts/loader.py::render_estimation_prompt()  (Jinja2 versioned templates)
            5. app/services/llm_wrapper.py::complete_structured()
                                                                (Instructor + Pydantic validators
                                                                 with automatic re-prompt)
            6. app/guardrails/output.py::enforce_scope_response() (filter policy)
            7. cache.set() + semantic_cache.store()
            8. return EstimationResponse(result, prompt_version, cached)
```

Key design points future changes should respect:

- **The router has no business logic.** It only catches three exceptions and turns them into HTTP statuses: `InputGuardrailViolation` → 400, anything else from the pipeline (including `instructor.exceptions.InstructorRetryException`) → 502, plus Pydantic 422 from `EstimationRequest` validation. Add new policies inside `EstimationService.estimate()`, not in the router.
- **Schema is the contract.** `EstimationResult` (in `app/schemas/estimation.py`) is what Instructor enforces against the LLM. The two `model_validator`s (`phases_sum_matches_total`, `low_confidence_requires_out_of_scope_prefix`) are the business rules — when they raise, Instructor re-prompts the LLM up to `max_retries=6` times.
- **Field order matters with Instructor.** `phases` is declared BEFORE `total_cost_eur` / `total_duration_weeks` on purpose: the LLM emits phases first (autoregressive) and then only needs to sum, instead of picking a round total and back-fitting phases. With smaller models like `gpt-4o-mini` this is the difference between consistent success and arithmetic failures.
- **Two caches in series.** Exact-match cache (`app/services/cache.py`) keys on SHA-256 of the typed request + prompt_version + model. The semantic cache (`app/cache/semantic.py`) layers on top: same bucket (`prompt_version:project_type:detail_level:output_format`) + cosine similarity ≥ `SEMANTIC_CACHE_THRESHOLD` (default 0.85). The semantic cache requires Redis Stack (`redis/redis-stack:7.4.0-v0`), not vanilla Redis — RediSearch is mandatory for vector queries.
- **Guardrails are policies, not features.** `check_input` uses `exception` policy (raise on violation). `enforce_scope_response` uses `filter` (rewrite the summary). The schema validators use `re-prompt` (Instructor handles it). The split is documented in the live-session guide.
- **Settings are a cached singleton** via `app/config.py::get_settings` (`@lru_cache`). Any change to `.env` requires recreating the container (`docker compose up -d --force-recreate`); a `--reload` is not enough.
- **Logging** is `structlog`. JSON in `production`, console in dev. Use `structlog.get_logger()` rather than stdlib `logging`.
- **The LLM wrapper bypasses the Router for streaming and for structured calls** (see `_dispatch`). LiteLLM's Router does round-robin between deployments, which would non-deterministically route to a fallback that may be unreachable. For deterministic behaviour `complete_structured` always uses the primary model directly.

## Architecture (Session 5 — conversational)

Multi-turn estimation with optional PDF/DOCX attachments. Sessions live in an in-memory `SessionStore` (one per worker; lost on restart — persistence is module-3 territory).

```
POST /api/v1/sessions
  └→ returns session UUID

POST /api/v1/sessions/{session_id}/estimate   (multipart/form-data)
  └→ app/routers/sessions.py
       └→ enrich_transcript() — extract attachment text locally (Camino B)
       └→ EstimationService.estimate_conversational()
            compression (anchor detection + cumulative summarizer)
            → LLM with tier-aware conversational prompt (v3)
            → optional Boss/Critic ACB loop (BOSS_MAX_ITERATIONS)
       └→ EstimationResponse + TurnObservation telemetry
```

Key design points:

- **Router mirrors v1 error mapping** plus attachment-specific 415/422.
- **`SessionStore` is process-local.** `docker compose restart` clears sessions; do not assume cross-worker sharing.
- **Compression runs before the LLM call** to keep history within the turn budget (`MAX_CONVERSATION_TURNS`).
- **`TurnObservation`** on the response exposes token/cost/latency telemetry consumed by the Session 6 stress runner — no log parsing.

## Architecture (Session 6 — data-driven AI)

Data catalog, ingestion pipeline, PII pseudonymization, and Postgres persistence. Ingestion is **not** wired into the estimation request path yet — it prepares the corpus for retrieval in Session 7.

### CAG / RAG decision (`app/ingestion/architecture.py`)

CLI-only module (Article 1). Evaluates four CAG constraints as an **AND** (context window, cost, latency, lost-in-the-middle) and recommends `CAG | Hybrid | RAG` over volume, refresh frequency, traceability, and access control. Run with `python -m app.ingestion.architecture`.

### Data catalog (`data/catalog/catalog.yaml`)

Versioned YAML loaded at startup via `get_catalog()`. Each source has an explicit `decision`: `include`, `review`, or `exclude`. Only `include` sources can be ingested. Inspect seed data with `python -m app.ingestion.catalog.inspect data/seed`; validate YAML with `python -m app.ingestion.catalog.loader data/catalog/catalog.yaml`. A malformed catalog fails at startup (lifespan hook), not on first request.

### Ingestion pipeline

```
POST /api/v1/ingestion/runs
  └→ app/routers/ingestion.py    (thin HTTP layer — no parser imports)
       ├→ validate source exists + decision == include
       ├→ JobsRepository.create() → 202 immediately
       └→ BackgroundTask → ingest_source()
            catalog.find() → loader.iter_blobs() → parser.parse() → list[Document]
            jobs_repo: pending → running → completed | failed

GET /api/v1/ingestion/jobs/{job_id}
  └→ poll job status from ingestion_jobs table
```

Key design points:

- **Router has no ingestion logic.** All parsing lives in `app/ingestion/orchestrator.py` and below.
- **Orchestrator is synchronous** — invoked from a `BackgroundTask` with its own DB session.
- **Parser registry** (`app/ingestion/parsers/registry.py`) registers JSON + TXT only. XLSX/DOCX/PDF parsers ship in `guides/session-06-reference/`; adding them is a one-line `registry.register()`.
- **`Document` is the canonical output** — flat model with `DocumentMetadata` + format-specific `extra` dict. IDs must be stable across re-ingestions for downstream dedup.

### Data cleaning (`app/ingestion/cleaning/`)

Pandera schemas validate budget records with `lazy=True` to collect all failures. `ValidationPolicy` routes rows into three buckets: `valid`, `quarantined` (recoverable — e.g. missing optional metadata), `discarded` (structural — e.g. negative amounts). Demo: `scripts/demo_cleaning_s06.py`.

### PII pseudonymization (`app/ingestion/pii/`)

Presidio analyzer (Spanish spaCy model `es_core_news_md`) detects entities; `ConsistentPseudonymizer` replaces them with stable Faker-generated pseudonyms keyed by HMAC-SHA256 of the original value + server salt. Mappings persist in `pseudonym_mappings` via `PostgresMappingStore`. Reversibility lives in the mapping store — deleting a row invalidates future lookups without touching the corpus. Demo: `scripts/demo_pii_s06.py`.

### Persistence (`app/persistence/`)

SQLAlchemy 2.0 + Alembic. Two tables in Session 6:

- `pseudonym_mappings` — `(entity_type, original_hash)` → pseudonym. Hash-only storage supports GDPR Art. 17 auditability.
- `ingestion_jobs` — async job bookkeeping for the ingestion endpoints.

`estimator-postgres` uses `pgvector/pgvector:pg16` but **pgvector is dormant** in S06 (no `CREATE EXTENSION vector`); Session 7 activates it. Host port `5433`, in-network port `5432`. Docker startup runs `alembic upgrade head` before uvicorn.

### Session 6 stress eval (`evals/stress/`)

Empirically maps where CAG breaks under growing attachments and conversational drift. Drives `POST /sessions/{id}/estimate` across scenarios × attachment sizes, reads `TurnObservation` telemetry, writes CSV with `CostBudgetMetric`, `LatencyBudgetMetric`, `MemoryDriftMetric` verdicts. Run: `uv run python -m evals.stress.run --http http://localhost:8000`.

## Configuration

`.env` (copied from `.env.example`) drives everything via `pydantic-settings`.

Session 2/3 vars:
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` — at least one required.
- `PRIMARY_MODEL` / `FALLBACK_MODEL` — LiteLLM Router config.
- `LLM_TIMEOUT` / `LLM_RETRIES` — per LLM call.
- `REDIS_URL` — points to the Redis Stack container in compose.

Session 4 vars:
- `EMBEDDING_MODEL` — defaults to `text-embedding-3-small`.
- `SEMANTIC_CACHE_THRESHOLD` — cosine similarity threshold (0..1). 0.85 default = the typical range mentioned in the live guide. Lower = more hits, more false positives.
- `SEMANTIC_CACHE_TTL` — seconds (24h default).
- `SEMANTIC_CACHE_LOG_ONLY` — when `true`, the cache logs would-be hits but never serves them. Use it to calibrate the threshold against real traffic before flipping on.

Session 5 vars:
- `MAX_CONVERSATION_TURNS` — user+assistant pairs kept in the sliding window (default 6).
- `MAX_ATTACHMENT_CHARS` — hard cap per extracted attachment (default 60_000).
- `METADATA_EXTRACTOR_MODEL` — cheap model for per-turn metadata extraction.
- `ANCHOR_DETECTION_MODE` — `heuristic` (regex) or `llm` (Instructor classifier).
- `COMPRESSION_MODEL` — model for cumulative history summarization.
- `CONVERSATIONAL_PROMPT_VERSION` — `v3` adds tier-aware `<audience>` and Boss `<critic_feedback>` blocks.
- `CRITIC_MODEL` / `BOSS_MAX_ITERATIONS` — Actor-Critic-Boss loop settings.

Session 6 vars:
- `DATABASE_URL` — Postgres for pseudonym mappings + ingestion jobs. Default `postgresql+psycopg://estimator:estimator@localhost:5433/estimator` (host); Docker overrides to `estimator-postgres:5432`.
- `CATALOG_PATH` — YAML catalog location (default `data/catalog/catalog.yaml`).
- `INGESTION_DATA_ROOT` — root for `CatalogSource.location` paths (default `data/seed`).
- `PRESIDIO_SPACY_MODEL` — Spanish spaCy model for Presidio (default `es_core_news_md`; install with `python -m spacy download es_core_news_md`).
- `PSEUDONYM_FAKER_LOCALE` — Faker locale for pseudonym generation (default `es_ES`).
- `PSEUDONYM_HASH_SALT` — HMAC salt for mapping keys. Rotate independently of code; change invalidates existing hash lookups.

## Docker

Multi-stage Dockerfile: `builder` installs prod-only deps with `uv sync --no-install-project --no-dev`, `runtime` is a clean `python:3.11-slim` that only carries `/app/.venv` and `app/`, runs as non-root `appuser`. There is a Docker-native HEALTHCHECK against `/health`.

`docker-compose.yml` services: `estimator`, `redis`, `estimator-postgres`. Bind-mounts `./app`, `./tests`, `./data`, and `./alembic` for development. Startup command runs `alembic upgrade head` then uvicorn with `--reload`. Redis uses `redis/redis-stack:7.4.0-v0` for RediSearch. Postgres uses `pgvector/pgvector:pg16` on host port `5433`.

For running tests inside the container the prod image lacks pytest. Two options:
```bash
# 1. Run on the host with uv
cd estimator && uv sync && uv run pytest

# 2. Install ad-hoc inside the container (lost on rebuild)
docker compose exec estimator bash -c '
  python -m ensurepip --upgrade && \
  python -m pip install --quiet pytest pytest-asyncio fakeredis httpx
'
docker compose exec estimator python -m pytest tests/ -v
```

## estimator-web (Rails)

Full guide in `estimator-web/README.md`. Consumes `POST /api/v1/estimate` and renders the structured `EstimationResponse`. Quick reference:

```bash
cd estimator-web
docker compose up --build               # http://localhost:3000

# Or with the FastAPI estimator (shared network):
cd <monorepo-root>
docker compose up --build
```

Common operations:

```bash
docker compose exec estimator-web bin/rails console
docker compose exec estimator-web bin/rails test
docker compose exec postgres psql -U postgres estimator_web_development
```

Design points to respect when editing:

- **`EstimationResponse.from_hash` builds nested `EstimationResult` + `Phase` POROs** from the FastAPI JSON. The view (`show.html.erb`) renders the typed object, not raw text.
- **The `Stimulus form_loading_controller`** is intentionally simple: it just disables the submit button and shows rolling phase messages while Rails waits for FastAPI. No SSE / no streaming — those were removed when the response became a single JSON object.
- **The cliente never talks to OpenAI / Anthropic directly.** It only POSTs to FastAPI, and the FastAPI handles guardrails, LLM calls and caches. That boundary is deliberate and documented in the session guide.
- **GuardrailViolation is a first-class error** in the cliente (`app/services/estimator_ai/client.rb`). The FastAPI returns 400 with `{detail: {reason, message}}` when input is rejected (moderation/prompt_injection/pii); the cliente surfaces this in `flash`.
- **`config/database.yml` reads `DATABASE_HOST` / `DATABASE_PORT` / `DATABASE_USER` / `DATABASE_PASSWORD` from ENV** with `nil` fallbacks (Unix socket when not in docker).
- **Kamal and Thruster** (`.kamal/`, `config/deploy.yml`, `bin/kamal`, `bin/thrust`, gems with `require: false`) are leftovers from `rails new`. Production is out of scope.
