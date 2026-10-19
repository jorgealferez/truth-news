"""La 'chicha' de un tema: origen, quien repite el mismo texto, que falla y que falta.

Todo sale de los articulos del tema y de la sintesis guardada; no llama a la IA. Si la pieza trae
`claves` (prompt nuevo) se usan; si no (piezas anteriores), se derivan de lo que hay.
"""

from __future__ import annotations

from collections import Counter

from truthnews.web.seo import slugify

SAME_TEXT = 0.6  # Jaccard de palabras de titular + extracto a partir del cual es "el mismo texto"
MIN_GROUP = 3  # por debajo, coincidir dos medios no merece agruparlos
SCOPES = ("national", "regional", "local", "international")


def _tokens(a) -> set[str]:
    words = slugify(f"{a.title} {(a.summary or '')[:300]}", max_len=10_000).split("-")
    return {w for w in words if len(w) > 3}


def same_text_groups(arts: list) -> list[list]:
    """Grupos de articulos (de medios distintos) que publican practicamente el mismo texto."""
    toks = [_tokens(a) for a in arts]
    parent = list(range(len(arts)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(arts)):
        for j in range(i + 1, len(arts)):
            if arts[i].outlet_id == arts[j].outlet_id or not toks[i] or not toks[j]:
                continue
            same_title = slugify(arts[i].title) == slugify(arts[j].title)
            if same_title or len(toks[i] & toks[j]) / len(toks[i] | toks[j]) >= SAME_TEXT:
                parent[find(i)] = find(j)
    buckets: dict[int, list] = {}
    for i, a in enumerate(arts):
        buckets.setdefault(find(i), []).append(a)
    groups = [g for g in buckets.values() if len({a.outlet_id for a in g}) >= MIN_GROUP]
    groups.sort(key=lambda g: -len({a.outlet_id for a in g}))
    return [sorted(g, key=lambda a: a.published_at) for g in groups]


def build(arts: list, synth: dict, outlets: dict, verdicts: dict) -> dict:
    """Modelo de la pagina de tema. `arts` en orden de publicacion; `outlets` por slug."""
    groups = same_text_groups(arts)
    arts_by_outlet: dict[int, set[int]] = {}
    for a in arts:
        arts_by_outlet.setdefault(a.outlet_id, set()).add(a.id)
    group_of: dict[int, int] = {}
    group_view = []
    for gi, g in enumerate(groups):
        ids = {a.id for a in g}
        members, seen = [], set()
        for a in g:
            if a.outlet_id in seen:
                continue
            seen.add(a.outlet_id)
            group_of.setdefault(a.outlet_id, gi)
            members.append({"outlet": a.outlet, "adds": bool(arts_by_outlet[a.outlet_id] - ids)})
        group_view.append({"first": g[0], "members": members, "n": len(members)})

    entries = synth.get("que_dice_cada_medio", [])
    first_entry: dict[int, dict] = {}
    own, copied = [], []
    for m in entries:
        out = outlets.get(m.get("medio_slug"))
        row = {**m, "outlet": out}
        gi = group_of.get(out.id) if out else None
        if gi is None:
            own.append(row)
            continue
        first_entry.setdefault(gi, row)
        member = next(x for x in group_view[gi]["members"] if x["outlet"].id == out.id)
        if member["adds"]:
            own.append({**row, "also_in_group": gi})  # copia el texto comun y ademas aporta algo propio
        else:
            copied.append(row)
    for gi, g in enumerate(group_view):
        g["summary"] = first_entry.get(gi)

    n_outlets = len(arts_by_outlet)
    n_copy_only = sum(1 for g in group_view for m in g["members"] if not m["adds"])
    scopes = Counter(a.outlet.scope for a in {a.outlet_id: a for a in arts}.values())

    first, last = (arts[0], arts[-1]) if arts else (None, None)
    total = (last.published_at - first.published_at).total_seconds() if arts else 0
    dots, seen_o = [], set()
    for a in arts:
        if a.outlet_id in seen_o:
            continue
        seen_o.add(a.outlet_id)
        pos = round(100 * (a.published_at - first.published_at).total_seconds() / total) if total else 0
        dots.append({"name": a.outlet.name, "pos": pos, "copy": a.outlet_id in group_of})

    claves = synth.get("claves") or {}
    v = synth.get("valoracion") or {}
    n_verdicts = sum(sum(c.values()) for c in verdicts.values())
    flags = []
    if group_view and group_view[0]["n"] * 2 > n_outlets:
        flags.append(("one_source", {"n": group_view[0]["n"], "total": n_outlets}))
    if not synth.get("datos"):
        flags.append(("no_official_data", {}))
    if not n_verdicts:
        flags.append(("no_verified_claims", {}))

    return {
        "groups": group_view,
        "own": own,
        "copied": copied,
        "n_outlets": n_outlets,
        "n_copy_only": n_copy_only,
        "n_own": n_outlets - n_copy_only,
        "scopes": [(s, scopes[s], round(100 * scopes[s] / n_outlets)) for s in SCOPES if scopes.get(s)]
        if n_outlets
        else [],
        "first": first,
        "hours": round(total / 3600),
        "dots": dots,
        "one_liner": claves.get("en_una_frase"),
        "origin_text": claves.get("origen"),
        "fails": claves.get("que_falla") or [d.get("aspecto") for d in synth.get("diferencias", [])],
        "fails_detailed": bool(claves.get("que_falla")),
        "missing": claves.get("que_falta") or v.get("lo_que_no_sabemos") or [],
        "flags": flags,
        "confidence": v.get("confianza"),
        "conclusion": v.get("conclusion"),
        "n_differences": len(synth.get("diferencias", [])),
        "n_verdicts": n_verdicts,
    }
