"""Create the original schema or adopt tables previously made by create_all.

Definitions are frozen here, deliberately independent of future ORM changes.
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_legacy_schema"
down_revision = None
branch_labels = depends_on = None


def legacy_metadata():
    m = sa.MetaData()
    sa.Table("users", m,
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("is_locked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    sa.Table("accounts", m,
        sa.Column("account_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("account_number", sa.String(32), unique=True, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("daily_transfer_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    sa.Table("transactions", m,
        sa.Column("transaction_id", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.String(64), sa.ForeignKey("accounts.account_id"), nullable=False),
        sa.Column("timestamp", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("merchant", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=False))
    sa.Table("audit_logs", m,
        sa.Column("audit_id", sa.String(64), primary_key=True),
        sa.Column("action_id", sa.String(64)),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("payload_digest", sa.String(128), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    sa.Table("action_approvals", m,
        sa.Column("action_id", sa.String(64), primary_key=True),
        sa.Column("proposal_id", sa.String(64)),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("action_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("verification_code", sa.String(16)),
        sa.Column("failed_attempts", sa.Numeric(2, 0), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False))
    return m


def upgrade():
    connection = op.get_bind()
    metadata = legacy_metadata()
    # Fail clearly on unsupported older schemas instead of silently stamping them.
    inspector = sa.inspect(connection)
    for table in metadata.sorted_tables:
        if inspector.has_table(table.name):
            actual = {c["name"] for c in inspector.get_columns(table.name)}
            missing = set(table.columns.keys()) - actual
            if missing:
                raise RuntimeError(f"Unsupported legacy table {table.name}: missing {sorted(missing)}")
    metadata.create_all(connection, checkfirst=True)


def downgrade():
    raise RuntimeError("Automatic destructive downgrade is disabled; restore a reviewed backup instead.")
