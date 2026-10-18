"""Cliente HTTP educado: User-Agent propio, robots.txt cacheado por host y ritmo por dominio."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx


class PoliteClient:
    def __init__(
        self,
        user_agent: str,
        per_domain_delay: float = 1.0,
        timeout: float = 20.0,
        concurrency: int = 16,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.user_agent = user_agent
        self.per_domain_delay = per_domain_delay
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent, "Accept-Language": "es,en;q=0.8"},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self._robots: dict[str, RobotFileParser | None] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._last_hit: dict[str, float] = {}
        self._sem = asyncio.Semaphore(concurrency)
        self.robots_blocked = 0

    async def __aenter__(self) -> PoliteClient:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _origin(url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    async def allowed(self, url: str) -> bool:
        origin = self._origin(url)
        lock = self._robots_locks.setdefault(origin, asyncio.Lock())
        async with lock:
            if origin not in self._robots:
                self._robots[origin] = await self._fetch_robots(origin)
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    async def _fetch_robots(self, origin: str) -> RobotFileParser | None:
        try:
            resp = await self._client.get(origin + "/robots.txt")
        except httpx.HTTPError:
            return None  # sin robots.txt accesible: se aplica el ritmo, no se presume prohibicion
        # RFC 9309: 4xx = sin restricciones; 5xx = inaccesible, se asume prohibicion total.
        if 400 <= resp.status_code < 500:
            return None
        parser = RobotFileParser()
        if resp.status_code >= 500:
            parser.disallow_all = True
            return parser
        parser.parse(resp.text.splitlines())
        return parser

    async def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        lock = self._domain_locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last_hit.get(host, 0) + self.per_domain_delay - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_hit[host] = time.monotonic()

    async def get(self, url: str, headers: dict | None = None) -> httpx.Response | None:
        """GET respetando robots.txt. Devuelve None si robots.txt lo prohibe."""
        if not await self.allowed(url):
            self.robots_blocked += 1
            return None
        async with self._sem:
            await self._throttle(url)
            return await self._client.get(url, headers=headers or {})
