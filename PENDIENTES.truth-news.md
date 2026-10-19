# PENDIENTES — ledger de continuidad de truth-news

continuidad: activa

Este archivo es el **estado de trabajo compartido entre agentes y sesiones** del repositorio
`truth-news`, y solo de el. Lo lee el hook `Stop` de continuidad: mientras haya un item sin marcar en
`## Activo`, ningun agente puede cerrar el turno. Protocolo: skill `continuidad`.

Reglas de edicion (resumen; la version completa esta en la skill):

- **Un ledger por repositorio, nombrado por repositorio.** Aqui solo entran items cuyo cambio vive en
  `truth-news`. Si una tarea toca otro repositorio, su parte va en el `PENDIENTES.<otro>.md` de ese
  repositorio, con referencia cruzada. Nunca se crea un `PENDIENTES.md` sin nombre ni un ledger global.
- `## Activo` esta en **orden de ejecucion**. Se toma siempre el primero sin reservar.
- Un item se marca `[x]` solo con su pull request mergeado (o su entregable verificado).
- `## Esperando`: items que dependen de algo externo (CI, revision, servicio). Al mover uno aqui, el
  agente **programa un despertador** antes de cerrar el turno. Si no puede programarlo, el item no se
  mueve: se sigue trabajando.
- `## Bloqueado`: solo con `BLOQUEADO: <motivo>` y solo si el motivo es una de las causas de la seccion
  "Cuando SI hay que parar y preguntar". Es la unica forma legitima de dejar de avanzar.
- `continuidad: pausada` la escribe **una persona**, nunca un agente.
- **Antes de empezar un item se RESERVA**: se le anade `EN CURSO (<sesion>, <fecha>)` y se publica el
  ledger (commit y push) *antes* de escribir codigo. Otra sesion que vea una reserva viva se salta ese
  item y toma el siguiente sin reservar. Una reserva caduca si su rama remota no se mueve en 24 h.
- Una seccion vacia se escribe `(vacio)`; nunca se borra la seccion.

## Activo

- [ ] Tarjetas de la historia con los medios a la vista (peticion del usuario 2026-10-19: "Mejora esto que pone medios pero no hay forma de clicar para ver cuáles son los que dicen cada. Adáptalo a móvil y desktop sin romper el formato"): cifras en disputa, omisiones y a quien se senala, desplegables con el nombre de cada medio y enlace a su noticia; rutas: `truthnews/web/templates/story.html`, `truthnews/web/static/site.css`, `truthnews/registry/i18n.yaml`, tests — EN CURSO (session_01QgjZUG9uLXjCTW4Q236ykL, 2026-10-19, rama ui/medios-desplegables)
- [ ] Ficha de medio y de noticia con datos citados y rastreo de modificaciones (peticion del usuario 2026-10-19: "incluye más datos cuando se entra en detalle del medio y la noticia aunque sea datos segmentados sin copiar todo para no robar el derecho pero si tener citación a la fuente y poder justificar el dato por si lo cambian. Debemos además rastrear modificaciones que hagan"): fragmentos breves citados con enlace, huella y fecha de captura de cada dato para justificarlo si el medio lo cambia, deteccion de cambios de titular/extracto/cifras entre rastreos e historial visible; ADR de datos antes de la migracion
- [ ] Hilo y consecuencias: archivo historico (GDELT, hemerotecas y sitemaps de los medios, anos atras) cruzado con la actualidad; linea temporal por tema (que se decia, que paso, que hubo por el camino, quien dijo que, que vino despues); conexiones entre hechos aparentemente sueltos con su evidencia (p. ej. Ceuta, presion diplomatica de Marruecos, EEUU/OTAN y Espana); analisis profundo con IA sin dar nada por sentado; en portada lo que ocurre ahora con su porque y su antes/despues (peticion del usuario 2026-10-19) — EN CURSO (session_012mRsejPRjvr7vC2Aq3edZ4, 2026-10-19)
  - [x] ADR 0013 y migracion 0006 (tabla thread); conectores de hemeroteca GDELT (artlist por periodo) y Wikipedia
  - [x] Constructor de hilos: plan con hipotesis, corpus citado (S/G/W), cronologia, quien dijo que, conexiones con solidez, control de fundamento
  - [x] Worker: hilos antes que piezas (2 por ciclo, refresco 12 h); paginas /hilo, bloque en la historia y franja en portada
  - [ ] Medir la primera generacion real en produccion (tiempo, tokens, publicados/revision)
- [ ] Consulta puntual de interes publico (decision del usuario 2026-10-19, precisada): cuando una pagina concreta (p. ej. un portal de transparencia) sea imprescindible para contrastar un dato concreto, se permite una navegacion dirigida aunque robots.txt lo excluya (precision del usuario: solo si hay dudas entre medios o falta de pruebas de la entidad y la fuente no se obtiene por otra via): las paginas necesarias para llegar a ese documento, con tope y cada URL registrada; al obtenerlo se para y nada se reutiliza para seguir rastreando; User-Agent honesto, se para ante 401/403/bloqueo, el motivo y la afirmacion que verifica quedan en la evidencia y en Metodologia; ADR que precisa el 0003
- [ ] Comparativas mejores: que dice cada medio lado a lado, cifras por medio, coincidencias y diferencias legibles, y la verdad segun los datos cuando la hay (peticion del usuario 2026-10-18) — Caso medido 2026-10-19: '12 migrantes' (autobus) frente a '500' (desalojo) sale como disputa y son hechos distintos: comparar solo cifras del mismo hecho
- [ ] Reposicionar el producto en "quien miente, quien informa, quien dice la verdad y cual es la verdad si la tenemos": ficha de fiabilidad por medio con historial de veredictos, ranking de medios por exactitud comprobada, portada que lo destaca (peticion del usuario 2026-10-18)
- [ ] Fase 4 — Distribucion en redes sociales, RSS, sitemap, interfaz en ingles
- [ ] Fase 5 — Despliegue en Railway medido en produccion

