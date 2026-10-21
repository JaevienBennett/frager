"""Shared pytest setup for the backend test suite.

The suite talks to a real PostgreSQL database (DATABASE_URL). This makes it
self-sufficient on a fresh database: the schema is created if it is missing
and a minimal user/league pair is seeded, because the M14 tests expect at
least one league and one user to exist.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import text

# Make `app` and `migrations` importable no matter how pytest was invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import models  # noqa: F401  (registers the tables on Base.metadata)
from app.database import Base, SessionLocal, engine
from app.security import hash_password


@pytest.fixture(scope="session", autouse=True)
def _database_ready():
    Base.metadata.create_all(engine)

    db = SessionLocal()
    try:
        if db.query(models.User).count() == 0:
            db.add(
                models.User(
                    email="seed-user@frager.invalid",
                    nickname="seed-user",
                    password_hash=hash_password("seed-password-123"),
                )
            )
            db.commit()

        if db.query(models.League).count() == 0:
            owner = db.query(models.User).order_by(models.User.id).first()
            league = models.League(
                name="Seed League",
                invite_code="seed-invite-code",
                owner_id=owner.id,
            )
            db.add(league)
            db.commit()
            db.add(models.Membership(league_id=league.id, user_id=owner.id))
            db.commit()
    finally:
        db.close()


@pytest.fixture(scope="session")
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
