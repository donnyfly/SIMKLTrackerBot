"""
SIMKL Watch Activity Tracker for Discord (AUTH V2)

Features:
- Uses AUTH V2 Device / PIN flow
- Automatic token refresh
- Proactive token refresh before expiry
- Smart polling via /sync/activities
- 60-minute polling by default
- Prevents overlapping polling cycles
- Cooldown for manual /simkl-checknow requests
- Groups consecutive watched episodes into ranges
- Clickable SIMKL titles in embeds
- TMDB landscape episode stills for TV/anime
- TMDB landscape backdrops for movies
- SIMKL poster fallback when TMDB has no suitable image
- Shows episode titles for individual episodes
- Uses a representative still for episode ranges
- Uses TVDB mapping to improve anime TMDB season matching
- Posts bulk-marked episodes without ever posting old history
  (a user's existing history is recorded once, when they link)
"""

import asyncio
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from dotenv import load_dotenv

from simkl_client import SimklAuthError, SimklClient, SimklSlowDown
from storage import EPOCH_ISO, storage
from tmdb_client import TmdbClient


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SIMKL_CLIENT_ID = os.getenv("SIMKL_CLIENT_ID")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
GUILD_ID = os.getenv("GUILD_ID")

# How often SIMKL activity is checked. Recommended: 60 minutes.
try:
    POLL_INTERVAL_MINUTES = max(
        int(os.getenv("POLL_INTERVAL_MINUTES", "60")),
        1,
    )
except ValueError:
    POLL_INTERVAL_MINUTES = 60

if not DISCORD_BOT_TOKEN or not SIMKL_CLIENT_ID:
    raise SystemExit("Missing DISCORD_BOT_TOKEN or SIMKL_CLIENT_ID.")

if not TMDB_API_KEY:
    raise SystemExit("Missing TMDB_API_KEY.")


# ---------------------------------------------------------------------------
# Constants and shared state
# ---------------------------------------------------------------------------

MEDIA_TYPES = ("shows", "anime", "movies")
WATCHLIST_STATUSES = ("watching", "plantowatch", "completed", "dropped")
STATUS_TEXT = {"watching": "started watching", "plantowatch": "planned to watch", "completed": "completed", "dropped": "dropped"}
EMBED_STYLES = ("rich", "minimal", "poster")
ARTWORK_STYLES = ("auto", "poster")
ACTIVITY_TEXT_STYLES = ("short", "detailed")

# Key used for each media type in the /sync/activities response.
ACTIVITY_KEYS = {
    "shows": "tv_shows",
    "anime": "anime",
    "movies": "movies",
}

# Embed colour and footer label for each media type.
MEDIA_STYLES = {
    "shows": (0x3498DB, "📺 TV"),
    "anime": (0xE91E63, "🌸 Anime"),
    "movies": (0xF1C40F, "🎬 Movie"),
}

# Full-history requests can be large.
HISTORY_FETCH_TIMEOUT_SECONDS = 120

# Prevents the background poll and /simkl-checknow from running together.
poll_lock = asyncio.Lock()

# Prevent /simkl-checknow from being spammed repeatedly.
CHECKNOW_COOLDOWN_SECONDS = 30
last_checknow_at = 0.0

# Discord user IDs with a /simkl-link flow currently in progress.
linking_users: set[str] = set()

# Users whose SIMKL account ID has already been looked up since startup.
profile_lookup_attempted: set[str] = set()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

log = logging.getLogger("simkl-bot")


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

simkl = SimklClient(SIMKL_CLIENT_ID)
tmdb = TmdbClient(TMDB_API_KEY)

intents = discord.Intents.default()


class SimklBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Slash commands synced to guild %s.", GUILD_ID)
        else:
            await self.tree.sync()
            log.info("Slash commands synced globally.")

    async def close(self):
        try:
            await simkl.close()
        except Exception:
            pass

        try:
            await tmdb.close()
        except Exception:
            pass

        await super().close()


bot = SimklBot()


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------


def to_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    return to_iso(datetime.now(timezone.utc))


def parse_iso(value: str) -> datetime:
    """Parse a SIMKL timestamp; unparseable values become the earliest time."""
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt

    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def calculate_token_expiry(expires_in) -> str | None:
    """Convert SIMKL's expires_in into an absolute UTC timestamp."""
    if expires_in is None:
        return None

    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None

    if seconds <= 0:
        return None

    return to_iso(
        datetime.now(timezone.utc)
        + timedelta(seconds=seconds)
    )


