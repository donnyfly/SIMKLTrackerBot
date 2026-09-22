"""
SIMKL Watch Activity Tracker for Discord (AUTH V2)

- Uses AUTH V2 Device / PIN flow
- Automatic token refresh
- Smart polling via /sync/activities
- Nice embeds with posters + clickable titles
- 5-minute polling by default
"""

import os
import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from dotenv import load_dotenv

from simkl_client import SimklClient, SimklAuthError
from storage import storage


load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SIMKL_CLIENT_ID = os.getenv("SIMKL_CLIENT_ID")
GUILD_ID = os.getenv("GUILD_ID")

if not DISCORD_BOT_TOKEN or not SIMKL_CLIENT_ID:
    raise SystemExit(
        "Missing DISCORD_BOT_TOKEN or SIMKL_CLIENT_ID.\n"
        "Copy .env.example to .env and fill in your values before running the bot."
    )


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

log = logging.getLogger("simkl-bot")

simkl = SimklClient(SIMKL_CLIENT_ID)

intents = discord.Intents.default()


# ---------------------------------------------------------------------------
# Discord bot
# ---------------------------------------------------------------------------

class SimklBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))

            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)

            log.info(
                "Slash commands synced to guild %s (instant).",
                GUILD_ID,
            )
        else:
            await self.tree.sync()

            log.info(
                "Slash commands synced globally "
                "(can take up to ~1 hour to appear)."
            )


bot = SimklBot()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)

    v = value.replace("Z", "+00:00")

    try:
        dt = datetime.fromisoformat(v)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt

    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def is_admin(interaction: discord.Interaction) -> bool:
    return (
        bool(interaction.user.guild_permissions.manage_guild)
        if interaction.guild
        else False
    )


