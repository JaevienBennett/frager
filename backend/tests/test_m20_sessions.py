"""Milestone 20 backend tests: rotating refresh tokens and revocation.

Users are created directly in the database and access tokens are minted with
``create_access_token`` so the suite does not lean on the auth rate limits.
``/api/auth/signup`` and ``/api/auth/login`` are each called exactly once, to
assert the response shape the frontend depends on.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import text

from app import models
from app.config import ALGORITHM, SECRET_KEY
from app.database import SessionLocal, engine
from app.main import app
from app.models import RefreshToken, User
from app.security import create_access_token, hash_password, hash_refresh_token
from migrations import migrate_v20_sessions

SESSION_SCHEMA = "m20_sessions_test"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _schema_ready():
    """Make sure the database has the M20 columns/tables before any test runs.

    ``Base.metadata.create_all`` (conftest) creates *missing tables* but never
    adds a column to an existing table, so a database created before M20 has
    no ``users.token_version``. The migration is idempotent, so running it here
    is safe on both a fresh and an already migrated database.
    """
    migrate_v20_sessions.migrate(schema="public")
    yield


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def db_session():
    session = SessionLocal()
    created: list[int] = []
    try:
        yield session, created
    finally:
        for user_id in created:
            session.query(RefreshToken).filter(
                RefreshToken.user_id == user_id
            ).delete()
            session.query(User).filter(User.id == user_id).delete()
        session.commit()
        session.close()


def _make_user(session, created) -> User:
    tag = uuid.uuid4().hex[:10]
    user = User(
        email=f"m20-{tag}@example.com",
        nickname=f"m20-{tag}",
        password_hash=hash_password("pass123456"),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    created.append(user.id)
    return user


def _insert_refresh_token(session, user_id, raw_token, expires_at=None):
    """Insert a refresh token row directly, bypassing the auth endpoints."""
    if expires_at is None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    row = RefreshToken(
        user_id=user_id,
        token_hash=hash_refresh_token(raw_token),
        expires_at=expires_at,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _bearer(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


# --------------------------------------------------------------------------
# token payload shape
# --------------------------------------------------------------------------


def test_signup_returns_access_and_refresh_tokens(client, db_session):
    session, created = db_session
    tag = uuid.uuid4().hex[:10]
    email = f"m20-signup-{tag}@example.com"
    r = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "nickname": f"m20s-{tag}",
            "password": "pass123456",
        },
    )
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    # the refresh token is opaque, not a JWT
    assert body["refresh_token"].count(".") == 0
    assert len(body["refresh_token"]) >= 43

    # track the row so it is removed again on a persistent database
    user = session.query(User).filter(User.email == email).one()
    created.append(user.id)


def test_login_returns_access_and_refresh_tokens(client, db_session):
    session, created = db_session
    user = _make_user(session, created)
    r = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "pass123456"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"

    # only the hash is stored, never the raw token
    row = session.query(RefreshToken).filter(
        RefreshToken.token_hash == hash_refresh_token(body["refresh_token"])
    ).one()
    assert row.user_id == user.id
    assert row.revoked_at is None
    assert body["refresh_token"] not in row.token_hash


# --------------------------------------------------------------------------
# refresh rotation
# --------------------------------------------------------------------------


def test_refresh_rotates_the_pair_and_works_on_me(client, db_session):
    session, created = db_session
    user = _make_user(session, created)
    raw = f"m20-raw-{uuid.uuid4().hex}"
    _insert_refresh_token(session, user.id, raw)

    r = client.post("/api/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["refresh_token"] != raw

    # the new access token carries the current token version
    claims = jwt.get_unverified_claims(body["access_token"])
    assert claims["sub"] == str(user.id)
    assert claims["ver"] == user.token_version

    # the new access token works
    r2 = client.get("/api/auth/me", headers=_bearer(body["access_token"]))
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == user.id

    # the presented token is now spent
    session.expire_all()
    old_row = session.query(RefreshToken).filter(
        RefreshToken.token_hash == hash_refresh_token(raw)
    ).one()
    assert old_row.revoked_at is not None


def test_replaying_a_just_rotated_token_does_not_nuke_sessions(client, db_session):
    """A multi-tab race must not revoke every session."""
    session, created = db_session
    user = _make_user(session, created)
    raw = f"m20-raw-{uuid.uuid4().hex}"
    _insert_refresh_token(session, user.id, raw)

    first = client.post("/api/auth/refresh", json={"refresh_token": raw})
    assert first.status_code == 200, first.text
    rotated = first.json()

    second = client.post("/api/auth/refresh", json={"refresh_token": raw})
    assert second.status_code == 401, second.text
    assert second.json()["detail"] == "Refresh token already rotated"

    session.expire_all()
    assert user.token_version == 0
    assert (
        session.query(RefreshToken)
        .filter(
            RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
        )
        .count()
        == 1
    )

    # the winning tab's token still works
    third = client.post(
        "/api/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert third.status_code == 200, third.text


def test_reusing_a_revoked_refresh_token_revokes_everything(client, db_session):
    session, created = db_session
    user = _make_user(session, created)
    raw = f"m20-raw-{uuid.uuid4().hex}"
    _insert_refresh_token(session, user.id, raw)
    old_access = create_access_token(str(user.id), user.token_version)

    first = client.post("/api/auth/refresh", json={"refresh_token": raw})
    assert first.status_code == 200, first.text
    rotated = first.json()
    assert (
        client.get("/api/auth/me", headers=_bearer(rotated["access_token"])).status_code
        == 200
    )

    # age the spent token past the rotation grace window: now it is theft
    session.expire_all()
    spent = (
        session.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_refresh_token(raw))
        .one()
    )
    assert spent.revoked_reason == "rotated"
    spent.revoked_at = datetime.now(timezone.utc) - timedelta(seconds=60)
    session.commit()

    second = client.post("/api/auth/refresh", json={"refresh_token": raw})
    assert second.status_code == 401, second.text
    assert second.json()["detail"] == "Refresh token reuse detected; all sessions revoked"

    session.expire_all()
    assert user.token_version == 1

    # every refresh token of that user is gone
    active = session.query(RefreshToken).filter(
        RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
    ).count()
    assert active == 0

    # the freshly issued refresh token is dead too
    third = client.post("/api/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    assert third.status_code == 401, third.text

    # and both access tokens are now invalid
    assert client.get("/api/auth/me", headers=_bearer(rotated["access_token"])).status_code == 401
    assert client.get("/api/auth/me", headers=_bearer(old_access)).status_code == 401


def test_refresh_with_unknown_token_is_rejected(client):
    r = client.post("/api/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert r.status_code == 401, r.text
    assert r.json()["detail"] == "Invalid refresh token"


def test_expired_refresh_token_is_rejected_without_rotating(client, db_session):
    session, created = db_session
    user = _make_user(session, created)
    raw = f"m20-raw-{uuid.uuid4().hex}"
    row = _insert_refresh_token(
        session,
        user.id,
        raw,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=5),
    )

    r = client.post("/api/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 401, r.text
    assert r.json()["detail"] == "Refresh token expired"

    # not rotated, not revoked
    session.expire_all()
    again = session.get(RefreshToken, row.id)
    assert again.revoked_at is None
    assert session.query(RefreshToken).filter(
        RefreshToken.user_id == user.id
    ).count() == 1


# --------------------------------------------------------------------------
# logout
# --------------------------------------------------------------------------


def test_logout_revokes_the_presented_refresh_token(client, db_session):
    session, created = db_session
    user = _make_user(session, created)
    raw = f"m20-raw-{uuid.uuid4().hex}"
    _insert_refresh_token(session, user.id, raw)

    r = client.post("/api/auth/logout", json={"refresh_token": raw})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    session.expire_all()
    row = session.query(RefreshToken).filter(
        RefreshToken.token_hash == hash_refresh_token(raw)
    ).one()
    assert row.revoked_at is not None
    assert row.revoked_reason == "logout"

    # it can no longer be used, but other sessions survive
    r2 = client.post("/api/auth/refresh", json={"refresh_token": raw})
    assert r2.status_code == 401, r2.text
    assert r2.json()["detail"] == "Refresh token has been revoked"
    session.expire_all()
    assert user.token_version == 0


def test_logout_with_unknown_token_still_succeeds(client):
    r = client.post("/api/auth/logout", json={"refresh_token": "never-existed"})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


def test_logout_all_invalidates_access_and_refresh_tokens(client, db_session):
    session, created = db_session
    user = _make_user(session, created)
    raw = f"m20-raw-{uuid.uuid4().hex}"
    _insert_refresh_token(session, user.id, raw)
    access = create_access_token(str(user.id), user.token_version)

    assert client.get("/api/auth/me", headers=_bearer(access)).status_code == 200

    r = client.post("/api/auth/logout-all", headers=_bearer(access))
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    session.expire_all()
    assert user.token_version == 1
    assert (
        session.query(RefreshToken).filter(
            RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
        ).count()
        == 0
    )

    # the old access token dies immediately
    assert client.get("/api/auth/me", headers=_bearer(access)).status_code == 401
    # and so does the refresh token, without bumping the version a second time
    spent = client.post("/api/auth/refresh", json={"refresh_token": raw})
    assert spent.status_code == 401, spent.text
    assert spent.json()["detail"] == "Refresh token has been revoked"
    session.expire_all()
    assert user.token_version == 1

    # a fresh login works again
    login = client.post(
        "/api/auth/login", json={"email": user.email, "password": "pass123456"}
    )
    assert login.status_code == 200, login.text
    new_access = login.json()["access_token"]
    assert client.get("/api/auth/me", headers=_bearer(new_access)).status_code == 200


def test_logout_all_requires_authentication(client):
    r = client.post("/api/auth/logout-all")
    assert r.status_code in (401, 403), r.text


# --------------------------------------------------------------------------
# backward compatibility
# --------------------------------------------------------------------------


def test_access_token_without_ver_claim_works_while_version_is_zero(
    client, db_session
):
    """Tokens issued before the deploy have no "ver" claim and must keep working."""
    session, created = db_session
    user = _make_user(session, created)
    assert user.token_version == 0

    legacy_access = jwt.encode(
        {"sub": str(user.id), "exp": datetime.utcnow() + timedelta(minutes=30)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    assert "ver" not in jwt.get_unverified_claims(legacy_access)
    assert client.get("/api/auth/me", headers=_bearer(legacy_access)).status_code == 200

    # once the version moves on, the legacy token is rejected
    user.token_version = 1
    session.commit()
    assert client.get("/api/auth/me", headers=_bearer(legacy_access)).status_code == 401


# --------------------------------------------------------------------------
# migration
# --------------------------------------------------------------------------


def _drop_schema(schema):
    conn = engine.connect()
    try:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()
    finally:
        conn.close()


def _create_legacy_users(conn, schema):
    """Create the pre-M20 users table (no token_version) in a throwaway schema."""
    conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    conn.execute(
        text(
            f"""
            CREATE TABLE "{schema}"."users" (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) NOT NULL UNIQUE,
                nickname VARCHAR(24) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
            """
        )
    )
    conn.commit()


def _column_info(schema):
    conn = engine.connect()
    try:
        rows = conn.execute(
            text(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = :schema AND table_name = 'users'
                  AND column_name = 'token_version'
                """
            ),
            {"schema": schema},
        ).all()
        return rows
    finally:
        conn.close()


