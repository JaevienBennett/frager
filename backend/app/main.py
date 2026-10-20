from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import database  # noqa: F401

app = FastAPI(title="Frager")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}
