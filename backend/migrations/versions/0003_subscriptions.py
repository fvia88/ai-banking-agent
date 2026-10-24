"""Store verified, account-scoped subscription state independently of detection."""
from alembic import op
import sqlalchemy as sa

revision = "0003_subscriptions"
down_revision = "0002_mfa_lifecycle"
branch_labels = depends_on = None


def upgrade():
    # Accept installations created by current ORM metadata without version tracking.
    connection = op.get_bind()
    if sa.inspect(connection).has_table("subscriptions"):
        columns = {c["name"] for c in sa.inspect(connection).get_columns("subscriptions")}
        expected = {"subscription_id", "user_id", "account_id", "merchant", "estimated_amount",
                    "cadence", "status", "cancellation_supported", "cancelled_at"}
        if columns != expected:
            raise RuntimeError("Incompatible existing subscriptions table; review schema manually")
        return
    op.create_table("subscriptions",
        sa.Column("subscription_id", sa.String(128), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("account_id", sa.String(64), sa.ForeignKey("accounts.account_id"), nullable=False),
        sa.Column("merchant", sa.String(128), nullable=False),
        sa.Column("estimated_amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("cadence", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("cancellation_supported", sa.Boolean(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True))


def downgrade():
    raise RuntimeError("Automatic destructive downgrade is disabled; restore a reviewed backup instead.")
