"""Medida en vivo del calendario electoral (ADR 0036): barre N dias del BOE y cuenta convocatorias.

Uso: python tools/measure_elecciones.py [dias]  -> JSON con dias leidos, convocatorias, fechas y tiempo.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime

from truthnews.elections.calendar import Calendar


def main(days: int = 75) -> dict:
    c = Calendar(days, background=False, registry_raw={"elections": []})
    now = datetime.now(UTC)
    t0 = time.monotonic()
    c.warm(now.date(), pause=0.3)
    seconds = round(time.monotonic() - t0, 1)
    found = c.boe()
    return {
        "measured_at": now.isoformat(timespec="seconds"),
        "boe_days_scanned": len(c._days),
        "seconds": seconds,
        "convocations": [
            {
                "slug": e.slug,
                "name": e.name,
                "date": e.date.isoformat(),
                "campaign": [d.isoformat() for d in e.campaign] if e.campaign else None,
                "constitution": e.constitution.isoformat() if e.constitution else None,
                "source": e.sources[0].url,
            }
            for e in found
        ],
        "active": [e.slug for e in c.active(None, now)],
    }


if __name__ == "__main__":
    print(json.dumps(main(int(sys.argv[1]) if len(sys.argv) > 1 else 75), ensure_ascii=False, indent=2))
