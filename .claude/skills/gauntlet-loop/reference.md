# Gauntlet Loop — referencia tecnica

Complemento de `SKILL.md`. Aqui esta el esquema del manifiesto, la semantica exacta del runner y como
extenderlo. `SKILL.md` manda sobre el *protocolo*; este documento sobre la *mecanica*.

## Piezas (en el repositorio de trabajo, instaladas por loop-init)

| Ruta | Que es |
|---|---|
| `.claude/gauntlet.json` | Manifiesto: unica fuente de verdad de las puertas y su orden |
| `.claude/loop-engineering/gauntlet.py` | Runner (Python 3.9+, sin dependencias) |
| `.claude/loop-engineering/checks/hygiene.sh` | Puerta `hygiene`, independiente del toolchain |
| `.claude/loop-engineering/checks/enforcement.sh` | Puerta `enforcement`: vigila que los automatismos sigan activos e integros |
| `.claude/loop-engineering/checks/ledger.py` | Puerta `ledger` y parser compartido de `PENDIENTES.<repo>.md` y `OBJETIVO.<repo>.md` |
| `.claude/loop-engineering/checks/ratchet.py` | Puerta `ratchet`: las medidas publicadas no empeoran ni se salen del presupuesto |
| `.claude/loop-engineering/checks/datos.py` | Puerta `datos`: toda modificacion de la capa de datos lleva su ADR de datos en el mismo cambio |
| `.claude/loop-engineering/hooks/*` | Hooks de Claude Code: `session-start.sh`, `user-prompt.sh`, `stop-gauntlet-guard.py`, `stop-continuity-guard.py`, `protect-rules-repo.py` |
| `.claude/loop-engineering.json` | Version instalada, origen, `repo_name`, toolchains y sumas sha256 de la capa canonica |
| `bin/gauntlet` | Envoltorio para humanos y agentes; resuelve la raiz desde su propia ubicacion |
| `.claude/commands/gauntlet*.md` | Comandos de barra: `/gauntlet`, `-fast`, `-gate`, `-list`, `-status` |
| `.githooks/pre-commit` | Ejecuta el perfil `fast` en cada `git commit` |
| `.claude/.gauntlet/` | Logs, `last-run.json`, `history.json` y estado de los guards. Ignorado por git |

## Esquema del manifiesto

```jsonc
{
  "version": 1,                  // obligatorio, unico valor soportado
  "project": "mi-repo",          // informativo
  "defaults": { "timeout_seconds": 900 },
  "gates": [                     // el orden del array ES el orden de ejecucion
    {
      "id": "py:ruff",           // obligatorio, unico, usado en -g y en los nombres de log
      "title": "ruff",           // obligatorio, texto humano del resumen
      "command": "ruff check .", // obligatorio, se ejecuta con `bash -c` desde la raiz del repo
      "when": "test -f ruff.toml",           // opcional: si sale != 0 la puerta se marca SKIP
      "when_description": "no aplica: ...",  // opcional: motivo legible del SKIP
      "blocking": true,          // opcional (true por defecto): si false, su fallo es WARN
      "profiles": ["fast", "full"],          // perfiles que la seleccionan
      "timeout_seconds": 600,    // opcional; al agotarse se mata el grupo de procesos -> TIMEOUT
      "enabled": true,           // opcional (true por defecto)
      "disabled_reason": "...",  // obligatorio de facto si enabled es false
      "notes": "...",            // opcional, documentacion
      "fix_hint": "...",         // opcional, se imprime cuando la puerta falla
      "inputs": ["src/", "*.toml"],          // opcional: pathspecs de git de TODO lo que la puerta lee -> cache
      "cache_key": "tool --version",         // opcional (exige inputs): su salida entra en la huella
      "group": "lint"            // opcional: puertas CONSECUTIVAS con el mismo grupo van en paralelo
    }
  ]
}
```

Claves desconocidas hacen fallar el runner con exit 2: el manifiesto no acepta erratas silenciosas.

## Estados

