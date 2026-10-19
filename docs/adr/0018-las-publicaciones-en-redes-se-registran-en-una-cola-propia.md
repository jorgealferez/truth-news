# ADR 0018 — Las publicaciones en redes se registran en una cola propia, una fila por red y contenido

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** 4 (item del ledger "Autopublicacion en redes")
- **Decide:** Constructor, auditado por el Critico

## Contexto
Peticion del usuario (2026-10-19): "auto publicar lo mas relevante y contrastado o mediatico en nuestras
redes sociales". Criterio C9 de la carta: cada verificacion publicada genera piezas para al menos 4 redes
(X, Bluesky, Mastodon, Telegram) dentro de sus limites; la publicacion real queda NO VERIFICADO hasta tener
credenciales.

Hoy no hay nada en el esquema sobre redes: la Fase 4a (#12) solo dibuja la imagen social por historia
(`/og/historia/{id}.png`, en memoria) y genera enlaces de compartir para el lector. Lo que se publicaria
sale de tablas existentes: `story` (`priority`, `contrast_score`, `contrast`), `thread` (`status`,
`sources`) y `verification` + `evidence` (`verdict`, `url`). Ninguna de esas tablas dice si un contenido
ya se publico en una red, cuando, con que texto ni con que resultado.

## Necesidad
Sin un registro persistente el worker no puede garantizar las tres reglas pedidas: sin duplicados (el
mismo contenido no se publica dos veces en la misma red aunque el worker se redespliegue o el ciclo se
repita), cupo por red y por dia (hay que contar lo publicado hoy) y registro de cada envio (texto exacto,
identificador y enlace devueltos por la red, error y reintentos). Alternativas sin esquema nuevo:
(a) recordar lo publicado en memoria del worker: se pierde en cada redespliegue (los agentes despliegan
varias veces por hora, ver `RECENT_CYCLE_MIN` en `truthnews/worker.py`) y se duplicaria;
(b) consultar a cada red sus ultimas publicaciones antes de publicar: no existe sin credenciales (modo
prueba), cuesta una llamada por red y ciclo y no guarda los errores; (c) una columna JSON
`published_on` en `story`, `thread` y `verification`: reparte el registro en tres tablas ajenas al
carril, obliga a tocar tres modelos compartidos y no permite contar el cupo diario con una consulta.
Ninguna basta.

## Escalabilidad
Con el cupo por defecto (X 4, Bluesky 6, Mastodon 6, Telegram 8 al dia) entran como maximo 24 filas al
dia: ~8.800 al ano, unas 3 MB con texto de hasta 1.024 caracteres. Escrituras: como mucho una por pieza y
ciclo (cada 60 min). Lecturas: dos por red y ciclo, ambas por indice: el cupo
(`network`, `created_at` >= hoy) por `ix_social_post_network_created` y los ya publicados
(`network`, `kind`, `ref_id`) por la restriccion unica. A 10x (240 al dia) sigue siendo trivial para
Postgres; el indice compuesto cuesta una entrada por fila insertada.

## Coherencia
Nombres y tipos como el resto del esquema: `id` entero, fechas `DateTime(timezone=True)` con `utcnow`,
estados en `String(16)` con `CHECK` (como `piece.status`, `thread.status`), textos en `Text`, enlaces en
`String(1000)` (como `article.url`). `kind` + `ref_id` apuntan a `story`, `thread` o `verification`
segun el tipo; no hay clave foranea porque la referencia es polimorfica, y se acepta: la fila es un
registro historico de lo que se envio y debe sobrevivir aunque el contenido se retire (si se retira una
historia, la publicacion ya existe en la red y el registro es la prueba). `UNIQUE (network, kind,
ref_id)` deja en la base el invariante "sin duplicados". El cupo diario y "nunca en revision ni sin
fuente" quedan en el codigo (`truthnews/social/select.py`), porque dependen de la configuracion y de
tablas de otros carriles.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Una tabla de piezas y otra de intentos de envio (1:N) | Con un maximo de 3 reintentos y una sola pieza por red, `attempts` + `error` + `sent_at` en la misma fila basta; dos tablas duplican lecturas sin necesidad medible |
| Claves foraneas reales (`story_id`, `thread_id`, `verification_id` nulables) | Tres columnas, dos siempre nulas, y un `CHECK` de exclusividad; y el borrado en cascada borraria el registro de algo ya publicado |
| Guardar la imagen en la base | Se regenera desde la historia (`truthnews/social/images.py`); solo se guarda su URL publica |

## Necesidades futuras
Volver a publicar una historia relanzada (`story.relaunched_at`, ADR 0012) choca con la unicidad: cuando
se pida, se anade una columna `edition` a la clave en una migracion pequena (expandir). Otros idiomas o
paises: `language` ya va en la fila; un pais distinto seria otra cuenta, otra `network` (p. ej.
`x-en`), ampliando el `CHECK`. Metricas de alcance (likes, compartidos) irian en una columna JSON nueva
o en una tabla aparte, sin tocar esta.

## Migracion y reversibilidad
Un paso, expandir: `CREATE TABLE social_post` con su indice, sin tocar tablas existentes ni bloquearlas,
sin relleno. El codigo que corre durante el despliegue no la conoce; el nuevo funciona con la tabla
vacia. Se revierte con `downgrade` (`DROP TABLE`): se pierde el registro de lo publicado, y el siguiente
ciclo podria volver a publicar lo de las ultimas 72 h (ventana de seleccion): por eso, si se revierte en
produccion con credenciales puestas, primero se pone `SOCIAL_ENABLED=0` en el worker.

## Decision
Se crea `social_post`: una fila por red y contenido (historia, hilo o verificacion), con el texto exacto,
el enlace, la imagen, el estado (`prueba` sin credenciales, `enviado`, `error`), el identificador y la URL
que devuelve la red, el ultimo error y los intentos; unica por (`network`, `kind`, `ref_id`).

## Verificacion
Migracion aplicada y revertida en SQLite en `tests/test_migrations.py`; tests de seleccion (sin
revision, sin fuente ni duplicados, cupo diario), de composicion (limites de X 280, Bluesky 300,
Mastodon 500, Telegram 1.024 con URL), de adaptadores con transporte HTTP simulado y del paso del worker
en modo prueba; benchmark `docs/benchmarks/fase_4b.json`.

## Alcance
- `truthnews/models.py`
- `alembic/versions/0008_redes.py`
