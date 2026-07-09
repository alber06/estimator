# Stress eval — informe

**Dataset:** `evals/stress/results.csv` — 900 filas (3 escenarios × 5 tamaños de adjunto × 3 repeticiones × 20 turnos).  
**Presupuestos por turno:** latencia ≤ 120 s, coste ≤ 1 USD. **Ventana de sesión en eval:** `max_turns=6`.

---

## Tabla resumen

Coste total = suma de `cost_usd` de los 60 turnos de la celda (3 repeticiones × 20 turnos).  
Recall fact-tracker = media de `memory_drift_passed` en turnos evaluables (turn > 1); comprueba si el hecho ancla del turno 1 persiste en summary/anchors/metadata.

| Escenario | Adj. (KB) | P50 lat. (ms) | P95 lat. (ms) | Coste total (USD) | Cache exacto | Cache semántico | Recall fact-tracker |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| grow | 0 | 5 224 | 10 675 | 0.06 | 0 % | 0 % | 1.00 |
| grow | 5 | 11 304 | 18 006 | 0.11 | 0 % | 0 % | 1.00 |
| grow | 20 | 16 142 | 21 716 | 0.28 | 0 % | 0 % | 1.00 |
| grow | 50 | 16 748 | 35 771 | 0.60 | 0 % | 0 % | 1.00 |
| grow | 100 | 16 416 | 31 428 | 0.72 | 0 % | 0 % | 1.00 |
| pivot | 0 | 5 068 | 11 607 | 0.05 | 0 % | 0 % | 1.00 |
| pivot | 5 | 10 124 | 21 047 | 0.11 | 0 % | 0 % | 1.00 |
| pivot | 20 | 9 644 | 18 368 | 0.26 | 0 % | 0 % | 1.00 |
| pivot | 50 | 14 080 | 21 385 | 0.58 | 0 % | 0 % | 1.00 |
| pivot | 100 | 16 426 | 29 635 | 0.69 | 0 % | 0 % | 1.00 |
| contradict | 0 | 5 408 | 11 958 | 0.05 | 0 % | 0 % | 1.00 |
| contradict | 5 | 16 004 | 21 479 | 0.11 | 0 % | 0 % | 1.00 |
| contradict | 20 | 17 648 | 21 734 | 0.28 | 0 % | 0 % | 1.00 |
| contradict | 50 | 20 277 | 24 915 | 0.61 | 0 % | 0 % | 1.00 |
| contradict | 100 | 20 686 | 24 157 | 0.73 | 0 % | 0 % | 1.00 |

Ningún turno supera los presupuestos de latencia ni coste. Caché exacta y semántica permanecen en 0 %: cada turno es una petición nueva con contexto distinto.

---

## Curvas (tablas)

### Latencia vs `tokens_in`

Agregado sobre las 900 observaciones, agrupado por bucket de ~1 000 tokens (P50/P95).

| tokens_in (≈) | P50 (ms) | P95 (ms) | n |
| ---: | ---: | ---: | ---: |
| 2 000 | 5 059 | 8 875 | 103 |
| 3 000 | 5 196 | 10 300 | 190 |
| 4 000 | 5 205 | 11 387 | 209 |
| 5 000 | 5 224 | 11 539 | 201 |
| 6 000 | 5 325 | 12 995 | 171 |
| 8 000 | 6 914 | 17 408 | 48 |
| 10 000 | 13 584 | 20 345 | 144 |
| 12 000 | 13 797 | 20 761 | 167 |
| 35 000 | 16 155 | 21 933 | 106 |
| 75 000 | 17 188 | 32 668 | 105 |
| 100 000 | 21 582 | 31 845 | 30 |

Por debajo de ~6 000 tokens la latencia se mantiene ~5 s (P50). A partir de ~10 000 tokens salta a ~13–14 s; con adjuntos grandes (>70 k tokens) P95 supera 30 s.

### Coste acumulado vs `turn_index` (sin adjunto, mediana por repetición)

| turn | grow (USD) | pivot (USD) | contradict (USD) |
| ---: | ---: | ---: | ---: |
| 1 | 0.0005 | 0.0004 | 0.0005 |
| 5 | 0.0031 | 0.0024 | 0.0030 |
| 10 | 0.0073 | 0.0062 | 0.0069 |
| 15 | 0.0119 | 0.0104 | 0.0112 |
| 18 | 0.0160 | 0.0129 | 0.0141 |
| 19 | 0.0181 | 0.0138 | 0.0151 |
| 20 | 0.0191 | 0.0146 | 0.0160 |

Con adjunto 100 KB el coste acumulado a turno 20 ronda 0.23–0.24 USD por sesión (~12× el baseline sin adjunto). La curva es aproximadamente lineal en turnos; el salto en **grow** en turnos 18–19 (+0.002 USD/turno, ~2× el coste medio) coincide con el pico de tokens.

### MemoryDriftMetric vs N (sin adjunto)

| turn | grow | pivot | contradict |
| ---: | ---: | ---: | ---: |
| 1 | — | — | — |
| 5 | 1.00 | 1.00 | 1.00 |
| 10 | 1.00 | 1.00 | 1.00 |
| 15 | 1.00 | 1.00 | 1.00 |
| 20 | 1.00 | 1.00 | 1.00 |

El hecho ancla del turno 1 aparece en summary, anchors o metadata en el 100 % de los turnos evaluables, en los tres perfiles y con cualquier tamaño de adjunto. No hay deriva de memoria medible con la métrica actual (solo comprueba el primer hecho, no el fact-tracker completo).

---

## Lectura

**¿A partir de qué turno se rompe el CAG?** Sin adjuntos, el sistema aguanta bien hasta el turno 17: `tokens_in` crece de forma gradual (de 2200 a 5400) y P50 se mantiene alrededor de 5s. En **grow** el primer síntoma aparece en el **turno 18**: `tokens_in` se duplica (de 5400 a a 12000), la latencia mediana pasa de ~5,3 s a ~10,4 s (P95 > 20 s en ese bucket) y el coste por turno se duplica. Es el punto en que la ventana deslizante (`max_turns=6`) fuerza una recomposición del contexto y el prompt aumenta; el turno 20 vuelve a ~5 250 tokens, señal de buena compactación, pero con un pico intermedio. Con adjuntos ≥ 5 KB la rotura es inmediata: P50 salta de ~5 s a ~10–16 s ya en el turno 1 y el coste escala con el tamaño del PDF, independientemente del número de turno.

**¿Qué dimensión domina y cuándo saltar a RAG?** La degradación la domina la **latencia ligada al volumen de tokens de entrada**, no la pérdida de memoria ni el coste absoluto. El coste acumulado a 20 turnos sin adjunto es ~0.02 USD — marginal frente a ~0.24 USD con PDF de 100 KB — pero incluso en el peor caso no se viola el presupuesto de 1 USD/turno. La memoria del hecho ancla no falla en ningún escenario. Un **caso límite que justifica RAG** sería una sesión multi-turno con adjuntos grandes (50–100 KB) reiterados en cada turno: ~75–100 k tokens de entrada, P95 > 30 s, coste de sesión ~0.24 USD sin ningún cache hit, y picos de recomposición como el de turno 18 en grow donde el contexto inline duplica tokens de un turno a otro. En ese régimen el CAG paga el PDF entero en cada llamada; RAG recuperaría solo los fragmentos relevantes y estabilizaría latencia y coste frente al crecimiento de adjuntos y turnos.
