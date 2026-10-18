#!/usr/bin/env python3
"""Puerta `datos` (loop-engineering): toda modificacion de la capa de datos lleva su revision de
arquitectura, escrita como ADR de tipo `datos`, en el mismo cambio.

Que mira. Los ficheros que cambian respecto a la rama por omision (merge-base de HEAD con
origin/HEAD, origin/main, origin/master, main o master, en ese orden; `GAUNTLET_BASE_REF` fuerza
otra referencia) mas el arbol de trabajo (indice, modificados y sin seguimiento). De ellos, los que
tocan la capa de datos:

  1. por ruta: migrations/, alembic/, prisma/, drizzle/, db/migrate/, *.prisma, schema.sql...
  2. por contenido: DDL (CREATE/ALTER/DROP TABLE|INDEX|VIEW..., ADD/DROP COLUMN) o un marcador de
     ORM o migrador (SQLAlchemy, Alembic, Django, TypeORM, JPA, EF Core, Knex, Sequelize, Rails,
     Laravel, Ecto, Drizzle, Diesel, GORM, ent, Mongoose, Liquibase, Terraform de almacenes...),
     fuera de docs/, tests y .claude/.

Que exige. Cada fichero de datos cambiado esta cubierto por un ADR `Tipo: datos` que **tambien cambia
en este diff** (nuevo, normalmente: un ADR aceptado no se edita, la siguiente modificacion lleva el
suyo) y que lo nombra en `## Alcance`. Ese ADR tiene las diez secciones de la plantilla
`docs/adr/0000-plantilla-datos.md` escritas de verdad: sin comentarios de plantilla, sin TODO, con
una cifra en `## Escalabilidad`. La puerta no juzga la calidad del razonamiento (eso lo hace el
agente al escribirlo y la persona al leer el PR); garantiza que la revision existe, que es de este
cambio y que responde a cada pregunta.

Config opcional, versionada: `.claude/datos.json`
  {"version": 1,
   "incluir": ["infra/db/**"],
   "excluir": [{"glob": "tools/seed.sql", "motivo": "solo INSERT de datos de prueba"}]}
Una exclusion sin motivo falla: excluir es relajar la puerta y se hace a la vista, con peticion
explicita del usuario.

Sin cambios en la capa de datos -> OK en silencio. Uso: datos.py [--json]
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ADR_DIR = "docs/adr"
CONFIG_PATH = ".claude/datos.json"
TEMPLATE_PREFIX = "0000-"
MIN_CHARS = 80
MAX_BYTES = 1_000_000

REQUIRED_SECTIONS = (
    "Contexto",
    "Necesidad",
    "Escalabilidad",
    "Coherencia",
    "Alternativas consideradas",
    "Necesidades futuras",
    "Migracion y reversibilidad",
    "Decision",
    "Verificacion",
    "Alcance",
)

DOC_SUFFIXES = (".md", ".txt", ".rst", ".adoc")
SKIP_PREFIXES = (
    "docs/",
    ".claude/",
    ".github/",
    "node_modules/",
    "vendor/",
    "dist/",
    "build/",
    "target/",
)
TEST_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec|specs|fixtures|testdata|__snapshots__|__mocks__)(/|$)"
    r"|(^|/)[^/]*[._-](test|spec)\.[^/]+$"
    r"|(^|/)test_[^/]+\.py$"
    r"|(^|/)conftest\.py$"
)

# 1. Rutas que son capa de datos por si mismas.
PATH_RE = re.compile(
    r"(^|/)(migrations?|migrate|alembic|liquibase|flyway|sqitch|dbmate|goose|atlas|drizzle|prisma"
    r"|supabase/migrations|db/schema|database/schema)(/|$)"
    r"|(^|/)(schema|structure)\.(sql|rb|prisma|dbml|hcl)$"
    r"|\.(prisma|dbml|ddl)$"
    r"|(^|/)knexfile\.[cm]?[jt]sx?$"
    r"|(^|/)(db|database)/(changelog|migrat)[^/]*\.(xml|ya?ml|json|sql)$",
    re.IGNORECASE,
)

# 2a. DDL en cualquier fichero de texto (SQL suelto, cadenas en codigo, scripts).
DDL_RE = re.compile(
    r"\b(CREATE|ALTER|DROP)\s+(OR\s+REPLACE\s+)?(TEMP(ORARY)?\s+)?(UNLOGGED\s+)?"
    r"(TABLE|INDEX|UNIQUE\s+INDEX|MATERIALIZED\s+VIEW|VIEW|SCHEMA|TYPE|SEQUENCE|EXTENSION|TRIGGER"
    r"|FUNCTION|PROCEDURE|DOMAIN|POLICY)\b"
    r"|\b(ADD|DROP|ALTER|RENAME)\s+COLUMN\b",
    re.IGNORECASE,
)

# 2b. Marcadores de ORM, migradores y definiciones de almacen (sensibles a mayusculas).
ORM_RE = re.compile(
    r"__tablename__\s*="  # SQLAlchemy declarativo
    r"|\bTable\(\s*['\"]\w+['\"]\s*,\s*\w*[Mm]eta"  # SQLAlchemy Core
    r"|\bSQLModel\b[^\n]*\btable\s*=\s*True"  # SQLModel
    r"|\bop\.(add_column|drop_column|create_table|drop_table|alter_column|create_index|drop_index"
    r"|rename_table|create_foreign_key|drop_constraint|create_unique_constraint|execute)\("  # Alembic
    r"|\bmigrations\.(AddField|RemoveField|AlterField|RenameField|CreateModel|DeleteModel"
    r"|RenameModel|AddIndex|RemoveIndex|AddConstraint|RemoveConstraint|RunSQL|RunPython"
    r"|AlterUniqueTogether|AlterModelTable)\("  # Django migraciones
    r"|\bmodels\.Model\b"  # Django / Tortoise modelos
    r"|\.schema\.(createTable|createTableIfNotExists|alterTable|dropTable|dropTableIfExists"
    r"|renameTable|table)\("  # Knex
    r"|\bqueryInterface\.(createTable|dropTable|addColumn|removeColumn|changeColumn|renameColumn"
    r"|addIndex|removeIndex|addConstraint)\("  # Sequelize migraciones
    r"|\bsequelize\.define\("  # Sequelize modelos
    r"|@(Entity|Embeddable|MappedSuperclass)\b"  # TypeORM / JPA / Hibernate
    r"|@(Table|Column|JoinColumn|PrimaryGeneratedColumn|PrimaryColumn|ManyToOne|OneToMany"
    r"|ManyToMany|OneToOne|Index|Unique)\("
    r"|\bmigrationBuilder\.\w+\(|\bmodelBuilder\.Entity<|\bDbSet<"  # EF Core
    r"|\bSchema::(create|table|drop|dropIfExists|rename)\("  # Laravel
    r"|\b(create_table|drop_table|add_column|remove_column|change_column|rename_column|add_index"
    r"|remove_index|add_reference|add_foreign_key|create_join_table)\s*[:(]"  # Rails
    r"|\bActiveRecord::Migration\b"
    r"|\b(create|alter|drop)\s+(table|index|unique_index)\(:"  # Ecto migraciones
    r"|^\s*schema\s+\"[^\"]+\"\s+do\b"  # Ecto esquemas
    r"|\b(pgTable|mysqlTable|sqliteTable|pgEnum|pgSchema)\("  # Drizzle
    r"|\bdefineTable\("  # Convex
    r"|\bmongoose\.Schema\(|\bnew\s+Schema(<[^>\n]*>)?\(\s*\{"  # Mongoose
    r"|\.(createCollection|createIndex|createIndexes|dropCollection|dropIndex)\("  # Mongo
    r"|\.indices\.(create|putMapping|delete)\("  # Elasticsearch / OpenSearch
    r"|\bdiesel::table!|^\s*table!\s*\{"  # Diesel
    r"|\bsqlx::migrate!|\brefinery::embed_migrations!"  # sqlx / refinery
    r"|\bgorm:\"|\bAutoMigrate\("  # GORM
    r"|\bent\.Schema\b|\bfield\.(String|Int|Int64|Bool|Time|UUID|Enum|JSON|Float|Text)\("  # ent
    r"|^\s*table\s+\"[^\"]+\"\s*\{"  # Atlas HCL
    r"|<(createTable|addColumn|dropTable|dropColumn|createIndex|modifyDataType|renameColumn)\b"
    r"|^\s*-?\s*(createTable|addColumn|dropTable|dropColumn|createIndex|modifyDataType)\s*:"  # Liquibase
    r"|\b(CreateTable|UpdateTable|DeleteTable)(Command)?\("  # DynamoDB SDK
    r"|resource\s+\"(aws_dynamodb_table|aws_rds_cluster|aws_db_instance|aws_redshift_cluster"
    r"|aws_elasticache_cluster|aws_opensearch_domain|google_bigquery_table|google_sql_database"
    r"|google_spanner_database|azurerm_mssql_database|azurerm_cosmosdb_sql_container"
    r"|mongodbatlas_cluster)\"",  # Terraform: almacenes y tablas
    re.MULTILINE,
)

COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
HEADER_FIELD_RE = re.compile(
    r"^\s*(?:-\s*)?\*{0,2}\s*([A-Za-z]+)\s*:?\*{0,2}\s*:?\s*(.+?)\s*$"
)
PLACEHOLDER_RE = re.compile(
    r"\b(TODO|TBD|FIXME|XXX)\b|pendiente de (encuadre|rellenar|escribir|revisar)",
    re.IGNORECASE,
)
TABLE_RULE_RE = re.compile(r"^\s*\|?\s*:?-{3,}")
BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
CODE_RE = re.compile(r"`([^`]+)`")
GLOB_CHARS = set("*?[")


# --------------------------------------------------------------------------- #
# utilidades
# --------------------------------------------------------------------------- #
def norm(text: str) -> str:
    """Minusculas y sin acentos: 'Decisión' y 'decision' son la misma seccion."""
    plain = unicodedata.normalize("NFKD", text)
    return "".join(c for c in plain if not unicodedata.combining(c)).strip().lower()


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )


def git_bytes(root: Path, *args: str) -> bytes | None:
    res = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False
    )
    return res.stdout if res.returncode == 0 else None


def glob_regex(pattern: str) -> re.Pattern:
    """Glob de rutas (`**`, `*`, `?`) a regex. Sin comodines, una ruta cubre tambien su contenido."""
    pat = pattern.strip()
    while pat.startswith("./"):
        pat = pat[2:]
    pat = pat.lstrip("/")
    if not (GLOB_CHARS & set(pat)):
        return re.compile("^" + re.escape(pat.rstrip("/")) + "(/.*)?$")
    if pat.endswith("/"):
        pat += "**"
    out = ""
    i = 0
    while i < len(pat):
        c = pat[i]
        if pat.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
            continue
        if pat.startswith("**", i):
            out += ".*"
            i += 2
            continue
        if c == "*":
            out += "[^/]*"
        elif c == "?":
            out += "[^/]"
        else:
            out += re.escape(c)
        i += 1
    return re.compile("^" + out + "$")


# --------------------------------------------------------------------------- #
# que ha cambiado
# --------------------------------------------------------------------------- #
def head_commit(root: Path) -> str | None:
    res = git(root, "rev-parse", "-q", "--verify", "HEAD")
    return res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else None


def base_commit(root: Path) -> tuple[str | None, str | None]:
    """(merge-base con la rama por omision, referencia usada); (None, None) si no hay ninguna."""
    candidates: list[str] = []
    forced = os.environ.get("GAUNTLET_BASE_REF")
    if forced:
        candidates.append(forced)
    sym = git(root, "symbolic-ref", "-q", "refs/remotes/origin/HEAD").stdout.strip()
    if sym:
        candidates.append(sym)
    candidates += [
        "refs/remotes/origin/main",
        "refs/remotes/origin/master",
        "refs/heads/main",
        "refs/heads/master",
    ]
    for ref in candidates:
        if git(root, "rev-parse", "-q", "--verify", ref + "^{commit}").returncode != 0:
            continue
        mb = git(root, "merge-base", "HEAD", ref)
        if mb.returncode == 0 and mb.stdout.strip():
            return mb.stdout.strip(), ref
    return None, None


def _parse_name_status(blob: str, into: dict[str, str]) -> None:
    fields = blob.split("\0")
    i = 0
    while i < len(fields):
        status = fields[i]
        if not status:
            i += 1
            continue
        if status[0] in "RC" and i + 2 < len(fields):
            into[fields[i + 2]] = status[0]
            i += 3
            continue
        if i + 1 < len(fields):
            into[fields[i + 1]] = status[0]
        i += 2


def changed_files(root: Path) -> tuple[dict[str, str], str | None, str | None]:
    """{ruta: estado} de lo que cambia frente a la base y en el arbol; mas (base, referencia)."""
    changed: dict[str, str] = {}
    head = head_commit(root)
    base, ref = base_commit(root) if head else (None, None)
    if head and base and base != head:
        res = git(root, "diff", "--name-status", "-z", base, head)
        if res.returncode == 0:
            _parse_name_status(res.stdout, changed)
    if head:
        res = git(root, "diff", "--name-status", "-z", "HEAD")
        if res.returncode == 0:
            _parse_name_status(res.stdout, changed)
    else:
        res = git(root, "ls-files", "-z")
        for p in res.stdout.split("\0"):
            if p:
                changed[p] = "A"
    res = git(root, "ls-files", "-z", "--others", "--exclude-standard")
    for p in res.stdout.split("\0"):
        if p:
            changed[p] = "?"
    return changed, base, ref


def file_bytes(root: Path, rel: str, base: str | None) -> bytes | None:
    """Contenido del arbol de trabajo; si el fichero se borro, el de HEAD o el de la base."""
    path = root / rel
    if path.is_file():
        try:
            with path.open("rb") as fh:
                return fh.read(MAX_BYTES + 1)
        except OSError:
            return None
    data = git_bytes(root, "show", f"HEAD:{rel}")
    if data is None and base:
        data = git_bytes(root, "show", f"{base}:{rel}")
    return data


def text_of(data: bytes | None) -> str | None:
    if data is None or len(data) > MAX_BYTES or b"\0" in data[:8000]:
        return None
    return data.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# configuracion
# --------------------------------------------------------------------------- #
def load_config(root: Path) -> tuple[dict, list[str]]:
    """Devuelve (config normalizada, fallos). Sin fichero: config vacia."""
    path = root / CONFIG_PATH
    cfg = {"incluir": [], "excluir": []}
    if not path.is_file():
        return cfg, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return cfg, [f"{CONFIG_PATH} ilegible: {exc}"]
    fails: list[str] = []
    if not isinstance(data, dict):
        return cfg, [f"{CONFIG_PATH} debe contener un objeto JSON"]
    for item in data.get("incluir") or []:
        if isinstance(item, str) and item.strip():
            cfg["incluir"].append(item.strip())
        else:
            fails.append(f"{CONFIG_PATH}: entrada de `incluir` invalida: {item!r}")
    for item in data.get("excluir") or []:
        if not isinstance(item, dict) or not isinstance(item.get("glob"), str):
            fails.append(
                f'{CONFIG_PATH}: cada exclusion es un objeto {{"glob", "motivo"}}: {item!r}'
            )
            continue
        motivo = item.get("motivo")
        if not isinstance(motivo, str) or len(motivo.strip()) < 15:
            fails.append(
                f"{CONFIG_PATH}: la exclusion de `{item['glob']}` no lleva motivo (15 caracteres como "
                "minimo). Excluir una ruta es relajar la puerta: se escribe el porque y lo pide el usuario"
            )
            continue
        cfg["excluir"].append({"glob": item["glob"].strip(), "motivo": motivo.strip()})
    return cfg, fails


# --------------------------------------------------------------------------- #
# clasificacion
# --------------------------------------------------------------------------- #
def skipped_by_default(rel: str) -> bool:
    return (
        rel.startswith(SKIP_PREFIXES)
        or rel.lower().endswith(DOC_SUFFIXES)
        or bool(TEST_RE.search(rel))
    )


def why_data(rel: str, text: str | None) -> str | None:
    """Motivo por el que `rel` es capa de datos, o None."""
    if PATH_RE.search(rel):
        return "ruta de la capa de datos"
    if text is None:
        return None
    m = DDL_RE.search(text)
    if m:
        return f"DDL: {' '.join(m.group(0).split())}"
    m = ORM_RE.search(text)
    if m:
        return f"marcador de ORM o almacen: {m.group(0).strip()[:40]}"
    return None


def data_files(
    root: Path,
    changed: dict[str, str],
    base: str | None,
    cfg: dict,
) -> tuple[dict[str, str], list[str]]:
    """({ruta de datos: motivo}, [rutas excluidas por configuracion])."""
    include = [glob_regex(g) for g in cfg["incluir"]]
    exclude = [(glob_regex(e["glob"]), e) for e in cfg["excluir"]]
    found: dict[str, str] = {}
    excluded: list[str] = []
    for rel in sorted(changed):
        reason = None
        if any(rx.match(rel) for rx in include):
            reason = f"declarado en {CONFIG_PATH} (incluir)"
        elif not skipped_by_default(rel):
            reason = why_data(rel, text_of(file_bytes(root, rel, base)))
        if reason is None:
            continue
        hit = next((e for rx, e in exclude if rx.match(rel)), None)
        if hit is not None:
            excluded.append(f"{rel} (excluido por {CONFIG_PATH}: {hit['motivo']})")
            continue
        found[rel] = reason
    return found, excluded


# --------------------------------------------------------------------------- #
# ADR de datos
# --------------------------------------------------------------------------- #
def parse_adr(text: str) -> dict:
    """{'tipo', 'estado', 'sections': {nombre normalizado: cuerpo}, 'order': [nombres]}."""
    header: dict[str, str] = {}
    sections: dict[str, str] = {}
    order: list[str] = []
    current: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        m = SECTION_RE.match(line)
        if m:
            if current is not None:
                sections[current] = "\n".join(body)
            current = norm(m.group(1))
            order.append(current)
            body = []
            continue
        if current is None:
            h = HEADER_FIELD_RE.match(line)
            if h:
                header[norm(h.group(1))] = h.group(2).strip().strip("*").strip()
            continue
        body.append(line)
    if current is not None:
        sections[current] = "\n".join(body)
    return {
        "tipo": header.get("tipo"),
        "estado": header.get("estado"),
        "sections": sections,
        "order": order,
    }


def is_data_adr(parsed: dict) -> bool:
    return "datos" in norm(parsed.get("tipo") or "")


def alcance_patterns(body: str) -> list[str]:
    pats: list[str] = []
    for line in COMMENT_RE.sub("", body).splitlines():
        m = BULLET_RE.match(line)
        if not m:
            continue
        item = m.group(1).strip()
        code = CODE_RE.search(item)
        pat = code.group(1) if code else (item.split() or [""])[0]
        pat = pat.strip()
        if pat and pat != "ruta/al/fichero":
            pats.append(pat)
    return pats


def adr_issues(parsed: dict) -> list[str]:
    """Defectos de forma de un ADR de datos: secciones ausentes, vacias, de plantilla o sin cifras."""
    issues: list[str] = []
    estado = norm(parsed.get("estado") or "")
    if not estado:
        issues.append("sin `Estado:` en la cabecera")
    elif "plantilla" in estado:
        issues.append("`Estado: plantilla`: es una copia sin rellenar")
    for name in REQUIRED_SECTIONS:
        key = norm(name)
        if key not in parsed["sections"]:
            issues.append(f"falta la seccion `## {name}`")
            continue
        raw = parsed["sections"][key]
        text = COMMENT_RE.sub("", raw)
        if key == "alcance":
            if not alcance_patterns(raw):
                issues.append(
                    "`## Alcance` sin rutas: lista cada fichero de datos cubierto, uno por linea, "
                    "entre acentos graves"
                )
            continue
        lines = [
            ln for ln in text.splitlines() if ln.strip() and not TABLE_RULE_RE.match(ln)
        ]
        chars = sum(len(ln.strip()) for ln in lines)
        if chars < MIN_CHARS:
            issues.append(
                f"`## {name}` tiene {chars} caracteres escritos (minimo {MIN_CHARS}): "
                "una revision no cabe en una frase; responde a las preguntas de la plantilla"
            )
        m = PLACEHOLDER_RE.search(text)
        if m:
            issues.append(
                f"`## {name}` conserva un marcador sin resolver: {m.group(0)!r}"
            )
        if key == "escalabilidad" and not re.search(r"\d", text):
            issues.append(
                "`## Escalabilidad` sin ninguna cifra: volumen actual y proyectado, tamanos, "
                "lecturas y escrituras por segundo son numeros, no adjetivos"
            )
    return issues


def adr_candidates(root: Path) -> list[str]:
    adr_dir = root / ADR_DIR
    if not adr_dir.is_dir():
        return []
    return sorted(
        p.relative_to(root).as_posix()
        for p in adr_dir.glob("*.md")
        if p.is_file() and not p.name.startswith(TEMPLATE_PREFIX)
    )


# --------------------------------------------------------------------------- #
# puerta
# --------------------------------------------------------------------------- #
def check(root: Path) -> tuple[list[str], list[str], dict]:
    """Devuelve (fallos, avisos, detalle)."""
    fails: list[str] = []
    warns: list[str] = []
    cfg, cfg_fails = load_config(root)
    fails += cfg_fails
    changed, base, ref = changed_files(root)
    files, excluded = data_files(root, changed, base, cfg)
    warns.extend(excluded)
    detail = {
        "base": base,
        "base_ref": ref,
        "changed": len(changed),
        "data_files": files,
        "excluded": excluded,
        "adrs": {},
    }
    if not files:
        return fails, warns, detail

    all_data_adrs: dict[str, dict] = {}
    for rel in adr_candidates(root):
        try:
            parsed = parse_adr((root / rel).read_text(encoding="utf-8"))
        except OSError:
            continue
        if is_data_adr(parsed):
            all_data_adrs[rel] = parsed
    changed_adrs = {rel: p for rel, p in all_data_adrs.items() if rel in changed}

    coverage: dict[str, list[tuple[str, re.Pattern]]] = {}
    for rel, parsed in all_data_adrs.items():
        coverage[rel] = [
            (pat, glob_regex(pat))
            for pat in alcance_patterns(parsed["sections"].get("alcance", ""))
        ]
        detail["adrs"][rel] = {
            "en_el_diff": rel in changed,
            "alcance": [pat for pat, _ in coverage[rel]],
        }

    for rel, parsed in changed_adrs.items():
        for issue in adr_issues(parsed):
            fails.append(f"{rel}: {issue}")

    for path, reason in files.items():
        covering = [
            a for a in changed_adrs if any(rx.match(path) for _, rx in coverage[a])
        ]
        if covering:
            detail["data_files"][path] = f"{reason}; cubierto por {', '.join(covering)}"
            continue
        stale = [
            a
            for a in all_data_adrs
            if a not in changed_adrs and any(rx.match(path) for _, rx in coverage[a])
        ]
        if stale:
            fails.append(
                f"{path} ({reason}) solo lo cubre {', '.join(stale)}, que no cambia en este diff: "
                "cada modificacion de la capa de datos lleva su propia revision. Escribe un ADR de "
                "datos nuevo para este cambio (un ADR aceptado no se edita)"
            )
        else:
            fails.append(
                f"{path} ({reason}) cambia sin revision de arquitectura de datos: ningun ADR "
                f"`Tipo: datos` de este diff lo nombra en `## Alcance`"
            )

    for rel in changed_adrs:
        if not any(rx.match(p) for p in files for _, rx in coverage[rel]):
            warns.append(
                f"{rel} es un ADR de datos de este diff pero su `## Alcance` no nombra ningun fichero "
                "de datos cambiado"
            )
    return fails, warns, detail


def main(argv: list[str]) -> int:
    root = Path(
        os.environ.get("GAUNTLET_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or "."
    ).resolve()
    if git(root, "rev-parse", "--is-inside-work-tree").returncode != 0:
        print(f"[datos] {root} no es un repositorio git")
        return 1
    fails, warns, detail = check(root)
    if "--json" in argv:
        print(json.dumps(detail, indent=2, ensure_ascii=False))
    for w in warns:
        print(f"[datos] AVISO: {w}")
    for f in fails:
        print(f"[datos] {f}")
    if fails:
        print(
            f"\n[datos] {len(fails)} problema(s): una modificacion de la capa de datos sin su revision "
            "de arquitectura escrita no esta terminada. Plantilla: docs/adr/0000-plantilla-datos.md"
        )
        return 1
    files = detail["data_files"]
    if not files:
        where = f" frente a {detail['base_ref']}" if detail["base_ref"] else ""
        print(
            f"[datos] OK: sin cambios en la capa de datos ({detail['changed']} fichero(s) "
            f"cambiados revisados{where})."
        )
        return 0
    adrs = sorted({a for a in detail["adrs"] if detail["adrs"][a]["en_el_diff"]})
    print(
        f"[datos] OK: {len(files)} fichero(s) de la capa de datos con su revision de arquitectura "
        f"en {', '.join(adrs)}:"
    )
    for path, reason in files.items():
        print(f"[datos]   - {path}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
