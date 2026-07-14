"""
OSE App — FastAPI backend entry point.

Run: uvicorn main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from config import Config
from engine import GameEngine
from ws_manager import manager
from utils.database import Database
from utils.dice import roll as roll_dice, roll_ability_scores, bx_modifier
from models.schemas import (
    LoginRequest, LoginResponse, CreateCharacterRequest, PlayActionRequest,
    RollRequest, GMSayRequest, UpdateHPRequest, StartCampaignRequest,
    RestRequest, UpdateInventoryRequest, UpdateSpellsRequest,
    PhysicalDiceModeRequest,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("ose-app")

config = Config()
db = Database(config.DB_PATH)
engine = GameEngine(db, config)

# One player action at a time — prevents interleaved GM responses
gm_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    log.info("Database initialized.")
    yield


app = FastAPI(title="OSE App", lifespan=lifespan)


# ── Auth dependency ───────────────────────────────────────────────────────────

async def current_user(x_passphrase: str = Header(...)) -> dict:
    user = Config.authenticate(x_passphrase)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid passphrase")
    return user


async def gm_user(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "gm":
        raise HTTPException(status_code=403, detail="GM only")
    return user


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/api/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    user = Config.authenticate(req.passphrase)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid passphrase")
    return user


@app.get("/api/me", response_model=LoginResponse)
async def me(user: dict = Depends(current_user)):
    return user


# ── Campaign ──────────────────────────────────────────────────────────────────

@app.get("/api/campaign")
async def get_campaign(user: dict = Depends(current_user)):
    campaign = await engine.get_campaign()
    return campaign or {}


@app.post("/api/campaign/start")
async def start_campaign(req: StartCampaignRequest, user: dict = Depends(current_user)):
    async with gm_lock:
        result = await engine.start_campaign(req.name, req.module)
    await manager.broadcast("gm_narration", {
        "author": "GM",
        "content": result["narration"],
        "campaign": result["campaign"],
    })
    return result


@app.get("/api/feed")
async def get_feed(user: dict = Depends(current_user)):
    return await engine.get_feed()


@app.get("/api/recap")
async def get_recap(user: dict = Depends(current_user)):
    try:
        text = await engine.recap()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"recap": text}


@app.get("/api/summary")
async def get_summary(user: dict = Depends(current_user)):
    try:
        return await engine.get_summary()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Play ──────────────────────────────────────────────────────────────────────

@app.post("/api/play")
async def play(req: PlayActionRequest, user: dict = Depends(current_user)):
    await manager.broadcast("player_action", {
        "author": user["name"],
        "color": user.get("color", "#ffffff"),
        "content": req.action,
    })
    await manager.broadcast("gm_thinking", {"acting_player": user["name"]})

    try:
        async with gm_lock:
            result = await engine.play(user["name"], req.action)
    except ValueError as e:
        await manager.broadcast("gm_thinking_done", {})
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"GM error: {e}")
        await manager.broadcast("gm_thinking_done", {})
        raise HTTPException(status_code=502, detail=f"GM unavailable: {e}")

    await manager.broadcast("gm_thinking_done", {})
    await manager.broadcast("gm_narration", {
        "author": "GM",
        "content": result["narration"],
    })

    if result["state_actions"]:
        party = await engine.get_party()
        await manager.broadcast("party_update", {"party": party})

    return {"ok": True}


@app.post("/api/roll")
async def roll(req: RollRequest, user: dict = Depends(current_user)):
    if req.reported_result is not None:
        total, rolls, physical = req.reported_result, [], True
    else:
        try:
            total, rolls, desc = roll_dice(req.notation)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        physical = False

    await manager.broadcast("dice_roll", {
        "author": user["name"],
        "color": user.get("color", "#ffffff"),
        "notation": req.notation,
        "reason": req.reason,
        "rolls": rolls,
        "total": total,
        "physical": physical,
    })
    return {"total": total, "rolls": rolls}


@app.get("/api/roll_stats")
async def roll_stats(user: dict = Depends(current_user)):
    stats = roll_ability_scores()
    return {
        stat: {"value": d["value"], "rolls": d["rolls"], "modifier": bx_modifier(d["value"])}
        for stat, d in stats.items()
    }


# ── Characters ────────────────────────────────────────────────────────────────

@app.get("/api/character")
async def get_character(user: dict = Depends(current_user)):
    char = await engine.get_character(user["name"])
    return char or {}


@app.post("/api/character")
async def create_character(req: CreateCharacterRequest, user: dict = Depends(current_user)):
    try:
        char = await engine.create_character(user["name"], req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    party = await engine.get_party()
    await manager.broadcast("party_update", {"party": party})
    await manager.broadcast("system_message", {
        "content": f"⚔️ {char['name']} the {char['class']} joins the party! (played by {user['name']})"
    })
    return char


@app.get("/api/party")
async def get_party(user: dict = Depends(current_user)):
    return await engine.get_party()


@app.put("/api/character/inventory")
async def update_inventory(req: UpdateInventoryRequest, user: dict = Depends(current_user)):
    try:
        await engine.update_inventory(user["name"], req.inventory)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    party = await engine.get_party()
    await manager.broadcast("party_update", {"party": party})
    return {"ok": True}


@app.put("/api/character/spells")
async def update_spells(req: UpdateSpellsRequest, user: dict = Depends(current_user)):
    try:
        await engine.update_spells(user["name"], req.spells)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    party = await engine.get_party()
    await manager.broadcast("party_update", {"party": party})
    return {"ok": True}


# ── Rest ──────────────────────────────────────────────────────────────────────

@app.post("/api/rest")
async def rest(req: RestRequest, user: dict = Depends(current_user)):
    try:
        result = await engine.rest(req.rest_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    party = await engine.get_party()
    await manager.broadcast("party_update", {"party": party})
    label = "🌙 The party takes a long rest. HP and spells restored." \
        if req.rest_type == "long" else "☕ The party rests briefly."
    await manager.broadcast("system_message", {"content": label})
    return result


# ── GM tools ──────────────────────────────────────────────────────────────────

@app.post("/api/gm/say")
async def gm_say(req: GMSayRequest, user: dict = Depends(gm_user)):
    try:
        await engine.gm_say(req.message)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await manager.broadcast("gm_narration", {
        "author": "GM (Manual)",
        "content": req.message,
    })
    return {"ok": True}


@app.post("/api/gm/update_hp")
async def gm_update_hp(req: UpdateHPRequest, user: dict = Depends(gm_user)):
    try:
        result = await engine.update_hp(req.target_user, req.delta)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    party = await engine.get_party()
    await manager.broadcast("party_update", {"party": party})
    if not result["alive"]:
        await manager.broadcast("system_message",
                                {"content": f"💀 {result['name']} has fallen!"})
    return result


@app.post("/api/gm/physical_dice_mode")
async def gm_set_physical_dice_mode(req: PhysicalDiceModeRequest, user: dict = Depends(gm_user)):
    try:
        enabled = await engine.set_physical_dice_mode(req.enabled)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await manager.broadcast("physical_dice_mode", {"enabled": enabled})
    return {"enabled": enabled}


@app.post("/api/gm/reset_campaign")
async def gm_reset_campaign(user: dict = Depends(gm_user)):
    # Takes gm_lock (unlike the other GM tools) so the delete can't race an
    # in-flight play()/start_campaign() that already holds a campaign_id.
    async with gm_lock:
        try:
            result = await engine.reset_campaign()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    await manager.broadcast("campaign_reset", {"name": result["name"]})
    return {"ok": True, "name": result["name"]}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, passphrase: str):
    user = Config.authenticate(passphrase)
    if not user:
        await websocket.close(code=4001)
        return

    await manager.connect(user["name"], websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user["name"], websocket)
        await manager.broadcast_presence()


# ── Static frontend ───────────────────────────────────────────────────────────
# Mount the entire static directory. For SPA routing, unmatched paths fall
# back to index.html via custom middleware — this avoids all route-ordering
# issues with FastAPI's catch-all patterns.

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import aiofiles

static_dir = Path(config.STATIC_DIR)


class SPAMiddleware(BaseHTTPMiddleware):
    """Serve index.html for any non-API, non-asset path that doesn't exist as a file."""
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        # Only intercept 404s that aren't API or WebSocket calls
        if (response.status_code == 404
                and not path.startswith("/api")
                and not path.startswith("/ws")
                and not path.startswith("/docs")
                and not path.startswith("/openapi")):
            index = static_dir / "index.html"
            if index.exists():
                return FileResponse(index)
        return response


app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
app.add_middleware(SPAMiddleware)
