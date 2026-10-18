# ADR 0011 — La marca es nosmienten.com: sobria, neutral y dibujada en contornos

- **Estado:** aceptado
- **Fecha:** 2026-10-18
- **Fase:** 6
- **Decide:** Constructor, auditado por el Critico

## Contexto
El usuario tiene el dominio nosmienten.com y pide "una imagen de marca solida y profesional, neutral a
nivel politico pero creible socialmente a nivel de masas", y despues prioriza "cambiar imagen de marca y
logotipos". El nombre es combativo; la identidad tiene que compensarlo con sobriedad y con un metodo
visible. La paleta anterior usaba un rojo (#b3001b) como acento: en Espana el rojo, el azul, el verde, el
morado y el magenta se asocian a partidos concretos.

## Decision
La marca es **nosmienten.com** (SITE_NAME `NosMienten`, SITE_DOMAIN `nosmienten.com`):

- **Simbolo**: un cuadrado de tinta con dos barras, la inferior mas corta y en ambar — lo que se cuenta y
  lo que dicen los datos no siempre miden lo mismo. Es geometria pura (`mark.svg`), legible a 16 px.
- **Logotipo**: simbolo + "nos" (Inter Medium) + "mienten" (Inter ExtraBold) + ".com" en ambar oscuro,
  convertido a contornos SVG (`logo.svg`) para que no dependa de las fuentes del lector. Inter es OFL 1.1.
- **Paleta**: tinta #14161b, papel #fbfaf6, ambar #e8a317 solo para superficies y barras, y su version
  oscura #8a5a00 para texto (5,67:1 sobre papel, WCAG AA). Los colores de los veredictos no cambian:
  son semantica, no marca.
- **Lema**: "Comparamos lo que cuentan los medios con lo que dicen los datos" y "Sin bandos. Con datos."
  La pagina "Que es esto" explica que el nombre no senala a nadie: es la pregunta del lector, respondida
  con el mismo metodo para todos los medios.
- **Activos**: favicon (SVG + ICO), iconos 180/192/512, manifest, imagen social por defecto 1200x630 y
  metadatos Open Graph / Twitter en todas las paginas. Se regeneran con `tools/brand.py`.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Marca neutra distinta (p. ej. "Contraste") con nosmienten.com como dominio de campana | El usuario ya eligio el dominio; dos nombres dividen el reconocimiento |
| Mantener el rojo como acento | Connotacion partidista y de alarma; contradice "neutral" |
| Logotipo con texto y fuente web | Depende de que cargue la fuente; los contornos pesan 4 KB y se ven igual en todas partes |
| Lupa o marca de verificacion como simbolo | Iconografia generica de verificadores; no cuenta la idea de comparar |

## Consecuencias
Identidad reconocible y coherente en web, redes y pestana del navegador sin cargar fuentes externas. El
dominio propio se conecta en Railway; los registros DNS los configura el usuario en su registrador. El
User-Agent del rastreador se mantiene hasta que nosmienten.com resuelva, para no publicar una URL rota.
Las imagenes sociales por pieza (titular + veredicto) quedan para la Fase 4.

## Verificacion
`tests/test_web.py`: contraste WCAG de los colores de texto de la paleta (metrica
`marca_contraste_texto_min` >= 4.5, con ratchet) y presencia del logotipo, favicon, manifest y metadatos
sociales.
