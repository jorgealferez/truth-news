# ADR 0048 — La pieza diaria "Hoy en 1 minuto" entra en la cola de publicaciones con su propio tipo

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** item del ledger "Hoy en 1 minuto" (asignado por la direccion 2026-10-19 08:37)
- **Decide:** Constructor, auditado por el Critico

## Contexto
"Hoy en 1 minuto" (ADR 0047) reune las claves contrastadas del dia en `/hoy`, con imagenes para redes, y
la direccion la quiere como pieza diaria de la autopublicacion. La cola es `social_post` (ADR 0018):
`kind` + `ref_id` identifican el contenido y `UNIQUE (network, kind, ref_id)` impide publicarlo dos
veces; `CHECK (kind IN ('historia', 'hilo', 'verificacion'))`.

## Necesidad
La pieza diaria no es una historia, un hilo ni una verificacion: no tiene fila propia en ninguna tabla.
Registrarla como `historia` con un `ref_id` inventado mezclaria identificadores de dos espacios (una
historia 20261019 existiria o no por casualidad) y el equilibrio de ADR 0043 la trataria como historia.
Sin registro no hay "una por dia y red" ni constancia de lo enviado. Hace falta un `kind` mas.
Alternativa sin esquema descartada: guardarla en memoria del worker (se repetiria tras cada redespliegue).

## Escalabilidad
Una fila por red y dia: 4 al dia (las cuentas inglesas no la publican), ~1.460 al ano. Mismas consultas e
indices que el ADR 0018; el `CHECK` no cuesta nada medible.

## Coherencia
`kind = 'hoy'` y `ref_id = AAAAMMDD` del dia (entero, como el resto de `ref_id`): la restriccion unica da
"una por dia y red" sin columnas nuevas. `link` apunta a `/hoy` e `image_url` a `/og/hoy-vertical.png`.
Invariantes en el codigo (`truthnews/social/select.py::today_piece`): solo hay pieza si hay al menos una
clave contrastada (sin relleno, ADR 0047) y solo en las redes en espanol, porque las frases solo existen
en espanol.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| `kind = 'historia'` con `ref_id` = fecha | Mezcla dos espacios de identificadores y confunde el equilibrio (ADR 0043) |
| Tabla `daily_digest` con la pieza y FK desde `social_post` | Una tabla para una fila al dia cuyo contenido ya se recalcula de la base; mas esquema sin necesidad |
| Columna `kind` sin `CHECK` | Pierde la proteccion contra un tipo mal escrito |

## Necesidades futuras
Una pieza semanal o mensual seria otro `kind` (`semana`, `ref_id` = AAAASS) con la misma regla. Si la
pieza diaria llegara a traducirse (frases en ingles desde los datos), entraria en las redes `*_en` sin
cambio de esquema.

## Migracion y reversibilidad
Un paso: `batch_alter_table` sustituye el `CHECK` de `kind` (en Postgres, `DROP`/`ADD CONSTRAINT` sobre
una tabla de cientos de filas: milisegundos). Encadenada a la cabeza de main (0021). `downgrade` borra las
filas `hoy` (en modo prueba hasta que haya credenciales) y restaura el `CHECK`; se pierde ese registro.

## Decision
`social_post.kind` admite `hoy`: la pieza diaria se registra una vez por dia y red, con `ref_id` = fecha
AAAAMMDD, y solo cuando hay algo contrastado.

## Verificacion
Migracion aplicada, revertida a 0021 (rechaza `hoy`) y vuelta a aplicar en SQLite; `compare_metadata` sin
diferencias en `social_post`; `tests/test_migrations.py`; `tests/test_social.py::
test_daily_piece_once_a_day_only_with_checked_data` (sin datos no hay pieza, una por dia, no en ingles,
imagen vertical).

## Alcance
- `truthnews/models.py`
- `alembic/versions/0020_pieza_diaria_hoy.py`
