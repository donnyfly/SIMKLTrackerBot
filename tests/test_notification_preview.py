"""Debug previews must use real notification cards without changing progression."""

import asyncio
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

from discord import app_commands
from PIL import Image

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
os.environ.setdefault("SIMKL_CLIENT_ID", "test-client")
os.environ.setdefault("TMDB_API_KEY", "test-key")

import bot  # noqa: E402
import storage as storage_module  # noqa: E402
from achievements import ACHIEVEMENTS  # noqa: E402
from level_visuals import accent_for_level, prestige_style, render_achievement_gif, render_level_up_gif  # noqa: E402
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
        selected=_interaction()
        await command.callback(
            selected,app_commands.Choice(name="Level up",value="level"),
            level=43,rank=app_commands.Choice(name="Dedicated Viewer",value=40),prestige=6,
        )
        selected.response.defer.assert_awaited_once_with(ephemeral=True)
        sent=selected.followup.send.await_args.kwargs
        assert "Prestige **6**" in sent["embed"].description
        assert "Level 43" in sent["embed"].description
        assert sent["embed"].color.value == int.from_bytes(bytes(prestige_style(6)[0]),"big")
        prestige=_interaction()
        await command.callback(prestige, app_commands.Choice(name="Prestige unlocked",value="prestige"), prestige=3)
        prestige.response.defer.assert_awaited_once_with(ephemeral=True)
        sent=prestige.followup.send.await_args.kwargs
        assert sent["ephemeral"] is True
        assert sent["embed"].image.url == "attachment://prestige.gif"
        assert "Prestige 3" in sent["embed"].title
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


def test_simkl_reconciliation_updates_existing_stats_and_xp(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            monkeypatch.setattr(storage_module,"DATA_PATH",f"{directory}/store.json")
            store=storage_module.Storage()
            monkeypatch.setattr(bot,"storage",store)
            await store.link_user("123","42","token",None,"tester","2026-09-20T00:00:00Z")
            for number in (1,2):
                key=f"series:shows:99:1:{number}"
                stamp=f"2026-09-2{number}T10:00:00Z"
                await store.record_watch("123","42","episode","Series",key,stamp)
                await store.award_watch_xp("42",f"episode:{key}:{stamp}","episode","Series",stamp,100)
            stats=store._data["guilds"]["123"]["users"]["42"]["statistics"]
            stats.pop("watch_events")  # Existing installations only had aggregate counts.

            def episode(number):
                return {"show":{"title":"Series","ids":{"simkl":99}},"seasons":[
                    {"number":1,"episodes":[{"number":number,"watched_at":f"2026-09-2{number}T10:00:00Z"}]}
                ]}

            current=[episode(2)]
            async def fetch(uid,user,token,media_type,**kwargs):
                return (current if media_type=="shows" else []),token
            monkeypatch.setattr(bot,"cached_simkl_items",fetch)
            await bot.reconcile_watch_progression("123","42",{},"token",{"shows"})
            assert (await store.get_statistics("123","42"))["episodes_watched"]==1
            assert (await store.get_progression("42"))["xp"]==100
            current.clear()
            await bot.reconcile_watch_progression("123","42",{},"token",{"shows"})
            assert (await store.get_statistics("123","42"))["episodes_watched"]==0
            assert (await store.get_progression("42"))["xp"]==0
    asyncio.run(scenario())


def test_consolidated_xp_leaderboard_orders_prestige_then_xp(monkeypatch):
    async def scenario():
        rows=[
            {"discord_user_id":"1","simkl_username":"One","xp":900,"prestige":0,"episodes":10,"movies":0,"anime":0},
            {"discord_user_id":"2","simkl_username":"Two","xp":100,"prestige":1,"episodes":5,"movies":0,"anime":0},
            {"discord_user_id":"3","simkl_username":"Three","xp":500,"prestige":1,"episodes":8,"movies":0,"anime":0},
        ]
        monkeypatch.setattr(bot.storage,"get_guild_leaderboard_snapshot",AsyncMock(return_value=rows))
        captured=[]
        def render(guild,category,values):
            captured.extend(row["discord_user_id"] for row in values)
            from io import BytesIO
            return BytesIO(b"preview")
        monkeypatch.setattr(bot,"render_leaderboard_png",render)
        interaction=_interaction()
        interaction.guild.name="Server"
        interaction.guild.get_member=lambda uid: None
        command=bot.bot.tree.get_command("simkl-leaderboard")
        await command.callback(interaction,app_commands.Choice(name="XP / progression",value="xp"))
        assert captured==["3","2","1"]
        interaction.response.defer.assert_awaited_once()
        assert interaction.followup.send.await_args.kwargs["file"].filename=="leaderboard.png"
        assert interaction.followup.send.await_args.kwargs["embed"].image.url=="attachment://leaderboard.png"
        assert bot.bot.tree.get_command("simkl-xp-leaderboard") is None
        assert bot.bot.tree.get_command("simkl-xp") is None
        assert bot.bot.tree.get_command("simkl-profile") is None
        assert bot.bot.tree.get_command("simkl-community") is not None
    asyncio.run(scenario())
