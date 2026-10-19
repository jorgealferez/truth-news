"""Punto de entrada publico para juzgar un texto suelto (una declaracion, un post) con el mismo juez.

No crea filas: devuelve los candidatos de las reglas y su veredicto contra el dato oficial. Quien guarde
el resultado (p. ej. las declaraciones de los partidos) lo hace con su propio modelo; el metodo es este.
"""

from __future__ import annotations

from datetime import datetime

from truthnews.analysis.claims import ClaimCandidate, extract
from truthnews.analysis.verify import Result, Verifier


def judge_text(
    text: str,
    language: str,
    default_geo: str,
    published: datetime,
    verifier: Verifier | None = None,
) -> list[tuple[ClaimCandidate, Result]]:
    """Afirmaciones comprobables de `text` (reglas) y su veredicto; `default_geo` "XX": sin pais supuesto."""
    verifier = verifier or Verifier()
    return [
        (c, verifier.judge(c)) for c in extract(text, language, default_geo, published.year, published.month)
    ]


def judge_candidate(cand: ClaimCandidate, verifier: Verifier | None = None) -> Result:
    """Veredicto de un candidato ya validado (p. ej. propuesto por la IA con `ai.claims.propose`)."""
    return (verifier or Verifier()).judge(cand)
