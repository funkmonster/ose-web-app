# The Old School Essentials Table

A self-hosted web app for playing B/X D&D / Old-School Essentials with an LLM Dungeon Master. Built for a party of three. Real-time multiplayer over WebSockets, persistent campaign state in SQLite, and long-term GM memory via rolling summarization.

The GM's narration renders as classic module boxed read-aloud text — cream paper cards against a graph-paper table.

---

## Quick Start (Docker — recommended)

```bash
# 1. Edit users.yaml — set names, passphrases, and who is GM
# 2. Set your LLM key
export ANTHROPIC_API_KEY="sk-ant-..."

# 3. Build and run
docker compose up --build
```

Open http://localhost:8000 and enter a passphrase from `users.yaml`.

## Quick Start (no Docker)

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."
uvicorn main:app --host 0.0.0.0 --port 8000

# Frontend (separate terminal) — builds into backend/static
cd frontend
npm install
npm run build

# Or for frontend development with hot reload:
npm run dev   # then open http://localhost:5173 (proxies to backend on 8000)
```

After `npm run build`, the backend serves the app directly at http://localhost:8000 — one process, one port.

---

## Configuration

### users.yaml
Three users, each with a `name`, `passphrase`, `color` (hex, used in the feed), and `role` (`gm` or `player`). The `gm` role unlocks manual narration and HP adjustment tools. Change the passphrases before you share the URL.

### Environment variables
| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | `anthropic` \| `openai` \| `ollama` |
| `ANTHROPIC_API_KEY` | — | required for Anthropic |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | model override |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | — / `gpt-4o` | OpenAI settings |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | localhost / `llama3` | local model settings |
| `HISTORY_WINDOW` | `20` | recent messages sent to the GM each turn |
| `SUMMARIZE_EVERY` | `10` | player actions between summary updates |
| `DB_PATH` | `data/campaign.db` | SQLite location |

### Migrating from the Discord bot
The schema is identical. Copy the bot's `data/campaign.db` into this app's `data/` directory. One caveat: characters in the bot are keyed by Discord user IDs, while the app keys them by the `name` values in `users.yaml`. To carry over characters, update the `discord_user_id` column to match your app usernames:

```sql
UPDATE characters SET discord_user_id = 'Sean' WHERE discord_user_id = '<your discord id>';
```

Also update the campaign row to the app's fixed scope:

```sql
UPDATE campaigns SET guild_id = 'local', channel_id = 'main';
```

---

## Playing

1. **Log in** with your passphrase. It's remembered in your browser.
2. **Create your character** — roll 3d6 down the line, pick a class, no take-backs. HP is rolled automatically.
3. Anyone can **start a campaign** from the toolbar (name + module).
4. Type what your character does and press **Enter**. Everyone sees your action, the GM's thinking indicator, and the narration in real time.
5. **Dice chips** roll and broadcast instantly — the GM will tell you what to roll.
6. **Recap** asks the GM for a quick summary; **Memory** shows the bot's long-term campaign chronicle; **Long rest** restores the party.

### GM tools (role: gm)
- **Narrate** — inject narration directly, bypassing the LLM (course-correct the story, run a scene by hand)
- **Apply HP change** — manual adjustments when you need to override

---

## Architecture

```
ose-app/
├── users.yaml              # identity: names, passphrases, colors, roles
├── Dockerfile              # multi-stage: builds frontend, runs backend
├── docker-compose.yml
├── backend/
│   ├── main.py             # FastAPI app: REST routes, WebSocket, static serving
│   ├── engine.py           # GM loop — transport-agnostic game logic
│   ├── ws_manager.py       # broadcast layer
│   ├── config.py           # env + users.yaml loading
│   ├── models/schemas.py   # Pydantic request models
│   └── utils/              # carried over from the Discord bot:
│       ├── database.py     #   SQLite layer (same schema)
│       ├── llm.py          #   provider adapter + OSE system prompt
│       ├── summarizer.py   #   rolling long-term memory
│       ├── state_parser.py #   [STATE_UPDATE] block parsing
│       └── dice.py         #   B/X dice + modifiers
└── frontend/
    ├── src/App.jsx          # auth gate, layout, socket wiring
    ├── src/components/      # GameView, PartyPanel, CharacterSheet
    ├── src/pages/           # Login, CharacterCreate
    └── src/hooks/           # useGameSocket (auto-reconnect)
```

**Event flow:** player action → REST `POST /api/play` → broadcast `player_action` + `gm_thinking` to all clients → engine runs the GM loop (summary check, context build, LLM call, state parsing) → broadcast `gm_narration` + `party_update` → all three screens update simultaneously.

A per-server lock serializes GM calls so two simultaneous actions can't interleave narration.

---

## Hosting later

When you're ready to move off localhost:
- **Tailscale** (easiest): run it on any machine you own, share your tailnet with your two friends, done. No ports exposed to the internet.
- **VPS**: `docker compose up -d` behind Caddy or nginx for TLS. The passphrase auth is fine for a private URL but do use HTTPS.
