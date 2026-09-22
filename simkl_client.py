"""
Minimal async client for the SIMKL API (AUTH V2).

Uses the Device / PIN flow + automatic token refresh.
"""

import logging
import aiohttp

API_BASE = "https://api.simkl.com"
log = logging.getLogger("simkl-bot")


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
            "User-Agent": "simkl-discord-bot/1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    # ---------- AUTH V2 Device / PIN flow ----------

    async def start_pin_auth(self) -> dict:
        """
        Starts the AUTH V2 device flow.
        Returns dict with: device_code, user_code, verification_uri, expires_in, interval
        """
        url = f"{API_BASE}/oauth2/device"
        data = {
            "client_id": self.client_id,
            "scope": "media:read media:write",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                data=data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "simkl-discord-bot/1.0",
                },
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def poll_pin(self, device_code: str) -> dict | None:
        """
        Polls for token approval.
        Returns {"access_token": ..., "refresh_token": ...} once approved, otherwise None.
        """
        url = f"{API_BASE}/oauth2/token"
        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": self.client_id,
            "device_code": device_code,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                data=data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "simkl-discord-bot/1.0",
                },
            ) as resp:
                text = await resp.text()

                if resp.status == 200:
                    try:
                        result = await resp.json()
                    except Exception:
                        log.warning("200 response but invalid JSON: %s", text)
                        return None

                    if "access_token" in result:
                        return {
                            "access_token": result["access_token"],
                            "refresh_token": result.get("refresh_token"),
                        }
                    log.warning("200 response but no access_token: %s", text)
                    return None

                # Pending or error
                try:
                    err = await resp.json()
                    error = err.get("error", "")
                    if error in ("authorization_pending", "slow_down"):
                        return None  # normal, keep polling
                    log.warning("Token poll error %s: %s", resp.status, text)
                except Exception:
                    log.warning("Token poll non-JSON %s: %s", resp.status, text)
                return None

    async def refresh_token(self, refresh_token: str) -> dict | None:
        """Exchange a refresh_token for a new access_token + refresh_token."""
        url = f"{API_BASE}/oauth2/token"
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                data=data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "simkl-discord-bot/1.0",
                },
            ) as resp:
                if resp.status != 200:
                    log.warning("Refresh failed %s: %s", resp.status, await resp.text())
                    return None
                result = await resp.json()
                return {
                    "access_token": result["access_token"],
                    "refresh_token": result.get("refresh_token", refresh_token),
                }

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
        url = f"{API_BASE}/sync/activities"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers(token)) as resp:
                if resp.status == 401:
                    raise SimklAuthError("Token invalid or revoked")
                resp.raise_for_status()
                return await resp.json()

    async def get_all_items(self, token: str, media_type: str, date_from: str | None = None) -> list:
        url = f"{API_BASE}/sync/all-items/{media_type}?extended=full&episode_watched_at=yes"
        if date_from:
            url += f"&date_from={date_from}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers(token)) as resp:
                if resp.status == 401:
                    raise SimklAuthError("Token invalid or revoked")
                resp.raise_for_status()
                data = await resp.json()
                if isinstance(data, dict):
                    return data.get(media_type, [])
                return data or []
