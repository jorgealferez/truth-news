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

- [ ] Ultimo minuto (peticion del usuario 2026-10-19: "monitorizar aun mas todos los temas de actualidad, el ultimo minuto, y meter alguna forma de recalcar eso. Sin ser molesto y sin perder la esencia [...] comparativas [...] mas hype para volver a entrar. No tener que esperar una hora para volver a ver algo [...] sintetizar [...] evitar tanto scroll [...] mas ameno, mas grafico y mucho mas ordenado"): carril rapido del worker (medios nacionales y agencias cada ~10 min, sin IA) ademas del ciclo completo horario; franja "Ultimo minuto" compacta en portada (hora, medios, +medios en la ultima hora, cifras en disputa, enlace al porque); "Nuevo desde tu ultima visita" y aviso discreto de novedades sin recargar. Carril: direccion (worker) y ficheros compartidos (home, site.css) con cambios pequenos — EN CURSO (session_01VVUuDkKCf1JjwvouACQM38, 2026-10-19)
- [ ] Grandes falsedades y discrepancias (peticion del usuario 2026-10-19: "recalcar donde hay grandes mentiras. Esa es la noticia grande"; "mayores discrepancias entre medios, mayores mentiras entre politicos, medios de comunicacion y datos"): ranking por gravedad (veredicto x desviacion frente al dato oficial x alcance x actualidad) de afirmaciones falsas o enganosas con quien las dijo (persona, partido o medio), mayores discrepancias entre medios, contradicciones de una misma persona o medio en el tiempo, y quien acumula mas falsedades con su denominador; pagina propia y bloque listo para la portada (la portada la lleva otro hilo). Carril: Entidades y archivo (docs/equipo.md) — EN CURSO (session_01Juk7hZcsWaeHLeGwUxFzuh, 2026-10-19)
- [ ] Entidades y archivo historico (peticion del usuario 2026-10-19: "importar noticias, aunque sean mas antiguas, para tener mas informacion anterior de las mismas personas"; "si se menciona a X personas, X entidades... analizar, extraer y ordenar ese dato... Big Data... asociar datos macro"): extraccion de personas, partidos, instituciones y lugares de cada noticia, atribucion de cada afirmacion a quien la dice, fichas por entidad (menciones en el tiempo, medios, con quien aparece, afirmaciones y veredictos), importacion de noticias antiguas de los medios del registro (GDELT, desde 2017) por entidad hacia atras con cupo por ciclo; ADR de datos antes de la migracion. Carril: Entidades y archivo (docs/equipo.md) — EN CURSO (session_01Juk7hZcsWaeHLeGwUxFzuh, 2026-10-19)
- [ ] Verificaciones a escala (prioridad del usuario 2026-10-19: "lo mas importante las verificaciones, sintetizar datos y dar mascado al publico"): extraccion de afirmaciones comprobables con IA (el veredicto lo decide el codigo con datos, ADR 0007), mas indicadores y fuentes oficiales (INE por comunidad, EPA, IPC, BOE, Eurostat, Banco de Espana), veredicto en una frase con grafico del dato, ficha de verificacion para compartir. Carril: Verificaciones (docs/equipo.md) — EN CURSO (session_01JFjThAepJmvn9ndTW2bdeH, 2026-10-19)
- [ ] Autopublicacion en redes (peticion del usuario 2026-10-19): seleccion de lo mas relevante, contrastado o mediatico; piezas por red dentro de sus limites con imagen; adaptadores Bluesky, Mastodon, Telegram y X; cola con registro y sin duplicados; modo prueba sin credenciales; pedir al usuario las cuentas y claves para Railway. Carril: Redes (docs/equipo.md) — EN CURSO (session_01XKtMQ5i5KmEUZeifKfix5k, 2026-10-19)
  - [x] ADR 0018 (Tipo: datos) y migracion 0008: tabla `social_post`, unica por red y contenido
  - [x] `truthnews/social/`: seleccion (sin revision, sin fuente ni lenguaje cargado), piezas X 280 / Bluesky 300 / Mastodon 500 / Telegram 1.024 con imagen y enlace, adaptadores y cola con cupo diario y reintentos; paso al final del ciclo del worker; modo prueba sin credenciales
  - [ ] Pedir a la direccion que el usuario cree las cuentas y ponga las claves en Railway (worker); medir el primer ciclo con envio real
