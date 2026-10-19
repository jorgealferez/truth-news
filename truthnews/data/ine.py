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
        fk = int(d["FK_Periodo"])
        # Trimestres: FK_Periodo 19-22 (medido en la EPA, tabla 65334); meses: 1-12.
        period = f"{d['Anyo']}-Q{fk - 18}" if 19 <= fk <= 22 else f"{d['Anyo']}-{fk:02d}"
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


def level(code: str, transport: httpx.BaseTransport | None = None) -> Observation | None:
    """Ultimo valor publicado de una serie que ya es una tasa (p. ej. la tasa de paro EPA), con historial."""
    obs = series(code, last=14, transport=transport)
    if not obs:
        return None
    latest = obs[-1]
    out = Observation(
        "ine",
        latest.label,
        latest.url,
        latest.period,
        latest.value,
        extra={"serie": code},
        history={o.period: o.value for o in obs},
    )
    if len(obs) > 1:
        out.previous = out.at(obs[-2].period)
    return out
