"""
Idempotent migration (Milestone 25): a prediction outlives the account that made it.

Deleting an account used to take its predictions with it (ON DELETE CASCADE),
and with them the picks other members had made, so their points and accuracy
silently changed. Two changes here:

1. ``predictions.creator_id`` becomes nullable and its foreign key becomes
   ON DELETE SET NULL: the prediction stays, nobody owns it any more.
2. ``ALTER COLUMN creator_id DROP NOT NULL`` so a null creator is allowed.

The live FK constraint for the column is discovered through
pg_constraint / pg_catalog (no hardcoded constraint names), so this works on
any database whose schema matches the models.

Running it twice is a no-op the second time: a constraint that already has
SET NULL is left untouched, and the column stays nullable.

Usage:
    cd backend
    python -m migrations.migrate_v25_creator_set_null             # public schema
    python -m migrations.migrate_v25_creator_set_null --schema myschema
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
except ModuleNotFoundError:  # running as `python migrations/migrate_v25_creator_set_null.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.database import engine

log = logging.getLogger(__name__)

TABLE = "predictions"
COLUMN = "creator_id"
REF_TABLE = "users"
REF_COLUMN = "id"

DELETE_RULES = {
    "a": "NO ACTION",
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}

FIND_FKS = text(
    """
    SELECT c.conname,
           c.confdeltype,
           c.confupdtype,
           c.condeferrable,
           c.condeferred
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
    ORDER BY c.conname
    """
)

NAME_TAKEN = text(
    """
    SELECT 1
    FROM pg_constraint c
    JOIN pg_namespace n ON n.oid = c.connamespace
    WHERE c.conname = :name AND n.nspname = :schema
    """
)

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
)


def _find_fks(conn, schema):
    rows = conn.execute(
        FIND_FKS,
        {
            "schema": schema,
            "table": TABLE,
            "column": COLUMN,
            "ref_table": REF_TABLE,
        },
    ).mappings().all()
    return [dict(r) for r in rows]


def _unique_name(conn, schema):
    base = f"fk_{TABLE}_{COLUMN}"
    name = base
    suffix = 1
    while conn.execute(NAME_TAKEN, {"name": name, "schema": schema}).first():
        suffix += 1
        name = f"{base}_v{suffix}"
    return name


def migrate(schema: str = "public") -> dict:
    """Make predictions.creator_id nullable with ON DELETE SET NULL.

    Safe to run repeatedly. Returns a summary dict with the per-step outcome
    so callers (and tests) can assert on exactly what changed.
    """
    results = []
    changed = 0

    with closing(engine.connect()) as conn:
        with conn.begin():
            if not conn.execute(
                TABLE_EXISTS, {"table": TABLE, "schema": schema}
            ).first():
                results.append(
                    {
                        "step": "table",
                        "action": "skipped",
                        "reason": f"table {schema}.{TABLE} does not exist",
                    }
                )
                print(f"[skip ] {schema}.{TABLE}: table does not exist")
                return {
                    "schema": schema,
                    "changed": 0,
                    "results": results,
                }

            column = conn.execute(
                COLUMN_EXISTS,
                {"table": TABLE, "schema": schema, "column": COLUMN},
            ).first()
            if column is None:
                results.append(
                    {
                        "step": "column",
                        "action": "skipped",
                        "reason": f"column {schema}.{TABLE}.{COLUMN} does not exist",
                    }
                )
                print(f"[skip ] {schema}.{TABLE}.{COLUMN}: column does not exist")
                return {
                    "schema": schema,
                    "changed": 0,
                    "results": results,
                }

            # 1. The column has to allow a null creator before SET NULL works.
            if column.attnotnull:
                conn.execute(
                    text(
                        f'ALTER TABLE "{schema}"."{TABLE}" '
                        f'ALTER COLUMN "{COLUMN}" DROP NOT NULL'
                    )
                )
                changed += 1
                results.append(
                    {"step": "not-null", "action": "changed", "before": "NOT NULL", "after": "NULL"}
                )
                print(f"[fix  ] {schema}.{TABLE}.{COLUMN}: dropped NOT NULL")
            else:
                results.append(
                    {"step": "not-null", "action": "unchanged", "before": "NULL", "after": "NULL"}
                )
                print(f"[ok   ] {schema}.{TABLE}.{COLUMN}: already nullable")

            # 2. The foreign key has to null the column instead of cascading.
            found = _find_fks(conn, schema)
            set_null_fks = [f for f in found if f["confdeltype"] == "n"]
            wrong_fks = [f for f in found if f["confdeltype"] != "n"]

            if not wrong_fks:
                for f in set_null_fks:
                    results.append(
                        {
                            "step": "foreign-key",
                            "action": "unchanged",
                            "constraint": f["conname"],
                            "before": "SET NULL",
                            "after": "SET NULL",
                        }
                    )
                    print(
                        f"[ok   ] {schema}.{TABLE}.{COLUMN} -> {REF_TABLE}.{REF_COLUMN}: "
                        f"'{f['conname']}' already ON DELETE SET NULL"
                    )
            else:
                # Reuse the name of the first constraint we replace so the
                # change stays as small as possible on the database.
                name = wrong_fks[0]["conname"]
                for f in wrong_fks:
                    before = DELETE_RULES.get(f["confdeltype"], f["confdeltype"])
                    conn.execute(
                        text(
                            f'ALTER TABLE "{schema}"."{TABLE}" DROP CONSTRAINT "{f["conname"]}"'
                        )
                    )
                    print(
                        f"[drop ] {schema}.{TABLE}.{COLUMN} -> {REF_TABLE}.{REF_COLUMN}: "
                        f"dropped '{f['conname']}' (ON DELETE {before})"
                    )
                conn.execute(
                    text(
                        f'ALTER TABLE "{schema}"."{TABLE}" ADD CONSTRAINT "{name}" '
                        f'FOREIGN KEY ("{COLUMN}") REFERENCES "{schema}"."{REF_TABLE}" ("{REF_COLUMN}") '
                        f"ON DELETE SET NULL"
                    )
                )
                changed += 1
                before = DELETE_RULES.get(
                    wrong_fks[0]["confdeltype"], wrong_fks[0]["confdeltype"]
                )
                results.append(
                    {
                        "step": "foreign-key",
                        "action": "changed",
                        "constraint": name,
                        "before": before,
                        "after": "SET NULL",
                    }
                )
                print(
                    f"[fix  ] {schema}.{TABLE}.{COLUMN} -> {REF_TABLE}.{REF_COLUMN}: "
                    f"recreated '{name}' ON DELETE {before} -> ON DELETE SET NULL"
                )

    summary = {
        "schema": schema,
        "changed": changed,
        "results": results,
    }
    print(f"migrate_v25_creator_set_null: {changed} change(s) in schema '{schema}'")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Make predictions.creator_id nullable with ON DELETE SET NULL"
    )
    parser.add_argument(
        "--schema",
        default="public",
        help="PostgreSQL schema holding the tables (default: public)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    migrate(schema=args.schema)
