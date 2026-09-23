"""
SIMKL API client for the Discord watch activity bot.

- Uses SIMKL AUTH V2 Device / PIN flow
- Supports automatic token refresh
- Reuses a single aiohttp session for all API requests
- Keeps the existing interface used by bot.py
"""

import logging

import aiohttp


API_BASE = "https://api.simkl.com"
USER_AGENT = "simkl-discord-bot/1.0"

log = logging.getLogger("simkl-bot")


class SimklAuthError(Exception):
    """Raised when a stored token is no longer valid."""
    pass


class SimklClient:
    def __init__(self, client_id: str):
        self.client_id = client_id
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """
        Return the shared HTTP session.

        A single session is reused for all SIMKL requests instead of
        creating a new TCP/TLS connection for every request.
        """

        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)

            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "User-Agent": USER_AGENT,
                },
            )

        return self._session

    async def close(self) -> None:
        """Close the shared HTTP session."""

        if self._session is not None and not self._session.closed:
            await self._session.close()

        self._session = None

    def _headers(self, token: str | None = None) -> dict:
        """Build common SIMKL API headers."""

        headers = {
            "Content-Type": "application/json",
            "simkl-api-key": self.client_id,
            "User-Agent": USER_AGENT,
        }

        if token:
            headers["Authorization"] = f"Bearer {token}"

        return headers

    # -----------------------------------------------------------------------
    # AUTH V2 Device / PIN flow
    # -----------------------------------------------------------------------

    async def start_pin_auth(self) -> dict:
        """
        Start the SIMKL AUTH V2 device flow.

        Returns:
            dict containing device_code, user_code, verification_uri,
            expires_in and interval.
        """

        url = f"{API_BASE}/oauth2/device"

        data = {
            "client_id": self.client_id,
            "scope": "media:read media:write",
        }

        session = await self._get_session()

        async with session.post(
            url,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": USER_AGENT,
            },
        ) as resp:

            resp.raise_for_status()

            return await resp.json()

    async def poll_pin(self, device_code: str) -> dict | None:
        """
        Poll for SIMKL device authorization.

        Returns:
            Token dictionary once approved, otherwise None.
        """

        url = f"{API_BASE}/oauth2/token"

        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": self.client_id,
            "device_code": device_code,
        }

        session = await self._get_session()

        async with session.post(
            url,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": USER_AGENT,
            },
        ) as resp:

            text = await resp.text()

            if resp.status == 200:
                try:
                    result = await resp.json()

                except Exception:
                    log.warning(
                        "200 response but invalid JSON: %s",
                        text,
                    )
                    return None

                if "access_token" in result:
                    return {
                        "access_token": result["access_token"],
                        "refresh_token": result.get("refresh_token"),
                    }

                log.warning(
                    "200 response but no access_token: %s",
                    text,
                )

                return None

            try:
                err = await resp.json()

                error = err.get("error", "")

                if error in (
                    "authorization_pending",
                    "slow_down",
                ):
                    return None

                log.warning(
                    "Token poll error %s: %s",
                    resp.status,
                    text,
                )

            except Exception:
                log.warning(
                    "Token poll non-JSON %s: %s",
                    resp.status,
                    text,
                )

            return None

    async def refresh_token(
        self,
        refresh_token: str,
    ) -> dict | None:
        """
        Exchange a refresh token for a new access token.
        """

        url = f"{API_BASE}/oauth2/token"

        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token,
        }

        session = await self._get_session()

        async with session.post(
            url,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": USER_AGENT,
            },
        ) as resp:

            if resp.status != 200:
                log.warning(
                    "Refresh failed %s: %s",
                    resp.status,
                    await resp.text(),
                )
                return None

            try:
                result = await resp.json()

            except Exception:
                log.exception(
                    "SIMKL refresh returned invalid JSON"
                )
                return None

            access_token = result.get("access_token")

            if not access_token:
                log.warning(
                    "SIMKL refresh response had no access_token"
                )
                return None

            return {
                "access_token": access_token,
                "refresh_token": result.get(
                    "refresh_token",
                    refresh_token,
                ),
            }

    # -----------------------------------------------------------------------
    # Authenticated API calls
    # -----------------------------------------------------------------------

    async def get_user_settings(
        self,
        token: str,
    ) -> dict:
        """Get the authenticated user's SIMKL settings."""

        url = f"{API_BASE}/users/settings"

        session = await self._get_session()

        async with session.get(
            url,
            headers=self._headers(token),
        ) as resp:

            if resp.status == 401:
                raise SimklAuthError(
                    "Token invalid or revoked"
                )

            resp.raise_for_status()

            return await resp.json()

    async def get_activities(
        self,
        token: str,
    ) -> dict:
        """Get the authenticated user's activity timestamps."""

        url = f"{API_BASE}/sync/activities"

        session = await self._get_session()

        async with session.get(
            url,
            headers=self._headers(token),
        ) as resp:

            if resp.status == 401:
                raise SimklAuthError(
                    "Token invalid or revoked"
                )

            resp.raise_for_status()

            return await resp.json()

    async def get_all_items(
        self,
        token: str,
        media_type: str,
        date_from: str | None = None,
    ) -> list:
        """
        Get full watched-item data from SIMKL.

        Returns the list for the requested media type.
        """

        url = (
            f"{API_BASE}/sync/all-items/"
            f"{media_type}"
            "?extended=full&episode_watched_at=yes"
        )

        if date_from:
            url += f"&date_from={date_from}"

        session = await self._get_session()

        async with session.get(
            url,
            headers=self._headers(token),
        ) as resp:

            if resp.status == 401:
                raise SimklAuthError(
                    "Token invalid or revoked"
                )

            resp.raise_for_status()

            data = await resp.json()

            if isinstance(data, dict):
                return data.get(media_type, [])

            return data or []
