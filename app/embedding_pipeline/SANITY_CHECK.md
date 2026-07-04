# Sanity check — similitud coseno entre embeddings

Ejecutado con `scripts/compare.py` (modelo `text-embedding-3-small`, vía contenedor Docker `estimator`).

Última ejecución: 2026-07-04.

## Pareja A — Textos semánticamente cercanos

**Expectativa:** similitud alta (orientativamente > 0.6).

| | Texto |
|---|---|
| Texto 1 | OAuth 2.0 authentication backend with JWT tokens for fintech mobile app |
| Texto 2 | Authorization service using JSON Web Tokens for a banking application |

**Resultado:** `0.5957`

**Veredicto:** Similitud alta, ligeramente por debajo del umbral orientativo de 0.6, pero ambos textos comparten el mismo dominio (auth/OAuth/JWT, fintech/banking) y el modelo los sitúa claramente por encima del ruido.

---

## Pareja B — Textos no relacionados

**Expectativa:** similitud baja (orientativamente < 0.4).

| | Texto |
|---|---|
| Texto 1 | OAuth 2.0 authentication backend with JWT tokens for fintech mobile app |
| Texto 2 | Database migration from MySQL to PostgreSQL with zero downtime |

**Resultado:** `0.1920`

**Veredicto:** Similitud baja; el embedding distingue bien un texto de autenticación de uno de migración de base de datos.

---

## Pareja C — Textos genéricos y ambiguos

**Expectativa:** ninguna fija; observar el comportamiento.

| | Texto |
|---|---|
| Texto 1 | Backend services |
| Texto 2 | API development |

**Resultado:** `0.5407`

**Comentario:** El resultado sorprende en este caso. A pesar de ser frases cortas y vagas, la similitud es moderada-alta (~0.54). "Backend services" y "API development" comparten significado semántico aunque no sean sinónimos literales. Esto implica que consultas genéricas pueden recuperar chunks relacionados por área técnica aunque el detalle difiera.
