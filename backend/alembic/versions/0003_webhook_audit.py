"""Create the audit table required by the webhook consumers.

Revision ID: 0003_webhook_audit
Revises: 0002_contacts_human_mode_default
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_webhook_audit"
down_revision = "0002_contacts_human_mode_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_audit",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("instance_id", sa.Text(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("message_type", sa.Text(), nullable=True),
        sa.Column("message_data", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("processing_status", sa.Text(), nullable=True),
        sa.Column("task_id", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_webhook_audit_dedupe", "webhook_audit", ["company_id", "message_id", "message_type", "created_at"])
    op.create_index("ix_webhook_audit_created_at", "webhook_audit", ["created_at"])


def downgrade() -> None:
    # Audit data and deduplication history must never be dropped silently.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM webhook_audit LIMIT 1) THEN
            RAISE EXCEPTION 'webhook_audit is not empty; preserve audit data before rollback';
        END IF;
    END $$""")
    op.drop_index("ix_webhook_audit_created_at", table_name="webhook_audit")
    op.drop_index("ix_webhook_audit_dedupe", table_name="webhook_audit")
    op.drop_table("webhook_audit")
