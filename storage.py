"""
Lightweight persistent storage for the SIMKL Discord bot.

Data is kept in memory while running and persisted to data/store.json.

Changes that happen on every poll (announced keys, checkpoints) only mark
the data as changed; the bot calls flush() to write them in one go.
Everything else (linking, unlinking, tokens, channel) is written at once.

Disk writes run in a worker thread so they never block the Discord
connection, and are atomic (write a temp file, then replace).
"""

import asyncio
import copy
import json
import os

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "store.json")

DEFAULT_POLL_INTERVAL_MINUTES = 60
EPOCH_ISO = "1970-01-01T00:00:00Z"

# Protects the in-memory data.
_lock = asyncio.Lock()

# Makes sure only one disk write happens at a time.
_write_lock = asyncio.Lock()


def _default_data() -> dict:
    return {
        "channel_id": None,
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
        "server_embed_preferences": {"style": "rich", "artwork": "auto", "activity_text": "short"},
        "users": {},
    }


def _load_from_disk() -> dict:
    """Load the store from disk, falling back to defaults if missing/invalid."""
    if not os.path.exists(DATA_PATH):
        return _default_data()

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _default_data()

    if not isinstance(data, dict):
        return _default_data()

    data.setdefault("channel_id", None)
    data.setdefault("poll_interval_minutes", DEFAULT_POLL_INTERVAL_MINUTES)
    data.setdefault("server_embed_preferences", {"style": "rich", "artwork": "auto", "activity_text": "short"})
    if not isinstance(data["server_embed_preferences"], dict):
        data["server_embed_preferences"] = {"style": "rich", "artwork": "auto", "activity_text": "short"}
    data["server_embed_preferences"].setdefault("style", "rich")
    data["server_embed_preferences"].setdefault("artwork", "auto")
    data["server_embed_preferences"].setdefault("activity_text", "short")
    data.setdefault("users", {})

    if not isinstance(data["users"], dict):
        data["users"] = {}

    return data


def _write_to_disk(text: str) -> None:
    """Atomically write the serialised store to disk."""
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    tmp_path = DATA_PATH + ".tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, DATA_PATH)


def _json_default(obj):
    """Store the internal announced sets as sorted lists in JSON."""
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serialisable")


def _normalise_user(user: dict) -> None:
    """Make sure a user record has every expected field."""
    user.setdefault("simkl_token", None)
    user.setdefault("refresh_token", None)
    user.setdefault("token_expires_at", None)
    user.setdefault("simkl_username", "unknown")
    user.setdefault("simkl_account_id", None)

    # Users linked before this version have not had their existing
    # history recorded yet; the bot does that on their next poll.
    user.setdefault("history_seeded", False)

    user.setdefault("embed_preferences", {
        "style": "rich",
        "artwork": "auto",
        "activity_text": "short",
    })
    prefs = user["embed_preferences"]
    if not isinstance(prefs, dict):
        prefs = {}
        user["embed_preferences"] = prefs
    prefs.setdefault("style", "rich")
    prefs.setdefault("artwork", "auto")
    prefs.setdefault("activity_text", "short")
    user.setdefault("embed_preferences_custom", prefs != {"style": "rich", "artwork": "auto", "activity_text": "short"})

    user.setdefault("activity_state", {
        "statuses": {},
        "watch_times": {},
        "statuses_seeded": False,
    })
    state = user["activity_state"]
    if not isinstance(state, dict):
        state = {}
        user["activity_state"] = state
    state.setdefault("statuses", {})
    state.setdefault("watch_times", {})
    state.setdefault("statuses_seeded", False)

    user.setdefault("last_checked", {})
    for media_type in ("shows", "movies", "anime"):
        user["last_checked"].setdefault(media_type, EPOCH_ISO)

    # Stored as a list in JSON, kept as a set in memory for fast lookups.
    announced = user.get("announced", [])
    if isinstance(announced, set):
        user["announced"] = announced
    elif isinstance(announced, list):
        user["announced"] = set(announced)
    else:
        user["announced"] = set()


