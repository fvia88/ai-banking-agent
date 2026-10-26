"""Persistent user safety locks and a shared verification-failure window."""
from alembic import op
import sqlalchemy as sa

revision = "0006_safety_lock"
down_revision = "0005_agent_continuation"
branch_labels = depends_on = None


def upgrade():
    columns = {c["name"]: c for c in sa.inspect(op.get_bind()).get_columns("users")}
    required = [
        sa.Column("security_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("security_failure_window_at", sa.DateTime(), nullable=True),
        sa.Column("safety_locked_at", sa.DateTime(), nullable=True),
        sa.Column("safety_lock_reason", sa.String(64), nullable=True),
    ]
    for column in required:
        if column.name not in columns:
            op.add_column("users", column)
        else:
            existing = columns[column.name]
            if (not isinstance(existing["type"], type(column.type))
                or existing["nullable"] != column.nullable
                or isinstance(column.type, sa.String) and existing["type"].length != column.type.length):
                raise RuntimeError(f"Incompatible existing users.{column.name}; review schema manually")


def downgrade():
    raise RuntimeError("Automatic destructive downgrade is disabled; restore a reviewed backup instead.")
