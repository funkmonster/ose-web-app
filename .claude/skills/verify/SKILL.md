---
name: verify
description: Build, launch, and drive ose-app to verify changes end-to-end against a scratch DB.
---

# Verifying ose-app changes

## Build & launch

1. Frontend must be rebuilt for backend-served UI changes: `cd frontend && npm run build`
   (outputs to `backend/static`).
2. Python: both `.venv` (repo root) and `backend/venv` are Python 3.14 with all
   requirements — either works. The codebase needs 3.10+ (`dict | None` syntax).
   Tests: `cd backend && ../.venv/bin/python -m pytest`.
3. Never run the server against `data/campaign.db` (real save data). Seed a scratch DB:
   `backend/venv/bin/python backend/scripts/seed_test_data.py data/playtest.db`
4. Launch via `.claude/launch.json` (`preview_start` name `playtest`). Gotcha: a bare
   local run needs `STATIC_DIR=backend/static` — `Config.BASE_DIR` is the repo root,
   so the default `STATIC_DIR` points at a nonexistent `<root>/static` (only Docker
   maps it correctly).

## Drive

- Log in with a passphrase from `users.yaml` (GM role: `Funk`). Passphrase is kept in
  localStorage, shared across Browser-pane tabs — two tabs = same user.
- A user needs a character before reaching the table; seeded characters use
  `seed-player-*` ids that match no users.yaml name, so every login starts at
  character creation. Roll + join to reach the table.
- Party panel / GM Tools hide below 980px viewport width — resize to ≥1400 first.
- Gotcha: two tabs logged in as the same user thrash each other's websocket
  (`ws_manager.py` keeps one connection per user; each reconnect kills the other).
  Only one of them receives broadcasts. Use distinct users to test broadcast fan-out.
- Gotcha: synthesized pointer clicks sometimes fail to trigger React handlers here
  (likely racing the presence re-renders). If a click visibly lands but nothing
  happens, fall back to `javascript_tool` with `element.click()` — same native-event
  path through React. For controlled inputs, set value via the native setter +
  `dispatchEvent(new Event('input', {bubbles: true}))`.
