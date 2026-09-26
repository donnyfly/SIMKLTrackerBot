"""
Lightweight persistent storage for the SIMKL Discord bot.

Global user records contain SIMKL authentication and personal preferences.
Guild records contain server configuration and per-server tracking state.
"""

import asyncio
import copy
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "store.json")

DEFAULT_POLL_INTERVAL_MINUTES = 60
EPOCH_ISO = "1970-01-01T00:00:00Z"
DEFAULT_TIMEZONE = "Asia/Singapore"


def _default_timezone_name() -> str:
    value = os.getenv("SIMKL_DEFAULT_TIMEZONE", DEFAULT_TIMEZONE).strip()
    return value or DEFAULT_TIMEZONE


def _resolve_timezone(name: str | None):
    value = (name or "").strip()
    if not value:
        value = _default_timezone_name()
    try:
        return ZoneInfo(value)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        try:
            return ZoneInfo(_default_timezone_name())
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            return timezone.utc

_lock = asyncio.Lock()
_write_lock = asyncio.Lock()

DEFAULT_EMBED_PREFERENCES = {
    "style": "rich",
    "artwork": "backdrop",
    "activity_text": "detailed",
    "show_imdb": True,
    "show_mal": True,
    "episode_code": False,
}


def _default_guild() -> dict:
    return {
        "channel_id": None,
        "embed_preferences": copy.deepcopy(DEFAULT_EMBED_PREFERENCES),
        "force_embed_preferences": False,
        "timezone": None,
        "weekly_recap_last_sent": None,
        "users": {},
    }


def _default_data() -> dict:
    return {
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
        "users": {},
        "guilds": {},
    }


def _load_from_disk() -> dict:
    if not os.path.exists(DATA_PATH):
        return _default_data()

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _default_data()

    if not isinstance(data, dict):
        return _default_data()

    data.setdefault("poll_interval_minutes", DEFAULT_POLL_INTERVAL_MINUTES)
    if not isinstance(data["users"], dict):
        data["users"] = {}
    if not isinstance(data.get("guilds"), dict):
        data["guilds"] = {}

    return data


def _write_to_disk(text: str) -> None:
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    tmp_path = DATA_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, DATA_PATH)


def _json_default(obj):
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serialisable")


def _default_statistics() -> dict:
    return {
        "episodes_watched": 0,
        "movies_watched": 0,
        "anime_episodes_watched": 0,
        "anime_movies_watched": 0,
        "watch_dates": {},
        "titles": {},
    }


def _default_activity_state() -> dict:
    return {
        "statuses": {},
        "watch_times": {},
        "statuses_seeded": False,
    }


def _default_guild_user(start_time_iso: str | None = None) -> dict:
    start = start_time_iso or EPOCH_ISO
    return {
        "history_seeded": False,
        "last_checked": {
            "shows": start,
            "movies": start,
            "anime": start,
        },
        "announced": set(),
        "activity_state": _default_activity_state(),
        "statistics": _default_statistics(),
        "achievements": {},
        "last_poll_at": None,
        "last_success_at": None,
        "last_error": None,
        "consecutive_failures": 0,
    }