- [ ] Datos politicos con IA (peticion del usuario 2026-10-19): votaciones y actividad del Congreso y Senado (datos abiertos), promesas y programas frente a hechos, presupuestos y ejecucion, nombramientos del BOE; contraste de lo que dicen politicos y medios con esos datos y graficos claros. Carril: Verificaciones (docs/equipo.md)
- [ ] Cobertura global en cualquier idioma (peticion del usuario 2026-10-19): medios internacionales de referencia por pais y lengua (RSS, GDELT), titulares traducidos con IA marcados como traduccion, misma historia contada en distintos paises lado a lado, paginas en ingles para mas audiencia. Carril: Global (docs/equipo.md) — EN CURSO (session_012trDStWm4oFnLoYbz2Be91, 2026-10-19)
  - [x] Registro global: 18 paises nuevos (UE, Reino Unido, EEUU, Latinoamerica, Marruecos, Argelia, Golfo, Egipto), 73 medios y 118 feeds validados en vivo en 7 lenguas; medidos con tools/check_feeds.py (docs/benchmarks/fase_g1.json) — #28
  - [ ] Titulares traducidos con IA marcados como traduccion: ADR 0017, migracion 0009, worker (120 por ciclo) y vista de la historia; medir en produccion tras el despliegue
  - [ ] Misma historia en distintos paises lado a lado
  - [ ] Paginas en ingles (coordinar con "Railway project")
- [x] Tarjetas de la historia con los medios a la vista (peticion del usuario 2026-10-19: "Mejora esto que pone medios pero no hay forma de clicar para ver cuáles son los que dicen cada. Adáptalo a móvil y desktop sin romper el formato"): cifras en disputa, omisiones y a quien se senala, desplegables con el nombre de cada medio y enlace a su noticia; rutas: `truthnews/web/templates/story.html`, `truthnews/web/static/site.css`, `truthnews/registry/i18n.yaml`, tests — hecho en #16 (squash d681371, 2026-10-19)
- [ ] Hilo y consecuencias: archivo historico (GDELT, hemerotecas y sitemaps de los medios, anos atras) cruzado con la actualidad; linea temporal por tema (que se decia, que paso, que hubo por el camino, quien dijo que, que vino despues); conexiones entre hechos aparentemente sueltos con su evidencia (p. ej. Ceuta, presion diplomatica de Marruecos, EEUU/OTAN y Espana); analisis profundo con IA sin dar nada por sentado; en portada lo que ocurre ahora con su porque y su antes/despues (peticion del usuario 2026-10-19) — EN CURSO (session_012mRsejPRjvr7vC2Aq3edZ4, 2026-10-19) — Ampliado por el usuario 2026-10-19: asociar automaticamente noticias de distintas epocas, datos y articulos propios generados (cada hilo puede producir su pieza propia enlazada)
  - [x] ADR 0013 y migracion 0006 (tabla thread); conectores de hemeroteca GDELT (artlist por periodo) y Wikipedia
  - [x] Constructor de hilos: plan con hipotesis, corpus citado (S/G/W), cronologia, quien dijo que, conexiones con solidez, control de fundamento
  - [x] Worker: hilos antes que piezas (2 por ciclo, refresco 12 h); paginas /hilo, bloque en la historia y franja en portada
  - [x] Produccion 2026-10-19 00:12: el worker llama a la API con 200 OK; el ciclo se corto por un redespliegue y se perdio lo generado -> confirmar cada hilo, pieza e investigacion al generarse
  - [ ] Medir la primera generacion real en produccion (tiempo, tokens, publicados/revision)
