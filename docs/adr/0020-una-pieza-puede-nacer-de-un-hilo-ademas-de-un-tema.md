# ADR 0020 — Una pieza puede nacer de un hilo, ademas de un tema

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** 10 (Hilo y consecuencias, ampliacion del usuario)
- **Decide:** Constructor (session_01XrLycos96UiYpoi6fz7tJZ), numero asignado por la direccion

## Contexto
El usuario amplio el 2026-10-19 el item "Hilo y consecuencias" del ledger: "asociar automaticamente
noticias de distintas epocas, datos y articulos propios generados (cada hilo puede producir su pieza
propia enlazada)". Los hilos (ADR 0013, tabla `thread`) ya guardan cronologia, quien dijo que y
conexiones, cada elemento citado contra un corpus numerado (`thread.sources`). Las piezas propias
(ADR 0008, tabla `piece`) solo pueden colgar de un tema: `piece.topic_id` es `NOT NULL` con clave
foranea a `topic`. Una pieza del antes y el despues de un hilo no tiene tema propio.

## Necesidad
Hace falta un sitio donde guardar la pieza del hilo con lo mismo que ya tienen las piezas: estado
(publicada o revision), control de fundamento, modelo, uso de tokens y huella del dossier
(`input_hash`) para no pagar dos veces el mismo texto. Alternativas sin tocar el esquema:
- Guardarla dentro de `thread.content` (JSON): no aparece en `/analisis` ni en la portada, que leen
  `piece`; duplicaria en otra forma los campos de estado, fundamento y uso; y regenerar el hilo cada
  12 h pisaria la pieza.
- Crear un `topic` por hilo: falsearia el recuento de temas y la regla de "un tema reune historias".
Ninguna basta; el cambio minimo es que `piece` pueda apuntar a un hilo.

## Escalabilidad
Hoy: el worker genera como mucho 2 hilos por ciclo de 30 min y los refresca a las 12 h, es decir
<= 96 hilos/dia en el peor caso, del orden de 30-40 reales (historias de cabecera con hilo nuevo o
caducado). Una pieza por hilo publicado y por dossier distinto: <= 96 filas/dia, ~35 000/ano en el
peor caso, con cuerpos de 3-6 KB: < 250 MB/ano. `piece` ya crece a 2 filas por tema y dossier; esto
la multiplica como mucho por 2. Lecturas nuevas: "pieza vigente de un hilo" (`WHERE thread_id = ?`)
por pagina de hilo y "pieza con esta huella" antes de generar; las sirve un indice en `thread_id`
(coste de escritura despreciable a < 100 inserciones/dia). A 10x sigue siendo una tabla pequena.

## Coherencia
`piece.thread_id INTEGER NULL` con clave foranea `fk_piece_thread_id` a `thread.id`
`ON DELETE CASCADE`, igual que `topic_id` con `topic`. `topic_id` pasa a admitir `NULL`, y un check
`ck_piece_parent` exige que haya al menos uno de los dos (`topic_id IS NOT NULL OR thread_id IS NOT
NULL`): ninguna pieza queda huerfana. Indice `ix_piece_thread_id` con la convencion de nombres de
`ix_piece_topic_id`. `kind` sigue siendo `analisis` u `opinion`: la pieza del hilo es un analisis. La
regla "solo se publica si cada cifra esta en el dossier" sigue en el codigo (`writer.py`), como en
ADR 0007.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Tabla nueva `thread_piece` | Duplica las 12 columnas de `piece` y obliga a unir dos tablas en `/analisis`, la portada y el panel |
| Columna generica `parent_kind` + `parent_id` | Sin clave foranea real: la base no garantiza la integridad ni el borrado en cascada |
| JSON en `thread.content` | Ver Necesidad: invisible para los listados y pisado en cada refresco |

## Necesidades futuras
Las investigaciones a demanda (ADR 0010) podran producir su pieza del mismo modo, con otra columna
nullable y el check ampliado; el patron sirve sin coste ahora. Internacionalizacion: `piece.language`
ya existe. Historico: una pieza nueva por dossier distinto conserva las anteriores.

## Migracion y reversibilidad
Un solo paso, expansivo: anadir la columna nullable, el indice y la clave foranea, y relajar
`topic_id` a nullable con el check. Sin relleno de datos (las filas existentes tienen `topic_id`). En
Postgres son `ALTER TABLE` de metadatos (la comprobacion del check recorre la tabla, de cientos de
filas: milisegundos). El codigo que corre durante el despliegue no lee la columna y sigue escribiendo
`topic_id`: compatible. Revertir: borrar las piezas de hilo (`thread_id IS NOT NULL`), quitar check,
indice, clave y columna, y volver `topic_id` a `NOT NULL`; se pierden solo las piezas de hilo, que se
regeneran en el siguiente ciclo.

## Decision
`piece` gana `thread_id` (nullable, con clave foranea, indice y borrado en cascada) y `topic_id` pasa a
nullable con un check que exige uno de los dos; la pieza de un hilo se genera con el mismo control de
fundamento que la de un tema.

## Verificacion
Migracion 0011 aplicada y revertida sobre una base limpia (`tests/test_migrations.py`), tests del
escritor de piezas de hilo y de las paginas que las muestran, gauntlet `full` en VERDE.

## Alcance
- `alembic/versions/0011_pieza_de_hilo.py`
- `truthnews/models.py`
