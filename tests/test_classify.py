from truthnews.classify import classify, normalize, topics


def test_normalize_strips_accents():
    assert normalize("Política ÉXITO") == "politica exito"


def test_keyword_classification():
    assert classify("El Gobierno aprueba un decreto en el Congreso") == "politica"
    assert classify("El IPC sube y el paro baja") == "economia"
    assert classify("Real Madrid gana la liga") == "deportes"
    assert classify("Los vídeos del partido entre el Real Valladolid y el Eldense") == "deportes"
    assert classify("Antxon Muneta podría tener las horas contadas como míster del Mirandés") == "deportes"
    assert classify("Portugal vence e conquista bronze no Mundial de hóquei", language="pt") == "deportes"
    assert classify("Una tarde cualquiera") == "sociedad"
    assert classify("Inflation rises in the United States economy", language="en") == "economia"


def test_url_and_hint_priority():
    assert classify("x", url="https://m.es/opinion/2026/x.html") == "opinion"
    assert classify("Real Madrid gana", hint="economia") == "economia"
    assert classify("algo", url="https://m.es/deportes/futbol/x") == "deportes"
    assert classify("algo", tags=["deportes"]) == "deportes"


def test_topics_dedup_and_limit():
    assert topics("t", ["Vivienda", "vivienda", "ab", "Ley " * 30, "Madrid"]) == ["Vivienda", "Madrid"]
    assert len(topics("t", [f"tema {i}" for i in range(20)], limit=3)) == 3
