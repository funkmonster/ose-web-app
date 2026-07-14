"""
Parses [STATE_UPDATE]...[/STATE_UPDATE] blocks from GM responses
and applies the changes to the database.
"""

import re
import logging

log = logging.getLogger("ose-bot.state")

STATE_BLOCK_RE = re.compile(
    r"\[STATE_UPDATE\](.*?)\[/STATE_UPDATE\]", re.DOTALL | re.IGNORECASE
)


def strip_state_block(text: str) -> str:
    """Remove the state update block from visible GM output."""
    return STATE_BLOCK_RE.sub("", text).strip()


def parse_state_block(text: str) -> list[dict]:
    """
    Extract state change directives from a GM response.
    Returns a list of action dicts.
    """
    match = STATE_BLOCK_RE.search(text)
    if not match:
        return []

    actions = []
    for raw_line in match.group(1).strip().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(":", 2)
        if len(parts) < 3:
            log.warning(f"Skipping malformed state line: {line!r}")
            continue
        action_type, target, value = parts[0].strip(), parts[1].strip(), parts[2].strip()
        actions.append({"type": action_type, "target": target, "value": value})
    return actions


async def apply_state_changes(db, campaign_id: int, actions: list[dict], characters: list[dict]):
    """
    Apply parsed state changes to the database.
    `characters` is a list of character dicts (from db.get_all_characters).
    """
    # Build name -> discord_user_id map (case-insensitive)
    char_map = {c["name"].lower(): c for c in characters}

    for action in actions:
        t = action["type"].lower()
        target = action["target"]
        value = action["value"]
        char_key = target.lower()

        if t == "hp":
            char = char_map.get(char_key)
            if not char:
                log.warning(f"State update: unknown character {target!r}")
                continue
            delta = int(value)
            new_hp = max(0, char["hp_current"] + delta)
            alive = 1 if new_hp > 0 else 0
            await db.update_character(campaign_id, char["discord_user_id"],
                                      hp_current=new_hp, alive=alive)
            if not alive:
                log.info(f"{char['name']} has died (hp -> 0).")

        elif t == "xp":
            char = char_map.get(char_key)
            if not char:
                continue
            delta = int(value)
            new_xp = max(0, char["xp"] + delta)
            await db.update_character(campaign_id, char["discord_user_id"], xp=new_xp)

        elif t == "gold":
            char = char_map.get(char_key)
            if not char:
                continue
            delta = float(value)
            new_gold = max(0.0, char["gold"] + delta)
            await db.update_character(campaign_id, char["discord_user_id"], gold=new_gold)

        elif t == "item_add":
            char = char_map.get(char_key)
            if not char:
                continue
            inventory = char["inventory"][:]
            inventory.append(value)
            await db.update_character(campaign_id, char["discord_user_id"], inventory=inventory)

        elif t == "item_remove":
            char = char_map.get(char_key)
            if not char:
                continue
            inventory = char["inventory"][:]
            # Remove first match (case-insensitive prefix)
            for i, item in enumerate(inventory):
                if item.lower().startswith(value.lower()):
                    inventory.pop(i)
                    break
            await db.update_character(campaign_id, char["discord_user_id"], inventory=inventory)

        elif t == "world":
            await db.set_world_state(campaign_id, target, value)

        else:
            log.warning(f"Unknown state action type: {t!r}")