## Esperando

(vacio)

## Bloqueado

- [ ] Verificar en produccion la generacion real de temas y piezas (C12, C13) — DESBLOQUEADO 2026-10-19: el usuario aporto la clave, comprobada contra la API y configurada en el worker; pendiente medir la primera generacion en produccion. Antes: BLOQUEADO: se necesita una credencial que el entorno no concede (ANTHROPIC_API_KEY en el servicio worker de Railway); pedida al usuario el 2026-10-18. Opciones: (a) el usuario la anade en Railway y el siguiente ciclo la usa; (b) usar el servicio `ai` del holding con HOLDING_PLATFORM_API_KEY

## Hecho

- [x] Fase 0 — Encuadre (#1)
- [x] Fase 1 — Nucleo: registro, rastreador, web segmentada, configuracion de Railway (#2)
- [x] Fase 1a — Despliegue temprano en Railway: produccion rastreando cada 30 min (#3)
- [x] Fase 2 — Motor de contraste: comparador por historia, datos oficiales, veredictos trazables (#4)
- [x] Correccion (Fase 2): veredictos contra el periodo citado, eurozona != UE, correccion publica (#5)
- [x] Fase 2b — Temas, sintesis por medio y piezas propias de analisis y opinion con IA (#6); generacion real pendiente de clave (ver Bloqueado)
- [x] Correccion v3: atribucion de territorio con nomenclator mundial y retirada con nota publica (#7)
- [x] Fase 3 — Administracion e investigaciones a demanda (#8)
  - [x] ADR 0010 (Tipo: datos) y migracion 0004 de la tabla `investigation` (ida y vuelta comprobada)
  - [x] `truthnews/investigate.py`: historias relacionadas, datos oficiales por pais, cobertura GDELT en ingles, analisis IA con control de fundamento
  - [x] Panel `/admin` (HTTP Basic, CSRF, 503 sin ADMIN_PASSWORD) con balance, feeds con errores, medios mudos, fiabilidad por medio, piezas en revision y alta de investigaciones
  - [x] Paginas publicas `/investigaciones` y `/investigacion/{id}`; el worker siembra las preguntas del usuario y procesa las pendientes
  - [x] Tests (tests/test_investigate.py) y benchmark docs/benchmarks/fase_3.json
- [x] Fase 6 — Marca nosmienten.com: identidad, logotipo, iconos, imagen social y dominio (#9)
  - [x] ADR 0011: simbolo (dos barras, la inferior mas corta), logotipo en contornos, paleta tinta/ambar fuera de colores de partido, lema "Sin bandos. Con datos."
  - [x] logo.svg, mark.svg, favicon, iconos, manifest, imagen social 1200x630 y metadatos Open Graph/Twitter (tools/brand.py)
  - [x] Railway: SITE_NAME/SITE_DOMAIN/SITE_URL en web y worker; nosmienten.com verificado con certificado; www.nosmienten.com pendiente de DNS del usuario
- [x] Fase 7 — Prioridad a lo que difiere y relanzamiento con datos nuevos (#10)
  - [x] ADR 0012 (Tipo: datos) y migracion 0005: contrast_score, priority, contrast, relaunched_at e indices (ida y vuelta comprobada)
  - [x] truthnews/analysis/score.py: puntuacion (disputas, veredictos, omisiones, lenguaje cargado) y prioridad; relleno incremental de 7 dias
  - [x] Relanzamiento: historia antigua con contraste que varios medios retoman, o con datos nuevos que la contrastan
  - [x] Portada y contrastes ordenados por prioridad; la tarjeta dice que difiere y si vuelve con datos nuevos
  - [x] "personas" desambiguado por contexto (falso positivo medido con datos reales)
- [x] Marca y dominio: valorar nosmienten.com (peticion del usuario 2026-10-18) para una imagen solida, profesional, politicamente neutral y creible para el gran publico; aplicar el nombre via SITE_NAME y el dominio en Railway cuando el usuario decida (#9: hecho en la Fase 6)
- [x] Fase 8 — Navegacion movil/escritorio e historia visual (#11)
  - [x] Barra de secciones fija, menu completo sin JS, pestanas inferiores en movil, migas de pan
  - [x] Historia visual: origen con linea de tiempo, barras de cifras en disputa, medidor de veredictos, a quien senala cada version, omisiones
  - [x] Ficha por medio (titular, propietario, cifra, senalados, omisiones, lenguaje cargado); keywords y piezas en desplegables (peticion del usuario 2026-10-19: "muy visual, no tan lineal")
- [x] Fase 4a — Sitemap, robots, RSS, compartir e imagen social por historia (#12)
  - [x] /robots.txt, /sitemap.xml (90 dias) y /rss.xml
  - [x] Compartir: WhatsApp, X, Telegram, Facebook, Bluesky, LinkedIn, email, copiar y Web Share nativo, sin scripts de terceros
  - [x] Imagen social por historia con titular, cifras en disputa y veredictos (Pillow + Inter OFL)
