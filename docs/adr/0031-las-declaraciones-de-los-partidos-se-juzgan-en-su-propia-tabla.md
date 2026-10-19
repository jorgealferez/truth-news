# ADR 0031 — Las declaraciones de los partidos se juzgan con el mismo juez y se guardan en su propia tabla

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** 9 (quien miente, quien informa, quien dice la verdad)
- **Decide:** Constructor (carril Datos politicos), revisado con Verificaciones y Global

## Contexto

La direccion pide (2026-10-19) "quien dice la verdad" por partido y por politico, estilo PolitiFact y
simetrico para todos. #84 ya publica `/quien-dice-la-verdad` con las afirmaciones que las noticias
atribuyen a quien habla (`claim.speaker_entity_id`, ADR 0028). Falta lo que los partidos dicen en sus
canales oficiales verificados: `political_statement` (ADR 0024, carril Global), con 223 filas en
produccion tras el ciclo de las 01:46 UTC del 2026-10-19.

El juez ya existe y es publico desde #99 (carril Verificaciones): `truthnews.analysis.judge.judge_text`
devuelve candidatos y veredictos para un texto suelto, y su propia documentacion dice que quien guarde
el resultado de una declaracion "lo hace con su propio modelo". Hoy `claim.article_id` y
`claim.outlet_id` son NOT NULL: una afirmacion siempre viene de una noticia de un medio.

## Necesidad

Para publicar el historial de un partido hay que guardar cada afirmacion de sus declaraciones con su
veredicto y su evidencia, y poder rehacerlo cuando cambia el metodo. Sin guardar nada (juzgar en
lectura) cada visita a `/quien-dice-la-verdad` consultaria Eurostat, INE o Banco Mundial por cada
afirmacion: inaceptable en latencia y en cuota de esas APIs.

Se considero no tocar el esquema y reutilizar `claim` + `verification` + `evidence` haciendo opcionales
`article_id` y `outlet_id`. Auditoria del codigo en `main` (2026-10-19 03:10 UTC): **37 puntos en 18
ficheros** suponen que toda afirmacion tiene noticia y medio (`c.outlet.name`, `claim.article.url`,
`join(Claim.outlet_id == Outlet.id)`, ...), repartidos en seis carriles: verificacion y su grafico
(`verification.html`, `web/verdicts.py`), redes (`social/select.py`), lo que no cuadra
(`analysis/ranking.py`), fiabilidad por medio (`analysis/reliability.py`), redaccion con IA
(`ai/writer.py`), "En claro" (`analysis/plain.py`) y la historia. Una afirmacion sin medio romperia
varias de esas paginas con un error 500 o colaria declaraciones de partido en rankings de medios.

## Escalabilidad

- Entrada: 223 declaraciones en el primer ciclo completo; ~14 actores con canal verificado y unos
  pocos mensajes por actor y dia (estimacion, no medida: decenas al dia en regimen).
- Proporcion con afirmacion comprobable: en noticias, 42 de 2 782 articulos tocan el catalogo de
  indicadores (1,5 %, medido por Verificaciones). Con esa tasa: ~1 a 5 filas al dia, menos de 2 000 al
  ano; a 10x, 20 000 filas de ~1 KB (20 MB). Sin crecimiento sin cota.
- Lecturas: `/quien-dice-la-verdad` agrega por `speaker_entity_id` y veredicto (indice
  `ix_statement_check_speaker`); el re-juicio por cambio de metodo filtra por `method` (indice
  `ix_statement_check_method`). Escrituras: una por afirmacion nueva en cada ciclo del worker.
- Coste del paso: las reglas son expresiones regulares (milisegundos por declaracion); solo las
  afirmaciones encontradas consultan la fuente oficial, igual que en las noticias.

## Coherencia

- Tabla `statement_check`: una fila por afirmacion comprobable de una declaracion, con los mismos
  nombres y tipos que `claim` (`text`, `indicator`, `geo`, `value`, `unit`, `direction`, `period`) y
  que `verification` (`verdict` con el mismo CHECK `VERDICTS`, `confidence`, `explanation`, `method`,
  `checked_at`). La evidencia se guarda como JSON (`evidence`: lista de `{source, label, url, period,
  value}`), el mismo contenido que las filas de `evidence`, porque nunca se consulta por sus campos.
- `statement_id` -> `political_statement.id` ON DELETE CASCADE (sin declaracion no hay afirmacion);
  `speaker_entity_id` -> `entity.id` ON DELETE SET NULL (el partido en el registro de entidades; si no
  se encuentra, la fila se guarda igual con su actor).
- Unicidad `(statement_id, indicator, geo, value)`: la misma afirmacion no se guarda dos veces.
- Invariantes en codigo: el mismo juez y el mismo metodo (`METHOD_VERSION`) que las noticias; los
  duplicados entre canales (mismo actor y mismo texto normalizado en 6 h, aviso de Global) se juzgan
  una vez; nunca se deduce la afiliacion de una persona.

## Alternativas consideradas

| Alternativa | Por que no |
|---|---|
| `claim.statement_id` opcional y `article_id`/`outlet_id` nulos | 37 puntos en 18 ficheros de seis carriles suponen noticia y medio: errores 500 y declaraciones de partido colandose en rankings de medios. Coste y riesgo muy superiores a una tabla de ~2 000 filas al ano. |
| Juzgar en lectura, sin guardar | Una consulta a Eurostat/INE/Banco Mundial por afirmacion y visita; sin historial estable ni re-juicio con correccion. |
| Guardar el veredicto en `political_statement` (JSON) | Una declaracion puede tener varias afirmaciones; mezcla el carril Global con el juicio y obliga a reescribir su tabla en cada re-juicio. |

## Necesidades futuras

- Declaraciones de politicos individuales (blogs, redes): misma tabla si llegan como `political_statement`
  con su actor; si llegan por otra via, una columna de origen se anade con su ADR.
- Extraccion con IA (`ai.claims.propose`): la tabla ya guarda `extractor` (`reglas` | `ia`) como `claim`.
- Migracion al holding (ADR 0025): tabla autocontenida con claves foraneas a dos tablas del mismo
  dominio (D3 contraste); se mueve con ese dominio sin tocar `claim`.

## Migracion y reversibilidad

Un paso: `CREATE TABLE statement_check` con sus indices, sin tocar tablas existentes ni bloquearlas; no
hay relleno (el worker la llena desde el ciclo siguiente). Compatible con el codigo en marcha durante el
despliegue (nadie la lee hasta que se despliega este codigo). Revertir: `DROP TABLE statement_check`;
se pierden los juicios de declaraciones, que el worker rehace en el siguiente ciclo tras volver a subir.

## Decision

Las afirmaciones comprobables de las declaraciones de los partidos se juzgan con `judge_text` (mismo
juez y metodo que las noticias) y se guardan en una tabla propia `statement_check`, sin tocar `claim`;
`/quien-dice-la-verdad` suma ambos historiales por partido.

## Verificacion

Migracion aplicada y revertida en SQLite y PostgreSQL limpios (`alembic upgrade head` y
`downgrade -1`); tests de `truthnews/analysis/statement_checks.py` (juicio, duplicados entre canales,
re-juicio por metodo, atribucion al partido) y de la pagina con historial mixto.

## Alcance

- `truthnews/models.py`
- `alembic/versions/0016_declaraciones_juzgadas.py`
