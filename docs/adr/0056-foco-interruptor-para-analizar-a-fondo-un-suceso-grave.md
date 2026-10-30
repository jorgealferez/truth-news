# ADR 0056 — Foco: interruptor para analizar a fondo un suceso grave

- **Estado:** aceptado
- **Fecha:** 2026-10-29
- **Fase:** transversal (operacion), peticion del usuario
- **Decide:** sesion del accidente AVE-Iryo, a peticion del usuario ("forzar que ahora mismo todo lo que
  tenga que ver con eso se active y lo analice a fondo")

## Contexto
El 28/10/2026 un AVE de Renfe choco con un Iryo entre Urda y Los Yebenes (Toledo). Las cifras de victimas
cambian segun el medio y la hora, que es justo lo que este medio contrasta. Pero cada paso de IA elige
su trabajo por su cuenta y compite por el mismo cupo:

- **Piezas**: los temas con mas medios primero, `AI_MAX_PIECES_PER_CYCLE` (3 en produccion, decision del
  usuario del 19/10) y una pieza por tema cada `AI_PIECE_REFRESH_MINUTES` (120).
- **Hilos**: las 8 historias de cabecera, 2 por ciclo, uno por historia cada 12 h.
- **Afirmaciones con IA**: los articulos del ultimo rastreo, 3 llamadas por ciclo.
- **Investigaciones**: solo las que se piden a mano en `/admin`.
- Todo gasta del tope diario general (`AI_DAILY_BUDGET_USD`, 10 USD). Si se agota, se para todo.

Ante un suceso que evoluciona por horas, nada garantiza que se analice primero ni que se actualice a menudo.

## Decision
`AI_FOCUS` (terminos separados por comas, sin tildes ni mayusculas, palabra o expresion entera) enciende el
foco. Sin la variable no cambia nada; se apaga borrandola. Mientras esta puesto, en cada ciclo:

1. **Afirmaciones**: antes que las generales, la IA propone y juzga afirmaciones de los articulos del foco
   de las ultimas 72 h (`AI_FOCUS_CLAIMS_CALLS`, 4 llamadas).
2. **Hilos**: hilos de las historias del foco (`AI_FOCUS_MAX_THREADS`, 2) con su pieza, rehechos cada
   `AI_FOCUS_REFRESH_MINUTES` (30) en vez de cada 12 h.
3. **Piezas**: los temas del foco van antes que los demas, con su propio cupo (`AI_FOCUS_MAX_PIECES`, 3) y
   su cadencia (30 min). No restan plazas al cupo general. Si los temas no se pueden regenerar (p. ej. la
   bolsa general esta agotada), el foco escribe igual sobre los temas que ya existen.
4. **Investigacion**: con `AI_FOCUS_QUESTION`, la investigacion de esa pregunta se crea sola, se procesa
   antes que las demas y se reabre cada 30 min para que siga al suceso.
   Su informe se cine a las historias del foco (no a la busqueda por terminos, que en produccion mezclo
   la muerte de Fatima Banez y una protesta de tractores) y lleva su `dossier`: titular y resumen de cada
   medio y cifras en disputa por historia (las 10 primeras), sin indicadores por pais, que no aplican.
5. **Coste**: todo lo anterior va a una bolsa diaria propia, `AI_FOCUS_BUDGET_USD` (15 USD). Agotar la
   general no para el foco, y el foco no gasta de la general. Con 0 gasta de la general. El ciclo apunta
   `foco_usd` y `hoy_foco_usd` en `ai_cost`.

Las reglas de fundamento no cambian: toda cifra de una pieza, hilo o investigacion debe estar en su
dossier, o la pieza va a revision (ADR 0007). El foco da prioridad y frecuencia, no relaja el rigor.

## Alternativas descartadas
- **Subir el tope general y el cupo de piezas**: gastaria en todos los temas, no en el suceso, y no
  garantiza el orden.
- **Investigacion a mano en `/admin`**: necesita la contrasena del panel, no se actualiza sola y no toca
  piezas, hilos ni afirmaciones.
- **Foco en la base de datos con un boton en `/admin`**: necesita una migracion. La variable de Railway
  se pone y se quita en segundos, y redesplegar lanza el ciclo al momento.

## Consecuencias
- Coste maximo extra: `AI_FOCUS_BUDGET_USD` al dia, visible por ciclo en `ai_cost`.
- Un termino demasiado comun (p. ej. "ave" sola, que tambien es un animal) mete historias que no son del
  suceso. Hay que elegir terminos especificos (`iryo`, `adif`, `los yebenes`).
- Sin cambios en la capa de datos.
