"""
SQLite persistence layer for OSE Bot.

Tables:
  campaigns    — one row per campaign (guild-scoped)
  characters   — one row per PC, linked to campaign + discord user
  session_log  — full narrative history (GM + player messages)
  world_state  — key/value store for campaign facts (location, NPCs, quests)
"""

import aiosqlite
import json
from pathlib import Path
from datetime import datetime


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.executescript("""
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS campaigns (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    TEXT NOT NULL,
                    channel_id  TEXT NOT NULL,
                    name        TEXT NOT NULL DEFAULT 'The Campaign',
                    module      TEXT,
                    active      INTEGER NOT NULL DEFAULT 1,
                    created_at  TEXT NOT NULL,
                    UNIQUE(guild_id, channel_id)
                );

                CREATE TABLE IF NOT EXISTS characters (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id     INTEGER NOT NULL REFERENCES campaigns(id),
                    discord_user_id TEXT NOT NULL,
                    name            TEXT NOT NULL,
                    class           TEXT NOT NULL,
                    race            TEXT NOT NULL DEFAULT 'Human',
                    level           INTEGER NOT NULL DEFAULT 1,
                    xp              INTEGER NOT NULL DEFAULT 0,
                    hp_max          INTEGER NOT NULL,
                    hp_current      INTEGER NOT NULL,
                    str             INTEGER NOT NULL,
                    dex             INTEGER NOT NULL,
                    con             INTEGER NOT NULL,
                    int             INTEGER NOT NULL,
                    wis             INTEGER NOT NULL,
                    cha             INTEGER NOT NULL,
                    ac              INTEGER NOT NULL DEFAULT 9,
                    gold            REAL NOT NULL DEFAULT 0,
                    inventory       TEXT NOT NULL DEFAULT '[]',
                    weapons_armor   TEXT NOT NULL DEFAULT '[]',
                    spells          TEXT NOT NULL DEFAULT '[]',
                    notes           TEXT NOT NULL DEFAULT '',
                    alive           INTEGER NOT NULL DEFAULT 1,
                    created_at      TEXT NOT NULL,
                    UNIQUE(campaign_id, discord_user_id)
                );

                CREATE TABLE IF NOT EXISTS session_log (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id  INTEGER NOT NULL REFERENCES campaigns(id),
                    role         TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                    author_id    TEXT,
                    author_name  TEXT,
                    content      TEXT NOT NULL,
                    timestamp    TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS world_state (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id  INTEGER NOT NULL REFERENCES campaigns(id),
                    key          TEXT NOT NULL,
                    value        TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    UNIQUE(campaign_id, key)
                );
            """)
            # Databases created before weapons_armor existed need the column
            # added — CREATE TABLE IF NOT EXISTS won't touch an existing table.
            async with db.execute("PRAGMA table_info(characters)") as cur:
                columns = {row[1] for row in await cur.fetchall()}
            if "weapons_armor" not in columns:
                await db.execute(
                    "ALTER TABLE characters ADD COLUMN weapons_armor TEXT NOT NULL DEFAULT '[]'"
                )
            await db.commit()

    # ── Campaigns ─────────────────────────────────────────────────────────────

    async def get_or_create_campaign(self, guild_id: str, channel_id: str, name: str = "The Campaign"):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM campaigns WHERE guild_id=? AND channel_id=?",
                (guild_id, channel_id)
            ) as cur:
                row = await cur.fetchone()
            if row:
                return dict(row)
            now = datetime.utcnow().isoformat()
            async with db.execute(
                "INSERT INTO campaigns (guild_id, channel_id, name, created_at) VALUES (?,?,?,?)",
                (guild_id, channel_id, name, now)
            ) as cur:
                campaign_id = cur.lastrowid
            await db.commit()
            return {"id": campaign_id, "guild_id": guild_id, "channel_id": channel_id,
                    "name": name, "active": 1, "created_at": now}

    async def get_campaign(self, guild_id: str, channel_id: str):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM campaigns WHERE guild_id=? AND channel_id=?",
                (guild_id, channel_id)
            ) as cur:
                row = await cur.fetchone()
            return dict(row) if row else None

    async def update_campaign(self, campaign_id: int, **kwargs):
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [campaign_id]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"UPDATE campaigns SET {sets} WHERE id=?", vals)
            await db.commit()

    # ── Characters ───────────────────────────────────────────────────────────

    async def create_character(self, campaign_id: int, discord_user_id: str, data: dict):
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO characters
                  (campaign_id, discord_user_id, name, class, race, level, xp,
                   hp_max, hp_current, str, dex, con, int, wis, cha, ac,
                   gold, inventory, weapons_armor, spells, notes, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                campaign_id, discord_user_id,
                data["name"], data["class"], data.get("race", "Human"),
                data.get("level", 1), data.get("xp", 0),
                data["hp_max"], data["hp_current"],
                data["str"], data["dex"], data["con"],
                data["int"], data["wis"], data["cha"],
                data.get("ac", 9),
                data.get("gold", 0),
                json.dumps(data.get("inventory", [])),
                json.dumps(data.get("weapons_armor", [])),
                json.dumps(data.get("spells", [])),
                data.get("notes", ""),
                now,
            ))
            await db.commit()

    async def get_character(self, campaign_id: int, discord_user_id: str):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM characters WHERE campaign_id=? AND discord_user_id=? AND alive=1",
                (campaign_id, discord_user_id)
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        c = dict(row)
        c["inventory"] = json.loads(c["inventory"])
        c["weapons_armor"] = json.loads(c["weapons_armor"])
        c["spells"] = json.loads(c["spells"])
        return c

    async def get_all_characters(self, campaign_id: int):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM characters WHERE campaign_id=? AND alive=1",
                (campaign_id,)
            ) as cur:
                rows = await cur.fetchall()
        chars = []
        for row in rows:
            c = dict(row)
            c["inventory"] = json.loads(c["inventory"])
            c["weapons_armor"] = json.loads(c["weapons_armor"])
            c["spells"] = json.loads(c["spells"])
            chars.append(c)
        return chars

    async def update_character(self, campaign_id: int, discord_user_id: str, **kwargs):
        if "inventory" in kwargs:
            kwargs["inventory"] = json.dumps(kwargs["inventory"])
        if "weapons_armor" in kwargs:
            kwargs["weapons_armor"] = json.dumps(kwargs["weapons_armor"])
        if "spells" in kwargs:
            kwargs["spells"] = json.dumps(kwargs["spells"])
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [campaign_id, discord_user_id]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                f"UPDATE characters SET {sets} WHERE campaign_id=? AND discord_user_id=?",
                vals
            )
            await db.commit()

    # ── Session Log ──────────────────────────────────────────────────────────

    async def log_message(self, campaign_id: int, role: str, content: str,
                          author_id: str = None, author_name: str = None):
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO session_log (campaign_id, role, author_id, author_name, content, timestamp) VALUES (?,?,?,?,?,?)",
                (campaign_id, role, author_id, author_name, content, now)
            )
            await db.commit()

    async def get_history(self, campaign_id: int, limit: int = 20):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT role, author_name, content FROM session_log
                   WHERE campaign_id=?
                   ORDER BY id DESC LIMIT ?""",
                (campaign_id, limit)
            ) as cur:
                rows = await cur.fetchall()
        return list(reversed([dict(r) for r in rows]))

    # ── World State ──────────────────────────────────────────────────────────

    async def set_world_state(self, campaign_id: int, key: str, value: str):
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO world_state (campaign_id, key, value, updated_at)
                VALUES (?,?,?,?)
                ON CONFLICT(campaign_id, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """, (campaign_id, key, value, now))
            await db.commit()

    async def get_world_state(self, campaign_id: int) -> dict:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT key, value FROM world_state WHERE campaign_id=?",
                (campaign_id,)
            ) as cur:
                rows = await cur.fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ── Reset / Delete ───────────────────────────────────────────────────────

    async def delete_campaign(self, campaign_id: int) -> None:
        """Permanently delete a campaign and every row scoped to it."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM characters WHERE campaign_id=?", (campaign_id,))
            await db.execute("DELETE FROM session_log WHERE campaign_id=?", (campaign_id,))
            await db.execute("DELETE FROM world_state WHERE campaign_id=?", (campaign_id,))
            await db.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
            await db.commit()
