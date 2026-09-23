"""
SIMKL Watch Activity Tracker for Discord (AUTH V2)

Features:
- Uses AUTH V2 Device / PIN flow
- Automatic token refresh
- Smart polling via /sync/activities
- 60-minute polling by default
- Groups consecutive watched episodes into ranges
- Minimal original-style Discord embeds
- Posters + clickable SIMKL titles
- Detects bulk-marked episodes without scanning old history
"""

import os
import asyncio
import logging
from datetime import datetime, timezone
from collections import defaultdict

import discord
from discord import app_commands
from dotenv import load_dotenv

from simkl_client import SimklClient, SimklAuthError
from storage import storage


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SIMKL_CLIENT_ID = os.getenv("SIMKL_CLIENT_ID")
GUILD_ID = os.getenv("GUILD_ID")

# How often SIMKL activity is checked.
# Recommended default: 60 minutes.
try:
    POLL_INTERVAL_MINUTES = max(
        int(os.getenv("POLL_INTERVAL_MINUTES", "60")),
        1,
    )
except ValueError:
    POLL_INTERVAL_MINUTES = 60

if not DISCORD_BOT_TOKEN or not SIMKL_CLIENT_ID:
    raise SystemExit(
        "Missing DISCORD_BOT_TOKEN or SIMKL_CLIENT_ID."
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

log = logging.getLogger("simkl-bot")


# ---------------------------------------------------------------------------
# SIMKL client
# ---------------------------------------------------------------------------

simkl = SimklClient(SIMKL_CLIENT_ID)


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

intents = discord.Intents.default()


class SimklBot(discord.Client):

    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):

        if GUILD_ID:

            guild = discord.Object(
                id=int(GUILD_ID)
            )

            self.tree.copy_global_to(
                guild=guild
            )

            await self.tree.sync(
                guild=guild
            )

            log.info(
                "Slash commands synced to guild %s.",
                GUILD_ID,
            )

        else:

            await self.tree.sync()

            log.info(
                "Slash commands synced globally."
            )

    async def close(self):

        try:
            await simkl.close()
        except Exception:
            pass

        await super().close()


bot = SimklBot()


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def parse_iso(value: str) -> datetime:

    if not value:
        return datetime.min.replace(
            tzinfo=timezone.utc
        )

    try:

        value = value.replace(
            "Z",
            "+00:00"
        )

        dt = datetime.fromisoformat(
            value
        )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt

    except Exception:

        return datetime.min.replace(
            tzinfo=timezone.utc
        )


def is_admin(
    interaction: discord.Interaction,
) -> bool:

    if not interaction.guild:
        return False

    return bool(
        interaction.user.guild_permissions.manage_guild
    )


def simkl_poster_url(
    poster_path: str | None,
) -> str | None:

    if not poster_path:
        return None

    return (
        "https://wsrv.nl/"
        "?url=https://simkl.in/posters/"
        f"{poster_path}_c.webp&q=90"
    )


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
        return (
            f"{base}/{simkl_id}/{slug}"
        )

    return (
        f"{base}/{simkl_id}"
    )


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


def group_consecutive_episodes(
    episodes,
):

    if not episodes:
        return []

    episodes = sorted(
        episodes,
        key=lambda x: x["episode_number"],
    )

    groups = []

    current = [
        episodes[0]
    ]

    for episode in episodes[1:]:

        previous = current[-1]

        if (
            episode["episode_number"]
            == previous["episode_number"] + 1
        ):

            current.append(
                episode
            )

        else:

            groups.append(
                current
            )

            current = [
                episode
            ]

    groups.append(
        current
    )

    return groups


# ---------------------------------------------------------------------------
# Bulk-watch detection
# ---------------------------------------------------------------------------

def is_bulk_watch_cluster(
    episodes,
    max_gap_seconds: int = 300,
) -> bool:
    """
    Detects a cluster of episodes whose watched_at timestamps are very close
    together.

    This is useful for SIMKL bulk marking, where episodes can receive
    timestamps only a few seconds apart.

    We deliberately do NOT treat an entire old watch history as new.
    """

    if len(episodes) < 2:
        return False

    timestamps = sorted(
        ep["watched_dt"]
        for ep in episodes
    )

    for index in range(
        len(timestamps) - 1
    ):

        gap = (
            timestamps[index + 1]
            - timestamps[index]
        ).total_seconds()

        if gap <= max_gap_seconds:
            return True

    return False


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

