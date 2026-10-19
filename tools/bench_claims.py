"""Medida del carril de verificaciones sobre una base real (DATABASE_URL): que extraen las reglas y cuantas
frases candidatas llegarian a la IA (por articulo; el ritmo por ciclo sale del log de produccion).

Uso: DATABASE_URL=sqlite:///bench.db python tools/bench_claims.py
"""

from __future__ import annotations

import json

from sqlalchemy import select

from truthnews.ai.claims import BATCH, candidate_sentences
from truthnews.analysis.claims import extract
from truthnews.analysis.pipeline import _aware, article_text
from truthnews.db import get_engine, session_scope
from truthnews.models import Article


def main() -> dict:
    with session_scope(get_engine()) as session:
        arts = list(session.scalars(select(Article)))
        rules = cand = with_text = with_cand = 0
        for a in arts:
            pub = _aware(a.published_at)
            text = article_text(a)
            n = len(candidate_sentences(text))
            with_text += bool(a.content_text)
            rules += len(extract(text, a.language, a.country, pub.year, pub.month))
            cand += n
            with_cand += n > 0
    n_arts = max(len(arts), 1)
    out = {
        "articulos": len(arts),
        "articulos_con_texto": with_text,
        "afirmaciones_por_reglas": rules,
        "afirmaciones_por_reglas_por_articulo": round(rules / n_arts, 4),
        "articulos_con_frases_candidatas": with_cand,
        "frases_candidatas_ia": cand,
        "frases_candidatas_por_articulo": round(cand / n_arts, 3),
        "frases_por_llamada": BATCH,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return out


if __name__ == "__main__":
    main()
