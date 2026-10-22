"""The pool must check a connection before it hands it out.

Found by a production probe: the first request after a quiet period answered
500, the second one worked. Neon (or the proxy in front of it) closes idle
connections, and a pool without ``pool_pre_ping`` hands the dead one to the
request instead of noticing.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import event

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import models  # noqa: F401
from app.database import SessionLocal, engine


def test_the_pool_pings_a_connection_before_it_hands_it_out(monkeypatch):
    """A checkout has to be preceded by a liveness check."""
    pings = []
    original = engine.dialect.do_ping

    def spy(dbapi_connection):
        pings.append(dbapi_connection)
        return original(dbapi_connection)

    monkeypatch.setattr(engine.dialect, "do_ping", spy)

    db = SessionLocal()
    try:
        assert db.query(models.User).first() is not None
    finally:
        db.rollback()
        db.close()

    assert pings, "the pool handed out a connection without checking it"


def test_the_engine_is_configured_to_ping_and_to_recycle():
    assert engine.pool._pre_ping is True
    assert engine.pool._recycle == 300
