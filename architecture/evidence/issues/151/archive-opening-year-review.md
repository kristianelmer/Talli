# Confirmed archive opening-year regression and bounded receiver seam

Working-tree read-only review against original91b178c2. No source edits, database/provider calls or suites were run. This is a source-verified call-chain regression; database reproduction remains B's task.

## Confirmation

Current archive `loadArchiveOpeningSnapshots` calls `loadOpeningSnapshots(token,[companyId])`, then filters the fully loaded/presented result by incomeYear. The transport retrieves every page and validates every snapshot. Backend `read_new_year_opening_snapshots_v1` materializes RF opening reads with `income_year=NULL` for the selected company; `read_opening_snapshots_v1` invokes `assert_opening_read_integrity_v1(company,NULL)` before returning rows. Any quarantined holder attached to any company opening therefore raises `ledger_dependency_unavailable` before the archive's requested-year filter can run. Invalid bank/opening composition in another returned year likewise fails all-year validation.

Original91b archive lines313–316 queried opening_balance_setups with both company and incomeYear; lines360–365 queried shareholders only for those selected setup IDs. A conflict in2024 was outside the2025 request. The new all-year failure domain is an introduced receiver regression, not a reason to relax validation.

## Smallest additive contract

Keep current `GET /api/v1/ledger/opening-snapshots`, operationId `ledgerListOpeningSnapshots`, parameters/cursors/ordering/member filtering, and its all-year semantics unchanged.

Add one read for a single company and required income year. Suggested names (root may align to current naming):

- `GET /api/v1/ledger/opening-snapshots/by-year?companyId=<uuid>&incomeYear=<year>`, operationId `ledgerReadOpeningSnapshotsForYear`.
- Application/session port `read_opening_snapshots_for_year(*, actor_id: ActorId, company_id: CompanyId, income_year: IncomeYear, correlation_id: CorrelationId) -> OpeningSnapshotPage`.
- SQL application composition `backend_system.read_new_year_opening_snapshots_for_year_v1(p_company_id uuid,p_income_year integer,p_verified_subject text)` under the existing ledger_workflow owner/executor authority; revoke ordinary Data API execution exactly like the existing read.
- Reuse `OpeningSnapshotView`, `OpeningShareholderView`, `LedgerOpeningSnapshotPageWire` and the existing Decimal-backed parser/presentation. Existing uniqueness `(company_id,income_year)` means at most one item, `nextCursor=null`, `hasMore=false`; no new cursor protocol or arbitrary cutoff is needed. Empty requested-year history remains an empty result.
- Generated client + public web feature `loadOpeningSnapshotsForYear(token,companyId,incomeYear,requestId?)`. Validate returned company/year and existing identity/provenance constraints before returning to the archive; the archive must call this exact scoped read and retain its original selected archive fields.

The SQL must pass the required year directly to BOTH `shareholder_register_filing.read_opening_snapshots_v1` and `ledger.read_opening_bank_inputs_v1` before either source validation. Holder read uses that same year and selected setup identity. Retain accepted-member filtering, verified-subject binding, same-transaction snapshot, exact original bank createdBy/createdAt provenance and monetary validation. RF remains owner of share facts, Ledger remains owner of original bank input, and backend application composition joins their existing public SQL seams. Do not route this through an all-year reader and filter afterward, put bank data in RF DTOs, weaken quarantine, or change existing list contracts. B can share the existing private row decoder/formatting, with no generic new query framework.

## Required narrow proofs

1. Real migrated database: valid2025 opening plus quarantined foreign-holder2024 opening. New2025 read succeeds with exact bank/share fields; new2024 read remains unavailable; old all-year read retains its current fail-closed behavior. Add the analogous unrelated-year invalid bank provenance if distinct parser paths need coverage.
2. Requested-year bad source remains unavailable; hidden company/current membership denial preserves original authorization behavior; response cannot escape company/year. No new MFA requirement for a normal read—the archive keeps its existing step-up gate.
3. Actual API and generated transport forward the required year and preserve Decimal >2^53, empty-year behavior and existing output wire. No old endpoint/cursor contract change.
4. Executed archive route calls only the scoped reader, completes all reads before export completion, and retains the prior27-field original fixture equality and eight unchanged generic sibling query expressions. A mocked all-year reader should be unreachable in that test.

## Reviewed source hashes

- `apps/web/app/archive/[companyId]/[incomeYear]/download/route.ts`: `39620a9fe39f61ebce35f639f072d835f0bac83fab4a6f1ea508afefe7c5e6c8`
- `apps/web/features/ledger/transport.ts`: `5fbace6534c2c1738652074f92b50799287018659dd70ccaa52ed4e6e091b19f`
- `apps/backend/src/talli_backend/application/new_year_opening.py`: `a3352c2c2fbc4968c89cabffa29d44a5cd4cff101f06ea16a7712ea06b059737`
- `apps/backend/src/talli_backend/adapters/supabase_ledger.py`: `9b38c9d5cd5e5bd8730d30b0e3140d31aa6cff16e36ccdb7f429ac689e24d9fa`
- `supabase/migrations/20260909190548_shareholder_register_filing_capability.sql`: `729c0d460a05cf8035aa62742a43e25a840b521e04fcd98b31327ce1227165af`
