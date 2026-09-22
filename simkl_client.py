"""
Minimal async client for the SIMKL API (https://api.simkl.com).

Only implements what this bot needs:
  - PIN authentication flow (no client secret required)
  - Fetching "last activity" timestamps
  - Fetching watched shows / movies / anime, optionally since a date
  - Fetching basic user info (for display name)
"""

import aiohttp

API_BASE = "https://api.simkl.com"


class SimklAuthError(Exception):
    """Raised when a stored token is no longer valid (revoked/expired)."""
    pass


class SimklClient:
    def __init__(self, client_id: str):
        self.client_id = client_id

    def _headers(self, token: str | None = None) -> dict:
        headers = {
            "Content-Type": "application/json",
            "simkl-api-key": self.client_id,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    # ---------- PIN auth flow ----------

    async def start_pin_auth(self) -> dict:
        """
        Kicks off the PIN login flow.
        Returns dict with: user_code, verification_url, expires_in, interval
        """
        url = f"{API_BASE}/oauth/pin?client_id={self.client_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers()) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def poll_pin(self, user_code: str) -> str | None:
        """
        Checks whether the user has approved the PIN yet.
        Returns the access_token once approved, otherwise None.
        """
        url = f"{API_BASE}/oauth/pin/{user_code}?client_id={self.client_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("access_token")

    # ---------- Authenticated calls ----------

    async def get_user_settings(self, token: str) -> dict:
        url = f"{API_BASE}/users/settings"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers(token)) as resp:
                if resp.status == 401:
                    raise SimklAuthError("Token invalid or revoked")
                resp.raise_for_status()
                return await resp.json()

    async def get_activities(self, token: str) -> dict:
        """Returns latest-change timestamps per media type/category."""
        url = f"{API_BASE}/sync/activities"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers(token)) as resp:
                if resp.status == 401:
                    raise SimklAuthError("Token invalid or revoked")
                resp.raise_for_status()
                return await resp.json()

    async def get_all_items(self, token: str, media_type: str, date_from: str | None = None) -> list:
        """
        media_type: 'shows', 'movies', or 'anime'
        date_from: ISO 8601 timestamp string, or None for the full library
        Returns a list of library entries for that type.
        """
        url = f"{API_BASE}/sync/all-items/{media_type}?extended=full&episode_watched_at=yes"
        if date_from:
            url += f"&date_from={date_from}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers(token)) as resp:
                if resp.status == 401:
                    raise SimklAuthError("Token invalid or revoked")
                resp.raise_for_status()
                data = await resp.json()
                # The API nests results under the type name, e.g. {"shows": [...]}
                if isinstance(data, dict):
                    return data.get(media_type, [])
                return data or []
