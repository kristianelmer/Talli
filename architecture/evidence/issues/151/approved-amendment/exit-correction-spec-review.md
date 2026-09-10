# Independent follow-up Spec review: #151 exit cleanup

Read-only source review of WIP atop 8f86488cb32e8d50ad8546654e20ea46d9c8885d, fixed point 91b178c281bcc5fb887a6257d2f72e380199f3e6. No database/browser operations or product edits. Root owns executable migration verification.

## Findings and closure

**No remaining concrete defect found in this bounded correction review.** The previous two findings are closed:

- **P1, full rollback overwrote sibling identity collisions:** full capability rollback now preflights all six generic families at367–372 before generic upserts. Non-RF collisions abort transactionally. The inspected red transcript shows full rollback failed to raise while phase rollback passed; the new test verifies retained sibling JSON and contracted phase after rejection.
- **P2, full rollback unnecessarily advanced archive generations:** full rollback now saves and suspends remaining public USER triggers at238–247, retains internal FK triggers, and restores original enable modes at658–663 after archive-trigger recreation. The inspected red transcript records generation17 becoming22 only for full rollback; the six-family regression now asserts exact generation JSON after reverse as well as after contract.

Inspected root-owned final lifecycle transcript: **54 passed in18.65s**, including both reverse variants of these regressions. These tests were not executed by this reviewer. The broader119-pass DB run reported by root predates the final two rollback fixes and is not evidence against these final source hashes.

Earlier reported paths remain addressed at source level: six-family retirement freezes provenance; reconciles canonical plus quarantine; deletes children first; verifies sibling and canonical/inventory/quarantine equality; retains FK/FORCE RLS; restores trigger modes. Both reverses replay quarantine after canonical parents, with authority evidence before submissions. Sibling comment ownership and RF-prefix conflicts are classified as previously requested.

## Explicit verification limits

Generic quarantine reverse coverage directly exercises the conflicting override. The quarantined-preview/dependent regression currently stops after EXPAND. No malformed generic-quarantine JSON replay regression was found. Source guards reject mismatched keys/record IDs, enforce typed row conversion/FKs, and operate transactionally; no concrete defect was established. Strong additional proof would replay quarantined preview plus dependent families through both reverses, and corrupt a quarantine key/ID then assert atomic failure with unchanged schema/security/archive state.

Full stage9/common envelope, browser/provider behavior, complete gates and protected integration remain uncertified by this review. Historical preclosure artifact: `/tmp/talli-151-exit-correction-spec-review-before-closure.md`.

## Source bindings

- `supabase/migrations/20260909190548_shareholder_register_filing_capability.sql`: `fa29bbe4b4c7a498554e18bf3f71ede4146d616e414e48b9290815d52fc99e15`
- `supabase/contract-migrations/20260909190955_shareholder_register_filing_contract.sql`: `b70e56d4dbf03bd83fcb6b932f9d0e80543929ef42ce0f711eb3f6c1b585a342`
- `supabase/rollback/20260909190955_shareholder_register_filing_contract.sql`: `fa34b43318cbfeb138d27f1791d04f46ac23bc1c686d079a7bd58315680b0a42`
- `supabase/rollback/20260909190548_shareholder_register_filing_capability.sql`: `dd77bf9f887f4c9d35cf94952a0c183da93b6d84f2fdf0706f8648589f3119ae`
- `apps/backend/tests/test_shareholder_register_filing_lifecycle.py`: `7055bbe3a8c29fa82da48e1b93cd7afb9f69ec9b1edbcafb18ab471af196d422`

## Inspected root-owned transcript bindings

- `/tmp/talli-151-exit-collision-red.log`: `8be8f67da98dcbbd0068be73d14b0d748dcba182f46a34a11b7bfdaf6ea3aaf7`
- `/tmp/talli-151-exit-archive-reverse-red.log`: `4ce75e73ed507c9f1e9c720c8b4ff5bbbd9db7612a87d35d3975c5118c4865bd`
- `/tmp/talli-151-exit-rollback-green.log`: `7e7306e57b03afe2ce1cfff51e4e529f2c92d73c631c47b56b94432f9dffb797`
