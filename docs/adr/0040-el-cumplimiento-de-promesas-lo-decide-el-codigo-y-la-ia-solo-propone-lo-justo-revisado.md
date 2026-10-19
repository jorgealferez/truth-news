# ADR 0040 — El cumplimiento de promesas lo decide el código con datos; la IA solo propone lo justo, revisado

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** 18 (18c)
- **Decide:** Constructor, auditado por el Critico

## Contexto

El usuario pide (2026-10-19) analizar "cuáles los que han gobernado han cumplido". Medido antes de decidir,
con el programa de Sumar de 2023 (687 promesas) y el Gobierno PSOE-Sumar (RD 828/2023, del 17/11/2023
a la disolución del 06/10/2026):

- Cruce por palabras del título con la legislación consolidada del BOE: ~1 de cada 6 normas encontradas
  trata de verdad de lo prometido. No basta para publicar nada.
- Metas medibles frente a los indicadores ya conectados: 0 de 687.

Se plantearon dos opciones: (a) que la IA proponga el estado, revisado antes de publicarse, o (b)
conectar series oficiales para las promesas con cifra. El usuario decide combinarlas "para obtener
mejores resultados y reducir el coste en IA a lo necesario". La dirección añade condiciones:
- solo se mide a quien gobernó, y esa asimetría se explica en la página;
- mismo trato para todos los gobiernos;
- "sin dato comprobable" cuando no baste;
- nunca "mintió".

ADR 0007 dice que la IA no decide veredictos.

## Decisión

Tres pasos en `truthnews/elections/fulfilment.py`. Solo el último gasta IA, y nada suyo se publica sin una
persona.

1. **`dato-v1` (código):** si la promesa fija una meta de un indicador oficial, se compara con el último
   dato. El resultado es cumplida, no cumplida o, si el Gobierno sigue, en curso. Se publica, como
   cualquier veredicto con datos (ADR 0007).
2. **`boe-candidatas-v1` (código):** se buscan en la legislación consolidada del BOE (API de datos
   abiertos) normas estatales del periodo de gobierno cuyo título contenga al menos dos palabras de tema
   de la promesa. Son candidatas internas: no se publican.
3. **`ia-boe-v1` (IA, revisado):** solo para promesas con candidatas y sin veredicto de datos.
   - **Qué ve la IA:** la promesa y los títulos de sus candidatas, nada más.
   - **Cómo se llama:** con el cliente estructurado del proyecto (`AIClient.structured`: esquema JSON,
     prompt de sistema estable y cacheado), el modelo configurado (`AI_MODEL`) y esfuerzo bajo
     (`PROMISES_AI_EFFORT=low`). Se agrupa en lotes de 10 promesas (`PROMISES_AI_BATCH`) con un máximo de
     2 llamadas por ciclo (`PROMISES_AI_MAX_CALLS`). Primero van las promesas cuyas candidatas tienen más
     términos en común.
   - **Qué puede responder:** solo "cumplida", "parcial" o "sin-datos". "No cumplida" no está en el
     esquema, porque que no conste una norma no lo prueba.
   - **Qué valida el código:** cada norma citada tiene que estar en la lista; sin cita válida, el estado
     queda en "sin dato comprobable".
   - **Revisión:** la propuesta se guarda como `ia-boe-v1:pendiente`. Solo se publica cuando una persona
     la aprueba en `/admin`, y entonces se marca "análisis asistido por IA, revisado". Si se rechaza,
     queda como `ia-boe-v1:rechazada`.

Solo se mide el programa con el que un partido llegó al Gobierno (registro `governments`, con su fuente
oficial). La página lo dice, con el Gobierno, las fechas y el decreto.

Esto es una excepción acotada a ADR 0007: la IA no publica nada por sí misma. Propone, citando normas
oficiales que encontró el código, y una persona decide.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Solo (b), series por promesa con cifra | Cubre ~3 % de las promesas (20 de 687 con cifra) y semanas de conectores |
| Solo (a), la IA sobre todas las promesas | 687 promesas por programa: ~69 llamadas; con el filtro del código, ~6 (−92 %) |
| Publicar las normas candidatas sin la IA | ~1 de 6 trata de lo prometido: induciría a error |
| Que la IA busque en la web | Más coste y fuentes sin control; aquí solo ve normas del BOE ya encontradas |
| Registrar la revisión en `admin_action` | Su CHECK de acciones exige una migración; la revisión queda en el método y en la explicación ("Revisado por X el fecha") |

## Consecuencias

- **Coste:** en la muestra medida (60 promesas de Sumar 2023), 5 tienen candidatas (8,3 %). La IA vería
  ~57 de 687 promesas en ~6 llamadas. Con 2 llamadas por ciclo, un programa queda propuesto en ~3 ciclos.
- **Tiempo:** el paso de reglas tarda ~2,3 s por promesa (una búsqueda en el BOE). Con 20 por ciclo
  (`PROMISES_CHECK_PER_RUN`), ~45 s por ciclo, y un programa de 687 promesas en ~35 ciclos (~18 h).
- **Lo que no se mide:**
  - El PSOE: su web bloquea al rastreador y su programa de 2023 no se ha podido importar; la página dice
    "sin medir".
  - Las metas medibles con indicadores aún no conectados (AOD, plazas de 0-3 años…): siguen siendo
    trabajo del carril Verificaciones.
- **Pendiente:**
  - otros gobiernos (autonómicos), que se añaden como datos en `governments`;
  - el acuerdo de coalición como documento `acuerdo`;
  - medir la precisión de las propuestas de la IA cuando haya clave en producción.

## Verificación

- `tests/test_fulfilment.py`: reglas, cola, lotes y tope, validación de citas, revisión, páginas y
  `/admin`.
- Medida en `docs/benchmarks/fase_18c.json`, bajo la puerta `ratchet`. Con el porcentaje de promesas que
  llega a la IA como techo del presupuesto.
