"""Add users.nickname (Milestone 7), idempotent.

users already exists, so create_tables.py will not add the column. Order
matters: add nullable column, backfill existing rows, then enforce
NOT NULL + unique index so old rows can't fail the constraints.
"""

from sqlalchemy import text

from app.database import engine

with engine.begin() as conn:
    cols = {
        row[0]: row[1]
        for row in conn.execute(
            text(
                "select column_name, is_nullable from information_schema.columns "
                "where table_name = 'users'"
            )
        )
    }

    if "nickname" not in cols:
        conn.execute(text("alter table users add column nickname varchar(24)"))
        print("added users.nickname (nullable)")
        cols["nickname"] = "YES"

    taken = {
        row[0]
        for row in conn.execute(text("select nickname from users where nickname is not null"))
    }
    rows = conn.execute(
        text("select id, email, nickname from users order by id")
    ).fetchall()
    for user_id, email, nickname in rows:
        if nickname is not None and nickname != "":
            continue
        base = (email.split("@")[0] or f"user-{user_id}")[:24]
        candidate = base
        while candidate in taken:
            suffix = f"-{user_id}"
            candidate = (base[: 24 - len(suffix)] + suffix)[:24]
        conn.execute(
            text("update users set nickname = :n where id = :id"),
            {"n": candidate, "id": user_id},
        )
        taken.add(candidate)
        print(f"backfilled user {user_id} -> {candidate}")

    if cols.get("nickname") == "YES":
        conn.execute(text("alter table users alter column nickname set not null"))
        print("set users.nickname NOT NULL")

    index_exists = conn.execute(
        text(
            "select 1 from pg_indexes where tablename = 'users' "
            "and indexname = 'ix_users_nickname'"
        )
    ).first()
    if index_exists is None:
        conn.execute(text("create unique index ix_users_nickname on users (nickname)"))
        print("created unique index ix_users_nickname")
    else:
        print("index ix_users_nickname already exists")

print("users.nickname migration done")
