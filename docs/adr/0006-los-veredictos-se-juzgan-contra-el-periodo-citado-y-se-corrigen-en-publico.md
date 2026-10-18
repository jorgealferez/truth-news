# ADR 0006 — Los veredictos se juzgan contra el periodo citado y se corrigen en público

- **Estado:** aceptado (amplia el ADR 0004)
- **Fecha:** 2026-10-18
- **Fase:** 2 (correccion)
- **Decide:** Constructor, auditado por el Critico

## Contexto
Primer ciclo en produccion con el metodo del ADR 0004: un veredicto `falso` contra OKDIARIO ("el IPC del
4,3 % de agosto") porque se comparo con el ultimo dato (septiembre, 4,92 %) en vez del de agosto (4,28 %,
INE, calculado de la serie IPC290751). Reproducido en local con un rastreo fresco. Al revisar los datos
reales aparecio otro riesgo: "eurozona" se trataba como UE-27, y una frase con dos territorios ("6,4 %
en la eurozona y 6,1 % en la UE") podia atribuirse al equivocado.

## Decision
1. Si la frase cita un periodo (mes o trimestre, con o sin ano), el veredicto se compara con el dato
   oficial de ese periodo; si la serie no lo tiene, `sin-datos`. Las series guardan su historial.
2. Zona euro y UE son territorios distintos (Eurostat EA21/EA20/EA19 por orden, y EU27_2020). Una frase
   que nombra mas de un territorio no se atribuye.
3. Cada veredicto guarda la version del metodo (`.../v2`). En cada ciclo se vuelven a juzgar los de una
   version anterior; si cambia el veredicto, la explicacion publicada lo dice ("Corregido el ...: el
   veredicto anterior era ... por un error de nuestro metodo").

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Borrar el veredicto erroneo | Un medio de verificacion que corrige en silencio pierde credibilidad; la correccion visible es el estandar del oficio |
| Ignorar las frases con periodo | Perderia afirmaciones comprobables (el caso de OKDIARIO era correcto y verificable) |

## Consecuencias
El veredicto erroneo en produccion se corrige solo al desplegar (medido en local: `falso->verdadero`).
Requiere historial en las observaciones (14 periodos en Eurostat, 26 meses de indice en el INE).

## Verificacion
`tests/test_verify.py::test_cited_period_is_compared_with_that_period`,
`tests/test_claims.py::test_cited_periods` (caso real de OKDIARIO), casos de eurozona en el banco de
afirmaciones, `tests/test_pipeline.py::test_reverify_outdated_methods_and_note_corrections`.
