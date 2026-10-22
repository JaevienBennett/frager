"""Milestone 25 migration tests: a prediction outlives the account that made it.

The migration is run against a throwaway schema, so the shared test database is
never touched.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app import models
from app.database import engine
from migrations import migrate_v18_cascades
from migrations import migrate_v25_creator_set_null

SCHEMA = "m25_creator_test"


def _translated_engine(schema):
    return engine.execution_options(schema_translate_map={None: schema})


def _drop_schema(schema):
    conn = engine.connect()
    try:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()
    finally:
        conn.close()


def _create_legacy_schema(conn, schema):
    """The database as it looked before M25.

    ``predictions.creator_id`` is NOT NULL and has no delete rule, so deleting
    the account that made a prediction would fail outright.
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


def _fk_rule(conn, schema, table, column, ref_table):
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


def _is_not_null(conn, schema, table, column):
    return conn.execute(
        text(
            """
            SELECT a.attnotnull
            FROM pg_attribute a
            JOIN pg_class t ON t.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE t.relname = :table
              AND n.nspname = :schema
              AND a.attname = :column
              AND a.attnum > 0
              AND NOT a.attisdropped
            """
        ),
        {"schema": schema, "table": table, "column": column},
    ).scalar()


def _seed_other_league(session):
    """Two users, a league owned by one of them, a prediction by the other."""
    tag = uuid.uuid4().hex[:8]
    owner = models.User(
        email=f"m25o-{tag}@example.com",
        nickname=f"m25o-{tag}",
        password_hash="x",
    )
    creator = models.User(
        email=f"m25c-{tag}@example.com",
        nickname=f"m25c-{tag}",
        password_hash="x",
    )
    session.add_all([owner, creator])
    session.flush()
    league = models.League(
        name="M25 League", invite_code=f"m25-{tag}", owner_id=owner.id
    )
    session.add(league)
    session.flush()
    session.add(models.Membership(league_id=league.id, user_id=owner.id))
    session.add(models.Membership(league_id=league.id, user_id=creator.id))
    prediction = models.Prediction(
        league_id=league.id, creator_id=creator.id, question="Outlive me?"
    )
    session.add(prediction)
    session.flush()
    session.add(
        models.Pick(
            prediction_id=prediction.id, user_id=owner.id, side="yes", stake=7
        )
    )
    session.commit()
    return owner.id, creator.id, league.id, prediction.id


def test_the_migration_makes_the_creator_nullable_and_sets_it_to_null():
    _drop_schema(SCHEMA)
    try:
        conn = _translated_engine(SCHEMA).connect()
        try:
            _create_legacy_schema(conn, SCHEMA)

            # pre-state: not null, and the foreign key has no delete rule
            assert _is_not_null(conn, SCHEMA, "predictions", "creator_id") is True
            rules = _fk_rule(conn, SCHEMA, "predictions", "creator_id", "users")
            assert len(rules) == 1, rules
            assert rules[0][1] != "n", rules

            summary = migrate_v25_creator_set_null.migrate(schema=SCHEMA)
            conn.commit()
            assert summary["changed"] == 2, summary

            # post-state: nullable, and the foreign key nulls the column
            assert _is_not_null(conn, SCHEMA, "predictions", "creator_id") is False
            rules = _fk_rule(conn, SCHEMA, "predictions", "creator_id", "users")
            assert len(rules) == 1, rules
            assert rules[0][1] == "n", rules

            # and running it again changes nothing
            again = migrate_v25_creator_set_null.migrate(schema=SCHEMA)
            conn.commit()
            assert again["changed"] == 0, again
        finally:
            conn.close()
    finally:
        _drop_schema(SCHEMA)


def test_running_the_old_migration_again_does_not_undo_this_one():
    """The M18 migration used to put CASCADE back on this column.

    It must not any more: running it after M25 has to leave the column
    nullable with SET NULL.
    """
    _drop_schema(SCHEMA)
    try:
        conn = _translated_engine(SCHEMA).connect()
        try:
            _create_legacy_schema(conn, SCHEMA)
            migrate_v18_cascades.migrate(schema=SCHEMA)
            migrate_v25_creator_set_null.migrate(schema=SCHEMA)
            conn.commit()

            # the old migration runs again, the way a re-deploy would
            migrate_v18_cascades.migrate(schema=SCHEMA)
            conn.commit()

            rules = _fk_rule(conn, SCHEMA, "predictions", "creator_id", "users")
            assert len(rules) == 1, rules
            assert rules[0][1] == "n", (
                "the M18 migration put the cascade back on predictions.creator_id"
            )
            assert _is_not_null(conn, SCHEMA, "predictions", "creator_id") is False
        finally:
            conn.close()
    finally:
        _drop_schema(SCHEMA)


def test_deleting_the_creator_keeps_the_prediction_and_its_pick():
    _drop_schema(SCHEMA)
    try:
        conn = _translated_engine(SCHEMA).connect()
        try:
            _create_legacy_schema(conn, SCHEMA)
            migrate_v18_cascades.migrate(schema=SCHEMA)
            migrate_v25_creator_set_null.migrate(schema=SCHEMA)
            conn.commit()

            session = Session(bind=conn)
            try:
                owner_id, creator_id, league_id, prediction_id = _seed_other_league(
                    session
                )

                session.delete(session.get(models.User, creator_id))
                session.commit()

                prediction = session.get(models.Prediction, prediction_id)
                assert prediction is not None, "the prediction was deleted"
                assert prediction.creator_id is None
                assert prediction.status == "open"

                picks = (
                    session.query(models.Pick)
                    .filter(models.Pick.prediction_id == prediction_id)
                    .all()
                )
                assert len(picks) == 1, "the pick was deleted with its maker"
                assert picks[0].user_id == owner_id
                assert picks[0].stake == 7

                # the league and its owner are untouched
                assert session.get(models.League, league_id) is not None
                assert session.get(models.User, owner_id) is not None
            finally:
                session.close()
        finally:
            conn.close()
    finally:
        _drop_schema(SCHEMA)
