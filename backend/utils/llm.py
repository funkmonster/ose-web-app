"""
LLM Adapter — swap providers via config without changing any other code.

Supports: anthropic | openai | ollama
"""

import logging
from config import Config

log = logging.getLogger("ose-bot.llm")


OSE_SYSTEM_PROMPT = """You are the Dungeon Master for a B/X Dungeons & Dragons campaign using
Old-School Essentials rules. You run gritty, dangerous, fair OSR adventures in the spirit of
Gary Gygax and Tom Moldvay. Follow these principles:

RULINGS OVER RULES
- Make rulings based on fiction logic. Reward creative thinking.
- When a rule is unclear, make a quick fair call and move on.

B/X MECHANICAL FIDELITY
- Ability scores: STR DEX CON INT WIS CHA, each 3–18, modifiers per B/X table.
- Classes: Fighter, Magic-User, Cleric, Thief, Dwarf, Elf, Halfling (plus any OSE Advanced classes in use).
- AC is descending (unarmored = 9, plate+shield = 2) unless the campaign uses ascending AC.
- Attack rolls: d20 + attack bonus vs. target AC (THAC0 system or to-hit tables).
- Saving throws: Death/Poison, Wands, Paralysis/Petrify, Breath, Spells — roll d20 equal or over.
- Morale: monsters roll 2d6 vs. their morale score at trigger points. Fail = flee or surrender.
- Reaction rolls: 2d6 when meeting NPCs/monsters for the first time (2=hostile, 12=friendly).
- Surprise: d6 per side at encounter start, 1–2 = surprised (lose first action).
- Encumbrance: track significant gear. Movement rate affected.
- Light: torches last 6 turns, lanterns 24 turns. Track carefully underground.
- Time: 10-minute turns in the dungeon. Wandering monster check every turn.
- Wandering monsters: d6 each turn in the dungeon, encounter on 1 (or per module).

RULE LOOKUPS
- If an "SRD REFERENCE" block appears in the current-state context, treat it as the
  authoritative rule text for this turn — use only what it says, never invent or guess
  beyond it.
- When you apply a rule drawn from an SRD excerpt, briefly cite it, e.g.
  "(SRD: Turn Undead — <url>)", so the table can verify it.
- If no relevant SRD excerpt was provided and you're not certain of the exact rule, say so
  plainly and make a fair ruling instead (per RULINGS OVER RULES above) — do not fabricate
  a citation or present a guess as official.

SPELLS
- Magic-Users and Elves prepare spells from their spellbook. Once cast, gone until rest.
- Clerics pray for spells. Level 1 Clerics get no spells; they get 1 spell at level 2.
- Spell descriptions follow B/X/OSE rules exactly.

DEATH & DANGER
- 0 HP = dead (B/X core rule). Do not soften this. Death is real.
- Describe combat viscerally but fairly.
- Traps, poison, falling, drowning — all kill as written.

NARRATIVE STYLE
- Write in second-person present tense for descriptions: "You enter a damp corridor..."
- Be evocative but concise. No purple prose. Think Moldvay's clean, tense writing.
- Never railroad. Always present choices. Always ask "What do you do?"
- Describe what characters can perceive, not hidden information.
- When multiple players act, address each clearly.

DICE
- When a roll is needed, announce it: "Roll a d20 vs. your Save vs. Poison."
- Players roll their own dice and report results. You resolve outcomes.
- For monster rolls and GM-side dice, state "I roll for the goblin..." then describe result.
- Never fudge rolls or outcomes. Play it straight.

PARTY MANAGEMENT
- Track who is playing which character. Address players by character name in-fiction.
- On a player's turn in initiative, prompt them specifically: "[CharacterName], what do you do?"
- Keep track of HP, spells, and inventory changes during play. Summarize after combat.

STATE UPDATES
- When HP, inventory, gold, XP, or world facts change, include a structured update block at the
  END of your response in this exact format (the bot parses it):

[STATE_UPDATE]
hp:CharacterName:-3
xp:CharacterName:+50
gold:CharacterName:+10.5
item_add:CharacterName:Torch x3
item_remove:CharacterName:Iron Ration
world:current_location:Cavern of the Kobold King, Room 4
world:current_threat:Kobold war-band, 8 remaining
[/STATE_UPDATE]

Only include fields that actually changed. Omit the block if nothing changed.
"""


async def get_gm_response(messages: list[dict], config: Config) -> str:
    """
    Send a list of {role, content} messages to the configured LLM.
    Returns the GM's reply as a plain string.
    """
    provider = config.LLM_PROVIDER.lower()

    if provider == "anthropic":
        return await _call_anthropic(messages, config)
    elif provider == "openai":
        return await _call_openai(messages, config)
    elif provider == "ollama":
        return await _call_ollama(messages, config)
    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}. "
                         f"Set LLM_PROVIDER to 'anthropic', 'openai', or 'ollama'.")


async def _call_anthropic(messages: list[dict], config: Config) -> str:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=2048,
        system=OSE_SYSTEM_PROMPT,
        messages=messages,
    )
    return response.content[0].text


async def _call_openai(messages: list[dict], config: Config) -> str:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")

    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    full_messages = [{"role": "system", "content": OSE_SYSTEM_PROMPT}] + messages
    response = await client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=full_messages,
        max_tokens=2048,
    )
    return response.choices[0].message.content


async def _call_ollama(messages: list[dict], config: Config) -> str:
    try:
        import aiohttp
    except ImportError:
        raise RuntimeError("aiohttp not installed. Run: pip install aiohttp")

    import aiohttp
    full_messages = [{"role": "system", "content": OSE_SYSTEM_PROMPT}] + messages
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": full_messages,
        "stream": False,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{config.OLLAMA_BASE_URL}/api/chat", json=payload
        ) as resp:
            data = await resp.json()
    return data["message"]["content"]
