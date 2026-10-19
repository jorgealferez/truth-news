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
| Publicidad (solo cliente de `ads-service`) | sesion `nosmienten:publicidad` | `truthnews/ads.py`, `_ad.html`, `advertising.html`, `static/ads.js`, estilos `.ad*` de `site.css`; la plataforma (anunciantes, campanas, subasta, medicion) vive en microservices-ecosystem (squad publicidad): aqui nada de tablas ni migraciones |
| Entidades, archivo historico y grandes falsedades | sesion "Entidades" (`session_01Juk7hZcsWaeHLeGwUxFzuh`) | `truthnews/entities/`, `truthnews/archive.py`, `entity.html`, `entities.html`, `discrepancies.html`, `_discrepancias.html` |
| Hilos, worker, produccion | direccion | `truthnews/ai/threads.py`, `worker.py`, `config.py`, Railway |
| Elecciones (ADR 0036/0037) | sesion `session_01RNYgqswu6mxYxkFCMnBbiD` | `truthnews/elections/`, `registry/elections.yaml`, `elections.html`, `election.html`, `promises.html`, `_promise_cite.html`, paso `programas` del worker; reutiliza `political_statement` y `statement_check` (Datos politicos) sin duplicar el juez |
| Migracion al holding (ADR 0025) | sesion `session_01DgF9WootYzqTr7jwzkbDSj` | `docs/migracion-holding.md`, `truthnews/ports/`, `truthnews/holding/`; la parte del holding (BFF, `newsroom-service`, ampliaciones) vive en microservices-ecosystem (squad nosmienten). Arranca cuando cierren los items en curso |

Ficheros compartidos: `story.html`, `base.html`, `home.html`, `site.css`, `app.py`, `queries.py`,
`i18n.yaml`, `models.py`, el ledger y la carta. Reglas: cambios pequenos y localizados, `git fetch` y
rebase sobre `origin/main` justo antes de abrir el PR, nunca reformatear bloques ajenos, y si dos carriles
necesitan el mismo bloque, avisar a la direccion.

## Registro de numeros (ADR y migraciones)

Para no chocar, los numeros se reservan **antes** de usarlos pidiendolos a la direccion
(`send_message` a `session_012mRsejPRjvr7vC2Aq3edZ4`), que actualiza esta tabla. Si al hacer rebase el
numero ya esta en `main`, se renumera y se reengancha `down_revision` al head de `main` (nunca dos heads;
ida y vuelta y `alembic check` antes del PR).

