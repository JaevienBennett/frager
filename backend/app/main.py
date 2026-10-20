from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import database  # noqa: F401
from .routes_auth import router as auth_router

app = FastAPI(title="Frager")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
