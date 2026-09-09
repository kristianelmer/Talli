# Retained workspace / final Ledger topology investigation

Read-only at HEAD `7730bd3473943f5308136207b2acce4f720c851c`. No database or source changes.

## Conclusion

This is an expected predecessor-topology mismatch, not a newly missing Ledger table. The retained workspace was historically an overlap consumer. Preserve its nine original Ledger calls by running it at **RF canonical_overlap + Ledger ordinary overlap**; run contracted RF database/browser proof afterward. Do not recreate an ad hoc public Ledger facade or restore authenticated foreign-table grants in the final schema.

Exact evidence:

- Pinned #150 main `91b178c281bcc5fb887a6257d2f72e380199f3e6:scripts/test-supabase-local.sh`, unchanged current lines 103–119: `test:supabase` and predecessor owner browser precede `test:ledger-hosted-migration-authority`.
- `scripts/prepare-isolated-supabase-workdir.mjs` copies the repository Supabase directory; Supabase ordinary migrations do not apply contract-migrations automatically.
- `tests/ledger_database_runtime.test.mjs` creates its own Docker test database; the earlier Ledger lifecycle lane does not contract the shared Supabase fixture.
- `tests/ledger_hosted_migration_authority.test.mjs:316–352` explicitly applies Ledger contract, rollback, complete expansion/additive recutover, then contract to the shared fixture. Its canonical exact recutover file inventory is lines 7–35.
- Ledger contract `supabase/contract-migrations/20260827101000_ledger_capability_contract.sql:114–143,178 onward` removes `public.ledger_entries`, `public.period_locks`, old grants/policies, then retires `ledger.entries.setup_id`. RF contract `20260909190955:202–215` requires that retired column absent before dropping old opening tables. Therefore those final contracts cannot coexist with unchanged successful legacy Ledger inserts/reads.
- Retained `.from("ledger_entries")` calls are at current lines 945, 1927, 2255, 2297, 2329, 2348, 2434, 2444, 2504. They include real admin-cost/tax/manual writes, denial/locked-period assertions and archive history, not merely obsolete table-existence checks.

## Smallest valid rehearsal phase

Fresh fixture: retain ordinary Ledger expansion. With required #150 Authority seams present, apply RF expand `20260909190548` and cutover `20260909190905`; do not yet apply RF contract. Run retained workspace/current RF API in this declared canonical-overlap phase. Later restore predecessors as needed for the existing Ledger hosted authority/Billing rehearsals, then apply their shipped final recutovers and RF expand/cutover/contract for final-schema proof. Existing complete-lane choreography needs an explicit RF rollback before the #150 helper and explicit RF recutover around current RF consumers; that helper currently only knows #150 files.

For C's already contracted disposable fixture, the documented reconstruction route is: RF full rollback `supabase/rollback/20260909190548_shareholder_register_filing_capability.sql`; Ledger rollback `supabase/rollback/20260827101000_ledger_capability_contract.sql`; Ledger expand/coordinators plus exactly the recutoverMigrations inventory from the hosted-authority test, stopping before Ledger contract; then RF expand/cutover, stopping before RF contract. Keep other capability topology explicit; do not run partial hand-written SQL to emulate the old view. A fresh ordinary-migration fixture may be simpler than repairing uncertain previously contracted sibling state.

One concrete fixture prerequisite: `tests/support/rf1086-workspace-api.mjs:97–109` seeds historical RF opening rows while `rfFixtureTransaction` disables their projection triggers. In canonical overlap this leaves no matching public opening/shareholder rows. Seed matching historical public projections within the same bounded fixture transaction (same IDs, company/year, creator/time, bank value and shareholders), or seed originals before RF expansion. This affects synthetic history setup only; runtime writers stay phase-controlled. Include exact opening tables in the helper's finite fixture inventory if that approach is used. Otherwise later frozen sibling setup_id FKs can fail.

The final API can mechanically replace the nine calls using existing Ledger public methods, but that is a separate fixture modernization requiring preserved output/tenant/period assertions; it is not necessary to rescue this retained overlap test. No new domain policy or architecture amendment is needed for the established overlap rehearsal. Billing company-cascade DELETE restoration is a separate test janitor concern already assigned to B/C.

## Preferred bounded reset for the existing owned fixture

Parent explicitly identified C's fixture as disposable, with no other user data and final-schema evidence already captured. Prefer resetting that known-owned local stack from current ordinary migrations rather than untangling a partially contracted sibling topology. Preserve its project ID, port assignments and config. Compare the private `supabase/migrations` directory's basenames and SHA-256 values to the current checkout; update only those ordinary SQL files and remove only verified stale copies. C may then perform the intentional local reset. Do not silently apply either Ledger or RF contract during this setup. RF expand and cutover permit the ordinary Ledger overlap; only final RF contract requires the retired Ledger setup column. The already-captured 20 schema/feedback + 1 hydrated authority cases remain historical evidence of their recorded final state, and later final-contract proof must be recorded separately. This review did not execute a reset or inspect credentials.
