"""
Tests for utils/database.py

These run against a real SQLite file (via aiosqlite) in a pytest tmp_path,
rather than mocking the DB layer — this module's whole job is translating
between Python dicts and SQL rows (including JSON-encoded columns), so a
mock would just restate the implementation instead of verifying it.
"""

import aiosqlite
import pytest

from utils.database import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "campaign.db"))
    await database.init()
    return database


def character_data(**overrides):
    data = {
        "name": "Thoradin",
        "class": "Fighter",
        "hp_max": 10,
        "hp_current": 10,
        "str": 16,
        "dex": 12,
        "con": 14,
        "int": 9,
        "wis": 10,
        "cha": 8,
    }
    data.update(overrides)
    return data


# ── init ─────────────────────────────────────────────────────────────────────

async def test_init_is_idempotent(tmp_path):
    database = Database(str(tmp_path / "campaign.db"))
    await database.init()
    await database.init()  # should not raise on re-run (CREATE TABLE IF NOT EXISTS)


async def test_init_creates_parent_directory(tmp_path):
    nested_path = tmp_path / "nested" / "dir" / "campaign.db"
    database = Database(str(nested_path))
    await database.init()
    assert nested_path.parent.exists()


# ── Campaigns ────────────────────────────────────────────────────────────────

async def test_get_campaign_returns_none_when_missing(db):
    assert await db.get_campaign("g1", "c1") is None


async def test_get_or_create_campaign_creates_new(db):
    campaign = await db.get_or_create_campaign("g1", "c1", "The Sunless Citadel")
    assert campaign["guild_id"] == "g1"
    assert campaign["channel_id"] == "c1"
    assert campaign["name"] == "The Sunless Citadel"
    assert campaign["id"] is not None


async def test_get_or_create_campaign_returns_existing_on_second_call(db):
    first = await db.get_or_create_campaign("g1", "c1", "First Name")
    second = await db.get_or_create_campaign("g1", "c1", "Ignored Name")

    assert second["id"] == first["id"]
    assert second["name"] == "First Name"  # unchanged — get, not overwrite


async def test_update_campaign_persists_changes(db):
    campaign = await db.get_or_create_campaign("g1", "c1")
    await db.update_campaign(campaign["id"], name="New Name", module="B2")

    updated = await db.get_campaign("g1", "c1")
    assert updated["name"] == "New Name"
    assert updated["module"] == "B2"


# ── Characters ───────────────────────────────────────────────────────────────

async def test_create_and_get_character_round_trips_fields(db):
    campaign = await db.get_or_create_campaign("g1", "c1")
    await db.create_character(campaign["id"], "user-1", character_data(
        inventory=["Torch", "Rope"], weapons_armor=["Sword", "Chain mail"], spells=["Sleep"],
    ))

    char = await db.get_character(campaign["id"], "user-1")
    assert char["name"] == "Thoradin"
    assert char["class"] == "Fighter"
    assert char["race"] == "Human"  # default
    assert char["inventory"] == ["Torch", "Rope"]
    assert char["weapons_armor"] == ["Sword", "Chain mail"]
    assert char["spells"] == ["Sleep"]
    assert char["alive"] == 1


async def test_create_character_applies_defaults(db):
    campaign = await db.get_or_create_campaign("g1", "c1")
    await db.create_character(campaign["id"], "user-1", character_data())

    char = await db.get_character(campaign["id"], "user-1")
    assert char["level"] == 1
    assert char["xp"] == 0
    assert char["ac"] == 9
    assert char["gold"] == 0
    assert char["inventory"] == []
    assert char["weapons_armor"] == []
    assert char["spells"] == []


async def test_get_character_missing_returns_none(db):
    campaign = await db.get_or_create_campaign("g1", "c1")
    assert await db.get_character(campaign["id"], "nobody") is None


