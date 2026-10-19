"""Integridad de los datos de disputas etiquetados (ADR 0016; base de medida del ADR 0053)."""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_labeled_dispute_sets_are_disjoint_and_complete():
    design = _load("disputes.json")["historias"]
    production = _load("disputes_produccion.json")["historias"]
    validation = _load("disputes_validacion.json")
    sets = [{h["historia"] for h in s} for s in (design, production, validation["historias"])]
    assert sum(map(len, sets)) == len(set().union(*sets)), "una historia no puede estar en dos conjuntos"
    # Cada muestra de validacion dice como se eligio, cuando y si se uso despues para ajustar.
    ids = [i for m in validation["muestras"] for i in m["historias"]]
    assert sorted(ids) == sorted(sets[2]) and len(ids) == len(set(ids))
    assert all(m["seleccion"] and m["tomada"] and m["uso"] for m in validation["muestras"])
    for story in production + validation["historias"]:
        for a in story["articulos"]:
            assert a["url"].startswith("http") and a["fuente"].startswith("https://nosmienten.com/")
            assert a["published_at"] and a["outlet"]
        for by_outlet in story["hechos"].values():
            assert all(fact for values in by_outlet.values() for fact in values.values())
