# ADR 0053 — Dos cifras solo se comparan si cuentan lo mismo, del mismo territorio y partido

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** ítem del ledger «Crecer el fixture de disputas con producción» (carril Comparativas)
- **Decide:** agente Comparativas, auditado por el Crítico
- **Amplía:** ADR 0016 (solo se comparan cifras del mismo hecho)

## Contexto
Encargo de la dirección (2026-10-19): crecer el fixture de disputas con casos reales en que los medios dan
cifras que no cuadran, con URL, fecha y cifra oficial cuando exista, y mejorar el juicio **solo con reglas**
(sin IA). Condición añadida: medir también **fuera de muestra**, con historias que no se miraron al diseñar
las reglas; si ahí la precisión baja de 0,8, decirlo y ajustar antes del merge.

Se añadieron 13 historias de producción del 18-19/10 (197 artículos) a `tests/fixtures/disputes.json`, cada
cifra etiquetada a mano con el hecho del que habla. Con las reglas del ADR 0016, en esas 13 salían 13
disputas y 7 eran falsas (precisión 0,462; por pares 0,138):

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
4. **Lo que les pasó, no quiénes son.** Con migrantes, soldados, agentes, policías y manifestantes, si lo
   que sigue a la cifra dice qué les pasó («500 policías heridos», «500 migrantes desalojados») cuenta eso;
   antes de la cifra solo vale un verbo de morir («mueren 12 inmigrantes»), porque un participio de antes es
   de la cifra anterior («1.800 personas detenidas y 500 policías»: los 500 no son detenidos). Es la regla
   que ya tenía «personas», sin descartar la cifra si no hay contexto.
5. **Solo castellano.** Las cifras se leen en artículos en castellano: en portugués «dos votos» no son dos y
   «morreram» no es un verbo que el extractor conozca.
6. La frase de una cifra del arranque se lee entera aunque pase del corte de 400 caracteres (hasta 300 más).
7. **Medidas.** Además de la precisión y la exhaustividad de las disputas, la **agrupación**
   (`grouping_quality`): por cada par de medios con el mismo sustantivo, si el comparador los pone en el
   mismo hecho como dice la etiqueta. Entra en el presupuesto (`disputas_agrupacion` ≥ 0,95).
8. **Diseño y validación separados.** `tests/fixtures/disputes.json` es el conjunto con el que se diseñan
   las reglas y la puerta exige ≥ 0,95. `tests/fixtures/disputes_validacion.json` guarda las muestras fuera
   de muestra: se miden y se publican, no se ajustan para que pasen, y cada muestra dice si después se usó
   para ajustar.

## Medida (docs/benchmarks/fase_2h.json)
| Muestra | Antes (ADR 0016) | Reglas 1-3 | Reglas 1-6 |
|---|---|---|---|
| Diseño: 15 historias del 17-18/10 | 5 disputas, precisión 1,00 | 1,00 | 1,00 |
| Diseño: 13 historias del 18-19/10 | 13 disputas, precisión 0,462 (pares 0,138) | 6 disputas, 1,00 | 1,00 |
| Fuera de muestra 1: 15 historias del 19/10 (190 artículos) | 5 disputas, precisión 0,20 | **3 disputas, 0,333** | 2 disputas, 0,50 |

Exhaustividad 1,00 en todas (11 disputas reales en diseño, 1 en la muestra 1). La muestra 1 se midió limpia
con las reglas 1-3 (0,333, bajo 0,8) y **después** se usó para ajustar (reglas 4 y 5), así que la columna de
la derecha ya no es fuera de muestra. El error que queda es 9640: «seis migrantes» de un naufragio frente a
«doce» de los dos: la parte y el todo, que ninguna de estas reglas distingue. La segunda muestra limpia se
publica en el mismo benchmark.

## Alternativas consideradas
| Alternativa | Por qué no |
|---|---|
| Pedir a la IA si dos cifras son el mismo hecho | Sin crédito, y la dirección pide reglas |
| Exigir el mismo territorio exacto | Separa balances reales («Cataluña y Valencia» frente a «Valencia»), que siguen siendo una disputa |
| Separar el dinero por palabras («media», «umbral», «por persona») | Cubre los casos vistos y falla en el siguiente; sin indicador no hay forma segura de decidirlo |
| Gazetteer con ciudades del mundo | «París» y «Francia» se cruzarían como distintos y romperían las disputas reales de las protestas |
| Leer el contexto de antes también con participios («desalojados 500 migrantes») | Arrastra el participio de la cifra anterior («1.800 detenidas y 500 policías») |
| Meter la muestra de validación en el fixture con puerta | Una muestra con la que no se diseña no debe ajustarse para pasar una puerta; se publica |

## Consecuencias
- Desaparecen de las fichas las disputas de euros. Una discrepancia real en euros (dos multas distintas por
  el mismo caso) ya no se marca aquí; si es un dato oficial, la recoge la verificación.
- La parte y el todo («seis en un naufragio», «doce en los dos») siguen juntándose.
- Los artículos en portugués no aportan cifras a las disputas.
- Sin esquema nuevo: el territorio y el partido se calculan en lectura (`Figure.territory`, `Figure.party`).

## Verificación
`tests/test_compare.py::test_territory_party_and_money_keep_facts_apart` (ozono por comunidad, CIS por
partido, alquiler en euros, lo que les pasó, data de agencia),
`tests/test_compare.py::test_dispute_precision_on_real_labeled_stories` (diseño: precisión, por pares y
exhaustividad ≥ 0,95 con 11 disputas esperadas; agrupación ≥ 0,98) y
`tests/test_compare.py::test_dispute_validation_set_is_measured` (validación separada del diseño).
