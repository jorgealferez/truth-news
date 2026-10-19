# ADR 0024 — Las declaraciones de los partidos se guardan aparte de los medios, con su canal y su cita

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** g4 (Fuentes politicas)
- **Decide:** Constructor, auditado por el Critico

## Contexto
Peticion del usuario 2026-10-19 (item "Fuentes politicas" del ledger): webs oficiales de todos los
partidos con representacion, por igual, y redes con acceso publico oficial (Bluesky, Mastodon, YouTube
RSS, canales publicos de Telegram); en la noticia, un bloque "Que dicen los partidos" simetrico y sin
calificativos. Hoy solo existen medios (`outlet`) y sus articulos (`article`), con `outlet.kind` en
press/tv/radio/agency/factcheck; un partido no es un medio.

## Necesidad
Guardar lo que publica cada partido como si fuera un medio (`outlet.kind = 'party'`, sus textos en
`article`) lo meteria en el agrupador de historias, en el comparador (7 llamadas a `compare()`), en el
ranking y la ficha de `/medios` y en la fiabilidad por medio: un partido apareceria "omitiendo" cifras
o "contando" una historia como un periodico. Hace falta una tabla propia. Calcular las declaraciones
en cada visita (pedir los canales al vuelo) no es posible: son 12 partidos y varios canales con ritmo
por dominio de 1 s.

## Escalabilidad
Medido el 2026-10-19 en vivo: RSS web 10-30 entradas por partido, Mastodon 20, Bluesky (API publica)
y Telegram (vista publica `t.me/s/`) ~20 mensajes visibles. Con 12 partidos y <= 3 canales, un ciclo
ve <= 700 entradas, casi todas repetidas; las nuevas son del orden de 10-30 por partido y dia: <= 400
filas/dia, ~150.000 al ano, ~100 MB con indices (texto <= 600 caracteres y extracto <= 1.200). El
enlace con la historia se guarda en la propia fila (`story_id`, con indice): la historia lee sus
declaraciones con una consulta por indice. Medido el 2026-10-19: el coseno de titulares (ADR 0022) no
sirve para posts de partidos (15 historias de >= 3 medios frente a 223 declaraciones: 0 enlaces con
umbral 0,25; las parejas correctas puntuan 0,07-0,20 y el ruido hasta 0,21), asi que el enlace lo
propone la IA y lo valida el codigo (ADR 0007) en el siguiente paso del item.

## Coherencia
Tabla `political_statement`, con el estilo de `article`: `id` Integer, `actor` String(40) (slug del
partido en `registry/political/<iso>.yaml`, sin FK: los partidos son datos del registro, como las
categorias), `country` String(2), `channel` String(16) con CHECK en web/bluesky/mastodon/telegram,
`url` String(1000), `url_hash` String(64) unico (sha256 de la URL, como `article.url_hash`), `text`
String(600), `summary` Text nullable, `published_at` y `fetched_at` DateTime con zona, y `story_id` FK a
`story.id` nullable con `ON DELETE SET NULL` (la historia de la que habla; una declaracion habla de una
sola cosa, y si la historia se borra la declaracion se conserva). Invariantes en
codigo: solo se guardan canales del registro y cada canal declara como se verifico que es oficial
(dominio propio o enlace desde la web oficial); no se guarda nada de una URL que robots.txt prohiba ni
de un sitio que responda 401/403.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| `outlet.kind = 'party'` y textos en `article` | Entrarian en historias, comparador, ranking y fiabilidad de medios |
| Una tabla de actores en la base | Los partidos cambian por legislatura y se editan como datos del registro (C10); un slug basta |
| No guardar y enlazar solo a sus perfiles | El bloque no podria citar que dijo cada partido sobre esa historia |
| Tabla de enlaces historia-declaracion | Una declaracion habla de una sola cosa; una columna basta y evita otra tabla |
| Emparejar por coseno de titulares al servir | Medido: 0 enlaces utiles (ver Escalabilidad) |

## Necesidades futuras
Politicos individuales (blogs, cuentas personales) son otro `actor` del registro con `kind: politician`
y el mismo esquema. Otro pais es otro `registry/political/<iso>.yaml`. Un canal nuevo (YouTube, si su
robots.txt lo permite, o X con API) es un valor mas del CHECK, con su migracion de una linea. El
contraste de declaraciones con datos (carril Verificaciones) puede leer esta tabla sin cambiarla.

## Migracion y reversibilidad
Migracion 0014 sobre 0011 (head de main): un `CREATE TABLE` con su indice, sin tocar tablas existentes ni bloquearlas y
sin relleno (el worker la llena en el siguiente ciclo). El codigo anterior no la lee. Reversion:
`DROP TABLE political_statement`; se pierden las declaraciones guardadas, que los canales vuelven a
servir en parte (sus ultimas ~20 entradas).

## Decision
Las declaraciones de los partidos se guardan en `political_statement`, separadas de los medios, con el
partido, el canal oficial verificado y la URL citada, y la historia las muestra en un bloque
"Que dicen los partidos" con el mismo formato y orden alfabetico para todos.

## Verificacion
Migracion aplicada y revertida en SQLite (`tests/test_migrations.py`, cabeza unica); `tests/test_political.py`
ejerce los cuatro canales con respuestas grabadas, la deduplicacion y el respeto a robots.txt; medida en vivo de canales validos por partido en `docs/benchmarks/fase_g4.json`.

## Alcance
- `alembic/versions/0014_declaraciones_politicas.py`
- `truthnews/models.py`
