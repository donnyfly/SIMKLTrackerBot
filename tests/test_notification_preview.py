"""Debug previews must use real notification cards without changing progression."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

from discord import app_commands
from PIL import Image

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
os.environ.setdefault("SIMKL_CLIENT_ID", "test-client")
os.environ.setdefault("TMDB_API_KEY", "test-key")

import bot  # noqa: E402
from achievements import ACHIEVEMENTS  # noqa: E402
from level_visuals import accent_for_level, render_achievement_gif, render_level_up_gif  # noqa: E402
from progression import RANKS, rank_for_level  # noqa: E402


def _interaction():
    return SimpleNamespace(
        guild=SimpleNamespace(id=123),
        user=SimpleNamespace(
            id=42, mention="<@42>",
            guild_permissions=SimpleNamespace(manage_guild=True),
        ),
        channel=SimpleNamespace(id=1),
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )


def test_achievement_animation_renders_every_defined_name():
    for achievement in ACHIEVEMENTS.values():
        animation=render_achievement_gif(achievement["name"], achievement["xp"])
        image=Image.open(animation)
        assert image.size == (720, 280)
        assert image.n_frames > 1
        assert image.info["duration"] >= 60
        assert len(animation.getvalue()) < 8_000_000


def test_level_animation_uses_each_rank_color():
    accents=[accent_for_level(minimum) for minimum, _ in RANKS]
    assert len(set(accents)) == len(RANKS)
    assert all(accent_for_level(minimum + 1) == color for (minimum, _), color in zip(RANKS, accents))
    footer_colors=[]
    for minimum in (1, 10, 50, 90):
        level=max(2, minimum)
        animation=render_level_up_gif(
            level, rank_for_level(level), previous_level=level - 1,
            previous_rank=rank_for_level(level - 1),
        )
        image=Image.open(animation)
        image.seek(image.n_frames - 1)
        footer_colors.append(image.convert("RGB").getpixel((400, 247)))
    assert len(set(footer_colors)) == 4


def test_debug_previews_are_private_and_do_not_write(monkeypatch):
    async def scenario():
        command=bot.bot.tree.get_command("simkl-debug")
        assert command is not None
        assert bot.bot.tree.get_command("simkl-achievement-test") is None
        assert command.default_permissions.manage_guild
        forbidden=AsyncMock(side_effect=AssertionError("preview wrote to storage"))
        monkeypatch.setattr(bot.storage, "unlock_achievement", forbidden)
        monkeypatch.setattr(bot.storage, "award_achievement_xp", forbidden)
        monkeypatch.setattr(bot.storage, "flush", forbidden)
        monkeypatch.setattr(bot.storage, "get_progression", AsyncMock(return_value={"xp": 0}))

        achievement=_interaction()
        await command.callback(
            achievement, app_commands.Choice(name="Achievement unlocked", value="achievement"),
            app_commands.Choice(name="First Watch", value="first_watch"),
        )
        achievement.response.defer.assert_awaited_once_with(ephemeral=True)
        sent=achievement.followup.send.await_args.kwargs
        assert sent["ephemeral"] is True
        assert sent["embed"].image.url == "attachment://achievement.gif"
        assert sent["file"].filename == "achievement.gif"

        rank=_interaction()
        await command.callback(rank, app_commands.Choice(name="Rank up", value="rank"))
        rank.response.defer.assert_awaited_once_with(ephemeral=True)
        sent=rank.followup.send.await_args.kwargs
        assert sent["ephemeral"] is True
        assert sent["embed"].title == "Rank Up"
        assert sent["embed"].image.url == "attachment://level-up.gif"
        forbidden.assert_not_awaited()

    asyncio.run(scenario())


def test_achievement_notification_falls_back_to_embed(monkeypatch):
    async def scenario():
        monkeypatch.setattr(bot, "render_achievement_gif", lambda *args: (_ for _ in ()).throw(RuntimeError("render failed")))
        send=AsyncMock()
        assert await bot.send_achievement_notification(send, "<@42>", "first_watch", preview=True)
        send.assert_awaited_once()
        assert send.await_args.kwargs["embed"].image.url is None
        assert send.await_args.kwargs["ephemeral"] is True

    asyncio.run(scenario())
