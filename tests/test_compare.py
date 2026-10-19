from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from truthnews.analysis.compare import compare, figures, loaded_words, proper_nouns

T0 = datetime(2026, 10, 18, 8, tzinfo=UTC)


def art(outlet, title, summary="", text=None, minutes=0):
    return NS(
        outlet=NS(name=outlet),
        title=title,
        summary=summary,
        content_text=text,
        published_at=T0 + timedelta(minutes=minutes),
        language="es",
    )


def test_figures_word_boundaries_and_scales():
    assert [(n, v, q) for n, v, q, _ in figures("Más de 1.800 detenidos y cuatro militares muertos")] == [
        ("detenidos", 1800.0, "mas de"),
        ("muertos", 4.0, ""),
    ]
    assert [v for _, v, _, _ in figures("unos 2 millones de votos y tres mil manifestantes")] == [2e6, 3000]
    assert figures("Desalojados 500 inmigrantes")[0][:2] == ("migrantes", 500.0)
    assert figures("un herido leve") == []


def test_compare_disputes_consensus_omissions_loaded():
    long = " Ayer Macron habló en París con Bruselas al fondo. " * 3
    arts = [
        art("A", "Caos en Francia: 2.000 detenidos y 500 heridos", text="Texto." + long, minutes=0),
        art("B", "Francia: 2.400 detenidos y 500 heridos", text="Texto." + long, minutes=60),
        art("C", "Protestas en Francia con 500 heridos", text="Texto sin nombres propios.", minutes=90),
        art("D", "Directo: 9.999 detenidos", minutes=100),
        art("E", "Jornada de protestas", text="Texto." + long, minutes=120),
    ]
    c = compare(arts)
    assert c.outlets == ["A", "B", "C", "D", "E"] and c.basis == "texto completo"
    assert [(f.outlet, f.value) for f in c.disputes["detenidos"]] == [("A", 2000.0), ("B", 2400.0)]
    assert "heridos: 500" in c.consensus and "Macron" in c.consensus
    assert c.omissions == {"C": ["Bruselas", "Macron", "París"]}
    assert c.loaded == {"A": ["caos"]}


def test_helpers():
    assert proper_nouns("Ayer, Emmanuel Macron dijo algo.  Este lunes") == {"Emmanuel Macron"}
    assert loaded_words("Una auténtica masacre y un escándalo") == ["escandalo", "masacre"]
    assert compare([art("A", "Uno")]).basis == "titulares y resumenes"


def test_personas_is_disambiguated_by_context():
    from truthnews.analysis.compare import figures

    assert [f[:2] for f in figures("Un coche mata a dos personas en Kansas")] == [("muertos", 2.0)]
    assert [f[:2] for f in figures("11 personas resultaron heridas")] == [("heridos", 11.0)]
    assert [f[:2] for f in figures("Unas 300 personas fueron evacuadas")] == [("evacuados", 300.0)]
    assert figures("Un cayuco con 132 personas llega a El Hierro") == []


def test_blames_and_framing_differences():
    from truthnews.analysis.compare import blames

    assert blames("Feijóo culpa al Gobierno de Sánchez del caos en Rodalies") == ["Gobierno de Sánchez"]
    assert blames("Vox carga contra Marlaska por la crisis") == ["Marlaska"]
    assert blames("Retrasos por culpa de Adif en la línea") == ["Adif"]
    assert blames("El Gobierno apunta a que la cifra sube") == []
    arts = [
        art("A", "El PSOE culpa a la Generalitat de los retrasos"),
        art("B", "El PP responsabiliza al Gobierno de los retrasos", minutes=30),
        art("C", "Retrasos en la red ferroviaria", minutes=60),
    ]
    c = compare(arts)
    assert c.blame == {"A": ["Generalitat"], "B": ["Gobierno"]} and c.blame_differs
    assert c.dispute_summaries() == []


def test_summarize_dispute_groups_by_value():
    arts = [
        art("A", "Protestas: 1.800 detenidos"),
        art("B", "Protestas con 1.800 detenidos", minutes=10),
        art("C", "Protestas: más de 2.400 detenidos", minutes=20),
    ]
    (d,) = compare(arts).dispute_summaries()
    assert (d.low, d.high, d.mode, d.mode_n, d.n_outlets) == (1800, 2400, 1800, 2, 3)
    assert [len(figs) for _, figs in d.groups] == [2, 1]
