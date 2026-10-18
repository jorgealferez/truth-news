"""Registro de paises, categorias, medios e idiomas cargado desde YAML (datos, no codigo)."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

REGISTRY_DIR = Path(__file__).resolve().parent
SCOPES = ("national", "regional", "local", "international")
KINDS = ("press", "tv", "radio", "agency", "factcheck")


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class FeedSpec:
    url: str
    category: str | None = None


@dataclass(frozen=True)
class OutletSpec:
    slug: str
    name: str
    homepage: str
    country: str
    language: str
    scope: str
    region: str | None = None
    city: str | None = None
    kind: str = "press"
    owner: str | None = None
    feeds: tuple[FeedSpec, ...] = field(default_factory=tuple)


def _load_yaml(path: Path):
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=1)
def countries() -> dict:
    return _load_yaml(REGISTRY_DIR / "countries.yaml")


@lru_cache(maxsize=1)
def categories() -> dict:
    return _load_yaml(REGISTRY_DIR / "categories.yaml")


@lru_cache(maxsize=1)
def translations() -> dict:
    return _load_yaml(REGISTRY_DIR / "i18n.yaml")


def languages() -> list[str]:
    return list(translations().keys())


def t(lang: str, key: str) -> str:
    table = translations()
    return table.get(lang, {}).get(key) or table["es"].get(key, key)


def category_name(slug: str, lang: str) -> str:
    cat = categories().get(slug)
    if not cat:
        return slug
    return cat["name"].get(lang) or cat["name"]["es"]


def country_name(iso: str, lang: str) -> str:
    c = countries().get(iso)
    if not c:
        return iso
    return c["name"].get(lang) or c["name"]["es"]


def region_name(code: str) -> str:
    country = code.split("-")[0]
    return countries().get(country, {}).get("regions", {}).get(code, code)


def _parse_outlet(raw: dict, country: str, default_language: str) -> OutletSpec:
    for key in ("slug", "name", "homepage", "scope"):
        if not raw.get(key):
            raise RegistryError(f"medio sin '{key}': {raw}")
    scope = raw["scope"]
    if scope not in SCOPES:
        raise RegistryError(f"{raw['slug']}: scope invalido {scope!r}")
    kind = raw.get("kind", "press")
    if kind not in KINDS:
        raise RegistryError(f"{raw['slug']}: kind invalido {kind!r}")
    region = raw.get("region")
    if region and region not in countries().get(country, {}).get("regions", {}):
        raise RegistryError(f"{raw['slug']}: region desconocida {region!r} para {country}")
    if scope in ("regional", "local") and not region:
        raise RegistryError(f"{raw['slug']}: un medio {scope} necesita region")
    feeds = []
    for f in raw.get("feeds") or []:
        cat = f.get("category")
        if cat and cat not in categories():
            raise RegistryError(f"{raw['slug']}: categoria desconocida {cat!r}")
        feeds.append(FeedSpec(url=f["url"], category=cat))
    return OutletSpec(
        slug=raw["slug"],
        name=raw["name"],
        homepage=raw["homepage"],
        country=country,
        language=raw.get("language", default_language),
        scope=scope,
        region=region,
        city=raw.get("city"),
        kind=kind,
        owner=raw.get("owner"),
        feeds=tuple(feeds),
    )


def load_outlets(directory: Path | None = None) -> list[OutletSpec]:
    directory = directory or REGISTRY_DIR / "sources"
    outlets: list[OutletSpec] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.yaml")):
        data = _load_yaml(path)
        country = data["country"]
        if country not in countries():
            raise RegistryError(f"{path.name}: pais {country!r} no esta en countries.yaml")
        default_language = data.get("default_language") or countries()[country]["default_language"]
        for raw in data.get("outlets") or []:
            spec = _parse_outlet(raw, country, default_language)
            if spec.slug in seen:
                raise RegistryError(f"slug duplicado: {spec.slug}")
            seen.add(spec.slug)
            outlets.append(spec)
    return outlets


def stats(outlets: list[OutletSpec] | None = None) -> dict:
    outlets = outlets if outlets is not None else load_outlets()
    out: dict = {"total": len(outlets), "by_country": {}, "by_scope": {}, "regions_covered": {}}
    for o in outlets:
        out["by_country"][o.country] = out["by_country"].get(o.country, 0) + 1
        key = f"{o.country}:{o.scope}"
        out["by_scope"][key] = out["by_scope"].get(key, 0) + 1
        if o.region:
            out["regions_covered"].setdefault(o.country, set()).add(o.region)
    coverage = {}
    for iso, regs in out["regions_covered"].items():
        ccaa = countries()[iso].get("autonomous_communities", [])
        coverage[iso] = {
            "regions": len(regs),
            "communities": len([r for r in ccaa if r in regs]),
            "communities_total": len(ccaa),
            "missing": [r for r in ccaa if r not in regs],
        }
    out["regions_covered"] = coverage
    return out
