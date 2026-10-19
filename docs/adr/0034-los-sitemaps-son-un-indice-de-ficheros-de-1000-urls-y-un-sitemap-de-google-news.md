# ADR 0034 — Los sitemaps son un indice de ficheros de 1000 URLs y un sitemap de Google News

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** SEO (peticion del usuario 2026-10-19)
- **Decide:** Constructor, auditado por el Critico

## Contexto
El usuario pide (2026-10-19): "Optimiza los sitemap para noticias, divide en maximo 1000 por fichero,
con su importancia, fechas, etc y todas las optimizaciones necesarias para que Google pueda indexar de
forma eficiente y correcta y mejorar el seo".

Estado medido en el codigo antes del cambio (`truthnews/web/app.py`, ADR de la Fase 4a, #12):

- un unico `/sitemap.xml` con todo: paginas fijas, secciones, paises, medios, historias de los ultimos
  90 dias (hasta 40 000), temas, hilos e investigaciones;
- `lastmod` solo con la fecha (`2026-10-19`), sin hora: para un medio que cambia cada hora, Google no
  distingue que ha cambiado hoy;
- sin `priority` ni `changefreq`, sin imagenes, sin sitemap de Google News;
- las historias con mas de 90 dias desaparecian del sitemap aunque su pagina siga viva;
- sin comunidades autonomas (`/region/<codigo>`) ni paginas de verificacion (`/verificacion/<id>`);
- sin cabeceras de cache: cada robot rehacia todas las consultas.

## Decision
1. `/sitemap.xml` es un **indice** (`<sitemapindex>`). Apunta a `/sitemaps/news.xml` y a ficheros
   `/sitemaps/<tipo>-<n>.xml` de **como mucho 1000 URLs** (`PAGE_SIZE`). Tipos: `paginas` (fijas,
   listados, secciones, paises, comunidades y medios), `historias`, `temas`, `hilos`, `investigaciones`
   y `verificaciones`. No se listan ficheros vacios; un fichero fuera de rango da 404.
2. Cada tipo se pagina **por id ascendente**: lo antiguo queda en los primeros ficheros y su contenido
   no cambia al entrar historias nuevas. El `lastmod` de cada fichero en el indice es el maximo de sus
   URLs, asi Google solo vuelve a leer los ficheros que han cambiado.
3. Cada URL lleva:
   - `lastmod` con fecha y hora W3C en UTC (`2026-10-19T08:05:07+00:00`), el ultimo cambio real del
     contenido (historia y tema: el mayor de `last_seen` y `updated_at`; hilo e investigacion:
     `updated_at`; verificacion: `checked_at`; listados: la ultima historia contrastada). Las paginas
     fijas sin fecha fiable no llevan `lastmod`: un `lastmod` falso hace que Google deje de creerlo.
   - `changefreq` por edad: `hourly` (< 1 dia), `daily` (< 7), `weekly` (< 30), `monthly`.
   - `priority` ("importancia"): historia 0,5 de base, hasta +0,3 por medios que la cuentan (10 o mas) y
     +0,2 si es de las ultimas 48 h (+0,1 si de la ultima semana); portada 1,0, listados 0,8-0,9,
     secciones y paises 0,7, hilos 0,7, temas, investigaciones y verificaciones 0,6, medios y
     comunidades 0,5, paginas institucionales 0,2-0,4. Google declara que ignora `priority` y
     `changefreq`; se publican porque otros buscadores (Bing, Yandex) si los usan y no cuestan nada.
   - en historias, `image:image` con la imagen social de la historia (`/og/historia/<id>.png`).
   - con mas de un idioma indexado, los `xhtml:link` hreflang de cada version y `x-default`, como antes.
4. `/sitemaps/news.xml` sigue el formato de **Google News**: historias contrastadas (>= 2 medios), hilos
   e investigaciones publicados en las ultimas **48 h**, como mucho **1000** URLs, con
   `news:publication` (nombre del sitio, `SITE_NAME`, e idioma por omision), `news:publication_date`
   (primera aparicion) y `news:title`. Solo en el idioma por omision: el contenido es castellano.
5. Solo se ofrece lo que tiene contraste: historias de un solo medio y verificaciones "sin datos" quedan
   fuera (contenido fino). Las historias ya no caducan a los 90 dias: si la pagina vive, se ofrece.
6. Idiomas: `/sitemap-<idioma>.xml` sigue existiendo para cada idioma de `INDEXED_LANGUAGES` y apunta a
   `/sitemaps/<idioma>/<tipo>-<n>.xml` con las URLs prefijadas. Con solo `es` indexado (decision del
   usuario 2026-10-19, #118) no hay version inglesa.
7. `robots.txt` declara el indice y el sitemap de noticias. Las respuestas llevan
   `Cache-Control: public` (300 s el indice y las noticias, 900 s los ficheros), `Last-Modified` y
   `X-Robots-Tag: noindex` (el sitemap no es un resultado de busqueda).
8. El indice solo lee las columnas de fecha de cada tipo, sin construir URLs.

## Medidas
Banco local (`sqlite`, 10 000 historias, mediana de 5 peticiones, 2026-10-19):

| Ruta | Tamano | Entradas | Mediana |
|---|---|---|---|
| `/sitemap.xml` | 2 KiB | 12 ficheros | 36 ms (138 ms si construyera las URLs) |
| `/sitemaps/news.xml` | 145 KiB | 412 | 11 ms |
| `/sitemaps/historias-1.xml` | 279 KiB | 1000 | 17 ms |
| `/sitemaps/historias-10.xml` | 284 KiB | 1000 | 21 ms |
| `/sitemaps/paginas-1.xml` | 12 KiB | 106 | 6 ms |

Todos los ficheros por debajo del limite del protocolo (50 MB, 50 000 URLs). XML validado con
`xml.etree` en los tests.

## Alternativas
- **Un fichero con hasta 50 000 URLs** (lo que permite el protocolo): menos ficheros, pero cualquier
  historia nueva cambia el unico `lastmod` y Google relee todo; descartada por la peticion y por coste.
- **Paginar por fecha (un fichero por dia o por mes)**: estable tambien, pero hay dias con miles de
  historias y otros sin ninguna; no garantiza el tope de 1000 sin subdividir.
- **Generar ficheros estaticos en el worker**: menos carga en la web, pero el contenedor de Railway no
  comparte disco entre web y worker; la cache HTTP y las consultas acotadas bastan con las medidas.

## Consecuencias
- Search Console debe recibir `https://<sitio>/sitemap.xml` (indice) y, si se da de alta en Google
  News, `https://<sitio>/sitemaps/news.xml`. NO VERIFICADO: el envio a Search Console no esta en este
  entorno (sin credenciales de Google).
- Las rutas `/sitemaps/...` son compartidas entre idiomas (`langprefix.SHARED` ya cubre `/sitemap`).
- `social.sitemap_xml` desaparece; el XML vive en `truthnews/web/sitemaps.py`.
