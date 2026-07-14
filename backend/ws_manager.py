"""
WebSocket connection manager.

Every connected client registers here. Game events (GM narration, dice rolls,
state changes, presence) are broadcast to everyone so all three players see
the same thing in real time.
"""

import json
import logging
from fastapi import WebSocket

log = logging.getLogger("ose-app.ws")


class ConnectionManager:
    def __init__(self):
        # user_name -> WebSocket (one connection per user; new connection replaces old)
        self.connections: dict[str, WebSocket] = {}

    async def connect(self, user_name: str, websocket: WebSocket):
        await websocket.accept()
        # Replace any stale connection for this user
        old = self.connections.get(user_name)
        if old is not None:
            try:
                await old.close()
            except Exception:
                pass
        self.connections[user_name] = websocket
        log.info(f"{user_name} connected ({len(self.connections)} online)")
        await self.broadcast_presence()

    def disconnect(self, user_name: str, websocket: WebSocket = None):
        # Only remove if this exact socket is registered (avoid races on reconnect)
        if user_name in self.connections:
            if websocket is None or self.connections[user_name] is websocket:
                del self.connections[user_name]
                log.info(f"{user_name} disconnected ({len(self.connections)} online)")

    async def broadcast(self, event_type: str, payload: dict):
        """Send an event to every connected client."""
        message = json.dumps({"type": event_type, "payload": payload})
        dead = []
        for name, ws in self.connections.items():
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(name)
        for name in dead:
            self.connections.pop(name, None)

    async def send_to(self, user_name: str, event_type: str, payload: dict):
        """Send an event to one specific user."""
        ws = self.connections.get(user_name)
        if ws:
            try:
                await ws.send_text(json.dumps({"type": event_type, "payload": payload}))
            except Exception:
                self.connections.pop(user_name, None)

    async def broadcast_presence(self):
        await self.broadcast("presence", {"online": list(self.connections.keys())})


manager = ConnectionManager()
