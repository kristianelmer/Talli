# #151 RF SQL/access working-tree review

Read-only review against original `91b178c281bcc5fb887a6257d2f72e380199f3e6`. This is a source snapshot while B is editing, not an immutable verdict or a database execution attestation. No database, provider, or hosted calls; no checkout edits. Public/pure RF contracts that I authored are excluded from independent certification.

## Concrete findings sent to root and B

1. **Reviewer comment creation is blocked by the preview lock.** Capability SQL `add_review_comment_v1` (lines 895–904; locked read at 898) executes `SELECT … FOR UPDATE` as `shareholder_register_filing_store_owner`. The preview UPDATE policy for that role is owner-only `rf151_owner_write` (591–593); the member lock policy (2027) applies only to the executor, not the SECURITY DEFINER owner. The later reviewer authorization and comment policy cannot restore the row hidden by this locked read. Original `actions.ts` at91b,1681–1733 uses an ordinary preview SELECT; original workspace SQL1790–1801 explicitly admits owner/reviewer comment INSERT. Preserve that permission and prove actual reviewer creation, read-only denial, and no direct preview mutation. Runtime confirmation requested from B; no DB was used by this reviewer.

2. **Opened support cases lose current RF permission/test evidence after contract.** `company_access_read_support_case` still obtains `authority_permissions` and `authority_test_runs` solely from public tables (capability2298–2312). Contract65–73 removes the canonical→public preparation projection. Canonical permission/test commands then update only the RF tables, so the support result remains stale. `read_support_filing_history_v1` (2139–2186) adds only the four production arrays. Preserve original generic sibling queries and merge an RF-owned authority-scope projection, deduplicating overlap identities; test new evidence after contract and wrong/missing/revoked scope. This preserves the original case-bound read contract and does not authorize deleting pending mixed queries.

3. **Quarantine classification is not transitive through a quarantined preview.** The classifier (167–183) checks a child's original preview's label/company/year, but not that preview's own setup provenance. A predecessor-valid preview P(company A) pointing to setup B is quarantined, while review comment C(company A,preview P) is still classified RF and copied. Adding its canonical preview FK (406) then aborts expand because P was excluded. Overrides/submissions have analogous parent dependencies. Classify the exact dependent rows as quarantined, preserving bytes/identities, before FK installation; demonstrate the minimal P/C fixture and no effects on valid sibling rows. This is distinct from the separately tracked zero-holder opening omission.

## Other bounded checks

Verified actor/session installation uses the verified Supabase identity and claims, a restricted executor and transaction-local settings. Canonical business tables use FORCE RLS; ordinary authenticated/service roles do not acquire the new writers; private insert primitive is not executable by runtime. Member history policies remain broader than owner mutation policies. The current owner-only feedback-artifact policy matches original `20260716155621_rf1086_feedback_reconciliation.sql:154–163`; it is not a new finding. Support production/documents projections retain case-bound RLS. SQL/application production operations retain request-first/pilot-second authorization locking and separate provider I/O. Source snapshot uses repeatable read and binds full retained event-row digests.

The existing zero-holder quarantine issue is being corrected independently; I did not duplicate it. Final lifecycle execution, rollback/recutover, dependent-row quarantine coverage, browser proof and complete gates remain outstanding evidence, not assumed passes. No additional actionable issue was identified in the bounded reviewed adapter/access paths.

## Inspected snapshot hashes

- `apps/backend/src/talli_backend/adapters/postgres_shareholder_register_filing.py`: `fb31d10dca2e2e3c8053edaa245a08619854b8fb6d7b2142d9622619242e4e79`
- `supabase/migrations/20260909190548_shareholder_register_filing_capability.sql`: `b74c9906da6544e3d0c9c8b69f1d410b5f11e5de5cdef8ad8fbfee674363cd3f`
- `supabase/migrations/20260909190905_shareholder_register_filing_cutover.sql`: `4b88c63a76f133f743eb63254eef0d8300defb5f6d31934b9a7a10c1593cc109`
- `supabase/contract-migrations/20260909190955_shareholder_register_filing_contract.sql`: `af98f4f4387acf192825cba6cd28a50d0b97cd59cad4eceefef3fa24d8481a23`

Exact inspected copies are in `/tmp/talli-151-sql-review-snapshot/`. Sources: #151 A2–A6 and lifecycle evidence envelope; ADR0010 behavior preservation, ADR0011 owner/public contract boundaries, ADR0013 verified/RLS migration requirements; original91b SQL/actions quoted above.
