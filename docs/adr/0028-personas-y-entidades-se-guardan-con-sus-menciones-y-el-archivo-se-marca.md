# ADR 0028 — Personas y entidades se guardan con sus menciones, cada afirmacion con quien la dice y lo importado del archivo se marca

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** 9 (quien miente, quien informa) y 10 (hilo y consecuencias)
- **Decide:** Constructor, auditado por el Critico

## Contexto

Peticion del usuario (2026-10-19): "si se menciona a X personas, X entidades... que podamos analizar,
extraer y ordenar ese dato... para poder asociar datos macro", "importar noticias, aunque sean mas
antiguas, para tener mas informacion anterior de las mismas personas" y "recalcar donde hay grandes
mentiras... entre politicos, medios de comunicacion y datos". Items del ledger "Entidades y archivo
historico" y "Grandes falsedades y discrepancias".

Hoy el esquema no sabe **de quien** habla una noticia ni **quien** dice cada cifra:

- `article` (3.164 noticias en la ventana de portada medida el 2026-10-19 en nosmienten.com, 130
  medios activos) guarda titular, extracto y texto, pero ninguna persona u organizacion.
- `claim` se atribuye solo al medio (`outlet_id`). Una cifra que un ministro da y un periodico recoge
  queda como "dicha por el periodico": no se puede decir que una persona falto a los datos ni seguir
  sus afirmaciones en el tiempo (referente PolitiFact de `docs/equipo.md`).
- Las noticias solo entran por RSS (`feed_id`), es decir, desde el dia en que se dio de alta cada medio.
  Para tener "informacion anterior de las mismas personas" hay que importar del archivo (GDELT DOC,
  desde 2017, ya usado por los hilos, ADR 0013) y distinguir esas noticias de las rastreadas.

## Necesidad

Es imprescindible tocar el esquema:

- **Entidades y menciones**: la ficha de una persona necesita sus menciones ordenadas en el tiempo,
  por medio y junto a quien aparece. Calcularlo en lectura exigiria pasar el extractor por todos los
  articulos en cada peticion (segundos por pagina con 10^5 articulos, frente al p95 < 300 ms de C7).
  El campo JSON `article.topics` existente es una lista de etiquetas de categoria sin identidad: no
  permite agrupar "Feijoo" y "Alberto Nunez Feijoo" ni consultar por entidad con indice.
- **Quien dice cada afirmacion**: sin una columna en `claim` el ranking de falsedades por persona
  tendria que reextraer el hablante cada vez; con ella es un `GROUP BY` indexado.
- **Origen de la noticia**: sin marca, una noticia de 2019 importada del archivo se mezclaria con la
  ingesta de hoy en el recuento de C2 y en "ultima hora". `feed_id IS NULL` no basta: ya hay
  articulos sin feed por `ON DELETE SET NULL`.
- **Progreso de la extraccion**: el worker procesa por tandas; sin `article.entities_at` tendria que
  recordar un cursor fuera de la base o reprocesar la tabla entera en cada ciclo.

Si no se hace, no hay fichas de personas, ni ranking de falsedades por quien las dice, ni archivo.

## Escalabilidad

Medido el 2026-10-19: ~3.200 noticias en la ventana de portada y 130 medios; la ingesta ronda
3.000 noticias/dia. Proyeccion a 12 meses con el archivo: ~1,1 M noticias rastreadas + hasta
~0,5 M importadas (cupo del archivo: 6 consultas GDELT por ciclo x 48 ciclos/dia x <=25 resultados,
solo de dominios del registro: <=7.200/dia, en la practica una fraccion).

- `mention`: el extractor medido sobre el conjunto etiquetado da ~4 entidades por noticia ->
  ~6 M filas a 12 meses, ~100 bytes por fila sin la cita (la cita solo se guarda cuando la entidad
  habla, <=300 caracteres) -> ~1 GB con indices. A 10x (60 M filas) sigue siendo un `SELECT` por
  `entity_id` con indice; si hiciera falta, se particiona por `published_at` sin cambiar el modelo.
- `entity`: crece con nombres propios distintos; las descubiertas se guardan y la portada/listado solo
  muestra las de >= 2 medios. Estimacion: ~50.000 filas a 12 meses.
- Escrituras: una tanda de <=2.000 noticias por ciclo (cada 30 min) -> ~8.000 inserciones de
  `mention` por ciclo, en una transaccion. Lecturas: la ficha de entidad usa `(entity_id,
  published_at)`; la co-aparicion ("con quien aparece") se calcula con un self-join por `article_id`
  acotado a las ultimas 500 menciones de la entidad, con `ix_mention_article`.
- Indices nuevos: `uq_mention_entity_article` (unicidad y acceso por entidad), `ix_mention_entity_published`,
  `ix_mention_article`, `ix_mention_story`, `uq_entity_key`, `ix_entity_kind_articles`,
  `ix_entity_last_seen`, `ix_claim_speaker_entity_id`, `ix_article_entities_at`. Coste en escritura:
  4 indices por fila de `mention`, aceptable para ~8.000 filas por ciclo.

## Coherencia

- Nombres y tipos como el resto del esquema: `id` entero, `created_at`/`updated_at`
  `DateTime(timezone=True)`, `kind` y `role` como `String` con `CheckConstraint` (igual que
  `verification.verdict`, `social_post.network`), claves foraneas con nombre explicito
  (`fk_<tabla>_<columna>`, como en ADR 0015/0017).
