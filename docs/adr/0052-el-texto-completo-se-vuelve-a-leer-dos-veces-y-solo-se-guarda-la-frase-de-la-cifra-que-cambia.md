# ADR 0052 — El texto completo se vuelve a leer dos veces y solo se guarda la frase de la cifra que cambia

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** item del ledger «Quien cambio su cifra tambien en el texto completo (content_hash)» (carril Comparativas, cedido a Entidades por la direccion)
- **Decide:** agente Entidades, auditado por el Critico

## Contexto
ADR 0032 detecta «quien cambio su cifra» comparando las revisiones de titular y extracto (ADR 0015).
Cada rastreo trae esos dos campos del feed y `track_revisions` guarda el antes y el despues en
`article_revision`. El texto completo no se vigila. `article.content_text` se descarga una vez, al
entrar la noticia o en el relleno (`backfill_texts`), y no se vuelve a pedir. `content_hash` se calcula
pero nadie lo compara. Un medio puede cambiar «12 muertos» por «15 muertos» en el cuerpo sin tocar el
titular y hoy no se ve.

Lo que hay en el esquema y se usa:
- `article.content_text`, `content_hash` y `word_count`.
- `article_revision(field IN ('title','summary'), before, after, before_hash, after_hash)`, con
  `before` y `after` recortados a 600 caracteres (`REVISION_MAX_CHARS`, derecho de cita, ADR 0003).
- `ix_article_revision_article_detected` e `ix_article_revision_outlet_detected`, que son las lecturas de
  la historia y de la ficha del medio.

## Necesidad
Hacen falta dos cosas que el esquema no tiene.

1. **Marcar que una revision es del texto completo.** El `CHECK` de `article_revision.field` solo admite
   `title` y `summary`. Guardarla como `summary` mentiria al lector («extracto») y mezclaria dos señales
   distintas en la ficha de captura.
2. **Saber cuantas veces se volvio a leer cada texto**, para no pedirlo en cada rastreo. Sin una marca,
   la unica forma de decidir que toca es la edad de la noticia. Con rastreos cada 5–25 minutos, una
   ventana de edad fija o se salta noticias o las pide varias veces. `fetched_at` es la primera captura
   y no cambia. `content_hash` no dice si ya se comparo.

Se considero no cambiar nada y recalcular en lectura. No se puede: el texto antiguo se sobrescribe, asi
que si no se guarda el antes en el momento de compararlo se pierde. Se considero tambien guardar el
texto entero en otra tabla. No hace falta y choca con ADR 0003: solo se guarda la frase de la cifra.

## Escalabilidad
Medido en los registros del worker en Railway el 2026-10-19, de 06:35 a 12:40 UTC:
- Entre 385 y 589 noticias nuevas por ciclo completo, con un ciclo cada 25–60 minutos.
- El relleno de textos encuentra 80–95 candidatas por rastreo y casi siempre rellena 0, porque el muro
  de pago o el 403 cierran el paso. Lo que tiene texto completo se descarga casi siempre al entrar.

Estimacion de la carga:
- Politica y economia (`VERIFIABLE`) son una parte de esas ~500 noticias por ciclo, y solo las que ya
  tienen texto se pueden volver a leer.
- Con dos relecturas por noticia (a las 3 h de la captura y a las 24 h de publicarse) y un tope de
  `MAX_TEXT_RECHECK_PER_RUN` = 60 por rastreo, 5 por dominio, el techo es de 60 peticiones por rastreo,
  repartidas en paralelo entre dominios con el mismo cliente educado del rastreo (robots.txt y pausa
  por dominio).
- A 10x noticias el tope no cambia: se releen menos y antes las mas viejas dentro de la ventana de 48 h.

Coste en la base:
- `article.content_checks` es un entero de 4 bytes por fila, sin indice. La consulta de candidatas ya
  filtra por `ix_article_category_published` (categoria y fecha en ventana de 48 h).
- `article_revision` solo crece cuando una cifra cambia de verdad. ADR 0032 midio 1 cambio de cifra en
  49 revisiones de titular y extracto, y el cuerpo deberia dar un orden de magnitud parecido: decenas de
  filas al dia como mucho, cada una de 1,2 kB como maximo (dos citas de 600 caracteres).

## Coherencia
- `content_checks` es `Integer NOT NULL DEFAULT 0`, como los contadores de `entity` (ADR 0028). Vale 0
  (aun no se ha releido), 1 (releido a las 3 h) o 2 (releido desde las 24 h; no hay mas). Se eligio un
  contador y no una fecha porque la regla «la segunda lectura, desde las 24 h de publicarse» con una fecha
  exige sumar un intervalo a una columna, y eso no se escribe igual en Postgres y en SQLite (la base de
  los tests). Con el contador la consulta es portable y el tope de dos lecturas queda en el dato. La hora
  de cada cambio ya esta en `article_revision.detected_at`.
- `field` pasa a admitir `content`, con el mismo `CHECK` con nombre (`ck_article_revision_field`) y la
  tupla `REVISION_FIELDS` del modelo como unica fuente.
- `before` y `after` guardan, para `content`, las frases de la cifra que cambia y, si existe, la frase
  nueva que avisa del cambio. Siempre dentro de `REVISION_MAX_CHARS`.
- `before_hash` y `after_hash` guardan el hash del texto completo, el mismo valor que `content_hash`, asi
  que la cadena de versiones se puede seguir.
- La invariante «solo se guarda la revision de cuerpo si cambia una cifra» vive en el codigo
  (`figure_changes.body_excerpts`), igual que la deteccion de ADR 0032.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Tabla `article_text_version` con el texto completo de cada version | Duplica textos de miles de palabras por noticia y republica el cuerpo (ADR 0003). Solo interesa la cifra |