| Estado | Significado | Efecto en el veredicto |
|---|---|---|
| `PASS` | exit 0 | — |
| `FAIL` | exit != 0 | ROJO si `blocking` |
| `TIMEOUT` | supero `timeout_seconds`; grupo de procesos abatido | ROJO si `blocking` |
| `WARN` | `FAIL`/`TIMEOUT` en puerta `blocking: false` | No cambia el veredicto; se lista aparte |
| `CACHED` | `inputs` declarados y misma huella que un PASS anterior: no se re-ejecuta | Cuenta como verificada; se declara aparte |
| `SKIP` | `when` no cumplido, o no ejecutada por aborto tras un fallo bloqueante | — |
| `DISABLED` | `enabled: false` | — |

Un `SKIP` **no** es un `PASS`: no aporta cobertura y hay que declararlo en el informe.

## Comportamiento del runner

- **Directorio de trabajo**: siempre la raiz del repositorio (`--root`, `GAUNTLET_ROOT` o
  `git rev-parse --show-toplevel` desde la ubicacion del propio runner). Los comandos del manifiesto se
  escriben relativos a la raiz.
- **Aborto temprano**: por defecto se detiene tras el primer fallo bloqueante (las puertas restantes
  quedan en `SKIP` con motivo explicito). `--no-bail` las ejecuta todas.
- **Perfiles**: un perfil no es mas que una etiqueta en `profiles`. `fast` = lo que aguanta un
  pre-commit; `full` = la pasada que cierra la tarea. Anadir un perfil es anadir su etiqueta.
- **Parcialidad**: `-g/--gate` ignora los perfiles y marca la ejecucion como `partial: true` en
  `last-run.json` (y `profile: null`). Una ejecucion parcial nunca cierra una tarea.
- **Cache por entradas** (`inputs`, `cache_key`; ADR 0012): ver la seccion Velocidad. `--no-cache`
  (o `GAUNTLET_NO_CACHE=1`) ejecuta todas las puertas; un PASS sigue refrescando la cache.
- **Grupos paralelos** (`group`): las puertas consecutivas con el mismo grupo se lanzan a la vez (hasta
  `-j/--jobs`, por defecto el numero de CPUs). Cada una escribe en su log; su salida se imprime al
  terminar el grupo, en el orden del manifiesto. El aborto temprano actua tras el grupo entero.
  `--serial` (o `--stream`) los ejecuta de uno en uno.
- **Tiempos**: el resumen imprime las tres puertas mas lentas y lo ahorrado por la cache; el historial
  guarda la duracion de cada puerta ejecutada (`durations`) y `--list` muestra la media.
- **Historial**: `.claude/.gauntlet/history.json` guarda las 20 ultimas ejecuciones. Si la misma puerta
  aparece en rojo en las 3 ultimas consecutivas, el runner imprime `ESCALADO: ...`.
- **Salida**: cada linea de cada puerta va al log; en fallo se imprimen las ultimas `--tail` lineas (40
  por defecto). `--stream` vuelca en vivo, `--json` anade el resumen en JSON.

### Variables de entorno

| Variable | Efecto |
|---|---|
| `GAUNTLET_PROFILE` | Perfil por defecto (si no se pasa `-p`) |
| `GAUNTLET_MANIFEST` | Ruta alternativa del manifiesto |
| `GAUNTLET_ROOT` | Raiz alternativa del repositorio |
| `GAUNTLET_NO_CACHE=1` | Igual que `--no-cache` |
| `GAUNTLET_SERIAL=1` | Igual que `--serial` |
| `GAUNTLET_JOBS` | Maximo de puertas simultaneas dentro de un grupo |
| `GAUNTLET_MAX_FILE_MB` | Limite de tamano de la puerta `hygiene` (5 por defecto) |
| `LOOP_FAST` | La puerta `py:unittest` (perfil fast) la exporta a 1 para que los tests lentos se omitan |
| `NO_COLOR` / `GAUNTLET_COLOR=always` | Control del color |

## Puertas por toolchain

`loop-init` genera el manifiesto a partir de `templates/gates/*.json` del repositorio de reglas segun lo
que detecta: `base` (siempre: `hygiene`, `enforcement`, `ledger`, `datos`, `ratchet`), `shell` (siempre;
autoguardadas), `node`, `python`, `rust`, `go`, `make`. Principio: el `when` comprueba que el proyecto
declara la herramienta (script en `package.json`, seccion en `pyproject.toml`, `Cargo.toml`, `go.mod`,
target en el `Makefile`); si la declara y la herramienta no esta, la puerta FALLA y el arreglo es
instalarla o declarar `NO VERIFICADO`. Unica excepcion: herramientas que nadie declara (`shellcheck`),
con `when: command -v` y SKIP ruidoso. Las puertas de Python excluyen `.claude/`: la maquinaria del
loop es herramienta instalada, no codigo del proyecto; la lintea el gauntlet del repositorio de reglas.

