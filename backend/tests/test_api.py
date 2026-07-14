"""
Tests for main.py — the FastAPI route layer.

These exercise the app through FastAPI's TestClient (real ASGI request/
response cycle, real SQLite via a fresh temp file per test) so that auth
wiring, status-code mapping, and dependency injection between routes and
the engine are verified end-to-end. The one external dependency — the LLM
call — is mocked via `mock_gm` so no network call is made.

`main.py` builds its `config`/`db`/`engine`/`app` as module-level globals at
import time, and `app.mount(...)` requires STATIC_DIR to already contain an
`assets/` directory. So Config's file-based settings are pointed at a temp
fixture *before* `main` is imported (module-scoped, imported once for this
file), and each test gets DB isolation by swapping `db.path` to a fresh
temp file and re-running the app's lifespan (which calls `db.init()`).
"""

import importlib
import sys
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi.testclient import TestClient

import engine as engine_module
from config import Config

GM_PASSPHRASE = "gm-secret-phrase"
PLAYER_PASSPHRASE = "player-secret-phrase"
GM_NAME = "GM Sean"
PLAYER_NAME = "Player Wren"


@pytest.fixture(scope="module")
def main_module(tmp_path_factory):
    base = tmp_path_factory.mktemp("main_app")
    static_dir = base / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<html></html>")

    users_file = base / "users.yaml"
    users_file.write_text(yaml.dump({"users": [
        {"name": GM_NAME, "passphrase": GM_PASSPHRASE, "role": "gm", "color": "#ff0000"},
        {"name": PLAYER_NAME, "passphrase": PLAYER_PASSPHRASE, "role": "player", "color": "#00ff00"},
    ]}))

    originals = (Config.USERS_FILE, Config.STATIC_DIR, Config.DB_PATH, Config._users_cache)
    Config._users_cache = None
    Config.USERS_FILE = str(users_file)
    Config.STATIC_DIR = str(static_dir)
    Config.DB_PATH = str(base / "initial.db")

    sys.modules.pop("main", None)
    module = importlib.import_module("main")

    yield module

    Config.USERS_FILE, Config.STATIC_DIR, Config.DB_PATH, Config._users_cache = originals


@pytest.fixture
def client(main_module, tmp_path, monkeypatch):
    # Fresh SQLite file per test — the app's lifespan re-runs db.init() on entry.
    monkeypatch.setattr(main_module.db, "path", str(tmp_path / "test.db"))
    with TestClient(main_module.app) as c:
        yield c


@pytest.fixture
def mock_gm(monkeypatch):
    mock = AsyncMock(return_value="A narration happens.")
    monkeypatch.setattr(engine_module, "get_gm_response", mock)
    return mock


