"""INE (API Tempus3): series oficiales de Espana por codigo de serie."""

from __future__ import annotations

import httpx

from truthnews.data import Observation, client

BASE = "https://servicios.ine.es/wstempus/js/ES"


def series(code: str, last: int = 13, transport: httpx.BaseTransport | None = None) -> list[Observation]:
    url = f"{BASE}/DATOS_SERIE/{code}?nult={last}"
    with client(transport) as c:
        resp = c.get(url)
    if resp.status_code != 200:
        return []
    body = resp.json()
    out = []
    for d in body.get("Data", []):
        if d.get("Valor") is None or d.get("Secreto"):
            continue
        # Periodo desde Anyo y FK_Periodo (mes 1-12): `Fecha` es medianoche en hora de Madrid y en UTC
        # cae en el mes anterior.
        period = f"{d['Anyo']}-{int(d['FK_Periodo']):02d}"
        out.append(
            Observation(
                "ine", body.get("Nombre", code).strip(), url, period, float(d["Valor"]), extra={"serie": code}
            )
        )
    return sorted(out, key=lambda o: o.period)


def annual_change(code: str, transport: httpx.BaseTransport | None = None) -> Observation | None:
    """Variacion interanual (%) de una serie de indice (p. ej. IPC290751): el ultimo mes y el historial."""
    obs = series(code, last=26, transport=transport)
    by_period = {o.period: o for o in obs}
    history: dict[str, float] = {}
    for o in obs:
        year, month = int(o.period[:4]), o.period[5:]
        base = by_period.get(f"{year - 1}-{month}")
        if base and base.value:
            history[o.period] = round((o.value / base.value - 1) * 100, 2)
    if not history:
        return None
    last = max(history)
    latest = by_period[last]
    out = Observation(
        "ine",
        f"{latest.label} (variación anual calculada)",
        latest.url,
        last,
        history[last],
        extra={"serie": code, "indice": latest.value},
        history=history,
    )
    periods = sorted(history)
    if len(periods) > 1:
        out.previous = out.at(periods[-2])
    return out