async def test_get_character_excludes_dead_characters(db):
    campaign = await db.get_or_create_campaign("g1", "c1")
    await db.create_character(campaign["id"], "user-1", character_data())
    await db.update_character(campaign["id"], "user-1", alive=0)

    assert await db.get_character(campaign["id"], "user-1") is None


async def test_get_all_characters_returns_only_alive(db):
    campaign = await db.get_or_create_campaign("g1", "c1")
    await db.create_character(campaign["id"], "user-1", character_data(name="Thoradin"))
    await db.create_character(campaign["id"], "user-2", character_data(name="Wren"))
    await db.update_character(campaign["id"], "user-2", alive=0)

    chars = await db.get_all_characters(campaign["id"])
    assert [c["name"] for c in chars] == ["Thoradin"]


async def test_update_character_reencodes_inventory_and_spells(db):
    campaign = await db.get_or_create_campaign("g1", "c1")
    await db.create_character(campaign["id"], "user-1", character_data())

    await db.update_character(
        campaign["id"], "user-1",
        inventory=["Rations", "Rope"], weapons_armor=["Sword", "Shield"],
        spells=["Light"], hp_current=3,
    )

    char = await db.get_character(campaign["id"], "user-1")
    assert char["inventory"] == ["Rations", "Rope"]
    assert char["weapons_armor"] == ["Sword", "Shield"]
    assert char["spells"] == ["Light"]
    assert char["hp_current"] == 3


async def test_init_migrates_pre_weapons_armor_database(tmp_path):
    """A DB created before the weapons_armor column existed gets it added
    (and backfilled to []) the next time init() runs."""
    path = tmp_path / "old.db"
    async with aiosqlite.connect(str(path)) as conn:
        await conn.execute("""
            CREATE TABLE characters (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id     INTEGER NOT NULL,
                discord_user_id TEXT NOT NULL,
                name            TEXT NOT NULL,
                class           TEXT NOT NULL,
                race            TEXT NOT NULL DEFAULT 'Human',
                level           INTEGER NOT NULL DEFAULT 1,
                xp              INTEGER NOT NULL DEFAULT 0,
                hp_max          INTEGER NOT NULL,
                hp_current      INTEGER NOT NULL,
                str INTEGER NOT NULL, dex INTEGER NOT NULL, con INTEGER NOT NULL,
                int INTEGER NOT NULL, wis INTEGER NOT NULL, cha INTEGER NOT NULL,
                ac              INTEGER NOT NULL DEFAULT 9,
                gold            REAL NOT NULL DEFAULT 0,
                inventory       TEXT NOT NULL DEFAULT '[]',
                spells          TEXT NOT NULL DEFAULT '[]',
                notes           TEXT NOT NULL DEFAULT '',
                alive           INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT NOT NULL,
                UNIQUE(campaign_id, discord_user_id)
            )
        """)
        await conn.execute("""
            INSERT INTO characters
              (campaign_id, discord_user_id, name, class, hp_max, hp_current,
               str, dex, con, int, wis, cha, created_at)
            VALUES (1, 'user-1', 'Old Timer', 'Fighter', 8, 8,
                    12, 12, 12, 12, 12, 12, '2026-01-01T00:00:00')
        """)
        await conn.commit()

    database = Database(str(path))
    await database.init()

    char = await database.get_character(1, "user-1")
    assert char["name"] == "Old Timer"
    assert char["weapons_armor"] == []


async def test_characters_are_scoped_per_campaign(db):
    c1 = await db.get_or_create_campaign("g1", "c1")
    c2 = await db.get_or_create_campaign("g1", "c2")
    await db.create_character(c1["id"], "user-1", character_data(name="Thoradin"))

    assert await db.get_character(c2["id"], "user-1") is None


# ── Session Log ──────────────────────────────────────────────────────────────

