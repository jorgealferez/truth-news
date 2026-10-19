"""Mide en vivo las fuentes de contratacion publica: anuncios del BOE (V.A) y adjudicaciones de Espana en TED.

Uso: python tools/measure_contratacion.py [--days 14] [--to AAAA-MM-DD]
Imprime cuantos anuncios y adjudicaciones hay y en cuantos se reconocen organo, objeto, importe y NIF.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import date, timedelta

from truthnews.data.contratacion import boe_anuncios, ted_adjudicaciones


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--to", type=date.fromisoformat, default=date.today())
    args = ap.parse_args()
    since = args.to - timedelta(days=args.days)
    boe, day = [], args.to
    while day >= since:
        if day.weekday() != 6:  # el BOE no se publica en domingo
            boe += boe_anuncios(day)
            time.sleep(1)
        day -= timedelta(days=1)
    t0 = time.monotonic()
    ted = ted_adjudicaciones(since, args.to)
    out = {
        "desde": since.isoformat(),
        "hasta": args.to.isoformat(),
        "boe": {
            "anuncios": len(boe),
            "tipos": dict(Counter(a.tipo for a in boe)),
            "con_organo": sum(bool(a.organo) for a in boe),
            "con_objeto": sum(bool(a.objeto) for a in boe),
            "con_expediente": sum(bool(a.expediente) for a in boe),
        },
        "ted": {
            "adjudicaciones": len(ted),
            "segundos": round(time.monotonic() - t0, 1),
            "con_importe": sum(a.importe is not None for a in ted),
            "con_adjudicatario": sum(bool(a.adjudicatarios) for a in ted),
            "un_adjudicatario_con_nif": sum(
                len(a.adjudicatarios) == 1 and bool(a.adjudicatarios[0][1]) for a in ted
            ),
            "varios_adjudicatarios": sum(len(a.adjudicatarios) > 1 for a in ted),
            "importe_eur": round(sum(a.importe or 0 for a in ted if a.moneda == "EUR")),
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
