# ADR 0051 — Dos cifras solo se comparan con el mismo territorio y partido, y el dinero no abre disputa

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** ítem del ledger «Crecer el fixture de disputas con producción» (carril Comparativas)
- **Decide:** agente Comparativas, auditado por el Crítico
- **Amplía:** ADR 0016 (solo se comparan cifras del mismo hecho)

## Contexto
Encargo de la dirección (2026-10-19): crecer el fixture de disputas con casos reales en que los medios dan
cifras que no cuadran, con URL, fecha y cifra oficial cuando exista, y mejorar el juicio **solo con reglas**
(sin IA). Se añadieron 13 historias de producción del 18-19/10 (197 artículos) a
`tests/fixtures/disputes.json`, cada cifra etiquetada a mano con el hecho del que habla.

Con las reglas del ADR 0016 (orden de magnitud y «según»), en esas 13 historias salían 13 disputas y 7 eran
falsas (precisión 0,462; por pares 0,138):

| Historia | Lo que se juntaba | Por qué no es el mismo hecho |
|---|---|---|
| 11626 ozono | 190, 300, 500, 500 y 200 muertes | Navarra, Aragón, Castilla y León, Hego Euskal Herria y Asturias |
| 12084 CIS andaluz | 20 y 53 escaños; 5 y 10 escaños | Vox frente al PP; lo que pierde el PSOE frente a Adelante Andalucía |
| 11478 renta | 16.000, 32.612, 28.607, 13.407, 15.500, 20.000 euros | Media de España, Pozuelo, Matadepera, un umbral, Galicia, una diferencia |
| 10022 alquiler | 700 y 1.000 euros | «Por debajo de 700» y «superan los 1.000»: dos umbrales |
| 7367 luz | 300 y 215,12 euros/MWh | La hora más cara y la media del día |
| 8448 IMV | 16.365 y 8.500 euros | Dos mujeres, dos sentencias |

## Decisión
1. **Territorio.** De la frase de cada cifra se leen las comunidades autónomas, sus provincias y capitales,
   y «España». Si las dos cifras tienen territorio y los conjuntos no se cruzan, son hechos distintos. Si se
   cruzan («dos muertos en Cataluña y la Comunidad Valenciana» frente a «tres en la Comunidad Valenciana») o
   una no tiene, decide el orden de magnitud como antes. El lugar de la data («Madrid, 19 oct (EFE).-») no
   cuenta. Solo territorios españoles: «París» frente a «Francia» no se puede decidir sin jerarquía.
2. **Partido.** En escaños y votos, el partido más cercano antes de la cifra en su frase (o el primero
   después si no hay antes). Partidos distintos, hechos distintos.
3. **Dinero.** Una cantidad en euros no es un recuento: en una noticia conviven medias, umbrales, multas y
   precios. Sin indicador ni periodo (eso lo hacen las verificaciones, ADR 0019) no se sabe si dos cifras
   son el mismo dato, así que **no se abre disputa**; si varios medios dan la misma cantidad, se dice que
   coinciden.
4. La frase de una cifra del arranque se lee entera aunque pase del corte de 400 caracteres (hasta 300 más).
5. Nueva medida de **agrupación** (`grouping_quality`): por cada par de medios con el mismo sustantivo, si
   el comparador los pone en el mismo hecho como dice la etiqueta. Entra en el presupuesto
   (`disputas_agrupacion` ≥ 0,95).

## Medida (docs/benchmarks/fase_2h.json)
| Muestra | Antes: disputas, precisión, por pares, exhaustividad, agrupación | Después |
|---|---|---|
| 15 historias del 17-18/10 | 5; 1,00; 1,00; 5/5; 1,00 | igual |
| 13 historias del 18-19/10 | 13; 0,462; 0,138; 6/6; 0,593 | 6; 1,00; 1,00; 6/6; 0,986 |
| Total | 18; 0,611; 0,514; 11/11; 0,797 | 11; 1,00; 1,00; 11/11; 0,993 |

Cada regla sola, en las 13 nuevas: dinero 0,667; territorio 0,50; partido 0,545. Los 5 pares de agrupación
que quedan mal son el 53 de El Mundo (escaños del PP en las elecciones de mayo) junto al 53 de la encuesta:
coinciden, no abren disputa.

**Aviso:** las 13 historias se usaron también para diseñar las reglas; es una medida dentro de la muestra.

## Alternativas consideradas
| Alternativa | Por qué no |
|---|---|
| Pedir a la IA si dos cifras son el mismo hecho | Sin crédito, y la dirección pide reglas |
| Exigir el mismo territorio exacto | Separa balances reales («Cataluña y Valencia» frente a «Valencia»), que siguen siendo una disputa |
| Separar el dinero por palabras («media», «umbral», «por persona») | Cubre los casos vistos y falla en el siguiente; sin indicador no hay forma segura de decidirlo |
| Gazetteer con ciudades del mundo | «París» y «Francia» se cruzarían como distintos y romperían las disputas reales de las protestas |

## Consecuencias
- Desaparecen de las fichas las disputas de euros. Una discrepancia real en euros (dos multas distintas por
  el mismo caso) ya no se marca aquí; si es un dato oficial, la recoge la verificación.
- Dos casos distintos del mismo sustantivo, sin territorio ni partido y en el mismo orden de magnitud,
  siguen juntándose (con detenidos o muertos; el caso 8448 solo se separa porque es dinero).
- Sin esquema nuevo: el territorio y el partido se calculan en lectura (`Figure.territory`, `Figure.party`).

## Verificación
`tests/test_compare.py::test_territory_party_and_money_keep_facts_apart` (ozono por comunidad, CIS por
partido, alquiler en euros, data de agencia) y
`tests/test_compare.py::test_dispute_precision_on_real_labeled_stories` (precisión, por pares y
exhaustividad ≥ 0,95 con 11 disputas esperadas; agrupación ≥ 0,99 sin separar nada por error).
