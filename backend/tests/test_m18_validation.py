"""Milestone 18 backend tests: input validation and cascade integrity."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app import models
from app.database import engine
from app.main import app
from app.schemas import LeagueCreate, PredictionCreate
from migrations import migrate_v18_cascades
from migrations import migrate_v25_creator_set_null

CASCADE_SCHEMA = "m18_cascade_test"

TARGET_FKS = (
    ("memberships", "league_id", "leagues", "id"),
    ("memberships", "user_id", "users", "id"),
    ("predictions", "league_id", "leagues", "id"),
    ("picks", "prediction_id", "predictions", "id"),
    ("picks", "user_id", "users", "id"),
    ("leagues", "owner_id", "users", "id"),
)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def auth_headers(client):
    tag = uuid.uuid4().hex[:10]
    r = client.post(
        "/api/auth/signup",
        json={
            "email": f"m18-{tag}@example.com",
            "nickname": f"m18-{tag}",
            "password": "pass123456",
        },
    )
    assert r.status_code in (200, 201), r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def league_id(client, auth_headers):
    r = client.post(
        "/api/leagues",
        json={"name": "M18 League"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------
# schema validation: prediction question
# --------------------------------------------------------------------------


@pytest.mark.parametrize("question", ["", "   ", "\t\n  "])
def test_blank_question_rejected(client, auth_headers, league_id, question):
    r = client.post(
        f"/api/leagues/{league_id}/predictions",
        json={"question": question},
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text


def test_question_too_long_rejected(client, auth_headers, league_id):
    r = client.post(
        f"/api/leagues/{league_id}/predictions",
        json={"question": "x" * 501},
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text


def test_valid_question_created(client, auth_headers, league_id):
    r = client.post(
        f"/api/leagues/{league_id}/predictions",
        json={"question": "  Will the Chiefs win?  "},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["question"] == "Will the Chiefs win?"
    assert body["creator_id"] > 0


def test_question_at_max_length_accepted(client, auth_headers, league_id):
    r = client.post(
        f"/api/leagues/{league_id}/predictions",
        json={"question": "y" * 500},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert len(r.json()["question"]) == 500


def test_question_schema_trims_and_rejects():
    assert PredictionCreate(question="  hi  ").question == "hi"
    with pytest.raises(ValueError):
        PredictionCreate(question="   ")
    with pytest.raises(ValueError):
        PredictionCreate(question="x" * 501)


# --------------------------------------------------------------------------
# schema validation: league name
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["", "   ", "\t\n  "])
def test_blank_league_name_rejected(client, auth_headers, name):
    r = client.post(
        "/api/leagues",
        json={"name": name},
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text


def test_league_name_too_long_rejected(client, auth_headers):
    r = client.post(
        "/api/leagues",
        json={"name": "z" * 101},
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text


def test_valid_league_name_created(client, auth_headers):
    r = client.post(
        "/api/leagues",
        json={"name": "  Friday Night League  "},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "Friday Night League"


def test_league_name_schema_trims_and_rejects():
    assert LeagueCreate(name="  hi  ").name == "hi"
    with pytest.raises(ValueError):
        LeagueCreate(name="   ")
    with pytest.raises(ValueError):
        LeagueCreate(name="z" * 101)


# --------------------------------------------------------------------------
# cascade integrity
# --------------------------------------------------------------------------


def test_models_declare_cascade_on_target_fks():
    """The models themselves must declare ON DELETE CASCADE for these FKs."""
    expected = {
        ("memberships", "league_id"),
        ("memberships", "user_id"),
        ("predictions", "league_id"),
        ("picks", "prediction_id"),
        ("picks", "user_id"),
        ("leagues", "owner_id"),
        # added in M20: deleting a user must drop their refresh tokens
        ("refresh_tokens", "user_id"),
    }
    found = set()
    for table in models.Base.metadata.tables.values():
        for column in table.columns:
            for fk in column.foreign_keys:
                if fk.ondelete == "CASCADE":
                    found.add((table.name, column.name))
    assert found == expected


def test_prediction_creator_is_set_null_not_cascade():
    """M25: a prediction outlives the account that made it.

    ON DELETE CASCADE here would take the picks other members made on the
    prediction with it and silently rewrite their points.
    """
    column = models.Base.metadata.tables["predictions"].columns["creator_id"]
    assert column.nullable
    assert [fk.ondelete for fk in column.foreign_keys] == ["SET NULL"]


def _fk_rules(conn, schema, table, column, ref_table):
    rows = conn.execute(
        text(
            """
            SELECT c.conname, c.confdeltype
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace tn ON tn.oid = t.relnamespace
            JOIN pg_class rt ON rt.oid = c.confrelid
            JOIN pg_namespace rn ON rn.oid = rt.relnamespace
            JOIN pg_attribute a
              ON a.attrelid = t.oid AND a.attnum = ANY (c.conkey)
            WHERE c.contype = 'f'
              AND tn.nspname = :schema
              AND t.relname = :table
              AND rn.nspname = :schema
              AND rt.relname = :ref_table
              AND a.attname = :column
              AND array_length(c.conkey, 1) = 1
            """
        ),
        {
            "schema": schema,
            "table": table,
            "column": column,
            "ref_table": ref_table,
        },
    ).all()
    return rows


def _create_legacy_schema(conn, schema):
    """Recreate the pre-M18 schema (FKs without ON DELETE CASCADE).

    The tables are built in a throwaway schema so the shared database is never
    touched.  ``schema_translate_map`` keeps the whole thing compile-time
    only: no server side session state is changed, so nothing leaks into the
    connection pool.

    ``predictions.creator_id`` is put back the way it was before M25 as well:
    NOT NULL, without a delete rule.  M25 (migration 25) is what turns it into
    a nullable column with ON DELETE SET NULL.
    """
    translate = {None: schema}
    conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    for table in models.Base.metadata.sorted_tables:
        ddl = str(
            CreateTable(table).compile(
                dialect=conn.dialect, schema_translate_map=translate
            )
        ).replace(" ON DELETE CASCADE", "").replace(" ON DELETE SET NULL", "")
        conn.execute(text(ddl))
    conn.execute(
        text(
            f'ALTER TABLE "{schema}"."predictions" '
            f'ALTER COLUMN "creator_id" SET NOT NULL'
        )
    )
    conn.commit()


def _translated_engine(schema):
    return engine.execution_options(schema_translate_map={None: schema})


def test_migration_adds_cascade_and_is_idempotent():
    """Runs the real migration against a throwaway schema, twice."""
    _drop_schema(CASCADE_SCHEMA)
    try:
        conn = _translated_engine(CASCADE_SCHEMA).connect()
        try:
            _create_legacy_schema(conn, CASCADE_SCHEMA)

            # pre-state: every target FK exists and is not CASCADE
            for table, column, ref_table, _ in TARGET_FKS:
                rules = _fk_rules(conn, CASCADE_SCHEMA, table, column, ref_table)
                assert len(rules) == 1, (table, column, rules)
                assert rules[0][1] != "c"

            first = migrate_v18_cascades.migrate(schema=CASCADE_SCHEMA)
            assert first["changed"] == len(TARGET_FKS)
            conn.commit()

            # post-state: exactly one constraint per column, all CASCADE
            for table, column, ref_table, _ in TARGET_FKS:
                rules = _fk_rules(conn, CASCADE_SCHEMA, table, column, ref_table)
                assert len(rules) == 1, (table, column, rules)
                assert rules[0][1] == "c", (table, column, rules)

            second = migrate_v18_cascades.migrate(schema=CASCADE_SCHEMA)
            assert second["changed"] == 0
            conn.commit()

            # and still exactly one CASCADE constraint per column
            for table, column, ref_table, _ in TARGET_FKS:
                rules = _fk_rules(conn, CASCADE_SCHEMA, table, column, ref_table)
                assert len(rules) == 1, (table, column, rules)
                assert rules[0][1] == "c", (table, column, rules)
        finally:
            conn.close()
    finally:
        _drop_schema(CASCADE_SCHEMA)


def _drop_schema(schema):
    conn = engine.connect()
    try:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()
    finally:
        conn.close()


def _seed_graph(session):
    user = models.User(
        email=f"{uuid.uuid4().hex[:10]}@example.com",
        nickname=f"m18c-{uuid.uuid4().hex[:8]}",
        password_hash="x",
    )
    session.add(user)
    session.flush()
    league = models.League(
        name="Cascade League",
        invite_code=f"m18c-{uuid.uuid4().hex[:8]}",
        owner_id=user.id,
    )
    session.add(league)
    session.flush()
    session.add(models.Membership(league_id=league.id, user_id=user.id))
    prediction = models.Prediction(
        league_id=league.id, creator_id=user.id, question="Cascade?"
    )
    session.add(prediction)
    session.flush()
    session.add(
        models.Pick(
            prediction_id=prediction.id, user_id=user.id, side="yes", stake=10
        )
    )
    session.commit()
    return user.id, league.id, prediction.id


def test_delete_user_cascades_to_dependents():
    """Deleting a user must remove their league, membership and picks.

    The prediction goes with the league: the user is its only member, so the
    league is deleted with them.  A prediction in somebody else's league is a
    different story and is covered by the M25 tests.
    """
    _drop_schema(CASCADE_SCHEMA)
    try:
        conn = _translated_engine(CASCADE_SCHEMA).connect()
        try:
            _create_legacy_schema(conn, CASCADE_SCHEMA)
            migrate_v18_cascades.migrate(schema=CASCADE_SCHEMA)
            # M25 owns predictions.creator_id now: it is nullable and the
            # foreign key sets it to null instead of cascading.
            migrate_v25_creator_set_null.migrate(schema=CASCADE_SCHEMA)
            conn.commit()

            session = Session(bind=conn)
            try:
                user_id, league_id, prediction_id = _seed_graph(session)
                assert session.query(models.Pick).count() == 1
                assert session.query(models.Prediction).count() == 1
                assert session.query(models.Membership).count() == 1
                assert session.query(models.League).count() == 1
                assert session.query(models.User).count() == 1

                session.delete(session.get(models.User, user_id))
                session.commit()

                assert session.query(models.User).count() == 0
                assert session.query(models.League).count() == 0
                assert session.query(models.Membership).count() == 0
                assert session.query(models.Prediction).count() == 0
                assert session.query(models.Pick).count() == 0
            finally:
                session.close()
        finally:
            conn.close()
    finally:
        _drop_schema(CASCADE_SCHEMA)


def test_delete_league_cascades_to_memberships_and_predictions():
    _drop_schema(CASCADE_SCHEMA)
    try:
        conn = _translated_engine(CASCADE_SCHEMA).connect()
        try:
            _create_legacy_schema(conn, CASCADE_SCHEMA)
            migrate_v18_cascades.migrate(schema=CASCADE_SCHEMA)
            # M25 owns predictions.creator_id now: it is nullable and the
            # foreign key sets it to null instead of cascading.
            migrate_v25_creator_set_null.migrate(schema=CASCADE_SCHEMA)
            conn.commit()

            session = Session(bind=conn)
            try:
                user_id, league_id, prediction_id = _seed_graph(session)

                session.delete(session.get(models.League, league_id))
                session.commit()

                assert session.query(models.League).count() == 0
                assert session.query(models.Membership).count() == 0
                assert session.query(models.Prediction).count() == 0
                assert session.query(models.Pick).count() == 0
                # the user itself is untouched
                assert session.query(models.User).count() == 1
            finally:
                session.close()
        finally:
            conn.close()
    finally:
        _drop_schema(CASCADE_SCHEMA)
