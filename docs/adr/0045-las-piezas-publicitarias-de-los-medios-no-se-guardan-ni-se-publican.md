# ADR 0045 — Las piezas publicitarias de los medios no se guardan ni se publican

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** rastreo (peticion del usuario 2026-10-19)
- **Decide:** Constructor, auditado por el Critico

## Contexto
El usuario envia una captura de "Ultimo minuto" en nosmienten.com y pide: "Suprime la publicacion de
articulos de este tipo que son meramente publicitarios". En la captura, tres de cuatro piezas eran
guias de compra de los medios: "El secador de Cecotec que perfuma el cabello ... por menos de 40 euros"
(5 medios), "Los mejores cepillos y pastas dentales para la higiene bucal de tu perro y gato" (10) y
"Los mejores cepillos de dientes electricos baratos por menos de 30€" (11).

Los medios publican estas piezas (escaparate, showroom, branded content, chollos del dia, enlaces de
afiliado) en los mismos feeds RSS que sus noticias. El rastreo las guardaba como cualquier articulo, el
agrupador las unia entre medios (todas copian el mismo producto) y, con muchos medios en una hora,
subian a "Ultimo minuto" como si fueran lo mas contrastado del dia. No contienen nada que verificar.

## Decision
1. Un detector determinista, `truthnews/promo.py::is_promotional(titulo, extracto, url)`, reconoce una
   pieza comercial por cualquiera de estas senales sobre texto normalizado (sin tildes):
   - **Seccion de la URL**: `/escaparate/`, `/compras/`, `/showroom/`, `/branded/`, `/branded-content/`,
     `/ofertas/`, `/chollos/`, `/de-tiendas/`, `/comparador-financiero/`, `/comprar/`, contenido
     patrocinado...
   - **Senal fuerte en titular o extracto**: "por menos de N euros", "chollo(s) del dia", "oferta del
     dia", "codigo descuento", "ofertas del Black Friday / Prime Day", "contenido patrocinado", o una
     tienda (Amazon, El Corte Ingles, Lidl...) junto a oferta, descuento, rebaja o chollo.
   - **"Los/Las (N) mejores X"** que se dirige al lector como consumidor (tu, tus, comprar, baratos,
     calidad-precio, un precio), salvo rankings editoriales (momentos, goles, colegios, hospitales...).
2. **Rastreo**: las entradas nuevas que el detector marca no se guardan; el rastreo cuenta cuantas en
   `crawl_run.stats["promotional_skipped"]`.
3. **Lo ya guardado**: en cada agrupacion (`assign_stories`, ventana de 72 h) se borran los articulos
   marcados y las historias que se quedan sin articulos; el resumen lo cuenta en
   `promotional_removed`. Lo anterior a la ventana ya no aparece en portada ni en "Ultimo minuto".
4. Se prefiere dejar pasar una pieza dudosa a perder una noticia: las senales debiles que tambien usa
   la informacion economica ("rebajado", "por debajo de N euros", "N % de descuento", "Black Friday" a
   secas, "el chollo de...") no bastan.

Sin cambio de esquema: no hay columna nueva ni migracion; la capa de datos no cambia.

## Medida (2026-10-19, feeds reales del registro)
- Precision: 1.245 titulares de 60 medios nacionales; 13 marcados, los 13 publicitarios (El Pais
  branded, The Objective branded-content, El Independiente ofertas de Amazon, AS showroom). 0 falsos
  positivos.
- Revision de lo no marcado: 1.352 titulares de 140 medios filtrados por palabras sospechosas (euros,
  oferta, Amazon, mas vendido...); 37 candidatos, 3 publicitarios sin marcar (La Vanguardia `/comprar/`,
  Cinco Dias `/comparador-financiero/` x2), anadidos al detector. El resto son noticias con cifras en
  euros.
- Las tres piezas de la captura del usuario quedan marcadas (tests en `tests/test_promo.py`).

## Alternativas descartadas
- **Columna `is_promotional` o categoria "publicidad"**: permitiria auditar lo descartado, pero exige
  migracion y revision de datos para un contenido que no aporta nada al producto; el contador por ciclo
  basta para vigilar el filtro.
- **Clasificador con IA**: mas cobertura, pero coste por articulo y resultado no determinista; las
  piezas comerciales usan secciones y frases muy estables.
- **Ocultarlas solo en la portada**: seguirian ocupando historias, temas, sitemaps y redes.

## Consecuencias
- "Ultimo minuto", la portada, los temas, los sitemaps y las redes dejan de mostrar guias de compra.
- Una pieza comercial sin ninguna senal reconocible sigue entrando; se corrige anadiendo la senal al
  detector con su test.