def _normalise_user(user: dict) -> None:
    user.setdefault("simkl_token", None)
    user.setdefault("refresh_token", None)
    user.setdefault("token_expires_at", None)
    user.setdefault("simkl_username", "unknown")
    user.setdefault("simkl_account_id", None)
    user.setdefault("embed_preferences", copy.deepcopy(DEFAULT_EMBED_PREFERENCES))
    user.setdefault("progression", {"xp": 0, "lifetime_xp": 0, "prestige": 0, "watch_xp_keys": {}, "xp_events": [], "challenge_completions": {}, "achievement_xp_awarded": {}, "history_xp_seeded": False})
    if not isinstance(user["progression"], dict):
        user["progression"] = {"xp": 0, "lifetime_xp": 0, "prestige": 0, "watch_xp_keys": {}, "xp_events": [], "challenge_completions": {}, "achievement_xp_awarded": {}}
    progression = user["progression"]
    progression.setdefault("xp", 0)
    progression.setdefault("lifetime_xp", 0)
    progression.setdefault("prestige", 0)
    progression.setdefault("watch_xp_keys", {})
    progression.setdefault("xp_events", [])
    progression.setdefault("challenge_completions", {})
    progression.setdefault("achievement_xp_awarded", {})
    progression.setdefault("history_xp_seeded", False)
    if not isinstance(progression["watch_xp_keys"], dict): progression["watch_xp_keys"] = {}
    if not isinstance(progression["xp_events"], list): progression["xp_events"] = []
    if not isinstance(progression["challenge_completions"], dict): progression["challenge_completions"] = {}
    if not isinstance(progression["achievement_xp_awarded"], dict): progression["achievement_xp_awarded"] = {}
    progression["history_xp_seeded"] = bool(progression.get("history_xp_seeded", False))

    prefs = user["embed_preferences"]
    if not isinstance(prefs, dict):
        prefs = copy.deepcopy(DEFAULT_EMBED_PREFERENCES)
        user["embed_preferences"] = prefs
    # Migrate the removed legacy "Poster" style to its equivalent
    # Rich layout + Poster artwork combination.
    if prefs.get("style") == "poster":
        prefs["style"] = "rich"
        prefs["artwork"] = "poster"
    prefs.setdefault("style", "rich")
    prefs.setdefault("artwork", "backdrop")
    prefs.setdefault("activity_text", "detailed")
    prefs.setdefault("show_imdb", True)
    prefs.setdefault("show_mal", True)
    prefs.setdefault("episode_code", False)
    user.setdefault(
        "embed_preferences_custom",
        prefs != DEFAULT_EMBED_PREFERENCES,
    )


def _normalise_guild_user(user: dict) -> None:
    defaults = _default_guild_user()
    user.setdefault("history_seeded", defaults["history_seeded"])
    user.setdefault("last_checked", copy.deepcopy(defaults["last_checked"]))
    if not isinstance(user["last_checked"], dict):
        user["last_checked"] = copy.deepcopy(defaults["last_checked"])
    for media_type in ("shows", "movies", "anime"):
        user["last_checked"].setdefault(media_type, EPOCH_ISO)

    user.setdefault("activity_state", _default_activity_state())
    user.setdefault("statistics", _default_statistics())
    stats = user["statistics"]
    if not isinstance(stats, dict):
        stats = _default_statistics()
        user["statistics"] = stats
    for key, default in _default_statistics().items():
        stats.setdefault(key, copy.deepcopy(default))
    if not isinstance(stats.get("watch_dates"), dict):
        stats["watch_dates"] = {}
    if not isinstance(stats.get("titles"), dict):
        stats["titles"] = {}
    achievements = user.get("achievements")
    if not isinstance(achievements, dict):
        user["achievements"] = {}
    state = user["activity_state"]
    if not isinstance(state, dict):
        state = _default_activity_state()
        user["activity_state"] = state
    state.setdefault("statuses", {})
    state.setdefault("watch_times", {})
    state.setdefault("statuses_seeded", False)

    user.setdefault("last_poll_at", defaults["last_poll_at"])
    user.setdefault("last_success_at", defaults["last_success_at"])
    user.setdefault("last_error", defaults["last_error"])
    try:
        user["consecutive_failures"] = max(int(user.get("consecutive_failures", 0)), 0)
    except (TypeError, ValueError):
        user["consecutive_failures"] = 0

    announced = user.get("announced", [])
    if isinstance(announced, set):
        user["announced"] = announced
    elif isinstance(announced, list):
        user["announced"] = set(announced)
    else:
        user["announced"] = set()


