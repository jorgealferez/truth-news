from pathlib import Path

from truthnews.crawler.extract import canonical_url, extract_text, sha256, word_count
from truthnews.crawler.feeds import clean_text, discover_feed_urls, parse_feed

FIX = Path(__file__).parent / "fixtures"


def test_parse_feed_unwraps_escaped_cdata_and_skips_untitled():
    entries, is_feed = parse_feed((FIX / "feed.xml").read_bytes())
    assert is_feed
    assert [e.title for e in entries] == [
        "El Gobierno aprueba el decreto de vivienda",
        "El IPC sube al 3,1 % en septiembre",
        "Prohibida por robots",
    ]
    first = entries[0]
    assert first.summary == "El Consejo de Ministros aprobó hoy el decreto ."
    assert first.tags == ["Vivienda"]
    assert first.image_url == "https://medio.test/img/1.jpg"
    assert first.published_at.isoformat() == "2026-10-18T08:00:00+00:00"
    assert entries[2].published_at is None


def test_parse_non_feed():
    entries, is_feed = parse_feed(b"<html><body>hola</body></html>")
    assert entries == [] and not is_feed


def test_discover_feed_urls():
    html = """<head><link rel="alternate" type="application/rss+xml" href="/rss/portada.xml">
    <link rel='alternate' type='application/atom+xml' href='https://m.es/atom'>
    <link rel="alternate" type="application/rss+xml" href="/comments/feed">
    <link rel="stylesheet" href="/x.css">
    <link rel="alternate" type="application/rss+xml" href="/rss/portada.xml"></head>"""
    assert discover_feed_urls(html, "https://m.es/") == ["https://m.es/rss/portada.xml", "https://m.es/atom"]
    assert discover_feed_urls(html, "https://m.es/", limit=1) == ["https://m.es/rss/portada.xml"]


def test_clean_text_truncates():
    assert clean_text(None) == ""
    out = clean_text("<p>uno dos tres cuatro cinco</p>", limit=12)
    assert out.endswith("…") and len(out) <= 12


def test_canonical_url_and_hash():
    assert canonical_url("HTTPS://Medio.ES/a?utm_source=x&id=3&fbclid=y#frag") == "https://medio.es/a?id=3"
    assert len(sha256("x")) == 64
    assert word_count(None) == 0 and word_count("a b c") == 3


def test_extract_text():
    html = (
        "<html><body><article><h1>T</h1>"
        + "<p>Texto largo del articulo con contenido real. </p>" * 20
        + "</article></body></html>"
    )
    text = extract_text(html, "https://m.es/a")
    assert text and "contenido real" in text
