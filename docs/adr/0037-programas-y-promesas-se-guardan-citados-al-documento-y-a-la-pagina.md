# ADR 0037 — Programas y promesas se guardan citados al documento y a la pagina

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** 18 (18b)
- **Decide:** Constructor, auditado por el Critico

## Contexto

Peticion del usuario (2026-10-19, item "Elecciones" del ledger, criterio C15): importar los programas
electorales publicados, las promesas que los partidos hacen por el camino y las de los ultimos anos, y
analizar cuales cumplieron quienes gobernaron. La seccion de elecciones (ADR 0036) ya muestra el
calendario y las declaraciones de los canales oficiales (`political_statement`, ADR 0024) y su juicio
(`statement_check`, ADR 0031), pero no hay donde guardar un programa ni una promesa.

Medido el 2026-10-19 con el User-Agent del rastreador y respetando robots.txt: BNG
(`/estaticas/programas-eleitorais.html`, 33 PDF desde 2000), Coalicion Canaria
(`/programas-electorales/`, 24 PDF desde 2011) y Sumar (`/programa-electoral-23j/`, 1 PDF) enlazan sus
programas desde su web; PP los anuncia en su sitemap (547 URL con "programa", noticias); PSOE responde
212 bytes (pagina de comprobacion) y ERC, Podemos y Vox 403 (bloqueo tecnico, no se elude). Ningun
programa de las generales del 29-N esta publicado aun.

## Necesidad

Sin tablas no hay historia: un programa se descubre una vez y se analiza durante anos (las promesas de
2023 se comparan con el BOE de 2024-2026); las promesas tienen que sobrevivir a reinicios y servir de
ancla para el cumplimiento (18c) y las contradicciones (18d). Reutilizar `political_statement` no basta:
un programa no es una declaracion breve de un canal (su texto pasa de 600 caracteres a cientos de
paginas, y la cita va a una pagina del documento). Guardar las promesas como JSON dentro del programa
impediria enlazarlas a su cumplimiento y consultarlas por tema y partido.

## Escalabilidad

Programas: ~30 documentos por partido y pais en 25 anos (BNG 33, CC 24); 12 partidos de Espana ->
< 500 filas; texto extraido ~100-700 KB por programa (medido: Sumar 2023, 182 paginas y 697 000 caracteres; BNG 2023, 68 paginas y 118 000) -> < 500 MB
a 10 paises en 12 meses; se escribe una vez por documento nuevo (huella SHA-256). Promesas: el extractor
por reglas acota 1000 por programa -> < 500 000 filas a 10x; lecturas por (partido, eleccion) y por tema,
con indices `ix_promise_actor_election` y `ix_promise_topic`. Cumplimiento: una fila por promesa y
metodo, se reescribe al cambiar de metodo; mismo orden de magnitud que las promesas.

## Coherencia

Mismos nombres y tipos que el resto: `actor` String(40) y `country` String(2) como en
`political_statement`; `url_hash` unico como en `article`/`political_statement`; `extractor`
('reglas' | 'ia') como en `claim` (ADR 0019); `evidence` JSON [{source, label, url, period}] como en
`statement_check`. Integridad en la base: `program.url_hash` unico; `promise` pertenece a un programa o a
una declaracion, nunca a los dos ni a ninguno (CHECK); `promise` unica por (actor, `text_hash`);
`promise_check.status` con CHECK a la lista cerrada y unico por (promesa, metodo); claves foraneas con
`ON DELETE CASCADE`. La eleccion se guarda como `election_kind` + `election_year` (y el `election` del
calendario cuando se conoce): el calendario vive en memoria (ADR 0036) y un programa de 2011 no tiene
por que estar en el. En el codigo quedan: que es una promesa (verbo de compromiso en futuro), que se
importa solo lo que robots.txt permite y que solo se publica la cita con su pagina (ADR 0003).

## Alternativas consideradas

| Alternativa | Por que no |
|---|---|
| Promesas como JSON dentro de `program` | No se pueden enlazar a su cumplimiento (18c) ni consultar por tema entre partidos sin leer todos los documentos |
| Reutilizar `political_statement` con canal `programa` | Su texto esta acotado a 600 caracteres y su unicidad es por URL; un programa tiene cientos de promesas en la misma URL |
| Una sola tabla `promise` con el texto del programa repetido | Duplicaria cientos de KB por promesa |
| Guardar solo el enlace al programa, sin texto | Habria que volver a descargar el PDF en cada analisis; la huella SHA-256 tambien detecta cuando el partido cambia el documento |

## Necesidades futuras

Multi-pais: `country` en cada tabla y la eleccion por tipo y ano sirven para cualquier pais. Historico:
un programa cambiado en la web del partido entra como fila nueva (otra URL) o actualiza la huella y queda
la fecha; las promesas se conservan. Migracion al holding (ADR 0025): son tablas del dominio de contraste
(D3) con claves propias, sin dependencias nuevas fuera de `political_statement`. La extraccion con IA
(18b, segunda vuelta) usa la misma tabla con `extractor = 'ia'`.

## Migracion y reversibilidad

Un paso, solo `CREATE TABLE` e indices sobre tablas nuevas: sin bloqueo de tablas existentes ni relleno.
Compatible con el codigo en marcha durante el despliegue (nadie lee las tablas hasta el nuevo codigo).
Se revierte con `downgrade` (borra `promise_check`, `promise` y `program`); se pierden los programas
importados y sus promesas, que se recuperan volviendo a descubrirlos en sus webs.

## Decision

Tres tablas nuevas: `program` (documento de un partido para una eleccion, con URL, huella, texto si
robots.txt lo permite y estado), `promise` (cita literal de un compromiso con su pagina, tema y origen:
programa o declaracion) y `promise_check` (cumplimiento con estado cerrado, explicacion y evidencia
citada), en la migracion 0018.

## Verificacion

Migracion aplicada y revertida en SQLite y PostgreSQL 16 (`tests/test_migrations.py` y `alembic check`);
`tests/test_programs.py` ejerce el esquema; la puerta `datos` comprueba este ADR.

## Alcance

- `alembic/versions/0018_programas_y_promesas.py`
- `truthnews/models.py`
