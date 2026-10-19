"""Paginas en otro idioma bajo su prefijo: /en/historia/12-slug sirve la misma ruta en ingles.

Un middleware ASGI quita el prefijo antes de enrutar (las rutas no cambian), deja el idioma en
`request.state.lang_prefix` y, a la vuelta, anade el prefijo a los enlaces internos del HTML y a las
redirecciones, para que quien navega en ingles siga en ingles y cada idioma tenga su URL indexable.
"""

from __future__ import annotations

import re

# Rutas que no cambian con el idioma: ficheros, feeds, panel y API.
SHARED = (
    "/static/",
    "/og/",
    "/favicon",
    "/site.webmanifest",
    "/robots.txt",
    "/sitemap",
    "/rss.xml",
    "/idioma/",
    "/admin",
    "/api/",
    "/healthz",
)
_TAG = re.compile(r"<[a-zA-Z][^>]*>")
_ATTR = re.compile(r'\b(href|action|content)="([^"]*)"')


def localize(path: str, prefix: str) -> str:
    """'/tema/3' -> '/en/tema/3'; deja igual lo compartido, lo externo y lo ya prefijado."""
    if not path.startswith("/") or path.startswith("//") or path.startswith(SHARED):
        return path
    if path == f"/{prefix}" or path.startswith(f"/{prefix}/"):
        return path
    return f"/{prefix}" + ("" if path == "/" else path)


def rewrite_html(html: str, prefix: str, site_url: str) -> str:
    """Prefija los enlaces internos (relativos o absolutos al sitio) salvo los alternos de idioma."""

    def attr(m: re.Match) -> str:
        name, value = m.group(1), m.group(2)
        if value.startswith(site_url + "/") or value == site_url:
            rest = value[len(site_url) :] or "/"
            return f'{name}="{site_url}{localize(rest, prefix)}"'
        if name == "content":  # en <meta> solo se tocan URLs absolutas del sitio
            return m.group(0)
        return f'{name}="{localize(value, prefix)}"'

    def tag(m: re.Match) -> str:
        t = m.group(0)
        return t if "hreflang=" in t else _ATTR.sub(attr, t)

    return _TAG.sub(tag, html)


class LangPrefix:
    def __init__(self, app, prefixes: list[str], site_url: str):
        self.app, self.prefixes, self.site_url = app, prefixes, site_url.rstrip("/")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        prefix = next((p for p in self.prefixes if path == f"/{p}" or path.startswith(f"/{p}/")), None)
        if prefix is None:
            return await self.app(scope, receive, send)
        inner = path[len(prefix) + 1 :] or "/"
        if inner.startswith(SHARED):  # /en/static/... no existe: 404 en vez de duplicar recursos
            inner = "/__no_such_page__"
        scope = {**scope, "path": inner, "raw_path": inner.encode(), "state": {**scope.get("state", {})}}
        scope["state"]["lang_prefix"] = prefix
        start: dict = {}
        chunks: list[bytes] = []

        async def capture(message):
            if message["type"] == "http.response.start":
                start.update(message)
                return
            if message["type"] != "http.response.body":  # extensiones (p. ej. debug de plantillas)
                return await send(message)
            chunks.append(message.get("body", b""))
            if message.get("more_body"):
                return
            headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
            body = b"".join(chunks)
            out = []
            for k, v in headers:
                if k.lower() == b"location":
                    v = localize(v.decode("latin-1"), prefix).encode("latin-1")
                out.append((k, v))
            ctype = dict((k.lower(), v) for k, v in headers).get(b"content-type", b"")
            if ctype.startswith(b"text/html"):
                body = rewrite_html(body.decode("utf-8"), prefix, self.site_url).encode("utf-8")
            out.append((b"content-length", str(len(body)).encode()))
            await send({**start, "headers": out})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, capture)
