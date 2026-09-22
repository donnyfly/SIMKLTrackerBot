"""
Tiny JSON-file storage. No database required.

Data shape (data/store.json):
{
    "channel_id": 123456789012345678,
    "poll_interval_minutes": 5,
    "users": {
        "<discord_user_id>": {
            "simkl_token": "...",
            "simkl_username": "...",
            "last_checked": {
                "shows": "2026-09-01T00:00:00Z",
                "movies": "2026-09-01T00:00:00Z",
                "anime": "2026-09-01T00:00:00Z"
            },
            "announced": ["shows:12345:1:2", "movies:6789", ...]
        }
    }
}
"""

import json
import os
import asyncio

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "store.json")

_lock = asyncio.Lock()

_DEFAULT = {
    "channel_id": None,
    "poll_interval_minutes": 5,
    "users": {},
}

# Cap how many "announced" keys we remember per user, so the file doesn't grow forever.
MAX_ANNOUNCED_PER_USER = 300


def _load() -> dict:
    if not os.path.exists(DATA_PATH):
        return json.loads(json.dumps(_DEFAULT))
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return json.loads(json.dumps(_DEFAULT))


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    tmp_path = DATA_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, DATA_PATH)


class Storage:
    """Thin async wrapper so bot.py never touches the file directly."""

    async def get_all(self) -> dict:
        async with _lock:
            return _load()

    async def set_channel(self, channel_id: int) -> None:
        async with _lock:
            data = _load()
            data["channel_id"] = channel_id
            _save(data)

    async def set_poll_interval(self, minutes: int) -> None:
        async with _lock:
            data = _load()
            data["poll_interval_minutes"] = minutes
            _save(data)

    async def link_user(self, discord_user_id: str, simkl_token: str, simkl_username: str, start_time_iso: str) -> None:
        async with _lock:
            data = _load()
            data["users"][discord_user_id] = {
                "simkl_token": simkl_token,
                "simkl_username": simkl_username,
                "last_checked": {
                    "shows": start_time_iso,
                    "movies": start_time_iso,
                    "anime": start_time_iso,
                },
                "announced": [],
            }
            _save(data)

    async def unlink_user(self, discord_user_id: str) -> bool:
        async with _lock:
            data = _load()
            if discord_user_id in data["users"]:
                del data["users"][discord_user_id]
                _save(data)
                return True
            return False

    async def update_last_checked(self, discord_user_id: str, category: str, iso_timestamp: str) -> None:
        async with _lock:
            data = _load()
            if discord_user_id in data["users"]:
                data["users"][discord_user_id]["last_checked"][category] = iso_timestamp
                _save(data)

    async def add_announced(self, discord_user_id: str, keys: list[str]) -> None:
        async with _lock:
            data = _load()
            if discord_user_id in data["users"]:
                existing = data["users"][discord_user_id].get("announced", [])
                existing.extend(keys)
                # Keep only the most recent N to bound file size
                data["users"][discord_user_id]["announced"] = existing[-MAX_ANNOUNCED_PER_USER:]
                _save(data)

    async def is_announced(self, discord_user_id: str, key: str) -> bool:
        async with _lock:
            data = _load()
            user = data["users"].get(discord_user_id)
            if not user:
                return False
            return key in user.get("announced", [])


storage = Storage()