@pytest.fixture
def mock_broadcast(main_module, monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(main_module.manager, "broadcast", mock)
    return mock


def gm_headers():
    return {"X-Passphrase": GM_PASSPHRASE}


def player_headers():
    return {"X-Passphrase": PLAYER_PASSPHRASE}


def create_character(client, headers=None, **overrides):
    headers = headers or player_headers()
    payload = dict(
        name="Thoradin", char_class="Fighter",
        str_score=14, dex_score=12, con_score=14,
        int_score=9, wis_score=10, cha_score=8,
    )
    payload.update(overrides)
    return client.post("/api/character", json=payload, headers=headers)


def start_campaign(client):
    return client.post("/api/campaign/start", json={"name": "Test Campaign", "module": "B1"},
                        headers=gm_headers())


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_login_valid_passphrase_returns_user(client):
    resp = client.post("/api/login", json={"passphrase": PLAYER_PASSPHRASE})
    assert resp.status_code == 200
    assert resp.json() == {"name": PLAYER_NAME, "color": "#00ff00", "role": "player"}


def test_login_invalid_passphrase_returns_401(client):
    resp = client.post("/api/login", json={"passphrase": "not-a-real-passphrase"})
    assert resp.status_code == 401


def test_me_without_header_returns_422(client):
    resp = client.get("/api/me")
    assert resp.status_code == 422


def test_me_with_invalid_passphrase_returns_401(client):
    resp = client.get("/api/me", headers={"X-Passphrase": "wrong"})
    assert resp.status_code == 401


def test_me_with_valid_passphrase_returns_user(client):
    resp = client.get("/api/me", headers=player_headers())
    assert resp.status_code == 200
    assert resp.json()["name"] == PLAYER_NAME


# ── Campaign ──────────────────────────────────────────────────────────────────

def test_get_campaign_before_start_returns_empty(client):
    resp = client.get("/api/campaign", headers=player_headers())
    assert resp.status_code == 200
    assert resp.json() == {}


def test_start_campaign_creates_campaign_and_returns_narration(client, mock_gm):
    resp = start_campaign(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["campaign"] == {"name": "Test Campaign", "module": "B1"}
    assert body["narration"] == "A narration happens."


def test_start_campaign_broadcasts_gm_narration(client, mock_gm, mock_broadcast):
    start_campaign(client)
    event_types = [call.args[0] for call in mock_broadcast.await_args_list]
    assert "gm_narration" in event_types


def test_get_campaign_after_start_reflects_it(client, mock_gm):
    start_campaign(client)
    resp = client.get("/api/campaign", headers=player_headers())
    assert resp.json()["name"] == "Test Campaign"


def test_get_feed_reflects_narration_after_start(client, mock_gm):
    start_campaign(client)
    resp = client.get("/api/feed", headers=player_headers())
    assert resp.status_code == 200
    feed = resp.json()
    assert any(row["content"] == "A narration happens." for row in feed)


def test_get_recap_without_campaign_returns_400(client):
    resp = client.get("/api/recap", headers=player_headers())
    assert resp.status_code == 400


def test_get_recap_with_campaign_returns_text(client, mock_gm):
    start_campaign(client)
    resp = client.get("/api/recap", headers=player_headers())
    assert resp.status_code == 200
    assert resp.json() == {"recap": "A narration happens."}


def test_get_summary_without_campaign_returns_400(client):
    resp = client.get("/api/summary", headers=player_headers())
    assert resp.status_code == 400


def test_get_summary_with_campaign_returns_defaults(client, mock_gm):
    start_campaign(client)
    resp = client.get("/api/summary", headers=player_headers())
    assert resp.status_code == 200
    assert resp.json() == {"summary": "", "action_count": 0, "summarize_every": Config.SUMMARIZE_EVERY}


# ── Play ──────────────────────────────────────────────────────────────────────

def test_play_without_campaign_returns_400(client):
    resp = client.post("/api/play", json={"action": "I look around."}, headers=player_headers())
    assert resp.status_code == 400


def test_play_without_character_returns_400(client, mock_gm):
    start_campaign(client)
    resp = client.post("/api/play", json={"action": "I look around."}, headers=player_headers())
    assert resp.status_code == 400


def test_play_success_returns_ok(client, mock_gm):
    start_campaign(client)
    create_character(client)
    resp = client.post("/api/play", json={"action": "I look around."}, headers=player_headers())
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_play_broadcasts_player_action_and_narration(client, mock_gm, mock_broadcast):
    start_campaign(client)
    create_character(client)
    mock_broadcast.reset_mock()

    client.post("/api/play", json={"action": "I look around."}, headers=player_headers())

    event_types = [call.args[0] for call in mock_broadcast.await_args_list]
    assert "player_action" in event_types
    assert "gm_thinking" in event_types
    assert "gm_narration" in event_types
    assert "gm_thinking_done" in event_types


def test_play_llm_failure_returns_502(client, monkeypatch):
    start_campaign_mock = AsyncMock(return_value="Opening.")
    monkeypatch.setattr(engine_module, "get_gm_response", start_campaign_mock)
    start_campaign(client)
    create_character(client)

    monkeypatch.setattr(engine_module, "get_gm_response", AsyncMock(side_effect=RuntimeError("LLM down")))
    resp = client.post("/api/play", json={"action": "I look around."}, headers=player_headers())
    assert resp.status_code == 502


# ── Roll ──────────────────────────────────────────────────────────────────────

def test_roll_valid_notation(client):
    resp = client.post("/api/roll", json={"notation": "1d20+2", "reason": "attack"}, headers=player_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["rolls"]) == 1
    assert body["total"] == body["rolls"][0] + 2


def test_roll_invalid_notation_returns_400(client):
    resp = client.post("/api/roll", json={"notation": "not dice"}, headers=player_headers())
    assert resp.status_code == 400


def test_roll_broadcasts_dice_roll_event(client, mock_broadcast):
    client.post("/api/roll", json={"notation": "1d6"}, headers=player_headers())
    event_types = [call.args[0] for call in mock_broadcast.await_args_list]
    assert "dice_roll" in event_types


def test_roll_stats_returns_all_six_abilities(client):
    resp = client.get("/api/roll_stats", headers=player_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"STR", "DEX", "CON", "INT", "WIS", "CHA"}
    for stat in body.values():
        assert "value" in stat and "rolls" in stat and "modifier" in stat


# ── Characters ────────────────────────────────────────────────────────────────

def test_get_character_before_creation_returns_empty(client):
    resp = client.get("/api/character", headers=player_headers())
    assert resp.status_code == 200
    assert resp.json() == {}


def test_create_character_success(client):
    resp = create_character(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Thoradin"
    assert body["class"] == "Fighter"


def test_create_character_duplicate_returns_400(client):
    create_character(client)
    resp = create_character(client)
    assert resp.status_code == 400


def test_create_character_broadcasts_party_update(client, mock_broadcast):
    create_character(client)
    event_types = [call.args[0] for call in mock_broadcast.await_args_list]
    assert "party_update" in event_types
    assert "system_message" in event_types


def test_get_party_lists_created_characters(client):
    create_character(client, headers=player_headers())
    resp = client.get("/api/party", headers=player_headers())
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert "Thoradin" in names


def test_update_inventory_without_campaign_returns_400(client):
    resp = client.put("/api/character/inventory", json={"inventory": ["Torch"]}, headers=player_headers())
    assert resp.status_code == 400


def test_update_inventory_success(client):
    create_character(client)
    resp = client.put("/api/character/inventory", json={"inventory": ["Torch", "Rope"]},
                       headers=player_headers())
    assert resp.status_code == 200

    char = client.get("/api/character", headers=player_headers()).json()
    assert char["inventory"] == ["Torch", "Rope"]


def test_update_spells_success(client):
    create_character(client, char_class="Magic-User")
    resp = client.put("/api/character/spells", json={"spells": ["Sleep"]}, headers=player_headers())
    assert resp.status_code == 200

    char = client.get("/api/character", headers=player_headers()).json()
    assert char["spells"] == ["Sleep"]


# ── Rest ──────────────────────────────────────────────────────────────────────

def test_rest_without_campaign_returns_400(client):
    resp = client.post("/api/rest", json={"rest_type": "long"}, headers=player_headers())
    assert resp.status_code == 400


def test_long_rest_heals_party(client, mock_gm):
    start_campaign(client)
    create_character(client)
    char = client.get("/api/character", headers=player_headers()).json()
    # Damage but not enough to kill — a dead character drops out of the party roster.
    safe_delta = -(char["hp_max"] - 1) if char["hp_max"] > 1 else 0
    client.post("/api/gm/update_hp", json={"target_user": PLAYER_NAME, "delta": safe_delta},
                headers=gm_headers())

    resp = client.post("/api/rest", json={"rest_type": "long"}, headers=player_headers())
    assert resp.status_code == 200
    party = resp.json()["party"]
    assert len(party) == 1
    assert party[0]["hp"] == party[0]["hp_max"]


# ── GM tools ──────────────────────────────────────────────────────────────────

def test_gm_say_forbidden_for_player(client):
    resp = client.post("/api/gm/say", json={"message": "The walls shake."}, headers=player_headers())
    assert resp.status_code == 403


def test_gm_say_forbidden_without_campaign_but_checks_role_first(client):
    # Role check happens before the campaign-exists check, so a non-GM still gets 403
    # even with no campaign started.
    resp = client.post("/api/gm/say", json={"message": "hi"}, headers=player_headers())
    assert resp.status_code == 403


def test_gm_say_without_campaign_returns_400_for_gm(client):
    resp = client.post("/api/gm/say", json={"message": "hi"}, headers=gm_headers())
    assert resp.status_code == 400


def test_gm_say_success_for_gm(client, mock_gm, mock_broadcast):
    start_campaign(client)
    mock_broadcast.reset_mock()

    resp = client.post("/api/gm/say", json={"message": "The walls shake."}, headers=gm_headers())

    assert resp.status_code == 200
    event_types = [call.args[0] for call in mock_broadcast.await_args_list]
    assert "gm_narration" in event_types


def test_gm_update_hp_forbidden_for_player(client):
    resp = client.post("/api/gm/update_hp", json={"target_user": PLAYER_NAME, "delta": -1},
                        headers=player_headers())
    assert resp.status_code == 403


def test_gm_update_hp_unknown_character_returns_400(client, mock_gm):
    start_campaign(client)
    resp = client.post("/api/gm/update_hp", json={"target_user": "Nobody", "delta": -5},
                        headers=gm_headers())
    assert resp.status_code == 400


def test_gm_update_hp_success_and_death_broadcast(client, mock_gm, mock_broadcast):
    start_campaign(client)
    create_character(client)
    mock_broadcast.reset_mock()

    resp = client.post("/api/gm/update_hp", json={"target_user": PLAYER_NAME, "delta": -9999},
                        headers=gm_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert body["hp"] == 0
    assert body["alive"] is False
    event_types = [call.args[0] for call in mock_broadcast.await_args_list]
    assert "system_message" in event_types


# ── Reset campaign ────────────────────────────────────────────────────────────

def test_reset_campaign_forbidden_for_player(client):
    resp = client.post("/api/gm/reset_campaign", headers=player_headers())
    assert resp.status_code == 403


def test_reset_campaign_forbidden_without_campaign_but_checks_role_first(client):
    # Role check happens before the campaign-exists check, so a non-GM still gets 403
    # even with no campaign started.
    resp = client.post("/api/gm/reset_campaign", headers=player_headers())
    assert resp.status_code == 403


def test_reset_campaign_without_campaign_returns_400_for_gm(client):
    resp = client.post("/api/gm/reset_campaign", headers=gm_headers())
    assert resp.status_code == 400


def test_reset_campaign_success_clears_campaign_and_party(client, mock_gm):
    start_campaign(client)
    create_character(client)

    resp = client.post("/api/gm/reset_campaign", headers=gm_headers())

    assert resp.status_code == 200
    assert resp.json()["name"] == "Test Campaign"
    assert client.get("/api/campaign", headers=player_headers()).json() == {}
    assert client.get("/api/party", headers=player_headers()).json() == []


def test_reset_campaign_broadcasts_campaign_reset_event(client, mock_gm, mock_broadcast):
    start_campaign(client)
    mock_broadcast.reset_mock()

    client.post("/api/gm/reset_campaign", headers=gm_headers())

    events = {call.args[0]: call.args[1] for call in mock_broadcast.await_args_list}
    assert events["campaign_reset"] == {"name": "Test Campaign"}


def test_reset_campaign_allows_starting_new_campaign_after(client, mock_gm):
    start_campaign(client)
    create_character(client)
    client.post("/api/gm/reset_campaign", headers=gm_headers())

    resp = start_campaign(client)

    assert resp.status_code == 200
    campaign = client.get("/api/campaign", headers=player_headers()).json()
    assert campaign["name"] == "Test Campaign"
    assert client.get("/api/party", headers=player_headers()).json() == []


# ── WebSocket ─────────────────────────────────────────────────────────────────

def test_websocket_rejects_invalid_passphrase(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?passphrase=wrong-passphrase") as ws:
            ws.receive_json()


def test_websocket_accepts_valid_passphrase_and_sends_presence(client):
    with client.websocket_connect(f"/ws?passphrase={PLAYER_PASSPHRASE}") as ws:
        message = ws.receive_json()
        assert message["type"] == "presence"
        assert PLAYER_NAME in message["payload"]["online"]
