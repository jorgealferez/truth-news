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


def test_only_figures_of_the_same_fact_are_disputed():
    # Caso real (historia 796): 12 migrantes ocultados en una casa frente a 500 desalojados no es disputa.
    arts = [
        art("A", "Ceuta desaloja a unos 500 migrantes", minutes=0),
        art("B", "Desalojados 500 inmigrantes de zonas periféricas", minutes=10),
        art("C", "Condenada por ocultar a doce migrantes en su casa", minutes=20),
    ]
    c = compare(arts)
    assert "migrantes" not in c.disputes
    assert c.agreed_figures == [("migrantes", 500, 2)]
    # Un balance que se actualiza sigue siendo disputa (2 -> 3 muertos, 1.800 -> 2.400 detenidos).
    c = compare([art("A", "Dos muertos en un cayuco"), art("B", "Tres muertos en el cayuco", minutes=60)])
    assert [f.value for f in c.disputes["muertos"]] == [2.0, 3.0]
    # Dos recuentos atribuidos de la misma manifestacion son disputa aunque difieran mucho.
    c = compare(
        [
            art("A", "20.000 manifestantes, según la Delegación del Gobierno"),
            art("B", "Según los organizadores, 100.000 manifestantes en Madrid", minutes=5),
        ]
    )
    assert [f.value for f in c.disputes["manifestantes"]] == [20000.0, 100000.0]


def test_headline_figure_wins_over_a_breakdown_in_the_same_article():
    # Caso real (historia 337): "Más de 1.800 detenidos ... París registró 855 arrestos".
    arts = [
        art("A", "Más de 1.800 detenidos en Francia", "París registró 855 arrestos."),
        art("B", "2.000 detenidos en Francia"),
    ]
    assert [f.value for f in compare(arts).disputes["detenidos"]] == [1800.0, 2000.0]


def test_a_second_disputed_fact_keeps_its_own_key():
    from truthnews.analysis.compare import Figure, same_facts

    figs = [Figure("muertos", v, "", o, T0, "") for o, v in [("A", 2), ("B", 3), ("C", 400), ("D", 600)]]
    assert [[f.outlet for f in fact] for fact in same_facts(figs)] == [["C", "D"], ["A", "B"]]
    arts = [
        art("A", "Dos muertos en el cayuco"),
        art("B", "Tres muertos en el cayuco"),
        art("C", "400 muertos en el terremoto"),
        art("D", "600 muertos en el terremoto"),
    ]
    assert sorted(compare(arts).disputes) == ["muertos", "muertos ·2"]


def test_dispute_precision_on_real_labeled_stories():
    import json
    from pathlib import Path

    from truthnews.analysis.evaluate import dispute_quality, grouping_quality

    fixture = json.loads((Path(__file__).parent / "fixtures" / "disputes.json").read_text(encoding="utf-8"))
    q = dispute_quality(fixture)
    # Medido 2026-10-19 (ADR 0016): antes 0,50 de precision (4 de 8 disputas mezclaban hechos distintos).
    # Con las 13 historias de produccion del 18-19/10 (ADR 0053): antes 0,611 (7 de 18 mal), despues 1,00.
    assert q["precision"] >= 0.95 and q["precision_pares"] >= 0.95, q["errores"]
    assert q["exhaustividad"] >= 0.95 and q["esperadas"] == 11
    g = grouping_quality(fixture)
    # Pares de cifras puestos en el mismo hecho o separados como dice la etiqueta: antes 0,797, despues 0,99.
    assert g["aciertos"] >= 0.98, g["errores"]


def test_dispute_validation_set_is_measured():
    # Fuera de muestra (ADR 0053): se mide y se publica en docs/benchmarks, no se ajusta para que pase.
    import json
    from pathlib import Path

    from truthnews.analysis.evaluate import dispute_quality, grouping_quality

    path = Path(__file__).parent / "fixtures" / "disputes_validacion.json"
    validation = json.loads(path.read_text(encoding="utf-8"))
    ids = {i for m in validation["muestras"] for i in m["historias"]}
    assert ids == {h["historia"] for h in validation["historias"]}
    dev = json.loads((path.parent / "disputes.json").read_text(encoding="utf-8"))
    assert not ids & {h["historia"] for h in dev["historias"]}
    assert dispute_quality(validation)["esperadas"] >= 1 and grouping_quality(validation)["pares"] > 0


