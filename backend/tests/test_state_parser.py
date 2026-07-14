"""
Tests for utils/state_parser.py

This module parses [STATE_UPDATE] blocks out of raw LLM text and applies
the resulting HP/XP/gold/inventory/world changes to the database. It's
the module most likely to silently misbehave, since its input is
free-form model output rather than a strict API contract — so it's the
highest-value place in the project to have tests.

The database is faked with unittest.mock.AsyncMock rather than hitting
a real DB — these tests only care that apply_state_changes() computes
the *right values* and calls the *right db methods*, not that SQLite
itself works.
"""

import pytest
from unittest.mock import AsyncMock

from utils.state_parser import (
    strip_state_block,
    parse_state_block,
    apply_state_changes,
)


# ── strip_state_block() ─────────────────────────────────────────────────────

def test_strip_state_block_removes_block_and_trims():
    text = (
        "You step into the cavern.\n\n"
        "[STATE_UPDATE]\n"
        "hp:Thoradin:-3\n"
        "[/STATE_UPDATE]"
    )
    assert strip_state_block(text) == "You step into the cavern."


def test_strip_state_block_no_block_present():
    text = "Nothing changed this turn. What do you do?"
    assert strip_state_block(text) == text


def test_strip_state_block_is_case_insensitive():
    text = "Text.\n[state_update]\nhp:Thoradin:-1\n[/State_Update]"
    assert strip_state_block(text) == "Text."


# ── parse_state_block() ─────────────────────────────────────────────────────

def test_parse_state_block_extracts_all_fields():
    text = (
        "[STATE_UPDATE]\n"
        "hp:Thoradin:-3\n"
        "xp:Thoradin:+50\n"
        "gold:Thoradin:+10.5\n"
        "item_add:Thoradin:Torch x3\n"
        "item_remove:Thoradin:Iron Ration\n"
        "world:current_location:Cavern of the Kobold King\n"
        "[/STATE_UPDATE]"
    )
    actions = parse_state_block(text)

    assert actions == [
        {"type": "hp", "target": "Thoradin", "value": "-3"},
        {"type": "xp", "target": "Thoradin", "value": "+50"},
        {"type": "gold", "target": "Thoradin", "value": "+10.5"},
        {"type": "item_add", "target": "Thoradin", "value": "Torch x3"},
        {"type": "item_remove", "target": "Thoradin", "value": "Iron Ration"},
        {"type": "world", "target": "current_location", "value": "Cavern of the Kobold King"},
    ]


def test_parse_state_block_no_block_returns_empty_list():
    assert parse_state_block("Just narration, no block here.") == []


def test_parse_state_block_skips_malformed_lines():
    # "hp:Thoradin" has no value segment — split(":", 2) yields only 2 parts
    text = (
        "[STATE_UPDATE]\n"
        "hp:Thoradin\n"
        "xp:Thoradin:+10\n"
        "[/STATE_UPDATE]"
    )
    actions = parse_state_block(text)
    assert actions == [{"type": "xp", "target": "Thoradin", "value": "+10"}]


def test_parse_state_block_ignores_blank_lines():
    text = "[STATE_UPDATE]\n\nxp:Thoradin:+10\n\n[/STATE_UPDATE]"
    actions = parse_state_block(text)
    assert len(actions) == 1


def test_parse_state_block_value_can_contain_colons():
    # split(":", 2) means only the first two colons are delimiters —
    # a value like a time or a ratio shouldn't get truncated.
    text = "[STATE_UPDATE]\nworld:last_rest_time:10:30 AM\n[/STATE_UPDATE]"
    actions = parse_state_block(text)
    assert actions == [{"type": "world", "target": "last_rest_time", "value": "10:30 AM"}]


# ── apply_state_changes() ───────────────────────────────────────────────────

@pytest.fixture
def db():
    fake = AsyncMock()
    return fake


@pytest.fixture
def characters():
    return [
        {
            "discord_user_id": "Sean",
            "name": "Thoradin",
            "hp_current": 10,
            "xp": 100,
            "gold": 20.0,
            "inventory": ["Torch", "Iron Ration"],
        },
        {
            "discord_user_id": "Friend1",
            "name": "Wren",
            "hp_current": 2,
            "xp": 0,
            "gold": 0.0,
            "inventory": [],
        },
    ]