- `entity.key` = `<kind>:<nombre normalizado>` unico: la misma persona descubierta en dos medios es
  una sola fila; los alias del registro curado (`registry/entities.yaml`) apuntan a la misma clave.
- `mention` unica por `(entity_id, article_id)`; `ON DELETE CASCADE` desde `entity`, `article` y
  `outlet` (una mencion no existe sin ellos); `story_id` `SET NULL` como en `claim`.
- Desnormalizacion deliberada: `mention.outlet_id`, `story_id` y `published_at` copian los del
  articulo para que la ficha y los rankings no necesiten unir `article` (la tabla mayor). Se
  reescriben si el articulo cambia de historia en el ciclo siguiente.
- `entity.n_mentions/n_articles/n_outlets/first_seen/last_seen` son agregados recalculados desde
  `mention` para las entidades tocadas en cada tanda (como `story.n_articles`, ADR 0004).
- `claim.speaker_entity_id` nullable `SET NULL`: la afirmacion sigue existiendo si se borra la
  entidad; `NULL` significa "la dice el medio" (lo que habia hasta ahora).
- `article.origin` `IN ('rss','archivo')` con `server_default 'rss'`: todas las filas existentes
  quedan como rastreadas, que es lo que son.
- Invariantes en la base: unicidades, checks y claves foraneas. En el codigo: que una entidad
  descubierta solo se publica con >= 2 medios y que el hablante se atribuye solo con un verbo de
  declaracion o "segun" en la misma frase (ADR 0027 describe el metodo).

## Alternativas consideradas

| Alternativa | Por que no |
|---|---|
| Guardar las entidades como JSON en `article` (`article.entities`) | Sin indice por entidad: la ficha de una persona tendria que leer todos los articulos; no deduplica nombres entre medios |
| Tabla `speaker` aparte para quien dice cada afirmacion | Una persona que habla es la misma que se menciona: dos tablas duplicarian identidades y alias |
| Tabla `archive_article` separada para lo importado | Las comparativas, historias y verificaciones tendrian que unir dos tablas; una columna `origin` basta |
| Extraer con un modelo de NER (spaCy) en lugar de reglas y registro curado | +500 MB de imagen y sin medida de precision en castellano periodistico; se deja abierto: el esquema no depende del extractor |
| Cursor de progreso en una tabla de estado clave-valor | Una columna por articulo es mas simple, sobrevive a cambios del extractor (se pone a NULL para reprocesar) y es indexable |

## Necesidades futuras

- **Wikidata**: la columna `entity.aliases` (JSON) y `kind` permiten anadir un identificador externo
  despues sin rehacer menciones (columna nueva nullable).
- **Multi-pais e idioma**: `entity.country` nullable; el extractor ya trabaja con texto normalizado
  sin tildes en es/en/pt.
- **Reprocesar con un extractor mejor**: basta `UPDATE article SET entities_at = NULL` (o por rango
  de fechas); las menciones se reescriben por articulo.
- **Archivo**: `entity.archived_until` guarda hasta donde se ha importado cada entidad hacia atras;
  si se anaden otras hemerotecas (sitemaps de los medios) reutilizan `article.origin = 'archivo'`.
- **Borrado o rectificacion de una entidad** (derecho de rectificacion): `ON DELETE CASCADE` borra sus
  menciones y deja las afirmaciones como dichas por el medio.

## Migracion y reversibilidad

Un solo paso, sin relleno sincrono: crea `entity` y `mention` (vacias), anade a `article` `origin`
(con `server_default`, en Postgres 11+ sin reescribir la tabla) y `entities_at` (nullable), y a
`claim` `speaker_entity_id` (nullable). En SQLite (tests) se usa `batch_alter_table`. El relleno lo
hace el worker por tandas de 2.000 noticias por ciclo, empezando por las mas recientes: ~2 h para
las ~3.200 de la ventana, unos dias para el historico completo, sin bloquear. El codigo antiguo que
siga corriendo durante el despliegue no lee las columnas nuevas y las nuevas tienen valor por
defecto o son nullable: compatible. Revertir borra `mention`, `entity` y las tres columnas: se
pierden las entidades extraidas (se regeneran) y la marca de origen de lo importado (las noticias de
archivo quedarian como rastreadas: antes de revertir con archivo importado conviene borrarlas con
`DELETE FROM article WHERE origin = 'archivo'`).

## Decision

Se crean `entity` y `mention`, se anade `claim.speaker_entity_id` y `article.origin` /
`article.entities_at`, con el registro curado en `registry/entities.yaml` y extraccion por reglas en
`truthnews/entities/`; las entidades descubiertas solo se publican con >= 2 medios.

## Verificacion

- `tests/test_migrations.py`: la migracion sube y baja en una base limpia y las columnas coinciden con
  los modelos.
- `tests/test_entities.py`: extraccion (precision y exhaustividad sobre `tests/fixtures/entities.json`),
  atribucion del hablante, guardado idempotente y agregados; `tests/test_archive.py` para la
  importacion con GDELT simulado.
- Medida publicada en `docs/benchmarks/fase_e1.json`.

## Alcance

- `truthnews/models.py`
- `alembic/versions/0015_entidades.py`
