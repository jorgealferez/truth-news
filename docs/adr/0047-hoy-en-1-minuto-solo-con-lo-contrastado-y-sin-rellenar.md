# ADR 0047 — "Hoy en 1 minuto" se arma solo con lo contrastado y no se rellena

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** item del ledger "Hoy en 1 minuto" (asignado por la direccion 2026-10-19 08:37)
- **Decide:** Constructor, auditado por el Critico

## Contexto
Peticion central del usuario: "verificaciones, sintetizar datos y dar mascado al publico". Ya existen
las piezas sueltas: cada verificacion tiene su frase (`web/verdicts.sentence`) y su pagina
(`/verificacion/{id}`), y cada historia con contraste guarda sus cifras en disputa (ADR 0012). Falta una
vista de un minuto que reuna lo del dia y sirva de pieza diaria para redes.

## Decision
1. **`/hoy`**: hasta 5 claves de las ultimas 24 h. Cada una lleva la frase, la cifra que circula, la
   oficial con su periodo, el veredicto, la fuente (con enlace) y el enlace a la verificacion o a la
   historia.
2. **Solo lo contrastado.** Primero las verificaciones falsas o enganosas, despues las imprecisas y las
   verdaderas (con evidencia oficial enlazada y con valor); al final, las cifras en disputa entre medios,
   diciendo que no hay dato oficial con que contrastarlas. Un indicador o una historia salen una vez.
3. **La frase no la escribe nadie.** Es `verdicts.sentence`, una plantilla que se rellena solo con los
   datos guardados (quien, cifra, dato oficial, periodo, fuente). La IA no interviene. Asi, por
   construccion, no puede aparecer una cifra ni un juicio que no esten en la base. La direccion permitia
   que la IA redactara sin aportar cifras; no hace falta y elimina el riesgo.
4. **Sin relleno.** Si en 24 h no hay nada contrastado, la pagina, el RSS y la imagen lo dicen ("Hoy
   todavia no hay nada contrastado con datos oficiales. No rellenamos.").
5. **Formatos:** `/hoy.xml` (RSS propio), `/og/hoy-vertical.png` (1080x1350), `/og/hoy-cuadrada.png`
   (1080x1080, menos lineas por clave) y `/og/hoy-horizontal.png` (1200x630, `og:image` de la pagina).
   Las imagenes se cachean por dia y conjunto de claves.
6. **Redes:** sera la pieza diaria de la autopublicacion (en modo prueba hasta que haya credenciales). Eso
   necesita un `kind` nuevo en `social_post` y va en un cambio aparte, con su ADR de datos.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Frase redactada por IA con control de cifras | Mas riesgo que la plantilla y ninguna ventaja medible: la plantilla ya dice lo esencial en una frase |
| Rellenar con las historias mas leidas si no hay verificaciones | Contra la esencia: solo se publica lo contrastado |
| Elegir por "dia natural" de Madrid | Una ventana movil de 24 h evita que a las 00:05 la pagina quede vacia |

## Consecuencias
- Si hay pocas verificaciones con valor oficial, la pagina tendra pocas claves o ninguna: es lo correcto,
  y mide la cobertura del carril Verificaciones.
- El equilibrio de lo publicado (ADR 0043) se aplica cuando la pieza entre en la autopublicacion.

## Verificacion
`tests/test_today.py`: dia vacio que lo dice (pagina e imagen), orden y deduplicacion, verificacion sin
enlace a la fuente fuera, disputa sin dato oficial, RSS, tamanos de las tres imagenes, formato
inexistente 404 y la pagina en ingles.
