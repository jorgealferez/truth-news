# ADR 0039 — Cumplimiento UE y España: sin aviso de cookies porque todo lo guardado es exento, y un test que lo vigila

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** ítem del ledger «Cumplimiento normativo UE y España» (carril Cumplimiento)
- **Decide:** agente de la sesión session_01JMVrG4yxzJrdtXtmCBmCtn

## Contexto
Petición del usuario (2026-10-19): «La web impulsa el cumplimiento de la normativa de la Unión Europea y de
España, entre ellas el tema de cookies, los textos legales y cualquier otra directiva que nos obligue».

Inventario del código el mismo día: lo único que el sitio escribe en el navegador es la cookie `lang`
(preferencia de idioma, solo cuando el lector elige idioma, 1 año, SameSite=Lax) y la clave de
almacenamiento local `nm_last_visit` (marca «Nuevo» en la portada, no sale del navegador). El panel usa
HTTP Basic, sin cookie. No hay analítica, ni píxeles, ni fuentes externas (se sirven desde `/static`), ni
contenido incrustado de terceros. La publicidad (ADR de #37) se elige por el tema y su baliza usa un hash
diario en memoria. Faltaban el aviso legal, la política de privacidad, la de cookies y la transparencia de
propiedad. Solo existía `/publicidad`.

## Normas que aplican y cómo se cubren
| Norma | Obligación | Dónde |
|---|---|---|
| LSSI (Ley 34/2002) art. 10 | Datos del prestador | `/aviso-legal` |
| LSSI art. 20 | Publicidad identificada | `/publicidad` (ya existía) |
| LSSI art. 22.2 y Directiva 2002/58/CE art. 5.3 | Consentimiento solo para lo no exento | `/cookies` y este ADR |
| RGPD arts. 13 y 14, LOPDGDD | Información del tratamiento y derechos | `/privacidad` |
| LOPDGDD art. 86, LO 2/1984 | Actualización y rectificación de noticias | `/aviso-legal#rectificacion` |
| Reglamento (UE) 2024/1083 (EMFA) art. 6 | Titular, propietarios y fondos públicos | `/transparencia` |
| Reglamento (UE) 2024/1689 (IA) art. 50 | Marcar el texto generado con IA | `/transparencia` y la marca que ya existía |
| Directiva (UE) 2019/790 art. 4 | Respetar la reserva frente a la minería de textos | ADR 0003, citado en `/aviso-legal` |
| WCAG 2.1 AA / EN 301 549 | Objetivo y canal para avisar de barreras | `/transparencia` |

## Decisión
1. **Sin aviso de cookies.** Todo lo guardado es exento según la Guía de cookies de la AEPD (2023): la
   cookie la pide el lector al elegir idioma y la marca local es necesaria para una función que usa y no
   sale del navegador. Poner un aviso sin necesidad sería un patrón molesto que no exige la ley. Si algún
   día se añade algo no exento, se pide el consentimiento antes y con la misma facilidad para rechazar.
2. **El inventario es código.** `truthnews/web/legal.py:STORAGE` alimenta la tabla de `/cookies`, y
   `tests/test_legal.py` escanea `set_cookie`, `localStorage/sessionStorage.setItem` y `document.cookie`
   en Python, JS y plantillas: si algo escrito en el navegador no está declarado, el gauntlet se pone en
   rojo.
3. **Datos del titular por entorno, nunca inventados.** `LEGAL_OWNER`, `LEGAL_TAX_ID`, `LEGAL_ADDRESS`,
   `LEGAL_EMAIL` (obligatorios), `LEGAL_REGISTRY`, `LEGAL_OWNERSHIP` y `LEGAL_STATE_ADS`. Si falta uno, la
   página lo marca «Pendiente de que el titular lo complete» y muestra un aviso visible.
4. **Textos en es y en.** El español es el vinculante y la versión inglesa lo dice. Los demás idiomas
   leen la inglesa.
5. **Pie de todas las páginas** con Aviso legal · Privacidad · Cookies · Transparencia, y las cuatro rutas
   en el sitemap de páginas.
6. La imagen de un anuncio nativo (del dominio del anunciante) se pide con `referrerpolicy="no-referrer"`.

## Alternativas descartadas
- **Plataforma de gestión del consentimiento (CMP) de terceros:** añade un script y cookies de terceros
  para pedir un consentimiento que hoy no hace falta.
- **Textos legales genéricos con datos de ejemplo:** falsearía el aviso legal. Mejor un pendiente visible.

## Pendiente y NO VERIFICADO
- Datos del titular, propietarios y fondos públicos: los aporta el usuario, en Railway (`LEGAL_*`).
- Garantías de transferencia internacional de Railway (cláusulas tipo o Marco de Privacidad de Datos):
  NO VERIFICADO. El texto remite a las del proveedor sin afirmar cuál.
- Que el dominio de los anunciantes no ponga cookies al servir la imagen: NO VERIFICADO desde este
  repositorio (depende de ads-service). La alternativa es servir las imágenes desde ads-service.
- Conformidad WCAG 2.1 AA: es el objetivo declarado, no una auditoría.
