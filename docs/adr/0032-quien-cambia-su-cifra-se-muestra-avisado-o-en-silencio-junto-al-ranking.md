# ADR 0032 — Quien cambia su cifra se muestra, avisado o en silencio, junto al ranking y no dentro

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** ítem del ledger «Quién cambió su cifra» (carril Comparativas)
- **Decide:** agente Comparativas, auditado por el Crítico

## Contexto
Encargo de la dirección (2026-10-19): cruzar las revisiones de titular y extracto (ADR 0015) con las cifras
(ADR 0016) para saber qué medio corrige un balance, cuándo, y si lo avisa o lo cambia en silencio, y
mostrarlo en la historia, en la ficha del medio y como señal del ranking (ADR 0021), con el mismo cuidado
estadístico.

Medido en producción el 2026-10-19: en las fichas de 21 medios hay 49 revisiones detectadas. Solo una
cambia una cifra: BBC Mundo pasó en su titular de «1.800 detenidos» a «2.400 detenidos» sin indicarlo. La
medida destapó además un fallo de lectura. En «Carney confirmó cuatro muertos. Otras 39 personas
resultaron heridas» (France 24), los 39 se leían como muertos porque el contexto de «personas» cruzaba la
frase, y eso habría convertido un extracto ampliado en un falso «cambio de 4 a 39 muertos».

## Decisión
1. **Cambio de cifra**: una revisión cambia una cifra si la primera cifra de un mismo sustantivo
   (detenidos, muertos, euros...) vale distinto antes y después. Si el sustantivo solo aparece en una de las
   dos versiones, no cuenta: ampliar un extracto no es cambiar una cifra.
2. **Avisado o en silencio**: «avisado» si el texto nuevo, y no el anterior, dice que actualiza (actualiza,
   rectifica, corrige, fe de errores, nuevo balance, eleva a, asciende a, ya son...). Si no, «en silencio».
3. **Directos fuera**: si el titular o una de las versiones es un directo, no cuenta, porque su titular
   rota sin que eso sea una corrección (hallazgo del 2026-10-19 en el ledger).
4. **Dónde se ve**:
   - En la historia, «Quién cambió su cifra»: la cifra de antes tachada y la de después, la cita de cada
     versión con su fecha (la de antes es la captura previa: la revisión anterior del mismo campo o la
     primera captura) y el enlace a la ficha de captura.
   - En la ficha del medio, la misma lista.
   - En el ranking, «cifras cambiadas en silencio: s de n» junto a la exactitud.
5. **No entra en la exactitud del ranking**. Actualizar un balance no es un error y la exactitud solo se
   mide contra datos oficiales (ADR 0021). La proporción en silencio no se da como porcentaje con menos de
   5 cambios (`MIN_CHANGES`).
6. **Lectura de cifras**: el contexto que decide qué son «personas» se limita a la frase de la cifra, y se
   mira primero lo que la sigue («39 personas resultaron heridas» son heridos).

Se calcula en lectura sobre `article_revision`, sin esquema nuevo.

## Alternativas consideradas
| Alternativa | Por qué no |
|---|---|
| Restar puntos de exactitud por cambiar una cifra | Penalizaría actualizar un balance, que es buena práctica; la exactitud se mide contra datos oficiales |
| Contar cualquier cambio de titular | El 98 % de las revisiones medidas no tocan cifras (redacción, SEO); mezclarlas tapa la señal |
| Detectar el aviso con IA | El aviso se escribe con un puñado de fórmulas; una lista reproducible basta y se audita (ADR 0007) |
| Tabla de cambios de cifra precalculada | Con 60-150 revisiones al día (ADR 0015) el cálculo en lectura cuesta milisegundos |

## Consecuencias
- Hoy hay muy pocos casos (1 de 49 revisiones). La señal crecerá con los ciclos del rastreador, y la
  proporción en silencio de cada medio no se publica hasta tener 5 cambios.
- Un aviso redactado de otra forma («cifra corregida tras...») se contaría como silencio. La lista crece
  con cada caso que se encuentre.
- Solo se ven los cambios entre capturas. Lo que el medio cambia antes de nuestra primera captura no se ve.

## Verificación
`tests/test_figure_changes.py` (casos reales BBC Mundo y France 24, avisos, directos, muestra mínima,
consultas y páginas) y `tests/test_compare.py::test_personas_context_stays_in_its_sentence`.