def test_territory_party_and_money_keep_facts_apart():
    from truthnews.analysis.compare import _figures
    from truthnews.classify import normalize

    # Casos reales del 19/10: el ozono por comunidad, el CIS andaluz por partido, el alquiler en euros.
    arts = [
        art("A", "El ozono causa cada año hasta 300 muertes en Aragón"),
        art("B", "El aire tóxico de Navarra: un exceso de 190 muertes en verano"),
        art("C", "La dana deja dos muertos en Cataluña y la Comunidad Valenciana"),
        art("D", "La dana deja tres muertos en la Comunidad Valenciana"),
    ]
    assert [[f.outlet for f in figs] for figs in compare(arts).disputes.values()] == [["C", "D"]]
    arts = [
        art("A", "Vox, con el 16,1 %, lograría entre 16 y 20 escaños"),
        art("B", "Vox sube, mientras Adelante Andalucía alcanzaría hasta diez escaños"),
        art("C", "El PP lograría entre 52 y 53 escaños"),
        art("D", "Los populares obtendrían 47 escaños, según otra encuesta"),
    ]
    disputes = compare(arts).disputes
    assert [[f.outlet for f in figs] for figs in disputes.values()] == [["C", "D"]]
    arts = [
        art("A", "Solo trece provincias siguen por debajo de los 700 euros de alquiler"),
        art("B", "Los alquileres superan los 1.000 euros en doce provincias"),
        art("C", "Los alquileres superan los 1.000 euros en doce provincias"),
    ]
    comp = compare(arts)
    assert comp.disputes == {} and comp.agreed_figures == [("euros", 1000, 2)]
    # Lo que les paso decide, no quienes son: "mueren 12 inmigrantes" son muertos (caso real 9640), y la
    # cifra anterior no cuenta como contexto ("2.397 detenidos y 997 policias heridos").
    assert [f[:2] for f in figures("Mueren 12 inmigrantes en dos naufragios")] == [("muertos", 12.0)]
    assert [f[:2] for f in figures("Con 2.397 detenidos y 997 policías heridos")] == [
        ("detenidos", 2397.0),
        ("heridos", 997.0),
    ]
    assert [f[:2] for f in figures("Llegan 39 migrantes a Cartagena")] == [("migrantes", 39.0)]
    assert [f[:2] for f in figures("Han sido detenidas dos personas")] == [("detenidos", 2.0)]
    # Las cifras se leen en castellano: en portugues "dos votos" no son dos.
    pt = art("B", "Lula obteve 47,03% dos votos e 2.400 detenidos")
    pt.language = "pt"
    assert compare([art("A", "2.000 detenidos en Francia"), pt]).disputes == {}
    # El lugar de la data ("Madrid, 19 oct (EFE).-") no es el territorio de la cifra.
    ((*_, territory, party, subject),) = _figures(
        normalize("Madrid, 19 oct (EFE).- Detenidas 40 personas en Sevilla")
    )
    assert territory == {"andalucia"} and party is None and subject is None
    # A quien le paso es parte del hecho (caso real 2109, Chile): carabineros y manifestantes heridos.
    arts = [art("A", "Seis carabineros heridos en Santiago"), art("B", "Hay cuatro manifestantes heridos")]
    assert compare(arts).disputes == {}
    arts = [art("A", "Seis carabineros heridos"), art("B", "14 agentes heridos, según el ministro")]
    assert [f.value for f in compare(arts).disputes["heridos"]] == [6.0, 14.0]


def test_personas_context_stays_in_its_sentence():
    # Caso real (France 24, 19/10): los 39 son heridos, no muertos.
    text = "Carney confirmó cuatro muertos. Otras 39 personas resultaron heridas, 19 de ellas de gravedad."
    assert [f[:2] for f in figures(text)] == [("muertos", 4.0), ("heridos", 39.0)]
