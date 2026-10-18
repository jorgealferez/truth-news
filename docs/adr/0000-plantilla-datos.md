# ADR 0000 — Plantilla de revision de arquitectura de datos

- **Estado:** plantilla (propuesto | aceptado | sustituido por ADR NNNN)
- **Tipo:** datos
- **Fecha:** AAAA-MM-DD
- **Fase:** N
- **Decide:** Constructor, auditado por el Critico

Toda modificacion de la capa de datos (migracion, esquema, modelo de ORM, indice, vista, procedimiento,
tabla de un almacen gestionado) lleva un ADR de este tipo **en el mismo cambio**: la puerta `datos` del
gauntlet lo exige y comprueba que cada seccion este escrita de verdad. Un ADR aceptado no se edita; la
siguiente modificacion lleva el suyo. Copia este fichero a `NNNN-titulo-declarativo.md`, quita los
comentarios y responde a cada pregunta con hechos del repositorio y cifras medidas, no con adjetivos.
Si la revision concluye que la modificacion no hace falta, el ADR lo dice y la modificacion no se
hace: ese tambien es un resultado valido, y mas barato.

## Contexto
<!-- Que cambia en los datos y por que ahora: la funcionalidad o el fallo que lo pide, con su
referencia (criterio de la carta, item del ledger, issue). Que hay hoy en el esquema que afecta a
este cambio (tablas, columnas, indices implicados y su uso real). -->

## Necesidad
<!-- Es imprescindible tocar el esquema? Que pasa si no se hace. Que alternativa sin cambiar el
esquema se ha considerado (reutilizar una tabla o columna existente, calcular en lectura, un campo
JSON ya presente, una vista) y por que no basta. -->

## Escalabilidad
<!-- Numeros, no adjetivos: filas hoy y proyeccion a 12 meses, tamano en disco, escrituras y lecturas
por segundo, patrones de acceso que lo tocan. Indices que necesita cada consulta nueva y lo que cuesta
mantenerlos en escritura. Cardinalidad, particionado, crecimiento sin cota. Que pasa a 10x. -->

## Coherencia
<!-- Nombres, tipos, nulabilidad, valores por defecto y claves conforme a lo que ya existe en el
esquema. Relaciones, claves foraneas y restricciones (unicidad, checks) que garantizan la integridad.
Normalizacion o desnormalizacion deliberada y por que. Que invariantes del dominio quedan en la base
de datos y cuales en el codigo. -->

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
<!-- Al menos una alternativa de modelado real (otra tabla, otra relacion, otro tipo, otro almacen) y
el motivo concreto por el que no se elige. -->

## Necesidades futuras
<!-- Que necesidades previsibles del producto afectan a este diseño y como las acomoda o las dificulta
(multi-tenant, historico y auditoria, borrado logico, internacionalizacion, limites por plan,
particion por cliente). Hay una forma de plantearlo que sirva tambien para eso sin coste ahora? Si no
se adopta, que habria que cambiar despues y cuanto costaria. -->

## Migracion y reversibilidad
<!-- Como se aplica: en un paso o en expandir/contraer, con bloqueo de tabla o sin el, relleno de
datos (backfill) y su duracion estimada sobre el volumen real. Compatibilidad con el codigo que esta
corriendo durante el despliegue. Como se revierte y que se pierde al revertir. -->

## Decision
<!-- Que se hace, en una frase afirmativa, y las condiciones que la acotan. -->

## Verificacion
<!-- Como se comprueba: la migracion aplicada y revertida en un entorno limpio, tests que ejercen el
esquema nuevo, medida publicada en docs/benchmarks/fase_N.json si afecta al presupuesto. -->

## Alcance
<!-- Los ficheros de la capa de datos que este ADR cubre, uno por linea, entre acentos graves. Rutas
exactas o globs (`migrations/0042_*.py`, `prisma/schema.prisma`). La puerta `datos` falla si un
fichero de datos cambiado no esta aqui. -->
- `ruta/al/fichero`
