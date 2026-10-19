"""Lo prometido frente a lo hecho (18c, ADR 0040): reglas primero, IA solo lo justo y revisada."""

import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from truthnews.ai.client import AIError, AIResult
from truthnews.config import Settings
from truthnews.data import boe_legislacion as boe
from truthnews.elections import calendar as cal
from truthnews.elections import fulfilment as fu
from truthnews.models import Program, Promise, PromiseCheck
from truthnews.web.app import create_app

FIX = Path(__file__).parent / "fixtures"
GOV = fu.load_governments(
    [
        {
            "country": "ES",
            "name": "Gobierno de prueba",
            "from": "2023-11-17",
            "to": "2026-10-06",
            "parties": ["sumar"],
            "election": {"kind": "generales", "year": 2023},
            "source": {"label": "RD", "url": "https://www.boe.es/x"},
        }
    ]
)


def test_registry_government_is_cited_and_only_governing_programmes_count():
    g = fu.governments()[0]
    assert g.parties == ("psoe", "sumar") and g.start == date(2023, 11, 17) and g.end == date(2026, 10, 6)
    assert "BOE-A-2023-23302" in g.source_label
    p = SimpleNamespace(
        program_id=1, country="ES", actor="sumar", election_kind="generales", election_year=2023
    )
    assert fu.government_of(p) == g
    assert fu.government_of(SimpleNamespace(**{**p.__dict__, "actor": "pp"})) is None  # no goberno
    assert fu.government_of(SimpleNamespace(**{**p.__dict__, "election_year": 2019})) is None
    assert fu.government_of(SimpleNamespace(**{**p.__dict__, "program_id": None})) is None  # declaracion


def test_boe_legislation_parse_keeps_state_laws_only():
    norms = boe.parse(json.loads((FIX / "boe_legislacion_vivienda_2026.json").read_text()))
    assert [n.id for n in norms] == [
        "BOE-A-2026-20823",
        "BOE-A-2026-20822",
        "BOE-A-2026-20385",
        "BOE-A-2026-20266",
    ]
    assert norms[0].rank == "Real Decreto-ley" and norms[0].published == date(2026, 10, 7)
    assert "vivienda" in norms[0].title and norms[0].url.startswith("https://www.boe.es/")
    q = json.loads(boe.query_for(["vivienda", "alquiler"], date(2023, 11, 17), date(2026, 10, 6)))
    assert q["query"]["query_string"]["query"] == "titulo:(vivienda OR alquiler)"
    assert q["query"]["range"]["fecha_publicacion"] == {"gte": "20231117", "lte": "20261006"}


def test_key_terms_skip_generic_and_boe_common_words():
    df = Counter({"vivienda": 3, "alquiler": 2, "turisticas": 1, "personas": 50})
    text = "Garantizaremos la protección del alquiler de vivienda y limitaremos las viviendas turísticas."
    assert fu.key_terms(text, df, n_docs=100)[:3] == ["alquiler", "vivienda", "viviendas"]
    norm = boe.Norm("BOE-A-1", "Ley de vivienda y alquiler asequible", "Ley", date(2024, 1, 1), "u")
    assert fu.hits(norm, ["vivienda", "alquiler", "turisticas"]) == 2


def _promise(session, text, actor="sumar", year=2023, page=1):
    prog = session.scalars(
        select(Program).where(Program.actor == actor, Program.election_year == year)
    ).first()
    if prog is None:
        prog = Program(
            actor=actor,
            country="ES",
            election_kind="generales",
            election_year=year,
            title=f"Programa {actor} {year}",
            url=f"https://{actor}.example/{year}.pdf",
            url_hash=f"{actor}{year}",
            found_on="f",
            status="importado",
        )
        session.add(prog)
        session.flush()
    p = Promise(
        program_id=prog.id,
        actor=actor,
        country="ES",
        election_kind="generales",
        election_year=year,
        text=text,
        text_hash=str(abs(hash(text))),
        page=page,
        made_at=datetime(year, 1, 1, tzinfo=UTC),
    )
    session.add(p)
    session.flush()
    return p


