from pathlib import Path

import pytest

from truthnews import registry


def test_c1_spanish_registry_meets_target():
    s = registry.stats()
    assert s["by_country"]["ES"] >= 80
    for scope in ("national", "regional", "local"):
        assert s["by_scope"][f"ES:{scope}"] > 0
    cov = s["regions_covered"]["ES"]
    assert cov["communities"] == cov["communities_total"] == 17
    assert cov["missing"] == []


def test_second_country_only_as_data():
    assert "PT" in registry.countries()
    assert any(o.country == "PT" for o in registry.load_outlets())


def test_c10_global_coverage_only_as_data():
    outlets = registry.load_outlets()
    with_feeds = {o.country for o in outlets if o.feeds}
    # UE, Reino Unido, EEUU, Latinoamerica, Marruecos y mundo arabe, todos con feeds declarados
    assert {"GB", "US", "FR", "DE", "IT", "MA", "MX", "AR", "BR", "SA", "EG"} <= with_feeds
    for iso in registry.countries():
        name = registry.countries()[iso]["name"]
        assert name.get("es") and name.get("en"), iso
        assert any(o.country == iso for o in outlets), f"{iso} sin medios"
    assert {o.language for o in outlets} >= {"es", "en", "fr", "de", "it", "pt", "ar"}


def test_country_keys_are_iso_codes():
    # YAML 1.1 lee NO (Noruega) como false: toda clave de pais tiene que seguir siendo un codigo ISO.
    for iso in registry.countries():
        assert isinstance(iso, str) and len(iso) == 2 and iso.isupper(), iso
    assert "NO" in registry.countries()


def test_lookups_and_translations():
    assert registry.category_name("economia", "en") == "Economy"
    assert registry.category_name("nope", "es") == "nope"
    assert registry.country_name("ES", "en") == "Spain"
    assert registry.country_name("ZZ", "es") == "ZZ"
    assert registry.region_name("ES-AN") == "Andalucía"
    assert registry.t("en", "outlets") == "Outlets"
    assert registry.t("xx", "outlets") == "Medios"
    assert set(registry.languages()) >= {"es", "en"}


NATIONAL = "- {slug: a, name: A, homepage: 'https://a', scope: national"


@pytest.mark.parametrize(
    "body,msg",
    [
        ("- {slug: a, name: A, homepage: 'https://a', scope: galactic}", "scope invalido"),
        ("- {slug: a, name: A, homepage: 'https://a', scope: national, kind: blog}", "kind invalido"),
        ("- {slug: a, name: A, homepage: 'https://a', scope: local}", "necesita region"),
        ("- {slug: a, name: A, homepage: 'https://a', scope: local, region: ES-ZZ}", "region desconocida"),
        (
            NATIONAL + ", feeds: [{url: x, category: magia}]}",
            "categoria desconocida",
        ),
        ("- {slug: a, name: A, scope: national}", "sin 'homepage'"),
        (
            NATIONAL + "}\n  " + NATIONAL.replace("name: A", "name: B") + "}",
            "duplicado",
        ),
    ],
)
def test_invalid_registry_entries(tmp_path: Path, body, msg):
    (tmp_path / "zz.yaml").write_text(f"country: ES\noutlets:\n  {body}\n", encoding="utf-8")
    with pytest.raises(registry.RegistryError, match=msg):
        registry.load_outlets(tmp_path)


def test_unknown_country_file(tmp_path: Path):
    (tmp_path / "zz.yaml").write_text("country: ZZ\noutlets: []\n", encoding="utf-8")
    with pytest.raises(registry.RegistryError, match="no esta en countries"):
        registry.load_outlets(tmp_path)
