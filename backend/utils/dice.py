"""
Dice roller for B/X OSE.
Supports standard notation: 3d6, 1d20+2, 2d6-1, d6, etc.
"""

import random
import re

DICE_RE = re.compile(r"^(\d*)d(\d+)([+-]\d+)?$", re.IGNORECASE)


def roll(notation: str) -> tuple[int, list[int], str]:
    """
    Roll dice in XdY+Z notation.
    Returns (total, individual_rolls, description_string).
    """
    notation = notation.strip().lower()
    m = DICE_RE.match(notation)
    if not m:
        raise ValueError(f"Invalid dice notation: {notation!r}")

    num = int(m.group(1)) if m.group(1) else 1
    sides = int(m.group(2))
    modifier = int(m.group(3)) if m.group(3) else 0

    if num < 1 or num > 100:
        raise ValueError("Number of dice must be 1–100.")
    if sides < 2 or sides > 1000:
        raise ValueError("Die sides must be 2–1000.")

    rolls = [random.randint(1, sides) for _ in range(num)]
    total = sum(rolls) + modifier

    parts = [f"[{', '.join(str(r) for r in rolls)}]"]
    if modifier != 0:
        sign = "+" if modifier > 0 else ""
        parts.append(f"{sign}{modifier}")
    desc = f"{notation.upper()}: {' '.join(parts)} = **{total}**"

    return total, rolls, desc


def roll_ability_scores() -> dict:
    """Roll 3d6 for each ability score (classic B/X method)."""
    stats = {}
    for stat in ("STR", "DEX", "CON", "INT", "WIS", "CHA"):
        total, rolls, _ = roll("3d6")
        stats[stat] = {"value": total, "rolls": rolls}
    return stats


def bx_modifier(score: int) -> int:
    """Return the B/X ability modifier for a given score."""
    table = {
        (3, 3): -3,
        (4, 5): -2,
        (6, 8): -1,
        (9, 12): 0,
        (13, 15): 1,
        (16, 17): 2,
        (18, 18): 3,
    }
    for (low, high), mod in table.items():
        if low <= score <= high:
            return mod
    return 0


def format_modifier(mod: int) -> str:
    return f"+{mod}" if mod >= 0 else str(mod)
