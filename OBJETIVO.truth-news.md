# OBJETIVO — carta de meta de truth-news

estado: en-curso
alcance: microservices-ecosystem

Esta carta dice **de donde parte** el repositorio `truth-news` y **a donde tiene que llegar**. Es la
referencia contra la que se mide todo el trabajo y la razon por la que el agente no para hasta
`estado: alcanzado`. Una carta por repositorio, nombrada por repositorio; lo que pertenezca a otro
repositorio va en su `OBJETIVO.<otro>.md`.

Estados: `sin-encuadrar` (recien instalada: la primera tarea es el encuadre) · `en-curso` ·
`alcanzado` (solo con todos los criterios medidos) · `pausado` (solo lo escribe una persona).

Reglas: los criterios se escriben con su medida (`— medida: <como se mide> — objetivo: <valor>`); las
fases van en orden, una fase = un pull request con squash merge; se pueden anadir fases al final,
nunca renumerar; una fase se marca `[x]` con la referencia de su PR o commit; un criterio que este
entorno no puede medir se anota `NO VERIFICADO (<motivo>)` y sigue pendiente; uno que el usuario saca
del alcance se anota `FUERA DE ALCANCE por decision del usuario (<fecha>)` y deja de contar. Las
suposiciones se escriben aqui, no se preguntan.

## Inicio

- Commit de partida: `06c3ab1` ("Initial commit"), 2026-10-18. Contenido: `README.md` (2 lineas:
  "Periódico que compara todo y da la verdad") y `LICENSE` (CC0 1.0). 0 lineas de codigo, 0 tests,
  0 CI, 0 despliegues.
- Toolchains detectados por `loop-init`: ninguno. Entorno disponible: Python 3.13, red de salida con
  proxy (medido: `feeds.elpais.com` 200, `servicios.ine.es` 200, `api.worldbank.org` 200, `pypi.org` 200).
- Infraestructura disponible: Railway (cuenta `jorgealferez`, 22 proyectos, ninguno de este producto),
  GitHub (`jorgealferez/truth-news`, rama `main`). MCP del holding con servicios `crawler`,
  `publicdata`, `social`, `knowledge`, `translation`, `ai`, `search` (credencial
  `HOLDING_PLATFORM_API_KEY`: **missing**, medido con `holding_estado`).
- Peticion del usuario (2026-10-18), resumida: medio digital tipo periodico generalista, en castellano
  primero y adaptable a cualquier idioma y pais, que **rastree automaticamente** medios publicos
  (locales, regionales, nacionales; empezando por Espana), **contraste** cada noticia con datos reales y
  entre medios (mentiras, omisiones, contexto que falta), analice politicas y grandes cuestiones
  (disturbios en Europa, influencia geopolitica), segmente por categorias, paises y temas, tenga
  **panel de administracion con balance**, permita **investigaciones a demanda**, genere contenido de
  forma automatica, este preparado para **redes sociales**, sea **riguroso** y se despliegue en
  **Railway** funcionando desde el primer minuto.

## Meta

El proyecto esta terminado cuando `truth-news` es un periodico de verificacion desplegado en Railway
que, sin intervencion humana, rastrea cada hora un registro amplio de medios espanoles (nacionales,
autonomicos y locales) respetando `robots.txt`, agrupa la misma noticia contada por distintos medios,
extrae las afirmaciones comprobables, las contrasta con fuentes de datos oficiales y abiertas (INE,
Eurostat, Banco Mundial, BOE, GDELT y las que se anadan) y publica piezas de verificacion con veredicto,
evidencia enlazada y comparativa de que dijo y que omitio cada medio; que se navega por categoria, pais,
comunidad, tema y medio; que tiene panel de administracion con el balance de la operacion (ingesta,
verificaciones, veredictos, fiabilidad por medio, cola de revision), investigaciones a demanda sobre
cualquier pregunta, piezas listas para redes sociales y publicacion automatica donde haya credenciales;
y cuya arquitectura (registro de medios por pais, idioma y conectores de datos por pais) permite anadir
otro pais o idioma con datos, sin tocar codigo.

Suposicion revisable: "verdad absoluta" se implementa como **veredicto trazable**: cada veredicto
enlaza su evidencia, declara su confianza y cae en "sin datos suficientes" cuando la evidencia no
alcanza; el sistema nunca afirma sin fuente.

## Criterios de salida

