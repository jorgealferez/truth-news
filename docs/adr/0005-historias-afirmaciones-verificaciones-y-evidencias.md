# ADR 0005 — Historias, afirmaciones, verificaciones y evidencias en cuatro tablas nuevas

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-18
- **Fase:** 2
- **Decide:** Constructor, auditado por el Critico

## Contexto
ADR 0004: el comparador necesita agrupar articulos en historias y guardar las afirmaciones extraidas,
sus veredictos y la evidencia de cada veredicto (criterios C4, C5, C6). Hoy existen `outlet`, `feed`,
`article` y `crawl_run` (ADR 0002); `article` no tiene relacion con ninguna agrupacion.

## Necesidad
Imprescindible persistir la historia: la portada, la pagina de historia y la fiabilidad por medio
leen historias y veredictos en cada peticion (p95 objetivo < 300 ms) y no pueden reagrupar miles de
articulos al vuelo. Alternativa sin esquema descartada: recalcular la agrupacion en cada peticion
(medido el 2026-10-18: agrupar 2 805 articulos reales cuesta 5,9 s en Python puro sin indice invertido, incompatible con C7). Las cifras en disputa,
omisiones y lenguaje SI se calculan en lectura a partir de los articulos de la historia (no se
guardan): son baratas (decenas de articulos por historia) y cambian con cada articulo nuevo.

## Escalabilidad
Produccion mide ~2 800 articulos en el primer ciclo y ~200-400 nuevos por ciclo de 30 min, ~10 000/dia.
Con el 74 % de historias de un solo articulo (medido: 2 805 articulos -> 2 072 historias, 192 con >= 2 medios), ~4 000 historias/dia, ~1,5 M a 12 meses (~300 B/fila,
~0,5 GB). Afirmaciones: solo en historias con >= 2 medios y solo numericas sobre indicadores conocidos:
estimacion 1-5 % de articulos, ~300/dia, ~110 000/ano; verificaciones 1:1 y evidencias 1-3 por
verificacion (~330 000 filas/ano, payload JSON < 2 KB). Consultas: portada por `story.last_seen`
filtrada por `country` y `n_outlets >= 2` -> indice `(country, last_seen)`; articulos de una historia
-> indice `article.story_id`; veredictos por medio -> `claim.outlet_id` + `verification.claim_id`
unico. A 10x (15 M historias) el listado sigue siendo un recorrido de indice acotado por LIMIT.

## Coherencia
Mismas convenciones que ADR 0002: claves enteras, fechas UTC con zona, ISO 3166 en `country`.
`article.story_id` nullable con `ON DELETE SET NULL` (un articulo puede no estar agrupado aun).
`claim` referencia `article` y `story` (CASCADE desde articulo) y desnormaliza `outlet_id` para
agregar fiabilidad por medio sin JOIN a `article`. `verification.claim_id` unico (1:1, re-verificar
actualiza). `verdict` restringido por CHECK a la escala cerrada del ADR 0004. `evidence` cuelga de
`verification` con CASCADE. Invariante C6 en codigo y en test: un veredicto distinto de `sin-datos`
exige al menos una evidencia.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Tabla N:M `story_article` | Un articulo pertenece a una sola historia; una FK en `article` es mas simple y suficiente |
| Guardar cifras en disputa y omisiones | Son derivadas y cambian con cada articulo; guardarlas obliga a invalidar caches |
| Verificacion y evidencia en un JSON dentro de `claim` | Impide consultar veredictos por medio con indices y validar la escala con CHECK |

## Necesidades futuras
Investigaciones a demanda (Fase 3) reutilizaran `evidence` con una `investigation` propia (su ADR).
Re-verificar con datos nuevos actualiza la fila de `verification` (historico en Fase 3 si se pide).
Multi-pais: `story.country` permite portadas por pais; las evidencias guardan la `geo` consultada.

## Migracion y reversibilidad
Migracion `0002_comparador` en un paso: crea cuatro tablas y anade `article.story_id` (columna nula,
sin backfill: el worker agrupa la ventana de 72 h en el siguiente ciclo). En PostgreSQL anadir una
columna nula sin defecto no reescribe la tabla. Web y worker ejecutan `db upgrade` al arrancar a la vez: `alembic/env.py` toma un bloqueo consultivo de
PostgreSQL (`pg_advisory_lock`) para que la segunda migracion espere a la primera y encuentre la
version ya aplicada. Reversible con `downgrade` a `0001` (se pierden
historias y veredictos, recalculables desde los articulos y las APIs publicas).

## Decision
Se crean `story`, `claim`, `verification` y `evidence` y la columna `article.story_id`, en
`truthnews/models.py` y la migracion `alembic/versions/0002_comparador.py`.

## Verificacion
`tests/test_migrations.py` aplica `upgrade head` y `downgrade base` y compara con los modelos; tests
del pipeline que escriben y leen historias, afirmaciones y evidencias.

## Alcance
- `truthnews/models.py`
- `alembic/versions/0002_comparador.py`
- `alembic/env.py`
