# ADR 0007 — La IA agrupa temas y redacta análisis, pero no decide veredictos ni afirma sin evidencia

- **Estado:** aceptado
- **Fecha:** 2026-10-18
- **Fase:** 2b
- **Decide:** Constructor, auditado por el Critico

## Contexto
El usuario pide temas que reunan articulos de distinto enfoque, sintesis por medio (que dice cada uno,
en que coinciden, en que difieren), valoracion con todos los datos y piezas propias de analisis y
opinion como seccion principal (criterios C12, C13). Medido el 2026-10-18 sobre 187 historias reales:
agrupar historias en temas por similitud lexica o por entidades compartidas produce agrupaciones sin
relacion ("mar" une Marruecos con drones; entidades como "Sevilla" encadenan 83 historias). Es un
problema semantico: lo resuelve bien un modelo de lenguaje, no la heuristica.

## Decision
- Proveedor: API de Anthropic con el SDK oficial `anthropic`; modelo por defecto `claude-opus-5-5`
  (configurable con `AI_MODEL`), pensamiento adaptativo, esfuerzo configurable (`AI_EFFORT`, por
  defecto `high`), salida estructurada con esquema JSON (`output_config.format`), *streaming* con
  `get_final_message()`, prompt de sistema estable y cacheado, y `fallbacks: "default"` (beta
  `server-side-fallback-2026-07-01`) ante rechazos; un rechazo final no publica nada.
- Reparto de papeles: la IA **propone temas** (solo con titulares y medios) y **redacta** sintesis y
  piezas a partir de un dossier cerrado (articulos, comparativa, veredictos y datos oficiales ya
  verificados). **Los veredictos los sigue dando el codigo** (ADR 0004/0006): la IA no los cambia.
- Comprobacion de fundamento: toda cifra que aparezca en la pieza debe estar en el dossier; todo
  identificador de historia o medio citado debe existir. Si falla, la pieza queda en `revision` y no se
  publica. Cada pieza se marca como elaborada con IA, lista sus fuentes y enlaza las historias.
- Neutralidad: mismas instrucciones para todos los medios; se atribuye cada afirmacion; se distingue
  hecho, dato y valoracion; "opinion" significa valoracion argumentada con la evidencia del dossier,
  sin adhesion partidista.
- Coste acotado: `AI_MAX_PIECES_PER_CYCLE` (por defecto 6) y regeneracion solo si cambia el dossier
  (`input_hash`). Sin `ANTHROPIC_API_KEY` el sistema funciona igual sin temas ni piezas.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Temas por similitud lexica o entidades | Medido: agrupa cosas sin relacion |
| Que la IA de veredictos | No reproducible ni trazable a un dato; el veredicto sigue siendo del codigo |
| Modelo mas barato por defecto | El usuario pide "analisis profundo y muy profundo"; el modelo es configurable si quiere bajar coste |
| Servicio `ai` del holding | Falta `HOLDING_PLATFORM_API_KEY`; se puede conectar despues como proveedor alternativo |

## Consecuencias
Las piezas propias existen solo con clave. El coste por pieza depende del tamano del dossier (se
mide en produccion con `usage`). Lo que la IA no pueda fundamentar no se publica.

## Verificacion
Tests con cliente simulado (esquema, fundamento, rechazo, presupuesto, enlaces); medida
`piezas_sin_fundamento_publicadas = 0`. Con clave real: NO VERIFICADO hasta que el usuario la configure.
