# ADR 0023 — La fiabilidad de un medio se mide con veredictos y con muestra suficiente

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** item del ledger "Reposicionar en quien miente, quien informa, quien dice la verdad"
- **Decide:** agente Comparativas, auditado por el Critico

## Contexto
El usuario (2026-10-18) quiere reposicionar el producto en "quien miente, quien informa, quien dice la
verdad y cual es la verdad si la tenemos": una ficha de fiabilidad por medio con su historial de
veredictos (como PolitiFact), un ranking por exactitud comprobada, "quien no lo cuenta" (como Ground News)
y una portada que lo destaque. Todo sin bandos ni etiquetas de ideologia.

Medido en produccion el 2026-10-19 (`/verificaciones`): hay 3 afirmaciones verificadas en total, 2 con dato
(una verdadera y una falsa) en 2 medios. Si se ordenara por porcentaje de acierto, un medio con 1 de 1 seria
"el mas fiable", y eso seria una afirmacion sin prueba.

## Decision
1. **Exactitud** de un medio = afirmaciones verdaderas / afirmaciones comprobadas contra un dato oficial
   (verdadero, impreciso, falso o enganoso). Los veredictos `sin-datos` no cuentan.
2. **Ranking** por el limite inferior del intervalo de Wilson al 95 %, que penaliza las muestras pequenas:
   2 de 2 (limite 0,34) queda por detras de 40 de 45 (0,77). Para entrar hacen falta al menos
   **5 afirmaciones comprobadas** (`MIN_CHECKS`). Los demas medios aparecen aparte, en "pocas
   verificaciones todavia", con su recuento a la vista y sin orden de merito.
3. **Ficha del medio**: exactitud con su muestra ("5 de 6"), medidor por veredicto, historial de veredictos
   con la evidencia enlazada y sus puntos ciegos.
4. **Quien no lo cuenta**: en una historia, los medios **nacionales del mismo pais** que publicaron algo
   entre 12 h antes y 12 h despues de la historia y no tienen ninguna pieza en ella. En la ficha del medio,
   la proporcion de las historias grandes de su pais en los ultimos 7 dias (al menos 5 medios) que conto,
   contando solo los dias en que publico. Se rotula como dato, no como acusacion: puede ser una decision
   editorial.
5. **Portada**: los 5 primeros del ranking de su pais junto a las ultimas verificaciones. Mientras nadie
   llega al minimo, se dice.

Calculo en lectura con consultas agregadas. No hay tabla nueva ni cambio de esquema.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Ordenar por porcentaje de acierto | Premia la suerte de la muestra pequena (1 de 1 = 100 %) |
| Puntuar tambien por cifras en disputa u omisiones | Una cifra distinta no es un error comprobado (balances que se actualizan, ADR 0004/0016); seria acusar sin dato oficial |
| Etiquetar medios por ideologia (Ground News, AllSides) | No se puede medir con el metodo del proyecto; es una de las cosas que no tomamos (docs/equipo.md) |
| Tabla de puntuaciones precalculadas | Con el volumen actual (cientos de verificaciones como mucho) la consulta agregada cuesta milisegundos; si crece se reevalua con ADR de datos |

## Consecuencias
- Hoy el ranking sale vacio y lo dice. Se llenara a medida que crezcan las verificaciones (carril
  Verificaciones). Es el precio de no publicar un ranking sin muestra.
- "Quien no lo cuenta" depende de que el agrupador junte bien las piezas (F1 0,885, ADR 0004). Un fallo del
  agrupador puede hacer que un medio parezca no contarlo, y la nota de la pagina lo advierte.
- La sesion "Railway project" es duena de `outlets.html` y `list.html`. Solo se anade una linea de inclusion
  en cada una; los componentes (`_ranking.html`, `_outlet_reliability.html`, `_ranking_mini.html`,
  `_missing.html`) son del carril Comparativas.

## Verificacion
`tests/test_reliability.py`: Wilson, ranking con minimo de muestra, historial, puntos ciegos y las paginas
`/medios`, `/medio/{slug}`, `/historia/{id}` y portada.
