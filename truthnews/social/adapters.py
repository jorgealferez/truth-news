"""Adaptadores de envio: Bluesky (app password), Mastodon (token), Telegram (bot) y X (API v2).

Solo usan `httpx`; el cliente se inyecta para poder probarlos con un transporte simulado. Cada `send`
devuelve (id externo, URL publica) o lanza `SendError` con el motivo que da la red (sin credenciales).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

TIMEOUT = 30.0


class SendError(Exception):
    pass


def _check(resp: httpx.Response, what: str) -> dict:
    if resp.status_code >= 400:
        raise SendError(f"{what}: HTTP {resp.status_code} {resp.text[:300]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise SendError(f"{what}: respuesta no JSON") from exc


class Bluesky:
    """AT Protocol: sesion con app password, imagen como blob y tarjeta de enlace (`embed.external`)."""

    def __init__(self, creds: dict[str, str], client: httpx.Client, pds: str = "https://bsky.social"):
        self.handle, self.password = creds["BLUESKY_HANDLE"], creds["BLUESKY_APP_PASSWORD"]
        self.client, self.pds = client, pds.rstrip("/")

    def send(self, text: str, link: str, image: bytes | None, title: str) -> tuple[str, str]:
        xrpc = f"{self.pds}/xrpc"
        session = _check(
            self.client.post(
                f"{xrpc}/com.atproto.server.createSession",
                json={"identifier": self.handle, "password": self.password},
            ),
            "bluesky sesion",
        )
        auth = {"Authorization": f"Bearer {session['accessJwt']}"}
        external = {"uri": link, "title": title[:300], "description": ""}
        if image:
            blob = _check(
                self.client.post(
                    f"{xrpc}/com.atproto.repo.uploadBlob",
                    content=image,
                    headers={**auth, "Content-Type": "image/png"},
                ),
                "bluesky imagen",
            )
            external["thumb"] = blob["blob"]
        record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "langs": ["es"],
            "facets": link_facets(text),
            "embed": {"$type": "app.bsky.embed.external", "external": external},
        }
        created = _check(
            self.client.post(
                f"{xrpc}/com.atproto.repo.createRecord",
                json={"repo": session["did"], "collection": "app.bsky.feed.post", "record": record},
                headers=auth,
            ),
            "bluesky publicacion",
        )
        rkey = created["uri"].rsplit("/", 1)[-1]
        return created["uri"], f"https://bsky.app/profile/{self.handle}/post/{rkey}"


def link_facets(text: str) -> list[dict]:
    """Facetas de enlace de Bluesky: los offsets van en bytes UTF-8, no en caracteres."""
    facets, start = [], 0
    raw = text.encode("utf-8")
    for word in text.split():
        if not word.startswith(("http://", "https://")):
            continue
        b = word.encode("utf-8")
        start = raw.index(b, start)
        facets.append(
            {
                "index": {"byteStart": start, "byteEnd": start + len(b)},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": word}],
            }
        )
        start += len(b)
    return facets


class Mastodon:
    def __init__(self, creds: dict[str, str], client: httpx.Client):
        self.base, self.client = creds["MASTODON_URL"].rstrip("/"), client
        self.auth = {"Authorization": f"Bearer {creds['MASTODON_TOKEN']}"}

    def send(self, text: str, link: str, image: bytes | None, title: str) -> tuple[str, str]:
        data: dict = {"status": text, "language": "es", "visibility": "public"}
        if image:
            media = _check(
                self.client.post(
                    f"{self.base}/api/v2/media",
                    files={"file": ("nosmienten.png", image, "image/png")},
                    data={"description": title[:1400]},
                    headers=self.auth,
                ),
                "mastodon imagen",
            )
            data["media_ids[]"] = [media["id"]]
        status = _check(
            self.client.post(
                f"{self.base}/api/v1/statuses",
                data=data,
                headers={**self.auth, "Idempotency-Key": hashlib.sha256(text.encode()).hexdigest()},
            ),
            "mastodon publicacion",
        )
        return str(status["id"]), status.get("url") or ""


class Telegram:
    def __init__(self, creds: dict[str, str], client: httpx.Client):
        self.chat, self.client = creds["TELEGRAM_CHAT_ID"], client
        self.api = f"https://api.telegram.org/bot{creds['TELEGRAM_BOT_TOKEN']}"

    def send(self, text: str, link: str, image: bytes | None, title: str) -> tuple[str, str]:
        if image:
            resp = self.client.post(
                f"{self.api}/sendPhoto",
                data={"chat_id": self.chat, "caption": text},
                files={"photo": ("nosmienten.png", image, "image/png")},
            )
        else:
            resp = self.client.post(f"{self.api}/sendMessage", data={"chat_id": self.chat, "text": text})
        body = _check(resp, "telegram")
        if not body.get("ok"):
            raise SendError(f"telegram: {body.get('description', 'sin detalle')}")
        msg_id = str(body["result"]["message_id"])
        url = f"https://t.me/{self.chat[1:]}/{msg_id}" if self.chat.startswith("@") else ""
        return msg_id, url


class X:
    """API v2 `POST /2/tweets` con OAuth 1.0a de usuario. La imagen llega por la tarjeta del enlace
    (`og:image` de la historia), sin subir medios: menos permisos y menos puntos de fallo."""

    URL = "https://api.x.com/2/tweets"

    def __init__(self, creds: dict[str, str], client: httpx.Client):
        self.creds, self.client = creds, client

    def send(self, text: str, link: str, image: bytes | None, title: str) -> tuple[str, str]:
        headers = {"Authorization": oauth1_header("POST", self.URL, self.creds)}
        body = _check(self.client.post(self.URL, json={"text": text}, headers=headers), "x")
        tweet_id = str(body["data"]["id"])
        return tweet_id, f"https://x.com/i/web/status/{tweet_id}"


def _pct(value: str) -> str:
    return quote(value, safe="~-._")


def oauth1_header(
    method: str, url: str, creds: dict[str, str], nonce: str | None = None, ts: str | None = None
) -> str:
    """Cabecera OAuth 1.0a HMAC-SHA1 (RFC 5849). Un cuerpo JSON no entra en la firma."""
    params = {
        "oauth_consumer_key": creds["X_API_KEY"],
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": ts or str(int(time.time())),
        "oauth_token": creds["X_ACCESS_TOKEN"],
        "oauth_version": "1.0",
    }
    base = "&".join(
        [method.upper(), _pct(url), _pct("&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(params.items())))]
    )
    key = f"{_pct(creds['X_API_SECRET'])}&{_pct(creds['X_ACCESS_SECRET'])}"
    params["oauth_signature"] = base64.b64encode(
        hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    ).decode()
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(params.items()))


ADAPTERS = {"bluesky": Bluesky, "mastodon": Mastodon, "telegram": Telegram, "x": X}


def make_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": "nosmienten.com/redes"})
