"""Scope contact identity to client, company and phone.

Revision ID: 0005_contacts_company_identity
Revises: 0004_contacts_waha_fields
"""
from alembic import op

revision = "0005_contacts_company_identity"
down_revision = "0004_contacts_waha_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM contacts WHERE company_id IS NULL LIMIT 1) THEN
        RAISE EXCEPTION 'contacts without company require remediation';
      END IF;
    END $$""")
    op.alter_column("contacts", "company_id", nullable=False)
    op.drop_constraint("uq_contact_client_phone", "contacts", type_="unique")
    op.create_unique_constraint("uq_contact_client_company_phone", "contacts", ["client_id", "company_id", "phone"])


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM contacts GROUP BY client_id, phone HAVING count(*) > 1 LIMIT 1) THEN
        RAISE EXCEPTION 'cross-company contacts conflict with former uniqueness; preserve data before rollback';
      END IF;
    END $$""")
    op.drop_constraint("uq_contact_client_company_phone", "contacts", type_="unique")
    op.create_unique_constraint("uq_contact_client_phone", "contacts", ["client_id", "phone"])
