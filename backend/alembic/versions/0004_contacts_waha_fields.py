"""Add contact fields used by WAHA; preserve existing uniqueness.

Revision ID: 0004_contacts_waha_fields
Revises: 0003_webhook_audit
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_contacts_waha_fields"
down_revision = "0003_webhook_audit"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("contacts", sa.Column("last_message_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("contacts", sa.Column("sender_lid", sa.String(255), nullable=True))
    op.add_column("contacts", sa.Column("source_id", sa.String(255), nullable=True))
    op.add_column("contacts", sa.Column("thumbnail_url", sa.Text(), nullable=True))
    op.add_column("contacts", sa.Column("unread_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    # New data must not be silently removed during rollback.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM contacts WHERE last_message_at IS NOT NULL
        OR sender_lid IS NOT NULL OR source_id IS NOT NULL
        OR thumbnail_url IS NOT NULL OR unread_count <> 0 LIMIT 1) THEN
        RAISE EXCEPTION 'contact WAHA fields contain data; preserve data before rollback';
      END IF;
    END $$""")
    for name in ("unread_count", "thumbnail_url", "source_id", "sender_lid", "last_message_at"):
        op.drop_column("contacts", name)
