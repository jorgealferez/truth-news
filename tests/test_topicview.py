from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from truthnews.config import Settings
from truthnews.models import Article, Outlet, Piece, Story, Topic
from truthnews.web import seo, topicview
from truthnews.web.app import create_app

COMMON = "Más eléctricos por debajo de 25.000 euros"
COMMON_SUMMARY = (
    "A cierre de 2026 habrá en Europa dieciséis coches eléctricos baratos según Transport Environment"
)


def test_slugify_and_paths():
    assert seo.slugify(COMMON) == "mas-electricos-por-debajo-de-25000-euros"
    assert seo.slugify("¿Qué pasó en Ceuta? 1,5 millones") == "que-paso-en-ceuta-1-5-millones"
    assert seo.slugify("") == "" and seo.slugify(None) == ""
    long = seo.slugify("palabra " * 30)
    assert len(long) <= seo.MAX_SLUG and not long.endswith("-") and long.endswith("palabra")
    assert seo.path("tema", 19, COMMON) == "/tema/19-mas-electricos-por-debajo-de-25000-euros"
    assert seo.path("tema", 19, "¡¿!") == "/tema/19"
    assert seo.parse_ref("19-algo") == 19 and seo.parse_ref("19") == 19
    assert seo.parse_ref("abc") is None and seo.parse_ref("-19") is None


def _topic(session, n_copies=4):
    now = datetime.now(UTC)
    tp = Topic(title="Eléctricos", category="economia", country="ES", first_seen=now, last_seen=now)
    session.add(tp)
    session.flush()
    st = Story(
        title="Historia", category="economia", country="ES", first_seen=now, last_seen=now, topic_id=tp.id
    )
    session.add(st)
    session.flush()
    outlets = []
    for i in range(n_copies + 1):
        o = Outlet(
            slug=f"m{i}",
            name=f"Medio {i}",
            homepage=f"https://m{i}.es",
            country="ES",
            language="es",
            scope="regional" if i else "national",
        )
        session.add(o)
        outlets.append(o)
    session.flush()

    def art(o, title, summary, minutes, k):
        session.add(
            Article(
                outlet_id=o.id,
                url=f"https://{o.slug}.es/{k}",
                url_hash=f"{o.slug}{k}".ljust(64, "0"),
                title=title,
                summary=summary,
                published_at=now - timedelta(minutes=minutes),
                language="es",
                country="ES",
                category="economia",
                topics=[],
                story_id=st.id,
            )
        )

    for i, o in enumerate(outlets[:n_copies]):
        art(o, COMMON, COMMON_SUMMARY, 100 - i, "a")
    art(
        outlets[1], "El vehículo eléctrico gana terreno", "Las marcas chinas suman cuota de mercado", 120, "b"
    )
    art(outlets[-1], "Conductores de Ourense divididos", "Debate en el salón del automóvil local", 5, "c")
    session.commit()
    return tp, outlets


def test_same_text_groups_and_view(session):
    tp, outlets = _topic(session)
    from truthnews.web import queries

    arts = queries.topic_articles(session, tp.id)
    groups = topicview.same_text_groups(arts)
    assert len(groups) == 1 and len({a.outlet_id for a in groups[0]}) == 4
    synth = {
        "que_dice_cada_medio": [
            {"medio_slug": o.slug, "sintesis": f"Síntesis {o.name}", "enfoque": "e"} for o in outlets
        ],
        "diferencias": [{"aspecto": "Heridos", "detalle": "5 frente a 15"}],
        "valoracion": {"conclusion": "c", "confianza": "media", "lo_que_no_sabemos": ["El total"]},
    }
    view = topicview.build(arts, synth, {o.slug: o for o in outlets}, {})
    g = view["groups"][0]
    assert g["n"] == 4 and g["first"].outlet.slug == "m0" and g["summary"]["medio_slug"] == "m0"
    assert [m["outlet"].slug for m in g["members"] if m["adds"]] == ["m1"]
    assert {r["medio_slug"] for r in view["own"]} == {"m1", "m4"}
    assert {r["medio_slug"] for r in view["copied"]} == {"m0", "m2", "m3"}
    assert view["n_outlets"] == 5 and view["n_copy_only"] == 3 and view["n_own"] == 2
    assert view["first"].outlet.slug == "m1"  # la pieza propia de m1 salio antes que el texto comun
    assert view["fails"] == ["Heridos"] and view["missing"] == ["El total"]
    assert {k for k, _ in view["flags"]} == {"one_source", "no_official_data", "no_verified_claims"}
    assert dict((s, n) for s, n, _ in view["scopes"]) == {"national": 1, "regional": 4}
    assert topicview.build([], {}, {}, {})["scopes"] == []


def test_topic_page_visual_and_redirects(engine, session):
    tp, outlets = _topic(session)
    title = "Más eléctricos baratos: un mismo texto en cuatro medios"
    synth = {
        "claves": {
            "en_una_frase": "Una previsión de una ONG publicada igual por cuatro medios.",
            "origen": "Informe de Transport & Environment",
            "que_falla": ["Previsión contada como hecho"],
            "que_falta": ["Precios reales en España"],
        },
        "que_dice_cada_medio": [
            {"medio_slug": o.slug, "sintesis": f"Síntesis {o.name}", "enfoque": "e"} for o in outlets
        ],
        "coincidencias": ["Dieciséis modelos"],
        "diferencias": [],
        "datos": [],
        "valoracion": {"conclusion": "Fuente única", "confianza": "baja", "lo_que_no_sabemos": []},
        "historias_citadas": [],
    }
    session.add(
        Piece(
            topic_id=tp.id,
            kind="analisis",
            status="publicada",
            title=title,
            dek="Entradilla",
            body=[{"subtitulo": "", "parrafos": ["Texto largo"]}],
            synthesis=synth,
            grounding={},
            model="m",
            input_hash="h",
            usage={},
        )
    )
    session.commit()
    client = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
    want = seo.path("tema", tp.id, title)
    r = client.get(f"/tema/{tp.id}?lang=es", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == want + "?lang=es"
    assert client.get(f"/tema/{tp.id}-slug-viejo", follow_redirects=False).headers["location"] == want
    page = client.get(want)
    assert page.status_code == 200
    html = page.text
    for needle in [
        f'<link rel="canonical" href="http://localhost:8000{want}">',
        "Una previsión de una ONG",
        "Informe de Transport &amp; Environment",
        "Previsión contada como hecho",
        "Precios reales en España",
        "4 medios publicaron el mismo texto",
        "Síntesis Medio 0",  # el resumen del grupo es el del primero que lo publico
        "Síntesis Medio 1",  # aporta una pieza propia: sale aparte
        "Síntesis Medio 4",
        "Leer el análisis completo",
        "Quién lo cuenta",
    ]:
        assert needle in html, needle
    assert "Síntesis Medio 2" not in html  # solo repite el texto comun: va en el grupo
    from truthnews.web import structured

    (art,) = structured.of_type(html, "NewsArticle")
    assert art["url"] == f"http://localhost:8000{want}" and art["description"] == "Entradilla"
    assert art["datePublished"] and art["publisher"]["name"] == "NosMienten"
    assert client.get("/tema/abc").status_code == 404
    st = session.query(Story).first()
    loc = client.get(f"/historia/{st.id}", follow_redirects=False).headers["location"]
    assert loc == f"/historia/{st.id}-historia"
    a = session.query(Article).first()
    assert client.get(f"/noticia/{a.id}", follow_redirects=False).status_code == 301
    assert client.get(f"/noticia/{a.id}").status_code == 200
