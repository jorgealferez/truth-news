# ADR 0029 — La consulta puntual de interés público llega a un documento concreto y para

- **Estado:** aceptado (precisa el ADR 0003)
- **Fecha:** 2026-10-19
- **Fase:** ítem del ledger «Consulta puntual de interés público»
- **Decide:** agente Comparativas (ítem tomado al vaciarse su carril), auditado por el Crítico

## Contexto
El ADR 0003 fija que el rastreador respeta robots.txt y no elude bloqueos. El usuario decidió el
2026-10-19, y lo precisó después, una excepción acotada: cuando una página concreta (por ejemplo, de un
portal de transparencia) sea imprescindible para contrastar un dato concreto, se permite una navegación
dirigida aunque robots.txt la excluya. La condición es que haya dudas entre medios o falten pruebas de la
entidad, y que la fuente no se obtenga por otra vía. Solo se visitan las páginas necesarias para llegar a
ese documento, con tope y registrando cada URL. Al obtenerlo se para y nada se reutiliza para seguir
rastreando. El User-Agent es honesto, se para ante 401, 403 o un bloqueo, y el motivo y la afirmación que
se verifica quedan en la evidencia y en Metodología.

## Decisión
`truthnews/crawler/targeted.py` (`lookup`) y el subcomando `truthnews consulta-puntual`:
1. **No se consulta sin justificación**: hace falta `dudas-entre-medios` o `falta-de-pruebas`, el motivo, la
   afirmación y al menos una vía alternativa probada (datos abiertos, BOE, nota de prensa...). Si falta algo,
   error.
2. **Tope de 5 páginas** (`MAX_PAGES`, que no se puede subir por argumento), solo dentro del dominio de
   partida. El siguiente paso lo elige quien llama entre los enlaces de la página; no hay cola ni
   descubrimiento.
3. **User-Agent del rastreador** (el de `CRAWLER_USER_AGENT`, con URL de contacto) en todas las peticiones
   y 1 s entre ellas.
4. **Se para** ante 401, 403 o 429 y ante una página de desafío (captcha, «verify you are human»). Un bloqueo
   técnico no se elude.
5. **Se para al obtener el documento**. Nada de lo visitado entra en el rastreo ni se vuelve a usar.
6. **Traza completa** (`Lookup.as_payload()`): motivo, justificación, afirmación, vías probadas, cada URL con
   su hora, su estado HTTP y si robots.txt la permitía, el documento y por qué se paró. Va al `payload` de la
   evidencia de la verificación que la motivó. Metodología explica la excepción en es y en en.

No cambia el esquema: la traza cabe en `evidence.payload` (JSON), así que no hace falta ADR de datos.

## Alternativas consideradas
| Alternativa | Por qué no |
|---|---|
| Seguir sin excepción (ADR 0003 tal cual) | El usuario decidió la excepción para casos de interés público con dudas o sin pruebas |
| Dejar que el rastreador ignore robots.txt en ciertos dominios | Convertiría la excepción en rastreo; la decisión es una consulta puntual que para |
| Suplantar un navegador o reintentar tras 403/429 | Prohibido por el ADR 0003 y por la precisión del usuario |
| Tabla propia para las consultas | La traza pertenece a la evidencia de una verificación; si crece su uso, se reevalúa con ADR de datos |

## Consecuencias
- La herramienta existe y queda probada, pero ningún proceso automático la llama. La usa quien verifica (el
  carril Verificaciones o una investigación) en un caso concreto. Conectarla al flujo automático exigiría
  decidir cuándo un caso cumple las condiciones, y eso se deja a una decisión posterior.
- `rastreo_descargas_prohibidas = 0` del ratchet sigue midiendo el rastreo normal; la consulta puntual no
  pasa por él y queda declarada en cada evidencia.

## Verificación
`tests/test_targeted.py`: llega al documento y para (no visita nada más), registra cada URL con el estado
de robots, usa el User-Agent honesto, se para ante 403, 429 y captcha, respeta el tope de páginas y el
dominio, registra errores de red, exige justificación y vías alternativas, y el CLI imprime la traza.
