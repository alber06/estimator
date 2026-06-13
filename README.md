# Estimator CAG - Servicio de Estimacion de Software con IA

Servicio de estimacion de proyectos de software impulsado por IA, utilizando una arquitectura **Cache Augmented Generation (CAG)**.

## Que es CAG y por que lo usamos

CAG (Cache Augmented Generation) es un patron de arquitectura donde el contexto relevante se inyecta directamente en el prompt del LLM como texto estatico. En esta fase del proyecto, las estimaciones de referencia se incluyen como ejemplos dentro del prompt del sistema, sin necesidad de una base de datos vectorial ni busqueda semantica.

Este enfoque es ideal para empezar porque:
- Es simple de implementar y depurar
- No requiere infraestructura adicional (ni embeddings, ni vector stores)
- Funciona bien cuando el volumen de contexto es manejable (pocos ejemplos)

En modulos posteriores del master, este servicio evolucionara a una arquitectura **RAG** (Retrieval Augmented Generation) con base de datos vectorial para manejar un volumen mayor de ejemplos.

## Requisitos previos

- **Docker** y **Docker Compose** (recomendado)
- Una **API key** de OpenAI y/o Anthropic (al menos una)
- Para desarrollo local sin Docker: **Python 3.11+** y **[uv](https://docs.astral.sh/uv/)**

## Inicio rapido con Docker (recomendado)

1. Clonar el repositorio y entrar al directorio raiz:
   ```bash
   cd estimator
   ```

2. Copiar el archivo de variables de entorno y configurar las API keys:
   ```bash
   cp .env.example .env
   # Editar .env y poner tu API key real
   ```

3. Construir y levantar la stack (API + Redis):
   ```bash
   docker compose up --build
   ```

4. Servicios disponibles:
   - **API:** `http://localhost:8000`
   - **Redis:** `redis://localhost:6379`
   - **Health check:** `GET /health`

## Ejecucion local sin Docker

Necesitas Redis accesible en `REDIS_URL` (por defecto `redis://localhost:6379`). Puedes levantar solo Redis con Docker:

```bash
docker compose up redis -d
```

Luego instala dependencias y arranca la API:

```bash
uv sync
cp .env.example .env   # si aun no lo tienes
uv run uvicorn app.main:app --reload
```

> **Nota:** la configuracion se cachea al arrancar el proceso. Si cambias `.env`, reinicia uvicorn por completo (un `--reload` no basta para el singleton de settings).

## Probar el servicio

El endpoint principal es `POST /api/v1/estimate`. El cuerpo de la peticion incluye la descripcion del proyecto y parametros que condicionan el prompt:

| Campo | Valores |
|-------|---------|
| `project_type` | `mobile_app`, `web_saas`, `internal_tool`, `data_pipeline` |
| `detail_level` | `summary`, `medium`, `detailed` |
| `output_format` | `phases_table`, `line_items`, `narrative` |
| `reference_projects` | *(opcional)* lista de proyectos de referencia con coste, tiempo y equipo |

Version del prompt (query param): `?prompt_version=v1` (default) o `?prompt_version=v2`.

```bash
curl -X POST "http://localhost:8000/api/v1/estimate?prompt_version=v1" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "The client wants to build a mobile app for managing restaurant reservations. They need user registration, a restaurant search with filters by cuisine and location, a real-time reservation system with availability checking, push notifications for reservation confirmations and reminders, and an admin panel for restaurant owners to manage their listings and view analytics.",
    "project_type": "mobile_app",
    "detail_level": "medium",
    "output_format": "phases_table"
  }'
```

Con proyectos de referencia (v2):

```bash
curl -X POST "http://localhost:8000/api/v1/estimate?prompt_version=v2" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "We need a small CRM with auth, contacts and roles. MVP six weeks.",
    "project_type": "web_saas",
    "detail_level": "detailed",
    "output_format": "line_items",
    "reference_projects": [
      {
        "description": "Internal sales dashboard delivered last quarter",
        "estimated_cost": 42000,
        "estimated_time": 680,
        "estimated_team": ["1 backend dev", "1 frontend dev", "0.5 designer"]
      }
    ]
  }'
```

## Tests

Instala dependencias de desarrollo y ejecuta la suite:

```bash
uv sync
uv run pytest
```

Comandos utiles:

```bash
# Un fichero concreto
uv run pytest tests/test_health.py -v

# Solo cache y wrapper LLM (sin llamadas reales al proveedor)
uv run pytest tests/test_cache.py tests/test_llm_wrapper.py -v

# Lint
uv run ruff check .
uv run ruff format .
```

Los tests usan `fakeredis` y mocks de LiteLLM, por lo que **no requieren API keys ni Redis real** para la mayor parte de la suite.

## Estructura del proyecto

```
estimator/
├── app/
│   ├── main.py                 # FastAPI, health check, CORS, static files
│   ├── config.py               # Settings (Pydantic)
│   ├── dependencies.py         # Singletons: cache Redis + LLMWrapper
│   ├── routers/
│   │   └── estimations.py      # POST /api/v1/estimate y /estimate/stream
│   ├── services/
│   │   ├── llm_wrapper.py      # LiteLLM Router, fallback, coste, streaming
│   │   └── cache.py            # Cache exact-match en Redis
│   ├── prompts/
│   │   ├── loader.py           # Render Jinja2 (system + user)
│   │   └── estimation/
│   │       ├── v1/             # Prompt version 1 (system, user, examples)
│   │       └── v2/             # Prompt version 2 (+ reference_projects)
│   ├── schemas/
│   │   └── estimation.py       # Request/response Pydantic
│   └── static/
│       └── sse_demo.html       # Demo HTML del streaming SSE
├── streamlit_app.py            # UI Streamlit (formulario)
├── tests/
│   ├── test_health.py
│   ├── test_cache.py
│   ├── test_llm_wrapper.py
│   ├── test_estimate_stream.py
│   └── prompts/
│       └── test_estimation_v1.py
├── Dockerfile
├── docker-compose.yml          # API + Redis
└── pyproject.toml
```

## Documentacion interactiva

Con el servicio corriendo:

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

## Sesion 3 — LiteLLM, Redis cache, SSE y Streamlit

El servicio incorpora una capa de wrapper sobre el LLM (`LLMWrapper`) que anade:

- **Fallback de proveedor** (LiteLLM Router) — si el modelo primario falla, se intenta el secundario
- **Cache exact-match** en Redis — misma peticion no vuelve a pagar tokens (`cache_hit: true`)
- **Streaming SSE** — `POST /api/v1/estimate/stream` emite tokens segun llegan
- **UI Streamlit** — formulario que consume la API por HTTP

### Variables de entorno relevantes

| Variable | Default | Descripcion |
|----------|---------|-------------|
| `PRIMARY_MODEL` | `gpt-4o-mini` | Modelo principal del Router |
| `FALLBACK_MODEL` | `claude-haiku-4-5-20251001` | Modelo de respaldo |
| `REDIS_URL` | `redis://localhost:6379` | URL de Redis |
| `CACHE_TTL` | `86400` | TTL de cache en segundos |
| `ESTIMATOR_API_BASE_URL` | `http://localhost:8000` | URL base para Streamlit |

### Probar el endpoint SSE

Demo HTML: [http://localhost:8000/static/sse_demo.html](http://localhost:8000/static/sse_demo.html)

Desde CLI:

```bash
curl -N -X POST "http://localhost:8000/api/v1/estimate/stream?prompt_version=v1" \
  -H 'Content-Type: application/json' \
  -d '{
    "description": "We need a small CRM with auth, contacts and roles. MVP six weeks.",
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "narrative"
  }'
```

### Verificar la cache

```bash
# La misma peticion dos veces — la segunda devuelve cache_hit: true
curl -s "http://localhost:8000/api/v1/estimate?prompt_version=v1" \
  -H 'Content-Type: application/json' \
  -d '{
    "description": "We need a small CRM with auth, contacts and roles. MVP six weeks.",
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "phases_table"
  }' | jq '{cache_hit, cost_usd}'

# Inspeccionar claves en Redis
docker compose exec redis redis-cli KEYS 'estimation:*'
```

### Streamlit

Streamlit corre **fuera** del contenedor de la API:

```bash
uv sync
uv run streamlit run streamlit_app.py
# Abrir http://localhost:8501
```

La URL del backend se lee de `ESTIMATOR_API_BASE_URL` (default `http://localhost:8000`).

## Sesion 4 — Prompts versionados, proyectos de referencia y logging

Cambios principales de esta rama:

- **Prompts en Jinja2** — plantillas en `app/prompts/estimation/v1/` y `v2/`, renderizadas por `loader.py`. Los ejemplos CAG viven en `examples.j2`, no en codigo Python.
- **Dos versiones de prompt** — seleccionables con `?prompt_version=v1|v2`. La v2 soporta `reference_projects` en el system prompt.
- **Nuevo contrato de API** — `EstimationRequest` exige `project_type`, `detail_level` y `output_format`; la descripcion debe tener entre 50 y 2000 caracteres.
- **Logging estructurado** — `structlog` con salida legible en desarrollo y JSON en produccion (`APP_ENV=production`).
- **Refactor del endpoint** — el router delega en `render_estimation_prompt` + `LLMWrapper`; la validacion estructural de sesiones anteriores se elimino.

---

> Este proyecto forma parte del **Master en AI Engineering** y servira como base para evolucionar hacia una arquitectura RAG con base de datos vectorial en modulos posteriores.