async def get_valid_token(
    discord_user_id: str,
    user_data: dict,
) -> str:

    access_token = user_data.get(
        "simkl_token"
    )

    if not access_token:
        raise SimklAuthError(
            "No SIMKL access token stored."
        )

    # Do NOT make an extra /sync/activities request here.
    #
    # The actual activity check in poll_single_user() is also capable of
    # detecting an expired token. If authentication fails there, the token
    # will be refreshed and the activity request retried.
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
            "SIMKL token expired and no "
            "refresh token is available."
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
            "SIMKL token refresh returned "
            "no access token."
        )

    new_refresh_token = new_tokens.get(
        "refresh_token"
    )

    await storage.update_tokens(
        discord_user_id,
        new_access_token,
        new_refresh_token,
    )

    # Keep the in-memory user data current for the rest of this polling
    # cycle and future operations using this object.
    user_data["simkl_token"] = new_access_token

    if new_refresh_token:
        user_data["refresh_token"] = new_refresh_token

    log.info(
        "Refreshed SIMKL token for user %s.",
        discord_user_id,
    )

    return new_access_token


# ---------------------------------------------------------------------------
# /simkl-link
# ---------------------------------------------------------------------------

@bot.tree.command(
    name="simkl-link",
    description=(
        "Link your SIMKL account so your "
        "watch activity gets posted."
    ),
)
async def simkl_link(
    interaction: discord.Interaction,
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

    user_code = pin_data[
        "user_code"
    ]

    device_code = pin_data[
        "device_code"
    ]

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

    discord_user_id = str(
        interaction.user.id
    )

    elapsed = 0

    while elapsed < expires_in:

        await asyncio.sleep(
            interval
        )

        elapsed += interval

        try:

            tokens = await simkl.poll_pin(
                device_code
            )

        except Exception:

            continue

        if not tokens:
            continue

        access_token = tokens[
            "access_token"
        ]

        refresh_token = tokens.get(
            "refresh_token"
        )

        try:

            settings = (
                await simkl.get_user_settings(
                    access_token
                )
            )

            simkl_username = (
                settings.get(
                    "user",
                    {}
                ).get(
                    "name"
                )
                or settings.get(
                    "account",
                    {}
                ).get(
                    "id"
                )
                or "SIMKL user"
            )

        except Exception:

            simkl_username = "SIMKL user"

        await storage.link_user(
            discord_user_id,
            access_token,
            refresh_token,
            simkl_username,
            now_iso(),
        )

        try:

            await interaction.user.send(
                f"✅ Linked! Your SIMKL account "
                f"(**{simkl_username}**) is now connected."
            )

        except discord.Forbidden:

            await interaction.followup.send(
                f"✅ Linked as **{simkl_username}**!",
                ephemeral=True,
            )

        return

    try:

        await interaction.user.send(
            "⌛ The SIMKL linking code expired. "
            "Run `/simkl-link` again."
        )

    except discord.Forbidden:
        pass


# ---------------------------------------------------------------------------
# /simkl-unlink
# ---------------------------------------------------------------------------

@bot.tree.command(
    name="simkl-unlink",
    description=(
        "Unlink your SIMKL account "
        "from this bot."
    ),
)
async def simkl_unlink(
    interaction: discord.Interaction,
):

    removed = await storage.unlink_user(
        str(interaction.user.id)
    )

    if removed:

        await interaction.response.send_message(
            "Your SIMKL account has been unlinked.",
            ephemeral=True,
        )

    else:

        await interaction.response.send_message(
            "You don't have a linked SIMKL account.",
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# /simkl-setchannel
# ---------------------------------------------------------------------------

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

    if not is_admin(
        interaction
    ):

        await interaction.response.send_message(
            "You need the Manage Server "
            "permission to do that.",
            ephemeral=True,
        )

        return

    target = (
        channel
        or interaction.channel
    )

    await storage.set_channel(
        target.id
    )

    await interaction.response.send_message(
        f"Watch activity will now be "
        f"posted in {target.mention}.",
        ephemeral=True,
    )


# ---------------------------------------------------------------------------
# /simkl-status
# ---------------------------------------------------------------------------

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

    if not is_admin(
        interaction
    ):

        await interaction.response.send_message(
            "You need the Manage Server "
            "permission to do that.",
            ephemeral=True,
        )

        return

    data = await storage.get_all()

    channel_id = data.get(
        "channel_id"
    )

    if channel_id:

        channel_text = (
            f"<#{channel_id}>"
        )

    else:

        channel_text = "**not set**"

    users = data.get(
        "users",
        {}
    )

    if users:

        lines = []

        for uid, user_data in users.items():

            lines.append(
                f"• <@{uid}> — SIMKL: "
                f"**{user_data.get('simkl_username', 'unknown')}**"
            )

        users_text = "\n".join(
            lines
        )

    else:

        users_text = (
            "No linked accounts."
        )

    await interaction.response.send_message(
        f"**Posting channel:** {channel_text}\n"
        f"**Poll interval:** every "
        f"{POLL_INTERVAL_MINUTES} minute(s)\n\n"
        f"**Linked accounts:**\n"
        f"{users_text}",
        ephemeral=True,
    )


# ---------------------------------------------------------------------------
# /simkl-checknow
# ---------------------------------------------------------------------------

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

    if not is_admin(
        interaction
    ):

        await interaction.response.send_message(
            "You need the Manage Server "
            "permission to do that.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(
        "Checking SIMKL activity now...",
        ephemeral=True,
    )

    await poll_all_users()

    await interaction.followup.send(
        "Done.",
        ephemeral=True,
    )


# ---------------------------------------------------------------------------
# Process TV / Anime
# ---------------------------------------------------------------------------

async def process_show_items(
    channel,
    discord_user_id: str,
    display_name: str,
    member,
    media_type: str,
    items,
    since_dt: datetime,
):

    episodes_by_show_and_season = defaultdict(
        lambda: {
            "title": None,
            "simkl_id": None,
            "slug": None,
            "poster": None,
            "episodes": [],
        }
    )

    newest_seen = datetime.min.replace(
        tzinfo=timezone.utc
    )

    for item in items or []:

        show = item.get(
            "show"
        ) or {}

        title = show.get(
            "title",
            "a show",
        )

        ids = show.get(
            "ids"
        ) or {}

        simkl_id = ids.get(
            "simkl"
        )

        slug = ids.get(
            "slug"
        )

        poster = show.get(
            "poster"
        )

        if simkl_id is None:
            continue

        for season in (
            item.get(
                "seasons"
            )
            or []
        ):

            season_num = season.get(
                "number"
            )

            if season_num is None:
                continue

            candidate_episodes = []

            for ep in (
                season.get(
                    "episodes"
                )
                or []
            ):

                watched_raw = ep.get(
                    "watched_at"
                )

                if not watched_raw:
                    continue

                ep_num = ep.get(
                    "number"
                )

                if ep_num is None:
                    continue

                watched_dt = parse_iso(
                    watched_raw
                )

                key = (
                    f"{media_type}:"
                    f"{simkl_id}:"
                    f"{season_num}:"
                    f"{ep_num}"
                )

                candidate_episodes.append(
                    {
                        "episode_number": ep_num,
                        "episode_title": ep.get(
                            "title"
                        ),
                        "watched_dt": watched_dt,
                        "key": key,
                    }
                )

            if not candidate_episodes:
                continue

            # ---------------------------------------------------------------
            # Determine which episodes should actually be posted.
            #
            # Normal watch:
            #   watched_at is newer than the previous checkpoint.
            #
            # Bulk mark:
            #   multiple episodes can have very close watched_at timestamps
            #   even though those timestamps themselves are historical.
            #
            # Old history:
            #   historical episodes with no recent timestamp are ignored.
            # ---------------------------------------------------------------

            recent_candidates = [
                ep
                for ep in candidate_episodes
                if ep["watched_dt"] > since_dt
            ]

            bulk_cluster = is_bulk_watch_cluster(
                candidate_episodes
            )

            if bulk_cluster:

                # Only allow historical episodes into a bulk cluster if
                # there is evidence that the returned show has changed
                # and the timestamps are tightly grouped.
                #
                # We don't simply accept every old watched episode.
                selected_candidates = [
                    ep
                    for ep in candidate_episodes
                    if not await storage.is_announced(
                        discord_user_id,
                        ep["key"],
                    )
                ]

            else:

                selected_candidates = (
                    recent_candidates
                )

            for ep in selected_candidates:

                key = ep["key"]

                if await storage.is_announced(
                    discord_user_id,
                    key,
                ):
                    continue

                group_key = (
                    simkl_id,
                    season_num,
                )

                group = (
                    episodes_by_show_and_season[
                        group_key
                    ]
                )

                group["title"] = title
                group["simkl_id"] = simkl_id
                group["slug"] = slug
                group["poster"] = poster

                group["episodes"].append(
                    ep
                )

                if (
                    ep["watched_dt"]
                    > newest_seen
                ):

                    newest_seen = (
                        ep["watched_dt"]
                    )

    # -----------------------------------------------------------------------
    # Send grouped episode embeds
    # -----------------------------------------------------------------------

    total_new = 0

    for (
        simkl_id,
        season_num,
    ), group in (
        episodes_by_show_and_season.items()
    ):

        episodes = group[
            "episodes"
        ]

        if not episodes:
            continue

        grouped = group_consecutive_episodes(
            episodes
        )

        title = group[
            "title"
        ] or "a show"

        title_url = simkl_title_url(
            media_type,
            simkl_id,
            group["slug"],
        )

        poster_url = simkl_poster_url(
            group["poster"]
        )

        for episode_group in grouped:

            first = episode_group[
                0
            ]

            last = episode_group[
                -1
            ]

            start_episode = first[
                "episode_number"
            ]

            end_episode = last[
                "episode_number"
            ]

            episode_label = (
                format_episode_range(
                    season_num,
                    start_episode,
                    end_episode,
                )
            )

            description = (
                f"watched **{episode_label}** "
                f"of **[{title}]({title_url})**"
            )

            if (
                len(episode_group) == 1
                and first.get(
                    "episode_title"
                )
            ):

                description += (
                    f"\n*{first['episode_title']}*"
                )

            timestamps = [
                ep["watched_dt"]
                for ep in episode_group
            ]

            embed_timestamp = max(
                timestamps
            )

            embed = discord.Embed(
                description=description,
                color=0x1ABC9C,
                timestamp=embed_timestamp,
            )

            embed.set_author(
                name=(
                    f"{display_name}'s Activity"
                ),
                icon_url=(
                    member.display_avatar.url
                    if member
                    else None
                ),
            )

            if poster_url:

                embed.set_thumbnail(
                    url=poster_url
                )

            embed.set_footer(
                text="SIMKL"
            )

            try:

                await channel.send(
                    embed=embed
                )

            except Exception:

                log.exception(
                    "Failed to send episode embed."
                )

                continue

            # Mark every individual episode in
            # this range as announced.
            keys = [
                ep["key"]
                for ep in episode_group
            ]

            await storage.add_announced(
                discord_user_id,
                keys,
            )

            total_new += len(
                keys
            )

    return (
        total_new,
        newest_seen,
    )


# ---------------------------------------------------------------------------
# Process Movies
# ---------------------------------------------------------------------------

async def process_movie_items(
    channel,
    discord_user_id: str,
    display_name: str,
    member,
    media_type: str,
    items,
    since_dt: datetime,
):

    total_new = 0

    newest_seen = datetime.min.replace(
        tzinfo=timezone.utc
    )

    for item in items or []:

        movie = item.get(
            "movie"
        ) or {}

        title = movie.get(
            "title",
            "a movie",
        )

        ids = movie.get(
            "ids"
        ) or {}

        simkl_id = ids.get(
            "simkl"
        )

        slug = ids.get(
            "slug"
        )

        poster = movie.get(
            "poster"
        )

        if simkl_id is None:
            continue

        watched_raw = item.get(
            "last_watched_at"
        )

        if not watched_raw:
            continue

        watched_dt = parse_iso(
            watched_raw
        )

        # Movies do not need the bulk-episode handling.
        # Only announce movies with a newer watch timestamp.
        if watched_dt <= since_dt:
            continue

        key = (
            f"{media_type}:"
            f"{simkl_id}"
        )

        if await storage.is_announced(
            discord_user_id,
            key,
        ):
            continue

        title_url = simkl_title_url(
            media_type,
            simkl_id,
            slug,
        )

        poster_url = simkl_poster_url(
            poster
        )

        description = (
            f"watched the movie "
            f"**[{title}]({title_url})**"
        )

        embed = discord.Embed(
            description=description,
            color=0x1ABC9C,
            timestamp=watched_dt,
        )

        embed.set_author(
            name=(
                f"{display_name}'s Activity"
            ),
            icon_url=(
                member.display_avatar.url
                if member
                else None
            ),
        )

        if poster_url:

            embed.set_thumbnail(
                url=poster_url
            )

        embed.set_footer(
            text="SIMKL"
        )

        try:

            await channel.send(
                embed=embed
            )

        except Exception:

            log.exception(
                "Failed to send movie embed."
            )

            continue

        await storage.add_announced(
            discord_user_id,
            [key],
        )

        total_new += 1

        if watched_dt > newest_seen:

            newest_seen = (
                watched_dt
            )

    return (
        total_new,
        newest_seen,
    )


# ---------------------------------------------------------------------------
# Poll one user
# ---------------------------------------------------------------------------

async def poll_single_user(
    channel,
    discord_user_id: str,
    user_data: dict,
):

    token = await get_valid_token(
        discord_user_id,
        user_data,
    )

    last_checked = user_data.get(
        "last_checked",
        {},
    )

    try:

        member = await bot.fetch_user(
            int(discord_user_id)
        )

        display_name = (
            member.display_name
            if hasattr(
                member,
                "display_name"
            )
            else member.name
        )

    except Exception:

        member = None
        display_name = "Someone"

    # -----------------------------------------------------------------------
    # Check SIMKL activities
    #
    # This is now the ONLY /sync/activities request made during a normal
    # polling cycle.
    # -----------------------------------------------------------------------

    try:

        activities = await simkl.get_activities(
            token
        )

    except SimklAuthError:

        # The activity request itself tells us whether the token is still
        # valid. If it isn't, refresh it and retry the SAME request.
        try:

            token = await refresh_user_token(
                discord_user_id,
                user_data,
            )

            activities = await simkl.get_activities(
                token
            )

        except SimklAuthError:

            log.warning(
                "SIMKL authentication failed "
                "for user %s after token refresh. "
                "They may need to /simkl-link again.",
                discord_user_id,
            )

            return

        except Exception:

            log.exception(
                "Failed to refresh SIMKL token "
                "or retry activities for user %s.",
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

    type_map = {
        "shows": "tv_shows",
        "anime": "anime",
        "movies": "movies",
    }

    for media_type in (
        "shows",
        "anime",
        "movies",
    ):

        since = last_checked.get(
            media_type,
            "1970-01-01T00:00:00Z",
        )

        since_dt = parse_iso(
            since
        )

        activity_key = type_map[
            media_type
        ]

        activity_data = (
            activities.get(
                activity_key
            )
            or {}
        )

        activity_timestamp = (
            activity_data.get(
                "all"
            )
        )

        if not activity_timestamp:
            continue

        activity_dt = parse_iso(
            activity_timestamp
        )

        # -------------------------------------------------------------------
        # Nothing changed.
        #
        # If SIMKL hasn't changed since the last successful check,
        # absolutely nothing else is requested.
        # -------------------------------------------------------------------

        if activity_dt <= since_dt:

            continue

        log.info(
            "SIMKL %s activity changed for user %s: "
            "%s -> %s",
            media_type,
            discord_user_id,
            since,
            activity_timestamp,
        )

        # -------------------------------------------------------------------
        # Incremental sync only.
        #
        # NO full-history fallback.
        # -------------------------------------------------------------------

        try:

            items = await simkl.get_all_items(
                token,
                media_type,
                date_from=since,
            )

        except SimklAuthError:

            # In case the token expires between /sync/activities and the
            # incremental sync request, refresh once and retry.
            try:

                token = await refresh_user_token(
                    discord_user_id,
                    user_data,
                )

                items = await simkl.get_all_items(
                    token,
                    media_type,
                    date_from=since,
                )

            except Exception:

                log.exception(
                    "Failed to refresh token or fetch "
                    "%s for user %s.",
                    media_type,
                    discord_user_id,
                )

                # Do NOT advance the checkpoint if the sync failed.
                continue

        except Exception:

            log.exception(
                "Failed to fetch %s for user %s.",
                media_type,
                discord_user_id,
            )

            # Do NOT advance the checkpoint if the sync failed.
            continue

        if media_type in (
            "shows",
            "anime",
        ):

            new_count, newest_seen = (
                await process_show_items(
                    channel,
                    discord_user_id,
                    display_name,
                    member,
                    media_type,
                    items,
                    since_dt,
                )
            )

        else:

            new_count, newest_seen = (
                await process_movie_items(
                    channel,
                    discord_user_id,
                    display_name,
                    member,
                    media_type,
                    items,
                    since_dt,
                )
            )

        # -------------------------------------------------------------------
        # The checkpoint MUST come from /sync/activities.
        #
        # Do not use watched_at here because bulk-marked episodes can have
        # historical watched_at timestamps.
        # -------------------------------------------------------------------

        await storage.update_last_checked(
            discord_user_id,
            media_type,
            activity_dt.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        )

        if new_count:

            log.info(
                "Posted %d new %s watch event(s) "
                "for user %s.",
                new_count,
                media_type,
                discord_user_id,
            )


# ---------------------------------------------------------------------------
# Poll all users
# ---------------------------------------------------------------------------

async def poll_all_users():

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
                "Configured channel %s "
                "is not accessible.",
                channel_id,
            )

            return

    for (
        discord_user_id,
        user_data,
    ) in list(
        data.get(
            "users",
            {}
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
