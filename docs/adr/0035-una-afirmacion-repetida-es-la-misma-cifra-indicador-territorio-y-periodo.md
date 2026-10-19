# ADR 0035 — Una afirmación repetida es la misma cifra sobre el mismo indicador, territorio y periodo

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** ítem del ledger «Afirmaciones que se repiten» (carril Comparativas)
- **Decide:** agente Comparativas, auditado por el Crítico

## Contexto
Encargo de la dirección (2026-10-19), tomado de Full Fact: seguir las afirmaciones que se repiten entre
medios y días y enlazarlas con su veredicto cuando lo haya. Una cifra falsa que se repite pesa más que una
que sale una vez, y una verdadera que todos repiten es consenso con prueba.

Medido en producción el 2026-10-19 (`/verificaciones`): hay 13 afirmaciones verificadas. De las 8 cuyo
indicador, territorio, periodo y cifra se pueden leer en la página, ninguna se repite todavía.

## Decisión
1. **La misma afirmación** es la que coincide en indicador, territorio, unidad y periodo citado (ADR 0019),
   con el valor redondeado a una décima. No se compara la redacción: «la inflación está en el 4,9 %» y «el
   IPC sube un 4,9 % en septiembre» son la misma cifra sobre el mismo dato.
2. **Se repite** cuando aparece en al menos 2 artículos distintos. Dos veces en el mismo artículo no
   cuenta.
3. **Veredicto**: el más reciente con dato oficial (verdadero, impreciso, falso o engañoso) de las
   verificaciones del grupo. Aquí no se juzga nada (ADR 0007): solo se agrupa, se cuenta quién la repite y
   cuándo, y se enlaza la evidencia.
4. **Dónde se ve**:
   - Página `/repetidas`, ordenada por número de medios, con la cifra, el indicador, el territorio y el
     periodo, el veredicto, cada aparición (medio, fecha, frase citada y enlace a la ficha) y la evidencia.
   - En la historia, el bloque «Esta afirmación se repite en otros medios».
   - Enlace en el pie del sitio.

Se calcula en lectura sobre `claim`, sin esquema nuevo.

## Alternativas consideradas
| Alternativa | Por qué no |
|---|---|
| Agrupar por frase parecida (similitud de texto) | La misma cifra se redacta de muchas formas, y frases parecidas con cifras distintas son afirmaciones distintas |
| Incluir cualquier cifra contable de las noticias (detenidos, euros...) | Sin indicador ni periodo no se sabe si es la misma afirmación (ADR 0016); queda para cuando haya una referencia común |
| Tabla de grupos precalculada | Con decenas o cientos de afirmaciones la consulta en lectura cuesta milisegundos; si crece, ADR de datos |

## Consecuencias
- Hoy la página está vacía y lo dice. Se llenará a medida que el carril Verificaciones extraiga más
  afirmaciones.
- Dos periodos escritos de forma distinta para el mismo dato («2026-09» y «septiembre») no se agrupan si la
  extracción no los normaliza. Depende de la normalización del ADR 0019.

## Verificación
`tests/test_repeated.py`: misma cifra a una décima en dos artículos, territorio y periodo distintos,
mismo artículo, veredicto más reciente con dato, página, bloque en la historia y página vacía.

## Precisión (2026-10-19, condición de la aprobación de la dirección)
La clave incluye también el **hablante o la fuente citada** (`claim.speaker_entity_id`). La misma cifra
dicha por un ministro y por una ONG son dos afirmaciones distintas; las que no tienen hablante atribuido
se agrupan entre sí. La tarjeta muestra «dicho por» cuando lo hay. Test:
`tests/test_repeated.py::test_group_same_figure_in_two_articles`.
