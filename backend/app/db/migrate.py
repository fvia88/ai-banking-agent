"""Versioned schema upgrades shared by Docker, local startup and the seed CLI."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db.session import engine

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def upgrade_database(bind=None):
    target = bind if bind is not None else engine
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    with target.begin() as connection:
        if connection.dialect.name == "postgresql":
            # Serialize concurrent startup upgrades, including the version-table creation.
            connection.execute(text("SET LOCAL lock_timeout = '30s'"))
            connection.execute(text("SELECT pg_advisory_xact_lock(726184921)"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    print("Database migrations are up to date.", flush=True)


if __name__ == "__main__":
    upgrade_database()
