# ADR 0041 — Quién informa primero y bien se mide solo con dato oficial y con muestra

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** ítem del ledger «Quién informa primero y bien» (carril Comparativas)
- **Decide:** agente Comparativas, auditado por el Crítico

## Contexto
Encargo de la dirección (2026-10-19), tras la fiabilidad (ADR 0021) y «quién cambió su cifra» (ADR 0032):
medir el tiempo desde el primer artículo de una historia hasta que cada medio publica la cifra que coincide
con el dato oficial, y quién se adelanta con una cifra que no cuadra. Solo en historias con dato oficial y
con muestra mínima por medio, como en la fiabilidad.

Medido en producción el 2026-10-19 (`/verificaciones`): hay 13 afirmaciones verificadas, repartidas entre
muy pocas historias. Ningún medio llega hoy a 5 historias con dato oficial comprobado.

## Decisión
1. **Historias que cuentan**: las que tienen al menos una afirmación con veredicto verdadero, impreciso,
   falso o engañoso. `sin-datos` no cuenta.
2. **Inicio de la historia**: la publicación de su primer artículo, sea de quien sea.
3. **Por medio y por historia**:
   - **acierta**: horas desde el inicio hasta su primera afirmación verdadera;
   - **se adelanta con una cifra que no cuadra**: su primera afirmación comprobada en la historia es
     imprecisa, falsa o engañosa.
4. **Por medio**: historias, aciertos, mediana de horas hasta acertar y veces que se adelantó con una cifra
   que no cuadra. Para entrar en la tabla hacen falta al menos **5 historias** (`MIN_STORIES`). Los demás
   aparecen aparte, sin orden de mérito. La tabla se ordena por la proporción de aciertos y, a igualdad,
   por la mediana de horas. No hay puntuación única que mezcle velocidad y acierto.
5. **Dónde se ve**: tabla «Quién informa primero y bien» dentro del ranking de `/medios`, y en «En claro»
   de cada historia la línea «Primero con la cifra correcta: medio, N h después del primer artículo».

Se calcula en lectura (`claim`, `verification`, `article`), sin esquema nuevo.

## Alternativas consideradas
| Alternativa | Por qué no |
|---|---|
| Medir velocidad en todas las historias | Sin dato oficial no se sabe qué cifra es la correcta: sería premiar al rápido, no al que acierta |
| Una puntuación única de velocidad y acierto | Esconde la compensación (rápido y equivocado frente a lento y correcto); se muestran las dos cosas |
| Contar desde la publicación del dato oficial | El dato suele ser anterior a la noticia (una serie mensual); lo que se compara es la cobertura de la historia |

## Consecuencias
- Hoy la tabla sale vacía y lo dice. Se llenará a medida que el carril Verificaciones compruebe más
  afirmaciones.
- Un medio que no publica ninguna cifra comprobable no aparece: no se le puede medir, y no se le penaliza.
- Depende del agrupador (ADR 0004): si un artículo cae en otra historia, cambia el inicio.

## Verificación
`tests/test_timeliness.py`: primera cifra correcta y primera que no cuadra, `sin-datos` fuera, muestra
mínima y orden, carga desde la base de datos, tabla en `/medios`, línea en la historia y tabla vacía.
