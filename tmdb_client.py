"""
TMDB API client for fetching TV episode stills, episode details,
and movie backdrops.

Uses TMDB's API:
https://developer.themoviedb.org/
"""

import asyncio
import logging

import aiohttp


API_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w780"

log = logging.getLogger("simkl-bot")


class TmdbClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._session: aiohttp.ClientSession | None = None

        # Cache successful and unsuccessful lookups.
        self._episode_cache: dict[
            tuple[int, int, int],
            dict | None,
        ] = {}

        self._movie_backdrop_cache: dict[
            int,
            str | None,
        ] = {}

        self._tv_backdrop_cache: dict[
            int,
            str | None,
        ] = {}

        self._movie_logo_cache: dict[
            int,
            str | None,
        ] = {}

        self._tv_logo_cache: dict[
            int,
            str | None,
        ] = {}

        # Cache TVDB -> TMDB series lookups.
        self._tvdb_series_cache: dict[
            int,
            int | None,
        ] = {}

        # Cache season details.
        self._season_cache: dict[
            tuple[int, int],
            dict | None,
        ] = {}

        # Cache TV series details used by anime fallback resolution.
        self._series_cache: dict[
            int,
            dict | None,
        ] = {}

        # Cache English-localized anime title lookups.
        self._tv_title_cache: dict[
            tuple[int, bool],
            str | None,
        ] = {}

        # Cache the result of the more expensive anime episode resolver.
        self._anime_episode_cache: dict[
            tuple,
            dict | None,
        ] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return the shared HTTP session, creating it if needed."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                headers={
                    "User-Agent": "simkl-tracker-bot/1.0.0",
                    "Accept": "application/json",
                },
            )

        return self._session

    async def close(self) -> None:
        """Close the shared HTTP session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()

        self._session = None

    # ------------------------------------------------------------------
    # Generic GET helper
    # ------------------------------------------------------------------

    async def _get_json(
        self,
        path: str,
        params: dict | None = None,
    ) -> dict | None:
        try:
            session = await self._get_session()

            request_params = {
                "api_key": self.api_key,
            }

            if params:
                request_params.update(params)

            for attempt in range(4):
                async with session.get(
                    path,
                    params=request_params,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()

                    if resp.status != 429 or attempt >= 3:
                        if resp.status == 429:
                            log.warning(
                                "TMDB rate limit reached for %s after %s retries.",
                                path,
                                attempt,
                            )
                        return None

                    retry_after = resp.headers.get("Retry-After")
                    try:
                        delay = float(retry_after)
                    except (TypeError, ValueError):
                        delay = 2 ** attempt

                    delay = min(max(delay, 1.0), 30.0)

                    log.warning(
                        "TMDB rate limit reached for %s; retrying in %.1fs.",
                        path,
                        delay,
                    )
                    await asyncio.sleep(delay)

        except (aiohttp.ClientError, TimeoutError):
            log.warning(
                "TMDB request failed: %s",
                path,
                exc_info=True,
            )
            return None

    # ------------------------------------------------------------------
    # TVDB -> TMDB
    # ------------------------------------------------------------------

    async def find_series_by_tvdb(
        self,
        tvdb_id,
    ) -> int | None:
        """
        Find the TMDB TV series corresponding to a TVDB ID.

        TMDB supports TheTVDB as an external source for TV shows,
        seasons and episodes.
        """

        try:
            tvdb_id = int(tvdb_id)
        except (TypeError, ValueError):
            return None

        if tvdb_id in self._tvdb_series_cache:
            return self._tvdb_series_cache[tvdb_id]

        path = f"{API_BASE}/find/{tvdb_id}"

        data = await self._get_json(
            path,
            {
                "external_source": "tvdb_id",
            },
        )

        if not data:
            self._tvdb_series_cache[tvdb_id] = None
            return None

        results = data.get("tv_results") or []

        if not results:
            self._tvdb_series_cache[tvdb_id] = None
            return None

        series_id = results[0].get("id")

        try:
            series_id = int(series_id)
        except (TypeError, ValueError):
            series_id = None

        self._tvdb_series_cache[tvdb_id] = series_id

        if series_id:
            log.info(
                "Resolved TVDB series %s -> TMDB series %s.",
                tvdb_id,
                series_id,
            )

        return series_id

    # ------------------------------------------------------------------
    # TV episode details
    # ------------------------------------------------------------------

    async def get_episode_details(
        self,
        series_id,
        season_number,
        episode_number,
    ) -> dict | None:
        """
        Return TMDB episode details.

        The returned dict contains useful fields such as:
        - name
        - still_path
        - episode_number
        - season_number

        Returns None when TMDB doesn't contain that episode.
        """

        try:
            series_id = int(series_id)
            season_number = int(season_number)
            episode_number = int(episode_number)
        except (TypeError, ValueError):
            return None

        cache_key = (
            series_id,
            season_number,
            episode_number,
        )

        if cache_key in self._episode_cache:
            return self._episode_cache[cache_key]

        path = (
            f"{API_BASE}/tv/{series_id}/season/"
            f"{season_number}/episode/{episode_number}"
        )

        data = await self._get_json(
            path,
            {
                "language": "en-US",
                "append_to_response": "external_ids",
            },
        )

        if not data:
            log.info(
                "TMDB episode not found: "
                "series=%s season=%s episode=%s",
                series_id,
                season_number,
                episode_number,
            )

            self._episode_cache[cache_key] = None
            return None

        self._episode_cache[cache_key] = data

        return data

    # ------------------------------------------------------------------
    # Episode stills
    # ------------------------------------------------------------------

    async def get_episode_still(
        self,
        series_id,
        season_number,
        episode_number,
    ) -> str | None:
        """
        Return a TMDB episode still URL.

        Uses the episode details endpoint first, because it gives us
        both the episode title and still_path in one request.
        """

        episode = await self.get_episode_details(
            series_id,
            season_number,
            episode_number,
        )

        if not episode:
            return None

        still_path = episode.get("still_path")

        if not still_path:
            return None

        return f"{IMAGE_BASE}{still_path}"

    # ------------------------------------------------------------------
    # Episode title
    # ------------------------------------------------------------------

    async def get_episode_title(
        self,
        series_id,
        season_number,
        episode_number,
    ) -> str | None:
        """Return the TMDB episode title."""

        episode = await self.get_episode_details(
            series_id,
            season_number,
            episode_number,
        )

        if not episode:
            return None

        title = episode.get("name")

        if not title:
            return None

        return str(title)

    # ------------------------------------------------------------------
    # Anime-aware episode lookup
    # ------------------------------------------------------------------

    async def find_anime_episode(
        self,
        series_id,
        tvdb_id,
        season_candidates,
        episode_number,
        episode_title=None,
    ) -> dict | None:
        """
        Try to resolve an anime episode when SIMKL's anime season
        numbering doesn't line up perfectly with TMDB.

        Strategy:

        1. Try the TMDB series ID directly.
        2. Try the TVDB -> TMDB series mapping.
        3. Try the supplied season candidates.
        4. If those fail, inspect TMDB seasons and match by episode
           number/title.

        This avoids assuming that SIMKL/TVDB/TMDB all use identical
        season numbering.
        """

        candidate_series_ids = []

        def add_series_id(value):
            try:
                value = int(value)
            except (TypeError, ValueError):
                return

            if value not in candidate_series_ids:
                candidate_series_ids.append(value)

        # Anime seasons on SIMKL are separate entries, while TMDB often
        # keeps them under one canonical TV series. Prefer the TVDB mapping
        # first because the SIMKL season entry's TMDB ID can resolve to a
        # season-specific/alternate record whose season 1 would otherwise
        # incorrectly win the lookup.
        if tvdb_id:
            resolved = await self.find_series_by_tvdb(tvdb_id)
            add_series_id(resolved)

        add_series_id(series_id)

        # --------------------------------------------------------------
        # Direct season candidates
        # --------------------------------------------------------------

        candidates = []

        for value in season_candidates or []:
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue

            if value < 0:
                continue

            if value not in candidates:
                candidates.append(value)

        try:
            episode_number = int(episode_number)
        except (TypeError, ValueError):
            return None

        normalized_title = (
            str(episode_title).strip().casefold()
            if episode_title
            else ""
        )
        cache_key = (
            tuple(candidate_series_ids),
            tuple(candidates),
            int(episode_number),
            normalized_title,
        )

        if cache_key in self._anime_episode_cache:
            return self._anime_episode_cache[cache_key]

        # --------------------------------------------------------------
        # First try the known season numbers.
        # --------------------------------------------------------------

        for current_series_id in candidate_series_ids:
            for season_number in candidates:
                episode = await self.get_episode_details(
                    current_series_id,
                    season_number,
                    episode_number,
                )

                if not episode:
                    continue

                # When we have a known TMDB series and season number,
                # the season + episode numbers are the authoritative match.
                # SIMKL/ANIDB episode titles can differ in language or can be
                # stale, so never reject a direct season/episode match because
                # the title text differs.
                result = {
                    "series_id": current_series_id,
                    "season_number": season_number,
                    "episode_number": episode_number,
                    "episode": episode,
                }
                self._anime_episode_cache[cache_key] = result
                return result

        # --------------------------------------------------------------
        # Broader fallback:
        #
        # Look through TMDB's seasons and find an episode whose
        # number/title matches what SIMKL gave us.
        # --------------------------------------------------------------

        for current_series_id in candidate_series_ids:
            series_data = await self._get_series_details(
                current_series_id,
            )

            if not series_data:
                continue

            seasons = series_data.get("seasons") or []

            for season in seasons:
                season_number = season.get("season_number")

                try:
                    season_number = int(season_number)
                except (TypeError, ValueError):
                    continue

                if season_number < 0:
                    continue

                season_data = await self._get_season_details(
                    current_series_id,
                    season_number,
                )

                if not season_data:
                    continue

                episodes = (
                    season_data.get("episodes")
                    or []
                )

                for episode in episodes:
                    try:
                        tmdb_episode_number = int(
                            episode.get("episode_number")
                        )
                    except (TypeError, ValueError):
                        continue

                    if (
                        tmdb_episode_number
                        != int(episode_number)
                    ):
                        continue

                    # If we know the title, use it as an additional
                    # safety check.
                    if episode_title:
                        tmdb_title = (
                            episode.get("name") or ""
                        ).strip().casefold()

                        simkl_title = (
                            str(episode_title)
                            .strip()
                            .casefold()
                        )

                        if (
                            tmdb_title
                            and simkl_title
                            and tmdb_title != simkl_title
                        ):
                            continue

                    result = {
                        "series_id": current_series_id,
                        "season_number": season_number,
                        "episode_number": episode_number,
                        "episode": episode,
                    }
                    self._anime_episode_cache[cache_key] = result
                    return result

        self._anime_episode_cache[cache_key] = None
        return None

    async def _get_series_details(
        self,
        series_id,
    ) -> dict | None:
        """Get and cache TMDB TV series details."""

        try:
            series_id = int(series_id)
        except (TypeError, ValueError):
            return None

        if series_id in self._series_cache:
            return self._series_cache[series_id]

        data = await self._get_json(
            f"{API_BASE}/tv/{series_id}",
            {
                "language": "en-US",
            },
        )
        self._series_cache[series_id] = data
        return data

    async def _get_season_details(
        self,
        series_id,
        season_number,
    ) -> dict | None:
        """Get and cache TMDB season details."""

        try:
            series_id = int(series_id)
            season_number = int(season_number)
        except (TypeError, ValueError):
            return None

        cache_key = (
            series_id,
            season_number,
        )

        if cache_key in self._season_cache:
            return self._season_cache[cache_key]

        path = (
            f"{API_BASE}/tv/{series_id}/season/"
            f"{season_number}"
        )

        data = await self._get_json(
            path,
            {
                "language": "en-US",
            },
        )

        self._season_cache[cache_key] = data

        return data

    # ------------------------------------------------------------------
    # TV series title
    # ------------------------------------------------------------------

    async def get_tv_title(
        self,
        series_id,
        prefer_english: bool = False,
    ) -> str | None:
        """Return the TV series title, optionally preferring an English translation."""

        try:
            series_id = int(series_id)
        except (TypeError, ValueError):
            return None

        cache_key = (series_id, bool(prefer_english))
        if cache_key in self._tv_title_cache:
            return self._tv_title_cache[cache_key]

        data = await self._get_series_details(series_id)
        if not data:
            self._tv_title_cache[cache_key] = None
            return None

        title = data.get("name")
        original_title = data.get("original_name")

        if prefer_english:
            # Prefer an English translation that is actually different from
            # the original/Romaji title.
            translations = await self._get_json(
                f"{API_BASE}/tv/{series_id}/translations",
            )
            english_titles = []
            if translations:
                for translation in translations.get("translations") or []:
                    if translation.get("iso_639_1") != "en":
                        continue
                    translated_title = (
                        (translation.get("data") or {}).get("name")
                    )
                    if translated_title:
                        english_titles.append(
                            (
                                translation.get("iso_3166_1") == "US",
                                str(translated_title).strip(),
                            )
                        )

            for is_us, translated_title in sorted(
                english_titles,
                key=lambda item: not item[0],
            ):
                if (
                    translated_title
                    and translated_title.casefold()
                    != str(original_title or "").strip().casefold()
                ):
                    title = translated_title
                    break

            # TMDB's search endpoint searches original, translated and
            # also-known-as names. Query it even when the details endpoint's
            # current name differs from original_name: an anime can have a
            # Romaji/localized primary name while still having an English
            # search result for the same TMDB series.
            query = original_title or title
            if query:
                search = await self._get_json(
                    f"{API_BASE}/search/tv",
                    {
                        "query": query,
                        "language": "en-US",
                        "include_adult": False,
                    },
                )
                results = search.get("results") if search else None
                matching = next(
                    (
                        result
                        for result in (results or [])
                        if result.get("id") == series_id
                    ),
                    None,
                )
                if matching and matching.get("name"):
                    title = str(matching["name"]).strip()

        result = str(title) if title else None
        self._tv_title_cache[cache_key] = result
        return result

    # ------------------------------------------------------------------
    # TV backdrops
    # ------------------------------------------------------------------

    async def get_tv_backdrop(self, series_id) -> str | None:
        try:
            series_id = int(series_id)
        except (TypeError, ValueError):
            return None
        if series_id in self._tv_backdrop_cache:
            return self._tv_backdrop_cache[series_id]
        data = await self._get_json(
            f"{API_BASE}/tv/{series_id}/images",
            {"include_image_language": "en,null"},
        )
        if not data:
            self._tv_backdrop_cache[series_id] = None
            return None
        backdrops = data.get("backdrops") or []
        if not backdrops:
            self._tv_backdrop_cache[series_id] = None
            return None
        backdrops = sorted(
            backdrops,
            key=lambda image: (
                image.get("vote_average", 0),
                image.get("vote_count", 0),
            ),
            reverse=True,
        )
        path = backdrops[0].get("file_path")
        result = f"{IMAGE_BASE}{path}" if path else None
        self._tv_backdrop_cache[series_id] = result
        return result


    # ------------------------------------------------------------------
    # Title logos
    # ------------------------------------------------------------------

    async def _get_title_logo(
        self,
        path: str,
        cache: dict[int, str | None],
        item_id: int,
    ) -> str | None:
        """Return the highest-rated English/neutral transparent title logo."""

        if item_id in cache:
            return cache[item_id]

        data = await self._get_json(
            path,
            {
                "include_image_language": "en,null",
            },
        )

        if not data:
            cache[item_id] = None
            return None

        logos = data.get("logos") or []
        if not logos:
            cache[item_id] = None
            return None

        logos = sorted(
            logos,
            key=lambda image: (
                image.get("vote_average", 0),
                image.get("vote_count", 0),
            ),
            reverse=True,
        )

        logo_path = logos[0].get("file_path")
        result = f"https://image.tmdb.org/t/p/w500{logo_path}" if logo_path else None
        cache[item_id] = result
        return result

    async def get_movie_logo(self, movie_id) -> str | None:
        try:
            movie_id = int(movie_id)
        except (TypeError, ValueError):
            return None

        return await self._get_title_logo(
            f"{API_BASE}/movie/{movie_id}/images",
            self._movie_logo_cache,
            movie_id,
        )

    async def get_tv_logo(self, series_id) -> str | None:
        try:
            series_id = int(series_id)
        except (TypeError, ValueError):
            return None

        return await self._get_title_logo(
            f"{API_BASE}/tv/{series_id}/images",
            self._tv_logo_cache,
            series_id,
        )

    # ------------------------------------------------------------------
    # Movies
    # ------------------------------------------------------------------

    async def get_movie_backdrop(
        self,
        movie_id,
    ) -> str | None:
        """
        Return the highest-rated TMDB movie backdrop.

        This intentionally uses a landscape backdrop rather than
        the portrait poster.
        """

        try:
            movie_id = int(movie_id)
        except (TypeError, ValueError):
            return None

        if movie_id in self._movie_backdrop_cache:
            return self._movie_backdrop_cache[movie_id]

        path = f"{API_BASE}/movie/{movie_id}/images"

        data = await self._get_json(
            path,
            {
                "include_image_language": "en,null",
            },
        )

        if not data:
            self._movie_backdrop_cache[movie_id] = None
            return None

        backdrops = data.get("backdrops") or []

        if not backdrops:
            self._movie_backdrop_cache[movie_id] = None
            return None

        backdrops = sorted(
            backdrops,
            key=lambda image: (
                image.get("vote_average", 0),
                image.get("vote_count", 0),
            ),
            reverse=True,
        )

        backdrop_path = backdrops[0].get(
            "file_path"
        )

        if not backdrop_path:
            self._movie_backdrop_cache[movie_id] = None
            return None

        backdrop_url = (
            f"{IMAGE_BASE}{backdrop_path}"
        )

        self._movie_backdrop_cache[movie_id] = (
            backdrop_url
        )

        return backdrop_url
