# ADR 0036 — Las elecciones se detectan solas y su seccion solo existe mientras estan en ventana

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** 18 (18a)
- **Decide:** Constructor, auditado por el Critico

## Contexto

El usuario pide (2026-10-19) un apartado **temporal** de elecciones, para cualquier pais, comunidad,
provincia o municipio, empezando por Espana, que se informe **automaticamente** de cuando las hay y que
reuna lo que dicen y prometen los partidos, sus programas, lo que cumplieron quienes gobernaron y sus
contradicciones. Las primeras convocadas son las generales del 29 de noviembre de 2026 (Real Decreto
806/2026, BOE-A-2026-20742, comprobado en el sumario y en el texto del decreto).

Restricciones: la API de Wikidata esta vetada a nuestro User-Agent por su robots.txt (ADR 0024); todo
dato publicado lleva fuente; mismo formato para todos los partidos (docs/equipo.md); las paginas de
elecciones no llevan publicidad (ads.py); los numeros de esquema se reservan (ADR 0037 + migracion 0018
para programas y promesas, 18b).

## Decision

Un calendario en memoria (`truthnews/elections/calendar.py`), sin tablas, une tres fuentes por orden de
autoridad: (1) los decretos de convocatoria del **BOE**, leidos de cada sumario diario y de su texto
(fecha de votacion, campana, sesion constitutiva), (2) el registro `registry/elections.yaml`, con lo
comprobado a mano y los enlaces a los programas, y (3) los **medios rastreados**, solo cuando al menos dos
medios distintos situan unas elecciones en el mismo pais y la misma fecha; estas se marcan "anunciada en
medios" con sus titulares citados y ceden ante una convocatoria oficial del mismo dia.

Una eleccion esta en ventana desde su convocatoria hasta 30 dias despues de votar. Solo entonces hay
enlace en la cabecera; `/elecciones` existe siempre y dice si no hay ninguna. La pagina de cada eleccion
(`/elecciones/{pais}-{tipo}-{territorio}-{fecha}`) muestra el calendario oficial citado, los partidos del
registro politico por igual (declaraciones de sus canales oficiales desde la convocatoria, afirmaciones
comprobadas con el juez de siempre, programa enlazado o "no localizado aun") y la cobertura de los medios.

## Alternativas consideradas

| Alternativa | Por que no |
|---|---|
| Wikidata o Wikipedia como calendario mundial | La API de Wikidata esta prohibida a nuestro User-Agent por robots.txt; Wikipedia no es fuente oficial y su "proximas elecciones" se edita a mano |
| Tabla `election` desde el primer PR | El calendario se reconstruye del BOE en ~2 min y cabe en memoria; la tabla llega con programas y promesas (18b, ADR 0037), que si necesitan historia |
| Seccion fija con elecciones a mano | El usuario pide que se adapte sola; una lista a mano caduca |
| Detectar elecciones por un solo medio | Un titular aislado ("elecciones en marzo") no basta para abrir una seccion: dos medios distintos o fuente oficial |

## Consecuencias

- La seccion aparece sola con cada convocatoria del BOE (generales, autonomicas, locales parciales,
  europeas) y con las elecciones extranjeras que los medios del registro citan con fecha; desaparece sola.
- El primer barrido de 75 dias de BOE tarda ~2 min en segundo plano por proceso web; despues se refrescan
  los ultimos dias cada 30 min. Si el BOE falla, queda el registro.
- Pendiente: programas y promesas con su tabla (18b, ADR 0037 + migracion 0018), cumplimiento de lo
  prometido (18c), contradicciones y cambios con fecha (18d), boletines autonomicos, candidaturas
  proclamadas y diarios oficiales de otros paises (18e).

## Verificacion

`tests/test_elections.py` con el sumario y el decreto reales; `tools/measure_elecciones.py` y
`docs/benchmarks/fase_18a.json` (0 convocatorias perdidas, 0 falsos positivos, barrido < 300 s) bajo
la puerta `ratchet`.
