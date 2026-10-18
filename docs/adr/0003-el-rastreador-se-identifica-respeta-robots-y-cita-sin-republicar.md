# ADR 0003 — El rastreador se identifica, respeta robots.txt (RFC 9309) y cita sin republicar

- **Estado:** aceptado
- **Fecha:** 2026-10-18
- **Fase:** 1
- **Decide:** Constructor, auditado por el Critico

## Contexto
C2 pide ingesta masiva de medios y la peticion del usuario dice "crawlear, scrapear, lo que sea". La
carta exige rigor y el liston editorial: derecho de cita y respeto a las reglas de cada sitio. El
primer rastreo real (2026-10-18) midio que algunos sitios devuelven 403/406 o prohiben el acceso por
`robots.txt` (El País, Cinco Días, AS, elEconomista, el grupo Prensa Ibérica con 406 a cualquier
agente desde este entorno).

## Decision
El rastreador usa un User-Agent propio con URL de contacto, consulta `robots.txt` por origen segun RFC
9309 (2xx: se aplican las reglas; 4xx: sin restricciones; 5xx o red caida al leerlo: sin
restricciones si no responde, prohibicion total si responde 5xx), espacia las peticiones por dominio
(`PER_DOMAIN_DELAY_SECONDS`, 1 s), descubre feeds por `<link rel="alternate">`, guarda el texto completo
solo para analisis interno y publica solo titular, extracto breve, enlace y analisis propio. No se
falsea el User-Agent ni se eluden bloqueos: un medio bloqueado se cubre por otras vias (agencias,
otros medios, su presencia en redes) y se declara en el panel.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Suplantar un navegador o rotar IPs para eludir 403/406 | Elude una decision explicita del sitio; riesgo legal y reputacional para un medio que acusa a otros de mentir |
| Ignorar `robots.txt` | Mismo motivo; ademas la carta lo fija como liston |
| Republicar el texto completo | Infringe derechos de autor; el valor del producto es el contraste, no la copia |

## Consecuencias
Algunos medios grandes quedan fuera del rastreo directo desde este entorno (medido en
`docs/benchmarks/fase_1.json`); su cobertura se recupera por agencias y por el resto de medios. Si el
usuario consigue acuerdos o APIs oficiales, se anaden como feeds en el registro, sin codigo.

## Verificacion
Tests `test_crawl_end_to_end` (una URL prohibida no se descarga), `test_robots_rules` (RFC 9309) y la
medida `rastreo_descargas_prohibidas = 0` del ratchet.
