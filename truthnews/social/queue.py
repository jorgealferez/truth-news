"""Paso de redes del worker: elige, compone, registra y (con credenciales) envia.

Orden por red: primero reintenta lo que fallo (hasta `MAX_ATTEMPTS`), despues anade lo nuevo mas
relevante hasta el cupo del dia y el tope por ciclo. Cada pieza se confirma en la base antes y despues
de enviarla: un redespliegue a mitad de ciclo no puede provocar un duplicado (la fila ya existe y la
restriccion unica de ADR 0018 lo impide). Si una red falla, se deja de enviar a esa red hasta el
siguiente ciclo.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from truthnews.models import SOCIAL_NETWORKS, SOCIAL_NETWORKS_EN, SocialPost, utcnow
from truthnews.social import adapters, balance
from truthnews.social.compose import fit
from truthnews.social.config import SocialSettings, base_network
from truthnews.social.images import image_for
from truthnews.social.select import Candidate, candidates, stories_en

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


def _adapter(network: str, creds: dict[str, str], settings: SocialSettings, client: httpx.Client):
    base = base_network(network)
    if base == "bluesky":
        return adapters.Bluesky(creds, client, settings.env.get("BLUESKY_PDS") or "https://bsky.social")
    return adapters.ADAPTERS[base](creds, client)


def _deliver(session: Session, post: SocialPost, adapter, image: bytes | None, title: str) -> bool:
    post.attempts += 1
    try:
        post.external_id, post.external_url = adapter.send(post.text, post.link, image, title)
    except (adapters.SendError, httpx.HTTPError, KeyError) as exc:
        post.status, post.error = "error", str(exc)[:1000]
        log.warning("redes: %s %s/%s fallo: %s", post.network, post.kind, post.ref_id, post.error)
        session.commit()
        return False
    post.status, post.error, post.sent_at = "enviado", None, utcnow()
    log.info("redes: %s %s/%s enviado %s", post.network, post.kind, post.ref_id, post.external_url)
    session.commit()
    return True


def run(
    session: Session,
    site_url: str,
    settings: SocialSettings | None = None,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    lang: str = "es",
) -> dict:
    settings = settings or SocialSettings()
    if not settings.enabled:
        return {"activo": False}
    now = now or utcnow()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    found = candidates(session, site_url, settings.min_score, settings.window_hours, lang, now)
    equilibrium = balance.measure(
        session, now
    )  # ADR 0043: nadie acapara lo negativo sin que los datos lo digan
    found = balance.diversify(session, found, equilibrium["marcados"])
    since = now - timedelta(hours=settings.window_hours)
    found_en = stories_en(session, site_url.rstrip("/"), since, settings.min_score)
    by_lang = {
        "es": {(c.kind, c.ref_id): c for c in found},
        "en": {(c.kind, c.ref_id): c for c in found_en},
    }
    pictures: dict[tuple, tuple[bytes, str]] = {}

    def picture(c: Candidate) -> tuple[bytes, str]:
        title = c.draft.headline if c.language == "en" else None
        key = (c.image_story_id, c.language, title)
        if key not in pictures:
            pictures[key] = image_for(session, c.image_story_id, site_url, c.language, title)
        return pictures[key]

    own_client = client is None
    client = client or adapters.make_client()
    summary: dict = {
        "candidatas": len(found),
        "candidatas_en": len(found_en),
        "equilibrio": {k: equilibrium[k] for k in ("piezas", "negativas", "por_actor", "marcados")},
    }
    try:
        for network in SOCIAL_NETWORKS + SOCIAL_NETWORKS_EN:
            english = network in SOCIAL_NETWORKS_EN
            pool = found_en if english else found
            by_key = by_lang["en" if english else "es"]
            creds = settings.credentials(network)
            adapter = _adapter(network, creds, settings, client) if creds else None
            stats = {"modo": "envio" if adapter else "prueba", "nuevas": 0, "enviadas": 0, "errores": 0}
            summary[network] = stats
            healthy = True
            if adapter:
                for post in list(
                    session.scalars(
                        select(SocialPost).where(
                            SocialPost.network == network,
                            SocialPost.status == "error",
                            SocialPost.attempts < MAX_ATTEMPTS,
                        )
                    )
                ):
                    c = by_key.get((post.kind, post.ref_id))
                    image = picture(c)[0] if c else None
                    ok = _deliver(session, post, adapter, image, c.draft.headline if c else post.text)
                    stats["enviadas" if ok else "errores"] += 1
                    if not ok:
                        healthy = False
                        break
            used = session.scalar(
                select(func.count())
                .select_from(SocialPost)
                .where(SocialPost.network == network, SocialPost.created_at >= day)
            )
            room = min(settings.quota.get(network, 0) - used, settings.per_cycle)
            done = set(
                session.execute(
                    select(SocialPost.kind, SocialPost.ref_id).where(SocialPost.network == network)
                ).all()
            )
            for c in [c for c in pool if (c.kind, c.ref_id) not in done][: max(room, 0)]:
                if not healthy:
                    break
                image, image_url = picture(c)
                post = SocialPost(
                    network=network,
                    kind=c.kind,
                    ref_id=c.ref_id,
                    language=c.language,
                    score=c.score,
                    text=fit(network, c.draft),
                    link=c.draft.url,
                    image_url=image_url,
                    status="prueba",
                    attempts=0,
                    created_at=now,
                )
                session.add(post)
                session.commit()  # registrada antes de enviar: nunca un duplicado
                stats["nuevas"] += 1
                if adapter:
                    ok = _deliver(session, post, adapter, image, c.draft.headline)
                    stats["enviadas" if ok else "errores"] += 1
                    healthy = ok
    finally:
        if own_client:
            client.close()
    return summary


def status(session: Session, settings: SocialSettings | None = None, now: datetime | None = None) -> dict:
    """Resumen para el panel: modo por red (sin mostrar credenciales), cupo de hoy y ultimas piezas."""
    settings = settings or SocialSettings()
    day = (now or utcnow()).replace(hour=0, minute=0, second=0, microsecond=0)
    today = dict(
        session.execute(
            select(SocialPost.network, func.count())
            .where(SocialPost.created_at >= day)
            .group_by(SocialPost.network)
        ).all()
    )
    networks = [
        {
            "network": n,
            "mode": "envio" if settings.credentials(n) else "prueba",
            "today": today.get(n, 0),
            "quota": settings.quota.get(n, 0),
        }
        for n in SOCIAL_NETWORKS + SOCIAL_NETWORKS_EN
    ]
    recent = list(session.scalars(select(SocialPost).order_by(SocialPost.id.desc()).limit(40)))
    return {
        "enabled": settings.enabled,
        "networks": networks,
        "recent": recent,
        "balance": balance.measure(session, now),
    }
