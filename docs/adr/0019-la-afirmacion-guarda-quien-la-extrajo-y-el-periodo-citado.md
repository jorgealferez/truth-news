# ADR 0019 — La afirmación guarda quién la extrajo y el periodo citado

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** Verificaciones a escala (item del ledger, prioridad del usuario 2026-10-19)
- **Decide:** Constructor, auditado por el Critico

## Contexto
El usuario pide "lo más importante las verificaciones": hoy casi no se juzga nada. Medido en los logs
del worker de producción (18 ciclos entre 2026-10-18 22:54 y 2026-10-19 00:55 UTC, unos 2 900
artículos en ventana): **3 afirmaciones en total, 0,17 por ciclo**. La extracción es solo por reglas
(`truthnews/analysis/claims.py`), deliberadamente conservadora. Se añade una extracción con IA: la IA
propone frase, indicador, territorio y periodo; el código valida cada propuesta con reglas
deterministas y el veredicto lo sigue decidiendo el código contra la serie oficial (ADR 0007).

La tabla `claim` guarda `text`, `indicator`, `geo`, `value`, `unit` y `direction`, pero no el periodo
citado: el periodo se recalcula en cada re-verificación volviendo a extraer la frase con las reglas
(`reverify_outdated`). Con dos extractores eso deja de valer: una afirmación propuesta por la IA y
validada por el código no la vuelven a encontrar las reglas, y se retiraría en la siguiente subida de
versión del método.

## Necesidad
Sin saber qué extractor produjo la afirmación, `reverify_outdated` retiraría como "no atribuible"
todas las de la IA al cambiar `METHOD_VERSION`, o habría que volver a llamar a la IA (coste y
resultado no reproducible). Sin el periodo guardado, la re-verificación de una afirmación de la IA
no podría compararse con el dato del periodo citado (ADR 0006). Alternativas sin esquema estudiadas:
codificar el extractor en `verification.method` (String(40), ya usado para `nivel/v3`) mezcla el
método de juicio con el origen y obliga a analizar cadenas en cada consulta; guardar el periodo en
`evidence.payload` no sirve porque un veredicto `sin-datos` no tiene evidencia y el periodo es de la
afirmación, no del dato oficial.

## Escalabilidad
Hoy `claim` tiene del orden de 10 filas. Proyección con la extracción con IA: el prefiltro deja
pasar las frases con cifra y palabra de indicador de los artículos nuevos de cada ciclo (unos 20-60
artículos por ciclo medidos en el log, `articles` crece 15-50 por ciclo); con un tope de 3 llamadas
de 40 frases por ciclo y una tasa de aceptación prevista del 10-30 %, entre 5 y 35 afirmaciones por
ciclo, unas 48 ciclos al día a 30 min: como máximo ~1 700 filas/día, ~600 000/año en el peor caso;
cada fila nueva añade 2 columnas de 8 y 20 caracteres (< 40 bytes), menos de 25 MB al año. No hacen
falta índices nuevos: ninguna consulta filtra por `extractor` o `period` (se leen con la afirmación,
por clave primaria o por `story_id`/`outlet_id`, ya indexados). A 10x (6 M filas) el coste de las
columnas sigue por debajo de 250 MB y no cambia ningún plan de consulta.

## Coherencia
`extractor` sigue el estilo de `verdict` y `piece.status`: `String(8)` no nulo con `CheckConstraint`
de valores cerrados (`'reglas'`, `'ia'`) y `server_default 'reglas'`, para que las filas existentes
queden correctas sin relleno. `period` sigue el formato de `evidence.period` (`String(20)`, nulable):
`'2026-08'`, `'2026-Q2'`, `'2025'` o nulo si la frase no cita periodo. Invariante en el código: una
afirmación con `extractor='ia'` solo se guarda si su frase está literalmente en el texto del
artículo, su cifra aparece en la frase, su indicador se nombra en la frase y su territorio y periodo
cuadran con las reglas deterministas; la base de datos garantiza solo el dominio de valores.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Codificar el extractor en `verification.method` | Mezcla el origen con el método de juicio; consultas por prefijo de cadena; se pierde al re-juzgar |
| Tabla aparte `claim_extraction` (1:1) | Una relación 1:1 para dos columnas pequeñas: un join más en cada lectura sin ganar nada |
| Periodo en `evidence.payload` | Un `sin-datos` no tiene evidencia; el periodo es de la afirmación, no del dato |
| Volver a llamar a la IA al re-verificar | Coste por ciclo y resultado no reproducible: el veredicto debe poder rehacerse solo con código |

## Necesidades futuras
Los siguientes pasos del carril (indicadores regionales del INE y la EPA, datos políticos) añaden
indicadores y territorios, no columnas: `geo` ya admite 8 caracteres (códigos de comunidad
`ES-AN`). Un tercer extractor (p. ej. afirmaciones aportadas por lectores) solo amplía el
`CheckConstraint`. El historial de veredictos por medio y por persona (ficha de fiabilidad) se apoya
en `extractor` para separar lo extraído por reglas de lo propuesto por la IA en la metodología.

## Migracion y reversibilidad
Un paso, migración `0010`: `ADD COLUMN` de dos columnas, una nulable y otra con `server_default`;
en PostgreSQL 11+ ambas son operaciones solo de catálogo (sin reescritura ni bloqueo largo) sobre
una tabla de decenas de filas. Sin relleno: las filas existentes quedan `extractor='reglas'` y
`period` nulo, que es lo que el código vigente ya supone (re-extrae el periodo de la frase). El
código antiguo, que no conoce las columnas, sigue funcionando durante el despliegue porque ambas
tienen valor por omisión. Reversión: `downgrade` borra las dos columnas; se pierde el origen y el
periodo guardado de las afirmaciones de la IA, que en la siguiente re-verificación por reglas se
retirarían con nota pública (comportamiento seguro: mejor callar que acusar).

## Decision
La tabla `claim` gana `extractor` (`'reglas'` | `'ia'`, por omisión `'reglas'`) y `period` (periodo
citado, nulable); la re-verificación de las afirmaciones de la IA usa los campos guardados y las
reglas de validación vigentes, sin volver a llamar a la IA.

## Verificacion
Migración aplicada y revertida en SQLite limpio (`tests/test_migrations.py`); tests de la
extracción con IA con cliente simulado (`tests/test_ai_claims.py`): propuestas inventadas,
cifra que no está en la frase, territorio o periodo que no cuadran y subgrupos rechazados;
re-verificación de una afirmación de la IA sin llamar a la IA. Medida antes/después en
`docs/benchmarks/verificaciones_1.json` (después: NO VERIFICADO hasta medir el log de producción).

## Alcance
- `alembic/versions/0010_afirmaciones_ia.py`
- `truthnews/models.py`
