import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from truthnews.analysis.cluster import Doc, cluster, pairwise_scores, representative
from truthnews.analysis.text import stem, tokens

FIX = json.loads((Path(__file__).parent / "fixtures" / "clusters.json").read_text(encoding="utf-8"))["docs"]


def test_c4_f1_on_hand_labelled_real_headlines():
    docs = [
        Doc(
            key=d["key"],
            title=d["title"],
            outlet=d["outlet"],
            published_at=datetime.fromisoformat(d["published_at"]),
        )
        for d in FIX
    ]
    gold: dict[str, list] = {}
    for d in FIX:
        gold.setdefault(d["story"], []).append(d["key"])
    scores = pairwise_scores([[m.key for m in g.members] for g in cluster(docs)], list(gold.values()))
    assert scores["f1"] >= 0.80 and scores["precision"] >= 0.90, scores


def test_window_and_representative():
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    docs = [
        Doc(1, "Incendio en el puerto de Vigo", published_at=t0),
        Doc(2, "Incendio en el puerto de Vigo deja dos heridos", published_at=t0 + timedelta(hours=1)),
        Doc(3, "Incendio en el puerto de Vigo", published_at=t0 + timedelta(days=5)),
    ]
    groups = cluster(docs)
    assert [sorted(m.key for m in g.members) for g in groups] == [[1, 2], [3]]
    assert representative(groups[0]).key in (1, 2)


def test_pairwise_edge_cases_and_text():
    assert pairwise_scores([[1]], [[1]])["f1"] == 1.0
    assert pairwise_scores([[1, 2]], [[1], [2]])["precision"] == 0.0
    assert tokens("Las viviendas del Gobierno y 3,5 %") == ["vivien", "gobier", "3,5"]
    assert stem("2026") == "2026"
