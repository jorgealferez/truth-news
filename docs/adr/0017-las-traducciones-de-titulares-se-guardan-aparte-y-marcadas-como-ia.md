# ADR 0017 — Las traducciones de titulares se guardan aparte, una fila por idioma, marcadas como IA

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** g2 (Cobertura global)
- **Decide:** Constructor, auditado por el Critico

## Contexto
Peticion del usuario 2026-10-19 (item "Cobertura global en cualquier idioma" del ledger, criterio C10):
"cualquier idioma, cualquier medio global", con titulares traducidos con IA y marcados como traduccion.
Desde #28 el registro tiene medios en 7 lenguas (ar, de, en, es, fr, it, pt): 2.699 entradas por pasada
en 18 paises nuevos (`docs/benchmarks/fase_g1.json`). Hoy `article` guarda `title` (String 600) y
`language` (String 8) del original y nada mas: un lector en espanol no entiende el titular de Hespress
en arabe ni el de Der Spiegel en aleman, y la comparacion entre medios pierde la mitad de su valor.

## Necesidad
Hay que guardar la traduccion: generarla en cada peticion costaria una llamada a la API por pagina vista
(latencia de segundos y coste sin cota). Alternativas sin esquema nuevo: (a) sobrescribir `title` con la
traduccion, que destruye el original citado, rompe la ficha de captura (ADR 0015, huellas sha256 del
titular) y haria creer que el medio dijo literalmente eso; (b) meterla en `article.topics` (JSON), que
mezcla dos cosas sin relacion y no deja saber que modelo tradujo ni cuando. Ninguna basta.

## Escalabilidad
Solo se traducen los articulos de historias con actividad en las ultimas 48 h cuyo idioma no es el de
destino, con tope por ciclo `AI_MAX_TRANSLATIONS_PER_CYCLE` (120 titulares, lotes de 40). Destinos: los
idiomas de la interfaz (es, en). Cota: 120 filas por ciclo x 48 ciclos/dia = 5.760 filas/dia como
maximo; en la practica menos, porque cada titular se traduce una sola vez. A 12 meses: <= 2,1 M filas de
~250 bytes (titular <= 600 caracteres), ~0,5 GB con indice; a 10x de medios el tope por ciclo no cambia
el crecimiento. Lectura: una consulta por historia con `article_id IN (...)` y `lang = ?`, servida por
la clave unica `(article_id, lang)`. Escritura: un INSERT por titular, sin actualizaciones.

## Coherencia
Tabla `article_translation`, como `article_revision` (ADR 0015): `id` Integer, `article_id` FK a
`article.id` con `ON DELETE CASCADE` y nombre explicito, `lang` String(8) como `article.language`,
`title` String(600) como `article.title`, `model` String(80) (que modelo tradujo, para declararlo),
`created_at` DateTime con zona. Unicidad `(article_id, lang)`: una traduccion por idioma. Invariante en
codigo: no se guarda traduccion al idioma del propio articulo ni un titular vacio, y el original nunca se
toca. Normalizada: el texto traducido no se duplica en `article`.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Columnas `title_es` y `title_en` en `article` | Una migracion por cada idioma nuevo de la interfaz; filas anchas en la tabla mas leida |
| Columna JSON `translations` en `article` | Sin unicidad ni FK por idioma, sin fecha ni modelo por traduccion y reescritura de la fila mas caliente |
| Servicio externo de traduccion sin guardar | Coste y latencia por pagina vista; el texto mostrado no seria reproducible ni auditable |

## Necesidades futuras
Un idioma de interfaz nuevo (pt, fr, ar) es una fila mas por articulo sin migracion. Si se traducen
tambien los extractos, se anade una columna `summary` nullable (expandir, sin bloqueo). La comparacion
entre paises de la misma historia leera estas traducciones para alinear titulares. Una correccion
humana de una traduccion cabria con una columna `reviewed_by` sin cambiar la clave.

## Migracion y reversibilidad
Migracion 0009: un `CREATE TABLE` con su indice unico, sin tocar tablas existentes ni bloquearlas; no hay
relleno (las traducciones las crea el worker en sus ciclos). El codigo desplegado antes de la migracion
no lee la tabla, y el nuevo tolera que este vacia. Reversion: `DROP TABLE article_translation`; se
pierden solo las traducciones, que se regeneran en los ciclos siguientes.

## Decision
Las traducciones de titulares se guardan en `article_translation`, una fila por articulo e idioma con el
modelo que la hizo, y la web las muestra debajo del titular original con la marca "traduccion
automatica (IA)", nunca en su lugar.

## Verificacion
Migracion aplicada y revertida en SQLite limpio (`tests/test_migrations.py`); `tests/test_translate.py`
ejerce la seleccion, el tope por ciclo, los ids inventados por el modelo y la unicidad; la vista de la
historia muestra la traduccion marcada (`tests/test_web.py`).

## Alcance
- `alembic/versions/000*_traducciones.py`
- `truthnews/models.py`
