# NextGenAI combined release (local only)

Reference API release: `waha-legacy-sql-fix-20261106T010101Z`.

Reference Celery worker release: `waha-crm-20261021-eBh5lPqc`.

This artifact combines the effective active API code with the active worker's
WAHA audit/retry behavior and adds only these tenant fixes:

- transaction advisory serialization for the `(company_id, WAHA message id)`;
- message lookup/re-read scoped by `company_id`;
- atomic, non-destructive contact upsert on `(client_id, company_id, phone)`;
- contact metadata updates scoped by the full tenant key;
- Board authorization delegated to `ensure_user_can_access_company` for every
  JWT entry point, while its API-key/JWT compatibility route keeps its existing
  authorization dependency;
- regression coverage for shared phone numbers, duplicate WAHA events, and
  Board authorization.

No database migration belongs to this release. Migration `0005` is retained
only because it is already part of the active API history and matches the
existing production constraint `uq_contact_client_company_phone`.

The package must be deployed as one identical source release for API and
worker. Do not use the currently split API/worker paths as a mixed runtime.
