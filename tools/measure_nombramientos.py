"""Mide la extraccion de nombramientos y ceses del BOE sobre sumarios reales de los ultimos dias.

Uso: python tools/measure_nombramientos.py [--days 15] [--to AAAA-MM-DD]
Imprime, por tipo, cuantas disposiciones hay y en cuantas se reconoce persona y cargo.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import date, timedelta

from truthnews.data.nombramientos import nombramientos


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=15)
    ap.add_argument("--to", type=date.fromisoformat, default=date.today())
    args = ap.parse_args()
    items, days = [], 0
    day = args.to
    while days < args.days:
        if day.weekday() != 6:  # el BOE no se publica en domingo
            items += nombramientos(day)
            days += 1
            time.sleep(1)
        day -= timedelta(days=1)
    out = {
        "dias": days,
        "hasta": args.to.isoformat(),
        "total": len(items),
        "tipos": dict(Counter(i.tipo for i in items)),
    }
    for kind in ("nombramiento", "cese"):
        xs = [i for i in items if i.tipo == kind]
        ind = [i for i in xs if i.persona]
        out[kind] = {"total": len(xs), "individuales": len(ind), "con_cargo": sum(bool(i.cargo) for i in ind)}
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
