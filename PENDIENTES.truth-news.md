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

- [ ] Correccion urgente (Fase 2): veredicto erroneo en produccion contra OKDIARIO por comparar con el ultimo mes y no con el citado; eurozona != UE; re-verificacion con nota publica de correccion (ADR 0006) — EN CURSO (session_012mRsejPRjvr7vC2Aq3edZ4, 2026-10-18)
- [ ] Fase 2b — Temas, sintesis por medio, valoracion con datos y piezas propias de analisis y opinion con IA (portada: como cuentan los medios cada tema) — EN CURSO (session_012mRsejPRjvr7vC2Aq3edZ4, 2026-10-18)
- [ ] Fase 3 — Administracion e investigaciones a demanda
- [ ] Fase 4 — Distribucion en redes sociales, RSS, sitemap, interfaz en ingles
- [ ] Fase 5 — Despliegue en Railway medido en produccion
- [ ] Marca y dominio: valorar nosmienten.com (peticion del usuario 2026-10-18) para una imagen solida, profesional, politicamente neutral y creible para el gran publico; aplicar el nombre via SITE_NAME y el dominio en Railway cuando el usuario decida

## Esperando

(vacio)

## Bloqueado

(vacio)

## Hecho

- [x] Fase 0 — Encuadre (#1)
- [x] Fase 1 — Nucleo: registro, rastreador, web segmentada, configuracion de Railway (#2)
- [x] Fase 1a — Despliegue temprano en Railway: produccion rastreando cada 30 min (#3)
- [x] Fase 2 — Motor de contraste: comparador por historia, datos oficiales, veredictos trazables (#4)
