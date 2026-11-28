"""Persist the next delivery time for approved dry-run actions."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("remediation_actions", sa.Column("dispatch_due_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_actions_dispatch_due", "remediation_actions", ["dispatch_due_at", "id"],
        postgresql_where=sa.text("dispatch_due_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_actions_dispatch_due", table_name="remediation_actions")
    op.drop_column("remediation_actions", "dispatch_due_at")