- [ ] Consulta puntual de interes publico (decision del usuario 2026-10-19, precisada): cuando una pagina concreta (p. ej. un portal de transparencia) sea imprescindible para contrastar un dato concreto, se permite una navegacion dirigida aunque robots.txt lo excluya (precision del usuario: solo si hay dudas entre medios o falta de pruebas de la entidad y la fuente no se obtiene por otra via): las paginas necesarias para llegar a ese documento, con tope y cada URL registrada; al obtenerlo se para y nada se reutiliza para seguir rastreando; User-Agent honesto, se para ante 401/403/bloqueo, el motivo y la afirmacion que verifica quedan en la evidencia y en Metodologia; ADR que precisa el 0003
- [ ] Fuentes politicas (peticion del usuario 2026-10-19): webs oficiales de todos los partidos con representacion por igual (notas de prensa, declaraciones; RSS y sitemap), politicos (blogs) y redes con acceso publico oficial (Bluesky, Mastodon, YouTube RSS, canales publicos de Telegram); X/Facebook/Instagram solo con API (pedir credenciales). robots.txt medido 2026-10-19: PP, PSOE, Vox, Sumar, Junts, Bildu, PNV y BNG permiten; Podemos y ERC responden 403 (bloqueo tecnico: no se evade, probar RSS). Si alguno excluye, decision del usuario: cargo publico, motivo anotado en el registro, sin saltar bloqueos tecnicos. En la noticia: bloque "Que dicen los partidos", simetrico y sin calificativos — EN CURSO (session_012trDStWm4oFnLoYbz2Be91, 2026-10-19)
- [ ] Comparativas mejores: que dice cada medio lado a lado, cifras por medio, coincidencias y diferencias legibles, y la verdad segun los datos cuando la hay (peticion del usuario 2026-10-18) — Caso medido 2026-10-19: '12 migrantes' (autobus) frente a '500' (desalojo) sale como disputa y son hechos distintos: comparar solo cifras del mismo hecho — EN CURSO (session_01Ed8Nu3mgXDvmuLLX4NkckV, 2026-10-19), carril Comparativas
  - [ ] Solo cifras del mismo hecho (ADR 0016): precision de disputas sobre 15 historias reales etiquetadas 0,50 -> 1,00, exhaustividad 1,00 -> 1,00 (`tests/fixtures/disputes.json`)
  - [ ] Lo que dice cada medio lado a lado, coincidencias y diferencias legibles, la verdad segun los datos
- [ ] Reposicionar el producto en "quien miente, quien informa, quien dice la verdad y cual es la verdad si la tenemos": ficha de fiabilidad por medio con historial de veredictos, ranking de medios por exactitud comprobada, portada que lo destaca (peticion del usuario 2026-10-18)
- [ ] Fase 4 — Distribucion en redes sociales, RSS, sitemap, interfaz en ingles
- [ ] Fase 5 — Despliegue en Railway medido en produccion

## Esperando

- [ ] Publicidad sutil y etiquetada (peticion del usuario 2026-10-19: "muy bien estrategicamente situados en la web, pero muy sutiles", "que si se note que es publicidad, porque hay que avisarlo legalmente en Espana", "siempre promocionemos nuestras marcas", "que se vaya anunciando segun el interes y contenido de la noticia"; precision: "usemos microservicios no crearlo directamente en el portal de noticias ni su repo. Solo conectarnos"): en truth-news SOLO el cliente de `ads-service` (microservices-ecosystem, squad publicidad, session_01NyV3KDTzeAa3MUMiVSCJLR), sin tablas ni subasta aqui; huecos story-inline, list-native y footer-strip con etiqueta "Publicidad", rel sponsored, "Por que veo esto", baliza de visibilidad, pagina /publicidad; Railway: ADS_SERVICE_URL y ADS_SITE_KEY cuando el squad avise. Carril: Publicidad (docs/equipo.md) — codigo hecho en #37 (squash); ESPERANDO el aviso del squad publicidad (URL de ads-service y clave del sitio) para Railway y la medicion en produccion — despertador send_later cada ~45 min (session_0161mHJUdETFgtxqSGotgKjo)
  - [x] Cliente `truthnews/ads.py`: POST /ads/v1/serve con X-Site-Key, 150 ms, cache de errores 60 s, cortacircuitos (3 fallos -> 60 s), viewer = hash diario en memoria; sin cookies nuevas
  - [x] Huecos story-inline (tras la comparativa), list-native (tras el 6.o, 1 por pagina) y footer-strip; `_ad.html` con "Publicidad", "Marca del grupo Simvix", rel sponsored y "Por que veo esto"; baliza de visibilidad `static/ads.js` (50 % durante 1 s)
  - [x] Pagina /publicidad (LSSI art. 20, LGP art. 9, Ley 3/1991 de Competencia Desleal art. 26) enlazada en el pie, en /metodologia y en /acerca; sin CSP en el sitio: nada que abrir
  - [ ] Railway: ADS_SERVICE_URL y ADS_SITE_KEY en el servicio web cuando el squad publicidad avise; medir en produccion anuncio en una historia real, baliza 204 y clic 302 con UTM
