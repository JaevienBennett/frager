"""
Idempotent migration (Milestone 20): rotating refresh tokens + token versions.

Adds:
  * ``users.token_version``  -- bumped to invalidate outstanding access tokens.
  * ``refresh_tokens``        -- one row per issued refresh token, storing only
                                the SHA-256 hash of the token. ``revoked_reason``
                                separates deliberate logout from rotation/theft.

Every statement is guarded (ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT
EXISTS / CREATE INDEX IF NOT EXISTS), so running it twice is a no-op the second
time. The DDL is schema qualified, so it can be pointed at a throwaway schema.

Usage:
    cd backend
    python -m migrations.migrate_v20_sessions                 # public schema
    python -m migrations.migrate_v20_sessions --schema myschema
"""

from __future__ import annotations

import argparse
import logging
import sys
from contextlib import closing
from pathlib import Path

from sqlalchemy import text

try:
    from app.database import engine
except ModuleNotFoundError:  # running as `python migrations/migrate_v20_sessions.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.database import engine

log = logging.getLogger(__name__)

TABLE_EXISTS = text(
    """
    SELECT 1
    FROM pg_class t
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE t.relname = :table AND n.nspname = :schema
    """
)

COLUMN_EXISTS = text(
    """
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = :schema AND table_name = :table AND column_name = :column
    """
)

INDEX_EXISTS = text(
    """
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = :schema AND tablename = :table AND indexname = :index
    """
)

ADD_TOKEN_VERSION = """
ALTER TABLE "{schema}"."users"
ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0
"""

CREATE_REFRESH_TOKENS = """
CREATE TABLE IF NOT EXISTS "{schema}"."refresh_tokens" (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "{schema}"."users" ("id") ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    revoked_reason VARCHAR(16),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
)
"""

ADD_REVOKED_REASON = """
ALTER TABLE "{schema}"."refresh_tokens"
ADD COLUMN IF NOT EXISTS revoked_reason VARCHAR(16)
"""

CREATE_TOKEN_HASH_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS "ix_refresh_tokens_token_hash"
ON "{schema}"."refresh_tokens" ("token_hash")
"""

CREATE_USER_ID_INDEX = """
CREATE INDEX IF NOT EXISTS "ix_refresh_tokens_user_id"
ON "{schema}"."refresh_tokens" ("user_id")
"""

FIND_USER_FK = text(
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
      AND t.relname = 'refresh_tokens'
      AND rn.nspname = :schema
      AND rt.relname = 'users'
      AND a.attname = 'user_id'
      AND array_length(c.conkey, 1) = 1
    """
)


