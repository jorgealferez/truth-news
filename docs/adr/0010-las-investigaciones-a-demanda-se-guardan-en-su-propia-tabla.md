# ADR 0010 — Las investigaciones a demanda se guardan en su propia tabla

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-18
- **Fase:** 3
- **Decide:** Constructor, auditado por el Critico

## Contexto
Fase 3 (criterio C8): el panel de administracion debe permitir lanzar investigaciones sobre cualquier
pregunta ("¿por que tantos disturbios en Europa?", "¿que influencia tiene EE. UU. sobre Rusia e
Israel?"), que el worker procesa reuniendo historias, datos oficiales y cobertura mundial, y publica
como informe. Hoy no hay donde guardar la pregunta, su estado ni su informe.

## Necesidad
Imprescindible: la investigacion es asincrona (la crea el panel, la procesa el worker) y su informe se
sirve en `/investigacion/{id}`. Alternativa descartada: reutilizar `piece` (ADR 0008) con otro `kind`;
`piece` exige un tema (`topic_id` no nulo) y su CHECK de `kind`, y una investigacion no nace de un tema
sino de una pregunta, con un ciclo de vida (pendiente -> en curso -> publicada/error) que `piece` no
tiene.

## Escalabilidad
Volumen editorial: decenas al mes (las crea una persona desde el panel), < 1 000 al ano; informe JSON de
10-50 KB (historias, series, texto): < 50 MB/ano. Consultas: pendientes por `status` (indice) para el
worker y publicadas por `created_at` para la web. A 10x sigue siendo trivial.

## Coherencia
Convenciones de ADR 0002/0005/0008: clave entera, fechas UTC, `status` restringido por CHECK
(`pendiente`, `en-curso`, `publicada`, `error`), `report` JSON validado en codigo, `language` y
`country` como en `piece`/`topic`. Sin claves foraneas: el informe guarda ids de historias como datos
(una historia purgada no debe borrar una investigacion publicada).

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| `piece` con `kind='investigacion'` y `topic_id` nulo | Cambia la semantica y las restricciones de `piece` y mezcla dos ciclos de vida |
| Cola externa (Redis) para las pendientes | Un servicio mas para decenas de trabajos al mes; la tabla con `status` basta |

## Necesidades futuras
Investigaciones periodicas (re-ejecutar cada semana) con un campo `refresh_every` y su propio ADR;
traduccion de informes con `language`.

## Migracion y reversibilidad
Migracion `0004_investigaciones` en un paso: crea `investigation` con su indice. Serializada con el
bloqueo consultivo (ADR 0005). Reversible con `downgrade` a `0003` (se pierden las investigaciones).

## Decision
Se crea la tabla `investigation` en `truthnews/models.py` y la migracion
`alembic/versions/0004_investigaciones.py`.

## Verificacion
`tests/test_migrations.py` y tests del procesado de investigaciones y del panel.

## Alcance
- `truthnews/models.py`
- `alembic/versions/0004_investigaciones.py`
