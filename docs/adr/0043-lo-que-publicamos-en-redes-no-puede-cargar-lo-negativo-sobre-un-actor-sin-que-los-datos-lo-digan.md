# ADR 0043 — Lo que publicamos en redes no puede cargar lo negativo sobre un actor sin que los datos lo digan

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** item del ledger "Equilibrio en lo que publicamos en redes" (asignado por la direccion 2026-10-19 06:07)
- **Decide:** Constructor, auditado por el Critico

## Contexto
La autopublicacion (ADR 0018) elige por relevancia: prioridad de contraste de la historia, veredicto de
la verificacion. Eso es neutral pieza a pieza, pero el conjunto puede no serlo: si en un dia salen cinco
piezas con veredicto negativo y todas afectan al mismo partido, nuestras cuentas parecen tomar partido
aunque cada pieza sea correcta. La esencia del proyecto es "sin bandos"; un bando no lo podemos medir
(ADR 0027: nunca etiquetamos ideologias), pero si podemos medir a quien afecta cada pieza.

## Decision
1. **Actor de una pieza.** Verificacion: quien dijo la frase si se conoce (`claim.speaker`, ADR 0028); si
   no, los partidos que menciona la noticia de la que sale. Historia e hilo: los partidos mencionados en
   la historia. Sin actor conocido, la pieza no cuenta para nadie.
2. **Pieza negativa:** lleva un veredicto falso o enganoso (en la propia verificacion o en alguna
   afirmacion de la historia). Impreciso no cuenta: no afirma que nadie falte a la verdad.
3. **Medida (24 h, en espanol, una vez por contenido aunque salga en cuatro redes):** reparto por actor de
   las piezas negativas publicadas, frente al reparto por actor de **todos** los veredictos negativos del
   mismo periodo (lo que dicen los datos).
4. **Marca:** un actor se marca si supera el 60 % de las piezas negativas publicadas, con al menos 3, **y**
   ese peso excede en 15 puntos su peso en los datos. Si es quien acumula las falsedades del periodo, los
   datos lo justifican y no se toca.
5. **Diversificar = reordenar:** las piezas negativas de un actor marcado pasan detras de las demas
   candidatas, conservando su orden. Ninguna se descarta (saldran cuando haya cupo) y ningun veredicto se
   oculta ni se suaviza en la web.
6. **Transparencia:** la medida va en el resumen de cada ciclo del worker (`social.equilibrio`), en
   `/admin` (seccion Redes) y en `python -m truthnews social balance`.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Cuotas fijas por partido | Publicariamos falsedades inexistentes para cuadrar, o callariamos las reales: contra "todo citado, nada inventado" |
| Clasificar actores en bandos (izquierda/derecha) | No es medible y contradice ADR 0027 |
| Descartar las piezas del actor marcado | Ocultaria veredictos correctos; reordenar basta para que la cuenta no se lea como campana |
| Contar por red | La misma pieza en cuatro redes pesaria cuatro veces; el equilibrio es de lo que decimos, no de por donde |

## Consecuencias
- Con pocos datos no actua (menos de 3 piezas negativas en 24 h).
- Personas: cuentan como actor propio; no se les atribuye partido (el registro de entidades no guarda
  cargos ni afiliaciones, ADR 0028).
- Coste: una consulta por candidata para sus actores (decenas por ciclo).
- Umbrales (`THRESHOLD`, `MIN_NEGATIVE`, `MARGIN` en `truthnews/social/balance.py`): cambiarlos exige un ADR
  nuevo; la medida publicada en el ledger y en el log permite revisarlos con datos.

## Verificacion
`tests/test_social.py`: actor sobrerrepresentado frente a los datos se marca y sus piezas negativas pasan
detras sin perder ninguna; actor que concentra todas las falsedades del periodo no se marca; el hablante
manda sobre los partidos mencionados; menos de 3 negativas nunca marcan. Medida real en produccion tras
el despliegue, anotada en el ledger.
