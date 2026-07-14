# Agent notes for ose-app

See README.md for architecture, setup, and configuration — this file only covers
conventions specific to automated coding agents working in this repo.

## Database safety — read this first

Never point `DB_PATH` at `data/campaign.db` (the default) when running the dev
server, a one-off script, or anything else by hand. That file is real campaign
data. Before running `uvicorn`, `backend/scripts/seed_test_data.py`, or any
manual invocation, set a scratch path first:

    export DB_PATH=data/agent-scratch.db

(`backend/tests/` is exempt — each test already gets its own isolated tmp_path
DB via pytest fixtures; you don't need to set `DB_PATH` to run `pytest`.)

## Exercising the API without an LLM key

    python backend/scripts/seed_test_data.py data/agent-scratch.db

populates a scratch DB with a fake campaign, three characters, and sample
session-log rows — enough to hit `/api/party`, `/api/feed`, `/api/gm/*`, etc.
without an `ANTHROPIC_API_KEY`. Then start the backend against that same file:

    cd backend && DB_PATH=../data/agent-scratch.db uvicorn main:app --reload

(`make seed` + `make playtest` do the same against `data/playtest.db`.)

## Running tests

    cd backend && pytest