def _norm(i, title, day=date(2024, 5, 1)):
    return boe.Norm(
        f"BOE-A-2024-{i}", title, "Ley", day, f"https://www.boe.es/buscar/act.php?id=BOE-A-2024-{i}"
    )


def test_rules_step_finds_candidates_without_ai(session):
    a = _promise(session, "Aprobaremos una ley de vivienda que limite el alquiler en zonas tensionadas.")
    b = _promise(session, "Crearemos un observatorio del clima en cada provincia del pais.")
    _promise(session, "Bajaremos el IVA de la cultura.", actor="pp")  # no goberno: no se mira
    _promise(session, "Otra promesa de vivienda y alquiler.", year=2019)  # otra eleccion
    calls = []

    def search(terms, since, until):
        calls.append((tuple(terms), since, until))
        if "vivienda" in terms:
            return [
                _norm(1, "Ley 12/2023 por el derecho a la vivienda y el alquiler"),
                _norm(2, "Ley de aguas"),
            ]
        return []

    out = fu.rules_step(session, 10, date(2026, 10, 19), search=search, pause=0, govs=GOV)
    assert out == {"checked": 2, "by_data": 0, "with_candidates": 1, "errors": 0}
    assert all(since == date(2023, 11, 17) and until == date(2026, 10, 6) for _, since, until in calls)
    chk = {c.promise_id: c for c in session.scalars(select(PromiseCheck))}
    assert chk[a.id].method == fu.METHOD_CANDIDATES and chk[a.id].status == "sin-datos"
    assert [e["id"] for e in chk[a.id].evidence] == ["BOE-A-2024-1"]  # la de aguas no comparte dos terminos
    assert chk[b.id].evidence == []
    assert fu.rules_step(session, 10, date(2026, 10, 19), search=search, pause=0, govs=GOV)["checked"] == 0


def test_rules_step_boe_down_is_retried_and_data_target_decides(session):
    _promise(session, "Aprobaremos una ley de vivienda y alquiler para todos.")

    def down(terms, since, until):
        raise httpx.HTTPError("boe caido")

    assert fu.rules_step(session, 10, date(2026, 10, 19), search=down, pause=0, govs=GOV)["errors"] == 1
    assert session.scalars(select(PromiseCheck)).first() is None  # no se guarda nada: vuelve a intentarse

    p = _promise(session, "Bajaremos la inflación al 2 % durante la legislatura.", page=9)
    obs = SimpleNamespace(value=2.9, period="2026-09", source="INE", label="IPC", url="https://ine.es/ipc")
    verifier = SimpleNamespace(observation=lambda ind, geo: obs if ind == "inflacion" else None)
    out = fu.rules_step(
        session, 10, date(2026, 10, 19), search=lambda *a: [], verifier=verifier, pause=0, govs=GOV
    )
    assert out["by_data"] == 1
    data = session.scalars(select(PromiseCheck).where(PromiseCheck.method == fu.METHOD_DATA)).one()
    assert data.promise_id == p.id and data.status == "no-cumplida"  # el Gobierno ya no esta y 2,9 > 2
    assert "2.9 %" in data.explanation and data.evidence[0]["url"] == "https://ine.es/ipc"


class FakeAI:
    def __init__(self, answers=None, fail=False):
        self.calls = []
        self.answers = answers or {}
        self.fail = fail

    def structured(self, system, user, schema):
        self.calls.append(user)
        if self.fail:
            raise AIError("rechazo")
        items = [{"id": pid, **ans} for pid, ans in self.answers.items() if f"Promesa {pid} " in user]
        return AIResult(data={"items": items}, model="m", usage={"input_tokens": 100, "output_tokens": 20})


def _with_candidates(session, n):
    out = []
    for i in range(n):
        p = _promise(session, f"Aprobaremos una ley de vivienda numero {i} con alquiler limitado.")
        session.add(
            PromiseCheck(
                promise_id=p.id,
                method=fu.METHOD_CANDIDATES,
                status="sin-datos",
                explanation="x",
                evidence=[
                    {
                        "source": "BOE",
                        "id": f"BOE-A-2024-{i}",
                        "label": "Ley de vivienda",
                        "url": "u",
                        "period": "2024-05-01",
                        "rank": "Ley",
                        "hits": 2 + i % 2,
                    }
                ],
            )
        )
        out.append(p)
    session.flush()
    return out


