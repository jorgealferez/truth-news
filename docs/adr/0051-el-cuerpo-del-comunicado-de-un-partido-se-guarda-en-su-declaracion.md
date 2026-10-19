# ADR 0051 — El cuerpo del comunicado de un partido se guarda en su declaracion

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** 9 (quien dice la verdad: declaraciones de los partidos juzgadas)
- **Decide:** Constructor (carril Datos politicos), pedido por la direccion; auditado por el Critico

## Contexto
Las declaraciones de los partidos (`political_statement`, ADR 0024) se juzgan con el juez de siempre por
reglas (ADR 0031) y, desde #155, tambien con la IA. La primera medida en produccion (run 108, 10:37 UTC
del 2026-10-19) dio 0 frases candidatas en las 176 declaraciones de la ventana de 30 dias: el canal `web`
de los partidos es un RSS que solo trae el titular (`text`, hasta 600 caracteres) y la entradilla
(`summary`, recortada a 1 200 caracteres por `parse_rss`). Las cifras de un comunicado estan en el cuerpo,
que hoy no se lee. La direccion pide descargar el texto completo una sola vez, con robots.txt y
parandose ante un 403, con un tope de 20 por ciclo y 3 por dominio, y medir cuantas frases candidatas
salen.

## Necesidad
Hace falta guardar el cuerpo. Si se descarga y se juzga en el mismo paso sin guardarlo: el paso por reglas
recorre cada ciclo toda la ventana de 30 dias (`statement_checks.run`) y tendria que descargar de nuevo
cada comunicado sin afirmaciones, 48 veces al dia, contra la regla de "una sola vez". Ademas, el re-juicio
cuando cambia el metodo trabaja sobre lo guardado. Tambien hay que anotar que el intento se hizo y como
acabo (ok, 403, robots, vacio): sin eso se reintentaria un dominio bloqueado en cada ciclo, que es
justamente insistir ante un bloqueo. No vale reutilizar `summary`: lo usan tal cual las promesas de
Elecciones (`elections/programs.py`) y el filtro regional de `elections/views.py`, y cambiaria su
significado (entradilla del RSS) para el resto de canales. `CrawlRun.stats` (JSON) no sirve para guardar
textos de miles de caracteres por declaracion ni se consulta por declaracion.

## Escalabilidad
Hoy, 176 declaraciones en 30 dias en 14 canales (unas 6 al dia). Solo el canal `web` tiene pagina propia
que descargar (7 de los 12 partidos del registro `registry/political/es.yaml`). Con 20 por ciclo, toda la
cola de 30 dias se vacia en 1-3 ciclos y despues entran unas pocas al dia. El cuerpo se recorta a
20 000 caracteres: unos 5 KB de media por comunicado, un maximo de unos 20 KB. A 12 meses son unas 2 200
filas con cuerpo, entre 11 y 44 MB. A 10x (60 declaraciones al dia, 22 000 filas al ano), entre 110 y
440 MB. Text en Postgres se guarda TOAST fuera de linea y no pesa en los recorridos de la tabla.
La consulta nueva (canal `web`, sin intento, de la ventana de 30 dias, a lo sumo 20 filas) recorre como
mucho las filas de la ventana, que ya se recorren enteras cada ciclo en `statement_checks.run`. No necesita
indice nuevo (existe `ix_political_statement_country_published`). Escrituras: como mucho 20
actualizaciones por ciclo.

## Coherencia
Tres columnas anulables en `political_statement`, con los nombres y tipos del esquema:
- `body` (`Text`): texto principal extraido con `crawler/extract.extract_text`, el mismo trafilatura que
  `article.content_text`; solo para analisis interno, nunca se republica (lo que se muestra sigue siendo
  la cita con enlace, ADR 0024).
- `body_status` (`String(16)`): `ok`, `vacio`, `robots`, `http <codigo>` o `error`, el mismo vocabulario
  que el estado de un canal en `crawler/political.fetch_channel`. NULL = aun no se intento. Sin CHECK:
  el codigo HTTP es abierto, y el vocabulario lo fija `crawler/political`, igual que `failed` en las stats
  del paso.
- `body_fetched_at` (`DateTime(timezone=True)`): cuando se hizo el intento. Con el, un dominio que dio
  401/403 o que prohibe robots.txt no se vuelve a pedir en 24 h.
Invariantes en el codigo: solo el canal `web` recibe intento; `body` solo se rellena con `body_status = ok`.
Sin desnormalizar: el cuerpo es de la declaracion, 1 a 1.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Tabla aparte `statement_body` (statement_id, body, status, fetched_at) | Relacion 1 a 1 sin ciclo de vida propio: una join mas en los dos pasos de juicio y una FK que mantener, sin ganar nada. Con TOAST, el texto ya vive fuera de la fila. |
| Descargar y juzgar en el mismo paso, sin guardar | Descarga repetida en cada ciclo (48 al dia por comunicado) y el re-juicio sin texto. |
| Guardar el cuerpo en `summary` | Cambia el significado de una columna que leen Elecciones y el filtro regional. |
| Guardar solo `body_status`, sin fecha | Un dominio bloqueado quedaria fuera para siempre o se reintentaria en cada ciclo: hace falta la fecha para la regla de 24 h. |

## Necesidades futuras
Si mas adelante otros canales enlazan a la web (un post de Telegram con el enlace al comunicado), la misma
columna sirve: basta con que el paso de descarga acepte el enlace. Si hiciera falta el idioma del cuerpo
(euskera, gallego, catalan), iria en otra columna sin tocar estas. El borrado de una declaracion se lleva
su cuerpo: no queda copia suelta.

## Migracion y reversibilidad
Un paso: `ALTER TABLE ... ADD COLUMN` de tres columnas anulables, sin valor por defecto, sin backfill y sin
reescribir la tabla en Postgres (176 filas en 30 dias, unos milisegundos). El codigo que corre durante el
despliegue no lee las columnas: es compatible en los dos sentidos. Revertir (`downgrade`) quita las tres
columnas y se pierden los cuerpos descargados; se pueden volver a descargar, con el mismo tope.

## Decision
Se anaden `body`, `body_status` y `body_fetched_at`, anulables, a `political_statement`. Se rellenan solo
en el canal `web`: a lo sumo 20 declaraciones por ciclo y 3 por dominio, respetando robots.txt, y un
dominio que da 401/403 o que robots.txt prohibe se para y no se vuelve a pedir en 24 h. Los dos pasos de
juicio usan el cuerpo cuando existe.

## Verificacion
Migracion aplicada y revertida en SQLite limpio en `tests/test_migrations.py` (cabeza unica de Alembic).
Tests de la descarga con respx: topes por ciclo y por dominio, robots.txt, un 403 que para el dominio
24 h, cuerpo vacio. Tests del juicio con el cuerpo, tambien con la IA, para una declaracion que ya habia
pasado el cursor. Medida en produccion de frases candidatas antes y despues, en el ledger.

## Alcance
- `truthnews/models.py`
- `alembic/versions/0022_cuerpo_de_las_declaraciones.py`
