# ADR 0055 — Publicidad propia de Ridelta por zona: banners rotativos y contenido patrocinado, siempre etiquetados

- **Estado:** aceptado
- **Fecha:** 2026-10-20
- **Fase:** transversal (publicidad), peticion del usuario
- **Decide:** sesion de Publicidad, a peticion del usuario

## Contexto
Peticion del usuario (2026-10-20): banners y "noticias cocinadas" de publicidad de Ridelta en cada zona donde
opera, sobre como funciona y sus dominios provinciales, "que suene organico y genere enlaces y visibilidad
maxima", con banners rotativos que lleven al lector al servicio y dominio de su zona segun su ubicacion, o al
generico si no se puede saber.

Lo que habia:

- El cliente de ads-service (`truthnews/ads.py`, carril Publicidad) con tres huecos (`story-inline`,
  `list-native`, `footer-strip`), etiqueta "Publicidad", `rel="sponsored"` y las reglas de neutralidad (sin
  anuncios en paginas de elecciones ni junto a un veredicto). No sirve nada: falta `ADS_SITE_KEY`
  (bloqueo anotado en el ledger desde el 2026-10-19), asi que hoy todos los huecos estan vacios.
- La politica publicada en /publicidad: solo marcas propias del grupo, siempre etiquetadas (LSSI art. 20,
  LGP art. 9, Ley 3/1991 art. 26), "nunca lo hacemos pasar por informacion".
- Ridelta (repositorio vtc-clm, solo lectura): `ridelta.com` (generico, con /cobertura y /apps), hubs
  `vtcclm.com` y `vtccyl.com`, y 14 dominios provinciales (5 de Castilla-La Mancha y 9 de Castilla y Leon),
  todos en 200 el 2026-10-20. El pie legal de ridelta.com dice "servicio bajo contratacion previa en
  Castilla-La Mancha y Castilla y Leon". ridelta.com/apps dice que las apps de iOS y Android "estan en
  preparacion para las tiendas" y que mientras tanto la web se instala como app.
- El sitio no recibe cabeceras de geolocalizacion (Railway, sin CDN delante): el servidor no sabe donde esta
  el lector.

## Decision
1. **Banners propios en los huecos vacios.** `ads_for` sigue pidiendo a ads-service y, en cada hueco que
   queda vacio, pone publicidad propia de Ridelta (`truthnews/house.py`). Las reglas del hueco no cambian:
   sin nada en paginas de elecciones, y en una historia con veredictos o "Que dicen los partidos" solo la
   franja del pie. `HOUSE_ADS_ENABLED=0` lo apaga.
2. **Zona del lector**, por este orden: (a) la que el elige en el propio banner, a mano o con "Usar mi
   ubicacion", guardada en la cookie de preferencia `zona` (exenta, declarada en `legal.STORAGE`); la
   ubicacion se pide solo al pulsar el boton, se resuelve en el navegador contra `/zonas.json` (municipio
   mas cercano en 45 km) y nunca llega al servidor; (b) el contenido de la pagina: la provincia con mas
   municipios citados en titular y extractos (sin los que son apellidos o palabras comunes: Toro,
   Consuegra, Torrijos...), o si no la comunidad de la pagina o de sus medios (hub regional); (c) si no se
   sabe, ridelta.com.
3. **Rotacion sin movimiento.** Cada banner lleva 3 o 4 piezas que `house.js` alterna cada 8 s, sin
   animacion; se para al pasar el raton, con el foco y con un boton de pausa (WCAG 2.2.2), y no rota con
   `prefers-reduced-motion`. Sin JavaScript queda la primera pieza y el selector de zonas con enlaces.
