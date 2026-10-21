import os

from dotenv import load_dotenv
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import database  # noqa: F401
from . import ws as ws_module
from .membership import is_member
from .routes_auth import router as auth_router
from .routes_leagues import router as leagues_router
from .routes_predictions import router as predictions_router
from .security import decode_access_token

load_dotenv()

app = FastAPI(title="Frager")

cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(leagues_router)
app.include_router(predictions_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws/leagues/{league_id}")
async def websocket_league(websocket: WebSocket, league_id: int, token: str = Query(...)):
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub"))
    except Exception:
        await websocket.close()
        return
    from .database import SessionLocal

    db = SessionLocal()
    try:
        if not is_member(db, league_id, user_id):
            await websocket.close()
            return
    finally:
        db.close()
    await ws_module.manager.connect(league_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_module.manager.disconnect(league_id, websocket)
    except Exception:
        ws_module.manager.disconnect(league_id, websocket)
