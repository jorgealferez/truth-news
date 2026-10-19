# Migracion de truth-news al holding (microservices-ecosystem)

Decision: ADR 0025. Peticion del usuario: 2026-10-19. Carril: "Migracion al holding" (docs/equipo.md),
responsable `session_01DgF9WootYzqTr7jwzkbDSj`.

La regla de oro es que **nada cae y nada se pierde**. Ningun dominio cambia de dueno sin tres cosas:
conciliacion con 0 diferencias, lectura en sombra con 0 diferencias y vuelta atras probada (bandera a
`local`).

## Destino

```
navegador ──> truth-news (FastAPI SSR: plantillas, i18n, reglas de veredicto, prompts, worker de orquestacion)
                  │  HTTPS + clave de aplicacion (tipo bff, producto nosmienten) -> JWT de identity
                  v
             gateway del holding  /api/nosmienten/  ──>  BFF del producto (lista blanca de rutas)
                  │
                  ├─ newsroom-service (nuevo, postgres propio): medios, feeds, articulos, historias, afirmaciones,
                  │     verificaciones+evidencia, temas, piezas, hilos, investigaciones, revisiones, traducciones
                  ├─ crawler      (feeds RSS/Atom + robots.txt + snapshots)      [ampliar: RSS]
                  ├─ publicdata   (BOE ya; INE Tempus, Eurostat, Banco Mundial, GDELT)  [ampliar: fuentes]
                  ├─ ai           (completions Anthropic, uso medido)
                  ├─ translation  (titulares; proveedor real via ai)              [ampliar: proveedor]
                  ├─ search       (documentos `article`, `story`, `piece`)        [ampliar: tipos]
                  ├─ social       (cola por red; Bluesky, Mastodon, Telegram, X)  [ampliar: adaptadores]
                  ├─ media        (imagenes OG y de redes)
                  ├─ identity     (OIDC del admin, sustituye a HTTP Basic)
                  └─ audit        (rastro de correcciones y decisiones de revision)
```

En truth-news **se queda**:
- las plantillas, los estaticos y la i18n;
- las reglas de contraste y de veredicto (ADR 0006, 0007, 0016);
- la puntuacion, la agrupacion y los prompts;
- la orquestacion del ciclo del worker.

**Se va** al holding todo estado persistente y toda llamada a terceros.

## Banderas

`DATA_BACKEND_<DOMINIO>` toma uno de cuatro valores:
- `local`: hoy.
- `dual`: escribe local y holding y lee local.
- `shadow`: escribe en los dos, lee local y compara con el holding, registrando cada diferencia.
- `holding`: lee y escribe en el holding; local queda como respaldo de solo escritura durante 7 dias.

Cada bandera se cambia por variable de entorno en Railway y vuelve atras sin despliegue.

Dominios, en orden de corte (de menos a mas riesgo):

| # | Dominio | Tablas locales | Destino | Notas |
|---|---|---|---|---|
| D1 | Registro | `outlet`, `feed` | newsroom (+ crawler para los feeds) | Datos de YAML; backfill trivial |
| D2 | Ingesta | `article`, `article_revision`, `crawl_run` | newsroom; texto via crawler `/extract` | Volumen mayor: backfill por lotes con huella |
| D3 | Contraste | `story`, `claim`, `verification`, `evidence` (+ 0010 a 0014 de los carriles) | newsroom | Invariante C6 comprobada en el holding |
| D4 | Contenido IA | `topic`, `piece`, `thread`, `investigation`, `article_translation` | newsroom; generacion via ai; traduccion via translation | Coste de IA medido por billing |
| D5 | Redes | `social_post` | social | Sin duplicados: clave por red y contenido |
| D6 | Busqueda | (nuevo) | search | Hoy no hay busqueda (ADR 0002) |
| D7 | Identidad del admin | (HTTP Basic) | identity OIDC via BFF | Basic queda de respaldo hasta el corte |

## Fases

Una fase es un PR por repositorio. Las del holding llevan su propio numero de fase, asignado por su
orquestador.

