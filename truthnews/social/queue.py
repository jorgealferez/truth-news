"""Paso de redes del worker: elige, compone, registra y (con credenciales) envia.

Orden por red: primero reintenta lo que fallo (hasta `MAX_ATTEMPTS`), despues anade lo nuevo mas
relevante hasta el cupo del dia y el tope por ciclo. Cada pieza se confirma en la base antes y despues
de enviarla: un redespliegue a mitad de ciclo no puede provocar un duplicado (la fila ya existe y la
restriccion unica de ADR 0018 lo impide). Si una red falla, se deja de enviar a esa red hasta el
siguiente ciclo.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from truthnews.models import SOCIAL_NETWORKS, SocialPost, utcnow
from truthnews.social import adapters
from truthnews.social.compose import fit
from truthnews.social.config import SocialSettings
from truthnews.social.images import image_for
from truthnews.social.select import Candidate, candidates

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


def _adapter(network: str, creds: dict[str, str], settings: SocialSettings, client: httpx.Client):
    if network == "bluesky":
        return adapters.Bluesky(creds, client, settings.env.get("BLUESKY_PDS") or "https://bsky.social")
    return adapters.ADAPTERS[network](creds, client)


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
    by_key = {(c.kind, c.ref_id): c for c in found}
    pictures: dict[int | None, tuple[bytes, str]] = {}

    def picture(c: Candidate) -> tuple[bytes, str]:
        if c.image_story_id not in pictures:
            pictures[c.image_story_id] = image_for(session, c.image_story_id, site_url, c.language)
        return pictures[c.image_story_id]

    own_client = client is None
    client = client or adapters.make_client()
    summary: dict = {"candidatas": len(found)}
    try:
        for network in SOCIAL_NETWORKS:
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
            for c in [c for c in found if (c.kind, c.ref_id) not in done][: max(room, 0)]:
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
