"""
Lightweight persistent storage for the SIMKL Discord bot.

The bot uses a JSON file for persistence, but keeps the data in memory
while running. This avoids repeatedly reading and parsing store.json
during polling.

The JSON file is still written whenever persistent data changes.

AUTH V2 stores both access_token and refresh_token.
"""

import asyncio
import copy
import json
import os


DATA_PATH = os.path.join(
    os.path.dirname(__file__),
    "data",
    "store.json",
)


_DEFAULT = {
    "channel_id": None,
    "poll_interval_minutes": 5,
    "users": {},
}


_lock = asyncio.Lock()


def _default_data() -> dict:
    """Return a fresh copy of the default data."""

    return copy.deepcopy(_DEFAULT)


def _load_from_disk() -> dict:
    """
    Load the persistent store from disk.

    If the file does not exist or contains invalid JSON, return defaults.
    """

    if not os.path.exists(DATA_PATH):
        return _default_data()

    try:
        with open(
            DATA_PATH,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

    except (
        OSError,
        json.JSONDecodeError,
    ):
        return _default_data()

    if not isinstance(data, dict):
        return _default_data()

    # Make sure expected top-level keys exist.
    data.setdefault(
        "channel_id",
        None,
    )

    data.setdefault(
        "poll_interval_minutes",
        5,
    )

    data.setdefault(
        "users",
        {},
    )

    if not isinstance(data["users"], dict):
        data["users"] = {}

    return data


def _save_to_disk(data: dict) -> None:
    """
    Atomically save the current data.

    Writes to a temporary file first, then replaces store.json.
    """

    os.makedirs(
        os.path.dirname(DATA_PATH),
        exist_ok=True,
    )

    tmp_path = DATA_PATH + ".tmp"

    with open(
        tmp_path,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
        )

        f.write("\n")

        f.flush()
        os.fsync(f.fileno())

    os.replace(
        tmp_path,
        DATA_PATH,
    )


def _normalise_user(user: dict) -> None:
    """
    Make sure an existing user's data has all expected fields.
    """

    user.setdefault(
        "simkl_token",
        None,
    )

    user.setdefault(
        "refresh_token",
        None,
    )

    user.setdefault(
        "simkl_username",
        "unknown",
    )

    user.setdefault(
        "last_checked",
        {},
    )

    user["last_checked"].setdefault(
        "shows",
        "1970-01-01T00:00:00Z",
    )

    user["last_checked"].setdefault(
        "movies",
        "1970-01-01T00:00:00Z",
    )

    user["last_checked"].setdefault(
        "anime",
        "1970-01-01T00:00:00Z",
    )

    # Older versions stored announced items as a list.
    #
    # Internally we convert it to a set for O(1) lookups.
    # The set is never written directly to JSON.
    announced = user.get(
        "announced",
        [],
    )

    if isinstance(announced, set):
        user["announced"] = announced

    elif isinstance(announced, list):
        user["announced"] = set(announced)

    else:
        user["announced"] = set()


class Storage:
    """
    In-memory storage with JSON persistence.

    store.json is loaded once when Storage is created.
    """

    def __init__(self):
        self._data = _load_from_disk()

        for user in self._data.get(
            "users",
            {},
        ).values():

            if isinstance(user, dict):
                _normalise_user(user)

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def _serialisable_data(self) -> dict:
        """
        Create a JSON-safe copy of the in-memory data.

        Internal announced sets are converted back into lists.
        """

        data = copy.deepcopy(self._data)

        for user in data.get(
            "users",
            {},
        ).values():

            if not isinstance(user, dict):
                continue

            announced = user.get(
                "announced",
                set(),
            )

            if isinstance(announced, set):
                # Sorting makes the JSON output deterministic.
                user["announced"] = sorted(
                    announced
                )

        return data

    def _save(self) -> None:
        """Save the current in-memory data to disk."""

        _save_to_disk(
            self._serialisable_data()
        )

    # -----------------------------------------------------------------------
    # General
    # -----------------------------------------------------------------------

    async def get_all(self) -> dict:
        """
        Return a snapshot of all stored data.

        The returned dictionary is a copy, so callers cannot accidentally
        modify the live storage state without using Storage methods.
        """

        async with _lock:
            return self._serialisable_data()

    async def set_channel(
        self,
        channel_id: int,
    ) -> None:

        async with _lock:
            self._data["channel_id"] = channel_id

            self._save()

    async def set_poll_interval(
        self,
        minutes: int,
    ) -> None:

        async with _lock:
            self._data["poll_interval_minutes"] = max(
                int(minutes),
                1,
            )

            self._save()

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
    ) -> None:

        async with _lock:

            self._data["users"][
                discord_user_id
            ] = {
                "simkl_token": access_token,
                "refresh_token": refresh_token,
                "simkl_username": simkl_username,
                "last_checked": {
                    "shows": start_time_iso,
                    "movies": start_time_iso,
                    "anime": start_time_iso,
                },
                "announced": set(),
            }

            self._save()

    async def update_tokens(
        self,
        discord_user_id: str,
        access_token: str,
        refresh_token: str | None,
    ) -> None:

        async with _lock:

            user = self._data["users"].get(
                discord_user_id
            )

            if not user:
                return

            user["simkl_token"] = access_token

            if refresh_token:
                user["refresh_token"] = refresh_token

            self._save()

    async def unlink_user(
        self,
        discord_user_id: str,
    ) -> bool:

        async with _lock:

            if discord_user_id not in self._data["users"]:
                return False

            del self._data["users"][
                discord_user_id
            ]

            self._save()

            return True

    # -----------------------------------------------------------------------
    # Polling state
    # -----------------------------------------------------------------------

    async def update_last_checked(
        self,
        discord_user_id: str,
        category: str,
        iso_timestamp: str,
    ) -> None:

        async with _lock:

            user = self._data["users"].get(
                discord_user_id
            )

            if not user:
                return

            user.setdefault(
                "last_checked",
                {},
            )

            user["last_checked"][
                category
            ] = iso_timestamp

            self._save()

    # -----------------------------------------------------------------------
    # Announcement tracking
    # -----------------------------------------------------------------------

    async def add_announced(
        self,
        discord_user_id: str,
        keys: list[str],
    ) -> None:
        """
        Mark activity keys as announced.

        Unlike the old implementation, this does not discard old
        announcement keys after an arbitrary 300-item limit.
        """

        if not keys:
            return

        async with _lock:

            user = self._data["users"].get(
                discord_user_id
            )

            if not user:
                return

            _normalise_user(user)

            user["announced"].update(keys)

            self._save()

    async def is_announced(
        self,
        discord_user_id: str,
        key: str,
    ) -> bool:
        """
        Check whether an activity key has already been announced.

        Uses a set internally for fast lookup.
        """

        async with _lock:

            user = self._data["users"].get(
                discord_user_id
            )

            if not user:
                return False

            _normalise_user(user)

            return key in user["announced"]


storage = Storage()
