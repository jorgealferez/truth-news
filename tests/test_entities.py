import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from truthnews import archive
from truthnews.analysis import ranking
from truthnews.config import Settings
from truthnews.entities import views
from truthnews.entities.extract import entity_key, extract, fold, speaker_of
from truthnews.entities.store import process, refresh_counts
from truthnews.models import Article, Claim, Entity, Evidence, Mention, Outlet, Story, Verification
from truthnews.web.app import create_app

NOW = datetime.now(UTC)
FIXTURE = Path(__file__).parent / "fixtures" / "entities.json"


def measure() -> dict:
    """Precision y exhaustividad del extractor sobre el conjunto etiquetado (ADR 0027)."""
    docs = json.loads(FIXTURE.read_text(encoding="utf-8"))["docs"]
    tp = fp = fn = stp = sfp = sfn = 0
    for doc in docs:
        got = extract(doc["title"], doc["text"])
        keys = {f.key for f in got}
        want = {entity_key(k, n) for k, n in doc["entidades"]}
        tp, fp, fn = tp + len(keys & want), fp + len(keys - want), fn + len(want - keys)
        said = {f.name for f in got if f.speaks}
        want_said = set(doc["hablan"])
        stp, sfp, sfn = stp + len(said & want_said), sfp + len(said - want_said), sfn + len(want_said - said)
    return {
        "precision": tp / (tp + fp),
        "recall": tp / (tp + fn),
        "speaker_precision": stp / (stp + sfp),
        "speaker_recall": stp / (stp + sfn),
        "entities": tp + fn,
        "speakers": stp + sfn,
    }


def test_extractor_meets_its_published_quality():
    m = measure()
    assert m["precision"] >= 0.95 and m["recall"] >= 0.90
    assert m["speaker_precision"] >= 0.90 and m["speaker_recall"] >= 0.85
    assert m["entities"] >= 50 and m["speakers"] >= 10


def test_fold_keeps_length_and_case_rules():
    assert fold("Núñez Feijóo") == "nunez feijoo" and len(fold("Ñandú ﬁn")) == len("Ñandú ﬁn")
    names = {f.name for f in extract("Hay que sumar votos", "el pp no es PP: podemos hablar")}
    assert names == {"Partido Popular"}  # "sumar", "pp" y "podemos" en minusculas no son partidos


def test_discovery_needs_a_given_name_or_an_institution_head():
    found = {(f.kind, f.name) for f in extract("Gran Premio de Motos en Jerez", "Lo dijo Marta Ruiz García.")}
    assert ("persona", "Marta Ruiz García") in found
    assert not any(n.startswith("Gran Premio") for _, n in found)
    found = {(f.kind, f.name) for f in extract("", "El Consejo de Seguridad Nuclear informa.")}
    assert ("institucion", "Consejo de Seguridad Nuclear") in found


def test_discovery_errors_seen_in_production():
    # Medidos en produccion el 2026-10-19 (fichas /entidad): nombres que cruzan un salto de linea, dos
    # personas unidas por "y", nombres de pila compuestos, cabezas inglesas y estadios.
    text = (
        "Lo firma Ricardo Sanz\nDirector del centro. Lo cuentan Manuel García y Javier Martínez Valencia."
        " Habló José María en la radio. Ruta por el Red Sea con la Union Home Minister. Gol en el Santiago"
        " Bernabéu. Pedro Martín presentó la Asociación Española Contra el Cáncer."
    )
    names = {f.name for f in extract("", text)}
    assert "Ricardo Sanz" in names and not any("Director" in n for n in names)
    assert "Manuel García" in names and "Javier Martínez Valencia" in names
    assert not {"José María", "Red Sea", "Union Home Minister", "Santiago Bernabéu"} & names
    assert {"Pedro Martín", "Asociación Española Contra el Cáncer"} <= names


