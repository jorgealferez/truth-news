"""Veredicto trazable de una afirmacion numerica contra la serie oficial (ADR 0004)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from truthnews.analysis.claims import ClaimCandidate, indicator_name, indicators
from truthnews.data import Observation, eurostat, ine, worldbank

# Version del metodo: un veredicto guardado con otra version se vuelve a juzgar en el siguiente ciclo.
# v2: compara con el periodo citado en la frase (mes o trimestre), no con el ultimo dato.
# v3: atribucion de territorio con nomenclator mundial; la poblacion exige pais explicito (ADR 0009).
# v4: una variacion ("el paro baja un 2 %") no se lee como el nivel del indicador.
# v5: el pais del medio solo se supone si la noticia no es de otro pais; paro EPA por comunidad.
# v6: "la inflacion le resta un 3,1 %" es un efecto, no el nivel; umbrales sin error de coma flotante.
# v7: expectativas y previsiones ("eleva su expectativa de inflacion al 3,7 % en 2026") no se juzgan.
METHOD_VERSION = "v7"
# Umbrales: porcentajes en puntos, cantidades en diferencia relativa.
PCT_TRUE, PCT_ROUGH = 0.2, 0.6
ABS_TRUE, ABS_ROUGH = 0.03, 0.10


def _fmt_pct(v: float) -> str:
    return f"{v:.1f} %".replace(".", ",")


def _fmt_abs(v: float) -> str:
    return f"{v:,.0f}".replace(",", ".")


@dataclass
class Result:
    verdict: str
    confidence: float
    explanation: str
    method: str
    observations: list[Observation] = field(default_factory=list)


Fetcher = Callable[[dict, str, str], Observation | None]


def negated(obs: Observation | None) -> Observation | None:
    """La serie con el signo cambiado (deficit = -capacidad de financiacion), historial incluido."""
    if obs is None:
        return None
    out = replace(obs, value=-obs.value, history={k: -v for k, v in obs.history.items()})
    out.extra = {**obs.extra, "signo": "cambiado: déficit = −(capacidad/necesidad de financiación)"}
    out.previous = negated(obs.previous) if obs.previous else None
    return out


def default_fetch(source: dict, geo: str, label: str) -> Observation | None:
    conn = source["connector"]
    if conn == "eurostat":
        obs = eurostat.latest(source["dataset"], geo, source["params"], label)
        return negated(obs) if source.get("negate") else obs
    if conn == "worldbank":
        return worldbank.latest(source["indicator"], geo, label)
    if conn == "ine_yoy":
        return ine.annual_change(source["serie"])
    if conn == "ine_level":
        return ine.level(source["series_by_geo"][geo])
    raise ValueError(f"conector desconocido: {conn}")


def applicable(source: dict, geo: str) -> bool:
    geos = source.get("geos")
    if "-" in geo and not isinstance(geos, list):
        return False  # una comunidad solo con una serie regional explicita, nunca con la del pais
    if geos is None:
        return geo != "EU" or source["connector"] == "worldbank"
    if geos == "EU":
        return geo in indicators()["eu_geos"]
    return geo in geos


class Verifier:
    """Resuelve la serie de cada (indicador, pais) una vez por ciclo y juzga afirmaciones."""

    def __init__(self, fetch: Fetcher = default_fetch):
        self._fetch = fetch
        self._cache: dict[tuple[str, str], Observation | None] = {}

    def observation(self, indicator: str, geo: str) -> Observation | None:
        key = (indicator, geo)
        if key not in self._cache:
            obs = None
            for source in indicators()[indicator]["sources"]:
                if not applicable(source, geo):
                    continue
                try:
                    obs = self._fetch(source, geo, indicator_name(indicator))
                except Exception:  # una fuente caida no tumba el ciclo: se prueba la siguiente
                    obs = None
                if obs is not None and not obs.is_stale():
                    break
            self._cache[key] = obs
        return self._cache[key]

    def judge(self, claim: ClaimCandidate) -> Result:
        result = self._judge(claim)
        result.method = f"{result.method}/{METHOD_VERSION}"
        return result

    def _judge(self, claim: ClaimCandidate) -> Result:
        name = indicator_name(claim.indicator)
        latest = self.observation(claim.indicator, claim.geo)
        if latest is None:
            msg = f"No hay una serie oficial disponible de «{name}» para {claim.geo}."
            return Result("sin-datos", 0.0, msg, "sin-fuente")
        obs = latest
        if claim.period:
            obs = latest.at(claim.period)
            if obs is None:
                msg = (
                    f"El texto se refiere a {claim.period} y la serie oficial de «{name}» ({latest.source}) "
                    f"no tiene dato publicado para ese periodo."
                )
                return Result("sin-datos", 0.0, msg, "sin-periodo", [latest])
        elif latest.is_stale():
            return Result(
                "sin-datos",
                0.0,
                f"El último dato oficial de «{name}» ({latest.period}) es demasiado "
                "antiguo para juzgar una afirmación actual.",
                "dato-obsoleto",
                [latest],
            )
        official = obs.value
        if claim.unit == "pct":
            diff = round(abs(claim.value - official), 6)  # 8,9 - 8,7 = 0,2000000000000001 en coma flotante
            close, rough = diff <= PCT_TRUE, diff <= PCT_ROUGH
            gap = f"{diff:.1f} puntos".replace(".", ",")
            fmt = _fmt_pct
        else:
            diff = round(abs(claim.value - official) / max(abs(official), 1e-9), 6)
            close, rough = diff <= ABS_TRUE, diff <= ABS_ROUGH
            gap = f"{diff * 100:.1f} %".replace(".", ",")
            fmt = _fmt_abs
        which = "del periodo citado" if claim.period else "más reciente"
        base = (
            f"El texto dice {fmt(claim.value)}; el dato oficial {which} de «{name}» ({claim.geo}, "
            f"{obs.period}, fuente {obs.source}) es {fmt(official)}: diferencia de {gap}."
        )
        if claim.direction and obs.previous is not None and obs.previous.value != official:
            real = "sube" if official > obs.previous.value else "baja"
            if real != claim.direction:
                return Result(
                    "enganoso",
                    0.8,
                    base + f" Además afirma que {claim.direction}, pero el dato "
                    f"oficial {real} respecto a {obs.previous.period} ({fmt(obs.previous.value)}).",
                    "direccion",
                    [obs, obs.previous],
                )
        if close:
            return Result("verdadero", 0.9, base, "nivel", [obs])
        if rough:
            return Result("impreciso", 0.7, base, "nivel", [obs])
        return Result("falso", 0.8, base, "nivel", [obs])
