# ADR 0030 — El archivo se importa de los ficheros GKG de GDELT, no de su API

- **Estado:** aceptado (sustituye la fuente del archivo del ADR 0028; el esquema no cambia)
- **Fecha:** 2026-10-19
- **Fase:** 10 (hilo y consecuencias), item "Entidades y archivo historico" del ledger
- **Decide:** sesion Entidades, auditado por el Critico

## Contexto
El ADR 0028 importaba noticias antiguas por entidad con la API DOC de GDELT (`artlist`, un mes hacia
atras por consulta). Medido en produccion el 2026-10-19 (logs del worker 02:46-03:43 UTC): 3 consultas por
ciclo y 4, 0, 0 y 0 noticias nuevas; las consultas fallaban con 429 ("Please limit requests to one every 5
seconds"). Desde el contenedor de desarrollo, 6 peticiones espaciadas 20 s dieron 429 las 6: la API limita
por IP y las IP de salida de la nube son compartidas. Con esa fuente no hay archivo.

## Decision
1. **Fuente**: los ficheros GKG 2.1 de GDELT (`data.gdeltproject.org/gdeltv2/<AAAAMMDDHHMMSS>.translation.gkg.csv.zip`,
   y el `.gkg.csv.zip` en ingles solo si algun medio elegido publica en ingles). Son estaticos, un fichero
   cada 15 minutos desde el 19-02-2015, sin limite de peticiones, y cada fila trae medio, URL, fecha y titular
   original (`<PAGE_TITLE>`). Medido: el tramo 2025-03-05 12:15 trae 156 noticias de medios espanoles del
   registro, y 2 tramos se importan en 3,9 s.
2. **Recorrido**: hacia atras desde la noticia de archivo mas antigua (o la primera rastreada si aun no hay),
   un tramo cada `ARCHIVE_STRIDE_MINUTES` (360: uno cada 6 h, unas 300 noticias por ciclo y unos 12 dias de
   historia por dia de funcionamiento), `ARCHIVE_SLOTS_PER_CYCLE` tramos por ciclo (2) y solo medios de
   `ARCHIVE_COUNTRIES` (ES). Es independiente de las entidades: importa la prensa entera de esos medios y la
   extraccion de entidades (ADR 0028) la ordena despues, asi las fichas de cualquier persona ganan historia.
3. **Lo que se guarda** no cambia: titular, fecha y enlace con `origin = 'archivo'`; no se descarga la pagina
   del medio (ADR 0003) y no se verifica contra el dato de hoy.
4. **Fallos**: un tramo que no existe (404) se salta; un fallo de red para el paso sin deshacer lo importado y
   el ciclo siguiente lo reintenta (el cursor se deduce de la base, no se guarda aparte).
5. `entity.archived_until` (ADR 0028) deja de usarse; se queda en el esquema (nullable, sin coste) por si
   vuelve un archivo por entidad, y se retirara con la siguiente migracion que toque `entity`.

## Consecuencias
- Crecimiento de `article`: ~14.000 filas al dia con los valores por defecto (2 tramos x ~150 x 48 ciclos),
  dentro de la proyeccion del ADR 0028 (<= 0,5 M de archivo al ano); se ajusta con las variables sin
  desplegar codigo.
- La fecha de una noticia de archivo es la de GDELT (cuando la vio), no la de publicacion: puede diferir en
  horas; basta para la linea temporal por meses.
- Riesgo: un tramo sin noticias de esos medios no mueve el cursor de la base; el recorrido dentro del ciclo
  si avanza, y solo se repetiria si todos los tramos de un ciclo salieran vacios.
