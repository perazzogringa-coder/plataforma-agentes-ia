"""Add the durable live-chat owner.

Revision ID: 0002_contact_assignee
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_contact_assignee"
down_revision = "0001"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("contacts", sa.Column("assigned_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_contacts_assigned_user", "contacts", "users", ["assigned_user_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_contacts_assigned_user_id", "contacts", ["assigned_user_id"])

def downgrade():
    op.drop_index("ix_contacts_assigned_user_id", table_name="contacts")
    op.drop_constraint("fk_contacts_assigned_user", "contacts", type_="foreignkey")
    op.drop_column("contacts", "assigned_user_id")
