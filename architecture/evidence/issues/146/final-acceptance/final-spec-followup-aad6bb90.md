# Bounded Spec review: aad6bb90

**PASS — no actionable Spec finding.** Reviewed `096dab57a8593f6df16a2b3e82a382e3d95a9b4f...aad6bb90951120b09771a23f58d5b662713e7a5a` (one commit).

The #146 plan requires a “source-owned reference seam without weakening removal protection.” Cutover now temporarily includes `company_tax_filing_identity_guard_owner` in the migration principal’s membership (`supabase/contract-migrations/20260913172000_company_tax_settlement_cutover.sql:8`). That is the existing owner of `has_document_reference_v1`, so the unchanged grant at line67 can authorize the actual Documents retention function owner. The matching revoke at line185 runs before commit. Failure aborts the same transaction, including the temporary membership. No runtime principal gains this owner role; no table permission, policy, helper body or tenant authorization changes. The intended direct helper EXECUTE grant remains available to Documents after cleanup.

Expansion and both rollback artifacts are byte-identical. The retained boolean reference helper still reads the active physical predecessor during rollback and canonical Tax otherwise; the full rollback restores its narrow document-reference read policy. This correction therefore preserves the existing retention contract across cutover, rollback and recutover rather than weakening removal checks.

The test’s only AST change is revoking three fixture-owner memberships before the phase transition (`apps/backend/tests/test_company_tax_filing_database.py:240`). The restricted Documents execution, exact `documents_evidence_linked` assertion, all three phases and outer transaction rollback remain intact.

Independent isolated static checks passed: exact paired-role-only SQL delta, transaction/order, unchanged rollback/requirements bytes, test AST preservation, both refreshed catalog hashes, **15 committed artifact digests**, **six byte-exact prior Spec adoptions**, and failed096 transcript identity. That transcript honestly records **2 failed/20 passed**, database-isolation exit1 and no exit credit. Adopted red/green logs report three permission failures then three successful retention refusals; the separate lifecycle log records22 passed. These are parent-produced retained-database results, not an independent database rerun.

Limits: this review executed no SQL, browser or shared process. Fresh complete gates, protected integration and full Company Tax/#152 exit are not accepted here. Static checker, output and exact bindings accompany this report.
