# ADR 0012 — La historia guarda su puntuacion de contraste y su relanzamiento

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-18
- **Fase:** 7
- **Decide:** Constructor, auditado por el Critico

## Contexto
Peticion del usuario (2026-10-18): "prioriza lo que tenga datos que difieran antes que noticias donde no
tengas nada que marcar; si son antiguas incluso puedes relanzarlas si hay nuevos datos relevantes y es
trending". Hoy `queries.top_stories` ordena por `n_outlets` y `last_seen` (indice
`ix_story_country_last_seen`): una historia contada por 12 medios sin ninguna diferencia va por delante
de una contada por 4 con dos cifras en disputa y un dato falso. Y una historia sale de la portada a las
48 h aunque vuelva a ser noticia con datos nuevos, porque `assign_stories` solo reagrupa los articulos
de 72 h y un articulo nuevo sobre un asunto antiguo crea una historia nueva.

## Necesidad
Ordenar por contraste exige conocer, para cada historia candidata, sus cifras en disputa, omisiones,
lenguaje cargado y veredictos. Calcularlo en lectura significa ejecutar `compare()` sobre todos los
articulos de cada una de las ~200 historias multimedio del dia en cada peticion de portada: medido en
local, `compare()` de una historia de 8 articulos de 500 palabras tarda 21 ms de mediana (31 ms p95), es
decir ~4 s por portada, frente al presupuesto `portada_p95_ms_10k <= 300` (hoy 12,9 ms). Hay que calcularlo una vez por
ciclo en el worker y guardarlo. El relanzamiento tambien necesita estado persistente: cuando ocurrio,
para que la historia vuelva a la portada aunque `last_seen` del grupo original sea antiguo.

## Escalabilidad
Produccion (2026-10-18): ~3 000 articulos/dia, ~200 historias multimedio/dia; proyeccion a 12 meses
~1,1 M de articulos y ~600 000 historias. Columnas nuevas por historia: dos `FLOAT` (16 B), un
`TIMESTAMP` (8 B) y un `JSON` resumen de ~150 B: ~105 MB/ano en el peor caso (menos: solo las
multimedio llevan resumen). Escrituras: una actualizacion por historia tocada por ciclo (~400 cada 30
min). Lecturas: la portada filtra por pais y por ventana (`last_seen` o `relaunched_at` recientes) y ordena
por `priority, id`. Indices nuevos: `ix_story_country_priority (country, priority)`, que SQLite recorre en
orden y corta en el limite (medido: 0,53 ms de mediana con 2 000 historias, frente a 0,81 ms de la
consulta anterior), y `ix_story_country_relaunched (country, relaunched_at)`, para que en Postgres las
dos ramas del `OR` se resuelvan con indices (BitmapOr sobre este y `ix_story_country_last_seen`) y el
orden se haga sobre las ~600 historias de la ventana, no sobre la tabla. Calculo por ciclo: ~600 historias multimedio en la ventana x 21 ms = ~13 s; a
10x (30 000 articulos/dia) ~6 000 x 21 ms = ~126 s, dentro de `analisis_duracion_s <= 600`.

## Coherencia
Mismas convenciones que `story` (ADR 0005): nombres en ingles, fechas UTC con zona. `contrast_score` y
`priority` son `FLOAT NOT NULL DEFAULT 0` (una historia sin calcular no tiene contraste); `contrast`
es `JSON` nulo hasta el primer calculo (nulo = pendiente, lo que permite el relleno incremental);
`relaunched_at` es nulo salvo relanzamiento. Desnormalizacion deliberada: la puntuacion se deriva de
`article`, `claim` y `verification`, y se recalcula cada vez que la historia o sus veredictos cambian;
la fuente de verdad sigue siendo esa. La formula vive en codigo (`truthnews/analysis/score.py`), no en
la base.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Calcular el contraste en lectura | ~4 s por portada (21 ms por historia, medido), fuera de presupuesto |
| Tabla aparte `story_score` 1:1 | Un JOIN mas en la consulta mas caliente para cuatro columnas que siempre se leen con la historia |
| Vista materializada en Postgres | No existe en SQLite (tests y desarrollo) y su refresco es global, no incremental |
| Relanzar duplicando la historia | Partiria el historial de veredictos y enlaces de la historia original |

## Necesidades futuras
Pesos por pais o seccion: caben en la formula sin tocar el esquema. Historico de puntuaciones (como
evoluciona un contraste) necesitaria su propia tabla y ADR; el resumen JSON actual guarda solo el
ultimo estado. Imagenes sociales de la Fase 4 leeran el resumen `contrast` para el titular.

## Migracion y reversibilidad
Migracion `0005_contraste` en un paso, aditiva: dos columnas con valor por defecto y dos nulas, mas dos
indices; en Postgres `ADD COLUMN ... DEFAULT` constante no reescribe la tabla. Serializada con el bloqueo
consultivo (ADR 0005). Relleno incremental: el worker puntua las historias multimedio de los ultimos 7
dias con `contrast` nulo (~1 400 historias x 21 ms = ~30 s, una sola vez). El codigo anterior ignora las columnas nuevas, asi
que web y worker pueden desplegarse en cualquier orden. Reversible con `downgrade` a `0004`: se pierden
las puntuaciones (se recalculan) y las marcas de relanzamiento.

## Decision
Se anaden a `story` las columnas `contrast_score`, `priority`, `contrast` y `relaunched_at` y los indices
`ix_story_country_priority` e `ix_story_country_relaunched`, en `truthnews/models.py` y `alembic/versions/0005_contraste.py`.

## Verificacion
`tests/test_migrations.py` (ida y vuelta), tests de puntuacion, orden de portada y relanzamiento, y
`portada_p95_ms_10k` publicado en `docs/benchmarks/fase_7.json`.

## Alcance
- `truthnews/models.py`
- `alembic/versions/0005_contraste.py`
