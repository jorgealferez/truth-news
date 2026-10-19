# ADR 0027 — Lo que no cuadra se ordena por gravedad y se atribuye a quien lo dice, con el mismo metodo para todos

- **Estado:** aceptado (amplia ADR 0005, 0007 y 0012; usa el esquema del ADR 0028)
- **Fecha:** 2026-10-19
- **Fase:** 9 (quien miente, quien informa), items "Grandes falsedades y discrepancias" y "Entidades y archivo historico" del ledger
- **Decide:** sesion Entidades, auditado por el Critico

## Contexto
Peticion del usuario (2026-10-19): "recalcar donde hay grandes mentiras. Esa es la noticia grande",
"mayores discrepancias entre medios, mayores mentiras entre politicos, medios de comunicacion y datos" y
"si se menciona a X personas, X entidades... analizar, extraer y ordenar ese dato". Hasta ahora cada
veredicto se atribuia al medio que publicaba la cifra, la portada se ordenaba por contraste por historia
(ADR 0012) y no habia ninguna vista que juntara lo mas grave ni que siguiera a una persona en el tiempo.

## Decision
1. **Quien lo dice.** Una afirmacion se atribuye a una persona, partido, institucion u organizacion solo
   si en su misma frase va precedida de "segun"/"en palabras de" o seguida (como mucho con un inciso que no
   empiece por nombre propio) de un verbo de declaracion; si hablan dos o nadie, se queda en el medio.
   Mejor callar que poner una cifra en boca de quien no la dijo.
2. **Entidades.** Registro curado (`registry/entities.yaml`, solo nombres y alias, nunca cargos) mas
   descubrimiento de nombres propios que empiezan por un nombre de pila o por la palabra de cabeza de una
   institucion. Una descubierta se publica con >= 2 medios. Calidad medida en `tests/fixtures/entities.json`
   y en titulares reales (`docs/benchmarks/fase_e1.json`), con suelo en el presupuesto.
3. **Gravedad de una falsedad** = peso del veredicto (falso/enganoso 3, impreciso 1,5) x (1 + desviacion
   relativa frente al dato oficial, tope 2) x (1 + log2 de los medios que repiten la cifra) x actualidad
   (mitad cada 30 dias). Una fila por cifra aunque la publiquen varios medios.
4. **Discrepancias** entre medios: historias con cifras en disputa del mismo hecho (ADR 0016) por su
   puntuacion de contraste, con el rango y que medio da cada cifra.
5. **Contradicciones**: el mismo actor da cifras que difieren mas de un 5 % del mismo indicador, territorio
   y periodo.
6. **Quien acumula mas**: falsas o enganosas sobre comprobadas, siempre con el denominador.
7. **Lenguaje**: la pagina se llama "Lo que no cuadra". Nunca escribimos que alguien "miente": decimos que
   cifra dio, que dice el dato y donde comprobarlo. La intencion no se puede medir; la desviacion si.
8. **Archivo**: lo importado (ADR 0028) alimenta fichas y lineas temporales pero no se verifica contra el
   dato de hoy.

## Consecuencias
- Pagina `/discrepancias`, fichas `/entidad/<id>-<slug>` y ranking `/entidades`; bloque
  `_discrepancias.html` listo para que el hilo de portada lo incluya (`falsehoods`, `discrepancies`).
- El ranking de falsedades depende del volumen de verificaciones (3 en produccion al escribir esto): crece
  con el carril Verificaciones sin tocar este codigo.
- Riesgo: un error del extractor de hablante pondria una cifra en boca equivocada. Mitigacion: regla
  conservadora, precision medida con suelo en el ratchet, y la frase citada siempre visible junto al nombre.
