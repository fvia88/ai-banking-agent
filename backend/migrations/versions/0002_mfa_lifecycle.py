"""Add nullable MFA lifecycle and audit linkage, accepting the manual SQL repair."""
from alembic import op
import sqlalchemy as sa

revision = "0002_mfa_lifecycle"
down_revision = "0001_legacy_schema"
branch_labels = depends_on = None


def upgrade():
    columns = {c["name"]: c for c in sa.inspect(op.get_bind()).get_columns("action_approvals")}
    required = {
        "mfa_issued_at": sa.DateTime(),
        "mfa_expires_at": sa.DateTime(),
        "mfa_consumed_at": sa.DateTime(),
        "audit_id": sa.String(64),
    }
    for name, datatype in required.items():
        if name not in columns:
            op.add_column("action_approvals", sa.Column(name, datatype, nullable=True))
        else:
            existing = columns[name]
            actual = existing["type"]
            compatible = (
                isinstance(actual, sa.DateTime) and not actual.timezone
                if isinstance(datatype, sa.DateTime)
                else isinstance(actual, sa.String) and actual.length == 64
            )
            if not compatible or not existing["nullable"]:
                raise RuntimeError(f"Incompatible existing action_approvals.{name}; review schema manually")


def downgrade():
    raise RuntimeError("Automatic destructive downgrade is disabled; restore a reviewed backup instead.")
