# The Old School Essentials Table

A self-hosted web app for playing B/X D&D / Old-School Essentials with an LLM Dungeon Master. Built for a party of three. Real-time multiplayer over WebSockets, persistent campaign state in SQLite, and long-term GM memory via rolling summarization.

The GM's narration renders as classic module boxed read-aloud text — cream paper cards against a graph-paper table.

---

## Quick Start (Docker — recommended)

```bash
# 1. Copy users.yaml.example to users.yaml — set names, passphrases, and who is GM
cp users.yaml.example users.yaml

# 2. Set your LLM key
export ANTHROPIC_API_KEY="sk-ant-..."

# 3. Build and run
docker compose up --build
```

Open http://localhost:8000 and enter a passphrase from `users.yaml`.

## Quick Start (no Docker)

```bash
# Users — copy the template and edit names/passphrases/roles
cp users.yaml.example users.yaml

# Frontend — build this first; the backend serves it from backend/static
cd frontend
npm install && npm run build
cd ..

# Backend — from the repo root; needs Python 3.10+
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."
cd backend && STATIC_DIR=static uvicorn main:app --host 0.0.0.0 --port 8000

# Or for frontend development with hot reload:
cd frontend && npm run dev   # then open http://localhost:5173 (proxies to backend on 8000)
```

After `npm run build`, the backend serves the app directly at http://localhost:8000 — one process, one port.

## Playtest / scratch database

Which database a session uses is decided when the **server** starts, via the
`DB_PATH` environment variable — there's no in-app switch. Start the backend the
normal way (Docker, or the Quick Start `uvicorn` line) and you're playing the real
campaign in `data/campaign.db`; start it with `make playtest` and you're on the
throwaway `data/playtest.db`. To switch, stop the server and start it the other way.

Never point a manual test run at `data/campaign.db` — that's your real save file.
Instead, run the backend against the throwaway file:

```bash
make playtest   # assumes your venv is active, same as Quick Start
```

This starts the backend with `DB_PATH=data/playtest.db` (auto-reloading), completely
isolated from `data/campaign.db`. Delete `data/playtest.db*` any time to start fresh
(it's gitignored and safe to churn).

To populate it with a fake campaign, characters, and session log so you can hit API
endpoints (`/api/party`, `/api/feed`, `/api/gm/*`, etc.) without an LLM key:

```bash
make seed
```

---

## Configuration

### users.yaml
Copy `users.yaml.example` to `users.yaml` (gitignored — it holds your table's real passphrases). Three users, each with a `name`, `passphrase`, `color` (hex, used in the feed), and `role` (`gm` or `player`). The `gm` role unlocks manual narration and HP adjustment tools. Change the passphrases before you share the URL.

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
| `DB_PATH` | `data/campaign.db` | SQLite location — point at a scratch file for playtesting, see "Playtest / scratch database" above |

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
- **Reset Campaign** — permanently deletes the campaign, all characters, and the session log (type-to-confirm; there is no undo)

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
│   └── utils/              
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
