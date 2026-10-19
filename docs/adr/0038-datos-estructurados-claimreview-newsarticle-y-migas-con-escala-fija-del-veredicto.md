# ADR 0038 — Datos estructurados: ClaimReview, NewsArticle y migas de pan, con escala fija del veredicto

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** SEO (encargo de la direccion 2026-10-19, confirmado por el usuario: "Si haz todo lo que sean
  mejoras en este aspecto")
- **Decide:** Constructor, auditado por el Critico

## Contexto
Medido en las plantillas antes del cambio (`truthnews/web/templates/`, 42 ficheros):

- **0** bloques JSON-LD: los buscadores no sabian que una pagina de verificacion es una verificacion,
  ni quien publica, ni las fechas reales de las piezas propias;
- `<link rel="canonical">` solo en 9 plantillas; portada, verificaciones, listados de seccion, pais,
  comunidad y medio, investigaciones, metodologia y el resto sin canonical;
- `og:url` con la ruta pedida, no con la canonica; `og:type` duplicado en tema y noticia; `og:image`
  duplicado en noticia;
- sin `max-image-preview:large` (Google limita la imagen en Discover y en Noticias sin el);
- migas de pan visibles en 4 plantillas y sin marcado; los listados sin `meta description` propia.

## Decision
1. **`truthnews/web/structured.py`** construye los objetos de schema.org y `jsonld()` los escribe en un
   `<script type="application/ld+json">` (`</` escapado, claves vacias fuera: no se declara lo que no
   hay). `extract()` y `of_type()` los leen de vuelta (tests y comprobaciones en produccion).
2. **ClaimReview** en `/verificacion/<id>` con veredicto: `claimReviewed` con la cita literal,
   `itemReviewed` (Claim) con el medio como autor, la fecha de su noticia y la noticia como
   `appearance`, `author` el propio medio (NewsMediaOrganization) y `reviewRating` con una **escala fija**:
   falso 1, enganoso 2, impreciso 3, verdadero 4 (`bestRating` 4, `worstRating` 1, `alternateName` el
   veredicto en el idioma de la pagina). "Sin datos suficientes" no lleva ClaimReview: no hay valoracion.
   La escala se publica en Metodologia (es/en).
3. **NewsArticle** en lo que elabora el medio: hilos, piezas de tema e investigaciones publicadas. Fechas
   reales (`datePublished` = creacion, `dateModified` = ultima actualizacion; la pieza de tema no guarda
   modificacion y repite su creacion), autor declarado "Redaccion <sitio> (IA, verificada)" con enlace a
   Metodologia, editor con logotipo, imagen (la social de la historia ancla en los hilos; la generica si
   no hay). Ademas `article:published_time` / `article:modified_time` y `og:type` `article`.
4. **NewsMediaOrganization y WebSite** solo en la portada (Google los lee alli): nombre, logo 512 px,
   `publishingPrinciples`, `verificationFactCheckingPolicy` y `correctionsPolicy` (Metodologia) y
   `ownershipFundingInfo` (Acerca).
5. **BreadcrumbList**: un macro (`_crumbs.html`) dibuja la miga visible y su marcado con los mismos
   elementos, asi nunca divergen. En historia, hilo, tema, verificacion, investigacion, entidad, medio,
   seccion, pais y comunidad.
6. **Canonical en todas las paginas** desde `base.html` (bloque `canonical`; por omision la ruta sin
   parametros, salvo `?page=N` en listados paginados, que son paginas distintas) y `og:url` = canonical.
7. **Robots**: las paginas indexables llevan `index, follow, max-image-preview:large, max-snippet:-1,
   max-video-preview:-1`; las de un idioma no indexado siguen con `noindex, follow` (#118).
8. Los listados llevan `meta description` propia ("<nombre>: <lema>").

## Alternativas
- **Microdatos en el HTML** (`itemprop`): mezcla el marcado con el diseno de cinco carriles distintos;
  JSON-LD es lo que Google recomienda y vive en la cabecera.
- **Escala de 5 o con "sin datos" como 0**: "sin datos" no es una valoracion de la afirmacion; ponerle
  nota seria afirmar sin fuente (C6). Cuatro niveles = los cuatro veredictos con evidencia.
- **NewsArticle tambien en historias** (comparativas automaticas): la historia agrupa textos de otros
  medios; marcarla como articulo propio atribuiria a la redaccion un texto que no escribio. Lleva migas
  y canonical, no NewsArticle.

## Consecuencias
- Google redujo en 2025 los resultados enriquecidos de ClaimReview en la busqueda general; el marcado
  sigue alimentando Fact Check Explorer y las herramientas de verificacion, y no cuesta nada.
- NO VERIFICADO: la Prueba de resultados enriquecidos y Search Console son herramientas web de Google
  sin acceso desde este entorno; los tests parsean el JSON-LD de las paginas reales y comprueban cada
  campo.
- Plantillas nuevas: el canonical lo pone `base.html`; si la ruta canonica no es la pedida, se sobrescribe
  el bloque `canonical`.
