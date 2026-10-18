# ADR 0001 — Una aplicacion Python con web SSR y worker programado sobre PostgreSQL

- **Estado:** aceptado
- **Fecha:** 2026-10-18
- **Fase:** 1
- **Decide:** Constructor, auditado por el Critico

## Contexto
El repositorio parte vacio (`06c3ab1`). La carta pide un periodico que rastree medios, contraste con
datos, se navegue por segmentos (C1, C2, C7, C10) y se despliegue en Railway (C11) cuanto antes. El
trabajo dominante es E/S de red (feeds, APIs de datos), procesamiento de texto y paginas HTML
indexables por buscadores.

## Decision
Un unico paquete Python (`truthnews`, Python >= 3.12) con dos procesos desde la misma imagen: `web`
(FastAPI + Jinja2, HTML renderizado en servidor) y `worker` (planificador que ejecuta rastreo y
analisis); persistencia en PostgreSQL via SQLAlchemy 2 y migraciones Alembic (SQLite en tests y
desarrollo); el registro de medios, paises, categorias y textos de interfaz vive en ficheros YAML de
`truthnews/registry/`, para que anadir un pais o un idioma sea anadir datos.

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Next.js + API en Node | Dos toolchains para un equipo de un agente; el ecosistema de extraccion de texto (trafilatura, feedparser) y de datos esta en Python |
| SPA con API JSON | Peor SEO para un medio que vive de buscadores y redes; mas codigo para la misma portada |
| Microservicios del holding (`crawler`, `social`, `publicdata`) como nucleo | `HOLDING_PLATFORM_API_KEY` falta (medido con `holding_estado`); se integran como adaptadores opcionales, no como dependencia dura |
| Un solo proceso web con planificador dentro | El rastreo compite con las peticiones web; se mantiene la opcion por variable (`TRUTHNEWS_ROLE=all`) para despliegues minimos |

## Consecuencias
Un toolchain (Python), una imagen, dos comandos de arranque. Anadir pais/idioma no toca codigo. El
precio: el HTML es SSR sin interactividad rica (suficiente para un periodico); Postgres es un servicio
mas que mantener en Railway.

## Verificacion
Puertas `py:ruff`, `py:pytest` (con cobertura) del gauntlet; test que carga el registro y comprueba
que un segundo pais existe solo en datos.
