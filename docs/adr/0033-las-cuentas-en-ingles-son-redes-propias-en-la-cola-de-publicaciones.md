# ADR 0033 — Las cuentas en ingles son redes propias en la cola de publicaciones

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** item del ledger "Redes v2" (asignado por la direccion 2026-10-19 05:29)
- **Decide:** Constructor, auditado por el Critico

## Contexto
La direccion pide piezas en ingles para cuentas internacionales, en modo prueba hasta que haya
credenciales. La cola de publicaciones es `social_post` (ADR 0018): una fila por red y contenido, con
`UNIQUE (network, kind, ref_id)` y `CHECK (network IN ('x', 'bluesky', 'mastodon', 'telegram'))`. La
columna `language` ya existe (`String(8)`, hoy siempre `es`). Los titulares traducidos con IA viven en
`article_translation` (ADR 0017) y se leen por historia con `queries.story_title_translations`.

Una cuenta en ingles es otra cuenta de la misma red: otras credenciales, otro cupo y otro registro. La
misma historia se publica una vez en `x` (espanol) y otra en la cuenta inglesa de X.

## Necesidad
Con el esquema actual la historia 12 en X en espanol ocupa la clave (`x`, `historia`, 12): la pieza
inglesa de la misma historia en la cuenta inglesa no cabe sin romper la unicidad que impide duplicados.
Alternativas sin migracion: (a) meter `language` en la clave unica: tambien es migracion, y mezcla en una
misma `network` dos cuentas con cupos y credenciales distintos, asi que el cupo diario (contado por
`network`) dejaria de ser por cuenta; (b) reutilizar `network` con un valor nuevo sin tocar el `CHECK`:
la base lo rechaza (comprobado: `CHECK constraint failed: ck_social_post_network`). Hace falta ampliar el
`CHECK`; es lo que el ADR 0018 dejo previsto en "Necesidades futuras" (`x-en`).

## Escalabilidad
Cupo por defecto de las cuentas inglesas: X 2, Bluesky 3, Mastodon 3, Telegram 4 al dia: como maximo 12
filas mas al dia (~4.400 al ano, ~1,5 MB). Las consultas son las mismas del ADR 0018 y siguen usando
`ix_social_post_network_created` y la restriccion unica; el `CHECK` no cuesta nada medible por fila.

## Coherencia
Valores `x_en`, `bluesky_en`, `mastodon_en`, `telegram_en`: guion bajo como el resto de identificadores
del esquema, `String(16)` sigue bastando (11 caracteres el mas largo). `language = 'en'` en esas filas
(invariante en el codigo: `truthnews/social/queue.py` toma el idioma del candidato). El nombre de la
restriccion no cambia (`ck_social_post_network`) y el modelo la construye con `SOCIAL_NETWORKS +
SOCIAL_NETWORKS_EN`, asi que modelo y migracion no pueden divergir sin que lo note
`tests/test_migrations.py`.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| `UNIQUE (network, language, kind, ref_id)` y la misma `network` | Dos cuentas con cupos y credenciales distintos bajo un mismo nombre; el cupo por `network` dejaria de ser por cuenta y habria que reescribir sus consultas |
| Tabla `social_account` (red, idioma, credenciales por referencia) y clave foranea | Mas flexible para N cuentas, pero hoy hay exactamente dos idiomas; seria una tabla y una relacion para 8 filas fijas que ya describe la configuracion |
| Quitar el `CHECK` | Perderia la proteccion contra un nombre de red mal escrito, que hoy rompe en la base y no en silencio |

## Necesidades futuras
Otro idioma o pais (p. ej. frances) seria otra extension del mismo `CHECK` (`x_fr`...) y otra lista en
`SOCIAL_NETWORKS_*`. Si llegaran a ser muchas cuentas, la tabla `social_account` de la segunda alternativa
pasaria a compensar; migrar a ella seria mapear cada `network` actual a una fila de cuentas, sin perder el
registro. Las metricas de alcance por cuenta (ADR 0018) no cambian.

## Migracion y reversibilidad
Un paso: `batch_alter_table` sustituye el `CHECK` (en Postgres, `DROP CONSTRAINT` + `ADD CONSTRAINT` sobre
una tabla de decenas de filas: bloqueo de milisegundos). Sin relleno. El codigo desplegado antes no
escribe redes `*_en`; el nuevo funciona igual con la tabla en cualquier estado. `downgrade` borra las filas
`*_en` (solo existen en modo prueba hasta que haya credenciales) y restaura el `CHECK` original; se pierde
el registro de lo que se habria publicado en ingles.

## Decision
Las cuentas en ingles son redes propias en `social_post` (`x_en`, `bluesky_en`, `mastodon_en`,
`telegram_en`), con sus credenciales (prefijo `*_EN_`), su cupo y su registro; solo publican historias con
titular traducido por IA y lo dicen ("Headline machine-translated from Spanish").

## Verificacion
Migracion aplicada, revertida a 0016 y vuelta a aplicar en SQLite: el `CHECK` acepta `x_en` tras subir,
lo rechaza tras bajar y rechaza siempre una red inexistente; `compare_metadata` sin diferencias en
`social_post`; `tests/test_migrations.py` y `tests/test_social.py`
(`test_english_pieces_only_with_translated_headline`, `test_english_accounts_use_their_own_credentials`).

## Alcance
- `truthnews/models.py`
- `alembic/versions/0017_redes_en_ingles.py`
