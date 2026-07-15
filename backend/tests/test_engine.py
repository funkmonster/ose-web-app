"""
Tests for engine.py — the GM loop, decoupled from transport.

The db layer and the LLM call are both mocked out (they have their own
test suites in test_database.py and test_llm.py); these tests only verify
GameEngine's own orchestration logic — what gets read, what gets written,
and in what order — plus the two pure prompt-building helper functions.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import engine as engine_module
from engine import GameEngine, build_messages, build_context_prefix, GUILD, CHANNEL


def make_config(**overrides):
    defaults = dict(HISTORY_WINDOW=20, SUMMARIZE_EVERY=10, SUMMARIZE_CONTEXT_WINDOW=40)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_character(**overrides):
    data = {
        "discord_user_id": "Sean", "name": "Thoradin", "class": "Fighter", "level": 1,
        "hp_current": 10, "hp_max": 10, "alive": 1, "ac": 7, "gold": 20.0,
        "inventory": [], "weapons_armor": [], "spells": [],
    }
    data.update(overrides)
    return data


@pytest.fixture
def db():
    return AsyncMock()


@pytest.fixture
def config():
    return make_config()


@pytest.fixture
def game(db, config):
    return GameEngine(db, config)


# ── get_campaign() ───────────────────────────────────────────────────────────

async def test_get_campaign_delegates_to_db(game, db):
    db.get_campaign.return_value = {"id": 1, "name": "X"}
    db.get_world_state.return_value = {}
    result = await game.get_campaign()
    db.get_campaign.assert_awaited_once_with(GUILD, CHANNEL)
    assert result == {"id": 1, "name": "X", "physical_dice_mode": False}


# ── start_campaign() ─────────────────────────────────────────────────────────

async def test_start_campaign_creates_and_seeds_opening_narration(game, db, monkeypatch):
    db.get_or_create_campaign.return_value = {"id": 1}
    db.get_history.return_value = []
    get_gm_response = AsyncMock(
        return_value="You stand before a gate.\n[STATE_UPDATE]\nworld:loc:Gate\n[/STATE_UPDATE]"
    )
    monkeypatch.setattr(engine_module, "get_gm_response", get_gm_response)

    result = await game.start_campaign("The Sunless Citadel", "B1")

    db.update_campaign.assert_awaited_once_with(1, name="The Sunless Citadel", module="B1")
    assert result["campaign"] == {"name": "The Sunless Citadel", "module": "B1"}
    assert result["narration"] == "You stand before a gate."


async def test_start_campaign_logs_system_prompt_then_raw_gm_reply(game, db, monkeypatch):
    db.get_or_create_campaign.return_value = {"id": 1}
    db.get_history.return_value = []
    monkeypatch.setattr(engine_module, "get_gm_response", AsyncMock(return_value="Opening scene."))

    await game.start_campaign("Camp", "Module X")

    first_call = db.log_message.await_args_list[0]
    assert first_call.args[0:2] == (1, "user")
    assert first_call.kwargs["author_id"] == "SYSTEM"
    assert "Camp" in first_call.args[2]
    assert "Module X" in first_call.args[2]

    second_call = db.log_message.await_args_list[1]
    assert second_call.args == (1, "assistant", "Opening scene.")


# ── play() ────────────────────────────────────────────────────────────────────

async def test_play_raises_when_no_campaign(game, db):
    db.get_campaign.return_value = None
    with pytest.raises(ValueError, match="No campaign has been started"):
        await game.play("Sean", "I look around.")


async def test_play_raises_when_no_character(game, db):
    db.get_campaign.return_value = {"id": 1}
    db.get_character.return_value = None
    with pytest.raises(ValueError, match="don't have a character"):
        await game.play("Sean", "I look around.")


async def test_play_raises_when_character_dead(game, db):
    db.get_campaign.return_value = {"id": 1}
    db.get_character.return_value = make_character(alive=0, name="Thoradin")
    with pytest.raises(ValueError, match="Thoradin is dead"):
        await game.play("Sean", "I look around.")


@pytest.fixture
def play_setup(db, monkeypatch):
    """Common wiring for a successful play() call."""
    char = make_character()
    db.get_campaign.return_value = {"id": 1}
    db.get_character.return_value = char
    db.get_world_state.return_value = {}
    db.get_all_characters.return_value = [char]
    db.get_history.return_value = []
    monkeypatch.setattr(engine_module, "maybe_update_summary", AsyncMock())
    return char


async def test_play_logs_player_action_with_character_context(game, db, play_setup, monkeypatch):
    monkeypatch.setattr(engine_module, "get_gm_response", AsyncMock(return_value="You proceed."))

    await game.play("Sean", "I open the door.")

    player_call = db.log_message.await_args_list[0]
    assert player_call.args[0:2] == (1, "user")
    assert "Thoradin, Fighter Lvl 1" in player_call.args[2]
    assert "HP 10/10" in player_call.args[2]
    assert "I open the door." in player_call.args[2]
    assert player_call.kwargs == {"author_id": "Sean", "author_name": "Sean"}


async def test_play_triggers_summary_check(game, db, play_setup, monkeypatch):
    summary_mock = AsyncMock()
    monkeypatch.setattr(engine_module, "maybe_update_summary", summary_mock)
    monkeypatch.setattr(engine_module, "get_gm_response", AsyncMock(return_value="You proceed."))

    await game.play("Sean", "I open the door.")

    summary_mock.assert_awaited_once_with(db, 1, game.config)


async def test_play_returns_narration_without_state_actions(game, db, play_setup, monkeypatch):
    monkeypatch.setattr(engine_module, "get_gm_response", AsyncMock(return_value="Just narration."))
    apply_mock = AsyncMock()
    monkeypatch.setattr(engine_module, "apply_state_changes", apply_mock)

    result = await game.play("Sean", "I open the door.")

    assert result["narration"] == "Just narration."
    assert result["state_actions"] == []
    apply_mock.assert_not_awaited()


async def test_play_applies_and_returns_state_actions(game, db, play_setup, monkeypatch):
    gm_reply = "You take damage.\n[STATE_UPDATE]\nhp:Thoradin:-3\n[/STATE_UPDATE]"
    monkeypatch.setattr(engine_module, "get_gm_response", AsyncMock(return_value=gm_reply))
    apply_mock = AsyncMock()
    monkeypatch.setattr(engine_module, "apply_state_changes", apply_mock)

    result = await game.play("Sean", "I fight the goblin.")

    assert result["state_actions"] == [{"type": "hp", "target": "Thoradin", "value": "-3"}]
    apply_mock.assert_awaited_once_with(db, 1, result["state_actions"], [play_setup])
    assert result["narration"] == "You take damage."


async def test_play_logs_raw_gm_reply_not_stripped_text(game, db, play_setup, monkeypatch):
    gm_reply = "Damage dealt.\n[STATE_UPDATE]\nhp:Thoradin:-1\n[/STATE_UPDATE]"
    monkeypatch.setattr(engine_module, "get_gm_response", AsyncMock(return_value=gm_reply))
    monkeypatch.setattr(engine_module, "apply_state_changes", AsyncMock())

    await game.play("Sean", "I fight.")

    assistant_call = db.log_message.await_args_list[1]
    assert assistant_call.args == (1, "assistant", gm_reply)


async def test_play_returns_freshly_refetched_character(game, db, play_setup, monkeypatch):
    monkeypatch.setattr(engine_module, "get_gm_response", AsyncMock(return_value="You proceed."))
    healed_char = make_character(hp_current=7)
    db.get_character.side_effect = [play_setup, healed_char]

    result = await game.play("Sean", "I open the door.")

    assert result["character"] == healed_char
    assert db.get_character.await_count == 2


# ── recap() ───────────────────────────────────────────────────────────────────

async def test_recap_raises_when_no_campaign(game, db):
    db.get_campaign.return_value = None
    with pytest.raises(ValueError, match="No campaign started"):
        await game.recap()


async def test_recap_strips_state_block_and_asks_for_brief_summary(game, db, monkeypatch):
    db.get_campaign.return_value = {"id": 1}
    db.get_history.return_value = []
    db.get_world_state.return_value = {}
    db.get_all_characters.return_value = []
    get_gm_response = AsyncMock(
        return_value="So far, the party has explored the dungeon.\n[STATE_UPDATE]\nworld:x:y\n[/STATE_UPDATE]"
    )
    monkeypatch.setattr(engine_module, "get_gm_response", get_gm_response)

    result = await game.recap()

    assert result == "So far, the party has explored the dungeon."
    sent_messages = get_gm_response.await_args.args[0]
    assert "brief recap" in sent_messages[-1]["content"]


# ── get_summary() ─────────────────────────────────────────────────────────────

async def test_get_summary_raises_when_no_campaign(game, db):
    db.get_campaign.return_value = None
    with pytest.raises(ValueError, match="No campaign started"):
        await game.get_summary()


async def test_get_summary_returns_summary_and_counts(game, db):
    db.get_campaign.return_value = {"id": 1}
    db.get_world_state.return_value = {
        "campaign_summary": "The party fights on.",
        "player_action_count": "23",
    }

    result = await game.get_summary()

    assert result == {
        "summary": "The party fights on.",
        "action_count": 23,
        "summarize_every": game.config.SUMMARIZE_EVERY,
    }


async def test_get_summary_defaults_when_world_state_empty(game, db):
    db.get_campaign.return_value = {"id": 1}
    db.get_world_state.return_value = {}

    result = await game.get_summary()

    assert result["summary"] == ""
    assert result["action_count"] == 0


# ── rest() ────────────────────────────────────────────────────────────────────

async def test_rest_raises_when_no_campaign(game, db):
    db.get_campaign.return_value = None
    with pytest.raises(ValueError, match="No campaign started"):
        await game.rest("long")


async def test_long_rest_heals_party_to_max_and_logs(game, db):
    db.get_campaign.return_value = {"id": 1}
    chars = [
        make_character(discord_user_id="Sean", name="Thoradin", hp_current=3, hp_max=10),
        make_character(discord_user_id="Wren", name="Wren", hp_current=1, hp_max=6),
    ]
    db.get_all_characters.return_value = chars

    result = await game.rest("long")

    db.update_character.assert_any_await(1, "Sean", hp_current=10)
    db.update_character.assert_any_await(1, "Wren", hp_current=6)
    db.log_message.assert_awaited_once()
    assert db.log_message.await_args.args[1] == "system"
    assert result == {
        "rest_type": "long",
        "party": [
            {"name": "Thoradin", "hp": 10, "hp_max": 10},
            {"name": "Wren", "hp": 6, "hp_max": 6},
        ],
    }


async def test_short_rest_does_not_heal_or_log(game, db):
    db.get_campaign.return_value = {"id": 1}
    chars = [make_character(discord_user_id="Sean", name="Thoradin", hp_current=3, hp_max=10)]
    db.get_all_characters.return_value = chars

    result = await game.rest("short")

    db.update_character.assert_not_awaited()
    db.log_message.assert_not_awaited()
    assert result == {"rest_type": "short", "party": [{"name": "Thoradin", "hp": 3, "hp_max": 10}]}


# ── gm_say() ──────────────────────────────────────────────────────────────────

async def test_gm_say_raises_when_no_campaign(game, db):
    db.get_campaign.return_value = None
    with pytest.raises(ValueError, match="No campaign started"):
        await game.gm_say("Hello party.")


async def test_gm_say_logs_as_gm(game, db):
    db.get_campaign.return_value = {"id": 1}
    await game.gm_say("A wizard appears.")
    db.log_message.assert_awaited_once_with(
        1, "assistant", "A wizard appears.", author_id="GM", author_name="GM"
    )


# ── update_hp() ───────────────────────────────────────────────────────────────

async def test_update_hp_raises_when_no_campaign(game, db):
    db.get_campaign.return_value = None
    with pytest.raises(ValueError, match="No campaign started"):
        await game.update_hp("Sean", -5)


async def test_update_hp_raises_when_no_character(game, db):
    db.get_campaign.return_value = {"id": 1}
    db.get_character.return_value = None
    with pytest.raises(ValueError, match="Sean has no character"):
        await game.update_hp("Sean", -5)


async def test_update_hp_damage_floors_at_zero_and_marks_dead(game, db):
    db.get_campaign.return_value = {"id": 1}
    db.get_character.return_value = make_character(hp_current=3, hp_max=10, name="Thoradin")

    result = await game.update_hp("Sean", -99)

    db.update_character.assert_awaited_once_with(1, "Sean", hp_current=0, alive=0)
    assert result == {"name": "Thoradin", "hp": 0, "hp_max": 10, "alive": False}


async def test_update_hp_healing_marks_alive(game, db):
    db.get_campaign.return_value = {"id": 1}
    db.get_character.return_value = make_character(hp_current=0, hp_max=10, name="Thoradin")

    result = await game.update_hp("Sean", 5)

    db.update_character.assert_awaited_once_with(1, "Sean", hp_current=5, alive=1)
    assert result["alive"] is True


# ── get_character() / get_party() ────────────────────────────────────────────

async def test_get_character_returns_none_when_no_campaign(game, db):
    db.get_campaign.return_value = None
    assert await game.get_character("Sean") is None


async def test_get_character_delegates_when_campaign_exists(game, db):
    db.get_campaign.return_value = {"id": 1}
    db.get_character.return_value = {"name": "Thoradin"}
    assert await game.get_character("Sean") == {"name": "Thoradin"}


async def test_get_party_returns_empty_when_no_campaign(game, db):
    db.get_campaign.return_value = None
    assert await game.get_party() == []


# ── create_character() ───────────────────────────────────────────────────────

def base_char_request(**overrides):
    data = dict(
        name="Thoradin", char_class="Fighter",
        str_score=14, dex_score=12, con_score=14,
        int_score=9, wis_score=10, cha_score=8,
        hp_max=8,
    )
    data.update(overrides)
    return data


async def test_create_character_raises_if_already_exists(game, db):
    db.get_or_create_campaign.return_value = {"id": 1}
    db.get_character.return_value = {"name": "Existing Hero"}

    with pytest.raises(ValueError, match="already have a character: Existing Hero"):
        await game.create_character("Sean", base_char_request())


async def test_create_character_raises_for_unknown_class(game, db):
    db.get_or_create_campaign.return_value = {"id": 1}
    db.get_character.return_value = None

    with pytest.raises(ValueError, match="Unknown class: Wizard"):
        await game.create_character("Sean", base_char_request(char_class="Wizard"))


async def test_create_character_normalizes_class_case_and_whitespace(game, db):
    db.get_or_create_campaign.return_value = {"id": 1}
    db.get_character.side_effect = [None, {"name": "Thoradin"}]

    await game.create_character("Sean", base_char_request(char_class="  fighter  "))

    created_data = db.create_character.await_args.args[2]
    assert created_data["class"] == "Fighter"


async def test_create_character_uses_provided_hp_max_as_is(game, db):
    db.get_or_create_campaign.return_value = {"id": 1}
    db.get_character.side_effect = [None, {"name": "Thoradin"}]

    await game.create_character("Sean", base_char_request(hp_max=17))

    created_data = db.create_character.await_args.args[2]
    assert created_data["hp_max"] == 17
    assert created_data["hp_current"] == 17


@pytest.mark.parametrize("char_class,expected_race", [
    ("Dwarf", "Dwarf"),
    ("Elf", "Elf"),
    ("Halfling", "Halfling"),
    ("Fighter", "Human"),
    ("Cleric", "Human"),
    ("Thief", "Human"),
    ("Magic-User", "Human"),
])
async def test_create_character_assigns_race_from_class(game, db, char_class, expected_race):
    db.get_or_create_campaign.return_value = {"id": 1}
    db.get_character.side_effect = [None, {"name": "X"}]

    await game.create_character("Sean", base_char_request(char_class=char_class))

    created_data = db.create_character.await_args.args[2]
    assert created_data["race"] == expected_race


async def test_create_character_persists_ability_scores_and_defaults(game, db):
    db.get_or_create_campaign.return_value = {"id": 1}
    db.get_character.side_effect = [None, {"name": "Thoradin"}]

    await game.create_character("Sean", base_char_request(
        str_score=16, dex_score=12, con_score=14, int_score=9, wis_score=10, cha_score=8,
    ))

    created_data = db.create_character.await_args.args[2]
    assert created_data["str"] == 16
    assert created_data["dex"] == 12
    assert created_data["con"] == 14
    assert created_data["int"] == 9
    assert created_data["wis"] == 10
    assert created_data["cha"] == 8
    assert created_data["level"] == 1
    assert created_data["xp"] == 0
    assert created_data["ac"] == 9
    assert created_data["gold"] == 0.0
    assert created_data["inventory"] == []
    assert created_data["weapons_armor"] == []
    assert created_data["spells"] == []


async def test_create_character_returns_final_db_record(game, db):
    db.get_or_create_campaign.return_value = {"id": 1}
    final_record = {"name": "Thoradin", "hp_max": 5}
    db.get_character.side_effect = [None, final_record]

    result = await game.create_character("Sean", base_char_request())

    assert result is final_record


# ── update_inventory() / update_spells() ─────────────────────────────────────

async def test_update_inventory_raises_when_no_campaign(game, db):
    db.get_campaign.return_value = None
    with pytest.raises(ValueError, match="No campaign started"):
        await game.update_inventory("Sean", ["Torch"])


async def test_update_inventory_delegates_to_db(game, db):
    db.get_campaign.return_value = {"id": 1}
    await game.update_inventory("Sean", ["Torch", "Rope"])
    db.update_character.assert_awaited_once_with(1, "Sean", inventory=["Torch", "Rope"])


async def test_update_weapons_armor_raises_when_no_campaign(game, db):
    db.get_campaign.return_value = None
    with pytest.raises(ValueError, match="No campaign started"):
        await game.update_weapons_armor("Sean", ["Sword"])


async def test_update_weapons_armor_delegates_to_db(game, db):
    db.get_campaign.return_value = {"id": 1}
    await game.update_weapons_armor("Sean", ["Sword", "Chain mail"])
    db.update_character.assert_awaited_once_with(1, "Sean", weapons_armor=["Sword", "Chain mail"])


async def test_update_spells_raises_when_no_campaign(game, db):
    db.get_campaign.return_value = None
    with pytest.raises(ValueError, match="No campaign started"):
        await game.update_spells("Sean", ["Sleep"])


async def test_update_spells_delegates_to_db(game, db):
    db.get_campaign.return_value = {"id": 1}
    await game.update_spells("Sean", ["Sleep"])
    db.update_character.assert_awaited_once_with(1, "Sean", spells=["Sleep"])


# ── get_feed() ────────────────────────────────────────────────────────────────

async def test_get_feed_returns_empty_when_no_campaign(game, db):
    db.get_campaign.return_value = None
    assert await game.get_feed() == []


async def test_get_feed_strips_state_blocks_from_assistant_messages_only(game, db):
    db.get_campaign.return_value = {"id": 1}
    db.get_history.return_value = [
        {"role": "user", "author_name": "Sean", "content": "I look around. [not a real block]"},
        {"role": "assistant", "author_name": None,
         "content": "You see a room.\n[STATE_UPDATE]\nworld:x:y\n[/STATE_UPDATE]"},
    ]

    feed = await game.get_feed()

    assert feed[0]["content"] == "I look around. [not a real block]"
    assert feed[1]["content"] == "You see a room."


async def test_get_feed_skips_system_authored_opening_prompt(game, db):
    db.get_campaign.return_value = {"id": 1}
    db.get_history.return_value = [
        {"role": "user", "author_name": "System", "content": "Begin the campaign..."},
        {"role": "assistant", "author_name": None, "content": "You awaken in a tavern."},
    ]

    feed = await game.get_feed()

    assert len(feed) == 1
    assert feed[0]["content"] == "You awaken in a tavern."


async def test_get_feed_respects_limit_argument(game, db):
    db.get_campaign.return_value = {"id": 1}
    db.get_history.return_value = []

    await game.get_feed(limit=5)

    db.get_history.assert_awaited_once_with(1, limit=5)


# ── build_messages() ──────────────────────────────────────────────────────────

def test_build_messages_empty_history_no_prefix():
    assert build_messages([]) == []


def test_build_messages_prepends_context_prefix_pair():
    messages = build_messages([], context_prefix="World state here.")
    assert messages == [
        {"role": "user", "content": "World state here."},
        {"role": "assistant", "content": "Understood. I have the current party and world state."},
    ]


def test_build_messages_prefixes_user_content_with_author():
    history = [{"role": "user", "author_name": "Sean", "content": "I open the door."}]
    messages = build_messages(history)
    assert messages == [{"role": "user", "content": "[Sean]: I open the door."}]


def test_build_messages_does_not_prefix_assistant_content():
    history = [{"role": "assistant", "author_name": None, "content": "It creaks open."}]
    messages = build_messages(history)
    assert messages == [{"role": "assistant", "content": "It creaks open."}]


def test_build_messages_non_standard_role_defaults_to_user():
    history = [{"role": "system", "author_name": None, "content": "A note."}]
    messages = build_messages(history)
    assert messages == [{"role": "user", "content": "A note."}]


def test_build_messages_preserves_history_order_after_prefix():
    history = [
        {"role": "user", "author_name": "Sean", "content": "first"},
        {"role": "assistant", "author_name": None, "content": "second"},
    ]
    messages = build_messages(history, context_prefix="ctx")
    assert [m["content"] for m in messages] == [
        "ctx", "Understood. I have the current party and world state.", "[Sean]: first", "second",
    ]


# ── build_context_prefix() ────────────────────────────────────────────────────

def test_build_context_prefix_always_has_header():
    prefix = build_context_prefix({}, [])
    assert prefix.startswith("[CURRENT STATE")


def test_build_context_prefix_includes_summary_when_present():
    prefix = build_context_prefix({"campaign_summary": "The party fled the goblins."}, [])
    assert "CAMPAIGN SUMMARY" in prefix
    assert "The party fled the goblins." in prefix


def test_build_context_prefix_omits_summary_section_when_blank():
    prefix = build_context_prefix({"campaign_summary": "   "}, [])
    assert "CAMPAIGN SUMMARY" not in prefix


def test_build_context_prefix_excludes_internal_keys_from_world_state():
    world = {
        "campaign_summary": "summary text",
        "player_action_count": "12",
        "current_location": "Cavern",
    }
    prefix = build_context_prefix(world, [])
    assert "current_location: Cavern" in prefix
    assert "player_action_count" not in prefix
    assert "12" not in prefix


def test_build_context_prefix_omits_world_state_section_when_only_internal_keys():
    world = {"campaign_summary": "x", "player_action_count": "1"}
    prefix = build_context_prefix(world, [])
    assert "Current World State" not in prefix


def test_build_context_prefix_formats_party_line():
    chars = [{
        "name": "Thoradin", "class": "Fighter", "level": 2,
        "hp_current": 8, "hp_max": 10, "ac": 4, "gold": 15.5,
        "inventory": [], "weapons_armor": [], "spells": [],
    }]
    prefix = build_context_prefix({}, chars)
    assert "Thoradin (Fighter Lvl 2) — HP 8/10, AC 4, Gold 15.5 gp" in prefix


def test_build_context_prefix_includes_gear_and_spells_when_present():
    chars = [{
        "name": "Elowen", "class": "Elf", "level": 1,
        "hp_current": 6, "hp_max": 6, "ac": 6, "gold": 0,
        "inventory": ["Torch", "Rope"], "weapons_armor": ["Sword", "Chain mail"],
        "spells": ["Sleep"],
    }]
    prefix = build_context_prefix({}, chars)
    assert "Weapons & Armour: Sword, Chain mail" in prefix
    assert "Inventory: Torch, Rope" in prefix
    assert "Spells: Sleep" in prefix


def test_build_context_prefix_omits_gear_and_spells_lines_when_empty():
    chars = [{
        "name": "Elowen", "class": "Elf", "level": 1,
        "hp_current": 6, "hp_max": 6, "ac": 6, "gold": 0,
        "inventory": [], "weapons_armor": [], "spells": [],
    }]
    prefix = build_context_prefix({}, chars)
    assert "Weapons & Armour" not in prefix
    assert "Inventory" not in prefix
    assert "Spells" not in prefix


def test_build_context_prefix_omits_party_section_when_no_characters():
    prefix = build_context_prefix({}, [])
    assert "Party:" not in prefix
