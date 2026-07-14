"""
Game engine — the GM loop, decoupled from any transport.

This is the brains extracted from the Discord bot's adventure cog.
Routers call these functions; results are broadcast via the WebSocket manager.
"""

import logging
from datetime import datetime

from config import Config
from utils.llm import get_gm_response
from utils.state_parser import parse_state_block, strip_state_block, apply_state_changes
from utils.summarizer import maybe_update_summary, SUMMARY_KEY
from utils.dice import roll as roll_dice, bx_modifier, roll_ability_scores
from utils.srd_lookup import SrdIndex, format_srd_context

log = logging.getLogger("ose-app.engine")

# The single campaign scope for a self-hosted app.
# We reuse the guild/channel columns with fixed values.
GUILD = "local"
CHANNEL = "main"

PHYSICAL_DICE_KEY = "physical_dice_mode"


class GameEngine:
    def __init__(self, db, config: Config, srd_index: SrdIndex | None = None):
        self.db = db
        self.config = config
        self.srd_index = srd_index

    # ── Campaign ─────────────────────────────────────────────────────────────

    async def get_campaign(self):
        campaign = await self.db.get_campaign(GUILD, CHANNEL)
        if not campaign:
            return None
        world = await self.db.get_world_state(campaign["id"])
        campaign["physical_dice_mode"] = world.get(PHYSICAL_DICE_KEY, "false") == "true"
        return campaign

    async def start_campaign(self, name: str, module: str) -> dict:
        campaign = await self.db.get_or_create_campaign(GUILD, CHANNEL, name)
        await self.db.update_campaign(campaign["id"], name=name, module=module)

        opening_prompt = (
            f"Begin the campaign '{name}', set in {module}. "
            f"Deliver a vivid opening narration that sets the scene and establishes the tone. "
            f"End by describing the party's immediate situation and asking what they do. "
            f"Do not reference any specific character names yet — the players will introduce themselves."
        )
        await self.db.log_message(campaign["id"], "user", opening_prompt,
                                  author_id="SYSTEM", author_name="System")

        history = await self.db.get_history(campaign["id"], limit=self.config.HISTORY_WINDOW)
        messages = build_messages(history)

        gm_reply = await get_gm_response(messages, self.config)
        clean = strip_state_block(gm_reply)
        await self.db.log_message(campaign["id"], "assistant", gm_reply)

        return {"campaign": {"name": name, "module": module}, "narration": clean}

    # ── Player action ────────────────────────────────────────────────────────

    async def play(self, user_name: str, action: str) -> dict:
        """
        Process a player action through the GM.
        Returns {narration, state_actions, character} or raises ValueError.
        """
        campaign = await self.get_campaign()
        if not campaign:
            raise ValueError("No campaign has been started yet.")

        char = await self.db.get_character(campaign["id"], user_name)
        if not char:
            raise ValueError("You don't have a character yet.")
        if not char["alive"]:
            raise ValueError(f"{char['name']} is dead. Create a new character.")

        player_msg = (
            f"[{char['name']}, {char['class']} Lvl {char['level']}, "
            f"HP {char['hp_current']}/{char['hp_max']}]: {action}"
        )
        await self.db.log_message(campaign["id"], "user", player_msg,
                                  author_id=user_name, author_name=user_name)

        # Rolling summary check
        await maybe_update_summary(self.db, campaign["id"], self.config)

        world = await self.db.get_world_state(campaign["id"])
        all_chars = await self.db.get_all_characters(campaign["id"])
        history = await self.db.get_history(campaign["id"], limit=self.config.HISTORY_WINDOW)

        srd_sections = self.srd_index.search(action) if self.srd_index else []
        context_prefix = build_context_prefix(world, all_chars, srd_sections=srd_sections)
        messages = build_messages(history, context_prefix)

        gm_reply = await get_gm_response(messages, self.config)

        state_actions = parse_state_block(gm_reply)
        if state_actions:
            await apply_state_changes(self.db, campaign["id"], state_actions, all_chars)

        clean = strip_state_block(gm_reply)
        await self.db.log_message(campaign["id"], "assistant", gm_reply)

        refreshed_char = await self.db.get_character(campaign["id"], user_name)

        return {
            "narration": clean,
            "state_actions": state_actions,
            "character": refreshed_char,
        }

    # ── Recap / Summary ──────────────────────────────────────────────────────

    async def recap(self) -> str:
        campaign = await self.get_campaign()
        if not campaign:
            raise ValueError("No campaign started.")

        history = await self.db.get_history(campaign["id"], limit=self.config.HISTORY_WINDOW)
        world = await self.db.get_world_state(campaign["id"])
        all_chars = await self.db.get_all_characters(campaign["id"])

        context_prefix = build_context_prefix(world, all_chars)
        messages = build_messages(history, context_prefix)
        messages.append({
            "role": "user",
            "content": ("Please give a brief recap of what has happened in the campaign so far — "
                        "where we are, what we've done, and any notable facts. Keep it to 3–5 sentences.")
        })
        reply = await get_gm_response(messages, self.config)
        return strip_state_block(reply)

    async def get_summary(self) -> dict:
        campaign = await self.get_campaign()
        if not campaign:
            raise ValueError("No campaign started.")
        world = await self.db.get_world_state(campaign["id"])
        return {
            "summary": world.get(SUMMARY_KEY, ""),
            "action_count": int(world.get("player_action_count", "0")),
            "summarize_every": self.config.SUMMARIZE_EVERY,
        }

    # ── Rest ─────────────────────────────────────────────────────────────────

    async def rest(self, rest_type: str) -> dict:
        campaign = await self.get_campaign()
        if not campaign:
            raise ValueError("No campaign started.")

        all_chars = await self.db.get_all_characters(campaign["id"])
        results = []

        if rest_type == "long":
            for c in all_chars:
                await self.db.update_character(campaign["id"], c["discord_user_id"],
                                               hp_current=c["hp_max"])
                results.append({"name": c["name"], "hp": c["hp_max"], "hp_max": c["hp_max"]})
            await self.db.log_message(
                campaign["id"], "system",
                "The party takes a long rest. All HP restored, spells recovered."
            )
        else:
            for c in all_chars:
                results.append({"name": c["name"], "hp": c["hp_current"], "hp_max": c["hp_max"]})

        return {"rest_type": rest_type, "party": results}

    # ── GM tools ─────────────────────────────────────────────────────────────

    async def gm_say(self, message: str):
        campaign = await self.get_campaign()
        if not campaign:
            raise ValueError("No campaign started.")
        await self.db.log_message(campaign["id"], "assistant", message,
                                  author_id="GM", author_name="GM")

    async def update_hp(self, target_user: str, delta: int) -> dict:
        campaign = await self.get_campaign()
        if not campaign:
            raise ValueError("No campaign started.")
        char = await self.db.get_character(campaign["id"], target_user)
        if not char:
            raise ValueError(f"{target_user} has no character.")
        new_hp = max(0, char["hp_current"] + delta)
        alive = 1 if new_hp > 0 else 0
        await self.db.update_character(campaign["id"], target_user,
                                       hp_current=new_hp, alive=alive)
        return {"name": char["name"], "hp": new_hp, "hp_max": char["hp_max"], "alive": bool(alive)}

    async def set_physical_dice_mode(self, enabled: bool) -> bool:
        campaign = await self.get_campaign()
        if not campaign:
            raise ValueError("No campaign started.")
        await self.db.set_world_state(campaign["id"], PHYSICAL_DICE_KEY,
                                      "true" if enabled else "false")
        return enabled

    async def reset_campaign(self) -> dict:
        """Hard-delete the current campaign and everything scoped to it."""
        campaign = await self.get_campaign()
        if not campaign:
            raise ValueError("No campaign to reset.")
        name = campaign["name"]
        await self.db.delete_campaign(campaign["id"])
        return {"name": name}

    # ── Characters ───────────────────────────────────────────────────────────

    async def get_character(self, user_name: str):
        campaign = await self.get_campaign()
        if not campaign:
            return None
        return await self.db.get_character(campaign["id"], user_name)

    async def get_party(self):
        campaign = await self.get_campaign()
        if not campaign:
            return []
        return await self.db.get_all_characters(campaign["id"])

    async def create_character(self, user_name: str, data: dict) -> dict:
        campaign = await self.db.get_or_create_campaign(GUILD, CHANNEL)

        existing = await self.db.get_character(campaign["id"], user_name)
        if existing:
            raise ValueError(f"You already have a character: {existing['name']}")

        from utils.dice import roll as _roll
        CLASS_HIT_DIE = {
            "Fighter": 8, "Cleric": 6, "Thief": 4,
            "Magic-User": 4, "Dwarf": 8, "Elf": 6, "Halfling": 6,
        }
        char_class = data["char_class"].strip().title()
        if char_class not in CLASS_HIT_DIE:
            raise ValueError(f"Unknown class: {char_class}. "
                             f"Valid: {', '.join(CLASS_HIT_DIE.keys())}")

        hd = CLASS_HIT_DIE[char_class]
        if data.get("hp_max"):
            hp_max = data["hp_max"]
        else:
            con_mod = bx_modifier(data["con_score"])
            hp_roll, _, _ = _roll(f"1d{hd}")
            hp_max = max(1, hp_roll + con_mod)

        race = data.get("race") or (
            char_class if char_class in ("Dwarf", "Elf", "Halfling") else "Human"
        )

        await self.db.create_character(campaign["id"], user_name, {
            "name": data["name"], "class": char_class, "race": race,
            "level": 1, "xp": 0,
            "hp_max": hp_max, "hp_current": hp_max,
            "str": data["str_score"], "dex": data["dex_score"], "con": data["con_score"],
            "int": data["int_score"], "wis": data["wis_score"], "cha": data["cha_score"],
            "ac": data.get("ac", 9), "gold": data.get("gold", 0.0),
            "inventory": data.get("inventory", []), "spells": data.get("spells", []),
        })
        return await self.db.get_character(campaign["id"], user_name)

    async def update_inventory(self, user_name: str, inventory: list[str]):
        campaign = await self.get_campaign()
        if not campaign:
            raise ValueError("No campaign started.")
        await self.db.update_character(campaign["id"], user_name, inventory=inventory)

    async def update_spells(self, user_name: str, spells: list[str]):
        campaign = await self.get_campaign()
        if not campaign:
            raise ValueError("No campaign started.")
        await self.db.update_character(campaign["id"], user_name, spells=spells)

    # ── History ──────────────────────────────────────────────────────────────

    async def get_feed(self, limit: int = 100):
        """Return recent narrative history for the GM feed, cleaned for display."""
        campaign = await self.get_campaign()
        if not campaign:
            return []
        history = await self.db.get_history(campaign["id"], limit=limit)
        feed = []
        for row in history:
            content = row["content"]
            if row["role"] == "assistant":
                content = strip_state_block(content)
            # Skip the internal opening prompt
            if row.get("author_name") == "System":
                continue
            feed.append({
                "role": row["role"],
                "author": row.get("author_name"),
                "content": content,
            })
        return feed