class Storage:
    """In-memory storage with JSON persistence."""

    def __init__(self):
        self._data = _load_from_disk()
        self._dirty = False

        for user in self._data["users"].values():
            if isinstance(user, dict):
                _normalise_user(user)

    def _user(self, discord_user_id: str) -> dict | None:
        """Return the live, normalised user record, or None."""
        user = self._data["users"].get(discord_user_id)
        if not isinstance(user, dict):
            return None
        _normalise_user(user)
        return user

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    async def flush(self) -> None:
        """Write pending changes to disk, if there are any."""
        async with _write_lock:
            async with _lock:
                if not self._dirty:
                    return
                text = json.dumps(self._data, indent=2, default=_json_default) + "\n"
                self._dirty = False

            try:
                await asyncio.to_thread(_write_to_disk, text)
            except Exception:
                # Try again on the next flush.
                self._dirty = True
                raise

    # -----------------------------------------------------------------------
    # General
    # -----------------------------------------------------------------------

    async def get_all(self) -> dict:
        """
        Return a snapshot of all stored data.

        The snapshot is a copy (so callers can't change live state by
        accident) and leaves out the announced sets, which can be large.
        Use get_announced() / is_announced() for those.
        """
        async with _lock:
            snapshot = {
                key: copy.deepcopy(value)
                for key, value in self._data.items()
                if key != "users"
            }
            snapshot["users"] = {
                uid: (
                    {k: copy.deepcopy(v) for k, v in user.items() if k != "announced"}
                    if isinstance(user, dict)
                    else copy.deepcopy(user)
                )
                for uid, user in self._data["users"].items()
            }
            return snapshot

    async def set_channel(self, channel_id: int) -> None:
        async with _lock:
            self._data["channel_id"] = channel_id
            self._dirty = True
        await self.flush()

    # -----------------------------------------------------------------------
    # Users
    # -----------------------------------------------------------------------

    async def link_user(
        self,
        discord_user_id: str,
        access_token: str,
        refresh_token: str | None,
        simkl_username: str,
        start_time_iso: str,
        token_expires_at: str | None = None,
        simkl_account_id: int | str | None = None,
    ) -> None:
        async with _lock:
            self._data["users"][discord_user_id] = {
                "simkl_token": access_token,
                "refresh_token": refresh_token,
                "token_expires_at": token_expires_at,
                "simkl_username": simkl_username,
                "simkl_account_id": simkl_account_id,
                "history_seeded": False,
                "last_checked": {
                    "shows": start_time_iso,
                    "movies": start_time_iso,
                    "anime": start_time_iso,
                },
                "announced": set(),
            }
            self._dirty = True
        await self.flush()

    async def update_tokens(
        self,
        discord_user_id: str,
        access_token: str,
        refresh_token: str | None,
        token_expires_at: str | None = None,
    ) -> None:
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return
            user["simkl_token"] = access_token
            if refresh_token:
                user["refresh_token"] = refresh_token
            user["token_expires_at"] = token_expires_at
            self._dirty = True
        await self.flush()

    async def get_server_embed_preferences(self) -> dict:
        async with _lock:
            return copy.deepcopy(self._data["server_embed_preferences"])

    async def set_server_embed_preferences(
        self,
        style: str | None = None,
        artwork: str | None = None,
        activity_text: str | None = None,
    ) -> None:
        async with _lock:
            prefs = self._data["server_embed_preferences"]
            if style is not None:
                prefs["style"] = style
            if artwork is not None:
                prefs["artwork"] = artwork
            if activity_text is not None:
                prefs["activity_text"] = activity_text
            self._dirty = True
        await self.flush()

    async def get_embed_preferences(self, discord_user_id: str) -> dict:
        async with _lock:
            user = self._user(discord_user_id)
            server = copy.deepcopy(self._data["server_embed_preferences"])
            if not user or not user.get("embed_preferences_custom", False):
                return server
            return copy.deepcopy(user["embed_preferences"])

    async def set_embed_preferences(
        self,
        discord_user_id: str,
        style: str | None = None,
        artwork: str | None = None,
        activity_text: str | None = None,
    ) -> None:
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return
            prefs = user["embed_preferences"]
            if style is not None:
                prefs["style"] = style
            if artwork is not None:
                prefs["artwork"] = artwork
            if activity_text is not None:
                prefs["activity_text"] = activity_text
            user["embed_preferences_custom"] = True
            self._dirty = True
        await self.flush()

    async def reset_embed_preferences(self, discord_user_id: str) -> None:
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return
            user["embed_preferences_custom"] = False
            self._dirty = True
        await self.flush()

    async def get_activity_state(self, discord_user_id: str) -> dict:
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return {"statuses": {}, "watch_times": {}}
            return copy.deepcopy(user["activity_state"])

    async def update_activity_state(
        self,
        discord_user_id: str,
        statuses: dict | None = None,
        watch_times: dict | None = None,
        statuses_seeded: bool | None = None,
    ) -> None:
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return
            state = user["activity_state"]
            if statuses:
                state["statuses"].update(statuses)
            if watch_times:
                state["watch_times"].update(watch_times)
            if statuses_seeded is not None:
                state["statuses_seeded"] = statuses_seeded
            self._dirty = True
        await self.flush()

    async def set_account_id(
        self,
        discord_user_id: str,
        simkl_account_id: int | str,
    ) -> None:
        """Save the user's SIMKL account ID (used for their profile link)."""
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return
            user["simkl_account_id"] = simkl_account_id
            self._dirty = True
        await self.flush()

    async def unlink_user(self, discord_user_id: str) -> bool:
        async with _lock:
            if discord_user_id not in self._data["users"]:
                return False
            del self._data["users"][discord_user_id]
            self._dirty = True
        await self.flush()
        return True

    # -----------------------------------------------------------------------
    # Polling state (call flush() afterwards)
    # -----------------------------------------------------------------------

    async def update_last_checked(
        self,
        discord_user_id: str,
        category: str,
        iso_timestamp: str,
    ) -> None:
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return
            user["last_checked"][category] = iso_timestamp
            self._dirty = True

    # -----------------------------------------------------------------------
    # Announcement tracking
    # -----------------------------------------------------------------------

    async def add_announced(self, discord_user_id: str, keys: list[str]) -> None:
        """Mark activity keys as announced (call flush() afterwards)."""
        if not keys:
            return
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return
            user["announced"].update(keys)
            self._dirty = True

    async def is_announced(self, discord_user_id: str, key: str) -> bool:
        async with _lock:
            user = self._user(discord_user_id)
            return bool(user) and key in user["announced"]

    async def get_announced(self, discord_user_id: str) -> set[str]:
        """Return a copy of the user's announced keys."""
        async with _lock:
            user = self._user(discord_user_id)
            return set(user["announced"]) if user else set()

    async def mark_history_seeded(
        self,
        discord_user_id: str,
        keys: list[str],
    ) -> bool:
        """
        Record the user's existing watch history as already announced,
        so it is never posted. Written to disk immediately.
        """
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return False
            user["announced"].update(keys)
            user["history_seeded"] = True
            self._dirty = True
        await self.flush()
        return True


storage = Storage()
