"""Link CRM leads to live-chat contacts without altering legacy records.

Revision ID: 0007_lead_contact_identity
Revises: 0006_contact_assignee
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_lead_contact_identity"
down_revision = "0006_contact_assignee"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("leads", sa.Column("contact_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_leads_contact",
        "leads",
        "contacts",
        ["contact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # A contact can have one active CRM card per company.  NULL legacy rows are
    # intentionally excluded so no historical lead is rewritten or rejected.
    op.create_index(
        "uq_leads_company_contact",
        "leads",
        ["company_id", "contact_id"],
        unique=True,
        postgresql_where=sa.text("contact_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_leads_company_contact", table_name="leads")
    op.drop_constraint("fk_leads_contact", "leads", type_="foreignkey")
    op.drop_column("leads", "contact_id")
