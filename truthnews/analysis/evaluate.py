"""Medida de la calidad de las disputas de cifras sobre historias reales etiquetadas (ADR 0016).

Fixture: `tests/fixtures/disputes.json`. Cada historia trae sus articulos (titular y resumen) y, en
`hechos`, de que hecho habla cada cifra: {sustantivo: {medio: {cifra: hecho}}}. Una disputa es correcta
si todas sus cifras hablan del mismo hecho; una cifra sin etiqueta cuenta como error.
"""

from __future__ import annotations

from datetime import datetime
from itertools import combinations
from types import SimpleNamespace

from truthnews.analysis.compare import compare


def _articles(story: dict) -> list:
    return [
        SimpleNamespace(
            outlet=SimpleNamespace(name=a["outlet"]),
            title=a["title"],
            summary=a["summary"],
            content_text=None,
            published_at=datetime.fromisoformat(a["published_at"]),
            language="es",
        )
        for a in story["articulos"]
    ]


def _fact(facts: dict, noun: str, outlet: str, value: float) -> str | None:
    return facts.get(noun, {}).get(outlet, {}).get(f"{value:.0f}" if value.is_integer() else f"{value:g}")


def expected_disputes(story: dict) -> set[str]:
    """Sustantivos con un mismo hecho contado con cifras distintas (> 10 %) por al menos dos medios."""
    out = set()
    for noun, by_outlet in story["hechos"].items():
        by_fact: dict[str, list[float]] = {}
        for values in by_outlet.values():
            for value, fact in values.items():
                by_fact.setdefault(fact, []).append(float(value))
        if any(len(v) >= 2 and max(v) > 1.1 * min(v) for v in by_fact.values()):
            out.add(noun)
    return out


def dispute_quality(fixture: dict) -> dict:
    """Precision por disputa y por pares, y exhaustividad sobre las disputas reales etiquetadas."""
    reported = correct = pairs = good_pairs = expected = found = 0
    errors: list[str] = []
    for story in fixture["historias"]:
        comp = compare(_articles(story))
        exp = expected_disputes(story)
        expected += len(exp)
        for key, figs in comp.disputes.items():
            noun = key.split(" ")[0]
            facts = [_fact(story["hechos"], noun, f.outlet, f.value) for f in figs]
            reported += 1
            ok = None not in facts and len(set(facts)) == 1
            correct += ok
            if not ok:
                errors.append(f"{story['historia']}:{key}")
            for (fa, a), (fb, b) in combinations(zip(facts, figs, strict=True), 2):
                if a.value != b.value:
                    pairs += 1
                    good_pairs += fa is not None and fa == fb
            found += noun in exp
    return {
        "disputas": reported,
        "precision": round(correct / reported, 3) if reported else 1.0,
        "precision_pares": round(good_pairs / pairs, 3) if pairs else 1.0,
        "exhaustividad": round(found / expected, 3) if expected else 1.0,
        "esperadas": expected,
        "errores": errors,
    }
