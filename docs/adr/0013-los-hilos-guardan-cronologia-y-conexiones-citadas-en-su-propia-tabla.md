# ADR 0013 — Los hilos guardan su cronologia y sus conexiones citadas en su propia tabla

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** 10
- **Decide:** Constructor, auditado por el Critico

## Contexto
Peticion del usuario (2026-10-19): ir mas alla de la noticia; cruzar lo que ocurre hoy con lo que se dijo
y paso antes ("que se decia, que paso, que hubo por el camino y como surgio despues"), quien dijo que, y
las consecuencias de actos que parecen no tener relacion (ejemplo del usuario: Ceuta, la presion de
Marruecos, EEUU/OTAN y Espana), con IA y sin dar nada por sentado. Hoy el esquema tiene `story` (la misma
noticia en varios medios, ventana de dias), `topic` (historias del momento agrupadas por la IA) e
`investigation` (preguntas a demanda). Ninguno guarda una cronologia de meses o anos con fuentes
externas, ni conexiones entre hechos con su evidencia.

## Necesidad
Imprescindible guardar el resultado: construir un hilo cuesta dos llamadas a la IA (~1-2 minutos y
coste por tokens) y hasta 6 consultas a GDELT limitadas a una cada 5 s; no puede hacerse en cada
peticion web. Alternativas sin tocar el esquema consideradas: (a) guardarlo en `investigation.report`:
mezcla un informe a demanda con un objeto que se refresca solo y se ancla a una historia, y obligaria a
filtrar por el contenido del JSON para encontrar el hilo de una historia; (b) `piece` con otro `kind`:
exige `topic_id` y no tiene estado de refresco. Ninguna basta.

## Escalabilidad
Presupuesto de IA por ciclo: 2 hilos nuevos o refrescados cada 30 min, como maximo 96 al dia; en la
practica las historias de cabecera cambian despacio: ~20-40 hilos/dia, ~10 000/ano. Tamano por hilo:
cronologia (<= 25 hechos), conexiones (<= 8), fuentes (<= 60 entradas de corpus con titular y URL),
analisis y uso de tokens: 20-60 KB de JSON. A 10 000/ano: 200-600 MB/ano en el peor caso; a 10x, 6 GB,
asumible en Postgres y mitigable purgando el corpus de hilos de mas de un ano (necesidad futura).
Consultas: el hilo de una historia (`anchor_story_id`, indice), los publicados recientes para portada
(`status, updated_at`, indice) y uno por id. Escrituras: <= 2 por ciclo.

## Coherencia
Convenciones de ADR 0008/0010: clave entera, fechas UTC con zona, `status` restringido por CHECK
(`publicado`, `revision`, `error`), `country` de 2 letras, JSON validado en codigo con esquema de salida
de la IA. `anchor_story_id` es FK a `story` con `ON DELETE SET NULL` (un hilo publicado sobrevive a la
purga de su historia), como `story.topic_id`. Los demas enlaces (historias del corpus, fuentes
externas) se guardan como datos en `sources`, no como claves: son evidencia citada, no relaciones. La
invariante "cada hecho y cada conexion publicados citan al menos una fuente del corpus" vive en el codigo
(control de fundamento, ADR 0007) y en tests.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Tablas normalizadas `thread_event` y `thread_link` | Se escriben y leen siempre juntas y se regeneran enteras en cada refresco; normalizar multiplica escrituras sin consultas que lo necesiten |
| Un grafo (Neo4j) de hechos y conexiones | Otro almacen que operar para decenas de escrituras al dia; el JSON basta mientras no se consulte el grafo entre hilos |
| Reutilizar `investigation` | Distinto ciclo de vida (a demanda frente a refresco automatico) y sin ancla a historia |

## Necesidades futuras
Conectar hilos entre si (que un hecho de un hilo aparezca en otro) pediria una tabla de hechos
compartidos con identidad propia: se hara con su ADR cuando haya hilos suficientes para medir cuantos
hechos se repiten. Traduccion: `language`. Purga del corpus de hilos antiguos.

## Migracion y reversibilidad
Migracion `0006_hilos` en un paso: crea `thread` con dos indices y su FK. Aditiva, sin relleno: los
hilos los crea el worker en los ciclos siguientes. Serializada con el bloqueo consultivo (ADR 0005).
Codigo anterior la ignora. Reversible con `downgrade` a `0005` (se pierden los hilos; se regeneran).

## Decision
Se crea la tabla `thread` en `truthnews/models.py` y la migracion `alembic/versions/0006_hilos.py`.

## Verificacion
`tests/test_migrations.py` (ida y vuelta), tests del constructor de hilos con IA y fuentes simuladas
(control de fundamento) y de las paginas; medidas en `docs/benchmarks/fase_10.json`.

## Alcance
- `truthnews/models.py`
- `alembic/versions/0006_hilos.py`
