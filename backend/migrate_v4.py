"""Add resolved_outcome and resolved_at to predictions (Milestone 4).

create_tables.py only creates missing tables, so existing databases need
these columns added by hand. Idempotent: safe to run more than once.
"""

from sqlalchemy import text

from app.database import engine

with engine.begin() as conn:
    existing = {
        row[0]
        for row in conn.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_name = 'predictions'"
            )
        )
    }
    if "resolved_outcome" not in existing:
        conn.execute(text("alter table predictions add column resolved_outcome varchar(8)"))
        print("added predictions.resolved_outcome")
    else:
        print("predictions.resolved_outcome already exists")
    if "resolved_at" not in existing:
        conn.execute(
            text("alter table predictions add column resolved_at timestamptz")
        )
        print("added predictions.resolved_at")
    else:
        print("predictions.resolved_at already exists")