def test_gdelt_strict_raises_instead_of_returning_nothing():
    import httpx

    from truthnews.data import gdelt

    t = httpx.MockTransport(lambda r: httpx.Response(429, text="Please limit requests"))
    start, end = NOW - timedelta(days=30), NOW
    assert gdelt.articles("x", start, end, transport=t, sleep=lambda s: None, retries=0) == []
    with pytest.raises(gdelt.Unavailable):
        gdelt.articles("x", start, end, transport=t, sleep=lambda s: None, retries=0, strict=True)


def test_extraction_older_than_the_rules_is_redone(session, corpus):
    from truthnews.entities.store import EXTRACTOR_SINCE

    process(session)
    elena = session.scalars(select(Entity).where(Entity.key == "persona:elena martinez")).one()
    # Una entidad de una extraccion antigua que las reglas nuevas ya no producen pierde sus cifras.
    old = Entity(
        key="persona:ruido viejo",
        kind="persona",
        name="Ruido Viejo",
        aliases=[],
        n_articles=1,
        n_outlets=1,
        n_mentions=1,
    )
    session.add(old)
    session.flush()
    _, arts, _, _ = corpus
    session.add(
        Mention(
            entity_id=old.id,
            article_id=arts[0].id,
            outlet_id=arts[0].outlet_id,
            published_at=arts[0].published_at,
        )
    )
    for a in arts:
        a.entities_at = EXTRACTOR_SINCE - timedelta(hours=1)
    session.flush()
    assert process(session)["articles"] == 3
    assert (old.n_articles, elena.n_articles) == (0, 3)


def test_speaker_of_a_claim_sentence():
    who = speaker_of("La ministra María Jesús Montero ha asegurado que el paro está en el 9 %.")
    assert who is not None and who.name == "María Jesús Montero"
    assert speaker_of("El paro está en el 9 % según el INE.").name == "INE"
    assert speaker_of("El paro está en el 9 %, con Feijóo y Sánchez en el debate.") is None
    # Dos que hablan en la misma frase: no se adivina.
    assert speaker_of("Feijóo dijo que el paro sube y Yolanda Díaz afirmó que baja.") is None


@pytest.fixture()
def corpus(session):
    outs = [
        Outlet(
            slug=f"m{i}",
            name=f"Medio {i}",
            homepage=f"https://www.medio{i}.es",
            country="ES",
            language="es",
            scope="national",
        )
        for i in range(3)
    ]
    session.add_all(outs)
    session.flush()
    st = Story(title="Debate", category="politica", country="ES", first_seen=NOW, last_seen=NOW)
    session.add(st)
    session.flush()
    texts = [
        ("Feijóo y Sánchez chocan por el paro", "La ministra Elena Martínez ha afirmado que el paro baja."),
        ("Sánchez defiende sus cuentas", "Elena Martínez aseguró que el paro está en el 14,5 %."),
        ("Elena Martínez, ante la prensa", "Según Elena Martínez, la deuda baja. Lo dijo en Sevilla."),
    ]
    arts = []
    for i, (title, summary) in enumerate(texts):
        a = Article(
            outlet_id=outs[i].id,
            url=f"https://medio{i}.es/{i}",
            url_hash=f"e{i:063d}",
            title=title,
            summary=summary,
            published_at=NOW - timedelta(hours=i),
            language="es",
            country="ES",
            category="politica",
            topics=[],
            story_id=st.id,
        )
        session.add(a)
        arts.append(a)
    session.flush()
    claim = Claim(
        article_id=arts[1].id,
        story_id=st.id,
        outlet_id=outs[1].id,
        text="Elena Martínez aseguró que el paro está en el 14,5 %.",
        indicator="paro",
        geo="ES",
        value=14.5,
        unit="pct",
    )
    session.add(claim)
    session.flush()
    ver = Verification(claim_id=claim.id, verdict="falso", confidence=0.9, explanation="x", method="nivel/v3")
    ver.evidence.append(
        Evidence(source="ine", label="EPA", url="https://ine.es/epa", period=f"{NOW.year}-Q3", value=10.5)
    )
    session.add(ver)
    session.flush()
    return outs, arts, st, claim


