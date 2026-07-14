"""
Tests for utils/dice.py

These are plain synchronous tests (no async, no DB, no network) —
the fastest, cheapest tests in the project to run and the best place
to start if you're new to pytest.
"""

import pytest
from utils.dice import roll, roll_ability_scores, bx_modifier, format_modifier


# ── roll() — notation parsing ──────────────────────────────────────────────

def test_roll_basic_notation(monkeypatch):
    # Force every die to land on 4 so the math is predictable
    monkeypatch.setattr("utils.dice.random.randint", lambda a, b: 4)

    total, rolls, desc = roll("3d6")

    assert rolls == [4, 4, 4]
    assert total == 12
    assert "3D6" in desc


def test_roll_with_positive_modifier(monkeypatch):
    monkeypatch.setattr("utils.dice.random.randint", lambda a, b: 5)

    total, rolls, _ = roll("1d20+3")

    assert rolls == [5]
    assert total == 8


def test_roll_with_negative_modifier(monkeypatch):
    monkeypatch.setattr("utils.dice.random.randint", lambda a, b: 6)

    total, rolls, _ = roll("2d6-1")

    assert rolls == [6, 6]
    assert total == 11


def test_roll_implicit_single_die(monkeypatch):
    # "d6" with no leading count should behave like "1d6"
    monkeypatch.setattr("utils.dice.random.randint", lambda a, b: 3)

    total, rolls, _ = roll("d6")

    assert rolls == [3]
    assert total == 3


def test_roll_is_case_insensitive(monkeypatch):
    monkeypatch.setattr("utils.dice.random.randint", lambda a, b: 2)
    total, _, _ = roll("1D4")
    assert total == 2


# ── roll() — validation / error handling ───────────────────────────────────

@pytest.mark.parametrize("bad_notation", [
    "",
    "not dice",
    "3x6",
    "d",
    "3d",
    "1d20++1",
    "1.5d6",
])
def test_roll_rejects_invalid_notation(bad_notation):
    with pytest.raises(ValueError):
        roll(bad_notation)


def test_roll_rejects_too_many_dice():
    with pytest.raises(ValueError):
        roll("101d6")


def test_roll_rejects_zero_dice():
    with pytest.raises(ValueError):
        roll("0d6")


def test_roll_rejects_die_with_too_few_sides():
    with pytest.raises(ValueError):
        roll("1d1")


def test_roll_rejects_die_with_too_many_sides():
    with pytest.raises(ValueError):
        roll("1d1001")


def test_roll_accepts_boundary_values(monkeypatch):
    # 100 dice, d1000 sides — should NOT raise, since bounds are inclusive
    monkeypatch.setattr("utils.dice.random.randint", lambda a, b: 1)
    total, rolls, _ = roll("100d1000")
    assert len(rolls) == 100


# ── roll_ability_scores() ──────────────────────────────────────────────────

def test_roll_ability_scores_covers_all_six_stats(monkeypatch):
    monkeypatch.setattr("utils.dice.random.randint", lambda a, b: 3)

    scores = roll_ability_scores()

    assert set(scores.keys()) == {"STR", "DEX", "CON", "INT", "WIS", "CHA"}
    for stat, data in scores.items():
        assert data["value"] == 9  # 3d6 of all 3s
        assert data["rolls"] == [3, 3, 3]


# ── bx_modifier() — B/X ability modifier table ─────────────────────────────

@pytest.mark.parametrize("score,expected", [
    (3, -3),
    (4, -2),
    (5, -2),
    (6, -1),
    (8, -1),
    (9, 0),
    (12, 0),
    (13, 1),
    (15, 1),
    (16, 2),
    (17, 2),
    (18, 3),
])
def test_bx_modifier_table(score, expected):
    assert bx_modifier(score) == expected


def test_bx_modifier_out_of_range_defaults_to_zero():
    # Scores below 3 or above 18 aren't valid B/X scores, but the function
    # should fail safe rather than raise or crash the GM loop.
    assert bx_modifier(0) == 0
    assert bx_modifier(25) == 0


# ── format_modifier() ───────────────────────────────────────────────────────

@pytest.mark.parametrize("mod,expected", [
    (3, "+3"),
    (0, "+0"),
    (-2, "-2"),
])
def test_format_modifier(mod, expected):
    assert format_modifier(mod) == expected