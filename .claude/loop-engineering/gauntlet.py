#!/usr/bin/env python3
"""Runner del Gauntlet Loop (loop-engineering, agnostico al proyecto).

Ejecuta, en orden, las puertas (gates) declaradas en `.claude/gauntlet.json`
y emite un veredicto binario y reproducible: VERDE o ROJO.

Velocidad sin perder calidad (ADR 0012):
  - `inputs` (+ `cache_key`): una puerta que ya paso con exactamente las mismas entradas, el mismo
    comando y las mismas versiones sale `CACHED` en vez de volver a ejecutarse. La huella se calcula
    en cada pasada sobre el arbol de trabajo; sin `inputs`, la puerta se ejecuta siempre.
  - `group`: puertas consecutivas con el mismo grupo se ejecutan en paralelo; el veredicto, el orden
    del informe y el aborto temprano (tras el grupo) no cambian.

Codigos de salida:
  0  VERDE (ninguna puerta bloqueante ha fallado)
  1  ROJO  (al menos una puerta bloqueante ha fallado o ha agotado el tiempo)
  2  Error de configuracion (manifiesto ausente, invalido o argumentos malos)

Uso habitual (desde cualquier subdirectorio del repositorio):
  bin/gauntlet                 # perfil full: la pasada que cierra una tarea
  bin/gauntlet -p fast         # perfil rapido: lo que exige el pre-commit
  bin/gauntlet -g lint         # una sola puerta (parcial: no cierra nada)
  bin/gauntlet --no-cache      # ignora la cache: ejecuta todas las puertas

  equivalente sin envoltorio: python3 .claude/loop-engineering/gauntlet.py ...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
DISABLED = "DISABLED"
TIMEOUT = "TIMEOUT"
CACHED = "CACHED"

BAD_STATES = (FAIL, TIMEOUT)

GATE_KEYS_REQUIRED = ("id", "title", "command")
GATE_KEYS_OPTIONAL = (
    "when",
    "when_description",
    "blocking",
    "profiles",
    "timeout_seconds",
    "enabled",
    "disabled_reason",
    "notes",
    "fix_hint",
    "inputs",
    "cache_key",
    "group",
)

HISTORY_LIMIT = 20
STALL_THRESHOLD = 3  # ejecuciones consecutivas fallando en la misma puerta

# Cache por huella de entradas. CACHE_SCHEMA entra en la huella: cambiar como se calcula invalida todo.
CACHE_SCHEMA = 1
CACHE_KEEP = 5  # huellas en verde recordadas por puerta (volver a un estado anterior tambien acierta)
# Un fichero modificado hace menos de esto no se memoriza por (tamano, fechas, inodo): con fechas de
# granularidad gruesa, dos escrituras seguidas podrian compartirlas. Se rehashea siempre (como git).
RACY_SECONDS = 3.0


# --------------------------------------------------------------------------- #
# utilidades
# --------------------------------------------------------------------------- #
def color_enabled(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("GAUNTLET_COLOR") == "always":
        return True
    return hasattr(stream, "isatty") and stream.isatty()


class Paint:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def green(self, t: str) -> str:
        return self._wrap("32", t)

    def red(self, t: str) -> str:
        return self._wrap("31", t)

    def yellow(self, t: str) -> str:
        return self._wrap("33", t)

    def dim(self, t: str) -> str:
        return self._wrap("2", t)

    def bold(self, t: str) -> str:
        return self._wrap("1", t)


def repo_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parent,
        )
        return Path(out.stdout.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        # .claude/loop-engineering/gauntlet.py -> 2 niveles hasta la raiz
        return Path(__file__).resolve().parents[2]


def die(message: str) -> None:
    print(f"gauntlet: error de configuracion: {message}", file=sys.stderr)
    raise SystemExit(2)


def load_manifest(path: Path) -> dict:
    if not path.is_file():
        die(f"no existe el manifiesto {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"{path} no es JSON valido: {exc}")
    if not isinstance(data, dict):
        die(f"{path} debe contener un objeto JSON")
    if data.get("version") != 1:
        die(
            f"version de manifiesto no soportada: {data.get('version')!r} (se espera 1)"
        )
    gates = data.get("gates")
    if not isinstance(gates, list) or not gates:
        die("el manifiesto no declara ninguna puerta en 'gates'")

    seen: set[str] = set()
    for index, gate in enumerate(gates):
        if not isinstance(gate, dict):
            die(f"gates[{index}] no es un objeto")
        for key in GATE_KEYS_REQUIRED:
            if not gate.get(key) or not isinstance(gate[key], str):
                die(f"gates[{index}] necesita la clave de texto '{key}'")
        unknown = set(gate) - set(GATE_KEYS_REQUIRED) - set(GATE_KEYS_OPTIONAL)
        if unknown:
            die(f"gate '{gate['id']}' tiene claves desconocidas: {sorted(unknown)}")
        if gate["id"] in seen:
            die(f"id de puerta duplicado: '{gate['id']}'")
        seen.add(gate["id"])
        profiles = gate.get("profiles", [])
        if not isinstance(profiles, list) or not all(
            isinstance(p, str) for p in profiles
        ):
            die(f"gate '{gate['id']}': 'profiles' debe ser una lista de textos")
        inputs = gate.get("inputs")
        if inputs is not None and (
            not isinstance(inputs, list)
            or not inputs
            or not all(isinstance(i, str) and i.strip() for i in inputs)
        ):
            die(
                f"gate '{gate['id']}': 'inputs' debe ser una lista no vacia de pathspecs de git"
            )
        if "cache_key" in gate:
            if not isinstance(gate["cache_key"], str) or not gate["cache_key"].strip():
                die(f"gate '{gate['id']}': 'cache_key' debe ser un comando de texto")
            if inputs is None:
                die(
                    f"gate '{gate['id']}': 'cache_key' sin 'inputs' no tiene efecto; declara las entradas"
                )
        if "group" in gate and (
            not isinstance(gate["group"], str) or not gate["group"].strip()
        ):
            die(f"gate '{gate['id']}': 'group' debe ser un texto no vacio")
    return data


def select_gates(manifest: dict, profile: str, only: list[str]) -> list[dict]:
    gates = manifest["gates"]
    if only:
        by_id = {g["id"]: g for g in gates}
        missing = [gid for gid in only if gid not in by_id]
        if missing:
            die(
                f"puertas inexistentes: {', '.join(missing)}. Disponibles: {', '.join(by_id)}"
            )
        return [by_id[gid] for gid in only]
    selected = [g for g in gates if profile in g.get("profiles", [])]
    if not selected:
        known = sorted({p for g in gates for p in g.get("profiles", [])})
        die(
            f"el perfil '{profile}' no selecciona ninguna puerta. Perfiles: {', '.join(known)}"
        )
    return selected


# --------------------------------------------------------------------------- #
# ejecucion
# --------------------------------------------------------------------------- #
def run_shell(
    command: str, cwd: Path, timeout: int, log_path: Path | None, stream: bool
):
    """Ejecuta `command` con bash. Devuelve (exit_code, timed_out, output)."""
    proc = subprocess.Popen(
        ["bash", "-c", command],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    timed_out = threading.Event()

    def kill_tree() -> None:
        timed_out.set()
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    watchdog = threading.Timer(timeout, kill_tree)
    watchdog.start()

    chunks: list[str] = []
    handle = log_path.open("w", encoding="utf-8") if log_path else None
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            chunks.append(line)
            if handle:
                handle.write(line)
            if stream:
                sys.stdout.write(line)
        proc.wait()
    finally:
        watchdog.cancel()
        if handle:
            handle.close()
    return proc.returncode, timed_out.is_set(), "".join(chunks)


def evaluate_when(gate: dict, cwd: Path) -> bool:
    condition = gate.get("when")
    if not condition:
        return True
    code, _, _ = run_shell(condition, cwd, timeout=120, log_path=None, stream=False)
    return code == 0


def tail(text: str, lines: int) -> str:
    rows = text.rstrip("\n").splitlines()
    return "\n".join(rows[-lines:]) if rows else "(sin salida)"


# --------------------------------------------------------------------------- #
# historial
# --------------------------------------------------------------------------- #
def load_history(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def stalled_gates(history: list[dict], failing: list[str]) -> list[str]:
    """Puertas que fallan en las ultimas STALL_THRESHOLD ejecuciones consecutivas."""
    if not failing:
        return []
    recent = history[-(STALL_THRESHOLD - 1) :]
    if len(recent) < STALL_THRESHOLD - 1:
        return []
    stalled = []
    for gid in failing:
        if all(gid in entry.get("failing", []) for entry in recent):
            stalled.append(gid)
    return stalled


# --------------------------------------------------------------------------- #
# cache por huella de entradas
# --------------------------------------------------------------------------- #
def load_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default
    return data if isinstance(data, type(default)) else default


class Fingerprinter:
    """Calcula la huella de las entradas de una puerta sobre el arbol de trabajo actual.

    La huella cubre: version del esquema, `command`, `when`, `inputs`, la salida de `cache_key` y, por
    cada fichero que casan los `inputs` (seguidos y sin seguimiento no ignorados, via `git ls-files`),
    su ruta, su bit de ejecucion y el sha256 de su contenido. Un fichero borrado, nuevo o renombrado
    cambia la huella. Para no releer cada vez un arbol grande, el sha de un fichero se memoriza por
    (tamano, mtime, ctime, inodo), salvo si es reciente (RACY_SECONDS).
    """

    def __init__(self, root: Path, memo: dict) -> None:
        self.root = root
        self.memo = memo
        self.lock = threading.Lock()

    def file_digest(self, rel: str) -> str:
        path = self.root / rel
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            return "borrado"
        if os.path.islink(path):
            return "enlace:" + os.readlink(path)
        if not os.path.isfile(path):
            return "no-fichero"
        stamp = [st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino]
        with self.lock:
            known = self.memo.get(rel)
        if known and known[:4] == stamp:
            sha = known[4]
        else:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
            sha = digest.hexdigest()
            if time.time() - st.st_mtime > RACY_SECONDS:
                with self.lock:
                    self.memo[rel] = [*stamp, sha]
        executable = "x" if st.st_mode & 0o111 else "-"
        return f"{executable}{sha}"

    def compute(self, gate: dict) -> tuple[str | None, str]:
        """Devuelve (huella, motivo). Huella None = esta puerta no se cachea en esta pasada."""
        inputs = gate.get("inputs")
        if not inputs:
            return None, "sin inputs declarados"
        try:
            listing = subprocess.run(
                [
                    "git",
                    "ls-files",
                    "-z",
                    "-c",
                    "-o",
                    "--exclude-standard",
                    "--",
                    *inputs,
                ],
                cwd=str(self.root),
                capture_output=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None, "git ls-files no disponible: sin cache"
        files = sorted(
            {
                f
                for f in listing.stdout.decode("utf-8", "surrogateescape").split("\0")
                if f
            }
        )
        if not files:
            # Unos inputs que no casan nada son casi siempre una errata: cachear con ellos daria un
            # CACHED permanente aunque la puerta lea otros ficheros. Se ejecuta y se avisa.
            return None, "los inputs no casan ningun fichero (errata?): sin cache"
        key_output = ""
        if gate.get("cache_key"):
            code, timed_out, output = run_shell(
                gate["cache_key"], self.root, timeout=120, log_path=None, stream=False
            )
            if code != 0 or timed_out:
                return None, "cache_key fallo: sin cache"
            key_output = output
        digest = hashlib.sha256()
        header = {
            "schema": CACHE_SCHEMA,
            "command": gate["command"],
            "when": gate.get("when"),
            "inputs": inputs,
            "cache_key": key_output,
        }
        digest.update(json.dumps(header, sort_keys=True).encode("utf-8"))
        for rel in files:
            digest.update(
                f"\0{rel}\0{self.file_digest(rel)}".encode("utf-8", "surrogateescape")
            )
        return digest.hexdigest(), f"{len(files)} fichero(s)"


def cache_hit(cache: dict, gid: str, fingerprint: str | None) -> dict | None:
    if not fingerprint:
        return None
    for entry in cache.get("gates", {}).get(gid, []):
        if entry.get("fingerprint") == fingerprint:
            return entry
    return None


def cache_store(cache: dict, gid: str, fingerprint: str, duration: float) -> None:
    entries = [
        e
        for e in cache.setdefault("gates", {}).get(gid, [])
        if e.get("fingerprint") != fingerprint
    ]
    entries.insert(
        0,
        {
            "fingerprint": fingerprint,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "duration": round(duration, 2),
        },
    )
    cache["gates"][gid] = entries[:CACHE_KEEP]


def batches(gates: list[dict]) -> list[list[dict]]:
    """Agrupa puertas consecutivas con el mismo `group`; el resto va sola, en su orden."""
    out: list[list[dict]] = []
    for gate in gates:
        group = gate.get("group")
        if group and out and out[-1][0].get("group") == group:
            out[-1].append(gate)
        else:
            out.append([gate])
    return out


def mean_durations(history: list[dict]) -> dict[str, float]:
    sums: dict[str, list[float]] = {}
    for entry in history:
        for gid, secs in (entry.get("durations") or {}).items():
            if isinstance(secs, (int, float)):
                sums.setdefault(gid, []).append(float(secs))
    return {gid: sum(v) / len(v) for gid, v in sums.items()}


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="gauntlet",
        description="Ejecuta el Gauntlet Loop declarado en .claude/gauntlet.json",
    )
    parser.add_argument(
        "-p",
        "--profile",
        default=os.environ.get("GAUNTLET_PROFILE", "full"),
        help="perfil de puertas a ejecutar (por defecto: full)",
    )
    parser.add_argument(
        "-g",
        "--gate",
        action="append",
        default=[],
        metavar="ID",
        help="ejecuta solo esta puerta (repetible); ignora el perfil",
    )
    parser.add_argument("--list", action="store_true", help="lista las puertas y sale")
    parser.add_argument(
        "--json", action="store_true", help="imprime el resumen en JSON"
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="vuelca la salida de cada puerta en vivo (implica --serial)",
    )
    parser.add_argument(
        "--no-bail",
        action="store_true",
        help="sigue ejecutando puertas tras el primer fallo bloqueante",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        default=os.environ.get("GAUNTLET_NO_CACHE") == "1",
        help="ejecuta todas las puertas aunque su huella de entradas ya este en verde",
    )
    parser.add_argument(
        "--serial",
        action="store_true",
        default=os.environ.get("GAUNTLET_SERIAL") == "1",
        help="ignora los grupos paralelos y ejecuta las puertas de una en una",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=int(os.environ.get("GAUNTLET_JOBS") or 0) or (os.cpu_count() or 2),
        help="maximo de puertas simultaneas dentro de un grupo (por defecto: CPUs)",
    )
    parser.add_argument(
        "--tail", type=int, default=40, help="lineas de log a mostrar al fallar"
    )
    parser.add_argument(
        "--manifest",
        default=os.environ.get("GAUNTLET_MANIFEST"),
        help="ruta del manifiesto",
    )
    parser.add_argument(
        "--root", default=os.environ.get("GAUNTLET_ROOT"), help="raiz del repositorio"
    )
    args = parser.parse_args(argv)
    if args.jobs < 1:
        die("--jobs debe ser 1 o mas")

    root = repo_root(args.root)
    manifest_path = (
        Path(args.manifest).resolve()
        if args.manifest
        else root / ".claude" / "gauntlet.json"
    )
    manifest = load_manifest(manifest_path)
    defaults = manifest.get("defaults", {})
    default_timeout = int(defaults.get("timeout_seconds", 900))

    paint = Paint(color_enabled(sys.stdout))

    work_dir = root / ".claude" / ".gauntlet"
    history_path = work_dir / "history.json"
    history = load_history(history_path)

    if args.list:
        means = mean_durations(history)
        print(paint.bold(f"Puertas declaradas en {manifest_path.relative_to(root)}:"))
        for gate in manifest["gates"]:
            flags = []
            if not gate.get("enabled", True):
                flags.append("desactivada")
            if not gate.get("blocking", True):
                flags.append("no bloqueante")
            if gate.get("inputs"):
                flags.append("cache por entradas")
            if gate.get("group"):
                flags.append(f"grupo {gate['group']}")
            if gate["id"] in means:
                flags.append(f"media {means[gate['id']]:.1f}s")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            profiles = ",".join(gate.get("profiles", [])) or "-"
            print(
                f"  {gate['id']:<18} perfiles={profiles:<10}{suffix}  {gate['title']}"
            )
            print(paint.dim(f"      $ {gate['command']}"))
        return 0

    gates = select_gates(manifest, args.profile, args.gate)

    logs_dir = work_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    cache_path = work_dir / "cache.json"
    cache = load_json(cache_path, {})
    if cache.get("schema") != CACHE_SCHEMA:
        cache = {"schema": CACHE_SCHEMA, "gates": {}, "files": {}}
    cache.setdefault("gates", {})
    fingerprinter = Fingerprinter(root, cache.setdefault("files", {}))
    cache_lock = threading.Lock()
    serial = args.serial or args.stream

    scope = f"puertas {', '.join(args.gate)}" if args.gate else f"perfil {args.profile}"
    print(paint.bold(f"== GAUNTLET LOOP == {scope} == {len(gates)} puertas =="))

    def skipped(gate: dict, state: str, reason: str) -> dict:
        return {
            "id": gate["id"],
            "title": gate["title"],
            "state": state,
            "reason": reason,
            "duration": 0.0,
            "exit_code": None,
            "blocking": gate.get("blocking", True),
        }

    def execute(gate: dict, emit) -> tuple[dict, str]:
        """Ejecuta una puerta completa (enabled, when, cache, comando). Devuelve (resultado, salida)."""
        gid = gate["id"]
        log_path = logs_dir / f"{gid.replace('/', '_').replace(':', '_')}.log"

        if not gate.get("enabled", True):
            reason = gate.get("disabled_reason", "desactivada en el manifiesto")
            emit(f"  {paint.yellow(DISABLED):<22} {gid} {paint.dim('- ' + reason)}")
            return skipped(gate, DISABLED, reason), ""

        if not evaluate_when(gate, root):
            reason = (
                gate.get("when_description")
                or f"condicion no cumplida: {gate.get('when')}"
            )
            emit(f"  {paint.dim(SKIP):<22} {gid} {paint.dim('- ' + reason)}")
            return skipped(gate, SKIP, reason), ""

        fingerprint, why = fingerprinter.compute(gate)
        if gate.get("inputs") and not fingerprint:
            emit(paint.yellow(f"  aviso: {gid}: {why}"))
        hit = None if args.no_cache else cache_hit(cache, gid, fingerprint)
        if hit:
            reason = (
                f"huella {fingerprint[:12]} en verde desde {hit.get('at')} "
                f"({why}; ahorra {hit.get('duration', 0):.1f}s)"
            )
            emit(f"  {paint.green(CACHED):<22} {gid} {paint.dim('- ' + reason)}")
            result = skipped(gate, CACHED, reason)
            result["fingerprint"] = fingerprint
            result["saved"] = hit.get("duration", 0.0)
            return result, ""

        shown = (
            gate["command"]
            if len(gate["command"]) <= 110
            else gate["command"][:107] + "..."
        )
        emit(f"  {paint.dim('RUN'):<22} {gid} {paint.dim('$ ' + shown)}")
        t0 = time.time()
        code, timed_out, output = run_shell(
            gate["command"],
            root,
            int(gate.get("timeout_seconds", default_timeout)),
            log_path,
            args.stream,
        )
        duration = time.time() - t0
        blocking = gate.get("blocking", True)

        if timed_out:
            state = TIMEOUT
        elif code == 0:
            state = PASS
        else:
            state = FAIL

        if state == PASS and fingerprint:
            # Solo se recuerda si las entradas no cambiaron mientras la puerta corria: si alguien
            # escribio a la vez, la puerta pudo ver una mezcla y su PASS no vale para ninguna huella.
            after, _ = fingerprinter.compute(gate)
            if after == fingerprint:
                with cache_lock:
                    cache_store(cache, gid, fingerprint, duration)
            else:
                emit(
                    paint.yellow(
                        f"  aviso: {gid}: sus entradas cambiaron durante la ejecucion; no se cachea"
                    )
                )

        label = {
            PASS: paint.green(PASS),
            FAIL: paint.red(FAIL),
            TIMEOUT: paint.red(TIMEOUT),
        }[state]
        emit(f"  {label:<22} {gid} {paint.dim(f'({duration:.1f}s, exit {code})')}")

        if state in BAD_STATES:
            emit(paint.dim(f"      log completo: {log_path.relative_to(root)}"))
            emit(tail(output, args.tail))
            if gate.get("fix_hint"):
                emit(paint.yellow(f"      pista: {gate['fix_hint']}"))

        result = {
            "id": gid,
            "title": gate["title"],
            "state": state,
            "reason": None,
            "duration": round(duration, 2),
            "exit_code": code,
            "blocking": blocking,
            "log": str(log_path.relative_to(root)),
        }
        if fingerprint:
            result["fingerprint"] = fingerprint
        return result, output

    results: list[dict] = []
    bailed = False
    started = time.time()

    for batch in batches(gates):
        if bailed:
            for gate in batch:
                results.append(
                    skipped(
                        gate, SKIP, "no ejecutada: se aborto tras un fallo bloqueante"
                    )
                )
            continue

        if serial or len(batch) == 1:
            for gate in batch:
                if bailed:
                    results.append(
                        skipped(
                            gate,
                            SKIP,
                            "no ejecutada: se aborto tras un fallo bloqueante",
                        )
                    )
                    continue
                result, _ = execute(gate, print)
                results.append(result)
                if (
                    result["state"] in BAD_STATES
                    and result["blocking"]
                    and not args.no_bail
                ):
                    bailed = True
            continue

        # Grupo paralelo: cada puerta escribe en su propio log y su salida se imprime al terminar
        # el grupo, en el orden del manifiesto. El aborto temprano actua tras el grupo entero.
        print(
            paint.dim(
                f"  -- grupo {batch[0]['group']} en paralelo: {', '.join(g['id'] for g in batch)}"
            )
        )
        buffers: list[list[str]] = [[] for _ in batch]
        with ThreadPoolExecutor(max_workers=min(args.jobs, len(batch))) as pool:
            futures = [
                pool.submit(execute, gate, buf.append)
                for gate, buf in zip(batch, buffers)
            ]
            batch_results = [f.result()[0] for f in futures]
        for buf in buffers:
            for line in buf:
                print(line)
        results.extend(batch_results)
        if not args.no_bail and any(
            r["state"] in BAD_STATES and r["blocking"] for r in batch_results
        ):
            bailed = True

    total = time.time() - started
    failing = [r["id"] for r in results if r["state"] in BAD_STATES and r["blocking"]]
    warnings = [
        r["id"] for r in results if r["state"] in BAD_STATES and not r["blocking"]
    ]
    passed = [r["id"] for r in results if r["state"] == PASS]
    cached = [r["id"] for r in results if r["state"] == CACHED]
    skipped_ids = [r["id"] for r in results if r["state"] in (SKIP, DISABLED)]
    saved = sum(float(r.get("saved") or 0.0) for r in results)
    green = not failing

    print()
    print(paint.bold("-- resumen --"))
    for r in results:
        mark = {
            PASS: paint.green("PASS"),
            CACHED: paint.green("CACHED"),
            FAIL: paint.red("FAIL"),
            TIMEOUT: paint.red("TIMEOUT"),
            SKIP: paint.dim("SKIP"),
            DISABLED: paint.yellow("DISABLED"),
        }[r["state"]]
        if r["state"] in BAD_STATES and not r["blocking"]:
            mark = paint.yellow("WARN")
        extra = r["reason"] or f"{r['duration']:.1f}s"
        print(f"  {mark:<22} {r['id']:<18} {paint.dim(extra)}")

    verdict = "VERDE" if green else "ROJO"
    line = (
        f"GAUNTLET: {paint.green(verdict) if green else paint.red(verdict)} -- "
        f"{len(passed)} PASS, {len(cached)} CACHED, {len(failing) + len(warnings)} FAIL, "
        f"{len(skipped_ids)} SKIP en {total:.1f}s ({scope})"
    )
    print()
    print(paint.bold(line))
    ran = sorted(
        (r for r in results if r["state"] in (PASS, *BAD_STATES)),
        key=lambda r: r["duration"],
        reverse=True,
    )
    if ran:
        slowest = ", ".join(f"{r['id']} {r['duration']:.1f}s" for r in ran[:3])
        print(paint.dim(f"  mas lentas: {slowest}"))
    if cached:
        print(
            paint.dim(
                f"  cache: {len(cached)} puerta(s) con la misma huella de entradas que un PASS anterior "
                f"(~{saved:.1f}s ahorrados). `--no-cache` las ejecuta todas."
            )
        )
    if failing:
        print(paint.red(f"  puertas bloqueantes en rojo: {', '.join(failing)}"))
        print(
            "  arregla la causa raiz y repite el gauntlet COMPLETO desde la primera puerta."
        )
    if warnings:
        print(paint.yellow(f"  avisos no bloqueantes: {', '.join(warnings)}"))
    if args.gate and green:
        print(
            paint.yellow(
                "  aviso: ejecucion parcial (-g). No cuenta como pasada limpia."
            )
        )

    stalled = stalled_gates(history, failing)
    if stalled:
        print(
            paint.red(
                f"  ESCALADO: {', '.join(stalled)} falla en {STALL_THRESHOLD} ejecuciones seguidas. "
                "Para el loop y consulta al usuario (ver SKILL.md, seccion Escalado)."
            )
        )

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": scope,
        "profile": None if args.gate else args.profile,
        "partial": bool(args.gate),
        "verdict": verdict,
        "failing": failing + warnings,
        "passed": passed,
        "cached": cached,
        "skipped": skipped_ids,
        "duration_seconds": round(total, 2),
        "saved_seconds": round(saved, 2),
        "durations": {
            r["id"]: r["duration"] for r in results if r["state"] in (PASS, *BAD_STATES)
        },
    }
    history.append(entry)
    history_path.write_text(
        json.dumps(history[-HISTORY_LIMIT:], indent=2) + "\n", encoding="utf-8"
    )
    summary = dict(entry, gates=results)
    (work_dir / "last-run.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    # La memoria de shas no crece sin limite: se olvidan los ficheros que ya no existen.
    cache["files"] = {
        rel: stamp for rel, stamp in cache["files"].items() if (root / rel).exists()
    }
    cache_path.write_text(json.dumps(cache) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(summary, indent=2))

    return 0 if green else 1


if __name__ == "__main__":
    # `gauntlet.py --list | head` no debe morir con BrokenPipeError: dejamos que SIGPIPE
    # tenga su comportamiento por defecto cuando la plataforma lo soporta.
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\ngauntlet: interrumpido", file=sys.stderr)
        raise SystemExit(130)
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        raise SystemExit(0)