def _normalise_guild(guild: dict) -> None:
    defaults = _default_guild()
    guild.setdefault("channel_id", defaults["channel_id"])
    guild.setdefault("embed_preferences", copy.deepcopy(DEFAULT_EMBED_PREFERENCES))
    guild.setdefault("force_embed_preferences", False)
    guild.setdefault("timezone", None)
    guild.setdefault("weekly_recap_last_sent", None)
    if guild.get("timezone") is not None and not isinstance(guild.get("timezone"), str):
        guild["timezone"] = None
    if not isinstance(guild["embed_preferences"], dict):
        guild["embed_preferences"] = copy.deepcopy(DEFAULT_EMBED_PREFERENCES)
    # Migrate the removed legacy "Poster" style to its equivalent
    # Rich layout + Poster artwork combination.
    if guild["embed_preferences"].get("style") == "poster":
        guild["embed_preferences"]["style"] = "rich"
        guild["embed_preferences"]["artwork"] = "poster"
    guild["embed_preferences"].setdefault("style", "rich")
    guild["embed_preferences"].setdefault("artwork", "backdrop")
    guild["embed_preferences"].setdefault("activity_text", "detailed")
    guild["embed_preferences"].setdefault("show_imdb", True)
    guild["embed_preferences"].setdefault("show_mal", True)
    guild["embed_preferences"].setdefault("episode_code", False)
    guild.setdefault("users", {})
    if not isinstance(guild["users"], dict):
        guild["users"] = {}
    for user in guild["users"].values():
        if isinstance(user, dict):
            _normalise_guild_user(user)