`loop-init --update` anade al manifiesto existente las puertas base que falten sin tocar las demas.

## Anadir una puerta

1. Deja el comando funcionando a mano primero.
2. Insertalo en `gates` **en su posicion de coste**: barato arriba, caro abajo. Un fallo caro que se
   podia detectar barato es tiempo perdido en cada iteracion del bucle.
3. Elige perfiles: si tarda menos de ~30 s y no necesita build, entra en `fast`; si no, solo `full`.
4. Escribe `when` para que la puerta se auto-omita mientras el proyecto no la declare, y
   `when_description` para que el SKIP se explique solo.
5. Si depende de un script, anadelo a la puerta de contrato del toolchain.
6. **Canario**: provoca el fallo que la puerta debe detectar y comprueba que sale ROJO. Una puerta que
   nunca ha fallado no esta demostrada.
7. Verifica el conjunto: `bin/gauntlet --list` y `bin/gauntlet -p full`.

Para puertas de dominio (presupuestos de rendimiento, contratos de datos): el umbral vive en el script
o en su config, nunca en el manifiesto. Asi el gauntlet solo decide *si* se pasa y el proyecto decide
*que* se mide. Los numeros medidos se publican en `docs/benchmarks/fase_N.json` y la puerta `ratchet`
impide que empeoren. El ratchet compara cada fase con la anterior por `fecha` y, en empate, por
nombre de fichero (ADR 0013): `fecha` es el **dia** de la medida (`AAAA-MM-DD`) y solo lleva hora
real (`AAAA-MM-DDTHH:MM:SSZ`) si otra fase ya publico ese mismo dia. Una hora adelantada para ganar
orden es una medida falsa.

## Velocidad sin perder calidad

Un proyecto pesado (Unreal Engine, monorepos con builds de decenas de minutos) no se acelera
quitando puertas de `full` ni moviendolas a un perfil que nadie ejecuta: eso es bajar el liston y
exige peticion del usuario (CLAUDE.md, seccion 5). Se acelera no repitiendo trabajo ya verificado y
no serializando lo independiente (ADR 0012).

**1. Mide antes de tocar nada.** El resumen dice `mas lentas: ...` y `bin/gauntlet --list` da la media
de cada puerta. Optimiza la que se come el reloj, no la que es facil.

**2. Cache por entradas.** Con `inputs`, el runner calcula en cada pasada una huella con: el esquema
de la cache, `command`, `when`, `inputs`, la salida de `cache_key` y, por cada fichero que casan los
`inputs` (seguidos y sin seguimiento no ignorados, `git ls-files -c -o --exclude-standard`), su ruta,
su bit de ejecucion y el sha256 de su contenido. Si un PASS anterior tiene la misma huella, la puerta
sale `CACHED`. Garantias, todas con canario en `tests/test_runner.py`:

- cualquier cambio de contenido, fichero nuevo, borrado o cambio de modo en los `inputs` la re-ejecuta;
- cambiar `command`, `when`, `inputs` o la salida de `cache_key` la re-ejecuta; si `cache_key` falla,
  no hay cache;
- un FAIL o TIMEOUT nunca se cachea; sin `inputs`, nunca hay cache;
- unos `inputs` que no casan ningun fichero (errata) desactivan la cache y lo avisan;
- si las entradas cambian mientras la puerta corre, el PASS no se guarda;
- la memoria de shas por (tamano, mtime, ctime, inodo) nunca se usa para ficheros de hace menos de
  3 s, y reescribir con el mismo tamano y la misma mtime se detecta (cambia el ctime).

