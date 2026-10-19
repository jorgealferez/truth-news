# ADR 0022 — La cobertura de otros paises se enlaza a la historia sin entrar en ella

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** g3 (Cobertura global)
- **Decide:** Constructor, auditado por el Critico

## Contexto
Peticion del usuario 2026-10-19 (item "Cobertura global en cualquier idioma" del ledger, C10): "la misma
historia contada en distintos paises lado a lado". Desde #28 el registro tiene medios de 18 paises
mas; desde #32 sus titulares se traducen al espanol (`article_translation`, ADR 0017). Hoy una historia
es un grupo de `article` con `article.story_id` (ADR 0004/0005), formado por TF-IDF sobre el titular en
su idioma original: un titular de Der Spiegel nunca cae en la historia espanola del mismo hecho.

## Necesidad
Meter esos articulos en la historia (`article.story_id`) no sirve: `compare()` se llama desde 7 sitios
(historia, hilos, piezas, redes, imagen social, puntuacion, evaluacion) y juzgaria un articulo en aleman
con palabras en espanol: "no menciona X" seria una afirmacion falsa sobre un medio. Calcularlo al servir
la pagina obliga a vectorizar ~1.200 titulares extranjeros de 72 h en cada visita (medido: 519 solo en
espanol en una pasada de feeds), frente a un p95 actual de 8,2 ms en la historia (`fase_2.json`). Hace
falta guardar el enlace precalculado por el worker.

## Escalabilidad
Se recalculan en cada ciclo las <= 80 historias activas (48 h, >= 2 medios) del pais de portada, con
<= 12 enlaces por historia y <= 3 por pais: <= 960 filas vivas, reemplazadas en cada ciclo (DELETE por
`story_id IN` + INSERT). Historias que dejan de estar activas conservan sus ultimos enlaces: a 12 meses,
~200 historias/dia x 12 = <= 0,9 M filas de ~40 bytes (< 80 MB con indices). Lectura: una consulta por
pagina de historia por `story_id` (indice de la clave unica, prefijo `story_id`). Coste del calculo
medido: 15 historias contra 519 candidatos en < 1 s en Python.

## Coherencia
Tabla `story_abroad` con el estilo de `article_revision`/`article_translation`: `id` Integer, `story_id`
FK a `story.id` y `article_id` FK a `article.id`, ambas `ON DELETE CASCADE` con nombre explicito,
`similarity` Float (coseno, para ordenar y auditar), `linked_at` DateTime con zona. Unicidad
`(story_id, article_id)`. Invariantes en codigo: el articulo es de otro pais que la historia, se compara
el titular en el idioma de portada (original o traduccion IA) y el umbral es 0,40.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Asignar el articulo extranjero a la historia (`article.story_id`) | El comparador lo juzgaria en otro idioma (omisiones falsas) en 7 llamadas |
| Guardar los ids en `story.contrast` (JSON) | Sin FK ni borrado en cascada; mezcla datos del comparador con otro carril |
| Calcular en cada visita | Vectorizar ~1.200 titulares por peticion contra un p95 de 8,2 ms |

## Necesidades futuras
Paginas por pais ("como lo cuenta el mundo") leen la misma tabla al reves (`article_id` -> historias).
Un indice por `article_id` se anade si esa consulta aparece. Si la portada cambia de pais, `link()`
recibe el pais por parametro y no cambia el esquema.

## Migracion y reversibilidad
Migracion 0013: un `CREATE TABLE` con su clave unica, sin tocar tablas existentes ni bloquearlas y sin
relleno (el worker la llena en el siguiente ciclo). El codigo anterior no la lee. Reversion:
`DROP TABLE story_abroad`; se pierden solo los enlaces, que se recalculan en un ciclo.

## Decision
La cobertura de medios de otros paises se enlaza a cada historia en `story_abroad`, precalculada por el
worker con umbral 0,40 sobre el titular en el idioma de portada, y se muestra en un bloque aparte de la
historia agrupado por pais, sin entrar en el comparador.

## Verificacion
Medida con feeds en vivo el 2026-10-19 (`tools/eval_abroad.py`): 663 articulos espanoles, 15 historias de
>= 3 medios, 519 articulos en espanol de otros paises; etiquetado a mano, precision 0,83 con umbral 0,30
(30 enlaces), 0,87 con 0,35 (23) y 0,94 con 0,40 (16 enlaces en 5 historias). Migracion aplicada y
revertida en SQLite (`tests/test_migrations.py`); `tests/test_abroad.py` ejerce el emparejamiento, los
topes, la traduccion y el reemplazo por ciclo.

## Alcance
- `alembic/versions/00*_cobertura_exterior.py`
- `truthnews/models.py`
