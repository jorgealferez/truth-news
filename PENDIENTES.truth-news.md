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

- [ ] Priorizar lo que tiene datos que difieren: puntuacion de contraste por historia (cifras en disputa, veredictos, omisiones) que ordena portada y contrastes; relanzar historias antiguas cuando hay datos nuevos relevantes y tendencia (peticion del usuario 2026-10-18) — EN CURSO (session_012mRsejPRjvr7vC2Aq3edZ4, 2026-10-18)
- [ ] Fase 4 — Distribucion en redes sociales, RSS, sitemap, interfaz en ingles
- [ ] Fase 5 — Despliegue en Railway medido en produccion
- [ ] Marca y dominio: valorar nosmienten.com (peticion del usuario 2026-10-18) para una imagen solida, profesional, politicamente neutral y creible para el gran publico; aplicar el nombre via SITE_NAME y el dominio en Railway cuando el usuario decida

## Esperando

(vacio)

## Bloqueado

- [ ] Verificar en produccion la generacion real de temas y piezas (C12, C13) — BLOQUEADO: se necesita una credencial que el entorno no concede (ANTHROPIC_API_KEY en el servicio worker de Railway); pedida al usuario el 2026-10-18. Opciones: (a) el usuario la anade en Railway y el siguiente ciclo la usa; (b) usar el servicio `ai` del holding con HOLDING_PLATFORM_API_KEY

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