La responsabilidad del manifiesto es que los `inputs` cubran **todo lo que la puerta lee** del
repositorio y que `cache_key` cubra lo que lee de fuera (version del compilador, del motor, de las
dependencias). Lo que el proyecto ignora en git (salidas de build, caches) no entra, y es correcto:
es derivado. Ante la duda, mas entradas: una entrada de mas cuesta una ejecucion; una de menos es
un PASS inventado. La cache vive en `.claude/.gauntlet/cache.json` (local, no versionada) y la CI
arranca sin ella, asi que su veredicto es independiente.

**3. Grupos paralelos.** Lint, formato, validacion de contenido y comprobaciones que no se pisan
(no escriben en el mismo sitio, no compiten por el mismo build) van con el mismo `group`, seguidas en
el manifiesto. Lo que depende de otra puerta (tests tras el build) no se agrupa con ella.

**4. Cache del propio toolchain.** El runner no puede hacer incremental una herramienta que limpia:
nada de `clean`/`rebuild` en las puertas, y la cache del compilador o del motor en una ruta que
sobreviva entre sesiones (en sesiones remotas el contenedor arranca vacio).

### Ejemplo: proyecto de Unreal Engine

Plantilla orientativa (Linux; en Windows, `Build.bat`, `RunUAT.bat` y `UnrealEditor-Cmd.exe`).
`<P>` es el nombre del proyecto; `UE_ROOT`, la raiz del motor:

```jsonc
{ "id": "ue:format", "group": "estatico", "profiles": ["fast", "full"],
  "command": "git ls-files -z -- 'Source/*.h' 'Source/*.cpp' | xargs -0 -r clang-format --dry-run --Werror",
  "inputs": ["Source/", ".clang-format"], "cache_key": "clang-format --version" },
{ "id": "ue:assets", "group": "estatico", "profiles": ["full"], "command": "<validacion de assets del proyecto>",
  "inputs": ["Content/", "Config/"] },
{ "id": "ue:build", "profiles": ["full"], "timeout_seconds": 5400,
  "command": "\"$UE_ROOT/Engine/Build/BatchFiles/Linux/Build.sh\" <P>Editor Linux Development -Project=\"$PWD/<P>.uproject\" -WaitMutex",
  "inputs": ["Source/", "Plugins/", "Config/", "*.uproject"],
  "cache_key": "cat \"$UE_ROOT/Engine/Build/Build.version\"" },
{ "id": "ue:tests", "profiles": ["full"], "timeout_seconds": 3600,
  "command": "\"$UE_ROOT/Engine/Binaries/Linux/UnrealEditor-Cmd\" \"$PWD/<P>.uproject\" -ExecCmds=\"Automation RunTests <P>;Quit\" -TestExit=\"Automation Test Queue Empty\" -unattended -nullrhi -nosplash -nosound -NoP4 -log",
  "inputs": ["Source/", "Plugins/", "Config/", "Content/", "*.uproject"],
  "cache_key": "cat \"$UE_ROOT/Engine/Build/Build.version\"" },
{ "id": "ue:cook", "profiles": ["full"], "timeout_seconds": 5400,
  "command": "\"$UE_ROOT/Engine/Build/BatchFiles/RunUAT.sh\" BuildCookRun -project=\"$PWD/<P>.uproject\" -platform=Linux -cook -iterate -skipstage -nop4 -unattended -nullrhi",
  "inputs": ["Source/", "Plugins/", "Config/", "Content/", "*.uproject"],
  "cache_key": "cat \"$UE_ROOT/Engine/Build/Build.version\"" }
```

Que gana cada vuelta del bucle: un cambio solo en `Content/` re-ejecuta assets, tests y cook, pero no
el build; un arreglo de formato re-ejecuta el formato y el build, y los tests si tocan `Source/`; una
pasada repetida sin cambios (la que exige el bucle tras un rojo arreglado en otra puerta) cuesta lo
que el hash. Fuera del runner, lo que mas acorta una pasada en frio es una DDC compartida y la cache
de compilacion de UBA en una ruta persistente, y `Intermediate/` y `Binaries/` sin limpiar.

## Puerta `datos`: revision de arquitectura de datos

Toda modificacion de la capa de datos lleva su revision escrita, como ADR de tipo `datos`, en el mismo
cambio. La puerta no juzga el razonamiento: garantiza que la revision existe, que es de este cambio y
que responde a cada pregunta (ADR 0011).

