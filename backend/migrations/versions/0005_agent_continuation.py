"""Persist owner-scoped P1 state and approval/result correlation."""
from alembic import op
import sqlalchemy as sa

revision = "0005_agent_continuation"
down_revision = "0004_transfer_day"
branch_labels = depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = {c["name"]: c for c in sa.inspect(connection).get_columns("action_approvals")}
    for name, kind in (("conversation_id", sa.String(128)),
                       ("continuation_status", sa.String(32)),
                       ("continuation_json", sa.Text())):
        if name not in columns:
            op.add_column("action_approvals", sa.Column(name, kind, nullable=True))
        elif not isinstance(columns[name]["type"], type(kind)):
            raise RuntimeError(f"Incompatible action_approvals.{name}; review schema manually")
    if "agent_conversations" not in sa.inspect(connection).get_table_names():
        op.create_table("agent_conversations",
                        sa.Column("user_id", sa.String(64), primary_key=True),
                        sa.Column("conversation_id", sa.String(128), primary_key=True),
                        sa.Column("state_json", sa.Text(), nullable=False))


def downgrade():
    raise RuntimeError("Automatic destructive downgrade is disabled; restore a reviewed backup instead.")
