import asyncio
import tempfile

import storage as storage_module
from progression import level_from_xp, rank_for_level, xp_for_level, xp_for_watch


def test_progression_curve():
    assert xp_for_watch("episode") == 100
    assert xp_for_watch("movie") == 300
    assert level_from_xp(0) == 1
    assert level_from_xp(xp_for_level(10)) == 10
    assert rank_for_level(1) == "Newcomer"
    assert rank_for_level(50) == "Media Enthusiast"
    assert rank_for_level(90) == "Screen Immortal"


def test_challenge_rotation():
    from progression import challenges_for

    daily, weekly = challenges_for(__import__("datetime").date(2026, 9, 26))
    assert len(daily) == 3
    assert len(weekly) == 3
    assert all("target" in item and "xp" in item for item in daily + weekly)


def test_storage_watch_xp_is_idempotent():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            old_path = storage_module.DATA_PATH
            storage_module.DATA_PATH = f"{tmp}/store.json"
            try:
                store = storage_module.Storage()
                await store.link_user(
                    "123", "42", "token", "refresh", "tester",
                    "2026-09-26T00:00:00Z", token_expires_at=None, simkl_account_id=123,
                )
                first = await store.award_watch_xp(
                    "42", "episode:show:1:1:1:2026-09-26T10:00:00Z",
                    "episode", "Test Episode", "2026-09-26T10:00:00Z", 100,
                )
                second = await store.award_watch_xp(
                    "42", "episode:show:1:1:1:2026-09-26T10:00:00Z",
                    "episode", "Test Episode", "2026-09-26T10:00:00Z", 100,
                )
                progression = await store.get_progression("42")
                assert first["awarded"] is True
                assert second["awarded"] is False
                assert progression["xp"] == 100
                assert progression["lifetime_xp"] == 100
                assert len(progression["xp_events"]) == 1
            finally:
                storage_module.DATA_PATH = old_path

    asyncio.run(scenario())