def simkl_poster_url(poster_path: str | None) -> str | None:
    if not poster_path:
        return None

    return (
        "https://wsrv.nl/"
        f"?url=https://simkl.in/posters/{poster_path}_c.webp&q=90"
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
        return f"{base}/{simkl_id}/{slug}"

    return f"{base}/{simkl_id}"


# ---------------------------------------------------------------------------
# SIMKL authentication
# ---------------------------------------------------------------------------

async def get_valid_token(
    discord_user_id: str,
    user_data: dict,
) -> str:
    """
    Return the stored access token.

    We intentionally do not make a test API request here.
    The polling request itself will detect an expired token and trigger
    the refresh flow. This prevents an unnecessary duplicate
    /sync/activities request every polling cycle.
    """

    access = user_data.get("simkl_token")

    if not access:
        raise SimklAuthError("No access token stored")

    return access


async def refresh_user_token(
    discord_user_id: str,
    user_data: dict,
) -> str:
    """
    Refresh the user's SIMKL access token using their refresh token.
    """

    refresh = user_data.get("refresh_token")

    if not refresh:
        raise SimklAuthError(
            "Token expired and no refresh_token is available"
        )

    new_tokens = await simkl.refresh_token(refresh)

    if not new_tokens:
        raise SimklAuthError(
            "Refresh failed - user needs to /simkl-link again"
        )

    new_access_token = new_tokens["access_token"]
    new_refresh_token = new_tokens.get("refresh_token")

    await storage.update_tokens(
        discord_user_id,
        new_access_token,
        new_refresh_token,
    )

    # Keep the in-memory copy up to date for the current polling cycle.
    user_data["simkl_token"] = new_access_token

    if new_refresh_token:
        user_data["refresh_token"] = new_refresh_token

    log.info(
        "Refreshed SIMKL token for user %s",
        discord_user_id,
    )

    return new_access_token


async def get_activities_with_refresh(
    discord_user_id: str,
    user_data: dict,
    token: str,
):
    """
    Get SIMKL activities.

    If SIMKL rejects the access token, refresh it once and retry.
    """

    try:
        return await simkl.get_activities(token)

    except SimklAuthError:
        log.info(
            "Access token expired for user %s. Refreshing...",
            discord_user_id,
        )

        new_token = await refresh_user_token(
            discord_user_id,
            user_data,
        )

        return await simkl.get_activities(new_token)


async def get_all_items_with_refresh(
    discord_user_id: str,
    user_data: dict,
    token: str,
    media_type: str,
    date_from: str,
):
    """
    Get full SIMKL watch data.

    If SIMKL rejects the access token, refresh it once and retry.
    """

    try:
        return await simkl.get_all_items(
            token,
            media_type,
            date_from=date_from,
        )

    except SimklAuthError:
        log.info(
            "Access token expired while fetching %s for user %s. "
            "Refreshing...",
            media_type,
            discord_user_id,
        )

        new_token = await refresh_user_token(
            discord_user_id,
            user_data,
        )

        return await simkl.get_all_items(
            new_token,
            media_type,
            date_from=date_from,
        )


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@bot.tree.command(
    name="simkl-link",
    description="Link your SIMKL account so your watch activity gets posted",
)
async def simkl_link(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        pin_data = await simkl.start_pin_auth()

    except Exception as e:
        log.exception("Failed to start PIN auth")

        await interaction.followup.send(
            f"Couldn't reach SIMKL to start linking: {e}",
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
        f"This code expires in about {expires_in // 60} minutes. "
        f"I'll message you here once you're linked — "
        f"no need to run anything else.",
        ephemeral=True,
    )

    discord_user_id = str(interaction.user.id)

    elapsed = 0

    while elapsed < expires_in:
        await asyncio.sleep(interval)
        elapsed += interval

        try:
            tokens = await simkl.poll_pin(device_code)

        except Exception:
            continue

        if tokens:
            access_token = tokens["access_token"]
            refresh_token = tokens.get("refresh_token")

            try:
                settings = await simkl.get_user_settings(
                    access_token
                )

                simkl_username = (
                    settings.get("user", {}).get("name")
                    or settings.get("account", {}).get("id")
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
                    f"(**{simkl_username}**) is now connected. "
                    f"Your future watch activity will be posted "
                    f"automatically."
                )

            except discord.Forbidden:
                await interaction.followup.send(
                    f"✅ Linked as **{simkl_username}**! "
                    f"(I couldn't DM you — your DMs may be closed.)",
                    ephemeral=True,
                )

            return

    try:
        await interaction.user.send(
            "⌛ That linking code expired before you approved it. "
            "Run `/simkl-link` again."
        )

    except discord.Forbidden:
        pass


@bot.tree.command(
    name="simkl-unlink",
    description="Unlink your SIMKL account from this bot",
)
async def simkl_unlink(interaction: discord.Interaction):
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


@bot.tree.command(
    name="simkl-setchannel",
    description="(Admin) Set the channel where watch activity gets posted",
)
@app_commands.describe(
    channel="The channel to post in (defaults to the current channel)"
)
async def simkl_setchannel(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None,
):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "You need the Manage Server permission to do that.",
            ephemeral=True,
        )
        return

    target = channel or interaction.channel

    await storage.set_channel(target.id)

    await interaction.response.send_message(
        f"Watch activity will now be posted in {target.mention}.",
        ephemeral=True,
    )


@bot.tree.command(
    name="simkl-status",
    description="(Admin) Show bot configuration and linked accounts",
)
async def simkl_status(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "You need the Manage Server permission to do that.",
            ephemeral=True,
        )
        return

    data = await storage.get_all()

    channel_id = data.get("channel_id")

    if channel_id:
        channel_text = f"<#{channel_id}>"

    else:
        channel_text = (
            "**not set** — run `/simkl-setchannel` first"
        )

    users = data.get("users", {})

    if users:
        lines = []

        for uid, user in users.items():
            lines.append(
                f"• <@{uid}> — "
                f"SIMKL: **{user.get('simkl_username', 'unknown')}**"
            )

        users_text = "\n".join(lines)

    else:
        users_text = (
            "No one has linked their account yet. "
            "Run `/simkl-link` to link one."
        )

    await interaction.response.send_message(
        f"**Posting channel:** {channel_text}\n"
        f"**Poll interval:** "
        f"every {data.get('poll_interval_minutes', 5)} minute(s)\n\n"
        f"**Linked accounts:**\n{users_text}",
        ephemeral=True,
    )


@bot.tree.command(
    name="simkl-checknow",
    description="(Admin) Immediately check everyone's SIMKL activity",
)
async def simkl_checknow(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "You need the Manage Server permission to do that.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        "Checking now...",
        ephemeral=True,
    )

    await poll_all_users()

    await interaction.followup.send(
        "Done.",
        ephemeral=True,
    )


# ---------------------------------------------------------------------------
# Polling logic
# ---------------------------------------------------------------------------

async def poll_all_users():
    data = await storage.get_all()

    channel_id = data.get("channel_id")

    if not channel_id:
        return

    channel = bot.get_channel(channel_id)

    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)

        except Exception:
            log.warning(
                "Configured channel %s is not accessible.",
                channel_id,
            )
            return

    for discord_user_id, user_data in list(
        data.get("users", {}).items()
    ):
        try:
            await poll_single_user(
                channel,
                discord_user_id,
                user_data,
            )

        except SimklAuthError:
            log.warning(
                "Token invalid for user %s — "
                "they may need to /simkl-link again.",
                discord_user_id,
            )

        except Exception:
            log.exception(
                "Error polling user %s",
                discord_user_id,
            )


