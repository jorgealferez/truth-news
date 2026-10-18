"""Dossier verificado de un tema y pieza propia con comprobacion de fundamento (ADR 0007)."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from truthnews.ai.client import AIClient
from truthnews.ai.prompts import WRITER_SYSTEM
from truthnews.ai.topics import topic_articles
from truthnews.analysis.compare import compare
from truthnews.analysis.verify import Verifier
from truthnews.models import Claim, Piece, Topic, Verification
from truthnews.registry import t

# Topes del dossier: acotan coste y contexto en temas con cientos de articulos.
MAX_STORIES_PER_TOPIC = 15
MAX_ARTICLES_PER_STORY = 12
CONTEXT_INDICATORS = ("paro", "inflacion", "pib_trimestral", "deuda_publica", "precio_vivienda")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def piece_schema() -> dict:
    s, arr = {"type": "string"}, lambda item: {"type": "array", "items": item}

    def obj(props: dict) -> dict:
        return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}

    return obj(
        {
            "titular": s,
            "entradilla": s,
            "que_dice_cada_medio": arr(obj({"medio_slug": s, "sintesis": s, "enfoque": s})),
            "coincidencias": arr(s),
            "diferencias": arr(obj({"aspecto": s, "detalle": s})),
            "datos": arr(obj({"dato": s, "fuente": s})),
            "valoracion": obj(
                {
                    "conclusion": s,
                    "confianza": {"type": "string", "enum": ["alta", "media", "baja"]},
                    "lo_que_no_sabemos": arr(s),
                }
            ),
            "analisis": arr(obj({"subtitulo": s, "parrafos": arr(s)})),
            "opinion": obj({"titulo": s, "parrafos": arr(s)}),
            "historias_citadas": arr({"type": "integer"}),
        }
    )


def build_dossier(session: Session, topic: Topic, verifier: Verifier | None = None) -> dict:
    arts = topic_articles(session, topic)
    by_story = defaultdict(list)
    for a in arts:
        by_story[a.story_id].append(a)
    stories = []
    ranked = sorted(by_story.items(), key=lambda kv: -len({a.outlet_id for a in kv[1]}))[
        :MAX_STORIES_PER_TOPIC
    ]
    by_story = dict(ranked)
    for sid, sarts in by_story.items():
        comp = compare(sarts)
        # Un articulo por medio (el primero) y como mucho MAX_ARTICLES_PER_STORY medios.
        seen: set[int] = set()
        sarts = [a for a in sarts if not (a.outlet_id in seen or seen.add(a.outlet_id))][
            :MAX_ARTICLES_PER_STORY
        ]
        stories.append(
            {
                "id": sid,
                "titular": sarts[0].story.title if sarts[0].story else sarts[0].title,
                "articulos": [
                    {
                        "medio_slug": a.outlet.slug,
                        "medio": a.outlet.name,
                        "ambito": t("es", "scope_" + a.outlet.scope),
                        "propiedad": a.outlet.owner or "",
                        "hora_utc": a.published_at.strftime("%d/%m %H:%M"),
                        "titular": a.title,
                        "resumen": (a.summary or "")[:500],
                        "arranque": (a.content_text or "")[:1200],
                    }
                    for a in sarts
                ],
                "cifras_distintas_segun_medio": {
                    noun: [
                        {"medio": f.outlet, "valor": f.value, "hora": f.published_at.strftime("%d/%m %H:%M")}
                        for f in figs
                    ]
                    for noun, figs in comp.disputes.items()
                },
                "en_lo_que_coinciden": comp.consensus,
                "omisiones": comp.omissions,
                "lenguaje_valorativo": comp.loaded,
            }
        )
    claims = session.scalars(
        select(Claim)
        .options(joinedload(Claim.verification).joinedload(Verification.evidence), joinedload(Claim.outlet))
        .where(Claim.story_id.in_(list(by_story) or [-1]))
    ).unique()
    verified = [
        {
            "medio": c.outlet.name,
            "afirmacion": c.text,
            "veredicto": c.verification.verdict,
            "explicacion": c.verification.explanation,
            "fuentes": [f"{e.source}: {e.label} ({e.period}) {e.url}" for e in c.verification.evidence],
        }
        for c in claims
        if c.verification
    ]
    context = []
    if verifier is not None and topic.category in ("economia", "politica", "sociedad"):
        for ind in CONTEXT_INDICATORS:
            obs = verifier.observation(ind, topic.country)
            if obs is not None and not obs.is_stale():
                context.append(
                    {
                        "indicador": obs.label,
                        "territorio": topic.country,
                        "periodo": obs.period,
                        "valor": obs.value,
                        "fuente": obs.source,
                        "url": obs.url,
                    }
                )
    return {
        "tema": topic.title,
        "categoria": topic.category,
        "pais": topic.country,
        "historias": stories,
        "afirmaciones_verificadas": verified,
        "datos_oficiales_de_contexto": context,
    }


def numbers_in(text: str) -> set[str]:
    out = set()
    for raw in _NUMBER.findall(text):
        n = raw.replace(".", "").replace(",", ".")
        try:
            v = float(n)
        except ValueError:  # pragma: no cover - el regex solo deja numeros
            continue
        out.add(f"{v:g}")
    return out


def check_grounding(output: dict, dossier: dict, story_ids: set[int], slugs: set[str]) -> dict:
    """Cifras, medios e historias del texto generado que no estan en el dossier (vacio = fundamentado)."""
    dossier_numbers = numbers_in(json.dumps(dossier, ensure_ascii=False))
    text = json.dumps({k: v for k, v in output.items() if k != "historias_citadas"}, ensure_ascii=False)
    unsupported = sorted(
        n
        for n in numbers_in(text) - dossier_numbers
        if not (float(n).is_integer() and (float(n) <= 10 or 1990 <= float(n) <= 2035))
    )
    bad_slugs = sorted({m["medio_slug"] for m in output.get("que_dice_cada_medio", [])} - slugs)
    bad_stories = sorted(set(output.get("historias_citadas", [])) - story_ids)
    return {
        "cifras_sin_fuente": unsupported,
        "medios_desconocidos": bad_slugs,
        "historias_desconocidas": bad_stories,
        "ok": not (unsupported or bad_slugs or bad_stories),
    }


def dossier_hash(dossier: dict) -> str:
    return hashlib.sha256(
        json.dumps(dossier, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def write_pieces(
    session: Session, topic: Topic, ai: AIClient, verifier: Verifier | None = None
) -> list[Piece]:
    """Genera (o no, si el dossier no ha cambiado) el analisis y la opinion de un tema."""
    dossier = build_dossier(session, topic, verifier)
    h = dossier_hash(dossier)
    if session.scalars(select(Piece.id).where(Piece.topic_id == topic.id, Piece.input_hash == h)).first():
        return []  # dossier sin cambios: no se paga otra llamada
    user = "DOSSIER (JSON):\n" + json.dumps(dossier, ensure_ascii=False, default=str)
    result = ai.structured(WRITER_SYSTEM, user, piece_schema())
    out = result.data
    story_ids = {s["id"] for s in dossier["historias"]}
    slugs = {a["medio_slug"] for s in dossier["historias"] for a in s["articulos"]}
    grounding = check_grounding(out, dossier, story_ids, slugs)
    status = "publicada" if grounding["ok"] else "revision"
    synthesis = {
        k: out[k]
        for k in (
            "que_dice_cada_medio",
            "coincidencias",
            "diferencias",
            "datos",
            "valoracion",
            "historias_citadas",
        )
    }
    analysis = Piece(
        topic_id=topic.id,
        kind="analisis",
        status=status,
        title=out["titular"][:300],
        dek=out["entradilla"],
        body=out["analisis"],
        synthesis=synthesis,
        grounding=grounding,
        model=result.model,
        input_hash=h,
        usage=result.usage,
    )
    opinion = Piece(
        topic_id=topic.id,
        kind="opinion",
        status=status,
        title=out["opinion"]["titulo"][:300],
        dek=out["valoracion"]["conclusion"],
        body=[{"subtitulo": "", "parrafos": out["opinion"]["parrafos"]}],
        synthesis={"historias_citadas": out["historias_citadas"]},
        grounding=grounding,
        model=result.model,
        input_hash=h,
        usage={},
    )
    session.add_all([analysis, opinion])
    session.flush()
    return [analysis, opinion]
