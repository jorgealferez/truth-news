# ADR 0026 — El ultimo minuto es un carril rapido sin IA y una franja compacta en portada

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** ultimo minuto (peticion del usuario 2026-10-19)
- **Decide:** Constructor, auditado por el Critico

## Contexto
El usuario pide (2026-10-19) "monitorizar aun mas todos los temas de actualidad, el ultimo minuto, y
meter alguna forma de recalcar eso. Sin ser molesto y sin perder la esencia [...] comparativas [...] mas
hype para volver a entrar. No tener que esperar una hora para volver a ver algo", y que todo sea "mas
ameno, mas grafico y mucho mas ordenado", con menos scroll.

Medido en el codigo: el worker programaba el ciclo con `next_run_time=None`, que en APScheduler 3 deja
el trabajo **en pausa** (comprobado: `add_job(..., next_run_time=None).next_run_time is None`). En
produccion solo se rastreaba al arrancar el worker, es decir, en cada redespliegue; la portada parecia
fresca ("Ultima hora: 26 min" el 2026-10-19 01:21 UTC) solo porque los agentes despliegan a menudo.

## Decision
1. El ciclo completo (rastreo de todo el registro, contraste, IA, investigaciones, redes) se programa
   sin pausa cada `CRAWL_INTERVAL_MINUTES` (60).
2. Un **carril rapido** rastrea cada `BREAKING_INTERVAL_MINUTES` (10; 0 lo apaga) solo los medios
   nacionales del pais por defecto (agencias, diarios, radio y television: 40 medios en ES, medido con `registry.load_outlets()`) y pasa el
   contraste con datos; **sin IA ni redes**, asi que su coste es el de leer RSS. Nunca se solapa con el
   ciclo completo (un cerrojo: si el ciclo esta en marcha, la vuelta rapida se salta). Sus rastreos se
   marcan `stats.lane = "rapido"` y no cuentan como ciclo completo al redesplegar.
3. La portada abre con una franja **"Ultimo minuto"**: hasta 6 historias multimedio nacidas en las
   ultimas 6 h, la que mas se mueve primero, en una linea cada una (hora, titulo, medidor de cuantos
   medios la cuentan, `+N en la ultima hora`, "cifras en disputa", enlace a "El porque" si hay hilo).
   Cada linea lleva a la comparativa: la esencia no cambia, solo se ordena lo nuevo arriba.
4. Sin molestar: "Nuevo" y "N nuevas desde tu ultima visita" se calculan en el navegador
   (`localStorage`, sin cookies ni rastreo); la pagina abierta pregunta a `/ahora.json` cada 2 min y, si
   hay algo nuevo, muestra un boton "Hay novedades" que el lector pulsa si quiere. Nunca recarga sola,
   ni ventanas, ni notificaciones, ni sonido; el punto rojo late despacio y se para con
   `prefers-reduced-motion`. Sin JS la franja se ve igual.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Bajar el ciclo completo a 10 min | Multiplica por 6 el gasto de IA y la carga sobre 205 medios (locales incluidos) para ganar sobre todo en nacionales |
| Recarga automatica de la portada | Molesta: pierde la posicion de lectura; el usuario pidio "sin ser molesto" |
| Notificaciones push | Piden permiso y datos del lector; fuera de la esencia y del alcance de este cambio |
| Pagina aparte de ultimo minuto | Mas scroll y un clic mas; la franja compacta cabe en la portada |
| Rastrear todo el registro cada 10 min | Los locales publican poco; 10 min por medio local es carga sin retorno |

## Consecuencias
- Lo nuevo de los medios nacionales llega a portada en <= 10 min (mas lo que tarde su RSS), y el ciclo
  horario vuelve a ocurrir de verdad aunque nadie redespliegue.
- Coste: ~6 rastreos por hora de 40 medios con peticiones condicionales (ETag/Last-Modified) y el
  retraso por dominio de siempre; sin coste de IA. Las piezas, hilos y traducciones siguen al ritmo del
  ciclo completo.
- Pendiente: medir en produccion cuanto adelanta el carril rapido la llegada de historias (log del
  worker "ultimo minuto terminado") y cuantas historias nuevas entran por hora.

## Verificacion
`tests/test_cli.py::test_breaking_lane_crawls_national_outlets_and_never_overlaps` (solo nacionales,
marca del carril, no cuenta como ciclo completo, no se solapa, los dos trabajos programados y no en
pausa) y `tests/test_web.py::test_breaking_band_and_now_json` (franja, impulso, disputas, porque,
`/ahora.json`, ingles). Rendimiento: `tools/bench_web.py` (portada p95 con 10 000 articulos).
