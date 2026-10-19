"""Nombramientos y ceses del BOE: sumarios reales (seccion II.A del 7 y 8 de octubre de 2026)."""

import json
from datetime import date
from pathlib import Path

import httpx

from truthnews.data import nombramientos as nb

FIX = Path(__file__).parent / "fixtures"


def load(day: str) -> dict:
    return json.loads((FIX / f"boe_sumario_{day}_2A.json").read_text())


def test_parse_real_summary_keeps_only_section_2a():
    items = nb.parse(load("20261007"), date(2026, 10, 7))
    assert len(items) == 13 and all(i.fecha == "2026-10-07" for i in items)
    assert all(i.id.startswith("BOE-A-2026-") and i.url.startswith("https://www.boe.es/") for i in items)
    by_person = {i.persona: i for i in items if i.persona}
    gab = by_person["María Tejero Martín"]
    assert gab.tipo == "nombramiento"
    assert gab.cargo == "Directora del Gabinete del Secretario de Estado para la Unión Europea"
    assert gab.departamento.startswith("MINISTERIO")
    # Un ascenso militar: persona si, cargo no (solo se extrae para nombramientos y ceses).
    assert by_person["Francisco Javier Moscoso Sicardo"].tipo == "ascenso"
    assert by_person["Francisco Javier Moscoso Sicardo"].cargo == ""


def test_combined_cese_and_appointment_does_not_leak_into_post():
    items = nb.parse(load("20261008"), date(2026, 10, 8))
    cese = next(i for i in items if i.persona == "Jaime Serrano-Jover González")
    assert cese.tipo == "cese" and cese.cargo.startswith("Fiscal Delegado de la Fiscalía Especial")
    assert "se nombra" not in cese.cargo and cese.cargo.endswith("Santa Cruz de Tenerife")
    fiscal = next(i for i in items if i.persona == "María Dolores Rial de la Calle")
    assert fiscal.cargo == "Teniente Fiscal de la Fiscalía de la Comunidad Autónoma de las Illes Balears"


def test_title_rules():
    t = (
        "Real Decreto 785/2026, por el que se designa Embajador de España en la "
        "República de Angola a don Miguel Utray Delgado."
    )
    assert nb.kind_of("", t) == "nombramiento" and nb.person_of(t) == "Miguel Utray Delgado"
    assert nb.post_of(t, "nombramiento") == "Embajador de España en la República de Angola"
    t = (
        "Orden INT/1091/2026, por la que se nombra para el Mando de la Jefatura "
        "de Policía Marítima (Madrid), "
        "al General de Brigada don José Miguel García Malo de Molina Martínez."
    )
    assert nb.post_of(t, "nombramiento") == "Mando de la Jefatura de Policía Marítima (Madrid)"
    assert nb.person_of(t) == "José Miguel García Malo de Molina Martínez"
    t = (
        "Orden INT/1089/2026, por la que se dispone el cese del Teniente General don Francisco "
        "Javier Moscoso Sicardo en el Mando de la Jefatura."
    )
    assert nb.kind_of("Ceses", t) == "cese" and nb.post_of(t, "cese") == "Mando de la Jefatura"
    t = (
        "Real Decreto 1/2026, por el que se dispone el cese de don Carlos Moreno Blanco "
        "como Secretario General, a petición propia."
    )
    assert nb.kind_of("", t) == "cese" and nb.post_of(t, "cese") == "Secretario General"
    # Nombramientos colectivos: sin persona ni cargo inventados.
    t = (
        "Resolución de 21 de septiembre de 2026, de la Universidad de Almería, por la "
        "que se nombran Catedráticos de Universidad."
    )
    assert nb.person_of(t) == "" and nb.post_of(t, "nombramiento") == ""
    assert nb.kind_of("Promociones", "Resolución sin más") == "otro"
    assert nb.kind_of("Jubilaciones", "x") == "situacion" and nb.kind_of("Destinos", "x") == "destino"


def test_fetch_uses_open_data_api_and_fails_closed():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("20261007"):
            return httpx.Response(200, json=load("20261007"))
        return httpx.Response(404)

    t = httpx.MockTransport(handler)
    items = nb.nombramientos(date(2026, 10, 7), transport=t)
    assert len(items) == 13 and seen[0].headers["Accept"] == "application/json"
    assert str(seen[0].url) == "https://www.boe.es/datosabiertos/api/boe/sumario/20261007"
    assert nb.nombramientos(date(2026, 10, 11), transport=t) == []  # sin BOE ese dia
    assert nb.as_dicts(items[:1])[0]["id"] == items[0].id
    assert nb.parse({}, date(2026, 10, 7)) == []
