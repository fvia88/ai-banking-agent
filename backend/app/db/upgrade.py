# backend/app/db/upgrade.py
"""
Minimal additive schema upgrade for databases created by older builds.

`Base.metadata.create_all` creates missing tables but never adds columns to a
table that already exists. Databases created before the P3 MFA lifecycle
therefore lack action_approvals.mfa_issued_at / mfa_expires_at /
mfa_consumed_at / audit_id, and every approval query fails on them.

This step only ever ADDs nullable columns that the models declare and the
database lacks. It never drops, renames, retypes or rewrites data, and it is
safe to run on every startup. A missing NOT NULL column cannot be added
without a backfill decision, so it is reported instead of guessed.
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from app.db.session import Base


def upgrade_schema(engine: Engine) -> list[str]:
    """Add missing nullable model columns to existing tables. Returns 'table.column' added."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added: list[str] = []
    blocked: list[str] = []

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all creates it with the full current schema
            present = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                if not column.nullable:
                    blocked.append(f"{table.name}.{column.name}")
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))
                added.append(f"{table.name}.{column.name}")

    if blocked:
        raise RuntimeError(
            "Database schema is missing required NOT NULL column(s) "
            f"{', '.join(blocked)}; these need a manual migration with a backfill value. "
            "No data was changed for them."
        )
    return added