def test_ai_only_for_what_code_did_not_decide_in_capped_batches(session):
    ps = _with_candidates(session, 5)
    session.add(
        PromiseCheck(
            promise_id=ps[0].id, method=fu.METHOD_DATA, status="cumplida", explanation="x", evidence=[]
        )
    )  # ya decidida por el dato: no gasta IA
    session.flush()
    queue = [p.id for p, _ in fu.ai_queue(session, GOV)]
    assert ps[0].id not in queue and len(queue) == 4
    assert queue[:2] == [ps[1].id, ps[3].id]  # primero las de mas terminos en comun
    ai = FakeAI(
        {
            ps[1].id: {"status": "cumplida", "norms": ["BOE-A-2024-1"], "explanation": "La ley 1 lo regula."},
            ps[3].id: {"status": "parcial", "norms": ["BOE-A-2099-9"], "explanation": "Inventada."},
        }
    )
    out = fu.ai_step(session, ai, max_calls=1, batch_size=2, govs=GOV)
    assert out == {"calls": 1, "proposals": 2, "input_tokens": 100, "output_tokens": 20, "errors": 0}
    props = {
        c.promise_id: c
        for c in session.scalars(select(PromiseCheck).where(PromiseCheck.method == fu.PENDING))
    }
    assert props[ps[1].id].status == "cumplida" and props[ps[1].id].evidence[0]["id"] == "BOE-A-2024-1"
    # Una norma fuera de la lista no vale: sin cita valida, "sin dato comprobable".
    assert props[ps[3].id].status == "sin-datos" and props[ps[3].id].evidence == []
    assert "Gobierno de prueba" in ai.calls[0] and "BOE-A-2024-1" in ai.calls[0]
    # Lo propuesto no vuelve a la cola; lo que falta, si, hasta el tope de llamadas.
    assert {p.id for p, _ in fu.ai_queue(session, GOV)} == {ps[2].id, ps[4].id}
    failing = FakeAI(fail=True)
    assert fu.ai_step(session, failing, max_calls=5, batch_size=1, govs=GOV)["errors"] == 1
    assert len(failing.calls) == 1  # al primer error se para


def test_review_publishes_only_approved_proposals(session):
    p = _with_candidates(session, 1)[0]
    chk = PromiseCheck(
        promise_id=p.id,
        method=fu.PENDING,
        status="cumplida",
        explanation="La ley lo regula.",
        evidence=[{"id": "BOE-A-2024-0", "url": "u"}],
    )
    session.add(chk)
    session.flush()
    fu.review(session, chk.id, True, "ana")
    assert chk.method == fu.METHOD_AI and "Revisado por ana" in chk.explanation
    with pytest.raises(ValueError):
        fu.review(session, chk.id, False, "ana")  # ya no esta pendiente
    assert fu.pending(session) == []


def test_run_uses_ai_only_with_a_client_and_budget(session):
    _promise(session, "Aprobaremos una ley de vivienda que limite el alquiler.")
    settings = Settings(database_url="sqlite://", promises_check_per_run=5, promises_ai_max_calls=1)
    search = lambda terms, since, until: [_norm(7, "Ley de vivienda y alquiler")]  # noqa: E731
    out = fu.run(session, settings, ai=None, today=date(2026, 10, 19), search=search, pause=0)
    assert "ai" not in out and out["rules"]["with_candidates"] == 1
    ai = FakeAI()
    out = fu.run(
        session, Settings(database_url="sqlite://", promises_ai_max_calls=0), ai=ai, search=search, pause=0
    )
    assert "ai" not in out and ai.calls == []  # tope 0: ni una llamada