- **Que compara.** Lo que cambia frente a la rama por omision (merge-base de HEAD con `origin/HEAD`,
  `origin/main`, `origin/master`, `main` o `master`, en ese orden; `GAUNTLET_BASE_REF` fuerza otra
  referencia) mas el arbol de trabajo (indice, modificados y sin seguimiento). En un clon superficial
  sin la rama por omision solo ve el arbol de trabajo.
- **Que es capa de datos.** Por ruta: `migrations/`, `migrate/`, `alembic/`, `prisma/`, `drizzle/`,
  `liquibase/`, `flyway/`, `db/schema/`, `*.prisma`, `*.dbml`, `*.ddl`, `schema.sql`, `structure.sql`,
  `schema.rb`, `knexfile.*`... Por contenido: DDL (`CREATE|ALTER|DROP TABLE|INDEX|VIEW|...`,
  `ADD|DROP COLUMN`) o marcadores de ORM, migrador o almacen (SQLAlchemy, Alembic, Django, TypeORM,
  JPA, EF Core, Knex, Sequelize, Rails, Laravel, Ecto, Drizzle, Diesel, GORM, ent, Mongoose, Mongo,
  Elasticsearch, Liquibase, DynamoDB, Terraform de bases de datos). Fuera por defecto: `docs/`,
  `.claude/`, `.github/`, tests y fixtures, dependencias y salidas de build. Un `.sql` con solo
  `INSERT` no es esquema.
- **Que exige.** Cada fichero de datos cambiado esta cubierto por un ADR `docs/adr/NNNN-*.md` con
  `- **Tipo:** datos` en la cabecera, que **tambien cambia en el diff** (un ADR aceptado no se edita:
  la siguiente modificacion lleva el suyo) y que lo nombra en `## Alcance` (rutas exactas o globs,
  entre acentos graves, una por linea). Ese ADR tiene las diez secciones de
  `docs/adr/0000-plantilla-datos.md` (Contexto, Necesidad, Escalabilidad, Coherencia, Alternativas
  consideradas, Necesidades futuras, Migracion y reversibilidad, Decision, Verificacion, Alcance) con
  al menos 80 caracteres escritos cada una, fuera de los comentarios `<!-- -->` de la plantilla, sin
  `TODO`/`TBD`/`FIXME`, con `Estado` distinto de `plantilla` y con al menos una cifra en
  `## Escalabilidad`. Acentos en los titulos de seccion dan igual.
- **Configuracion**, opcional y versionada, en `.claude/datos.json`:
  `{"version": 1, "incluir": ["infra/db/**"], "excluir": [{"glob": "tools/seed.sql", "motivo": "..."}]}`.
  `incluir` anade rutas que la deteccion no ve; `excluir` saca falsos positivos, **con motivo** (15
  caracteres como minimo; sin el, la puerta falla) y con peticion explicita del usuario: excluir es
  relajar la puerta y se hace a la vista. Las exclusiones aplicadas se imprimen como AVISO.
- **Salidas.** `OK: sin cambios en la capa de datos` cuando no hay nada que revisar; `OK` con la lista
  de ficheros y el ADR que los cubre; en rojo, por fichero, si no hay ADR, si el unico que lo cubre no
  cambia en el diff, o que seccion del ADR falla y por que. `datos.py --json` vuelca la clasificacion.
- **Protocolo del agente.** La revision se escribe **antes** de la migracion: copiar la plantilla,
  responder cada pregunta con hechos del repositorio y cifras medidas, y si la conclusion es que el
  cambio no hace falta, no hacerlo. Rellenar las secciones para que la puerta pase sin haber pensado
  el diseño es fabricar, con la misma gravedad que un gauntlet verde de memoria.

## Resolucion de problemas