- [x] C1 Registro de medios — medida: `python -m truthnews sources stats` — objetivo: >= 80 medios de Espana, con los tres ambitos (nacional, autonomico, local) y las 17 comunidades autonomas cubiertas
- [x] C2 Ingesta real — medida: una ejecucion de `python -m truthnews crawl` contra la red real — objetivo: >= 30 feeds con respuesta valida y >= 300 articulos ingeridos, 0 URLs prohibidas por robots.txt descargadas
- [ ] C3 Calidad del codigo — medida: `pytest --cov` y `ruff check` — objetivo: 100 % tests en verde, cobertura >= 80 %, 0 avisos de ruff
- [x] C4 Agrupacion entre medios — medida: precision y exhaustividad sobre el conjunto etiquetado `tests/fixtures/clusters.json` — objetivo: F1 >= 0.80
- [x] C5 Contraste con datos reales — medida: conectores con test de contrato (fixture) y una consulta en vivo — objetivo: >= 5 fuentes de datos (INE, Eurostat, Banco Mundial, BOE, GDELT) respondiendo en vivo
- [ ] C6 Rigor — medida: invariante comprobada por test y por consulta a la base — objetivo: 100 % de las verificaciones publicadas con >= 1 evidencia con URL y confianza; 0 veredictos sin evidencia fuera de "sin datos suficientes"
- [x] C7 Rendimiento web — medida: benchmark local de la portada con 10 000 articulos — objetivo: p95 < 300 ms
- [x] C8 Administracion — medida: tests de integracion del panel — objetivo: balance (ingesta, verificaciones, veredictos, fiabilidad por medio), cola de revision y alta de investigaciones operativos y protegidos por credencial
- [x] C9 Redes sociales — medida: tests de los generadores y adaptadores — objetivo: cada verificacion publicada genera piezas para >= 4 redes (X, Bluesky, Mastodon, Telegram) dentro de sus limites; publicacion real NO VERIFICADO hasta tener credenciales (medido 2026-10-19, docs/benchmarks/fase_4.json: tests/test_social.py en verde para las 4 redes; publicacion real NO VERIFICADO sin credenciales)
- [x] C10 Multi-pais y multi-idioma — medida: tests — objetivo: interfaz en >= 2 idiomas (es, en) y >= 2 paises en el registro, anadidos solo con datos (medido 2026-10-19, docs/benchmarks/fase_4.json: es y en con 345 cadenas cada uno, ?lang=en en produccion; 21 paises en el registro)
- [ ] C12 Temas y sintesis — medida: tests y consulta a produccion — objetivo: cada tema con >= 3 medios publica coincidencias, diferencias y valoracion con datos; >= 80 % de los temas del dia con >= 3 medios tienen pieza propia
- [ ] C13 Analisis propio con IA — medida: piezas publicadas con su metodo — objetivo: cada pieza propia enlaza >= 5 paginas internas y todas sus fuentes, se marca como elaborada con IA y no afirma nada que no este en la evidencia; NO VERIFICADO hasta tener clave de IA
- [ ] C11 Despliegue — medida: `curl` a la URL publica de Railway y logs del worker — objetivo: `/healthz` 200, web y worker en marcha, ingesta automatica registrada en produccion
- [ ] C14 Migracion al holding — medida: conciliacion por tabla local/holding (`docs/benchmarks/fase_1N.json`) y monitor de disponibilidad durante cada corte — objetivo: los dominios D1 a D7 de `docs/migracion-holding.md` servidos por el BFF y los servicios del holding, 0 filas perdidas (diferencia 0 y huellas iguales), 0 minutos de caida atribuibles a la migracion, p95 de portada < 300 ms (C7 es suelo) y truth-news sin `DATABASE_URL` propio (ADR 0025)
- [ ] C15 Elecciones — medida: tests del detector y consulta a produccion — objetivo: toda eleccion convocada en el BOE aparece en /elecciones en <= 1 ciclo del worker con fecha, campana y cita al decreto; cada partido con escano tiene ficha simetrica (declaraciones, programa con enlace o "no publicado", promesas citadas); 0 promesas sin cita a su fuente; la seccion no se muestra sin elecciones en ventana

## Fases