- [ ] Ficha de medio y de noticia con datos citados y rastreo de modificaciones (peticion del usuario 2026-10-19: "incluye más datos cuando se entra en detalle del medio y la noticia aunque sea datos segmentados sin copiar todo para no robar el derecho pero si tener citación a la fuente y poder justificar el dato por si lo cambian. Debemos además rastrear modificaciones que hagan"): fragmentos breves citados con enlace, huella y fecha de captura de cada dato para justificarlo si el medio lo cambia, deteccion de cambios de titular/extracto/cifras entre rastreos e historial visible; ADR de datos antes de la migracion — codigo hecho en #20 (squash d7c347f) y desplegado; ESPERANDO varios ciclos del worker para medir cambios/dia — despertador send_later 2026-10-19 ~02:05 UTC (session_01QgjZUG9uLXjCTW4Q236ykL)
  - [x] ADR 0015 (Tipo: datos) y migracion 0007: tabla `article_revision` (antes/despues recortados, huellas sha256, fecha, rastreo)
  - [x] Rastreador: compara titular y extracto de las entradas ya conocidas y guarda cada cambio; la noticia queda en su version vigente
  - [x] Noticia: datos citados por fragmentos con fuente, cambios detectados con diff, ficha de captura (huella, fechas, copia de archivo)
  - [x] Medio: noticias rastreadas, cambios detectados y ultimos cambios enlazados
  - [ ] Medir en produccion cuantos cambios se detectan al dia (log del worker: "N cambios de titular o extracto")

## Bloqueado

- [ ] Verificar en produccion la generacion real de temas y piezas (C12, C13) — DESBLOQUEADO 2026-10-19: el usuario aporto la clave, comprobada contra la API y configurada en el worker; pendiente medir la primera generacion en produccion. Antes: BLOQUEADO: se necesita una credencial que el entorno no concede (ANTHROPIC_API_KEY en el servicio worker de Railway); pedida al usuario el 2026-10-18. Opciones: (a) el usuario la anade en Railway y el siguiente ciclo la usa; (b) usar el servicio `ai` del holding con HOLDING_PLATFORM_API_KEY

## Hecho

- [x] URLs SEO y tema "con chicha" muy visual (peticion del usuario 2026-10-19: "urls seo", "si muchos se repiten sintetiza para dar interés al lector y que vea la chicha", "más introducción y más datos gráficos de que falla, que falta, que origen", "todo muy visual"; ejemplos /tema/19 y /tema/17) (#26)
  - [x] URLs /tema|historia|hilo|noticia|investigacion/<id>-<slug> con 301 desde la forma antigua o un slug viejo; enlaces, canonical, sitemap, RSS y compartir con la URL nueva
  - [x] Pagina de tema: en una frase, cifras clave, tarjetas "de donde sale / que falla / que falta / valoracion", barras de cobertura (ambito, texto propio frente a mismo texto), diferencias en tarjetas, analisis largo plegado
  - [x] Medios que publican el mismo texto agrupados en un bloque (quien lo publico primero y chips); aparte solo lo que aporta cada uno
  - [x] Prompt del analisis: campo "claves" (en_una_frase, origen, que_falla, que_falta) y sintesis de una frase para las copias; las piezas antiguas usan lo derivado
  - [ ] Ver en produccion /tema/19 y /tema/17 tras el despliegue; las "claves" de IA llegan al regenerarse cada tema
- [x] Marca v2b: mezclar el simbolo con el logotipo formal, punto ambar en la i y la regla como recurso grafico en web e imagenes sociales; arreglar lo que falle (peticion del usuario 2026-10-19: "mezcla todo y arregla lo que falle") (#17)
- [x] Marca v2: icono, favicon e imagen completa mas profesionales para nosmienten.com, clara y agnostica a partidos e ideologias: "solo un medio donde verificar datos" (peticion del usuario 2026-10-19) (#14)
  - [x] ADR 0014: simbolo "n medida" (arco de la n que baja hasta una vara graduada), elegido por el usuario entre nivel de burbuja y monograma; logotipo, paleta e imagen social como estaban ("mas formal")
  - [x] mark.svg, favicon.svg/ico simplificado, iconos sobre papel (apple opaco, maskable en el manifest), avatar 400 para redes, og-default e imagen por historia con el simbolo nuevo
  - [ ] Registro de la marca (OEPM/EUIPO) y busqueda de anterioridades: tramite del usuario, NO VERIFICADO desde aqui
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