| Guardar el cuerpo como revision `summary` | Mezcla dos campos y la ficha diria «extracto» de algo que no lo es |
| Fecha de la ultima relectura (`content_checked_at`) | Probado: la regla de la segunda lectura necesita columna + intervalo, que SQLite no evalua; el contador da lo mismo y limita las lecturas en el dato |
| Sin marca: releer por edad (de 3 h a 3 h y 10 min) | Los rastreos no tienen periodo fijo (5–25 min); se saltan noticias o se piden dos veces |
| Releer en cada rastreo hasta las 48 h | Unas 10–20 veces mas peticiones a los medios por la misma señal; descortes con sus servidores |
| Guardar cualquier cambio del cuerpo | La mayor parte son retoques de redaccion. Guardarlos llenaria la tabla de citas sin señal |

## Necesidades futuras
- Si se quiere una tercera relectura (por ejemplo a la semana), basta otra regla sobre
  `content_checks` = 2, sin esquema.
- Si algun dia se quiere el historial de cambios del cuerpo no numericos, hara falta otro ADR: aqui no se
  guardan a proposito.
- La migracion al holding (ADR 0025) recibe un campo y un valor de enumerado mas en el dominio de
  noticias, ambos compatibles hacia atras (el contador con valor por defecto).

## Migracion y reversibilidad
Migracion 0023, en un paso:
1. `ALTER TABLE article ADD COLUMN content_checks INTEGER NOT NULL DEFAULT 0`. En Postgres 11 o
   posterior, una columna con valor por defecto constante es un cambio de catalogo, sin reescribir la
   tabla. Las filas existentes quedan a 0 y entran en la primera relectura si estan dentro de la ventana
   de 48 h.
2. El `CHECK` de `article_revision.field` se sustituye por uno que incluye `content`. En SQLite se hace en
   modo batch, recreando la tabla.

El codigo en marcha durante el despliegue no escribe `content` ni lee la columna nueva, asi que la base
nueva es compatible con el codigo anterior.

Para revertir se borran las revisiones `content`, se vuelve al `CHECK` anterior y se quita la columna.
Se pierden solo las revisiones de cuerpo detectadas y el contador de relecturas.

## Decision
El rastreo vuelve a leer el texto completo de las noticias de politica y economia que ya lo tienen, dos
veces (a las 3 h de la primera captura y a partir de las 24 h de publicarse), con un tope por rastreo y
por dominio. Cuando cambia una cifra se guarda una revision `content` con la frase de antes y la de
despues; cuando no, solo se actualiza el texto y su hash. Las revisiones de cuerpo entran en «Quien
cambio su cifra» con las mismas reglas de ADR 0032.

Que es «cambiar una cifra» en el cuerpo (revision de Global): la misma frase con otra cifra. Una frase
nueva que comparte al menos el 60 % de sus palabras, sin contar cifras, con una frase anterior que ya no
esta, y en la que la cifra de un mismo sustantivo vale distinto. La regla de ADR 0032, la primera cifra
del sustantivo, no sirve en un cuerpo largo: un parrafo nuevo de contexto («en 2019 hubo 30 muertos»)
cambiaria esa primera cifra sin que el medio corrija nada, y «cambio su cifra en silencio» es una
acusacion.

Una relectura con menos de la mitad de palabras que el texto guardado (muro de pago, registro o
consentimiento de cookies) cuenta como relectura fallida. No pisa el cuerpo y se mide en
`run.stats["recheck_shorter"]`. La segunda relectura exige ademas que la noticia entrase hace 21 h
(`fetched_at`), para que una noticia que llega tarde al feed no haga sus dos relecturas seguidas.
Limite conocido (nota de Global): `fetched_at` es la entrada de la noticia, no la del relleno del texto,
asi que un texto rellenado tarde aun puede releerse dos veces en ciclos seguidos. Cuesta una peticion
de mas en 0–10 textos por rastreo (lo que rellena hoy `backfill_texts`) y no da revisiones falsas, porque
solo cuenta la misma frase con otra cifra. Queda para otro PR, si la medida en produccion lo pide.

Solo se releen noticias en castellano (`language == "es"`). El lector de cifras (ADR 0016) es de
castellano, y en portugues «dos votos» se lee como 2, como midio Comparativas en el fixture de disputas
(#215).

Tres limites, de la revision de Global y de la direccion (2026-10-19):
- Los directos no se releen: su texto cambia a cada minuto y no es una correccion (#87).
- El paso no empieza ninguna peticion pasado un minuto (`RECHECK_MAX_SECONDS`). Su duracion se publica en
  `run.stats["recheck_seconds"]`.
- Los 403 y 429 se cuentan por medio en `run.stats["recheck_refused"]` y no se rodean. Un medio que
  frena se deja hasta el ciclo siguiente.

## Verificacion
- La migracion se aplica y se revierte en una base SQLite limpia (test).
- Tests de la relectura:
  - Se pide solo lo que toca.
  - Un cambio de cifra guarda una revision `content` con la cita y el aviso.
  - Un retoque sin cifra solo actualiza el texto.
  - La segunda relectura llega a las 24 h y no hay tercera.
  - Un dominio que falla se deja.
- Medida en produccion tras el despliegue, en `docs/benchmarks/fase_e2.json`: textos releidos por rastreo,
  revisiones de cuerpo y duracion del paso.

## Alcance

- `truthnews/models.py`
- `alembic/versions/0023_relectura_del_texto.py`
