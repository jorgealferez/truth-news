# ADR 0015 — Los cambios de titular y extracto se guardan como revisiones citadas

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** item del ledger "Ficha de medio y de noticia con datos citados y rastreo de modificaciones"
- **Decide:** Constructor, auditado por el Critico

## Contexto
Peticion del usuario (2026-10-19, cita literal en `PENDIENTES.truth-news.md`): mas datos en la ficha del
medio y de la noticia, por fragmentos y sin reproducir el texto completo (derecho de cita), con cita a la
fuente y la prueba necesaria para justificar cada dato si el medio lo cambia; y rastrear las
modificaciones que hagan los medios.

Hoy `article` guarda el titular y el extracto **de la primera captura** (`title`, `summary`), la fecha de
captura (`fetched_at`) y la huella del texto completo cuando se descarga (`content_hash`). El rastreador
deduplica por `url_hash` (`truthnews/crawler/ingest.py`, paso 3): una URL ya vista se descarta sin mirar
si el medio ha cambiado su titular o su extracto. Si un medio rectifica una cifra o suaviza un titular,
hoy no queda rastro y lo que publicamos no se puede justificar frente a la version nueva.

## Necesidad
Hace falta guardar la version anterior: el feed solo trae la actual, y sin una copia propia del antes no
hay cambio que mostrar ni dato que justificar. Alternativas sin tocar el esquema consideradas:
(a) sobrescribir `article.title`/`summary` con la version nueva: pierde justo la prueba que se pide;
(b) una lista JSON de versiones dentro de `article` (no hay columna JSON libre en `article`, habria que
anadirla igualmente) que obliga a reescribir la fila entera en cada cambio y no permite consultar "cambios
de este medio" sin leer todas sus noticias; (c) enlazar solo a una copia de archivo externa (Wayback): se
anade como enlace, pero no depende de nosotros que exista ni detecta el cambio. Ninguna basta.

## Escalabilidad
Entrada por ciclo, medida en produccion el 2026-10-18 (`docs/benchmarks/fase_1a.json`): 126 feeds
correctos, hasta 30 entradas por feed, es decir ~3 800 entradas por ciclo, de las que la gran mayoria ya
existe. Comparar esas entradas con lo guardado exige leer `id, url_hash, title, summary` de las ya
existentes: una consulta por lotes de 500 por `url_hash` (indice unico ya existente), ~8 consultas por
ciclo, sin escrituras salvo cuando hay cambio.

Revisiones esperadas (estimacion, NO medida aun: es el primer subitem tras el despliegue): si un 2-5 % de
las ~2 900 noticias diarias cambia titular o extracto mientras sigue en el feed, 60-150 filas/dia, 20 000-
55 000/ano. Cada fila guarda antes y despues de un campo recortados a 600 caracteres (el mismo limite que
ya se publica del extracto): <= 1,3 KB, 25-70 MB/ano; a 10x, < 1 GB/ano. Lecturas: la pagina de una
noticia (por `article_id`) y la de un medio (por `outlet_id` y fecha); dos indices compuestos
`(article_id, detected_at)` y `(outlet_id, detected_at)`, cuyo coste en escritura es despreciable con
este volumen.

## Coherencia
Tabla `article_revision` con el estilo del esquema: `id` entero, `article_id` FK a `article` con
`ON DELETE CASCADE` (una revision no existe sin su noticia), `outlet_id` FK a `outlet` con `CASCADE`
(desnormalizado a proposito para listar los cambios de un medio sin unir con `article`; es inmutable y se
copia de la noticia), `crawl_run_id` FK opcional a `crawl_run` con `SET NULL`, `field` con `CHECK` en
`('title', 'summary')`, `before`/`after` `Text` no nulos, `before_hash`/`after_hash` `String(64)` (sha256,
como `url_hash` y `content_hash`) y `detected_at` con zona horaria. La noticia pasa a mostrar su version
**vigente** (se actualiza `article.title`/`summary`) y el historial guarda todas las anteriores; la
invariante "toda version publicada alguna vez esta en `article` o en `article_revision`" vive en el
codigo del rastreador y la cubre un test. No se guarda el texto completo de nadie: solo titular y extracto
del feed, recortados, que es lo que ya se publica como cita (ADR 0003).

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Una fila de version completa por noticia (`article_version` con titular, extracto y texto) | Duplica texto completo ajeno (derecho de cita, ADR 0003) y multiplica el tamano sin aportar al usuario mas que el cambio |
| Columna JSON `history` en `article` | Reescribe la fila caliente en cada cambio; sin indice para "cambios de un medio" |
| Solo enlazar a Wayback | No detecta el cambio ni garantiza que exista la copia |

## Necesidades futuras
Rastrear cambios en el texto completo o en las cifras de una noticia ya descargada (otro valor de `field`,
p. ej. `content`, guardando solo la huella y los fragmentos con cifras): cabe ampliando el `CHECK` en una
migracion pequena. Un ranking de "quien rectifica mas" sale de contar por `outlet_id` sin cambios de
esquema. Multi-pais e idioma no afectan: la tabla no tiene texto de interfaz.

## Migracion y reversibilidad
Un paso, expandir: `CREATE TABLE` e indices nuevos, sin tocar tablas existentes ni bloquearlas; sin
relleno (no hay historial anterior que recuperar). El codigo que corre durante el despliegue no lee la
tabla, y el nuevo funciona con la tabla vacia. Se revierte con `downgrade` (`DROP TABLE`): se pierden las
revisiones detectadas desde el despliegue; las noticias conservan su version vigente.

## Decision
Se crea `article_revision` y el rastreador, en cada ciclo, compara titular y extracto de las entradas ya
conocidas con lo guardado: si cambian, guarda el antes y el despues (recortados) con su huella y fecha, y
actualiza la noticia a la version vigente.

## Verificacion
Migracion aplicada y revertida en SQLite y en el test de migraciones; tests del rastreador con dos ciclos
sobre un feed que cambia el titular y el extracto; tests de las paginas de noticia y de medio; numero real
de revisiones al dia medido en produccion tras el despliegue (subitem del ledger).

## Alcance
- `truthnews/models.py`
- `alembic/versions/0007_revisiones.py`
