# ADR 0014 — El simbolo es la "n medida": una n cuyo arco baja hasta una vara graduada

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** marca v2 (peticion del usuario, fuera de las fases de la carta)
- **Decide:** Constructor, auditado por el Critico; el usuario eligio la propuesta entre varias
- **Revisa:** ADR 0011 (solo el simbolo; logotipo, paleta, lema e imagen social siguen igual)

## Contexto
El usuario pide un icono "mas identificativo, menos generico y mas profesional", "algo que podamos
registrar y sea recordable como algo unico", agnostico a partidos e ideologias: "solo un medio donde
verificar datos". El simbolo del ADR 0011 (un cuadrado de tinta con dos barras) se leia como un icono de
"texto" o de menu: no era propio ni registrable. Se prototiparon un nivel de burbuja (tambien generico) y
un monograma; el usuario eligio el monograma con la regla ("me gusta la vara de medir") y pidio mantener
el resto de la marca como estaba, por ser mas formal.

## Decision
El simbolo es la **"n medida"**, monograma de nosmienten:

- El **arco de la n** (tinta) es lo que se cuenta; baja hasta una **vara ambar** (lo que se mide),
  separada del arco por un corte limpio: es un instrumento apoyado en la letra.
- La vara lleva **graduacion por dentro**, larga-corta-larga-corta-larga, recortada con el color del
  fondo. Las primeras pruebas con tres marcas que cruzaban la vara se leian como una "E" ("nE"); cinco
  marcas finas de longitud alterna se leen como regla y no forman ninguna letra.
- Geometria en una rejilla de 64 (caja 12-52 x 10-54): tallos de 10, arco de radio 20/10, vara de 10.
  Una sola fuente de verdad en `tools/brand.py` (`glyph`), replicada en `truthnews/web/social.py`.
- **Version pequena** (`favicon.svg`, `favicon.ico` 16/32/48): la misma n sin graduacion sobre placa de
  papel, porque a 16 px las marcas solo son ruido.
- **Iconos**: sobre papel (la marca vive en claro); `icon-180.png` opaco para iOS, `icon-192/512.png`,
  `icon-maskable-512.png` con zona segura (declarado `purpose: maskable` en el manifest) y
  `avatar-400.png` para la foto de perfil en redes, que se recorta en circulo.
- Sin cambios: logotipo "nos" Medium + "mienten" ExtraBold + ".com" en ambar oscuro, paleta tinta /
  papel / ambar, lema "Sin bandos. Con datos." e imagen social por defecto.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Mantener las dos barras (ADR 0011) | Se leia como icono generico de texto o menu; nada propio que registrar |
| Nivel de burbuja (burbuja centrada: "sin inclinacion") | Buena idea de neutralidad, pero es un icono de herramienta comun, poco distintivo |
| Lupa o marca de verificacion | Iconografia de todos los verificadores (ya descartada en el ADR 0011) |
| Rediseno completo (punto de la i ambar, regla como recurso grafico, nombre en un solo peso) | Probado y descartado por el usuario: "el resto dejalo como estaba, que era mas formal" |

## Consecuencias
Signo figurativo propio, ligado al nombre (la n) y a la tesis del medio (medir lo que se cuenta),
candidato a registro como marca figurativa o mixta. El registro (OEPM o EUIPO; clases orientativas 9,
38, 41 y 42) y la busqueda de anterioridades son tramites del usuario: este repositorio no puede
verificar que no exista un signo parecido registrado (NO VERIFICADO). Los PNG se regeneran con
`python tools/brand.py` (dependencias solo de desarrollo: fontTools, cairosvg).

## Verificacion
`tests/test_web.py::test_brand_assets_and_social_meta`: favicon SVG enlazado, icono adaptable en el
manifest y todos los activos servidos; `test_social_image_*`: la imagen por historia se sigue generando
con el simbolo nuevo. Revision visual de 16, 32, 48, 64, 180 y 512 px en la sesion.
