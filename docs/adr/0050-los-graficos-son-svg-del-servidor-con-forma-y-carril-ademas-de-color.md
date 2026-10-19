# ADR 0050 — Los graficos son SVG del servidor, con forma y carril ademas de color

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** 9 (quien miente, quien informa), item "Graficos de entidad e historia" del ledger
- **Decide:** sesion Entidades (numero asignado por la direccion), auditado por el Critico

## Contexto
El usuario pide "muy grafico, sobre todo en movil". La direccion encarga (2026-10-19 10:13 UTC) dos graficos
con los datos del carril Entidades: lo que dijo cada persona y cuando, coloreado por veredicto, y "la cifra
en el tiempo" de una historia frente al dato oficial; sin JS ni librerias, accesibles y ligeros (suelo
movil de SEO, fase_m1).

## Decision
1. **SVG generado en Python** (`truthnews/web/charts.py`), incrustado en el HTML: 0 peticiones extra, 0 JS,
   1-2,5 KB por grafico (medido). `viewBox` de 360 de ancho y `width:100%` (tope 640 px): en un movil de
   390 px el texto de 11 unidades se lee a ~12 px.
2. **Lo que dijo y cuando** (ficha de entidad): un carril por veredicto con su nombre y su recuento escritos
   (falso o enganoso, impreciso, verdadero, sin comprobar), cada afirmacion un punto en su fecha que enlaza
   a `/verificacion/<id>` (o a la noticia si es una frase sin comprobar).
3. **El color no es la unica pista.** Los colores de veredicto son los de la web (estado); el validador de
   paleta da verde/ambar ΔE 4,8 con protanopia (FAIL), asi que la identidad va tambien por **carril con
   etiqueta** y por **forma**: cuadrado (falso/enganoso), triangulo (impreciso), circulo (verdadero), anillo
   (sin comprobar). No se cambian los colores de la marca.
4. **La cifra en el tiempo** (historia): primero las afirmaciones con dato oficial (cada medio en su hora
   frente a la linea discontinua del dato, con fuente y periodo), despues las cifras en disputa del mismo
   hecho (ADR 0016) y las cifras que una noticia cambio tras publicarse (revisiones, ADR 0015: anillo del
   valor anterior unido al nuevo). Etiquetas solo en los extremos; maximo 3 graficos por historia.
5. **Accesibilidad**: `role="img"` con `<title>` y `<desc>` que contienen los numeros; cada punto con su
   `<title>` (detalle al pasar el raton sin JS); la pagina conserva la lista o tabla con el mismo contenido.
6. **Coste**: las revisiones de la historia se leen en una sola consulta. Medido con `tools/bench_web.py`
   (10.000 noticias): historia p50 26 ms en la rama frente a 27-29 ms en main en la misma maquina.

## Consecuencias
- Un SVG sin JS no tiene cruz de lectura ni filtros; el detalle va en el `<title>` de cada punto y en la
  lista de la pagina. Si hiciera falta mas, se anadira sin cambiar el formato.
- Con pocas afirmaciones comprobadas, la linea de "lo que dijo" se llena sobre todo de frases sin comprobar;
  crece con el carril Verificaciones.
