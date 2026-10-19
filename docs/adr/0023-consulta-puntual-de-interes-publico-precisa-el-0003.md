# ADR 0023 — Consulta puntual de interés público: precisa el ADR 0003

- **Estado:** aceptado (precisa el ADR 0003, que sigue vigente para el rastreo)
- **Fecha:** 2026-10-19
- **Fase:** Verificaciones a escala (item "Consulta puntual de interés público" del ledger)
- **Decide:** Constructor, auditado por el Critico; decisión de fondo del usuario (2026-10-19)

## Contexto
El ADR 0003 fija que el rastreador respeta `robots.txt` (RFC 9309), se identifica y nunca elude un
bloqueo. El usuario decidió el 2026-10-19, y lo precisó después, que cuando una página concreta (p. ej.
un portal de transparencia) sea imprescindible para contrastar un dato concreto se permita una
navegación dirigida aunque `robots.txt` la excluya, **solo** si hay dudas entre medios o faltan pruebas
de la entidad y la fuente no se obtiene por otra vía. `robots.txt` regula sobre todo el rastreo
automático masivo; una consulta humana-equivalente, puntual y motivada de un documento de interés
público es otra cosa, pero tiene que ser verificable que no se convierte en rastreo.

## Decision
1. **El rastreador no cambia.** Sigue respetando `robots.txt` sin excepciones (ADR 0003). La
   excepción vive en un módulo aparte, `truthnews/crawler/targeted.py`, que el rastreador no importa.
2. **Solo con justificación completa** (`Justification`): la afirmación concreta que se verifica, la
   condición del usuario que se cumple (`dudas_entre_medios` o `falta_pruebas_entidad`), el motivo y
   las vías alternativas ya intentadas (al menos una). Sin ella, la consulta no empieza.
3. **Navegación dirigida y acotada:** una lista cerrada de URLs (las páginas necesarias para llegar al
   documento), como máximo `MAX_PAGES = 5`, todas del mismo host que la primera; sin descubrir ni
   seguir enlaces por su cuenta; redirecciones solo dentro del mismo host. Al obtener el documento
   objetivo (la última URL) se para.
4. **Honesto y sin eludir nada:** el mismo User-Agent identificado del proyecto; se para en seco ante
   401, 403, 407, 429 o 451, o ante un desafío anti-bots (captcha, "challenge"): eso es un bloqueo
   técnico y no se rodea (sin cambiar de agente, IP ni cabeceras).
5. **Todo queda registrado:** cada URL con su código, fecha, huella sha256 y si `robots.txt` la
   excluía; la justificación y el registro se guardan en la evidencia (`payload["consulta_puntual"]`,
   JSON ya existente, sin cambio de esquema) y la Metodología pública lo explica.
6. **Nada se reutiliza:** el cliente se crea y se cierra en cada consulta; no alimenta la caché de
   `robots.txt`, ni los feeds, ni la cola del rastreador.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Añadir una lista blanca de dominios al rastreador | Mezcla rastreo masivo y consulta puntual; una entrada en la lista se rastrearía en cada ciclo |
| Seguir sin excepción (ADR 0003 tal cual) | Contradice la decisión del usuario; deja sin contrastar datos de interés público cuando falta la prueba |
| Navegador sin cabeza o agente de navegador | Parece eludir la identificación; no hace falta para documentos públicos |
| Permitir rodear 403/429 si el interés es alto | Prohibido: un bloqueo técnico es una decisión del sitio (ADR 0003) |

## Consecuencias
Una consulta puntual deja rastro público y auditable; su coste es de, como mucho, 5 peticiones con el
ritmo de 1 s. Aún no hay disparador automático: se invoca desde una investigación o una verificación
cuando se cumplen las condiciones; el disparo automático, si llega, reutilizará la misma justificación.

## Verificacion
`tests/test_targeted.py`: sin justificación no hay petición; tope de páginas; otro host rechazado;
redirección a otro host parada; 403 y 429 paran sin más peticiones; un desafío anti-bots para; registro
con huella y bandera de `robots.txt`; el rastreador sigue sin descargar URLs prohibidas
(`test_crawl_end_to_end`, medida `rastreo_descargas_prohibidas = 0`).