4. **Contenido patrocinado** en `/patrocinado` (indice) y `/patrocinado/<slug>`: una pieza general, una por
   comunidad y dos por provincia (como funciona en la provincia; ir al aeropuerto o al AVE).
   El hueco de listado lleva a la pieza de la zona. Se escriben **con tono de servicio, utiles y legibles,
   pero etiquetadas** arriba ("Contenido patrocinado · Patrocinado por Ridelta") y abajo, con aspecto
   distinto del editorial, fuera de la portada, del RSS, del sitemap de Google News y de las verificaciones.
   **Pieza de cabecera y enfoque rural** (peticion del usuario del mismo dia: "que se vea que apostamos por
   zonas rurales ... donde no llegan las grandes"): `/patrocinado/donde-no-llegan-las-grandes` va primera
   (32 piezas en total), cada pieza provincial lleva "Donde no llegan las grandes" con sus municipios
   pequenos y cada banner provincial una pieza "Donde no llegan las grandes plataformas, llegamos". Se apoya
   en un dato que se puede comprobar: ninguna de las 14 provincias ni de sus 168 municipios de origen esta en
   la lista de ciudades de Cabify en Espana (13, copiada de vtc-clm, `src/lib/mundo/ciudades-cabify.ts`, con
   fuente y fecha en la pieza). `outside_big` lo comprueba por zona y la frase desaparece de la zona donde
   deje de ser cierta. No se escribe "los primeros" ni "los unicos": no hay forma de probarlo y un superlativo
   sin prueba es publicidad enganosa (Ley 3/1991 arts. 5 y 10; LGP art. 3). Uber y otras no se nombran: no
   hay lista suya en vtc-clm.
5. **Enlaces con `rel="sponsored"` y UTM** (`utm_source=nosmienten`, `utm_medium=banner|patrocinado`,
   `utm_campaign=ridelta-<zona>`): la visibilidad y las visitas se miden en el destino.
6. **Solo se afirma lo que hace el servicio.** Las frases salen de vtc-clm (titulares, demanda, carreteras,
   municipios y destinos de cada provincia; ventajas y pasos de ridelta.com) y del README de vtc-clm. Sin
   precios inventados ni promesas de disponibilidad. Las apps se anuncian como estan: "en preparacion para
   las tiendas; la web se instala como app" mientras `apps_in_stores: false`.
7. **Datos, no codigo.** Zonas, dominios, municipios y coordenadas en `registry/house_ads.yaml`, copiados de
   vtc-clm. Solo zonas con servicio contratado: Madrid y los sitios de mercado (`taximadrid.ridelta.com`,
   Barcelona, Alicante, A Coruna, Medellin) quedan fuera mientras el pie de ridelta.com no diga que se presta
   servicio alli. Anadir una zona es una entrada en el YAML.

## Lo que no se hace, y por que
- **No se hacen pasar por noticias.** La peticion pide que "suene organico"; se hace en el tono, no en la
  forma: presentar publicidad como informacion es publicidad encubierta (LSSI art. 20, Ley 3/1991 de
  Competencia Desleal art. 26, Ley General de Publicidad art. 9) y contradice la politica publicada en
  /publicidad y la razon de ser del sitio (verificar). Ademas, Google trata el contenido patrocinado sin
  etiquetar de un medio como incumplimiento de sus politicas de Google News.
- **Enlaces con `rel="sponsored"`, no `follow`.** Enlaces pagados o de autopromocion que pasan autoridad son
  un esquema de enlaces para Google (politicas de spam: "link schemes"); el riesgo es una accion manual
  sobre nosmienten.com y sobre los dominios de Ridelta, justo lo contrario de lo pedido. Con `sponsored` los
  banners y las piezas dan visitas y visibilidad medibles sin poner en riesgo el posicionamiento de nadie.
- **No se pide la ubicacion sin que el lector lo pulse** ni se usa la IP para geolocalizar: no hay cabecera
  de pais o provincia en Railway, y una base de IP a provincia seria un tratamiento de datos que la politica
  de privacidad no declara.
- **Sin tablas ni migracion**: no toca la capa de datos (sin ADR de datos).

## Relacion con ads-service
La peticion anterior del usuario (2026-10-19) era no construir la plataforma de publicidad aqui ("solo
conectarnos"). Esto no la construye: no hay anunciantes, campanas, subasta ni medicion propia; es un relleno
de marca propia leido de un YAML, que cede el hueco en cuanto ads-service sirva un anuncio. Cuando el squad
publicidad tenga campanas, estas piezas pueden pasar a ser creatividades de ads-service y este relleno
apagarse con `HOUSE_ADS_ENABLED=0`.

## Consecuencias
- Desde el despliegue, toda pagina con huecos (portada, listados, historias sin veredicto, /analisis,
  /region) lleva un banner de Ridelta etiquetado; la franja del pie aparece en todas ellas.
- Se puede medir en el destino (UTM) cuanto trafico llega de cada zona y de cada pieza.
- Cambia /publicidad (nueva seccion "Publicidad propia por zona") y /cookies (cookie `zona`).
