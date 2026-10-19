# ADR 0040 — La contratación pública se lee del BOE y de TED, en memoria y citada, y se cruza con la prensa sin afirmar relación

- **Estado:** aceptado
- **Fecha:** 2026-10-19
- **Fase:** ítem del ledger «Contratación pública, transparencia y datos abiertos» (carril Contratación y transparencia)
- **Decide:** Constructor, auditado por el Crítico

## Contexto
Petición del usuario (2026-10-19): «Incluye el análisis y cruce de datos con licitaciones y concursos públicos y
otros datos publicados también en portales de transparencia, BOE y datos abiertos». Ya tenemos el sumario del BOE
(ADR 0005, nombramientos) y la ejecución presupuestaria de la IGAE, ambos sin tablas.

Lo que dice el robots.txt de cada fuente, medido el 2026-10-19 con nuestro User-Agent:

| Fuente | Qué ofrece | robots.txt / acceso | Uso |
|---|---|---|---|
| BOE, API de datos abiertos, sección V.A | 58 anuncios el 16/10/2026: licitaciones y formalizaciones con órgano, objeto y expediente | permite `/datosabiertos/` | sí |
| TED, API de búsqueda v3 (Oficina de Publicaciones de la UE) | 909 adjudicaciones con comprador en España del 05/10 al 18/10/2026. Importe en 843 y adjudicatario en 859 | `api.ted.europa.eu/robots.txt` da 404 y `ted.europa.eu/robots.txt` está vacío: sin exclusión | sí |
| Plataforma de Contratación del Sector Público (sindicación ATOM) | todos los perfiles del contratante | `Disallow: /` | no se rastrea (ADR 0003). Solo cabe la consulta puntual del ADR 0029 |
| BDNS (subvenciones) | convocatorias y concesiones | `pap.hacienda.gob.es`: `Disallow: /api/`. El robots.txt de `infosubvenciones.es` da «Autorización requerida» | no |
| datos.gob.es | catálogo | protección antibots (Incapsula) | no se evade |
| transparencia.gob.es | portal de transparencia de la AGE | no excluye nada | pendiente (siguiente subitem) |

Cuando hay varios adjudicatarios, TED no da los identificadores en el orden de los nombres. En el aviso
692450-2026, el primer NIF (A08092744) es el de B. Braun Medical, que figura en quinto lugar.

## Decisión
1. **Fuentes**: la sección V.A del sumario diario del BOE y los avisos `can-standard` de TED con `buyer-country=ESP`.
   El código está en `truthnews/data/contratacion.py`. Del título del BOE se leen el tipo (licitación, formalización,
   adjudicación, anulación, rectificación), el órgano, el objeto y el expediente. Lo que no se reconoce se deja
   vacío.
2. **NIF**: solo se atribuye cuando el aviso tiene un único adjudicatario y un único identificador con forma de NIF
   español. Con lotes de varias empresas, no se atribuye ninguno, porque emparejar por posición daría NIF ajenos.
3. **Importes**: el valor de un aviso con varios adjudicatarios no se suma a cada empresa, que se cuentan como
   «lotes». Así no se infla el total por empresa. Las empresas se agrupan por su nombre sin forma jurídica.
4. **Sin tablas**: es la misma revisión de datos que en nombramientos. En memoria caben un BOE por día, con un
   máximo de 120 días, y 14 días de TED, unas 1.000 adjudicaciones. Un día pasado con datos no cambia; TED se
   refresca cada 6 h y, si falla, cada 10 min, conservando la última lista buena. No hay migración ni ADR de
   datos. Si hiciera falta historial más largo (series por empresa de varios años), se escribirá un ADR
   `Tipo: datos` antes de crear tablas.
5. **Cruce con la prensa**: para las empresas que más suman, se listan las noticias rastreadas de los últimos
   60 días que nombran a la empresa por su nombre completo sin forma jurídica. Quedan fuera las UTE y los nombres
   que se reducen a palabras genéricas («grupo», «servicios»...) o a una sola palabra de menos de 6 letras. La
   página dice que la mención no implica relación con el contrato. Ni se afirma ni se insinúa irregularidad
   alguna.
6. **Dónde se ve**: en `/contratos`, enlazada en el pie y en el sitemap, en es y en. Cada fila enlaza su anuncio
   oficial.

## Alternativas consideradas
| Alternativa | Por qué no |
|---|---|
| Sindicación ATOM de la Plataforma de Contratación | Su robots.txt lo excluye todo. Rastrearla contradice el ADR 0003 y la decisión del usuario del 2026-10-19 |
| Emparejar NIF y nombre por posición en TED | Falso medido (aviso 692450-2026): atribuiría a una empresa el NIF de otra |
| Tablas `contrato` y `adjudicatario` ya | Sin necesidad medida: la página y el cruce de 60 días caben en memoria. Se decidirá con un ADR de datos cuando haga falta historial |
| Marcar «posible conflicto» al cruzar adjudicatario y noticia | Coincidir en un nombre no prueba nada. Sería un veredicto sin evidencia (ADR 0007) |

## Consecuencias
Se gana una sección de contratación citada y medible desde el primer despliegue, y la base para cruzar
contratos con hilos, entidades e investigaciones. Cuesta una petición a TED cada 6 h, con hasta 6 páginas de
250 avisos (unos 2,5 MB por página), y una al BOE por día visitado.

Pendiente, como subitems del ledger:
- contratos en la historia y en las investigaciones a demanda;
- BORME de los adjudicatarios (administradores y nombramientos mercantiles), cruzado con los nombramientos del BOE;
- portal de transparencia (retribuciones de altos cargos, convenios);
- licitaciones de comunidades autónomas en sus diarios oficiales.

## Verificación
`tests/test_contratacion.py` comprueba:
- el parseo del sumario real del 16/10/2026 (58 anuncios);
- las adjudicaciones reales de TED;
- que no se atribuye NIF con lotes;
- que no se inflan los importes;
- las cachés y el cierre ante fallos;
- la página en es y en, con el cruce con la prensa.

`tools/measure_contratacion.py` mide las fuentes en vivo.
