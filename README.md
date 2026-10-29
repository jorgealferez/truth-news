# truth-news

Periódico que compara todo y da la verdad: un medio digital **automatizado** que rastrea cientos de
medios (nacionales, autonómicos y locales; España primero, cualquier país después), agrupa la misma
noticia contada por cada uno, contrasta sus afirmaciones con **datos oficiales y abiertos** y señala lo
que cada medio omite. Cada veredicto enlaza su evidencia; si no hay datos suficientes, se dice.

Estado y hoja de ruta: [`OBJETIVO.truth-news.md`](OBJETIVO.truth-news.md) · trabajo en curso:
[`PENDIENTES.truth-news.md`](PENDIENTES.truth-news.md) · decisiones: [`docs/adr/`](docs/adr/).

## Arranque local

```bash
pip install -e '.[dev]'
python -m truthnews db upgrade          # crea el esquema (SQLite por defecto: ./truthnews.db)
python -m truthnews sources stats       # registro de medios por país, ámbito y comunidad
python -m truthnews crawl               # un rastreo real (respeta robots.txt)
python -m truthnews serve               # http://localhost:8000
python -m truthnews worker              # rastreo periódico (CRAWL_INTERVAL_MINUTES, 60 por defecto)
```

## Despliegue en Railway

Una imagen (`Dockerfile`), dos servicios desde el mismo repositorio y un PostgreSQL:

| Servicio | Variables |
|---|---|
| `web` | `TRUTHNEWS_ROLE=web`, `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `SITE_URL` |
| `worker` | `TRUTHNEWS_ROLE=worker`, `DATABASE_URL=${{Postgres.DATABASE_URL}}` |

`bin/start` aplica las migraciones y arranca el rol. Para un despliegue mínimo, `TRUTHNEWS_ROLE=all`
arranca web y worker en un solo servicio. El healthcheck es `/healthz`.

### Redes sociales (worker, ADR 0018)

El worker publica en cada ciclo lo más contrastado (historias, hilos publicados y verificaciones con
fuente) en las redes que tengan credenciales; las demás quedan en modo prueba: la pieza se genera y se
registra en `social_post`, pero no se envía. Las claves solo van en las variables del servicio `worker`:

| Red | Variables |
|---|---|
| Bluesky | `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` (contraseña de aplicación), opcional `BLUESKY_PDS` |
| Mastodon | `MASTODON_URL` (instancia), `MASTODON_TOKEN` (permiso `write:statuses` y `write:media`) |
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (`@canal`, con el bot como administrador) |
| X | `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET` (OAuth 1.0a, lectura y escritura; la imagen se sube con `POST /2/media/upload` y, si falla, la pone la tarjeta del enlace) |

Cuentas en inglés (ADR 0033): las mismas variables con `_EN_` tras el nombre de la red (`X_EN_API_KEY`,
`BLUESKY_EN_HANDLE`, `MASTODON_EN_TOKEN`, `TELEGRAM_EN_CHAT_ID`...). Solo publican historias con titular
traducido por IA, marcado como traducción automática; cupo por defecto `x_en:2,bluesky_en:3,mastodon_en:3,telegram_en:4`.

Ajustes: `SOCIAL_ENABLED` (1), `SOCIAL_DRY_RUN` (0; 1 fuerza el modo prueba), `SOCIAL_DAILY_QUOTA`
(`x:4,bluesky:6,mastodon:6,telegram:8`), `SOCIAL_PER_CYCLE` (2), `SOCIAL_MIN_SCORE` (2),
`SOCIAL_WINDOW_HOURS` (72).
Reparto en el día: `SOCIAL_ACTIVE_HOURS` (`8-23`, hora de Madrid; de noche no se publica) y una pieza por red
cada (horas activas / cupo), como mucho una por ciclo; `SOCIAL_SPREAD=0` lo desactiva.

Prueba a mano: `python -m truthnews social preview` muestra las piezas que saldrían ahora en cada
red sin escribir nada; `python -m truthnews social run --dry` ejecuta el paso en modo prueba. La cola se
revisa en `/admin` (sección Redes).

### Foco: analizar a fondo un suceso grave (ADR 0056)

Variables del servicio `worker`. `AI_FOCUS` enciende el foco (terminos separados por comas, p. ej.
`iryo,adif,los yebenes,urda,alta velocidad`); borrarla lo apaga. Mientras esta puesto, lo que case pasa
primero por afirmaciones, hilos y piezas, cada 30 min y con su propia bolsa diaria, que no gasta de la
general. Con `AI_FOCUS_QUESTION` se crea y se actualiza sola una investigacion con esa pregunta. Ajustes:
`AI_FOCUS_BUDGET_USD` (15), `AI_FOCUS_MAX_PIECES` (3), `AI_FOCUS_MAX_THREADS` (2),
`AI_FOCUS_CLAIMS_CALLS` (4), `AI_FOCUS_REFRESH_MINUTES` (30).

### Publicidad propia de Ridelta por zona (ADR 0055)

Los huecos de publicidad que ads-service deja vacíos llevan un banner rotativo de Ridelta con la web de la
zona del lector: la que elige en el banner (a mano o con «Usar mi ubicación», resuelta en su navegador), la
de la zona de la que trata la página o, si no se sabe, `ridelta.com`. Las piezas de contenido patrocinado
por zona están en `/patrocinado`, siempre etiquetadas y con enlaces `rel="sponsored"` y UTM. Zonas, dominios
y municipios en `truthnews/registry/house_ads.yaml` (copiados de vtc-clm); `HOUSE_ADS_ENABLED=0` lo apaga.

## Añadir un país o un idioma (sin código)

- País: una entrada en `truthnews/registry/countries.yaml` y un `truthnews/registry/sources/<iso>.yaml`.
- Medio: una línea en el `sources/<iso>.yaml` de su país (los feeds se descubren solos si no se dan).
- Idioma: una clave nueva en `truthnews/registry/i18n.yaml` y sus palabras clave en `categories.yaml`.

## Principios editoriales

El rastreador se identifica, respeta `robots.txt` y espacia las peticiones; del medio original se
publica solo titular, extracto breve y enlace (derecho de cita); el análisis es propio y el contenido
automatizado se marca como tal (ADR 0003).

## Calidad

Loop Engineering: `bin/gauntlet -p full` (lint, tests con cobertura ≥ 80 %, integridad del loop,
revisión de datos, ratchet de benchmarks) en verde antes de cada PR.
