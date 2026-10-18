# ADR 0004 — El comparador agrupa por historia y contrasta cifras, omisiones, lenguaje y datos oficiales

- **Estado:** aceptado
- **Fecha:** 2026-10-18
- **Fase:** 2
- **Decide:** Constructor, auditado por el Critico

## Contexto
El usuario (2026-10-18), viendo la web desplegada: "mete noticias pero no hay contraste. Necesitamos
ser una especie de comparador de noticias y luego leer de que sale todo a nivel global y dar esa
valoracion, no solo agregador". Criterios C4, C5 y C6 de la carta.

## Decision
La unidad editorial deja de ser el articulo y pasa a ser la **historia**: la misma noticia contada por
varios medios. Por cada historia el sistema publica, sin intervencion humana:
1. **Cobertura**: que medios la cuentan, cuando y con que titular; y que ambitos (nacional, autonomico,
   local, internacional) la ignoran.
2. **Cifras en disputa**: la misma magnitud (detenidos, muertos, euros, %) con valores distintos segun el
   medio, con la hora de cada uno (una diferencia puede ser un balance actualizado: se dice).
3. **Omisiones**: los datos (cifras y nombres propios) que la mayoria de medios incluye y un medio no.
4. **Lenguaje cargado**: palabras valorativas por medio, frente al tono medio de la historia.
5. **Contraste con datos oficiales**: afirmaciones numericas sobre indicadores (paro, inflacion, PIB,
   deuda, vivienda, poblacion...) comparadas con Eurostat, INE y Banco Mundial; veredicto trazable.

Agrupacion: TF-IDF sobre titular (x2) y resumen, coseno contra el centroide de historias abiertas en una
ventana de 48 h, umbral 0,30; tokens normalizados con raiz por prefijo de 6 letras y palabras vacias
es/en/pt. Medido sobre 155 titulares reales etiquetados a mano en 26 historias: precision 0,930,
exhaustividad 0,844, F1 0,885.

Veredicto (escala cerrada): `verdadero` (diferencia <= 0,2 puntos o <= 3 %), `impreciso` (<= 0,6 puntos
o <= 10 %), `falso` (mayor), `enganoso` (la direccion afirmada, sube/baja, contradice el dato) y
`sin-datos` (no hay serie, la serie no es fresca, o la afirmacion no es comprobable). Una serie cuyo
ultimo dato tiene mas de 400 dias se considera obsoleta y da `sin-datos`: nunca se juzga con un dato
viejo. Toda verificacion guarda su evidencia (fuente, URL de la API, periodo, valor, fecha de consulta).

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Embeddings con un modelo de lenguaje para agrupar | Coste por articulo y dependencia de una clave que hoy no existe; el F1 medido ya supera el objetivo. Se reevalua con la clave |
| Pedir a un LLM el veredicto | Un veredicto debe ser reproducible y trazable a un dato; el LLM puede redactar, no decidir |
| Marcar como "falsa" toda cifra que difiere entre medios | Los balances se actualizan durante el dia; seria acusar sin prueba. Se muestra la discrepancia con la hora |

## Consecuencias
La portada pasa a ser de contrastes. El contraste de omisiones y lenguaje es mas fiable con texto
completo (tope de 600 por ciclo); con solo titular y resumen se dice en la pagina. Quedan para fases
siguientes la redaccion asistida por LLM y las investigaciones a demanda (Fase 3).

## Verificacion
`tests/test_cluster.py` (F1 >= 0,80 sobre `tests/fixtures/clusters.json`), tests de cifras, omisiones,
veredictos y frescura; medidas `agrupacion_f1`, `fuentes_datos_vivas` y `verificaciones_sin_evidencia`
en `docs/benchmarks/fase_2.json`.
