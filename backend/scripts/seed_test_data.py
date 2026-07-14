"""
Seed a scratch SQLite database with fixture data for playtesting/development.

Creates an isolated DB file with a fake campaign, a few characters, and some
session-log rows so API endpoints can be exercised without an LLM key or any
real campaign data. Talks to the Database layer directly — no LLM involved.

Usage:
    python backend/scripts/seed_test_data.py [path/to/scratch.db]

Path resolution: CLI arg > DB_PATH env var > data/playtest.db.
Refuses to run against the real save file (data/campaign.db).
"""

import asyncio
import os
import sys
from pathlib import Path

# Make backend/ importable when run as `python backend/scripts/seed_test_data.py`
# (same trick as tests/conftest.py).
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import Config
from engine import GUILD, CHANNEL
from utils.database import Database

REAL_DB = (Config.BASE_DIR / "data" / "campaign.db").resolve()

CHARACTERS = [
    ("seed-player-1", {
        "name": "Thoradin", "class": "Fighter", "race": "Human",
        "level": 1, "xp": 0, "hp_max": 8, "hp_current": 8,
        "str": 16, "dex": 12, "con": 14, "int": 9, "wis": 10, "cha": 8,
        "ac": 5, "gold": 30.0,
        "inventory": ["Chain mail", "Shield", "Sword", "Torches (6)"],
        "spells": [],
    }),
    ("seed-player-2", {
        "name": "Zelara", "class": "Magic-User", "race": "Human",
        "level": 1, "xp": 0, "hp_max": 3, "hp_current": 3,
        "str": 8, "dex": 13, "con": 10, "int": 17, "wis": 11, "cha": 12,
        "ac": 9, "gold": 45.0,
        "inventory": ["Dagger", "Spellbook", "Lantern"],
        "spells": ["Sleep"],
    }),
    ("seed-player-3", {
        "name": "Pip Underbough", "class": "Thief", "race": "Halfling",
        "level": 1, "xp": 0, "hp_max": 4, "hp_current": 4,
        "str": 9, "dex": 16, "con": 12, "int": 10, "wis": 9, "cha": 13,
        "ac": 7, "gold": 25.0,
        "inventory": ["Leather armor", "Sling", "Thieves' tools", "Rope (50')"],
        "spells": [],
    }),
]

LOG_ROWS = [
    ("user", "seed-player-1", "Thoradin",
     "[Thoradin, Fighter Lvl 1, HP 8/8]: I push open the citadel's outer gate."),
    ("assistant", None, None,
     "The gate groans inward on rusted hinges. Beyond, a ravine swallows the "
     "ruined citadel — worn steps descend into shadow. The air smells of cold "
     "stone and something faintly sweet. What do you do?"),
    ("user", "seed-player-2", "Zelara",
     "[Zelara, Magic-User Lvl 1, HP 3/3]: I light the lantern and study the steps for tracks."),
    ("assistant", None, None,
     "Lantern light spills over the stairs. Small clawed footprints — kobolds, "
     "likely — cross the dust in both directions. A frayed rope is tied off at "
     "the top step, dangling into the dark."),
    ("user", "seed-player-3", "Pip Underbough",
     "[Pip Underbough, Thief Lvl 1, HP 4/4]: I check the rope for traps before anyone touches it."),
    ("assistant", None, None,
     "The rope is sound, if weathered. No wires, no hidden blades — just honest "
     "hemp, anchored to an iron ring. It would bear a climber's weight. The "
     "descent awaits."),
]


async def seed(target: Path):
    # Deterministic re-runs: start from a clean slate (plus WAL/SHM sidecars).
    for suffix in ("", "-wal", "-shm"):
        sidecar = Path(str(target) + suffix)
        if sidecar.exists():
            sidecar.unlink()

    db = Database(str(target))
    await db.init()

    campaign = await db.get_or_create_campaign(GUILD, CHANNEL, "The Sunless Citadel")
    await db.update_campaign(campaign["id"], module="B/X conversion — The Sunless Citadel")

    for user_id, data in CHARACTERS:
        await db.create_character(campaign["id"], user_id, data)

    for role, author_id, author_name, content in LOG_ROWS:
        await db.log_message(campaign["id"], role, content,
                             author_id=author_id, author_name=author_name)

    await db.set_world_state(campaign["id"], "current_location",
                             "The Sunless Citadel — Ravine Entrance")

    return campaign


def main():
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
    else:
        target = Path(os.getenv("DB_PATH", str(Config.BASE_DIR / "data" / "playtest.db")))

    resolved = target.resolve()
    if resolved == REAL_DB or target.name == "campaign.db":
        print(f"Refusing to seed {target} — that's the real campaign database.\n"
              f"Pass an explicit scratch path, e.g.:\n"
              f"  python backend/scripts/seed_test_data.py data/playtest.db",
              file=sys.stderr)
        sys.exit(1)

    campaign = asyncio.run(seed(resolved))

    print(f"Seeded {resolved}")
    print(f"  Campaign: '{campaign['name']}' (id {campaign['id']})")
    print(f"  Characters:")
    for user_id, data in CHARACTERS:
        print(f"    {data['name']} ({data['class']}) — user id: {user_id}")
    print(f"  Session log: {len(LOG_ROWS)} rows, world state: 1 key")
    print()
    print("Note: character user ids won't match names in users.yaml — /api/party and")
    print("/api/feed work as-is; to play as one, add a matching user to users.yaml.")
    print()
    print(f"Run the backend against it with:")
    print(f"  DB_PATH={resolved} uvicorn main:app --reload   (from backend/)")
    print(f"or, if you used the default path:  make playtest")


if __name__ == "__main__":
    main()
