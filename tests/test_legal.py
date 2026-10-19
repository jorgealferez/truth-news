"""Cumplimiento normativo UE y Espana (ADR 0039): paginas legales, pie, sitemap e inventario de cookies."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from truthnews.config import Settings
from truthnews.web import legal
from truthnews.web.app import create_app

ROOT = Path(__file__).resolve().parents[1] / "truthnews"


def client(engine, **legal_data):
    return TestClient(create_app(Settings(database_url="sqlite://", **legal_data), engine=engine))


def test_legal_pages_in_both_languages_and_linked(engine):
    tc = client(engine)
    expected = {
        "aviso-legal": ("Ley 34/2002", "Ley Orgánica 2/1984", "Legal notice"),
        "privacidad": ("Reglamento (UE) 2016/679", "www.aepd.es", "Privacy"),
        "cookies": ("artículo 22.2 de la LSSI", "nm_last_visit", "Cookies"),
        "transparencia": ("Reglamento (UE) 2024/1083", "Reglamento (UE) 2024/1689", "Transparency"),
    }
    for slug, (law, detail, en_title) in expected.items():
        page = tc.get(f"/{slug}?lang=es")  # el cliente guarda la cookie de idioma del paso en ingles
        assert page.status_code == 200, slug
        assert law in page.text and detail in page.text, slug
        assert f'<link rel="canonical" href="http://localhost:8000/{slug}">' in page.text
        en = tc.get(f"/{slug}?lang=en").text
        assert f"<h1>{en_title}</h1>" in en and "Spanish version is the legally binding one" in en
    home = tc.get("/").text
    for slug in legal.PAGES:
        assert f'href="/{slug}"' in home
    sitemap = tc.get("/sitemaps/paginas-1.xml").text
    assert all(f"/{slug}</loc>" in sitemap for slug in legal.PAGES)
    assert tc.get("/static/legal.js").status_code == 200


def test_missing_owner_data_is_marked_pending_never_invented(engine):
    page = client(engine).get("/aviso-legal").text
    assert "Pendiente de que el titular lo complete" in page and "legal-pending" in page
    assert legal.missing_owner_data(Settings(database_url="sqlite://")) == list(legal.OWNER_FIELDS)
    filled = client(
        engine,
        legal_owner="Ejemplo SL",
        legal_tax_id="B00000000",
        legal_address="Calle Falsa 1, Madrid",
        legal_email="legal@example.org",
        legal_ownership="Persona A (100 %)",
        legal_state_ads="0 EUR",
    )
    page = filled.get("/aviso-legal").text
    assert "Ejemplo SL" in page and "B00000000" in page and 'href="mailto:legal@example.org"' in page
    assert "legal-pending" not in page and "Pendiente de que el titular" not in page
    tr = filled.get("/transparencia").text
    assert "Persona A (100 %)" in tr and "0 EUR" in tr


def test_cookie_policy_lists_the_whole_inventory(engine):
    page = client(engine).get("/cookies").text
    for s in legal.STORAGE:
        assert f"<code>{s.name}</code>" in page and s.purpose["es"] in page
    assert "data-legal-clear" in page


def test_plain_page_sets_no_cookie(engine):
    tc = client(engine)
    for path in ("/", "/cookies", "/privacidad"):
        assert "set-cookie" not in tc.get(path).headers, path
    # La cookie de idioma solo aparece cuando el lector elige idioma.
    assert "lang=en" in tc.get("/?lang=en").headers.get("set-cookie", "")


def written_storage() -> set[str]:
    """Lo que el codigo escribe en el navegador: set_cookie en Python, setItem y document.cookie en JS."""
    names: set[str] = set()
    for py in ROOT.rglob("*.py"):
        names |= set(re.findall(r"set_cookie\(\s*[\"'](\w+)[\"']", py.read_text()))
    for js in ROOT.rglob("*.js"):
        src = js.read_text()
        consts = dict(re.findall(r"(?:var|let|const)\s+(\w+)\s*=\s*[\"'](\w+)[\"']", src))
        for arg in re.findall(r"(?:localStorage|sessionStorage)\.setItem\(\s*([^,\s]+)", src):
            names.add(consts.get(arg, arg.strip("\"'")))
        names |= set(re.findall(r"document\.cookie\s*=\s*[\"'](\w+)=", src))
    for html in ROOT.rglob("*.html"):
        assert "document.cookie" not in html.read_text() and "setItem(" not in html.read_text(), html
    return names


def test_everything_written_to_the_browser_is_declared():
    written = written_storage()
    assert {"lang", "nm_last_visit"} <= written  # el escaner los encuentra
    undeclared = written - {s.name for s in legal.STORAGE}
    assert not undeclared, f"declarar en truthnews/web/legal.py STORAGE (y en ADR 0039): {undeclared}"