async def poll_single_user(
    channel: discord.abc.Messageable,
    discord_user_id: str,
    user_data: dict,
):
    # Get the currently stored access token.
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
            if hasattr(member, "display_name")
            else member.name
        )

    except Exception:
        display_name = "Someone"
        member = None

    # -----------------------------------------------------------------------
    # Smart gate
    #
    # /sync/activities is the cheap check.
    # We only request the more expensive full watched-item data when SIMKL
    # reports that something newer exists.
    #
    # If the token has expired, this function refreshes it and retries once.
    # -----------------------------------------------------------------------

    try:
        activities = await get_activities_with_refresh(
            discord_user_id,
            user_data,
            token,
        )

    except Exception:
        log.exception(
            "Failed to get activities for user %s",
            discord_user_id,
        )
        return

    # If the token was refreshed, use the new token from user_data.
    token = user_data.get(
        "simkl_token",
        token,
    )

    type_map = {
        "shows": "tv_shows",
        "anime": "anime",
        "movies": "movies",
    }

    for media_type, kind in (
        ("shows", "show"),
        ("anime", "show"),
        ("movies", "movie"),
    ):
        since = last_checked.get(
            media_type,
            "1970-01-01T00:00:00Z",
        )

        since_dt = parse_iso(since)

        act_key = type_map[media_type]

        act_all = (
            activities.get(act_key) or {}
        ).get("all")

        if act_all:
            act_dt = parse_iso(act_all)

            if act_dt <= since_dt:
                continue

        # Something changed, so now fetch the more expensive full data.
        try:
            items = await get_all_items_with_refresh(
                discord_user_id,
                user_data,
                token,
                media_type,
                since,
            )

        except Exception:
            log.exception(
                "Failed to get %s data for user %s",
                media_type,
                discord_user_id,
            )
            continue

        # If the token was refreshed while fetching full data,
        # keep the latest token for subsequent media types.
        token = user_data.get(
            "simkl_token",
            token,
        )

        newest_seen = since_dt
        announce_keys = []

        for item in items:

            # ----------------------------------------------------------------
            # TV shows / anime
            # ----------------------------------------------------------------

            if kind == "show":
                show = item.get("show") or {}

                title = show.get(
                    "title",
                    "a show",
                )

                simkl_id = (
                    show.get("ids", {}).get("simkl")
                )

                slug = (
                    show.get("ids", {}).get("slug")
                )

                poster = show.get("poster")

                for season in item.get(
                    "seasons",
                    [],
                ) or []:

                    season_num = season.get(
                        "number"
                    )

                    for ep in season.get(
                        "episodes",
                        [],
                    ) or []:

                        watched_raw = ep.get(
                            "watched_at"
                        )

                        if not watched_raw:
                            continue

                        watched_dt = parse_iso(
                            watched_raw
                        )

                        if watched_dt <= since_dt:
                            continue

                        ep_num = ep.get(
                            "number"
                        )

                        key = (
                            f"{media_type}:"
                            f"{simkl_id}:"
                            f"{season_num}:"
                            f"{ep_num}"
                        )

                        if await storage.is_announced(
                            discord_user_id,
                            key,
                        ):
                            continue

                        announce_keys.append(key)

                        if watched_dt > newest_seen:
                            newest_seen = watched_dt

                        ep_title = ep.get(
                            "title"
                        )

                        if (
                            season_num is not None
                            and ep_num is not None
                        ):
                            ep_label = (
                                f"S{season_num:02d}"
                                f"E{ep_num:02d}"
                            )
                        else:
                            ep_label = "an episode"

                        title_url = simkl_title_url(
                            media_type,
                            simkl_id,
                            slug,
                        )

                        poster_url = simkl_poster_url(
                            poster
                        )

                        # ----------------------------------------------------
                        # Minimal original-style embed
                        # ----------------------------------------------------

                        description = (
                            f"watched **{ep_label}**"
                            f" of **[{title}]({title_url})**"
                        )

                        if ep_title:
                            description += (
                                f'\n*"{ep_title}"*'
                            )

                        embed = discord.Embed(
                            description=description,
                            color=0x1ABC9C,
                            timestamp=watched_dt,
                        )

                        if member and hasattr(
                            member,
                            "display_avatar",
                        ):
                            embed.set_author(
                                name=(
                                    f"{display_name}'s Activity"
                                ),
                                icon_url=(
                                    member
                                    .display_avatar
                                    .url
                                ),
                            )
                        else:
                            embed.set_author(
                                name=(
                                    f"{display_name}'s Activity"
                                )
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
                                "Failed to send embed"
                            )

            # ----------------------------------------------------------------
            # Movies
            # ----------------------------------------------------------------

            else:
                movie = item.get("movie") or {}

                title = movie.get(
                    "title",
                    "a movie",
                )

                simkl_id = (
                    movie.get("ids", {}).get("simkl")
                )

                slug = (
                    movie.get("ids", {}).get("slug")
                )

                poster = movie.get("poster")

                watched_raw = item.get(
                    "last_watched_at"
                )

                if not watched_raw:
                    continue

                watched_dt = parse_iso(
                    watched_raw
                )

                if watched_dt <= since_dt:
                    continue

                key = (
                    f"{media_type}:{simkl_id}"
                )

                if await storage.is_announced(
                    discord_user_id,
                    key,
                ):
                    continue

                announce_keys.append(key)

                if watched_dt > newest_seen:
                    newest_seen = watched_dt

                title_url = simkl_title_url(
                    media_type,
                    simkl_id,
                    slug,
                )

                poster_url = simkl_poster_url(
                    poster
                )

                # ------------------------------------------------------------
                # Minimal original-style movie embed
                # ------------------------------------------------------------

                description = (
                    f"watched **[{title}]({title_url})**"
                )

                embed = discord.Embed(
                    description=description,
                    color=0x1ABC9C,
                    timestamp=watched_dt,
                )

                if member and hasattr(
                    member,
                    "display_avatar",
                ):
                    embed.set_author(
                        name=(
                            f"{display_name}'s Activity"
                        ),
                        icon_url=(
                            member
                            .display_avatar
                            .url
                        ),
                    )
                else:
                    embed.set_author(
                        name=(
                            f"{display_name}'s Activity"
                        )
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
                        "Failed to send embed"
                    )

        if announce_keys:
            await storage.add_announced(
                discord_user_id,
                announce_keys,
            )

        if newest_seen > since_dt:
            await storage.update_last_checked(
                discord_user_id,
                media_type,
                newest_seen.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            )


# ---------------------------------------------------------------------------
# Background polling
# ---------------------------------------------------------------------------

poll_task_started = False


@bot.event
async def on_ready():
    global poll_task_started

    log.info(
        "Logged in as %s",
        bot.user,
    )

    if not poll_task_started:
        poll_task_started = True

        bot.loop.create_task(
            polling_loop()
        )


async def polling_loop():
    await bot.wait_until_ready()

    while not bot.is_closed():
        data = await storage.get_all()

        interval_minutes = data.get(
            "poll_interval_minutes",
            5,
        )

        try:
            await poll_all_users()

        except Exception:
            log.exception(
                "Error during polling cycle"
            )

        await asyncio.sleep(
            max(interval_minutes, 1) * 60
        )


# ---------------------------------------------------------------------------
# Start bot
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)