| Sintoma | Causa habitual y salida |
|---|---|
| exit 2 `no existe el manifiesto` | Se ejecuta con `--root`/`GAUNTLET_ROOT` apuntando fuera del repo, o el sistema no esta instalado (`bin/loop-init`) |
| exit 2 `claves desconocidas` | Errata en una clave del manifiesto; compara con el esquema de arriba |
| Todas las puertas en `SKIP` | El proyecto aun no declara ningun toolchain: es correcto al principio, pero hay que decirlo en el informe |
| `enforcement` en rojo por sumas | Alguien edito la capa canonica a mano; `loop-init --update` la restaura (en el repositorio de reglas: `loop-init --self`) |
| `ledger` en rojo por coexistencia | Hay un `PENDIENTES.md`/`OBJETIVO.md` sin nombre junto al nombrado: retira el legado en un commit aparte |
| `datos` en rojo con un fichero que no es esquema | Falso positivo de la deteccion por contenido: excluyelo en `.claude/datos.json` con su motivo, a la vista y con el usuario; nunca borrando el DDL del fichero para que pase |
| `datos` en rojo por un ADR que "ya existe" | El ADR es de una modificacion anterior y no cambia en este diff: cada modificacion lleva su propia revision, en un ADR nuevo |
| Una puerta pasa suelta (`-g`) y falla en `-p full` | Efecto de una puerta anterior (build, deps, artefactos). Diagnostica siempre con la pasada completa |
| Una puerta cara sale `CACHED` y sospechas de ella | `--no-cache` la ejecuta; si entonces falla, sus `inputs` no cubren algo que lee: amplialos (nunca al reves) |
| Una puerta con `inputs` se ejecuta siempre | Mira el aviso: `inputs` que no casan nada, `cache_key` que falla, o la propia puerta escribe en sus entradas (genera codigo en `Source/`): saca lo generado a una ruta ignorada |
| `TIMEOUT` en una puerta que antes iba bien | Proceso colgado, no un limite demasiado bajo: revisa el log antes de subir `timeout_seconds` |
| El pre-commit no se ejecuta | `git config core.hooksPath` no apunta a `.githooks`; ejecuta `bin/loop-doctor` desde el repositorio de reglas o `git config core.hooksPath .githooks` |
| Exit 141 al canalizar la salida | SIGPIPE por `\| head`; no es un veredicto. El veredicto se lee de una ejecucion sin tuberia truncante |
| El hook `Stop` bloquea el cierre | Falta la pasada verde posterior al ultimo cambio: ejecutala. Si no puede quedar verde, escala; no crees `disable-stop-guard` |

## Semantica del guard `Stop` del gauntlet

Al intentar cerrar el turno compara el arbol de trabajo (`git status --porcelain=v1 -z -uall`, asi que
un archivo nuevo dentro de un directorio nuevo tambien cuenta y las rutas con espacios o no ASCII no
se pierden) con `.claude/.gauntlet/last-run.json` y **bloquea** (exit 2) si falta una pasada que sea a
la vez: VERDE, completa (no `-g`), del perfil exigido por el tipo de cambio, y posterior en el tiempo al
ultimo archivo modificado.

- El perfil exigido es `full`, salvo que *todos* los archivos cambiados sean documentacion (`.md`,
  `.txt`, `.rst`, `.adoc` o bajo `docs/`), en cuyo caso basta `fast` y `full` tambien vale.
- Exime a `PENDIENTES.<repo>.md`: es estado de continuidad, no un entregable.
- Cota por progreso: la clave es (rutas cambiadas, fecha del ultimo cambio, fecha de la ultima pasada).
  Dos bloqueos con la misma clave y el tercero deja cerrar con `ESCALADO`. Una edicion o una pasada
  nueva reinician el contador. No basta con `stop_hook_active`: honrarlo dejaria cerrar a la segunda con
  el arbol igual de sin verificar.
- Valvula de escape humana: `touch .claude/.gauntlet/disable-stop-guard`. Para el agente, crear ese
  archivo es una regla dura violada.

## Integracion con CI

El mismo contrato debe correr en CI, con el mismo comando y sin reimplementarlo:

```yaml
- run: bin/gauntlet -p full --no-bail
```

`--no-bail` en CI da el panorama completo en un solo run; en local el aborto temprano es mas rapido.
La CI no debe restaurar `.claude/.gauntlet/` entre ejecuciones: arrancar sin cache es lo que hace de
su veredicto un segundo veredicto independiente. Si
CI y el gauntlet local divergen, el manifiesto es el que manda: corrige CI, no el manifiesto. Si el
proyecto no tiene CI operativa (sin runners, sin cuota), la pasada local es el unico veredicto y se
declara asi en `## Decisiones del usuario` de la carta.
