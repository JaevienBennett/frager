import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import database  # noqa: F401
from .routes_auth import router as auth_router
from .routes_leagues import router as leagues_router
from .routes_predictions import router as predictions_router

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
