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
    """Variacion interanual (%) del ultimo mes a partir de una serie de indice (p. ej. IPC290751)."""
    obs = series(code, last=14, transport=transport)
    by_period = {o.period: o for o in obs}
    for o in reversed(obs):
        year, month = int(o.period[:4]), o.period[5:]
        base = by_period.get(f"{year - 1}-{month}")
        if base and base.value:
            value = round((o.value / base.value - 1) * 100, 2)
            return Observation(
                "ine",
                f"{o.label} (variación anual calculada)",
                o.url,
                o.period,
                value,
                extra={"serie": code, "indice": o.value, "indice_hace_un_ano": base.value},
            )
    return None