def test_pages_explain_asymmetry_and_show_only_reviewed(engine, session, monkeypatch):
    monkeypatch.setattr(fu, "governments", lambda: GOV)
    kept = _promise(session, "Aprobaremos una ley de vivienda que limite el alquiler.", page=45)
    waiting = _promise(session, "Crearemos un banco publico de inversion.", page=12)
    other = _promise(session, "Reduciremos la jornada laboral a 37,5 horas.", page=7)
    for p in (kept, waiting, other):
        session.add(
            PromiseCheck(
                promise_id=p.id, method=fu.METHOD_CANDIDATES, status="sin-datos", explanation="x", evidence=[]
            )
        )
    session.add(
        PromiseCheck(
            promise_id=kept.id,
            method=fu.METHOD_AI,
            status="cumplida",
            explanation="La Ley 12/2023 limita el alquiler en zonas tensionadas.",
            evidence=[
                {
                    "source": "BOE",
                    "id": "BOE-A-2023-12203",
                    "label": "Ley 12/2023",
                    "url": "https://www.boe.es/buscar/act.php?id=BOE-A-2023-12203",
                    "period": "2023-05-25",
                    "rank": "Ley",
                }
            ],
        )
    )
    pend = PromiseCheck(
        promise_id=waiting.id,
        method=fu.PENDING,
        status="cumplida",
        explanation="Sin revisar.",
        evidence=[{"id": "BOE-A-2024-5", "url": "u", "label": "x"}],
    )
    session.add(pend)
    session.commit()
    today = datetime.now(UTC).date()
    poll = today + timedelta(days=20)
    reg = {
        "elections": [
            {
                "country": "ES",
                "kind": "generales",
                "date": str(poll),
                "convened": str(today - timedelta(days=5)),
                "source": {"label": "Decreto", "url": "https://www.boe.es/y"},
            }
        ]
    }
    settings = Settings(database_url="sqlite://", admin_password="secreto")
    client = TestClient(create_app(settings, engine=engine, elections=cal.Calendar(0, registry_raw=reg)))
    page = client.get(f"/elecciones/es-generales-{poll.isoformat()}").text
    assert "Lo prometido y lo hecho" in page and "Solo se mide a quien gobernó: Gobierno de prueba" in page
    assert "Cumplida 1" in page and "sin dato comprobable 2" in page and "revisadas 3 de 3" in page
    assert "BOE-A-2023-12203" in page and "análisis asistido por IA, revisado" in page
    assert "Sin revisar." not in page and "BOE-A-2024-5" not in page  # pendiente: no se publica
    assert "mintió" not in page
    lst = client.get(f"/elecciones/es-generales-{poll.isoformat()}/promesas?partido=sumar&anio=2023").text
    assert "BOE-A-2023-12203" in lst and "Sin revisar." not in lst

    assert client.get("/admin").status_code == 401
    adm = client.get("/admin", auth=("admin", "secreto")).text
    assert "Sin revisar." in adm and f"/admin/promesa/{pend.id}/aprobar" in adm
    csrf = adm.split('name="csrf" value="')[1].split('"')[0]
    r = client.post(f"/admin/promesa/{pend.id}/aprobar", data={"csrf": "malo"}, auth=("admin", "secreto"))
    assert r.status_code == 403
    r = client.post(
        f"/admin/promesa/{pend.id}/aprobar",
        data={"csrf": csrf},
        auth=("admin", "secreto"),
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert (
        client.post(
            f"/admin/promesa/{pend.id}/rechazar", data={"csrf": csrf}, auth=("admin", "secreto")
        ).status_code
        == 409
    )
    page = client.get(f"/elecciones/es-generales-{poll.isoformat()}").text
    assert "Cumplida 2" in page and "BOE-A-2024-5" in page


def test_ai_without_credit_saves_nothing_and_stops(session):
    ps = _with_candidates(session, 25)

    class NoCredit:
        calls = 0

        def structured(self, system, user, schema):
            NoCredit.calls += 1
            raise RuntimeError("Your credit balance is too low to access the Anthropic API.")

    out = fu.ai_step(session, NoCredit(), max_calls=5, batch_size=10, govs=GOV)
    assert NoCredit.calls == 1 and out["errors"] == 1 and out["proposals"] == 0
    assert "credit balance" in out["last_error"]
    ai_rows = select(PromiseCheck).where(PromiseCheck.method.startswith(fu.METHOD_AI))
    assert session.scalars(ai_rows).all() == []
    assert len(fu.ai_queue(session, GOV)) == len(ps)  # todo sigue en la cola para cuando vuelva el credito
