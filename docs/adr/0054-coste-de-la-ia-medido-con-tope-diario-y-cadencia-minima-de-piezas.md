# ADR 0054 — Coste de la IA medido, con tope diario y cadencia minima de piezas

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** transversal (coste de operacion), peticion del usuario
- **Decide:** sesion de coste de IA, a peticion del usuario ("controlar el coste sin perder calidad")

## Contexto
El 2026-10-19 la API de Anthropic se quedo sin credito a las 11:07 UTC, tras unos 40 USD gastados en pocas
horas. Los logs del worker ("ciclo terminado", ciclos 89 a 108, de 06:35 a 10:37 UTC) muestran:

- **Piezas**: `pieces_written: 6` en **todos** los ciclos medidos, con Opus 5.5 y esfuerzo alto, y entre
  760 y 910 s por paso `ai`. La huella del dossier (`input_hash`, ADR 0007) no evita nada en la practica:
  incluye hora, resumen y arranque de cada articulo, asi que un articulo nuevo en el tema la cambia. Con
  ciclos cada 30 min son hasta 288 piezas al dia, casi todas reescrituras de los mismos temas de cabecera.
- **Hilos**: 1 o 2 por ciclo (3 llamadas Opus con esfuerzo alto cada uno), ya limitados a uno cada 12 h por
  historia.
- **Temas** (~10 000 tokens de entrada y ~1 500 de salida) y **afirmaciones** (~2 500 y ~1 500) son baratos.
- **Traducciones**: siempre al tope (120 + 60 titulares por ciclo), con esfuerzo bajo.
- Solo los temas y las afirmaciones apuntan su consumo en el log; el de las piezas, los hilos y las
  traducciones no se ve en ningun sitio, y no hay manera de saber lo que cuesta un ciclo ni un dia.

Linea base completa (18 ciclos del 18 y 19/10, 9 con IA) en `docs/benchmarks/fase_ia1.json`: 54 piezas en 9
ciclos (6 en cada uno), 14 hilos, 120 + 60 traducciones por ciclo; temas y afirmaciones suman 1,05 USD en
esos 9 ciclos, asi que casi todo el gasto es de piezas, hilos y traducciones, cuyo uso solo esta en la base
(`Piece.usage`, `Thread.usage`).

## Decision
1. **Coste medido** (`truthnews/ai/cost.py`): cada llamada apunta su coste con los precios por millon de
   tokens del modelo que respondio (entrada, salida, que incluye el pensamiento, lectura y escritura de
   cache). Se cobra tambien la respuesta que luego no se usa (rechazo, truncada, JSON invalido), porque se
   paga. Un modelo sin precio en la tabla (p. ej. el de respaldo ante un rechazo) se cuenta al mas caro.
   El ciclo guarda en `CrawlRun.stats["ai_cost"]` el total, las llamadas, el reparto por modelo y por paso
   (como `seconds`) y lo gastado en el dia; sale tambien en el log "ciclo terminado".
2. **Tope diario** `AI_DAILY_BUDGET_USD` (0 = sin tope), por dia UTC. **Los 40 USD por omision son una
   suposicion** (lo gastado el 2026-10-19 antes del corte, en unas 11 h), no una decision: la cifra la
   decide el usuario y se cambia en Railway sin tocar el codigo. Lo gastado hoy es la
   suma de `ai_cost.usd` de los ciclos guardados desde las 00:00 UTC. Pasado el tope, `AIClient` no llama y
   lanza `AIError`: cada paso de IA ya esta guardado (#200) y el ciclo sigue sin IA (rastreo, analisis,
   entidades, archivo y redes), como cuando no hay credito, pero sin errores de la API. El orden de los
   pasos del ciclo fija la prioridad: afirmaciones, hilos, temas y piezas, investigaciones. El ciclo llega
   al final con la marca "terminado" (test `test_daily_budget_skips_ai_and_the_cycle_still_finishes`).
3. **Cadencia minima de piezas** `AI_PIECE_REFRESH_MINUTES` (120 por omision; 0 = como antes): un tema con
   una pieza de hace menos de ese tiempo cede su plaza en el ciclo al siguiente tema, aunque su dossier haya
   cambiado. Un tema sin pieza se escribe en el primer ciclo, como antes. La huella del dossier se mantiene:
   pasado el plazo, un tema que no ha cambiado sigue sin reescribirse.

## Calidad
Ninguna pieza se escribe con menos: mismo modelo (Opus 5.5), mismo esfuerzo, mismo dossier y mismas
comprobaciones de citas. Lo que cambia es la frescura: el analisis de un tema que ya lo tiene se actualiza
como mucho cada 2 h en vez de cada 30 min. Las plazas que deja libres un tema reciente pasan a temas que aun
no tienen pieza, asi que la cobertura de temas no baja. No se cambia de modelo ni se baja el esfuerzo en
ningun paso: eso cambia la calidad y es una decision del usuario, que se le plantea con los numeros que
esta medida produzca.

## Alternativas descartadas
- **Bajar a Sonnet o Haiku las traducciones, las afirmaciones o los temas**: abarata, pero cambia la
  calidad del juez y de los textos; se decide con medidas de calidad, no a ciegas.
- **API de lotes (50 % mas barata)**: las respuestas pueden tardar horas y el ciclo publica cada 30 min
  (criterio C11); se puede estudiar para las traducciones cuando haya medidas.
- **Cache de 1 h para los prompts de sistema**: los prompts de sistema son cortos (~800-1 700 tokens); el
  ahorro de leerlos de cache es pequeno frente al de no repetir piezas.
- **Huella "material" del dossier** (solo historias, medios y afirmaciones): exige guardar otra huella por
  pieza (migracion); la cadencia minima consigue el ahorro sin tocar el esquema.

## Consecuencias
- Hasta 288 piezas al dia pasan a, como mucho, 12 al dia por tema (una cada 2 h). Con los 10-12 temas
  activos medidos, el techo baja a la mitad y lo normal sera bastante menos, porque no todos los temas
  cambian. El ahorro real se mide con `ai_cost` en produccion cuando vuelva el credito: **NO VERIFICADO**
  hasta entonces (la API responde "credit balance too low" desde las 11:07 UTC).
- Un ciclo cortado por un redespliegue antes de guardar sus estadisticas no suma su gasto al del dia: el
  tope puede quedarse algo corto, pero nunca bloquea de mas.
- Ningun cambio de esquema: `ai_cost` va en el JSON `stats` que ya existe.

## Decision del usuario (2026-10-19 15:07 UTC)
Con el primer ciclo medido tras el despliegue (run 138: 2,48 USD en 17 llamadas Opus; ai 2,03, threads 0,43,
ai_claims 0,02; unos 119 USD/dia a 48 ciclos), el usuario fija en el worker de produccion:
- `AI_DAILY_BUDGET_USD=10` (sustituye a la suposicion de 40);
- `AI_MAX_PIECES_PER_CYCLE=3`: analisis solo para los ~6 temas de cabecera (candidatos = 2 x 3), cada uno
  como mucho cada 2 h; los temas 7 en adelante se quedan sin analisis.
Rechaza por ahora traducir con un modelo mas barato y limitar los hilos. Las verificaciones no se tocan.
