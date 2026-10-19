"""Que cambia entre dos programas del mismo partido (18d): promesas repetidas, nuevas y que desaparecen.

Dos promesas son la misma si comparten la mayor parte de sus palabras de contenido (Jaccard sobre las
raices, sin palabras vacias): una medida conservadora, que prefiere no emparejar a emparejar mal. Cada
pareja se cita con las dos paginas; nada se califica.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from truthnews.analysis.text import tokens
from truthnews.models import Promise

SAME = 0.6
MIN_TOKENS = 4


@dataclass
class Comparison:
    repeated: list[tuple[Promise, Promise, float]]  # (antes, ahora, parecido)
    new: list[Promise]
    dropped: list[Promise]


def _bag(p: Promise) -> frozenset[str]:
    return frozenset(tokens(p.text))


def compare(before: list[Promise], after: list[Promise], same: float = SAME) -> Comparison:
    bags_before = {p.id: _bag(p) for p in before}
    index: dict[str, list[Promise]] = defaultdict(list)
    for p in before:
        for tok in bags_before[p.id]:
            index[tok].append(p)
    repeated, new, used = [], [], set()
    for p in after:
        bag = _bag(p)
        if len(bag) < MIN_TOKENS:
            continue
        best, score = None, 0.0
        for cand in {c.id: c for tok in bag for c in index.get(tok, ())}.values():
            other = bags_before[cand.id]
            j = len(bag & other) / len(bag | other)
            if j > score:
                best, score = cand, j
        if best is not None and score >= same:
            repeated.append((best, p, round(score, 2)))
            used.add(best.id)
        else:
            new.append(p)
    dropped = [p for p in before if p.id not in used and len(bags_before[p.id]) >= MIN_TOKENS]
    return Comparison(repeated, new, dropped)
