"""Alembic configuration; connection credentials come from backend settings."""
from alembic import context
from sqlalchemy import create_engine, pool

from app.config import settings
from app.db.models import Base


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
elif context.is_offline_mode():
    raise RuntimeError("These adoption migrations require an online database connection.")
else:
    engine = create_engine(settings.DATABASE_URL, poolclass=pool.NullPool)
    with engine.connect() as connection:
        run(connection)
    engine.dispose()
