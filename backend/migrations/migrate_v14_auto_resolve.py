"""
Idempotent migration to add auto-resolution fields to predictions.

Adds nullable columns for sports game linking and auto-resolution metadata,
backfills resolution_source='manual' where NULL.
"""

from __future__ import annotations

import logging
from contextlib import closing

from sqlalchemy import text

from app.database import engine

log = logging.getLogger(__name__)


def migrate() -> None:
    sql_statements = [
        "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS external_game_id TEXT",
        "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS sport TEXT",
        "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS league TEXT",
        "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS home_team TEXT",
        "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS away_team TEXT",
        "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS game_time TIMESTAMPTZ",
        "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS resolution_source TEXT",
        "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS auto_resolved_at TIMESTAMPTZ",
        "UPDATE predictions SET resolution_source = 'manual' WHERE resolution_source IS NULL",
    ]
    with closing(engine.connect()) as conn:
        for stmt in sql_statements:
            conn.execute(text(stmt))
        conn.commit()
    log.info("migrate_v14_auto_resolve: completed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
