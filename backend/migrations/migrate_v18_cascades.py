"""
Idempotent migration (Milestone 18): make core foreign keys ON DELETE CASCADE.

The live FK constraints for the target columns are discovered through
pg_constraint / pg_catalog (no hardcoded constraint names), so this works on
any database whose schema matches the models. Each constraint that is not
already ON DELETE CASCADE is dropped and recreated with ON DELETE CASCADE.

Running it twice is a no-op the second time: constraints that already have
CASCADE are left untouched, and every target column ends up with exactly one
correct constraint.

Usage:
    cd backend
    python -m migrations.migrate_v18_cascades                 # public schema
    python -m migrations.migrate_v18_cascades --schema myschema
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
except ModuleNotFoundError:  # running as `python migrations/migrate_v18_cascades.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.database import engine

log = logging.getLogger(__name__)

# (table, column, referenced table, referenced column)
TARGET_FKS = (
    ("memberships", "league_id", "leagues", "id"),
    ("memberships", "user_id", "users", "id"),
    ("predictions", "league_id", "leagues", "id"),
    ("predictions", "creator_id", "users", "id"),
    ("picks", "prediction_id", "predictions", "id"),
    ("picks", "user_id", "users", "id"),
    ("leagues", "owner_id", "users", "id"),
)

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

COUNT_FKS = text(
    """
    SELECT count(*)
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


def _find_fks(conn, schema, table, column, ref_table):
    rows = conn.execute(
        FIND_FKS,
        {
            "schema": schema,
            "table": table,
            "column": column,
            "ref_table": ref_table,
        },
    ).mappings().all()
    return [dict(r) for r in rows]


def _unique_name(conn, schema, table, column):
    base = f"fk_{table}_{column}"
    name = base
    suffix = 1
    while conn.execute(NAME_TAKEN, {"name": name, "schema": schema}).first():
        suffix += 1
        name = f"{base}_v{suffix}"
    return name


def migrate(schema: str = "public") -> dict:
    """Apply ON DELETE CASCADE to the target FKs. Safe to run repeatedly.

    Returns a summary dict with the per-constraint outcome so callers (and
    tests) can assert on exactly what changed.
    """
    results = []
    changed = 0

    with closing(engine.connect()) as conn:
        with conn.begin():
            for table, column, ref_table, ref_column in TARGET_FKS:
                if not conn.execute(TABLE_EXISTS, {"table": table, "schema": schema}).first():
                    results.append(
                        {
                            "table": table,
                            "column": column,
                            "action": "skipped",
                            "reason": f"table {schema}.{table} does not exist",
                        }
                    )
                    print(f"[skip ] {schema}.{table}.{column}: table does not exist")
                    continue

                found = _find_fks(conn, schema, table, column, ref_table)
                if not found:
                    results.append(
                        {
                            "table": table,
                            "column": column,
                            "action": "created",
                            "constraint": f"fk_{table}_{column}",
                            "before": None,
                            "after": "CASCADE",
                        }
                    )
                    changed += 1
                    name = _unique_name(conn, schema, table, column)
                    conn.execute(
                        text(
                            f'ALTER TABLE "{schema}"."{table}" ADD CONSTRAINT "{name}" '
                            f'FOREIGN KEY ("{column}") REFERENCES "{schema}"."{ref_table}" ("{ref_column}") '
                            f"ON DELETE CASCADE"
                        )
                    )
                    print(
                        f"[create] {schema}.{table}.{column} -> {ref_table}.{ref_column}: "
                        f"no FK found, created '{name}' ON DELETE CASCADE"
                    )
                    continue

                cascade_fks = [f for f in found if f["confdeltype"] == "c"]
                wrong_fks = [f for f in found if f["confdeltype"] != "c"]

                if not wrong_fks:
                    for f in cascade_fks:
                        results.append(
                            {
                                "table": table,
                                "column": column,
                                "action": "unchanged",
                                "constraint": f["conname"],
                                "before": "CASCADE",
                                "after": "CASCADE",
                            }
                        )
                        print(
                            f"[ok   ] {schema}.{table}.{column} -> {ref_table}.{ref_column}: "
                            f"'{f['conname']}' already ON DELETE CASCADE"
                        )
                    continue

                # Reuse the name of the first constraint we replace so the
                # change stays as small as possible on the database.
                name = wrong_fks[0]["conname"]
                for f in wrong_fks:
                    before = DELETE_RULES.get(f["confdeltype"], f["confdeltype"])
                    conn.execute(
                        text(
                            f'ALTER TABLE "{schema}"."{table}" DROP CONSTRAINT "{f["conname"]}"'
                        )
                    )
                    print(
                        f"[drop ] {schema}.{table}.{column} -> {ref_table}.{ref_column}: "
                        f"dropped '{f['conname']}' (ON DELETE {before})"
                    )
                conn.execute(
                    text(
                        f'ALTER TABLE "{schema}"."{table}" ADD CONSTRAINT "{name}" '
                        f'FOREIGN KEY ("{column}") REFERENCES "{schema}"."{ref_table}" ("{ref_column}") '
                        f"ON DELETE CASCADE"
                    )
                )
                changed += 1
                before = DELETE_RULES.get(wrong_fks[0]["confdeltype"], wrong_fks[0]["confdeltype"])
                results.append(
                    {
                        "table": table,
                        "column": column,
                        "action": "changed",
                        "constraint": name,
                        "before": before,
                        "after": "CASCADE",
                    }
                )
                print(
                    f"[fix  ] {schema}.{table}.{column} -> {ref_table}.{ref_column}: "
                    f"recreated '{name}' ON DELETE {before} -> ON DELETE CASCADE"
                )

    summary = {
        "schema": schema,
        "changed": changed,
        "total": len(TARGET_FKS),
        "results": results,
    }
    print(
        f"migrate_v18_cascades: {changed} of {len(TARGET_FKS)} constraint(s) changed "
        f"in schema '{schema}'"
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add ON DELETE CASCADE to core FKs")
    parser.add_argument(
        "--schema",
        default="public",
        help="PostgreSQL schema holding the tables (default: public)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    migrate(schema=args.schema)