def _indexes(schema):
    conn = engine.connect()
    try:
        return {
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname = :schema AND tablename = 'refresh_tokens'
                    """
                ),
                {"schema": schema},
            ).all()
        }
    finally:
        conn.close()


def _fk_delete_rule(schema):
    conn = engine.connect()
    try:
        rows = conn.execute(
            text(
                """
                SELECT c.confdeltype
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace tn ON tn.oid = t.relnamespace
                JOIN pg_class rt ON rt.oid = c.confrelid
                JOIN pg_namespace rn ON rn.oid = rt.relnamespace
                JOIN pg_attribute a
                  ON a.attrelid = t.oid AND a.attnum = ANY (c.conkey)
                WHERE c.contype = 'f'
                  AND tn.nspname = :schema
                  AND t.relname = 'refresh_tokens'
                  AND rn.nspname = :schema
                  AND rt.relname = 'users'
                  AND a.attname = 'user_id'
                """
            ),
            {"schema": schema},
        ).all()
        return rows[0][0] if rows else None
    finally:
        conn.close()


def test_migration_is_idempotent_and_creates_the_session_schema():
    _drop_schema(SESSION_SCHEMA)
    try:
        conn = engine.connect()
        try:
            _create_legacy_users(conn, SESSION_SCHEMA)
        finally:
            conn.close()

        # pre-state: no token_version column, no refresh_tokens table
        assert _column_info(SESSION_SCHEMA) == []
        assert _indexes(SESSION_SCHEMA) == set()

        first = migrate_v20_sessions.migrate(schema=SESSION_SCHEMA)
        assert first["changed"] > 0
        assert first["schema"] == SESSION_SCHEMA

        # the column exists, NOT NULL, defaulting to 0
        cols = _column_info(SESSION_SCHEMA)
        assert len(cols) == 1
        name, data_type, nullable, default = cols[0]
        assert name == "token_version"
        assert data_type == "integer"
        assert nullable == "NO"
        assert "0" in (default or "")

        # the table and both indexes exist
        assert "ix_refresh_tokens_token_hash" in _indexes(SESSION_SCHEMA)
        assert "ix_refresh_tokens_user_id" in _indexes(SESSION_SCHEMA)

        # revocation reasons are recorded
        conn = engine.connect()
        try:
            columns = {
                row[0]
                for row in conn.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = :schema
                          AND table_name = 'refresh_tokens'
                        """
                    ),
                    {"schema": SESSION_SCHEMA},
                ).all()
            }
        finally:
            conn.close()
        assert "revoked_reason" in columns

        # the user_id FK cascades
        assert _fk_delete_rule(SESSION_SCHEMA) == "c"

        # second run changes nothing
        second = migrate_v20_sessions.migrate(schema=SESSION_SCHEMA)
        assert second["changed"] == 0
        assert all(r["action"] == "unchanged" for r in second["results"])

        # and the schema is still correct
        assert len(_column_info(SESSION_SCHEMA)) == 1
        assert _fk_delete_rule(SESSION_SCHEMA) == "c"
    finally:
        _drop_schema(SESSION_SCHEMA)


def test_migration_leaves_the_public_schema_alone():
    """The public schema is migrated by the session fixture; it must be stable."""
    first = migrate_v20_sessions.migrate(schema="public")
    assert first["changed"] == 0
    assert all(r["action"] == "unchanged" for r in first["results"])


def test_users_model_declares_token_version():
    column = models.Base.metadata.tables["users"].columns["token_version"]
    assert not column.nullable
    assert column.default.arg == 0
    assert column.server_default is not None


def test_refresh_token_model_declares_unique_hash_and_cascade():
    table = models.Base.metadata.tables["refresh_tokens"]
    assert table.columns["token_hash"].unique is True
    assert table.columns["token_hash"].type.length == 64
    assert table.columns["revoked_reason"].nullable is True
    fks = [fk for col in table.columns for fk in col.foreign_keys]
    assert len(fks) == 1
    assert fks[0].ondelete == "CASCADE"
