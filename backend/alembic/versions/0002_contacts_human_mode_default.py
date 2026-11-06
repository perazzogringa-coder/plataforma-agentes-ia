"""Set a server default for human mode without changing existing contacts.

Revision ID: 0002_contacts_human_mode_default
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_contacts_human_mode_default"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "contacts", "human_mode", existing_type=sa.Boolean(),
        existing_nullable=False, server_default=sa.false(),
    )


def downgrade() -> None:
    op.alter_column(
        "contacts", "human_mode", existing_type=sa.Boolean(),
        existing_nullable=False, server_default=None,
    )