def is_admin(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False

    if GUILD_ID and interaction.guild.id != int(GUILD_ID):
        return False

    return bool(interaction.user.guild_permissions.manage_guild)


def simkl_poster_url(
    poster_path: str | None,
    size: str = "_m",
) -> str | None:
    """
    Build a SIMKL poster URL.

    "_m" is the larger poster.
    """
    if not poster_path:
        return None

    return (
        "https://wsrv.nl/?url=https://simkl.in/posters/"
        f"{poster_path}{size}.webp&q=90"
    )


def simkl_profile_url(simkl_account_id) -> str | None:
    if not simkl_account_id:
        return None

    return f"https://simkl.com/{simkl_account_id}/"


def account_id_from_settings(settings) -> int | str | None:
    if not isinstance(settings, dict):
        return None

    return (settings.get("account") or {}).get("id")


def simkl_title_url(
    media_type: str,
    simkl_id,
    slug: str | None = None,
) -> str:
    if media_type == "movies":
        base = "https://simkl.com/movies"
    elif media_type == "anime":
        base = "https://simkl.com/anime"
    else:
        base = "https://simkl.com/tv"

    if slug:
        return f"{base}/{simkl_id}/{slug}"

    return f"{base}/{simkl_id}"


def episode_key(
    media_type: str,
    simkl_id,
    season_num,
    ep_num,
) -> str:
    return f"{media_type}:{simkl_id}:{season_num}:{ep_num}"


def movie_key(media_type: str, simkl_id) -> str:
    return f"{media_type}:{simkl_id}"


# ---------------------------------------------------------------------------
# SIMKL episode parsing
# ---------------------------------------------------------------------------


def iter_show_episodes(media_type: str, items):
    """
    Yield one dict per valid episode in a SIMKL shows/anime response.

    For anime we retain BOTH:
    - the original SIMKL season number
    - the mapped TVDB season number

    The mapped season is used for display/storage when available, while
    the original season remains available for TMDB fallback matching.
    """

    for item in items or []:
        show = item.get("show") or {}
        ids = show.get("ids") or {}

        simkl_id = ids.get("simkl")

        if simkl_id is None:
            continue

        anime_mapped_seasons = item.get("mapped_tvdb_seasons") or []

        for season in item.get("seasons") or []:
            original_season_num = season.get("number")

            if original_season_num is None:
                continue

            mapped_tvdb_season_num = None

            if media_type == "anime" and anime_mapped_seasons:
                if (
                    isinstance(original_season_num, int)
                    and original_season_num > 0
                    and original_season_num <= len(anime_mapped_seasons)
                ):
                    mapped_tvdb_season_num = anime_mapped_seasons[
                        original_season_num - 1
                    ]

            season_num = (
                mapped_tvdb_season_num
                if mapped_tvdb_season_num is not None
                else original_season_num
            )

            for ep in season.get("episodes") or []:
                ep_num = ep.get("number")

                if ep_num is None:
                    continue

                watched_raw = ep.get("watched_at")

                yield {
                    "show_title": show.get("title", "a show"),
                    "simkl_id": simkl_id,
                    "tmdb_id": ids.get("tmdb"),
                    "tvdb_id": ids.get("tvdb"),
                    "anilist_id": ids.get("anilist"),
                    "kitsu_id": ids.get("kitsu"),
                    "slug": ids.get("slug"),
                    "poster": show.get("poster"),

                    # Display/storage season.
                    "season_num": season_num,

                    # Original SIMKL anime season.
                    "original_season_num": original_season_num,

                    # TVDB mapped season, when available.
                    "mapped_tvdb_season_num": mapped_tvdb_season_num,

                    "episode_number": ep_num,
                    "episode_title": ep.get("title"),
                    "watched_raw": watched_raw,
                    "watched_dt": (
                        parse_iso(watched_raw)
                        if watched_raw
                        else None
                    ),
                    "key": episode_key(
                        media_type,
                        simkl_id,
                        season_num,
                        ep_num,
                    ),
                }


# ---------------------------------------------------------------------------
# Episode grouping
# ---------------------------------------------------------------------------


def format_episode_range(
    season_number: int | None,
    start_episode: int,
    end_episode: int,
) -> str:
    if season_number is None:
        if start_episode == end_episode:
            return f"E{start_episode:02d}"

        return (
            f"E{start_episode:02d}-E{end_episode:02d}"
        )

    if start_episode == end_episode:
        return (
            f"S{season_number:02d}"
            f"E{start_episode:02d}"
        )

    return (
        f"S{season_number:02d}"
        f"E{start_episode:02d}"
        f"-E{end_episode:02d}"
    )


def group_consecutive_episodes(episodes):
    """Split episodes into runs of consecutive episode numbers."""

    if not episodes:
        return []

    episodes = sorted(
        episodes,
        key=lambda x: x["episode_number"],
    )

    groups = []
    current = [episodes[0]]

    for episode in episodes[1:]:
        if (
            episode["episode_number"]
            == current[-1]["episode_number"] + 1
        ):
            current.append(episode)
        else:
            groups.append(current)
            current = [episode]

    groups.append(current)

    return groups


# ---------------------------------------------------------------------------
# TMDB episode helpers
# ---------------------------------------------------------------------------


async def find_episode_tmdb_data(
    media_type: str,
    episode: dict,
) -> dict | None:
    """
    Find the best TMDB match for an episode.

    Normal TV:
        Try the SIMKL TMDB series ID directly.

    Anime:
        Try the mapped/original season candidates and also resolve the
        SIMKL TVDB ID through TMDB when necessary.
    """

    tmdb_id = episode.get("tmdb_id")
    tvdb_id = episode.get("tvdb_id")
    episode_number = episode.get("episode_number")
    episode_title = episode.get("episode_title")

    if episode_number is None:
        return None

    # ---------------------------------------------------------------
    # Anime
    # ---------------------------------------------------------------

    if media_type == "anime":
        season_candidates = []

        for value in (
            episode.get("season_num"),
            episode.get("mapped_tvdb_season_num"),
            episode.get("original_season_num"),
        ):
            if value is None:
                continue

            try:
                value = int(value)
            except (TypeError, ValueError):
                continue

            if value not in season_candidates:
                season_candidates.append(value)

        result = await tmdb.find_anime_episode(
            tmdb_id,
            tvdb_id,
            season_candidates,
            episode_number,
            episode_title=episode_title,
        )

        if result:
            return result

        return None

    # ---------------------------------------------------------------
    # Normal TV
    # ---------------------------------------------------------------

    if tmdb_id is not None:
        try:
            tmdb_episode = await tmdb.get_episode_details(
                tmdb_id,
                episode.get("season_num"),
                episode_number,
            )
        except Exception:
            tmdb_episode = None

        if tmdb_episode:
            return {
                "series_id": int(tmdb_id),
                "season_number": int(episode.get("season_num")),
                "episode_number": int(episode_number),
                "episode": tmdb_episode,
            }

    # ---------------------------------------------------------------
    # TVDB fallback
    # ---------------------------------------------------------------

    if tvdb_id is not None:
        resolved_series_id = await tmdb.find_series_by_tvdb(tvdb_id)

        if resolved_series_id:
            try:
                tmdb_episode = await tmdb.get_episode_details(
                    resolved_series_id,
                    episode.get("season_num"),
                    episode_number,
                )
            except Exception:
                tmdb_episode = None

            if tmdb_episode:
                return {
                    "series_id": resolved_series_id,
                    "season_number": int(
                        episode.get("season_num")
                    ),
                    "episode_number": int(episode_number),
                    "episode": tmdb_episode,
                }

    return None


async def get_episode_media(
    media_type: str,
    episode: dict,
) -> tuple[str | None, str | None]:
    """
    Return:

        (still_url, episode_title)

    The TMDB episode still is preferred.
    SIMKL's episode title remains the preferred displayed title.
    """

    result = await find_episode_tmdb_data(
        media_type,
        episode,
    )

    if not result:
        return None, episode.get("episode_title")

    series_id = result.get("series_id")
    season_number = result.get("season_number")
    episode_number = result.get("episode_number")

    still_url = None

    if (
        series_id is not None
        and season_number is not None
        and episode_number is not None
    ):
        try:
            still_url = await tmdb.get_episode_still(
                series_id,
                season_number,
                episode_number,
            )
        except Exception:
            log.warning(
                "Could not retrieve TMDB still for %s S%sE%s.",
                series_id,
                season_number,
                episode_number,
                exc_info=True,
            )

    tmdb_episode = result.get("episode") or {}
    tmdb_episode_title = tmdb_episode.get("name")

    episode_title = (
        episode.get("episode_title")
        or tmdb_episode_title
    )

    return still_url, episode_title


# ---------------------------------------------------------------------------
# Embeds
# ---------------------------------------------------------------------------


def _default_embed_preferences() -> dict:
    return {"style": "rich", "artwork": "auto", "activity_text": "short"}


async def get_embed_preferences(discord_user_id: str) -> dict:
    return await storage.get_embed_preferences(discord_user_id)


def build_activity_embed(
    media_type: str,
    description: str,
    timestamp: datetime,
    display_name: str,
    member,
    image_url: str | None,
    profile_url: str | None,
    title: str | None = None,
    title_url: str | None = None,
    poster_url: str | None = None,
    preferences: dict | None = None,
) -> discord.Embed:
    color, label = MEDIA_STYLES[media_type]
    prefs = {**_default_embed_preferences(), **(preferences or {})}
    style = prefs.get("style", "rich")
    artwork = prefs.get("artwork", "auto")
    embed = discord.Embed(title=title, url=title_url, description=description, color=color, timestamp=timestamp)
    embed.set_author(name=f"{display_name}'s Activity", url=profile_url, icon_url=member.display_avatar.url if member else None)
    selected_image = poster_url if (artwork == "poster" or style == "poster") else image_url
    if not selected_image:
        selected_image = poster_url or image_url
    if selected_image:
        if style == "minimal":
            embed.set_thumbnail(url=selected_image)
        else:
            embed.set_image(url=selected_image)
    embed.set_footer(text=f"{label} · SIMKL")
    return embed


async def send_embed(channel, embed: discord.Embed, what: str) -> bool:
    try:
        await channel.send(embed=embed)
        return True
    except Exception:
        log.exception("Failed to send %s embed.", what)
        return False



# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


async def get_valid_token(
    discord_user_id: str,
    user_data: dict,
) -> str:
    access_token = user_data.get("simkl_token")

    if not access_token:
        raise SimklAuthError(
            "No SIMKL access token stored."
        )

    token_expires_at = user_data.get(
        "token_expires_at"
    )

    if token_expires_at:
        expiry_dt = parse_iso(token_expires_at)

        if expiry_dt <= (
            datetime.now(timezone.utc)
            + timedelta(days=1)
        ):
            log.info(
                "SIMKL token for user %s is expiring "
                "within 24 hours. Refreshing proactively.",
                discord_user_id,
            )

            try:
                return await refresh_user_token(
                    discord_user_id,
                    user_data,
                )
            except SimklAuthError:
                log.warning(
                    "Proactive SIMKL token refresh failed "
                    "for user %s. Continuing with existing token.",
                    discord_user_id,
                )

    return access_token


async def refresh_user_token(
    discord_user_id: str,
    user_data: dict,
) -> str:
    refresh_token = user_data.get(
        "refresh_token"
    )

    if not refresh_token:
        raise SimklAuthError(
            "SIMKL token expired and no refresh token is available."
        )

    new_tokens = await simkl.refresh_token(
        refresh_token
    )

    if not new_tokens:
        raise SimklAuthError(
            "SIMKL token refresh failed."
        )

    new_access_token = new_tokens.get(
        "access_token"
    )

    if not new_access_token:
        raise SimklAuthError(
            "SIMKL token refresh returned no access token."
        )

    new_refresh_token = new_tokens.get(
        "refresh_token"
    )

    token_expires_at = calculate_token_expiry(
        new_tokens.get("expires_in")
    )

    await storage.update_tokens(
        discord_user_id,
        new_access_token,
        new_refresh_token,
        token_expires_at,
    )

    user_data["simkl_token"] = new_access_token

    if new_refresh_token:
        user_data["refresh_token"] = new_refresh_token

    user_data["token_expires_at"] = (
        token_expires_at
    )

    log.info(
        "Refreshed SIMKL token for user %s.",
        discord_user_id,
    )

    return new_access_token


async def call_with_refresh(
    discord_user_id: str,
    user_data: dict,
    token: str,
    func,
    *args,
    **kwargs,
):
    """
    Call func(token, *args, **kwargs).

    If SIMKL says the token is invalid, refresh it once
    and retry the same call.

    Returns:
        (result, token)
    """

    try:
        return (
            await func(token, *args, **kwargs),
            token,
        )

    except SimklAuthError:
        token = await refresh_user_token(
            discord_user_id,
            user_data,
        )

        return (
            await func(
                token,
                *args,
                **kwargs,
            ),
            token,
        )


# ---------------------------------------------------------------------------
# History seeding
# ---------------------------------------------------------------------------


async def seed_history(
    discord_user_id: str,
    user_data: dict,
    token: str,
) -> str:
    """
    Record everything the user had already watched as announced.

    Existing history is never posted.

    Anything watched after the user's last_checked timestamp
    is left available for normal polling.
    """

    last_checked = (
        user_data.get("last_checked")
        or {}
    )

    keys = []
    statuses = {}
    watch_times = {}

    for media_type in MEDIA_TYPES:
        since_dt = parse_iso(
            last_checked.get(
                media_type,
                EPOCH_ISO,
            )
        )

        items, token = await call_with_refresh(
            discord_user_id,
            user_data,
            token,
            simkl.get_all_items,
            media_type,
            timeout=HISTORY_FETCH_TIMEOUT_SECONDS,
        )

        if media_type == "movies":
            for item in items or []:
                movie = item.get("movie") or {}
                simkl_id = (
                    movie.get("ids") or {}
                ).get("simkl")

                if simkl_id is None:
                    continue

                watched_raw = item.get(
                    "last_watched_at"
                )

                if (
                    watched_raw
                    and parse_iso(watched_raw) > since_dt
                ):
                    continue

                key = movie_key(media_type, simkl_id)
                keys.append(key)
                if item.get("status"):
                    statuses[f"{media_type}:{simkl_id}"] = item["status"]
                if watched_raw:
                    watch_times[key] = watched_raw

        else:
            for raw_item in items or []:
                raw_show = raw_item.get("show") or {}
                raw_ids = raw_show.get("ids") or {}
                raw_simkl_id = raw_ids.get("simkl")
                raw_status = raw_item.get("status")
                if raw_simkl_id is not None and raw_status:
                    statuses[f"{media_type}:{raw_simkl_id}"] = raw_status
            for ep in iter_show_episodes(
                media_type,
                items,
            ):
                if (
                    ep["watched_dt"] is not None
                    and ep["watched_dt"] > since_dt
                ):
                    continue

                keys.append(ep["key"])
                if ep.get("watched_raw"):
                    watch_times[ep["key"]] = ep["watched_raw"]

    await storage.mark_history_seeded(discord_user_id, keys)
    await storage.update_activity_state(discord_user_id, statuses=statuses, watch_times=watch_times)

    user_data["history_seeded"] = True

    log.info(
        "Recorded %d existing SIMKL history item(s) "
        "for user %s.",
        len(keys),
        discord_user_id,
    )

    return token


# ---------------------------------------------------------------------------
# /simkl-link
# ---------------------------------------------------------------------------


@bot.tree.command(
    name="simkl-link",
    description=(
        "Link your SIMKL account so your watch "
        "activity gets posted."
    ),
)
async def simkl_link(
    interaction: discord.Interaction,
):
    discord_user_id = str(
        interaction.user.id
    )

    if discord_user_id in linking_users:
        await interaction.response.send_message(
            "You already have a linking code waiting. "
            "Finish that one first, or wait for it to expire.",
            ephemeral=True,
        )
        return

    linking_users.add(
        discord_user_id
    )

    try:
        await run_link_flow(
            interaction,
            discord_user_id,
        )
    finally:
        linking_users.discard(
            discord_user_id
        )


async def run_link_flow(
    interaction: discord.Interaction,
    discord_user_id: str,
):
    await interaction.response.defer(
        ephemeral=True
    )

    try:
        pin_data = await simkl.start_pin_auth()

    except Exception as e:
        log.exception(
            "Failed to start SIMKL PIN authentication."
        )

        await interaction.followup.send(
            f"Couldn't reach SIMKL: {e}",
            ephemeral=True,
        )
        return

    user_code = pin_data["user_code"]
    device_code = pin_data["device_code"]

    verification_url = pin_data.get(
        "verification_uri",
        "https://simkl.com/pin",
    )

    expires_in = pin_data.get(
        "expires_in",
        900,
    )

    interval = pin_data.get(
        "interval",
        5,
    )

    await interaction.followup.send(
        f"**Step 1:** Go to {verification_url}\n"
        f"**Step 2:** Enter this code: `{user_code}`\n\n"
        f"The code expires in about "
        f"{expires_in // 60} minutes.",
        ephemeral=True,
    )

    elapsed = 0
    tokens = None

    while elapsed < expires_in:
        await asyncio.sleep(interval)
        elapsed += interval

        try:
            tokens = await simkl.poll_pin(
                device_code
            )

        except SimklSlowDown:
            interval += 5
            continue

        except SimklAuthError as e:
            log.info(
                "SIMKL PIN for user %s ended: %s",
                discord_user_id,
                e,
            )
            break

        except Exception:
            log.warning(
                "SIMKL PIN poll failed; will retry.",
                exc_info=True,
            )
            continue

        if tokens:
            break

    if not tokens:
        await dm_or_followup(
            interaction,
            "⌛ The SIMKL linking code expired or "
            "was cancelled. Run `/simkl-link` again.",
            followup_text=None,
        )
        return

    access_token = tokens[
        "access_token"
    ]

    refresh_token = tokens.get(
        "refresh_token"
    )

    token_expires_at = calculate_token_expiry(
        tokens.get("expires_in")
    )

    simkl_account_id = None

    try:
        settings = await simkl.get_user_settings(
            access_token
        )

        simkl_account_id = (
            account_id_from_settings(
                settings
            )
        )

        simkl_username = (
            settings.get("user", {}).get("name")
            or settings.get("account", {}).get("id")
            or "SIMKL user"
        )

    except Exception:
        simkl_username = "SIMKL user"

    link_time = now_iso()

    await storage.link_user(
        discord_user_id,
        access_token,
        refresh_token,
        simkl_username,
        link_time,
        token_expires_at,
        simkl_account_id,
    )

    await dm_or_followup(
        interaction,
        (
            f"✅ Linked! Your SIMKL account "
            f"(**{simkl_username}**) is now connected."
        ),
        followup_text=(
            f"✅ Linked as **{simkl_username}**!"
        ),
    )

    user_data = {
        "simkl_token": access_token,
        "refresh_token": refresh_token,
        "token_expires_at": token_expires_at,
        "last_checked": {
            media_type: link_time
            for media_type in MEDIA_TYPES
        },
    }

    try:
        await seed_history(
            discord_user_id,
            user_data,
            access_token,
        )

    except Exception:
        log.warning(
            "Couldn't record SIMKL history for user %s yet; "
            "will retry on the next poll.",
            discord_user_id,
            exc_info=True,
        )


async def dm_or_followup(
    interaction: discord.Interaction,
    dm_text: str,
    followup_text: str | None,
):
    """DM the user; fall back to an ephemeral follow-up."""

    try:
        await interaction.user.send(
            dm_text
        )
        return

    except discord.HTTPException:
        pass

    if followup_text is None:
        return

    try:
        await interaction.followup.send(
            followup_text,
            ephemeral=True,
        )

    except discord.HTTPException:
        log.info(
            "Couldn't notify user %s about linking.",
            interaction.user.id,
        )


# ---------------------------------------------------------------------------
# /simkl-unlink
# ---------------------------------------------------------------------------


@bot.tree.command(
    name="simkl-unlink",
    description="Unlink your SIMKL account from this bot.",
)
async def simkl_unlink(
    interaction: discord.Interaction,
):
    removed = await storage.unlink_user(
        str(interaction.user.id)
    )

    if removed:
        message = (
            "Your SIMKL account has been unlinked."
        )
    else:
        message = (
            "You don't have a linked SIMKL account."
        )

    await interaction.response.send_message(
        message,
        ephemeral=True,
    )


# ---------------------------------------------------------------------------
# User embed preferences
# ---------------------------------------------------------------------------

STYLE_CHOICES = [
    app_commands.Choice(name="Rich (large artwork)", value="rich"),
    app_commands.Choice(name="Minimal (small artwork)", value="minimal"),
    app_commands.Choice(name="Poster (large poster)", value="poster"),
]
ARTWORK_CHOICES = [
    app_commands.Choice(name="Automatic", value="auto"),
    app_commands.Choice(name="Poster only", value="poster"),
]
TEXT_CHOICES = [
    app_commands.Choice(name="Short", value="short"),
    app_commands.Choice(name="Detailed", value="detailed"),
]

@bot.tree.command(name="simkl-style", description="Choose how your SIMKL activity embeds are displayed.")
@app_commands.describe(style="Embed layout.", artwork="Choose which artwork type to use.", activity_text="Choose short or detailed activity wording.")
@app_commands.choices(style=STYLE_CHOICES, artwork=ARTWORK_CHOICES, activity_text=TEXT_CHOICES)
async def simkl_style(interaction: discord.Interaction, style: app_commands.Choice[str] | None = None, artwork: app_commands.Choice[str] | None = None, activity_text: app_commands.Choice[str] | None = None):
    user_id = str(interaction.user.id)
    current = await storage.get_embed_preferences(user_id)
    if style is None and artwork is None and activity_text is None:
        await interaction.response.send_message(
            f"Embed style: {current['style']}\\nArtwork: {current['artwork']}\\nActivity text: {current['activity_text']}", ephemeral=True
        )
        return
    await storage.set_embed_preferences(
        user_id,
        style=style.value if style else None,
        artwork=artwork.value if artwork else None,
        activity_text=activity_text.value if activity_text else None,
    )
    updated = await storage.get_embed_preferences(user_id)
    await interaction.response.send_message(
        f"Updated: {updated['style']} / {updated['artwork']} / {updated['activity_text']}", ephemeral=True
    )


# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------

NOT_ADMIN_MESSAGE = (
    "You need the Manage Server permission to do that."
)


@bot.tree.command(
    name="simkl-setchannel",
    description=(
        "(Admin) Set the channel where "
        "watch activity is posted."
    ),
)
@app_commands.describe(
    channel=(
        "The channel to post in. "
        "Defaults to the current channel."
    )
)
async def simkl_setchannel(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None,
):
    if not is_admin(interaction):
        await interaction.response.send_message(
            NOT_ADMIN_MESSAGE,
            ephemeral=True,
        )
        return

    target = channel or interaction.channel

    await storage.set_channel(
        target.id
    )

    await interaction.response.send_message(
        f"Watch activity will now be posted in "
        f"{target.mention}.",
        ephemeral=True,
    )


@bot.tree.command(
    name="simkl-status",
    description=(
        "(Admin) Show bot configuration "
        "and linked accounts."
    ),
)
async def simkl_status(
    interaction: discord.Interaction,
):
    if not is_admin(interaction):
        await interaction.response.send_message(
            NOT_ADMIN_MESSAGE,
            ephemeral=True,
        )
        return

    data = await storage.get_all()

    channel_id = data.get(
        "channel_id"
    )

    channel_text = (
        f"<#{channel_id}>"
        if channel_id
        else "**not set**"
    )

    users = data.get(
        "users",
        {}
    )

    if users:
        users_text = "\n".join(
            (
                f"• <@{uid}> — SIMKL: "
                f"**{user_data.get('simkl_username', 'unknown')}**"
            )
            for uid, user_data in users.items()
        )
    else:
        users_text = (
            "No linked accounts."
        )

    await interaction.response.send_message(
        f"**Posting channel:** {channel_text}\n"
        f"**Poll interval:** every "
        f"{POLL_INTERVAL_MINUTES} minute(s)\n\n"
        f"**Linked accounts:**\n{users_text}",
        ephemeral=True,
    )


@bot.tree.command(
    name="simkl-checknow",
    description=(
        "(Admin) Immediately check "
        "everyone's SIMKL activity."
    ),
)
async def simkl_checknow(
    interaction: discord.Interaction,
):
    global last_checknow_at

    if not is_admin(interaction):
        await interaction.response.send_message(
            NOT_ADMIN_MESSAGE,
            ephemeral=True,
        )
        return

    elapsed = (
        time.monotonic()
        - last_checknow_at
    )

    if elapsed < CHECKNOW_COOLDOWN_SECONDS:
        remaining = (
            int(
                CHECKNOW_COOLDOWN_SECONDS
                - elapsed
            )
            + 1
        )

        await interaction.response.send_message(
            f"Please wait about {remaining} "
            f"second(s) before using "
            f"`/simkl-checknow` again.",
            ephemeral=True,
        )
        return

    if poll_lock.locked():
        await interaction.response.send_message(
            "A SIMKL activity check is already running. "
            "Please wait for it to finish.",
            ephemeral=True,
        )
        return

    await poll_lock.acquire()

    last_checknow_at = time.monotonic()

    try:
        await interaction.response.send_message(
            "Checking SIMKL activity now...",
            ephemeral=True,
        )

        await _poll_all_users()

    finally:
        poll_lock.release()

    await interaction.followup.send(
        "Done.",
        ephemeral=True,
    )


# ---------------------------------------------------------------------------
# Process TV / Anime
# ---------------------------------------------------------------------------


async def process_show_items(channel, discord_user_id: str, display_name: str, member, media_type: str, items, profile_url: str | None = None):
    announced = await storage.get_announced(discord_user_id)
    state = await storage.get_activity_state(discord_user_id)
    watch_times = state.get("watch_times", {})
    preferences = await get_embed_preferences(discord_user_id)
    groups = defaultdict(lambda: {"title": None, "slug": None, "poster": None, "episodes": []})
    for ep in iter_show_episodes(media_type, items):
        if ep["watched_dt"] is None:
            continue
        previous_raw = watch_times.get(ep["key"])
        previous_dt = parse_iso(previous_raw) if previous_raw else None
        is_rewatch = ep["key"] in announced and previous_dt is not None and ep["watched_dt"] > previous_dt
        is_new = ep["key"] not in announced
        if not is_new and not is_rewatch:
            continue
        ep = dict(ep)
        ep["activity_type"] = "rewatched" if is_rewatch else "watched"
        group = groups[(ep["simkl_id"], ep["season_num"], ep["activity_type"])]
        group["title"] = ep["show_title"]; group["slug"] = ep["slug"]; group["poster"] = ep["poster"]; group["episodes"].append(ep)
    total_new = 0; all_sent = True; pending_watch_times = {}
    for (simkl_id, season_num, activity_type), group in groups.items():
        title = group["title"] or "a show"; title_url = simkl_title_url(media_type, simkl_id, group["slug"]); fallback = simkl_poster_url(group["poster"])
        for episode_group in group_consecutive_episodes(group["episodes"]):
            first, last = episode_group[0], episode_group[-1]
            episode_label = format_episode_range(season_num, first["episode_number"], last["episode_number"])
            image_url = None; episode_title = None
            try: image_url, episode_title = await get_episode_media(media_type, first)
            except Exception: log.warning("TMDB episode lookup failed for %s.", title, exc_info=True)
            image_url = image_url or fallback
            verb = "rewatched" if activity_type == "rewatched" else "watched"
            description = f"{verb} **{episode_label}**"
            if preferences.get("activity_text") == "detailed": description = f"{verb} **{episode_label}** of **{title}**"
            if len(episode_group) == 1 and episode_title: description += f"\\n*{episode_title}*"
            embed = build_activity_embed(media_type, description, max(ep["watched_dt"] for ep in episode_group), display_name, member, image_url, profile_url, title=title, title_url=title_url, poster_url=fallback, preferences=preferences)
            if not await send_embed(channel, embed, "episode"):
                all_sent = False; continue
            await storage.add_announced(discord_user_id, [ep["key"] for ep in episode_group])
            for ep in episode_group: pending_watch_times[ep["key"]] = ep["watched_raw"]
            total_new += len(episode_group)
    if pending_watch_times: await storage.update_activity_state(discord_user_id, watch_times=pending_watch_times)
    return total_new, all_sent


# ---------------------------------------------------------------------------
# Process Movies
# ---------------------------------------------------------------------------


async def process_movie_items(channel, discord_user_id: str, display_name: str, member, media_type: str, items, since_dt: datetime, profile_url: str | None = None):
    announced = await storage.get_announced(discord_user_id); state = await storage.get_activity_state(discord_user_id); watch_times = state.get("watch_times", {}); preferences = await get_embed_preferences(discord_user_id)
    total_new = 0; all_sent = True; pending = {}
    for item in items or []:
        movie = item.get("movie") or {}; ids = movie.get("ids") or {}; simkl_id = ids.get("simkl"); watched_raw = item.get("last_watched_at")
        if simkl_id is None or not watched_raw: continue
        watched_dt = parse_iso(watched_raw); key = movie_key(media_type, simkl_id); previous_raw = watch_times.get(key); previous_dt = parse_iso(previous_raw) if previous_raw else None
        is_rewatch = key in announced and previous_dt is not None and watched_dt > previous_dt; is_new = key not in announced and watched_dt > since_dt
        if not is_new and not is_rewatch: continue
        title = movie.get("title", "a movie"); title_url = simkl_title_url(media_type, simkl_id, ids.get("slug")); poster_url = simkl_poster_url(movie.get("poster")); image_url = None
        if ids.get("tmdb") is not None:
            try: image_url = await tmdb.get_movie_backdrop(ids["tmdb"])
            except Exception: log.warning("TMDB movie backdrop lookup failed for %s.", title, exc_info=True)
        image_url = image_url or poster_url; verb = "rewatched" if is_rewatch else "watched a movie"; description = verb
        if preferences.get("activity_text") == "detailed": description = f"{verb} **{title}**"
        embed = build_activity_embed(media_type, description, watched_dt, display_name, member, image_url, profile_url, title=title, title_url=title_url, poster_url=poster_url, preferences=preferences)
        if not await send_embed(channel, embed, "movie"): all_sent = False; continue
        await storage.add_announced(discord_user_id, [key]); pending[key] = watched_raw; total_new += 1
    if pending: await storage.update_activity_state(discord_user_id, watch_times=pending)
    return total_new, all_sent


async def process_status_items(channel, discord_user_id: str, display_name: str, member, media_type: str, items, profile_url: str | None = None, baseline: bool = False):
    state = await storage.get_activity_state(discord_user_id); statuses = state.get("statuses", {}); baseline = baseline or not state.get("statuses_seeded", False); preferences = await get_embed_preferences(discord_user_id); pending = {}; sent_count = 0; all_sent = True
    for item in items or []:
        media = (item.get("movie") if media_type == "movies" else item.get("show")) or {}; ids = media.get("ids") or {}; simkl_id = ids.get("simkl"); status = item.get("status")
        if simkl_id is None or status not in WATCHLIST_STATUSES: continue
        state_key = f"{media_type}:{simkl_id}"; previous = statuses.get(state_key); pending[state_key] = status
        if baseline or previous == status: continue
        title = media.get("title") or "Untitled"; title_url = simkl_title_url(media_type, simkl_id, ids.get("slug")); poster_url = simkl_poster_url(media.get("poster")); image_url = None
        try:
            if ids.get("tmdb") is not None:
                image_url = await (tmdb.get_movie_backdrop(ids["tmdb"]) if media_type == "movies" else tmdb.get_tv_backdrop(ids["tmdb"]))
        except Exception: log.warning("TMDB status artwork lookup failed for %s.", title, exc_info=True)
        image_url = image_url or poster_url; description = STATUS_TEXT[status]
        if preferences.get("activity_text") == "detailed": description = f"{STATUS_TEXT[status]} **{title}**"
        embed = build_activity_embed(media_type, description, datetime.now(timezone.utc), display_name, member, image_url, profile_url, title=title, title_url=title_url, poster_url=poster_url, preferences=preferences)
        if not await send_embed(channel, embed, status): all_sent = False; continue
        sent_count += 1
    if pending and all_sent: await storage.update_activity_state(discord_user_id, statuses=pending, statuses_seeded=True)
    return sent_count, all_sent


# ---------------------------------------------------------------------------
# Poll one user
# ---------------------------------------------------------------------------


async def resolve_display(
    discord_user_id: str,
):
    """Return (user, display name) for embeds."""

    try:
        member = await bot.fetch_user(
            int(discord_user_id)
        )

        return (
            member,
            member.display_name,
        )

    except Exception:
        return None, "Someone"


async def poll_single_user(
    channel,
    discord_user_id: str,
    user_data: dict,
):
    token = await get_valid_token(
        discord_user_id,
        user_data,
    )

    member, display_name = await resolve_display(
        discord_user_id
    )

    # One /sync/activities request per user per cycle.
    try:
        activities, token = (
            await call_with_refresh(
                discord_user_id,
                user_data,
                token,
                simkl.get_activities,
            )
        )

    except SimklAuthError:
        log.warning(
            "SIMKL authentication failed for user %s "
            "after token refresh. They may need to "
            "/simkl-link again.",
            discord_user_id,
        )
        return

    except Exception:
        log.exception(
            "Failed to get SIMKL activities "
            "for user %s.",
            discord_user_id,
        )
        return

    # Users who linked before history seeding existed:
    # record their history before posting anything.
    if not user_data.get(
        "history_seeded"
    ):
        try:
            token = await seed_history(
                discord_user_id,
                user_data,
                token,
            )

        except Exception:
            log.warning(
                "Couldn't record SIMKL history "
                "for user %s; will retry next cycle.",
                discord_user_id,
                exc_info=True,
            )
            return

    # Look up SIMKL profile ID once for older linked accounts.
    if (
        not user_data.get(
            "simkl_account_id"
        )
        and discord_user_id
        not in profile_lookup_attempted
    ):
        profile_lookup_attempted.add(
            discord_user_id
        )

        try:
            settings, token = (
                await call_with_refresh(
                    discord_user_id,
                    user_data,
                    token,
                    simkl.get_user_settings,
                )
            )

            account_id = (
                account_id_from_settings(
                    settings
                )
            )

            if account_id:
                await storage.set_account_id(
                    discord_user_id,
                    account_id,
                )

                user_data[
                    "simkl_account_id"
                ] = account_id

        except Exception:
            log.warning(
                "Couldn't look up SIMKL profile "
                "for user %s.",
                discord_user_id,
                exc_info=True,
            )

    profile_url = simkl_profile_url(
        user_data.get(
            "simkl_account_id"
        )
    )

    last_checked = (
        user_data.get(
            "last_checked"
        )
        or {}
    )

    try:
        for media_type in MEDIA_TYPES:
            since = last_checked.get(
                media_type,
                EPOCH_ISO,
            )

            since_dt = parse_iso(
                since
            )

            activity_data = (
                activities.get(
                    ACTIVITY_KEYS[
                        media_type
                    ]
                )
                or {}
            )

            activity_timestamp = (
                activity_data.get("all")
            )

            if not activity_timestamp:
                continue

            activity_dt = parse_iso(
                activity_timestamp
            )

            # Nothing changed.
            if activity_dt <= since_dt:
                continue

            log.info(
                "SIMKL %s activity changed "
                "for user %s: %s -> %s",
                media_type,
                discord_user_id,
                since,
                activity_timestamp,
            )

            # Incremental sync only.
            try:
                items, token = (
                    await call_with_refresh(
                        discord_user_id,
                        user_data,
                        token,
                        simkl.get_all_items,
                        media_type,
                        date_from=since,
                    )
                )

            except Exception:
                log.exception(
                    "Failed to fetch %s "
                    "for user %s.",
                    media_type,
                    discord_user_id,
                )

                # Do not advance checkpoint.
                continue

            status_count, status_sent = await process_status_items(
                channel,
                discord_user_id,
                display_name,
                member,
                media_type,
                items,
                profile_url,
            )

            if media_type == "movies":
                (
                    new_count,
                    all_sent,
                ) = await process_movie_items(
                    channel,
                    discord_user_id,
                    display_name,
                    member,
                    media_type,
                    items,
                    since_dt,
                    profile_url,
                )

            else:
                (
                    new_count,
                    all_sent,
                ) = await process_show_items(
                    channel,
                    discord_user_id,
                    display_name,
                    member,
                    media_type,
                    items,
                    profile_url,
                )

            all_sent = all_sent and status_sent

            # The checkpoint comes from /sync/activities,
            # not watched_at, because bulk-marked episodes can
            # have old watched_at values.
            #
            # If a post failed, retain the old checkpoint so
            # it will be retried next cycle.
            if all_sent:
                await storage.update_last_checked(
                    discord_user_id,
                    media_type,
                    to_iso(activity_dt),
                )

            else:
                log.warning(
                    "Some %s posts for user %s failed; "
                    "will retry next cycle.",
                    media_type,
                    discord_user_id,
                )

            await storage.flush()

            if new_count:
                log.info(
                    "Posted %d new %s watch event(s) "
                    "for user %s.",
                    new_count,
                    media_type,
                    discord_user_id,
                )

    finally:
        await storage.flush()


# ---------------------------------------------------------------------------
# Poll all users
# ---------------------------------------------------------------------------


async def _poll_all_users():
    """
    Run one polling cycle.

    Assumes poll_lock is already held.
    """

    data = await storage.get_all()

    channel_id = data.get(
        "channel_id"
    )

    if not channel_id:
        return

    channel = bot.get_channel(
        channel_id
    )

    if channel is None:
        try:
            channel = await bot.fetch_channel(
                channel_id
            )

        except Exception:
            log.warning(
                "Configured channel %s is not accessible.",
                channel_id,
            )
            return

    for (
        discord_user_id,
        user_data,
    ) in list(
        data.get(
            "users",
            {},
        ).items()
    ):
        try:
            await poll_single_user(
                channel,
                discord_user_id,
                user_data,
            )

        except SimklAuthError:
            log.warning(
                "SIMKL authentication failed "
                "for user %s. They may need "
                "to /simkl-link again.",
                discord_user_id,
            )

        except Exception:
            log.exception(
                "Error polling user %s.",
                discord_user_id,
            )


async def poll_all_users():
    """Run one polling cycle with the global polling lock."""

    async with poll_lock:
        await _poll_all_users()


# ---------------------------------------------------------------------------
# Background polling
# ---------------------------------------------------------------------------

poll_task_started = False


@bot.event
async def on_ready():
    global poll_task_started

    log.info(
        "Logged in as %s.",
        bot.user,
    )

    log.info(
        "SIMKL polling interval: every %d minute(s).",
        POLL_INTERVAL_MINUTES,
    )

    if not poll_task_started:
        poll_task_started = True

        bot.loop.create_task(
            polling_loop()
        )


async def polling_loop():
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            await poll_all_users()

        except Exception:
            log.exception(
                "Error during polling cycle."
            )

        await asyncio.sleep(
            POLL_INTERVAL_MINUTES * 60
        )


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    bot.run(
        DISCORD_BOT_TOKEN
    )