class Storage:
    def __init__(self):
        self._data = _load_from_disk()
        migrated_legacy_preferences = False

        for user in self._data["users"].values():
            if isinstance(user, dict):
                had_legacy_poster_style = (
                    isinstance(user.get("embed_preferences"), dict)
                    and user["embed_preferences"].get("style") == "poster"
                )
                _normalise_user(user)
                migrated_legacy_preferences |= had_legacy_poster_style

        for guild in self._data["guilds"].values():
            if isinstance(guild, dict):
                had_legacy_poster_style = (
                    isinstance(guild.get("embed_preferences"), dict)
                    and guild["embed_preferences"].get("style") == "poster"
                )
                _normalise_guild(guild)
                migrated_legacy_preferences |= had_legacy_poster_style

        self._dirty = migrated_legacy_preferences

    def _user(self, discord_user_id: str) -> dict | None:
        user = self._data["users"].get(discord_user_id)
        if not isinstance(user, dict):
            return None
        _normalise_user(user)
        return user

    def _guild(self, guild_id: str, create: bool = False) -> dict | None:
        guild_id = str(guild_id)
        guild = self._data["guilds"].get(guild_id)
        if guild is None and create:
            guild = _default_guild()
            self._data["guilds"][guild_id] = guild
            self._dirty = True
        if isinstance(guild, dict):
            _normalise_guild(guild)
        return guild

    def _guild_user(self, guild_id: str, discord_user_id: str, create: bool = False) -> dict | None:
        guild = self._guild(guild_id, create=create)
        if guild is None:
            return None
        user = guild["users"].get(str(discord_user_id))
        if user is None and create:
            user = _default_guild_user()
            guild["users"][str(discord_user_id)] = user
            self._dirty = True
        if isinstance(user, dict):
            _normalise_guild_user(user)
        return user

    def _migrate_legacy_guild_locked(self, guild_id: str) -> None:
        guild_id = str(guild_id)
        if guild_id in self._data["guilds"]:
            return

        old_channel = self._data.get("channel_id")
        old_prefs = self._data.get("server_embed_preferences")
        legacy_users = []

        for uid, old_user in self._data["users"].items():
            if not isinstance(old_user, dict):
                continue
            if any(
                key in old_user
                for key in ("history_seeded", "last_checked", "announced", "activity_state")
            ):
                legacy_users.append((uid, old_user))

        guild = _default_guild()
        if old_channel:
            guild["channel_id"] = old_channel
        if isinstance(old_prefs, dict):
            guild["embed_preferences"].update({
                k: old_prefs.get(k, v)
                for k, v in DEFAULT_EMBED_PREFERENCES.items()
            })

        for uid, old_user in legacy_users:
            guild_user = _default_guild_user()
            guild_user["history_seeded"] = bool(old_user.get("history_seeded", False))
            guild_user["last_checked"] = copy.deepcopy(
                old_user.get("last_checked") or guild_user["last_checked"]
            )
            guild_user["announced"] = set(old_user.get("announced", []))
            guild_user["activity_state"] = copy.deepcopy(
                old_user.get("activity_state") or _default_activity_state()
            )
            guild_user["statistics"] = copy.deepcopy(
                old_user.get("statistics") or _default_statistics()
            )
            guild["users"][uid] = guild_user

            # Preserve the user's personal preferences in the new global user record.
            _normalise_user(old_user)
            for key in (
                "simkl_token", "refresh_token", "token_expires_at",
                "simkl_username", "simkl_account_id",
                "embed_preferences", "embed_preferences_custom",
            ):
                if key in old_user:
                    self._data["users"].setdefault(uid, {})[key] = copy.deepcopy(old_user[key])

        self._data["guilds"][guild_id] = guild
        self._data.pop("channel_id", None)
        self._data.pop("server_embed_preferences", None)
        self._dirty = True

    async def flush(self) -> None:
        async with _write_lock:
            async with _lock:
                if not self._dirty:
                    return
                text = json.dumps(self._data, indent=2, default=_json_default) + "\n"
                self._dirty = False
            try:
                await asyncio.to_thread(_write_to_disk, text)
            except Exception:
                self._dirty = True
                raise

    async def ensure_guild(self, guild_id: int | str) -> None:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            self._guild(str(guild_id), create=True)
            self._dirty = True
        await self.flush()

    async def get_all(self) -> dict:
        async with _lock:
            return copy.deepcopy(self._data)

    async def get_user(self, discord_user_id: str) -> dict | None:
        async with _lock:
            user = self._user(discord_user_id)
            return copy.deepcopy(user) if user else None

    async def get_poll_targets(self, guild_id: str | None = None) -> list[dict]:
        async with _lock:
            guild_ids = [str(guild_id)] if guild_id is not None else list(self._data["guilds"].keys())
            targets = []
            for gid in guild_ids:
                guild = self._guild(gid)
                if not guild or not guild.get("channel_id"):
                    continue
                for uid in guild["users"].keys():
                    user = self._user(uid)
                    if not user or not user.get("simkl_token"):
                        continue
                    guild_user = self._guild_user(gid, uid)
                    if not guild_user:
                        continue
                    targets.append({
                        "guild_id": gid,
                        "channel_id": guild["channel_id"],
                        "discord_user_id": uid,
                        "user_data": copy.deepcopy(user),
                        "guild_user_data": copy.deepcopy(guild_user),
                    })
            return targets

    async def get_channel(self, guild_id: int | str) -> int | None:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            guild = self._guild(guild_id, create=True)
            return guild.get("channel_id")

    async def set_channel(self, guild_id: int | str, channel_id: int) -> None:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            guild = self._guild(guild_id, create=True)
            guild["channel_id"] = channel_id
            self._dirty = True
        await self.flush()

    async def get_timezone(self, guild_id: int | str) -> dict:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            guild = self._guild(guild_id, create=True)
            configured = guild.get("timezone")
            if configured:
                try:
                    ZoneInfo(configured)
                    return {"name": configured, "source": "server"}
                except (TypeError, ValueError, ZoneInfoNotFoundError):
                    pass
            default_name = _default_timezone_name()
            try:
                ZoneInfo(default_name)
            except (TypeError, ValueError, ZoneInfoNotFoundError):
                default_name = "UTC"
            return {"name": default_name, "source": "environment" if os.getenv("SIMKL_DEFAULT_TIMEZONE") else "built-in"}

    async def set_timezone(self, guild_id: int | str, timezone_name: str | None) -> None:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            guild = self._guild(guild_id, create=True)
            guild["timezone"] = timezone_name.strip() if timezone_name else None
            self._dirty = True
        await self.flush()

    async def get_weekly_recap_last_sent(self, guild_id: int | str) -> str | None:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            guild = self._guild(guild_id, create=True)
            return guild.get("weekly_recap_last_sent")

    async def set_weekly_recap_last_sent(self, guild_id: int | str, week_key: str) -> None:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            guild = self._guild(guild_id, create=True)
            guild["weekly_recap_last_sent"] = week_key
            self._dirty = True
        await self.flush()

    async def get_server_embed_preferences(self, guild_id: int | str) -> dict:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            guild = self._guild(guild_id, create=True)
            return copy.deepcopy(guild["embed_preferences"])

    async def set_server_embed_preferences(self, guild_id: int | str, style=None, artwork=None, activity_text=None, show_imdb=None, show_mal=None, episode_code=None, force_override=None) -> None:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            guild = self._guild(guild_id, create=True)
            prefs = guild["embed_preferences"]
            if style is not None:
                prefs["style"] = style
            if artwork is not None:
                prefs["artwork"] = artwork
            if activity_text is not None:
                prefs["activity_text"] = activity_text
            if show_imdb is not None:
                prefs["show_imdb"] = bool(show_imdb)
            if show_mal is not None:
                prefs["show_mal"] = bool(show_mal)
            if episode_code is not None:
                prefs["episode_code"] = bool(episode_code)
            if force_override is not None:
                guild["force_embed_preferences"] = bool(force_override)
            self._dirty = True
        await self.flush()

    async def reset_server_embed_preferences(self, guild_id: int | str) -> None:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            guild = self._guild(guild_id, create=True)
            guild["embed_preferences"] = copy.deepcopy(DEFAULT_EMBED_PREFERENCES)
            guild["force_embed_preferences"] = False
            self._dirty = True
        await self.flush()

    async def get_server_embed_force_override(self, guild_id: int | str) -> bool:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            guild = self._guild(guild_id, create=True)
            return bool(guild.get("force_embed_preferences", False))

    async def get_embed_preferences(self, guild_id: str | int, discord_user_id: str) -> dict:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            guild = self._guild(guild_id, create=True)
            user = self._user(discord_user_id)
            if guild.get("force_embed_preferences", False):
                return copy.deepcopy(guild["embed_preferences"])
            if user and user.get("embed_preferences_custom", False):
                return copy.deepcopy(user["embed_preferences"])
            return copy.deepcopy(guild["embed_preferences"])

    async def set_embed_preferences(self, discord_user_id: str, style=None, artwork=None, activity_text=None, show_imdb=None, show_mal=None, episode_code=None) -> None:
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
            if show_imdb is not None:
                prefs["show_imdb"] = bool(show_imdb)
            if show_mal is not None:
                prefs["show_mal"] = bool(show_mal)
            if episode_code is not None:
                prefs["episode_code"] = bool(episode_code)
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

    async def reset_user_tracking(self, guild_id: str | int, discord_user_id: str, start_time_iso: str) -> bool:
        """Reset one user's server-local tracking state while preserving their SIMKL link and preferences."""
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            guild = self._guild(guild_id)
            if not guild or str(discord_user_id) not in guild["users"]:
                return False
            guild["users"][str(discord_user_id)] = _default_guild_user(start_time_iso)
            self._dirty = True
        await self.flush()
        return True

    async def get_progression(self, discord_user_id: str) -> dict:
        async with _lock:
            user = self._user(discord_user_id)
            return copy.deepcopy(user.get("progression", {})) if user else {}

    async def mark_history_xp_seeded(self, discord_user_id: str) -> None:
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return
            user["progression"]["history_xp_seeded"] = True
            self._dirty = True
        await self.flush()

    async def award_watch_xp(self, discord_user_id: str, event_key: str, media_type: str, title: str, watched_at: str, amount: int) -> dict:
        """Award watch XP once globally per SIMKL watch event."""
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return {"awarded": False, "amount": 0, "progression": {}}
            progression = user["progression"]
            if event_key in progression["watch_xp_keys"]:
                return {"awarded": False, "amount": 0, "progression": copy.deepcopy(progression)}
            progression["watch_xp_keys"][event_key] = watched_at
            xp = max(0, int(amount))
            progression["xp"] = int(progression.get("xp", 0)) + xp
            progression["lifetime_xp"] = int(progression.get("lifetime_xp", 0)) + xp
            progression["xp_events"].append({"at": watched_at, "amount": xp, "media_type": media_type, "title": title or "Untitled", "event_key": event_key})
            progression["xp_events"] = [event for event in progression["xp_events"] if str(event.get("at") or "") >= "2025-01-01T00:00:00Z"]
            progression["watch_xp_keys"] = {key: stamp for key, stamp in progression["watch_xp_keys"].items() if str(stamp or "") >= "2025-01-01T00:00:00Z"}
            self._dirty = True
            result = copy.deepcopy(progression)
        await self.flush()
        return {"awarded": True, "amount": xp, "progression": result}

    async def complete_challenge(self, discord_user_id: str, challenge_id: str, period_key: str, amount: int) -> bool:
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return False
            completed = user["progression"]["challenge_completions"].setdefault(period_key, {})
            if challenge_id in completed:
                return False
            completed[challenge_id] = {"completed_at": datetime.now(timezone.utc).isoformat(), "xp": int(amount)}
            progression = user["progression"]
            xp = max(0, int(amount))
            progression["xp"] = int(progression.get("xp", 0)) + xp
            progression["lifetime_xp"] = int(progression.get("lifetime_xp", 0)) + xp
            self._dirty = True
        await self.flush()
        return True

    async def get_challenge_state(self, discord_user_id: str) -> dict:
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return {}
            return {"xp_events": copy.deepcopy(user["progression"].get("xp_events", [])), "challenge_completions": copy.deepcopy(user["progression"].get("challenge_completions", {}))}

    async def prestige_user(self, discord_user_id: str) -> bool:
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return False
            user["progression"]["xp"] = 0
            user["progression"]["prestige"] = int(user["progression"].get("prestige", 0)) + 1
            self._dirty = True
        await self.flush()
        return True

    async def get_activity_state(self, guild_id: str | int, discord_user_id: str) -> dict:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            user = self._guild_user(guild_id, discord_user_id)
            return copy.deepcopy(user["activity_state"]) if user else _default_activity_state()

    async def update_activity_state(self, guild_id: str | int, discord_user_id: str, statuses=None, watch_times=None, statuses_seeded=None, flush: bool = True) -> None:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            user = self._guild_user(guild_id, discord_user_id)
            if not user:
                return
            if statuses:
                user["activity_state"]["statuses"].update(statuses)
            if watch_times:
                user["activity_state"]["watch_times"].update(watch_times)
            if statuses_seeded is not None:
                user["activity_state"]["statuses_seeded"] = statuses_seeded
            self._dirty = True
        if flush:
            await self.flush()

    async def get_statistics(self, guild_id: str | int, discord_user_id: str) -> dict:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            user = self._guild_user(guild_id, discord_user_id)
            return copy.deepcopy(user["statistics"]) if user else _default_statistics()

    async def get_achievements(self, guild_id: str | int, discord_user_id: str) -> dict:
        """Return unlocked achievements keyed by achievement ID."""
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            user = self._guild_user(guild_id, discord_user_id)
            return copy.deepcopy(user.get("achievements", {})) if user else {}

    async def unlock_achievement(
        self,
        guild_id: str | int,
        discord_user_id: str,
        achievement_id: str,
        unlocked_at: str,
        flush: bool = True,
    ) -> bool:
        """Unlock an achievement once; return True only for a new unlock."""
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            user = self._guild_user(guild_id, discord_user_id)
            if not user:
                return False
            achievements = user.setdefault("achievements", {})
            if achievement_id in achievements:
                return False
            achievements[achievement_id] = {"unlocked_at": unlocked_at}
            self._dirty = True
        if flush:
            await self.flush()
        return True

    async def award_achievement_xp(
        self,
        discord_user_id: str,
        achievement_id: str,
        amount: int,
        title: str,
        awarded_at: str,
    ) -> dict:
        """Award achievement XP exactly once, including for old unlocks."""
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return {"awarded": False, "amount": 0, "progression": {}}
            progression = user["progression"]
            awarded = progression.setdefault("achievement_xp_awarded", {})
            if achievement_id in awarded:
                return {"awarded": False, "amount": 0, "progression": copy.deepcopy(progression)}
            xp = max(0, int(amount))
            awarded[achievement_id] = awarded_at
            progression["xp"] = int(progression.get("xp", 0)) + xp
            progression["lifetime_xp"] = int(progression.get("lifetime_xp", 0)) + xp
            progression["xp_events"].append({
                "at": awarded_at,
                "amount": xp,
                "media_type": "achievement",
                "title": title or "Achievement",
                "event_key": f"achievement:{achievement_id}",
                "achievement_id": achievement_id,
            })
            self._dirty = True
            result = copy.deepcopy(progression)
        await self.flush()
        return {"awarded": True, "amount": xp, "progression": result}

    async def record_watch(
        self,
        guild_id: str | int,
        discord_user_id: str,
        media_type: str,
        title: str,
        item_key: str,
        watched_at: str,
        flush: bool = True,
    ) -> None:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            user = self._guild_user(guild_id, discord_user_id)
            if not user:
                return
            stats = user["statistics"]
            if media_type == "anime_episode":
                stats["episodes_watched"] += 1
                stats["anime_episodes_watched"] += 1
                category = "anime_episodes"
            elif media_type == "anime_movie":
                stats["movies_watched"] += 1
                stats["anime_movies_watched"] += 1
                category = "anime_movies"
            elif media_type == "movie":
                stats["movies_watched"] += 1
                category = "movies"
            else:
                stats["episodes_watched"] += 1
                category = "episodes"

            day = None
            if watched_at:
                try:
                    watched_dt = datetime.fromisoformat(watched_at.replace("Z", "+00:00"))
                    if watched_dt.tzinfo is None:
                        watched_dt = watched_dt.replace(tzinfo=timezone.utc)
                    guild = self._guild(guild_id, create=True)
                    timezone_name = guild.get("timezone")
                    day = watched_dt.astimezone(_resolve_timezone(timezone_name)).date().isoformat()
                except (TypeError, ValueError):
                    day = watched_at[:10]
            if day:
                daily = stats["watch_dates"].setdefault(day, {})
                daily[category] = int(daily.get(category, 0)) + 1
                daily["total"] = int(daily.get("total", 0)) + 1

            title_record = stats["titles"].setdefault(
                item_key,
                {"title": title or "Untitled", "type": media_type, "count": 0, "last_watched": None},
            )
            title_record["title"] = title or title_record.get("title") or "Untitled"
            title_record["type"] = media_type
            title_record["count"] = int(title_record.get("count", 0)) + 1
            title_record["last_watched"] = watched_at
            self._dirty = True
        if flush:
            await self.flush()

    async def get_last_checked(self, guild_id: str | int, discord_user_id: str) -> dict:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            user = self._guild_user(guild_id, discord_user_id)
            return copy.deepcopy(user["last_checked"]) if user else {}

    async def update_last_checked(self, guild_id: str | int, discord_user_id: str, category: str, iso_timestamp: str) -> None:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            user = self._guild_user(guild_id, discord_user_id)
            if not user:
                return
            user["last_checked"][category] = iso_timestamp
            self._dirty = True

    async def update_poll_health(
        self,
        guild_id: str | int,
        discord_user_id: str,
        last_poll_at: str | None = None,
        last_success_at: str | None = None,
        last_error: str | None = None,
        consecutive_failures: int | None = None,
        flush: bool = True,
    ) -> None:
        """Update persistent polling health information for one guild/user."""
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            user = self._guild_user(guild_id, discord_user_id)
            if not user:
                return
            if last_poll_at is not None:
                user["last_poll_at"] = last_poll_at
            if last_success_at is not None:
                user["last_success_at"] = last_success_at
            if last_error is not None:
                user["last_error"] = last_error
            if consecutive_failures is not None:
                user["consecutive_failures"] = max(int(consecutive_failures), 0)
            self._dirty = True
        if flush:
            await self.flush()

    async def add_announced(self, guild_id: str | int, discord_user_id: str, keys: list[str]) -> None:
        if not keys:
            return
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            user = self._guild_user(guild_id, discord_user_id)
            if not user:
                return
            user["announced"].update(keys)
            self._dirty = True

    async def is_announced(self, guild_id: str | int, discord_user_id: str, key: str) -> bool:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            user = self._guild_user(guild_id, discord_user_id)
            return bool(user) and key in user["announced"]

    async def get_announced(self, guild_id: str | int, discord_user_id: str) -> set[str]:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            user = self._guild_user(guild_id, discord_user_id)
            return set(user["announced"]) if user else set()

    async def mark_history_seeded(self, guild_id: str | int, discord_user_id: str, keys: list[str]) -> bool:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            user = self._guild_user(guild_id, discord_user_id)
            if not user:
                return False
            user["announced"].update(keys)
            user["history_seeded"] = True
            self._dirty = True
        await self.flush()
        return True

    async def link_user(self, guild_id: str | int, discord_user_id: str, access_token: str, refresh_token: str | None, simkl_username: str, start_time_iso: str, token_expires_at: str | None = None, simkl_account_id: int | str | None = None) -> None:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            existing = self._user(discord_user_id)
            if existing:
                personal = {
                    "embed_preferences": copy.deepcopy(existing.get("embed_preferences", DEFAULT_EMBED_PREFERENCES)),
                    "embed_preferences_custom": existing.get("embed_preferences_custom", False),
                    "progression": copy.deepcopy(existing.get("progression", {"xp": 0, "lifetime_xp": 0, "prestige": 0, "watch_xp_keys": {}, "xp_events": [], "challenge_completions": {}, "achievement_xp_awarded": {}})),
                }
            else:
                personal = {
                    "embed_preferences": copy.deepcopy(DEFAULT_EMBED_PREFERENCES),
                    "embed_preferences_custom": False,
                }
            self._data["users"][discord_user_id] = {
                "simkl_token": access_token,
                "refresh_token": refresh_token,
                "token_expires_at": token_expires_at,
                "simkl_username": simkl_username,
                "simkl_account_id": simkl_account_id,
                **personal,
            }
            self._data["guilds"][str(guild_id)]["users"][discord_user_id] = _default_guild_user(start_time_iso)
            self._dirty = True
        await self.flush()

    async def unlink_user(self, guild_id: str | int, discord_user_id: str) -> bool:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            guild = self._guild(guild_id)
            if not guild or discord_user_id not in guild["users"]:
                return False
            del guild["users"][discord_user_id]

            # Authentication is global and can be reused in other servers.
            still_linked = any(
                isinstance(g, dict) and discord_user_id in (g.get("users") or {})
                for g in self._data["guilds"].values()
            )
            if not still_linked:
                self._data["users"].pop(discord_user_id, None)

            self._dirty = True
        await self.flush()
        return True

    async def update_tokens(self, discord_user_id: str, access_token: str, refresh_token: str | None, token_expires_at: str | None = None) -> None:
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

    async def get_guild_statistics(self, guild_id: str | int) -> list[dict]:
        async with _lock:
            self._migrate_legacy_guild_locked(str(guild_id))
            guild = self._guild(guild_id)
            if not guild:
                return []
            results = []
            for uid, user in guild["users"].items():
                _normalise_guild_user(user)
                global_user = self._user(uid) or {}
                results.append({
                    "discord_user_id": uid,
                    "simkl_username": global_user.get("simkl_username", "unknown"),
                    "statistics": copy.deepcopy(user["statistics"]),
                })
            return results

    async def set_account_id(self, discord_user_id: str, simkl_account_id: int | str) -> None:
        async with _lock:
            user = self._user(discord_user_id)
            if not user:
                return
            user["simkl_account_id"] = simkl_account_id
            self._dirty = True
        await self.flush()


storage = Storage()
