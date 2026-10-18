"""Comprueba en vivo cada fuente de datos oficial (criterio C5). Imprime JSON con el resultado."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from truthnews.data import boe, eurostat, gdelt, ine, worldbank


def main() -> None:
    checks = {
        "eurostat": lambda: eurostat.latest(
            "une_rt_m", "ES", {"s_adj": "SA", "age": "TOTAL", "sex": "T", "unit": "PC_ACT"}
        ),
        "ine": lambda: ine.annual_change("IPC290751"),
        "worldbank": lambda: worldbank.latest("SP.POP.TOTL", "ES"),
        "boe": lambda: boe.sumario((datetime.now(UTC) - timedelta(days=2)).date()) or None,
        "gdelt": lambda: gdelt.timeline("protests europe", "7d") or None,
    }
    out = {}
    for name, fn in checks.items():
        try:
            res = fn()
        except Exception as exc:  # se informa, no se oculta
            out[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
            continue
        if res is None:
            out[name] = {"ok": False}
        elif isinstance(res, list):
            out[name] = {"ok": True, "items": len(res)}
        else:
            out[name] = {"ok": True, "period": res.period, "value": res.value}
    out["vivas"] = sum(1 for v in out.values() if isinstance(v, dict) and v.get("ok"))
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