async def test_log_message_and_get_history_preserves_order(db):
    campaign = await db.get_or_create_campaign("g1", "c1")
    await db.log_message(campaign["id"], "user", "I open the door.", author_name="Sean")
    await db.log_message(campaign["id"], "assistant", "The door creaks open.")
    await db.log_message(campaign["id"], "user", "I step inside.", author_name="Sean")

    history = await db.get_history(campaign["id"], limit=20)

    assert [h["content"] for h in history] == [
        "I open the door.", "The door creaks open.", "I step inside.",
    ]


async def test_get_history_respects_limit_and_keeps_most_recent(db):
    campaign = await db.get_or_create_campaign("g1", "c1")
    for i in range(5):
        await db.log_message(campaign["id"], "user", f"message {i}")

    history = await db.get_history(campaign["id"], limit=2)

    assert [h["content"] for h in history] == ["message 3", "message 4"]


async def test_get_history_empty_campaign_returns_empty_list(db):
    campaign = await db.get_or_create_campaign("g1", "c1")
    assert await db.get_history(campaign["id"]) == []


# ── World State ──────────────────────────────────────────────────────────────

async def test_set_and_get_world_state(db):
    campaign = await db.get_or_create_campaign("g1", "c1")
    await db.set_world_state(campaign["id"], "current_location", "Cavern Entrance")

    world = await db.get_world_state(campaign["id"])
    assert world == {"current_location": "Cavern Entrance"}


async def test_set_world_state_upserts_existing_key(db):
    campaign = await db.get_or_create_campaign("g1", "c1")
    await db.set_world_state(campaign["id"], "current_location", "Room 1")
    await db.set_world_state(campaign["id"], "current_location", "Room 2")

    world = await db.get_world_state(campaign["id"])
    assert world == {"current_location": "Room 2"}


async def test_world_state_scoped_per_campaign(db):
    c1 = await db.get_or_create_campaign("g1", "c1")
    c2 = await db.get_or_create_campaign("g1", "c2")
    await db.set_world_state(c1["id"], "key", "value-for-c1")

    assert await db.get_world_state(c2["id"]) == {}


# ── Reset / Delete ───────────────────────────────────────────────────────────

async def seeded_campaign(db, guild="g1", channel="c1"):
    campaign = await db.get_or_create_campaign(guild, channel)
    await db.create_character(campaign["id"], "user-1", character_data())
    await db.log_message(campaign["id"], "user", "I open the door.", author_name="Sean")
    await db.set_world_state(campaign["id"], "current_location", "Room 1")
    return campaign


async def test_delete_campaign_removes_campaign_row(db):
    campaign = await seeded_campaign(db)
    await db.delete_campaign(campaign["id"])

    assert await db.get_campaign("g1", "c1") is None


async def test_delete_campaign_removes_characters(db):
    campaign = await seeded_campaign(db)
    await db.delete_campaign(campaign["id"])

    assert await db.get_character(campaign["id"], "user-1") is None
    assert await db.get_all_characters(campaign["id"]) == []


async def test_delete_campaign_removes_session_log(db):
    campaign = await seeded_campaign(db)
    await db.delete_campaign(campaign["id"])

    assert await db.get_history(campaign["id"]) == []


async def test_delete_campaign_removes_world_state(db):
    campaign = await seeded_campaign(db)
    await db.delete_campaign(campaign["id"])

    assert await db.get_world_state(campaign["id"]) == {}


async def test_delete_campaign_does_not_affect_other_campaigns(db):
    doomed = await seeded_campaign(db, channel="c1")
    kept = await seeded_campaign(db, channel="c2")

    await db.delete_campaign(doomed["id"])

    assert await db.get_campaign("g1", "c2") is not None
    assert len(await db.get_all_characters(kept["id"])) == 1
    assert len(await db.get_history(kept["id"])) == 1
    assert await db.get_world_state(kept["id"]) == {"current_location": "Room 1"}


async def test_delete_campaign_is_idempotent_when_campaign_missing(db):
    await db.delete_campaign(999999)  # should not raise
