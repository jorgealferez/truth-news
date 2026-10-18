"""Agrupacion incremental de articulos en historias (la misma noticia contada por varios medios).

TF-IDF sobre titular (peso doble) y resumen, similitud coseno contra el centroide de las historias
abiertas en una ventana temporal; un articulo se une a la historia mas parecida si supera el umbral,
o abre una nueva. Determinista y sin dependencias externas (ADR 0004).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from truthnews.analysis.text import tokens

DEFAULT_THRESHOLD = 0.30
DEFAULT_WINDOW = timedelta(hours=48)


@dataclass
class Doc:
    key: object
    title: str
    summary: str = ""
    published_at: datetime | None = None
    outlet: str = ""

    def terms(self) -> Counter:
        c = Counter(tokens(self.title))
        c.update(c)  # titular con peso doble
        c.update(tokens(self.summary[:400]))
        return c


@dataclass
class Group:
    members: list[Doc] = field(default_factory=list)
    vectors: list[dict[str, float]] = field(default_factory=list)
    centroid: dict[str, float] = field(default_factory=dict)
    last_seen: datetime | None = None
    _sum: Counter = field(default_factory=Counter)

    def add(self, doc: Doc, vec: dict[str, float]) -> None:
        self.members.append(doc)
        self.vectors.append(vec)
        self._sum.update(vec)
        norm = math.sqrt(sum(v * v for v in self._sum.values())) or 1.0
        self.centroid = {k: v / norm for k, v in self._sum.items()}
        if doc.published_at and (self.last_seen is None or doc.published_at > self.last_seen):
            self.last_seen = doc.published_at


def representative(group: Group) -> Doc:
    """El miembro mas parecido al centroide: su titular resume mejor la historia que el primero."""
    best = max(range(len(group.members)), key=lambda i: cosine(group.vectors[i], group.centroid))
    return group.members[best]


def idf_table(docs: Iterable[Doc]) -> dict[str, float]:
    df: Counter = Counter()
    n = 0
    for d in docs:
        n += 1
        df.update(set(d.terms()))
    return {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}


def vectorize(doc: Doc, idf: dict[str, float]) -> dict[str, float]:
    tf = doc.terms()
    vec = {t: (1 + math.log(c)) * idf.get(t, 1.0) for t, c in tf.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {t: v / norm for t, v in vec.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def cluster(
    docs: list[Doc],
    threshold: float = DEFAULT_THRESHOLD,
    window: timedelta = DEFAULT_WINDOW,
    idf: dict[str, float] | None = None,
) -> list[Group]:
    """Agrupa en orden cronologico. Devuelve todas las historias (tambien las de un solo articulo)."""
    idf = idf if idf is not None else idf_table(docs)
    ordered = sorted(docs, key=lambda d: (d.published_at or datetime.min, str(d.key)))
    groups: list[Group] = []
    postings: dict[str, list[int]] = {}  # termino -> indices de historias que lo contienen
    for doc in ordered:
        vec = vectorize(doc, idf)
        best, best_i, best_sim = None, -1, 0.0
        # Solo se comparan las historias que comparten algun termino con el documento (indice invertido).
        candidates = {i for t in vec for i in postings.get(t, ())}
        for i in sorted(candidates):
            g = groups[i]
            if doc.published_at and g.last_seen and doc.published_at - g.last_seen > window:
                continue
            sim = cosine(vec, g.centroid)
            if sim > best_sim:
                best, best_i, best_sim = g, i, sim
        if best is not None and best_sim >= threshold:
            target, index = best, best_i
        else:
            target, index = Group(), len(groups)
            groups.append(target)
        before = set(target.centroid)
        target.add(doc, vec)
        for t in vec:
            if t not in before:
                postings.setdefault(t, []).append(index)
    return groups


def pairwise_scores(pred: list[list[object]], gold: list[list[object]]) -> dict[str, float]:
    """Precision/exhaustividad/F1 por pares (dos articulos en la misma historia)."""

    def pairs(groups: list[list[object]]) -> set[tuple]:
        out = set()
        for g in groups:
            items = sorted(map(str, g))
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    out.add((items[i], items[j]))
        return out

    p, g = pairs(pred), pairs(gold)
    tp = len(p & g)
    precision = tp / len(p) if p else 1.0
    recall = tp / len(g) if g else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "pred_pairs": len(p),
        "gold_pairs": len(g),
    }
