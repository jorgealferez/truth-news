# ADR 0008 — Temas y piezas propias en dos tablas nuevas y story.topic_id

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-18
- **Fase:** 2b
- **Decide:** Constructor, auditado por el Critico

## Contexto
ADR 0007: la IA agrupa historias en temas y redacta piezas propias (analisis y opinion) por tema. Hoy
existen `story` (ADR 0005) y no hay donde guardar temas ni piezas (criterios C12, C13).

## Necesidad
Imprescindible: las piezas se generan con coste (llamadas a la API) y deben servirse en cada peticion
de la portada y de `/tema/{id}` sin regenerarse; los temas agrupan historias y la web los lista.
Alternativa sin esquema descartada: guardar la pieza en JSON dentro de `story` (una pieza cubre varias
historias; duplicarla rompe la consistencia y el enlazado).

## Escalabilidad
Medido: 187 historias con >= 2 medios en un rastreo completo; ~15-30 temas al dia con >= 2 historias.
Con el tope de 6 piezas por ciclo de 30 min, como mucho ~290 piezas/dia; en la practica ~30-60
(regeneracion solo si cambia el dossier). A 12 meses: ~11 000 temas y ~20 000 piezas (cuerpo y sintesis
en JSON, ~10-30 KB por pieza: ~0,5 GB). Consultas: portada por `piece.status`+`created_at` (indice) y
temas por `country`+`last_seen` (indice); historias de un tema por `story.topic_id` (indice). A 10x
sigue siendo lectura por indice acotada por LIMIT.

## Coherencia
Convenciones de ADR 0002/0005: claves enteras, fechas UTC, ISO 3166. `story.topic_id` nullable con
`ON DELETE SET NULL` y FK con nombre (`fk_story_topic_id`). `piece.topic_id` con CASCADE (una pieza no
existe sin su tema). `piece.kind` y `piece.status` restringidos por CHECK. `body` y `synthesis` son JSON:
estructura definida por el esquema de salida del ADR 0007 y validada en codigo antes de guardar.
`input_hash` permite no regenerar si el dossier no cambia.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Tabla N:M `topic_story` | Una historia pertenece a un tema; FK simple suficiente |
| Pieza por historia en lugar de por tema | El usuario pide sintesis de temas con distinto enfoque; una historia sola ya tiene su comparativa |
| Guardar el Markdown generado | Se renderiza sin HTML del modelo: secciones estructuradas y escapadas, enlaces construidos por el codigo |

## Necesidades futuras
Fase 4 (redes) generara piezas cortas desde `piece`; Fase 3 (investigaciones) reutilizara `piece` con
otro `kind` (requerira ampliar el CHECK con su propio ADR). Multi-idioma: una pieza por idioma via
`language`.

## Migracion y reversibilidad
Migracion `0003_temas_y_piezas` en un paso: crea `topic` y `piece` y anade `story.topic_id` (columna
nula, sin backfill). Serializada con el bloqueo consultivo del ADR 0005. Reversible con `downgrade` a
`0002` (se pierden temas y piezas, regenerables con coste de API).

## Decision
Se crean `topic` y `piece` y la columna `story.topic_id` en `truthnews/models.py` y la migracion
`alembic/versions/0003_temas_y_piezas.py`.

## Verificacion
`tests/test_migrations.py` (upgrade/downgrade y paridad con modelos) y tests de la pipeline de IA que
escriben y leen temas y piezas.

## Alcance
- `truthnews/models.py`
- `alembic/versions/0003_temas_y_piezas.py`
