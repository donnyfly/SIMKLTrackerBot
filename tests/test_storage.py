import asyncio
import json

import storage as storage_module


def test_poll_health_is_persisted_and_loaded(tmp_path, monkeypatch):
    data_path = tmp_path / "store.json"
    monkeypatch.setattr(storage_module, "DATA_PATH", str(data_path))

    async def scenario():
        store = storage_module.Storage()
        store._data["users"]["42"] = {
            "simkl_token": "token",
            "simkl_username": "tester",
        }
        store._guild("123", create=True)["users"]["42"] = storage_module._default_guild_user()
        await store.update_poll_health(
            "123",
            "42",
            last_poll_at="2026-09-23T10:00:00Z",
            last_success_at="2026-09-23T10:00:05Z",
            last_error="",
        )

        with data_path.open("r", encoding="utf-8") as f:
            saved = json.load(f)
        saved_user = saved["guilds"]["123"]["users"]["42"]
        assert saved_user["last_poll_at"] == "2026-09-23T10:00:00Z"
        assert saved_user["last_success_at"] == "2026-09-23T10:00:05Z"
        assert saved_user["last_error"] == ""

        reloaded = storage_module.Storage()
        loaded_user = reloaded._guild_user("123", "42")
        assert loaded_user["last_poll_at"] == "2026-09-23T10:00:00Z"
        assert loaded_user["last_success_at"] == "2026-09-23T10:00:05Z"
        assert loaded_user["last_error"] == ""

    asyncio.run(scenario())


def test_existing_guild_user_gets_new_health_defaults(tmp_path, monkeypatch):
    data_path = tmp_path / "store.json"
    data_path.write_text(
        json.dumps(
            {
                "poll_interval_minutes": 60,
                "users": {},
                "guilds": {
                    "123": {
                        "channel_id": 456,
                        "embed_preferences": {},
                        "users": {
                            "42": {
                                "history_seeded": True,
                                "last_checked": {},
                                "announced": [],
                                "activity_state": {},
                            }
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(storage_module, "DATA_PATH", str(data_path))

    store = storage_module.Storage()
    user = store._guild_user("123", "42")
    assert user["last_poll_at"] is None
    assert user["last_success_at"] is None
    assert user["last_error"] is None