async def test_hp_damage_is_applied_and_floored_at_zero(db, characters):
    actions = [{"type": "hp", "target": "Wren", "value": "-99"}]
    await apply_state_changes(db, 1, actions, characters)

    db.update_character.assert_awaited_once_with(
        1, "Friend1", hp_current=0, alive=0
    )


async def test_hp_healing_marks_character_alive(db, characters):
    actions = [{"type": "hp", "target": "Thoradin", "value": "+5"}]
    await apply_state_changes(db, 1, actions, characters)

    db.update_character.assert_awaited_once_with(
        1, "Sean", hp_current=15, alive=1
    )


async def test_hp_target_lookup_is_case_insensitive(db, characters):
    actions = [{"type": "hp", "target": "thoradin", "value": "-1"}]
    await apply_state_changes(db, 1, actions, characters)
    db.update_character.assert_awaited_once()


async def test_unknown_character_for_hp_is_skipped_without_crashing(db, characters):
    actions = [{"type": "hp", "target": "Nobody", "value": "-5"}]
    await apply_state_changes(db, 1, actions, characters)
    db.update_character.assert_not_awaited()


async def test_xp_is_floored_at_zero(db, characters):
    actions = [{"type": "xp", "target": "Wren", "value": "-500"}]
    await apply_state_changes(db, 1, actions, characters)
    db.update_character.assert_awaited_once_with(1, "Friend1", xp=0)


async def test_gold_is_floored_at_zero_and_supports_floats(db, characters):
    actions = [{"type": "gold", "target": "Thoradin", "value": "-100.75"}]
    await apply_state_changes(db, 1, actions, characters)
    db.update_character.assert_awaited_once_with(1, "Sean", gold=0.0)


async def test_item_add_appends_without_mutating_original_list(db, characters):
    original_inventory = characters[0]["inventory"]
    actions = [{"type": "item_add", "target": "Thoradin", "value": "Rope, 50ft"}]

    await apply_state_changes(db, 1, actions, characters)

    db.update_character.assert_awaited_once_with(
        1, "Sean", inventory=["Torch", "Iron Ration", "Rope, 50ft"]
    )
    # The character dict passed in shouldn't be mutated in place
    assert original_inventory == ["Torch", "Iron Ration"]


async def test_item_remove_matches_case_insensitive_prefix(db, characters):
    actions = [{"type": "item_remove", "target": "Thoradin", "value": "iron"}]
    await apply_state_changes(db, 1, actions, characters)
    db.update_character.assert_awaited_once_with(1, "Sean", inventory=["Torch"])


async def test_item_remove_missing_item_is_a_noop_update(db, characters):
    actions = [{"type": "item_remove", "target": "Thoradin", "value": "Excalibur"}]
    await apply_state_changes(db, 1, actions, characters)
    # Still calls update_character, just with an unchanged inventory
    db.update_character.assert_awaited_once_with(
        1, "Sean", inventory=["Torch", "Iron Ration"]
    )


async def test_world_update_applies_even_for_unknown_target(db, characters):
    actions = [{"type": "world", "target": "current_threat", "value": "3 kobolds remain"}]
    await apply_state_changes(db, 1, actions, characters)
    db.set_world_state.assert_awaited_once_with(1, "current_threat", "3 kobolds remain")


async def test_unknown_action_type_is_ignored(db, characters):
    actions = [{"type": "teleport", "target": "Thoradin", "value": "Narnia"}]
    await apply_state_changes(db, 1, actions, characters)
    db.update_character.assert_not_awaited()
    db.set_world_state.assert_not_awaited()


async def test_multiple_actions_applied_in_order(db, characters):
    actions = [
        {"type": "hp", "target": "Thoradin", "value": "-2"},
        {"type": "xp", "target": "Thoradin", "value": "+50"},
        {"type": "world", "target": "current_location", "value": "Room 4"},
    ]
    await apply_state_changes(db, 1, actions, characters)

    assert db.update_character.await_count == 2
    db.set_world_state.assert_awaited_once_with(1, "current_location", "Room 4")