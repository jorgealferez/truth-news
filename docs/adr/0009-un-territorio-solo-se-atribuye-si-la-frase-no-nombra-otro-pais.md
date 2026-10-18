# ADR 0009 — Una cifra solo se atribuye al país del medio si la frase no nombra otro país

- **Estado:** aceptado (amplia los ADR 0004 y 0006)
- **Fecha:** 2026-10-18
- **Fase:** 2b (correccion)
- **Decide:** Constructor, auditado por el Critico

## Contexto
Produccion, 18/10/2026: "Canada es el segundo mas extenso del planeta... con solo unos 40 millones de
habitantes" (El Mundo) se juzgo `falso` contra la poblacion de Espana. La lista de paises del extractor
(`geo_names`) era parcial: un pais ausente de la lista no impedia atribuir la cifra al pais del medio.

## Decision
1. Nomenclator mundial (`truthnews/registry/world.yaml`, ~110 paises en es/en/pt con gentilicios
   principales): si la frase nombra cualquier pais distinto del atribuible, la cifra no se atribuye.
2. Los indicadores marcados `requires_explicit_geo` (poblacion) exigen el pais nombrado en la frase.
3. Metodo `v3`: la re-verificacion vuelve a extraer cada afirmacion publicada con las reglas vigentes;
   si ya no es atribuible se retira (`sin-datos`, metodo `retirada/v3`) con nota publica de correccion.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Ampliar `geo_names` caso a caso | Siempre faltara un pais; el fallo es estructural |
| Borrar las afirmaciones mal atribuidas | La correccion debe ser visible (ADR 0006) |

## Consecuencias
Menos afirmaciones extraidas (mas conservador) y ninguna atribuida a un pais distinto del nombrado. El
veredicto erroneo publicado se retira solo al desplegar.

## Verificacion
Casos reales en `tests/test_claims.py` (Canada, Japon, Turquia, poblacion sin pais) y
`tests/test_pipeline.py::test_reverify_outdated_methods_and_note_corrections` (retirada con nota).
