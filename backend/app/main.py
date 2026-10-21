import os

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from . import database  # noqa: F401
from . import ws as ws_module
from .membership import is_member
from .rate_limit import limiter
from .routes_auth import router as auth_router
from .routes_leagues import router as leagues_router
from .routes_predictions import router as predictions_router
from .security import decode_access_token

load_dotenv()

app = FastAPI(title="Frager")
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Too many requests. Try again later."})


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


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

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
