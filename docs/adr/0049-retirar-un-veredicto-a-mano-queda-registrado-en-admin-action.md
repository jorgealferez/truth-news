# ADR 0049 — Retirar un veredicto a mano queda registrado en `admin_action`

- **Estado:** aceptado
- **Tipo:** datos
- **Fecha:** 2026-10-19
- **Fase:** Verificaciones a escala (carril Verificaciones)
- **Decide:** Constructor, auditado por el Critico

## Contexto
El 19/10/2026 a las 08:17 UTC se publicaron dos "Falso" injustos: Infobae (paro de EEUU juzgado contra
Argentina) y La Razon (IPC de Francia juzgado contra Espana). El arreglo de metodo (v11, #182) los
corrige en el siguiente ciclo del worker con el re-juicio automatico (`reverify_outdated`). Pero entre el
fallo y el ciclo no habia forma de retirarlos: el panel /admin no tiene ninguna accion sobre veredictos y
ninguna sesion tiene acceso a la base de produccion. La direccion pide una ruta protegida para "retirar
un veredicto con nota de correccion" y que quede registrado quien la uso, cuando y por que.

Hoy el veredicto vive en `verification` (`verdict`, `explanation`, `method`, `checked_at`). La nota de
correccion publica ya se escribe dentro de `explanation` ("[Corregido el ...]"). No hay ninguna tabla de
auditoria de acciones manuales.

## Necesidad
La nota publica cuenta al lector que se corrigio y por que, pero no guarda quien lo hizo. Los logs de
Railway cubren el "quien" solo unos dias. Sin una tabla, una retirada manual no se puede auditar despues,
y un veredicto se podria cambiar sin rastro, lo que choca con la neutralidad y la transparencia del sitio.
Alternativas sin esquema: meter el usuario en `explanation` (publico: expone datos internos y no se puede
consultar) o en `method` (String(40), ya usado para el metodo). Ninguna da un registro consultable.

## Escalabilidad
Una fila por accion manual. Hoy 0; previsto menos de 10 al dia en el peor caso (son excepciones: lo normal
es corregir el metodo). A 12 meses, menos de 4 000 filas y menos de 1 MB. Solo se escribe desde /admin y
se lee en /admin (ultimas 20, por `at` descendente): indice en `at`. A 10x sigue siendo trivial.

## Coherencia
Tabla `admin_action`: `id` Integer PK; `at` DateTime(timezone=True) not null, por defecto `utcnow`, con
indice; `user` String(60) not null (usuario de HTTP Basic); `action` String(30) not null con check
(`retirar-veredicto`, `restituir-veredicto`); `target` String(60) not null ("verification:<id>"); `reason` Text not null;
`before` String(16) nullable (veredicto anterior). Sin clave foranea a `verification`: la auditoria tiene
que sobrevivir aunque se borre la afirmacion. Mismas convenciones de nombres y tipos que el resto
(`utcnow`, `String`, checks con nombre `ck_<tabla>_<columna>`).

El veredicto retirado queda en `verification` con `verdict = 'sin-datos'`, `method =
'retirada-manual/<version>'` y la nota publica "[Retirado el dd/mm/aaaa: <motivo>]". `reverify_outdated`
no re-juzga los metodos que empiezan por `retirada-manual`: una retirada a mano no la deshace un cambio de
version del metodo.

Restituir (pedido por la direccion) deshace una retirada con su propio registro: pone `method =
'restituida/manual'`, que no acaba en la version vigente, y el siguiente ciclo lo vuelve a juzgar con el
metodo vigente. El re-juicio conserva las notas publicas anteriores ([Corregido], [Retirado], [Restituido])
para que el lector vea cada cambio que hubo. El motivo de una retirada se muestra destacado en /verificaciones
y en la ficha ("Retirado por la redaccion").

## Alternativas consideradas
| Alternativa | Por que no |
|---|---|
| Columnas `retired_by`, `retired_at`, `retired_reason` en `verification` | Solo guarda la ultima accion y mezcla auditoria con el veredicto; no sirve para otras acciones manuales |
| Solo log del servidor | Los logs caducan y no se pueden consultar desde el panel |
| Tabla generica de eventos con JSON | Mas flexible pero sin checks; para una accion basta un esquema explicito |

## Necesidades futuras
Otras acciones manuales del panel (por ejemplo, despublicar una pieza) caben en la misma tabla
ampliando el check de `action` en su propia migracion. Si el panel llega a tener varios usuarios, `user`
ya los distingue.

## Migracion y reversibilidad
Migracion 0021 (`down_revision` = cabeza de main al hacer merge; hoy 0018): `create_table` y un indice, sin tocar
tablas existentes ni rellenar datos. Es compatible con el codigo que corre durante el despliegue, que no
conoce la tabla. Se revierte con `drop_table`; al revertir se pierde el registro de las acciones manuales,
pero no los veredictos ni sus notas publicas.

## Decision
Se crea `admin_action` y dos rutas, `POST /admin/verificacion/{id}/retirar` y `.../restituir` (HTTP Basic y
CSRF, motivo obligatorio de 10 a 500 caracteres), que dejan una fila en `admin_action` cada una. Retirar
pasa el veredicto a "sin datos" con nota publica; restituir lo devuelve al re-juicio del metodo vigente.

## Alcance
- `alembic/versions/0021_acciones_de_admin.py`
- `truthnews/models.py`

## Verificacion
Tests: la migracion se aplica y se revierte en sqlite (`tests/test_migrations` si existe, y el arranque
de la app de tests); la ruta exige credenciales y CSRF; retira con nota y registra quien, cuando y por que;
el re-juicio posterior no la deshace; restituir
deja su propio registro y el re-juicio conserva las notas; el motivo se ve en las paginas publicas.
