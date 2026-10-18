# ADR 0002 — El esquema inicial guarda medios, feeds, articulos y rastreos en cuatro tablas

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-18
- **Fase:** 1
- **Decide:** Constructor, auditado por el Critico

## Contexto
Fase 1 de la carta (criterios C1, C2, C7): hace falta persistir el registro de medios, sus feeds, los
articulos ingeridos y el historial de cada rastreo. Hoy no existe esquema (repositorio vacio).

## Necesidad
Imprescindible: sin almacen no hay portada, ni segmentacion, ni agrupacion entre medios en la Fase 2.
Alternativa sin esquema considerada: guardar JSON en disco por articulo; no permite consultar por
categoria/pais/fecha con indices ni concurrencia web + worker, y Railway no garantiza disco persistente
sin volumen.

## Escalabilidad
Volumen estimado con el registro de Fase 1 (~120 medios, ~1,5 feeds por medio, ~30 entradas por feed
y rastreo horario con deduplicacion por URL): ~3 000 articulos nuevos/dia, ~1,1 M filas a 12 meses.
Con `content_text` medio de ~4 KB, ~4,5 GB/ano en `article`; se acota guardando el texto completo solo
90 dias (purga en Fase 5) y conservando titular, resumen y metadatos (~1 KB/fila, ~1,1 GB/ano).
Escrituras: picos de ~200 inserciones por rastreo, < 1 escritura/s de media. Lecturas: portada y
listados por `published_at` filtrados por `category`, `country`, `region` u `outlet_id`; indices
compuestos `(category, published_at)`, `(country, published_at)`, `(outlet_id, published_at)` y
`published_at`, mas unicidad en `url_hash`. A 10x (11 M filas) los listados siguen siendo un recorrido
de indice limitado por `LIMIT`; el coste de mantener 5 indices en escritura es despreciable a < 10
escrituras/s.

## Coherencia
Claves primarias enteras autoincrementales; `slug` unico en `outlet`; `url` unica en `feed`;
`url_hash` (sha256 de la URL canonica) unico en `article` para deduplicar. Fechas en UTC con zona.
Codigos de pais ISO 3166-1 alfa-2 y de region ISO 3166-2 (`ES-AN`). Claves foraneas `feed.outlet_id`,
`article.outlet_id` (obligatorias) y `article.feed_id` (nula si llega por otro canal) con `ON DELETE
CASCADE` desde `outlet`. Desnormalizacion deliberada: `article.country`, `region` y `language` se
copian del medio al ingerir para filtrar sin JOIN y para conservar el valor historico si el medio cambia.
`topics` y `crawl_run.stats` son JSON: listas abiertas sin consultas por elemento en esta fase.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Tabla `category` y `country` normalizadas | Son catalogos pequenos y estables que viven en YAML versionado; una FK no anade integridad que el registro no garantice ya al sincronizar |
| Tabla `article_topic` (N:M) desde ya | No hay consultas por tema hasta la Fase 2; se crea con su propio ADR cuando las haya |
| Elasticsearch/OpenSearch como almacen primario | Otro servicio sin necesidad medida; la busqueda de texto llegara con `tsvector` o el servicio `search` del holding |

## Necesidades futuras
Multi-pais e idioma ya estan en columnas (`country`, `language`). La Fase 2 anadira `story` (agrupacion),
`claim`, `verification` y `evidence` referenciando `article.id`; el diseño no lo impide. Borrado logico
de medios via `outlet.active`. La purga del texto a 90 dias se hace poniendo `content_text` a NULL,
sin cambio de esquema.

## Migracion y reversibilidad
Migracion Alembic `0001_initial` en un paso sobre base vacia, sin backfill. Reversible con
`alembic downgrade base` (borra las cuatro tablas; no hay datos que perder en el primer despliegue).

## Decision
Se crean `outlet`, `feed`, `article` y `crawl_run` con los indices descritos, definidos en
`truthnews/models.py` y creados por la migracion `0001_initial`.

## Verificacion
Test que aplica `alembic upgrade head` y `downgrade base` sobre SQLite limpio y compara el esquema con
los modelos; tests de ingesta que ejercen la deduplicacion por `url_hash`.

## Alcance
- `truthnews/models.py`
- `alembic/versions/0001_initial.py`
- `alembic/env.py`
- `alembic.ini`
- `alembic/script.py.mako`