| Numero | Tipo | Estado | Carril |
|---|---|---|---|
| ADR 0016 | diseno | en main | Comparativas (mismo hecho) |
| ADR 0017 + migracion 0009 | datos | en main | Global (traducciones) |
| ADR 0018 + migracion 0008 | datos | en main | Redes (cola de publicaciones) |
| ADR 0019 + migracion 0010 | datos | en main | Verificaciones (afirmaciones extraidas por IA) |
| ADR 0020 + migracion 0011 | datos | en main | Temas, SEO y sintesis (pieza por hilo) |
| ADR 0021 | diseno | en main | Comparativas (fiabilidad por medio; sin migracion) |
| ADR 0022 + migracion 0013 | datos | en main | Global (cobertura exterior) |
| ADR 0023 | — | libre | (no usar: se libero; los numeros nuevos siguen hacia arriba) |
| migracion 0012 | — | libre | (no usar: se libero; las migraciones nuevas siguen hacia arriba) |
| ADR 0024 + migracion 0014 | datos | en main | Global (fuentes politicas) |
| ADR 0025 | diseno | en main | Migracion al holding (plan) |
| ADR 0026 | diseno | en main | Ultimo minuto |
| ADR 0027 | diseno | en main | Entidades (lo que no cuadra) |
| ADR 0028 + migracion 0015 | datos | en main | Entidades (entidades, menciones, hablante y archivo) |
| ADR 0029 | diseno | en main | Comparativas / Verificaciones (consulta puntual de interes publico) |
| ADR 0030 | diseno | en main | Entidades (archivo desde los ficheros GKG de GDELT) |
| ADR 0031 + migracion 0016 | datos | en main | Datos politicos (declaraciones juzgadas, `statement_check`) |
| ADR 0032 | diseno | en main | Comparativas (quien cambio su cifra; sin migracion) |
| ADR 0033 + migracion 0017 | datos | PR #125 | Redes (cuentas en ingles: x_en, bluesky_en, mastodon_en, telegram_en) |
| ADR 0034 | diseno | en main | Temas, SEO y sintesis (sitemaps: indice, 1000 URLs por fichero, Google News) |
| ADR 0035 | diseno | en main | Comparativas (afirmaciones que se repiten; sin migracion) |
| ADR 0036 | diseno | PR #139 | Elecciones (seccion temporal, calendario: BOE, JEC, IFES y medios; candidaturas; sin migracion) |
| ADR 0037 + migracion 0018 | datos | PR #139 | Elecciones (program, promise, promise_check) |
| ADR 0038 | diseno | PR (este) | Temas, SEO y sintesis (datos estructurados: ClaimReview, NewsArticle, BreadcrumbList; sin migracion) |
| ADR 0039 | diseno | en main | Cumplimiento (aviso legal, privacidad, cookies, transparencia; sin migracion) |
| ADR 0040 | diseno | reservado | Elecciones (cumplimiento de promesas de quien goberno; 18c BLOQUEADO por decision del usuario, ledger) |
| ADR 0041 | diseno | en main | Comparativas (quien informa primero y bien; #159) |
| ADR 0042 | diseno | reservado | Contratacion y transparencia (/contratos: BOE V.A y TED; sin migracion) |
| ADR 0043 | diseno | PR #138 | Redes (equilibrio de lo que se publica) |
| ADR 0044 + migracion 0019 | datos | reservado | Global (indicadores Eurostat y Banco Mundial, solo si necesita esquema) |
| ADR 0045 | diseno | PR #151 | Rastreo (piezas publicitarias de los medios; sin migracion) |
| ADR 0046 | diseno | en main | Temas, SEO y sintesis (objetivos tactiles de 44 px en movil; sin migracion) |
| ADR 0047 | diseno | PR #174 | Redes (Hoy en 1 minuto) |
| ADR 0048 + migracion 0020 | datos | reservado | Redes (pieza diaria de Hoy en 1 minuto: kind `hoy` en `social_post`) |
| ADR 0049 + migracion 0021 | datos | PR #183 | Verificaciones (retirar un veredicto a mano, registro en `admin_action`; pedido por la direccion) |
| ADR 0050 | diseno | PR (este) | Entidades (graficos SVG de entidad e historia; asignado por la direccion) |
| siguiente libre | — | — | ADR 0051 + migracion 0022; pedir a la direccion. Cabeza de alembic en main: ver `alembic heads` |

## Como se trabaja

- Reservar el item del ledger antes de empezar (`EN CURSO (<sesion>, <fecha>)`).
- Un PR pequeno por mejora, gauntlet `full` en VERDE, squash merge. Como maximo un merge cada ~15
  minutos por agente; agrupar cambios menores.
- **Ventana de merges de codigo del worker.** El worker solo se redespliega si cambia `truthnews/**`
  (salvo plantillas y estaticos), `alembic/**`, `pyproject.toml`, `Dockerfile` o `railway.json` (watch
  paths en Railway). Un ciclo completo dura ~25 min y un redespliegue lo corta. Por eso esos merges se
  hacen **solo en las horas pares, entre HH:00 y HH:10 UTC** (00:00, 02:00, 04:00…; el despliegue tarda ~10 min mas): asi
  caben ciclos completos cada 30 min en las dos horas entre ventanas (criterio C11); documentacion, ledger, plantillas y estaticos, a cualquier hora.
  Urgencias de produccion (un fallo que tumba el ciclo), fuera de ventana avisando a la direccion.
- Cambio de esquema: ADR `Tipo: datos` en el mismo PR (puerta `datos`).
- Credenciales: nunca en el chat ni en el repositorio; se piden al usuario para que las ponga en Railway.
- Al terminar un item, el siguiente de tu carril; si tu carril se vacia, avisar a la direccion.
