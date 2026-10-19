# ADR 0025 — truth-news migra al holding por dominios, sin corte de servicio ni perdida de datos

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** 11 (Migracion al holding, plan)
- **Decide:** Constructor, auditado por el Critico

## Contexto
Peticion del usuario 2026-10-19: cuando termine el trabajo en curso de nosmienten, y sin pararlo,
truth-news debe migrar al ecosistema `microservices-ecosystem` (el "holding"). Al final, en este
repositorio solo queda **un frontend con nuestra logica de negocio**, que usa el BFF, los
microservicios y la base de datos del holding. La condicion es que no se corte el servicio ni se
pierda informacion. La migracion es tambien una prueba de que el holding funciona.

Base medida el 2026-10-19:
- **truth-news hoy.** Un monolito Python (FastAPI SSR + worker APScheduler) sobre un Postgres propio
  en Railway, con 15 tablas (migraciones 0001 a 0009 y las reservadas 0010 a 0014). El admin entra
  con HTTP Basic. Las llamadas directas a Anthropic, INE, Eurostat, Banco Mundial, BOE, GDELT,
  Wikipedia y las redes salen del propio codigo. ADR 0001 aplazo el holding porque faltaba
  `HOLDING_PLATFORM_API_KEY`.
- **El holding.** Tiene 57 servicios con un almacen por servicio (`eco:isolation`) y 19 BFF. Solo el
  gateway es publico (`/api/<familia>/`). identity es el unico emisor de JWT, y las claves de
  aplicacion se canjean por token. Ya hay servicios utiles para nosotros: crawler (robots.txt,
  snapshots), publicdata (BOE, PLACSP), search (FTS), translation (proveedor stub), ai (Anthropic),
  social (Facebook e Instagram), media, scheduler, audit y webhooks.
- **Lo que no hay.** Ningun servicio es dueno del dominio "noticias y verificacion" (medios, feeds,
  articulos, historias, afirmaciones, veredictos con evidencia, temas, piezas, hilos, investigaciones,
  revisiones, traducciones y cola de redes). Tampoco existe todavia la credencial:
  `HOLDING_PLATFORM_API_KEY` sigue en `missing` (medido con `holding_estado`).
- **Precedente.** El carril Publicidad ya es "solo cliente de `ads-service`" (docs/equipo.md).

## Decision
La migracion sigue el **patron estrangulador, dominio a dominio**:
1. Una capa de **puertos de datos** en truth-news con dos adaptadores: SQL local y holding via BFF.
2. **Doble escritura** con bandeja de salida (outbox) y reintentos.
3. **Backfill** idempotente por clave natural.
4. **Conciliacion** de recuentos y huellas.
5. **Lectura en sombra** comparada con la local.
6. **Corte de lectura** por bandera.
7. **Retirada** del Postgres propio, que solo se hace tras 7 dias de conciliacion limpia y con el
   volcado final archivado.

La parte del holding la construye el squad `nosmienten` dentro de las reglas del holding:
- un BFF del producto (ADR del holding: ampliar una familia o crear `nosmienten-bff`);
- un servicio de dominio nuevo `newsroom-service`, con ADR Tipo: datos alli;
- ampliaciones pequenas de crawler, publicdata, social, translation, search y media, cada una
  hecha por su dueno.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Corte en seco: volcado, restauracion y cambio de DNS | Hay ventana de corte y el worker escribe cada hora. Si algo falla, la vuelta atras pierde lo escrito durante la ventana, y eso viola "sin que caiga nada ni se pierda informacion". |
| Replica logica de Postgres hacia el holding | Saltaria las reglas del holding: un almacen por servicio, acceso solo por API y eventos, y CONNECT revocado. Acoplaria el esquema de truth-news al servicio destino. |
| Repartir las tablas entre servicios genericos (content para piezas, knowledge para hilos...) | Se perderian las invariantes del dominio (ADR 0005, 0006, 0016: evidencia obligatoria, periodo citado, mismo hecho) y se repartirian entre duenos que no las conocen. Si se reutilizan donde encajan (texto, busqueda, medios, IA, redes, datos publicos), pero el nucleo del veredicto necesita un dueno. |
| Mantener truth-news aparte y llamar al holding solo como adaptador opcional (ADR 0001) | Es lo contrario de lo que pide el usuario ahora. |

## Consecuencias
- **Gana.** truth-news queda en frontend y logica (analisis, reglas de veredicto, prompts). Los datos,
  la identidad del admin (OIDC del holding en lugar de HTTP Basic), la IA, la traduccion, la busqueda
  y las redes pasan a ser del holding, y el holding gana un producto real que lo pone a prueba.
- **Cuesta.**
  - Hay latencia de red por cada lectura. Se mitiga con cache de lectura en el BFF y en truth-news, y
    el presupuesto de C7 (p95 de portada < 300 ms) es suelo: no se corta la lectura de un dominio si
    lo rompe.
  - Hay doble escritura durante semanas.
  - Hay dependencia de dos credenciales que provisiona una persona.
- **Orden.** Arranca cuando cierren los items en curso de `## Activo` (peticion del usuario). La
  preparacion en el holding (BFF y servicio) va en paralelo, porque no toca truth-news.
- **Durante la migracion.** Toda tabla nueva de cualquier carril se declara tambien en el contrato de
  `newsroom-service` (`docs/migracion-holding.md`, seccion "Regla para los demas carriles").
- **Detalle.** Fases, banderas, conciliacion y criterios de corte en `docs/migracion-holding.md`.

## Verificacion
- Cada fase de migracion publica `docs/benchmarks/fase_11x.json` con la conciliacion:
  - filas por tabla, local frente a holding: diferencia 0;
  - huellas SHA-256 por lote: coinciden;
  - diferencias de lectura en sombra: 0;
  - p95 de portada e historia dentro de presupuesto.
- El corte de un dominio solo se hace con esos numeros en verde.
- La retirada del Postgres propio exige 7 dias de conciliacion sin diferencias y el volcado final
  archivado con su huella.
