# ADR 0046 — Objetivos tactiles de 44 px en pantallas tactiles, sin mover el diseno

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** SEO y movil (encargo de la direccion 2026-10-19, dentro de la peticion del usuario "Si haz
  todo lo que sean mejoras en este aspecto")
- **Decide:** Constructor, auditado por el Critico

## Contexto
Medido en produccion (nosmienten.com, 2026-10-19 08:3x UTC) con Chromium headless en perfil movil
(412x823, pantalla tactil, CPU 4x mas lenta, red 4G lenta de 150 ms y 1,6 Mbit/s, sin cache; mediana
de 3 cargas) sobre portada, una historia, una verificacion y /quien-dice-la-verdad:

| Pagina | LCP | CLS | Peso | Peticiones | Contraste < AA | Tactiles < 44 px | < 24 px |
|---|---|---|---|---|---|---|---|
| `/` | 1052 ms | 0 | 24 KB | 6 | 0 de 532 textos | 23 | 14 |
| `/historia/24` | 1096 ms | 0 | 18 KB | 5 | 0 de 297 | 24 | 5 |
| `/verificacion/1` | 920 ms | 0 | 17 KB | 5 | 0 de 270 | 23 | 5 |
| `/quien-dice-la-verdad` | 932 ms | 0 | 15 KB | 5 | 0 de 207 | 13 | 5 |

El rendimiento ya esta muy por dentro de los umbrales "buenos" de Google (LCP < 2,5 s, CLS < 0,1): sin
fuentes web (system-ui y serif del sistema), dos imagenes SVG con dimensiones, un CSS y como mucho un
script; las imagenes OG no se cargan en la pagina (solo las leen las redes). No hay nada que perezosear
ni que recortar con beneficio medible.

Lo que falla son los **objetivos tactiles**: selector de idioma (16 px), logo (30), icono de portada
(26), barra de secciones (16), boton de menu (30), enlaces del menu (35), barra inferior (34), chips
(24), botones de compartir (27), desplegables (24-39), paginacion (17), saltos de seccion (26), enlaces
de la franja de ultimo minuto (15) y llamadas a fuentes `[1]` en los hilos (14). El minimo WCAG 2.2 AA
(2.5.8) es 24 px y la recomendacion de Apple/Google y WCAG AAA (2.5.5), 44 px.

## Decision
1. Todo va en un bloque `@media (pointer: coarse)` al final de `site.css`: el escritorio con raton no
   cambia (medido: misma altura de pagina, 4725 px la portada y 1890 px la historia).
2. **Bloques** (barra de secciones, menu, barra inferior, chips, compartir, desplegables, paginacion,
   saltos): `min-height: 44px` (y `min-width` en botones cortos como "X"), centrando el texto.
3. **Enlaces de linea o de una fila compacta** (idioma, logo, icono, enlaces de la franja de ultimo
   minuto, titulares enlazados, cifras de cabecera): relleno vertical con margen negativo igual. El area
   que se toca crece y las lineas no se mueven.
4. **Llamadas a fuentes dentro del texto** (`.cite`): un pseudoelemento absoluto amplia el area de toque
   sin cambiar el interlineado. Como el resto de enlaces dentro de una frase, quedan en la excepcion
   "en linea" de WCAG 2.5.8 y el medidor no las cuenta.
5. `[hidden]` sigue mandando en los botones de compartir (el boton nativo solo aparece si el navegador
   sabe compartir).

Coste visible en movil: la portada crece 10 px y una historia, 124 px (chips y botones mas altos). No se
quita contenido ni datos.

## Alternativas
- **24 px (minimo AA)**: cumple la norma, pero el encargo y las guias de plataforma piden 44; la
  diferencia en altura es pequena con el truco del margen negativo.
- **Agrandar tambien en escritorio**: el raton no necesita 44 px y cambiaria un diseno que funciona.
- **Reescribir componentes** (menu, chips) con otra disposicion: mas riesgo en ficheros compartidos de
  cinco carriles por el mismo resultado.

## Consecuencias
- Componentes nuevos con enlaces o botones: si van en bloque, `min-height: 44px` dentro del bloque
  `pointer: coarse`; si van en linea, relleno con margen negativo.
- Las medidas quedan publicadas en `docs/benchmarks/fase_m1.json` como suelo (ratchet).
- Siguiente mejora posible, sin urgencia: URL versionada y `Cache-Control` largo para `site.css` (hoy se
  revalida con ETag en cada visita; 1 peticion de pocos bytes).
