"""Small IMDb client for exact title and episode ratings."""

import asyncio
import logging
import time

import aiohttp


API_BASE = "https://api.graphql.imdb.com/"
CACHE_TTL_SECONDS = 6 * 60 * 60
NEGATIVE_CACHE_TTL_SECONDS = 60 * 60

log = logging.getLogger("simkl-bot")


class ImdbClient:
    def __init__(self):
        self._session: aiohttp.ClientSession | None = None
        self._cache: dict[str, tuple[float, float | None]] = {}
        self._inflight: dict[str, asyncio.Task] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                headers={
                    "User-Agent": "simkl-tracker-bot/1.0.0",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _fetch_rating(self, imdb_id: str) -> float | None:
        session = await self._get_session()
        query = """
        query TitleRating($id: ID!) {
          title(id: $id) {
            ratingsSummary {
              aggregateRating
            }
          }
        }
        """
        try:
            async with session.post(
                API_BASE,
                json={"query": query, "variables": {"id": imdb_id}},
            ) as resp:
                if resp.status != 200:
                    log.warning(
                        "IMDb rating request returned HTTP %s for %s.",
                        resp.status,
                        imdb_id,
                    )
                    return None
                data = await resp.json()
                if data.get("errors"):
                    log.warning(
                        "IMDb rating request returned GraphQL errors for %s: %s",
                        imdb_id,
                        data["errors"],
                    )
                    return None
                value = (
                    ((data.get("data") or {}).get("title") or {})
                    .get("ratingsSummary") or {}
                ).get("aggregateRating")
                try:
                    return float(value) if value is not None else None
                except (TypeError, ValueError):
                    return None
        except (aiohttp.ClientError, TimeoutError):
            log.warning("IMDb rating request failed for %s.", imdb_id, exc_info=True)
            return None

    async def get_rating(self, imdb_id: str | None) -> float | None:
        if not imdb_id or not str(imdb_id).startswith("tt"):
            return None
        imdb_id = str(imdb_id)
        now = time.monotonic()
        cached = self._cache.get(imdb_id)
        if cached is not None:
            expires_at, value = cached
            if now < expires_at:
                return value
            self._cache.pop(imdb_id, None)

        task = self._inflight.get(imdb_id)
        if task is None:
            task = asyncio.create_task(self._fetch_rating(imdb_id))
            self._inflight[imdb_id] = task
        try:
            value = await task
        finally:
            if self._inflight.get(imdb_id) is task:
                self._inflight.pop(imdb_id, None)

        ttl = CACHE_TTL_SECONDS if value is not None else NEGATIVE_CACHE_TTL_SECONDS
        self._cache[imdb_id] = (time.monotonic() + ttl, value)
        return value