# ── Prompt-building helpers (shared with old bot logic) ───────────────────────

def build_messages(history: list[dict], context_prefix: str = "") -> list[dict]:
    messages = []
    if context_prefix:
        messages.append({"role": "user", "content": context_prefix})
        messages.append({"role": "assistant",
                         "content": "Understood. I have the current party and world state."})
    for row in history:
        role = row["role"] if row["role"] in ("user", "assistant") else "user"
        author = row.get("author_name")
        content = row["content"]
        if author and role == "user":
            content = f"[{author}]: {content}"
        messages.append({"role": role, "content": content})
    return messages


def build_context_prefix(world: dict, chars: list[dict], srd_sections: list | None = None) -> str:
    lines = ["[CURRENT STATE — for GM reference only, do not read aloud]"]

    summary = world.get(SUMMARY_KEY, "").strip()
    if summary:
        lines.append("\nCAMPAIGN SUMMARY (everything that has happened so far):")
        lines.append(summary)

    if world.get(PHYSICAL_DICE_KEY) == "true":
        lines.append(
            "\nPHYSICAL DICE MODE IS ON: the party is rolling real dice at the table. "
            "Announce what to roll but do not roll dice yourself or state a result — "
            "wait for the player to report what they rolled."
        )

    _internal = {SUMMARY_KEY, "player_action_count", PHYSICAL_DICE_KEY}
    world_facts = {k: v for k, v in world.items() if k not in _internal}
    if world_facts:
        lines.append("\nCurrent World State:")
        for k, v in world_facts.items():
            lines.append(f"  {k}: {v}")

    if chars:
        lines.append("\nParty:")
        for c in chars:
            lines.append(
                f"  {c['name']} ({c['class']} Lvl {c['level']}) — "
                f"HP {c['hp_current']}/{c['hp_max']}, AC {c['ac']}, Gold {c['gold']} gp"
            )
            if c["inventory"]:
                lines.append(f"    Inventory: {', '.join(c['inventory'])}")
            if c["spells"]:
                lines.append(f"    Spells: {', '.join(c['spells'])}")

    if srd_sections:
        lines.append("\n" + format_srd_context(srd_sections))

    return "\n".join(lines)
