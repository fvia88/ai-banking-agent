"""Date daily transfer counters using the Asia/Shanghai calendar."""
from datetime import datetime, timedelta, timezone

from alembic import op
import sqlalchemy as sa

revision = "0004_transfer_day"
down_revision = "0003_subscriptions"
branch_labels = depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = {c["name"]: c for c in sa.inspect(connection).get_columns("accounts")}
    column = columns.get("daily_transfer_date")
    if column is None:
        op.add_column("accounts", sa.Column("daily_transfer_date", sa.Date(), nullable=True))
    elif not isinstance(column["type"], sa.Date) or isinstance(column["type"], sa.DateTime):
        raise RuntimeError("Incompatible accounts.daily_transfer_date; review schema manually")
    # Legacy totals have no trustworthy date. Preserve them conservatively for
    # the upgrade day; they will expire at the next Shanghai day boundary.
    today = datetime.now(timezone(timedelta(hours=8))).date()
    accounts = sa.table("accounts", sa.column("daily_transfer_date", sa.Date()))
    connection.execute(accounts.update().where(accounts.c.daily_transfer_date.is_(None)).values(daily_transfer_date=today))


def downgrade():
    raise RuntimeError("Automatic destructive downgrade is disabled; restore a reviewed backup instead.")
