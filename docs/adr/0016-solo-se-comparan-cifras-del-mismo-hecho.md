# ADR 0016 — Solo se comparan cifras del mismo hecho

- **Estado:** aceptado (precisa el punto 2 del ADR 0004)
- **Fecha:** 2026-10-19
- **Fase:** 2 (motor de contraste), item "Comparativas mejores" del ledger
- **Decide:** agente Comparativas, auditado por el Critico

## Contexto
El ADR 0004 marca como "cifra en disputa" cualquier par de valores del mismo sustantivo (detenidos,
migrantes...) que difieran mas de un 10 % entre medios de una historia. En produccion (2026-10-19) la
historia "Ceuta desaloja a unos 500 migrantes" mostraba una disputa 500 frente a 12: los 12 eran los
migrantes que una mujer oculto en su casa, otro hecho. Decir que dos medios discrepan cuando hablan de cosas
distintas es acusar sin prueba, lo contrario de la esencia del proyecto.

Medido sobre 15 historias reales de produccion (152 articulos, titular y resumen, rastreo del 17-18/10),
etiquetando a mano de que hecho habla cada una de sus cifras (`tests/fixtures/disputes.json`): de 8 disputas
publicadas, 4 mezclaban hechos distintos.

| Disputa publicada | Que pasaba |
|---|---|
| Migrantes 500 / 12 (Ceuta) | 12 = ocultados en una casa, no el desalojo |
| Detenidos 50 / 2.000 (protestas en Europa) | 50 en Milan, 2.000 en Francia |
| Migrantes 2 / 177 (cayucos en El Hierro) | 2 fallecidos en un cayuco, 177 a bordo de otro |
| Detenidos 855 / 400 / 1.800-2.400 (Francia) | de un mismo articulo contaba la ultima cifra: "Paris registro 855" sustituia a "Mas de 1.800" del titular; "400 por saqueos" es un desglose |

## Decision
Dos cifras del mismo sustantivo solo se comparan si pueden hablar del mismo hecho:
1. **De cada articulo cuenta la primera cifra de cada sustantivo** (la del titular si la hay); el resto suele
   ser un desglose. De cada medio sigue contando su ultimo articulo (un balance se actualiza).
2. **Orden de magnitud**: dos cifras que se diferencian en mas de 3 veces y en mas de 10 unidades son hechos
   distintos. Un balance que se actualiza (2 -> 3 muertos, 1.800 -> 2.400 detenidos) o una discrepancia real
   (5 frente a 15 heridos) quedan dentro.
3. **Excepcion: recuentos atribuidos**. Si las dos cifras se atribuyen a una fuente ("segun la Delegacion del
   Gobierno" / "segun los organizadores"), son versiones del mismo recuento y si se comparan.
4. Las cifras de un sustantivo se reparten en hechos anclando en la cifra que mas medios dan; el hecho que mas
   medios cuentan conserva el rotulo ("detenidos") y otro hecho disputado se rotula aparte ("detenidos ·2").
   Lo que no es disputa y comparten varios medios pasa a "en lo que coinciden".

Tambien se reconoce "la detencion de N personas" como detenidos.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Comparar el contexto de cada cifra (palabras cercanas) | Las versiones del mismo hecho usan palabras distintas ("desaloja" / "desalojados" / "cifra en"), y el vocabulario comun de la historia ("cayuco", "Francia") aparece tambien junto a las cifras de otro hecho. Sin texto completo no discrimina |
| Lugar nombrado junto a la cifra (Paris frente a Francia) | Exige un nomenclator de ciudades; el caso real se resuelve con la regla 1 y no hay otro en la muestra |
| Pedir a un LLM si dos cifras son el mismo hecho | Coste por historia y no reproducible (ADR 0007); se puede reevaluar como segunda opinion con la clave |
| Subir el umbral del 10 % | No separa hechos: 12 frente a 500 seguiria siendo disputa |

## Consecuencias
- Precision de disputas sobre la muestra etiquetada: **0,50 -> 1,00** (por pares: 0,724 -> 1,00); exhaustividad
  sobre las 5 disputas reales de la muestra: **1,00 -> 1,00**. La muestra se uso tambien para disenar la regla:
  la medida en datos nuevos puede ser menor; el fixture crece con cada caso que se detecte en produccion.
- Una discrepancia real de mas de 3 veces sin atribucion (p. ej. un balance que pasa de 3 a 40 muertos) deja
  de marcarse como disputa: se prefiere callar a acusar sin prueba.
- La puntuacion de contraste (ADR 0012) cuenta cada hecho disputado; el resumen publico solo lista rotulos.

## Verificacion
`tests/test_compare.py::test_dispute_precision_on_real_labeled_stories` (precision y exhaustividad >= 0,95
sobre `tests/fixtures/disputes.json`, medidas con `truthnews/analysis/evaluate.py`) y tests de la regla;
medidas `disputas_precision` y `disputas_exhaustividad` en `docs/benchmarks/fase_2c.json`.