def test_process_stores_mentions_counts_and_speakers(session, corpus):
    outs, arts, st, claim = corpus
    out = process(session, now=NOW)
    assert out["articles"] == 3 and out["speakers"] == 1 and out["mentions"] == 4
    elena = session.scalars(select(Entity).where(Entity.key == "persona:elena martinez")).one()
    assert (elena.n_articles, elena.n_outlets, elena.curated) == (3, 3, False)
    assert claim.speaker_entity_id == elena.id
    said = session.scalars(select(Mention).where(Mention.entity_id == elena.id, Mention.role == "dice")).all()
    assert len(said) == 3 and all(m.quote and m.story_id == st.id for m in said)
    sanchez = session.scalars(
        select(Entity).where(Entity.key == entity_key("persona", "Pedro Sánchez"))
    ).one()
    assert sanchez.curated and sanchez.n_articles == 0  # "Sanchez" solo no es un alias del registro
    # Idempotente: nada pendiente; reprocesar reescribe sin duplicar.
    assert process(session)["articles"] == 0
    n = session.scalar(select(func.count(Mention.id)))
    for a in arts:
        a.entities_at = None
    process(session)
    assert session.scalar(select(func.count(Mention.id))) == n


def test_refresh_counts_zeroes_entities_without_mentions(session, corpus):
    process(session)
    elena = session.scalars(select(Entity).where(Entity.key == "persona:elena martinez")).one()
    session.query(Mention).filter(Mention.entity_id == elena.id).delete()
    refresh_counts(session, [elena.id])
    assert (elena.n_articles, elena.n_mentions, elena.n_outlets) == (0, 0, 0)