def migrate(schema: str = "public") -> dict:
    """Add the session tables/columns. Safe to run repeatedly.

    Returns a summary dict with the per-step outcome so callers (and tests)
    can assert on exactly what changed.
    """
    results = []
    changed = 0

    with closing(engine.connect()) as conn:
        with conn.begin():
            users_exists = conn.execute(
                TABLE_EXISTS, {"table": "users", "schema": schema}
            ).first()
            if not users_exists:
                results.append(
                    {
                        "step": "all",
                        "action": "skipped",
                        "reason": f"table {schema}.users does not exist",
                    }
                )
                print(f"[skip ] {schema}: table users does not exist")
                return {
                    "schema": schema,
                    "changed": 0,
                    "total": 6,
                    "results": results,
                }

            # 1. users.token_version
            if conn.execute(
                COLUMN_EXISTS,
                {"schema": schema, "table": "users", "column": "token_version"},
            ).first():
                results.append(
                    {
                        "step": "users.token_version",
                        "action": "unchanged",
                    }
                )
                print(f"[ok   ] {schema}.users.token_version: already present")
            else:
                conn.execute(text(ADD_TOKEN_VERSION.format(schema=schema)))
                changed += 1
                results.append(
                    {
                        "step": "users.token_version",
                        "action": "created",
                    }
                )
                print(
                    f"[create] {schema}.users.token_version: added INTEGER NOT NULL DEFAULT 0"
                )

            # 2. refresh_tokens table
            if conn.execute(
                TABLE_EXISTS, {"table": "refresh_tokens", "schema": schema}
            ).first():
                results.append(
                    {
                        "step": "refresh_tokens",
                        "action": "unchanged",
                    }
                )
                print(f"[ok   ] {schema}.refresh_tokens: table already present")
            else:
                conn.execute(text(CREATE_REFRESH_TOKENS.format(schema=schema)))
                changed += 1
                results.append(
                    {
                        "step": "refresh_tokens",
                        "action": "created",
                    }
                )
                print(
                    f"[create] {schema}.refresh_tokens: table created "
                    "(user_id FK ON DELETE CASCADE)"
                )

            # 3. refresh_tokens.revoked_reason (added after the table shipped)
            if conn.execute(
                COLUMN_EXISTS,
                {
                    "schema": schema,
                    "table": "refresh_tokens",
                    "column": "revoked_reason",
                },
            ).first():
                results.append(
                    {
                        "step": "refresh_tokens.revoked_reason",
                        "action": "unchanged",
                    }
                )
                print(
                    f"[ok   ] {schema}.refresh_tokens.revoked_reason: already present"
                )
            else:
                conn.execute(text(ADD_REVOKED_REASON.format(schema=schema)))
                changed += 1
                results.append(
                    {
                        "step": "refresh_tokens.revoked_reason",
                        "action": "created",
                    }
                )
                print(
                    f"[create] {schema}.refresh_tokens.revoked_reason: "
                    "added VARCHAR(16)"
                )

            # 4. unique index on token_hash
            if conn.execute(
                INDEX_EXISTS,
                {
                    "schema": schema,
                    "table": "refresh_tokens",
                    "index": "ix_refresh_tokens_token_hash",
                },
            ).first():
                results.append(
                    {
                        "step": "ix_refresh_tokens_token_hash",
                        "action": "unchanged",
                    }
                )
                print(f"[ok   ] {schema}.ix_refresh_tokens_token_hash: already present")
            else:
                conn.execute(text(CREATE_TOKEN_HASH_INDEX.format(schema=schema)))
                changed += 1
                results.append(
                    {
                        "step": "ix_refresh_tokens_token_hash",
                        "action": "created",
                    }
                )
                print(
                    f"[create] {schema}.ix_refresh_tokens_token_hash: unique index created"
                )

            # 5. index on user_id
            if conn.execute(
                INDEX_EXISTS,
                {
                    "schema": schema,
                    "table": "refresh_tokens",
                    "index": "ix_refresh_tokens_user_id",
                },
            ).first():
                results.append(
                    {
                        "step": "ix_refresh_tokens_user_id",
                        "action": "unchanged",
                    }
                )
                print(f"[ok   ] {schema}.ix_refresh_tokens_user_id: already present")
            else:
                conn.execute(text(CREATE_USER_ID_INDEX.format(schema=schema)))
                changed += 1
                results.append(
                    {
                        "step": "ix_refresh_tokens_user_id",
                        "action": "created",
                    }
                )
                print(f"[create] {schema}.ix_refresh_tokens_user_id: index created")

            # 6. the user_id FK must cascade, so deleting a user drops their
            #    refresh tokens. A table created elsewhere may not have it.
            fks = conn.execute(FIND_USER_FK, {"schema": schema}).mappings().all()
            if len(fks) == 1 and fks[0]["confdeltype"] == "c":
                results.append(
                    {
                        "step": "refresh_tokens.user_id_fkey",
                        "action": "unchanged",
                    }
                )
                print(
                    f"[ok   ] {schema}.refresh_tokens.user_id: "
                    f"'{fks[0]['conname']}' already ON DELETE CASCADE"
                )
            else:
                for fk in fks:
                    conn.execute(
                        text(
                            f'ALTER TABLE "{schema}"."refresh_tokens" '
                            f'DROP CONSTRAINT "{fk["conname"]}"'
                        )
                    )
                    print(
                        f"[drop ] {schema}.refresh_tokens.user_id: "
                        f"dropped '{fk['conname']}'"
                    )
                conn.execute(
                    text(
                        f'ALTER TABLE "{schema}"."refresh_tokens" '
                        f'ADD CONSTRAINT "fk_refresh_tokens_user_id" '
                        f'FOREIGN KEY ("user_id") REFERENCES "{schema}"."users" ("id") '
                        f"ON DELETE CASCADE"
                    )
                )
                changed += 1
                results.append(
                    {
                        "step": "refresh_tokens.user_id_fkey",
                        "action": "created",
                    }
                )
                print(
                    f"[create] {schema}.refresh_tokens.user_id: "
                    f"recreated FK ON DELETE CASCADE"
                )

    summary = {
        "schema": schema,
        "changed": changed,
        "total": 6,
        "results": results,
    }
    print(
        f"migrate_v20_sessions: {changed} change(s) applied in schema '{schema}'"
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Add refresh token storage and access token versioning"
    )
    parser.add_argument(
        "--schema",
        default="public",
        help="PostgreSQL schema holding the tables (default: public)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    migrate(schema=args.schema)
