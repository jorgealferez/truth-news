# Equipo de agentes de nosmienten.com

Direccion: sesion `session_012mRsejPRjvr7vC2Aq3edZ4` (prioriza, revisa, mide produccion y coordina).
Este documento es la referencia comun de todos los agentes que trabajan en `truth-news`. Las reglas del
loop (CLAUDE.md, gauntlet, ledger, ADR, carta) siguen intactas; esto solo reparte el trabajo.

## La esencia (no se negocia)

1. **Verificaciones primero.** Lo que nos distingue es comprobar afirmaciones contra datos oficiales y
   decir quien informa bien, quien se equivoca y quien engana, con la evidencia enlazada.
2. **Mascado para el publico.** Primero la conclusion en una frase y un grafico; el detalle, en
   desplegables. Movil primero.
3. **Sin bandos.** Mismo metodo y mismo formato para todos los medios, partidos y gobiernos. Sin
   calificativos. Nunca etiquetamos ideologias que no podemos medir.
4. **Todo citado.** Lo que no tiene fuente con fecha y enlace no se publica. La IA redacta y busca; los
   veredictos los decide el codigo con datos (ADR 0007).
5. **Ir mas alla de la noticia.** Contexto, antecedentes, quien dijo que y consecuencias (hilos).

## Referentes (tomamos lo mejor, sin perder la esencia)

| Referente | Lo que tomamos | Lo que no |
|---|---|---|
| Ground News | Reparto de la cobertura y "quien no lo cuenta" (puntos ciegos) | Etiquetas de ideologia por medio |
| AllSides | Titulares de cada medio lado a lado | Clasificacion izquierda/derecha |
| PolitiFact | Historial de veredictos por persona y por medio (ficha de fiabilidad) | Escala con humor |
| Maldita / Newtral | Veredicto claro arriba y explicacion corta, formato para redes | — |
| Full Fact | Seguimiento de afirmaciones que se repiten | — |
| Our World in Data | Graficos sobrios con la fuente debajo | — |

## Carriles

Cada carril tiene dueno. Fuera de su carril, un agente solo toca ficheros compartidos y con cambios
pequenos.

| Carril | Dueno | Ficheros principales |
|---|---|---|
| Verificaciones a escala | agente "Verificaciones" | `truthnews/analysis/claims.py`, `verify.py`, `truthnews/data/`, `registry/indicators.yaml`, `verifications.html`, extraccion con IA, datos politicos (Congreso, BOE, presupuestos) |
| Redes y autopublicacion | agente "Redes" | `truthnews/social/`, `truthnews/web/social.py`, `_share.html`, paso de redes del worker |
| Comparativas y fiabilidad por medio | agente "Comparativas" | `truthnews/analysis/compare.py`, `score.py`, ranking de `/medios` |
| Cobertura global e idiomas | agente "Global" | `truthnews/registry/sources/` (nuevos paises), `registry/countries.yaml`, traduccion de titulares, comparacion entre paises |
| Ficha de medio y noticia, textos es/en | sesion "Railway project" | `list.html`, `article.html`, `outlets.html`, `registry/i18n.yaml` (ingles) |
| Temas, SEO y sintesis | sesion "SEO y sintesis" | `topic.html`, `truthnews/ai/topics.py`, `writer.py`, metadatos y URLs |
| Entidades, archivo historico y grandes falsedades | sesion "Entidades" (`session_01Juk7hZcsWaeHLeGwUxFzuh`) | `truthnews/entities/`, `truthnews/archive.py`, `entity.html`, `entities.html`, `discrepancies.html`, `_discrepancias.html` |
| Hilos, worker, produccion | direccion | `truthnews/ai/threads.py`, `worker.py`, `config.py`, Railway |

Ficheros compartidos: `story.html`, `base.html`, `home.html`, `site.css`, `app.py`, `queries.py`,
`i18n.yaml`, `models.py`, el ledger y la carta. Reglas: cambios pequenos y localizados, `git fetch` y
rebase sobre `origin/main` justo antes de abrir el PR, nunca reformatear bloques ajenos, y si dos carriles
necesitan el mismo bloque, avisar a la direccion.

## Como se trabaja

- Reservar el item del ledger antes de empezar (`EN CURSO (<sesion>, <fecha>)`).
- Un PR pequeno por mejora, gauntlet `full` en VERDE, squash merge. Cada merge redespliega web y
  worker: como maximo un merge cada ~15 minutos por agente; agrupar cambios menores.
- Cambio de esquema: ADR `Tipo: datos` en el mismo PR (puerta `datos`).
- Credenciales: nunca en el chat ni en el repositorio; se piden al usuario para que las ponga en Railway.
- Al terminar un item, el siguiente de tu carril; si tu carril se vacia, avisar a la direccion.