| Fase | Repositorio | Contenido | Sale cuando |
|---|---|---|---|
| 11 | truth-news + holding (ledger) | Plan: este documento, ADR 0025, items cruzados en los dos ledgers | PR mergeado |
| H1 | holding | Producto `nosmienten` en `productos.json`; ADR del BFF (ampliar familia o `nosmienten-bff`); BFF con lista blanca; publicado en `/api/nosmienten/` | `eco:bffs`, `eco:products` y `deploy:smoke` en verde |
| H2 | holding | `newsroom-service` (`pnpm new-service newsroom --db postgres`): ADR Tipo: datos, entidades D1 a D4 con claves naturales (url canonica del articulo, slug de historia...), upsert idempotente, `POST /bulk`, endpoint de huella por lote, eventos `newsroom.*` | Tests, `eco:isolation`, `docs:check` y contrato OpenAPI en verde |
| 12 | truth-news | Puertos de datos (`truthnews/ports/`) con adaptador SQL (comportamiento identico) y cliente del BFF (`truthnews/holding/`); banderas a `local` | Gauntlet full en verde; 0 cambios visibles |
| 13 | truth-news | D1 y D2: `dual` + outbox + backfill + conciliacion; despues `shadow` y `holding` | Conciliacion 0 diferencias; p95 dentro de presupuesto |
| 14 | truth-news | D3: idem | Conciliacion 0 y C6 medida en el holding |
| H3 | holding | Ampliaciones: crawler RSS, publicdata (INE, Eurostat, Banco Mundial, GDELT), translation real, search `article`, social (4 redes) | Cada una en su PR, con sus puertas |
| 15 | truth-news | D4 y D5: IA, traduccion y redes via servicios del holding | Coste por ciclo medido; 0 duplicados en redes |
| 16 | truth-news | D6 y D7: busqueda y admin con OIDC | Tests de integracion del panel con JWT |
| 17 | truth-news | Retirada: 7 dias limpios, volcado final archivado en media con huella, Postgres propio eliminado tras confirmacion; truth-news sin `DATABASE_URL` | Conciliacion final 0; servicio sin caidas medido |

## Conciliacion (sin perder nada)

- **Clave natural por tabla**: `outlet.slug`, `feed.url`, `article.url` canonica, `story.slug`,
  `claim` por (`article`, posicion, texto), etc. El id del holding guarda el id local como
  `legacy_id`.
- **Backfill**: por lotes de 500 en orden de `id`, con upsert idempotente, que se puede reanudar desde
  el ultimo `id` confirmado.
- **Huella**: SHA-256 de las filas del lote, normalizadas a JSON canonico, calculada en los dos lados.
  Una diferencia reabre el lote.
- **Outbox**: tabla local `holding_outbox` durante `dual` y `shadow`, una escritura por cambio, con
  reintentos exponenciales. Mientras quede alguna pendiente, el dominio no pasa a `holding`.
- **Informe por fase**: `docs/benchmarks/fase_1N.json` con filas por tabla local/holding, lotes con
  huella distinta, diferencias de sombra, pendientes en outbox y p95 de portada e historia.

## Credenciales (las provisiona una persona; nunca en el repositorio ni en el chat)

| Credencial | Donde | Estado 2026-10-19 |
|---|---|---|
| Clave de aplicacion `nosmienten` (tipo bff) | identity (panel Claves); variable `HOLDING_API_KEY` en el servicio web y worker de truth-news | por crear |
| `HOLDING_PLATFORM_API_KEY` (MCP del holding) | vault `holding/platform-api-key` | missing (`holding_estado`) |
| URL del gateway | `HOLDING_BASE_URL=https://app.simvixgroup.com` | conocida |

Sin estas claves, todo se construye y se prueba en local contra el BFF en docker compose. Lo de
produccion se declara `NO VERIFICADO (falta credencial)` y no se corta ningun dominio.

## Regla para los demas carriles mientras dura la migracion

- Una tabla nueva o una columna nueva se anota en la seccion "Esquema pendiente para newsroom" de este
  documento, en el mismo PR que la crea (nombre, clave natural, ADR).
- Despues de la fase 12, el acceso a datos nuevo pasa por `truthnews/ports/`, no por consultas directas
  de SQLAlchemy desde la web o el worker.

## Esquema pendiente para newsroom

Ademas de las migraciones 0001 a 0009 en main:
- 0010 a 0014 (reservadas por Verificaciones, Temas, Comparativas y Global, docs/equipo.md);
- Entidades y archivo historico (pendiente de su ADR).

Se incorporan a H2 cuando se mergeen.