- [x] Fase 0 — Encuadre: esta carta rellena desde la base real, ledger sembrado, primer gauntlet en VERDE (#1)
- [x] Fase 1 — Nucleo: modelo de datos, registro de medios de Espana, crawler RSS con robots.txt, web publica segmentada, configuracion de Railway (acerca C1, C2, C3, C7, C10) (#2)
- [x] Fase 1a — Despliegue temprano en Railway: Postgres, web y worker rastreando en produccion desde el primer minuto, por la urgencia pedida por el usuario (acerca C2, C11) (#3)
- [x] Fase 2 — Motor de contraste: agrupacion entre medios, extraccion de afirmaciones, conectores de datos reales, veredictos con evidencia, comparativa de cobertura y omisiones, fiabilidad por medio (acerca C4, C5, C6) (#4)
- [x] Fase 2b — Temas, sintesis y analisis propio: agrupacion por tema (articulos relacionados con distinto enfoque), sintesis por medio (que dice cada uno, en que coinciden, en que difieren), valoracion con todos los datos, piezas propias de analisis y opinion como seccion principal generadas con IA y con enlazado interno; la portada pasa a ser "como cuentan los medios cada tema" (peticion del usuario 2026-10-18; acerca C6, C12, C13) (#6; generacion real NO VERIFICADO sin ANTHROPIC_API_KEY)
- [x] Fase 3 — Administracion e investigaciones: panel con balance, cola de revision, gestion de fuentes, investigaciones a demanda (acerca C8) (#8; gestion de fuentes desde el panel queda pendiente)
- [x] Fase 4 — Distribucion: generadores y adaptadores de redes sociales, RSS, sitemap y SEO, interfaz en ingles (acerca C9, C10) (#12, #33, #38, #68, #75, #76 y este PR; docs/benchmarks/fase_4.json; publicacion real en redes NO VERIFICADO sin credenciales)
- [ ] Fase 5 — Despliegue en Railway: Postgres, web, worker programado, medido en produccion (acerca C2, C11)
- [x] Fase 6 — Marca nosmienten.com: identidad sobria y neutral (logotipo, favicon, imagen social, cabecera), dominio propio en Railway (peticion del usuario 2026-10-18; acerca C9, C11) (#9; www pendiente de DNS)
- [x] Fase 7 — Prioridad a lo que difiere: puntuacion de contraste por historia que ordena portada y contrastes, y relanzamiento de historias antiguas con datos nuevos y tendencia (peticion del usuario 2026-10-18; acerca C6, C12) (#10)
- [x] Fase 8 — Navegacion movil y escritorio: cabecera compacta, menu accesible, historias legibles en movil, enlaces entre historias, medios y temas (peticion del usuario 2026-10-18) (#11)
- [ ] Fase 9 — Quien miente, quien informa, quien dice la verdad: fiabilidad por medio con historial de veredictos, ranking por exactitud comprobada, comparativas lado a lado y "la verdad segun los datos" cuando la hay (peticion del usuario 2026-10-18; acerca C6, C12)
- [ ] Fase 10 — Hilo y consecuencias: archivo historico cruzado con la actualidad, linea temporal por tema, conexiones entre hechos con evidencia y analisis profundo con IA; portada con el porque y el antes/despues de lo que ocurre (peticion del usuario 2026-10-19; acerca C12, C13)
- [x] Fase 11 — Migracion al holding (plan): ADR 0025, `docs/migracion-holding.md`, items cruzados en ambos ledgers, alcance de la carta (peticion del usuario 2026-10-19; acerca C14) (#47)
- [ ] Fase 12 — Puertos de datos: `truthnews/ports/` con adaptador SQL identico y cliente del BFF del holding, banderas `DATA_BACKEND_*` a `local` (acerca C14)
- [ ] Fase 13 — Registro e ingesta en el holding: doble escritura, outbox, backfill idempotente, conciliacion, sombra y corte de D1 y D2 (acerca C14)
- [ ] Fase 14 — Contraste en el holding: D3 con la invariante C6 medida en `newsroom-service` (acerca C6, C14)
- [ ] Fase 15 — IA, traduccion y redes por servicios del holding: D4 y D5 (acerca C9, C13, C14)
- [ ] Fase 16 — Busqueda y admin con OIDC del holding: D6 y D7 (acerca C8, C14)
- [ ] Fase 17 — Retirada del Postgres propio: 7 dias limpios, volcado final archivado con huella; truth-news queda como frontend con su logica (acerca C14)
- [ ] Fase 18 — Elecciones: seccion temporal que se activa sola con comicios convocados en cualquier pais y ambito (Espana primero: generales del 29-N de 2026, RD 806/2026), con calendario desde fuentes oficiales, que dicen y prometen los partidos por igual, programas importados, promesas pasadas frente a hechos, contradicciones y cambios con fecha (peticion del usuario 2026-10-19; acerca C6, C12, C15)

## Calidad y proyeccion

Liston que no se negocia: gauntlet `full` en VERDE antes de cada PR; un ADR por decision de diseño en
`docs/adr/`; un benchmark medido por fase en `docs/benchmarks/fase_N.json` con sus numeros dentro del
presupuesto (`presupuesto.json`); Ratchet: un numero medido es suelo minimo para las fases
siguientes; nada de fases de relleno: cada fase acerca un criterio de salida y lo dice.

Liston editorial: se guarda del articulo ajeno lo necesario para analizarlo y se publica solo titular,
enlace, cita breve y analisis propio (derecho de cita); todo contenido generado por IA se marca como
tal; el crawler se identifica con su User-Agent y respeta `robots.txt` y un ritmo por dominio.

Fuentes que el entorno no puede medir: votaciones y actividad del Congreso y del Senado, NO VERIFICADO
(2026-10-19: sus servidores responden 403 a nuestro User-Agent identificado y no se elude; solicitud de
acceso en `docs/solicitud-datos-abiertos-cortes.md`, la envia el usuario).

## Decisiones del usuario

- 2026-10-18 (peticion): empezar por Espana, castellano primero, todos los temas, despliegue en Railway,
  maxima automatizacion, rigor.
- 2026-10-18 (suposicion revisable): stack Python 3.12 + FastAPI + SQLAlchemy + PostgreSQL; LLM de
  Anthropic (`ANTHROPIC_API_KEY`) con modo heuristico sin clave; los servicios del holding se integran
  como adaptadores opcionales mientras falte `HOLDING_PLATFORM_API_KEY`.
- 2026-10-18 (peticion): el producto es un **comparador** de noticias, no un agregador: contrastar entre medios y con datos globales y dar una valoracion; tema visual claro.
- 2026-10-18 (peticion): valorar el dominio nosmienten.com para una marca solida, profesional, neutral y creible.
- 2026-10-18 (peticion): temas que reunen articulos de distinto enfoque, sintesis por medio, piezas propias de analisis y opinion como categoria principal, enlazado interno, y la portada "como cuentan los medios un tema: coincidencias, diferencias y la verdad segun los datos y el analisis de la IA".
- 2026-10-18 (suposicion revisable): no hay CI con runners; la pasada local del gauntlet es el veredicto.
- 2026-10-18 (peticion): mejorar de forma indefinida con PR y squash merge por mejora; prioridad a la marca y los logotipos, y a las historias con datos que difieren sobre las que no tienen nada que marcar; relanzar historias antiguas si hay datos nuevos relevantes y es tendencia.
- 2026-10-18 (peticion): mejorar la navegacion en movil y escritorio, sitemap, compartir en redes, mejores comparativas y subir el nivel de verdad y mentira por medio: el producto no es un sitio de noticias sino de quien miente, quien informa, quien dice la verdad y cual es la verdad si la tenemos.
- 2026-10-19 (peticion): ir mas alla de la noticia: cruzar archivo historico con la actualidad, que se decia, que paso, quien dijo que y que consecuencias tuvo, buscando correlaciones entre hechos aparentemente sueltos; con IA (el usuario aportara la clave de Anthropic); en portada siempre lo que ocurre ahora con su porque.
- 2026-10-19 (peticion no aplicada): saltarse robots.txt cuando la informacion sea fundada y relevante. No se implementa: en la UE una exclusion legible por maquina puede valer como reserva frente a la mineria de textos (Directiva 2019/790, art. 4) y contradice ADR 0003. Alternativa aplicada: metadatos de GDELT y RSS (titular, fecha, URL) de los medios bloqueados, sin descargar sus paginas; y peticion de permiso a esos medios. Si el usuario quiere revisarlo, decision suya con asesoria legal. Insistencia del usuario el mismo dia (usar un agente, interes publico): se mantiene la decision; el interes publico ampara citar y publicar, no esta claro que ampare rastrear contra una exclusion expresa. Se usan agentes y fuentes de uso publico (datos oficiales, GDELT, Wikipedia, RSS).
- 2026-10-19 (decision del usuario, precisada): no rastrear sitios que lo excluyen, pero si consultar puntualmente una pagina concreta de interes publico (p. ej. transparencia) cuando sea imprescindible para contrastar un dato, una sola descarga, sin evadir bloqueos y con el motivo publicado.
- 2026-10-19 (peticion): cuando termine el trabajo en curso de nosmienten, y sin pararlo, migrar todo truth-news a microservices-ecosystem para que aqui solo quede el frontend con la logica de negocio, usando su BFF, sus microservicios y su base de datos, sin caida de servicio ni perdida de informacion, coordinado con los agentes del holding y de forma automatica. Plan: ADR 0025 y `docs/migracion-holding.md`. Suposicion revisable: las credenciales del holding (clave de aplicacion del BFF y `HOLDING_PLATFORM_API_KEY`) las crea una persona (regla del holding, `docs/holding/CREDENCIALES.md`); mientras falten, se construye y se prueba en local y no se corta ningun dominio en produccion.
- 2026-10-19 (peticion): seccion temporal de elecciones automatica para cualquier pais y ambito, empezando por las generales de Espana; recopilar declaraciones, promesas y programas, cumplimiento de quien goberno, verdades, mentiras, contradicciones y cambios con fecha y contexto. Confirma "Promesas frente a hechos (b)". Suposiciones revisables: solo fuentes citadas, mismo formato para todos los partidos, sin calificativos; "mentira" solo con veredicto del juez de datos (ADR 0007); un programa se importa si robots.txt lo permite, si no se enlaza.
