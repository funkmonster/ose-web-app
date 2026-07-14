"""
Tests for ws_manager.py

ConnectionManager tracks one WebSocket per user name and fans out broadcast
messages to everyone. These tests fake the WebSocket with AsyncMock rather
than opening real sockets — we only care that the manager calls accept/
send_text/close correctly and cleans up dead connections.
"""

import json

import pytest
from unittest.mock import AsyncMock

from ws_manager import ConnectionManager


@pytest.fixture
def manager():
    return ConnectionManager()


def make_ws():
    return AsyncMock()


async def test_connect_accepts_and_registers(manager):
    ws = make_ws()
    await manager.connect("Sean", ws)

    ws.accept.assert_awaited_once()
    assert manager.connections["Sean"] is ws


async def test_connect_closes_stale_connection_for_same_user(manager):
    old_ws = make_ws()
    new_ws = make_ws()

    await manager.connect("Sean", old_ws)
    await manager.connect("Sean", new_ws)

    old_ws.close.assert_awaited_once()
    assert manager.connections["Sean"] is new_ws


async def test_connect_survives_close_raising(manager):
    old_ws = make_ws()
    old_ws.close.side_effect = Exception("already gone")
    new_ws = make_ws()

    await manager.connect("Sean", old_ws)
    # Should not raise even though closing the stale socket fails
    await manager.connect("Sean", new_ws)

    assert manager.connections["Sean"] is new_ws


async def test_connect_broadcasts_presence_to_all(manager):
    ws1, ws2 = make_ws(), make_ws()
    await manager.connect("Sean", ws1)
    await manager.connect("Wren", ws2)

    # Each connect() re-broadcasts presence to everyone currently connected
    last_call_ws2 = json.loads(ws2.send_text.await_args_list[-1].args[0])
    assert last_call_ws2["type"] == "presence"
    assert set(last_call_ws2["payload"]["online"]) == {"Sean", "Wren"}


def test_disconnect_removes_user(manager):
    ws = make_ws()
    manager.connections["Sean"] = ws
    manager.disconnect("Sean", ws)
    assert "Sean" not in manager.connections


def test_disconnect_ignores_unknown_user(manager):
    # Should not raise
    manager.disconnect("Nobody")
    assert manager.connections == {}


def test_disconnect_does_not_remove_newer_connection(manager):
    # Simulates a race: an old socket's disconnect handler fires after
    # the user already reconnected with a new socket.
    stale_ws = make_ws()
    fresh_ws = make_ws()
    manager.connections["Sean"] = fresh_ws

    manager.disconnect("Sean", stale_ws)

    assert manager.connections["Sean"] is fresh_ws


async def test_broadcast_sends_to_all_connections(manager):
    ws1, ws2 = make_ws(), make_ws()
    manager.connections = {"Sean": ws1, "Wren": ws2}

    await manager.broadcast("gm_narration", {"content": "A door creaks open."})

    for ws in (ws1, ws2):
        sent = json.loads(ws.send_text.await_args.args[0])
        assert sent == {"type": "gm_narration", "payload": {"content": "A door creaks open."}}


async def test_broadcast_drops_dead_connections(manager):
    good_ws = make_ws()
    dead_ws = make_ws()
    dead_ws.send_text.side_effect = Exception("connection reset")
    manager.connections = {"Sean": good_ws, "Ghost": dead_ws}

    await manager.broadcast("system_message", {"content": "hello"})

    assert "Ghost" not in manager.connections
    assert "Sean" in manager.connections


async def test_send_to_specific_user_only(manager):
    ws1, ws2 = make_ws(), make_ws()
    manager.connections = {"Sean": ws1, "Wren": ws2}

    await manager.send_to("Sean", "private_note", {"text": "psst"})

    ws1.send_text.assert_awaited_once()
    ws2.send_text.assert_not_awaited()


async def test_send_to_unknown_user_is_a_noop(manager):
    # Should not raise
    await manager.send_to("Nobody", "event", {})


async def test_send_to_drops_connection_on_send_failure(manager):
    ws = make_ws()
    ws.send_text.side_effect = Exception("closed")
    manager.connections = {"Sean": ws}

    await manager.send_to("Sean", "event", {})

    assert "Sean" not in manager.connections


async def test_broadcast_presence_lists_online_users(manager):
    ws1, ws2 = make_ws(), make_ws()
    manager.connections = {"Sean": ws1, "Wren": ws2}

    await manager.broadcast_presence()

    sent = json.loads(ws1.send_text.await_args.args[0])
    assert sent["type"] == "presence"
    assert set(sent["payload"]["online"]) == {"Sean", "Wren"}