def test_rankings_profile_and_web_pages(engine, session, corpus):
    outs, arts, st, claim = corpus
    process(session)
    st.contrast_score, st.n_outlets = 4.0, 3
    st.contrast = {"disputas": ["paro"]}
    rows = views.ranking(session)
    assert rows[0][0].name == "Elena Martínez" and rows[0][1:] == (3, 3)
    assert all(e.kind == "persona" for e, _, _ in views.ranking(session, kind="persona"))
    elena = rows[0][0]
    p = views.profile(session, elena.id)
    assert p.checked == 1 and p.bad == 1 and len(p.quotes) == 3 and p.months and p.peak == 3
    assert {o.name for o, _ in p.together} >= {"Alberto Núñez Feijóo"}
    assert views.oldest_article(session, elena.id) is not None
    lonely = Entity(
        key="persona:x y", kind="persona", name="X Y", aliases=[], n_outlets=1, n_articles=1, n_mentions=1
    )
    session.add(lonely)
    session.flush()
    assert views.profile(session, lonely.id) is None  # descubierta con un solo medio: no se publica
    session.commit()
    client = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
    r = client.get("/discrepancias")
    assert r.status_code == 200 and "Elena Martínez" in r.text and "14,5 %" in r.text and "10,5 %" in r.text
    assert client.get("/entidades").status_code == 200
    assert "Elena Martínez" in client.get("/entidades?tipo=persona&dias=7").text
    r = client.get(f"/entidad/{elena.id}", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == f"/entidad/{elena.id}-elena-martinez"
    page = client.get(f"/entidad/{elena.id}-elena-martinez")
    assert page.status_code == 200 and "Lo que dice" in page.text and "Falso" in page.text
    assert client.get(f"/entidad/{lonely.id}").status_code == 404
    story = client.get(f"/historia/{st.id}-debate")
    assert story.status_code == 200 and "Quién aparece" in story.text
    assert f'href="/entidad/{elena.id}-elena-martinez"' in story.text
    assert [e.name for e, _ in views.for_story(session, st.id)][0] == "Elena Martínez"
    assert client.get("/entidad/999999").status_code == 404
    assert "People and entities" in client.get("/entidades?lang=en").text


def test_ranking_falsehoods_contradictions_and_board(session, corpus):
    outs, arts, st, claim = corpus
    process(session)
    f = ranking.falsehoods(session, now=NOW)
    assert len(f) == 1 and f[0].official == 10.5 and f[0].speakers and round(f[0].deviation, 3) == 0.381
    assert ranking.falsehoods(session, country="PT", now=NOW) == []
    # Otra cifra del mismo actor, indicador, territorio y periodo: contradiccion.
    other = Claim(
        article_id=arts[2].id,
        outlet_id=outs[2].id,
        text="Elena Martínez dijo que el paro está en el 12 %.",
        indicator="paro",
        geo="ES",
        value=12.0,
        unit="pct",
        speaker_entity_id=claim.speaker_entity_id,
    )
    session.add(other)
    session.flush()
    v = Verification(
        claim_id=other.id, verdict="impreciso", confidence=0.8, explanation="x", method="nivel/v3"
    )
    v.evidence.append(
        Evidence(source="ine", label="EPA", url="https://ine.es", period=f"{NOW.year}-Q3", value=10.5)
    )
    session.add(v)
    session.flush()
    c = ranking.contradictions(session, now=NOW)
    assert (
        len(c) == 1 and c[0].actor == "Elena Martínez" and sorted(x[0] for x in c[0].values) == [12.0, 14.5]
    )
    assert c[0].label == "Tasa de paro"
    board = ranking.scoreboard(session, now=NOW)
    top = board["personas"][0]
    assert (top.name, top.bad, top.imprecise, top.checked) == ("Elena Martínez", 1, 1, 2)
    assert top.share_bad == 0.5 and len(board["medios"]) == 2
    assert (
        ranking.gravity("falso", 0.5, 10, 0)
        > ranking.gravity("falso", 0.5, 1, 0)
        > ranking.gravity("falso", 0.5, 1, 60)
    )
    assert (
        ranking.deviation(5, 0) == 1.0
        and ranking.deviation(0, 0) == 0.0
        and ranking.deviation(1, None) is None
    )


def test_discrepancies_use_disputed_figures(session):
    outs = [
        Outlet(
            slug=f"d{i}", name=f"D{i}", homepage="https://d", country="ES", language="es", scope="national"
        )
        for i in range(2)
    ]
    session.add_all(outs)
    st = Story(
        title="Incendio",
        category="sucesos",
        country="ES",
        first_seen=NOW,
        last_seen=NOW,
        n_outlets=2,
        contrast_score=2.0,
        contrast={"disputas": ["muertos"]},
    )
    session.add(st)
    session.flush()
    for i, n in enumerate((3, 5)):
        session.add(
            Article(
                outlet_id=outs[i].id,
                url=f"https://d/{i}",
                url_hash=f"d{i:063d}",
                title=f"El incendio deja {n} muertos en Huelva",
                published_at=NOW,
                language="es",
                country="ES",
                category="sucesos",
                topics=[],
                story_id=st.id,
            )
        )
    session.flush()
    d = ranking.discrepancies(session, country="ES", now=NOW)
    assert len(d) == 1 and d[0].disputes[0].low == 3 and d[0].disputes[0].high == 5
    assert ranking.discrepancies(session, country="PT", now=NOW) == []


def gkg_zip(rows: list[list[str]]) -> bytes:
    """Un fichero GKG 2.1 de prueba: 27 columnas separadas por tabuladores, dentro de un zip."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.gkg.csv", "\n".join("\t".join(r) for r in rows))
    return buf.getvalue()


def gkg_row(when: str, domain: str, url: str, title: str | None, lang: str = "spa", collection: str = "1"):
    row = [""] * 27
    row[1], row[2], row[3], row[4] = when, collection, domain, url
    row[25] = f"srclc:{lang};eng:GT-SPA 1.0" if lang else ""
    row[26] = f"<PAGE_TITLE>{title}</PAGE_TITLE>" if title is not None else ""
    return row


def test_archive_imports_gkg_slots_backwards(session, corpus):
    outs, arts, st, claim = corpus
    calls = []

    def fake(url):
        calls.append(url)
        stamp = url.rsplit("/", 1)[1][:14]
        return gkg_zip(
            [
                gkg_row(
                    stamp, "medio0.es", f"https://www.medio0.es/{stamp}/elena", "Elena Mart&#xED;nez, en 2019"
                ),
                gkg_row(stamp, "otro.com", "https://otro.com/x", "Fuera del registro"),
                gkg_row(stamp, "medio1.es", "https://medio1.es/sin", None),
                gkg_row(stamp, "medio2.es", "https://medio2.es/cat", "Titular en catal\u00e0", lang="cat"),
                gkg_row(stamp, "medio2.es", "https://medio2.es/x", "No es web", collection="2"),
                gkg_row("roto", "medio2.es", "https://medio2.es/y", "Fecha rota"),
            ]
        )

    ticks = iter(range(1000))
    out = archive.run(
        session, slots=2, stride=timedelta(hours=6), now=NOW, fetch=fake, clock=lambda: next(ticks)
    )
    assert out["slots"] == 2 and out["new"] == 3  # la catalana tiene el mismo enlace en los dos tramos
    first = archive.floor_slot(min(a.published_at for a in arts)) - timedelta(hours=6)
    assert calls == [
        f"{archive.BASE}/{first:%Y%m%d%H%M%S}.translation.gkg.csv.zip",
        f"{archive.BASE}/{first - timedelta(hours=6):%Y%m%d%H%M%S}.translation.gkg.csv.zip",
    ]
    imported = session.scalars(select(Article).where(Article.origin == "archivo").order_by(Article.id)).all()
    assert imported[0].title == "Elena Martínez, en 2019" and imported[0].url.startswith(
        "https://www.medio0.es/"
    )
    assert {a.language for a in imported} == {"es", "ca"} and all(a.entities_at is None for a in imported)
    # La siguiente vuelta sigue hacia atras desde lo mas antiguo importado; lo repetido no se duplica.
    archive.run(session, slots=1, stride=timedelta(hours=6), now=NOW, fetch=fake)
    assert calls[-1].endswith(f"{first - timedelta(hours=12):%Y%m%d%H%M%S}.translation.gkg.csv.zip")
    # Lo importado se extrae en el ciclo siguiente y entra en la linea temporal como archivo.
    process(session)
    elena = session.scalars(select(Entity).where(Entity.key == "persona:elena martinez")).one()
    assert views.profile(session, elena.id).archive_articles == 3
    # Un tramo que falla no tumba el paso ni deshace lo anterior; un tramo que no existe se salta.
    total = session.scalar(select(func.count(Article.id)).where(Article.origin == "archivo"))
    assert total == 4

    def boom(url):
        raise RuntimeError("gdelt caido")

    assert archive.run(session, slots=1, now=NOW, fetch=boom)["slots"] == 0
    missing = archive.run(session, slots=1, now=NOW, fetch=lambda url: None)
    assert (missing["slots"], missing["new"]) == (1, 0)
    assert session.scalar(select(func.count(Article.id)).where(Article.origin == "archivo")) == total


def test_archive_helpers(session, corpus):
    outs, *_ = corpus
    assert archive.host("https://www.elpais.com/x") == "elpais.com" and archive.host("abc.es") == "abc.es"
    t = datetime(2025, 3, 5, 12, 44, 59, tzinfo=UTC)
    assert archive.floor_slot(t) == datetime(2025, 3, 5, 12, 30, tzinfo=UTC)
    hosts = archive.outlet_hosts(session, ["ES"])
    assert (
        set(hosts) == {"medio0.es", "medio1.es", "medio2.es"} and archive.outlet_hosts(session, ["PT"]) == {}
    )
    assert len(archive.file_urls(t, hosts)) == 1  # sin medios en ingles no se baja el fichero ingles
    outs[0].language = "en"
    assert archive.file_urls(t, hosts)[1].endswith("20250305124459.gkg.csv.zip")
    assert archive.parse(["x"] * 3, hosts) is None
    # Sin medios de esos paises no se pide nada; por debajo de 2015 tampoco.
    assert archive.run(session, countries=["PT"], fetch=lambda u: 1 / 0)["slots"] == 0
    assert archive.run(session, now=archive.FLOOR, fetch=lambda u: 1 / 0)["slots"] == 0


def test_archive_download_handles_missing_slots():
    import httpx

    from truthnews import data

    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(404 if "missing" in str(request.url) else 200, content=b"zip")

    real = data.client
    try:
        archive.client = lambda: real(httpx.MockTransport(handler))
        assert archive.download("https://data.gdeltproject.org/gdeltv2/missing.zip") is None
        assert archive.download("https://data.gdeltproject.org/gdeltv2/ok.zip") == b"zip"
    finally:
        archive.client = real


def test_archived_articles_are_not_verified_against_todays_data(session, corpus):
    from truthnews.analysis.pipeline import verify_claims
    from truthnews.analysis.verify import Verifier
    from truthnews.data import Observation

    outs, arts, st, claim = corpus
    session.add(
        Article(
            outlet_id=outs[0].id,
            url="https://medio0.es/old",
            url_hash="o" * 64,
            origin="archivo",
            title="La tasa de paro se sitúa en el 20,5 %",
            published_at=NOW,
            language="es",
            country="ES",
            category="economia",
            topics=[],
        )
    )
    session.flush()
    verifier = Verifier(lambda s, g, label: Observation("ine", label, "https://ine.es", "2026-09", 10.5))
    verify_claims(session, NOW - timedelta(days=1), verifier)  # las rastreadas del corpus
    old = session.scalars(select(Article).where(Article.origin == "archivo")).one()
    assert session.scalar(select(func.count(Claim.id)).where(Claim.article_id == old.id)) == 0


def test_cli_entities_and_archive(monkeypatch, db_url, capsys):
    from truthnews import cli

    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr(archive, "download", lambda url: None)
    assert cli.main(["entities", "--limit", "10"]) == 0
    assert '"articles": 0' in capsys.readouterr().out
    assert cli.main(["archive", "--slots", "1", "--countries", ""]) == 0
    assert '"slots"' in capsys.readouterr().out


def test_archive_cursor_ignores_stray_old_articles(session, corpus):
    # Produccion 2026-10-19: 4 noticias de 2022 importadas por la API antigua hicieron saltar el recorrido
    # a diciembre de 2022. La serie contigua desde la primera noticia rastreada es la que manda.
    outs, arts, *_ = corpus
    session.add(
        Article(
            outlet_id=outs[0].id,
            url="https://medio0.es/2022",
            url_hash="s" * 64,
            origin="archivo",
            title="Suelta de 2022",
            published_at=datetime(2022, 12, 15, 16, tzinfo=UTC),
            language="es",
            country="ES",
            category="politica",
            topics=[],
        )
    )
    session.flush()
    start = archive.floor_slot(min(a.published_at for a in arts))
    stride = timedelta(hours=6)
    assert archive.oldest(session, NOW, stride) == start
    calls = []

    def fake(url):
        calls.append(url)
        stamp = url.rsplit("/", 1)[1][:14]
        return gkg_zip([gkg_row(stamp, "medio1.es", f"https://medio1.es/{stamp}", "Titular de archivo")])

    archive.run(session, slots=2, stride=stride, now=NOW, fetch=fake)
    assert calls[0].endswith(f"{start - stride:%Y%m%d%H%M%S}.translation.gkg.csv.zip")
    assert archive.oldest(session, NOW, stride) == start - 2 * stride
