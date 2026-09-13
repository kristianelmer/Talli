# Local RF final-topology verification

Observed 9 September 2026 UTC on the exclusively owned disposable database. No hosted database, provider operation, settings change, or production activation occurred. HEAD remained `7730bd34` during the final 108-case run; the receipt contains the full commit and 263 source hashes.

## Passing checks

- Shipped `rehearse-authority-topology.mjs rollback` restored the predecessor before the existing source-owner rehearsals.
- Existing local Ledger migration-authority rehearsal: 1 passed, 0 skipped. It performed its original contract, rollback, recutover, and failed-authority cleanup.
- Existing Corporate Governance lifecycle commands: 24 + 2 passed, 0 skipped.
- Full Billing Python suite: **699 passed, 0 skipped**, 339.06 seconds. The following Node lifecycle initially rejected a host-clock fixture timestamp; the separately corrected Node lifecycle subsequently passed **1/1, 0 skipped** and established the final Billing contract.
- Five ordinary-fresh Python MFA fixture timestamps now use the existing database-clock-minus-one-second helper. All 34 affected cases passed again with complete pre/post source hashes, 8.87 seconds. The original stale branches, expiry vectors, assertions, and runtime authorization SQL are unchanged.
- Two ordinary-fresh Node receipt fixture timestamps now use the database clock minus one second inside their existing transactions. Independent whole-file comparison confirmed all other source text unchanged.
- Shipped `rehearse-authority-topology.mjs recutover` succeeded after the original Ledger contract removed `ledger.entries.setup_id`.
- Four new actual DB read-role/archive-generation cases: **4 passed**, 37 deselected, 0 skipped.
- Complete current AU/operator/launch/RF/lifecycle suite: **108 passed, 0 skipped**, 30.93 seconds; every recorded source hash matched at completion.

## Final facts

The final catalog snapshot records RF phase `contracted`; both old public opening tables, the public Ledger entries compatibility view, the retired Ledger setup column, and the public System User view are absent. The bank archive-generation trigger is enabled. `ledger_executor` can execute both opening/bank read contracts and cannot execute either RF opening or Ledger bank mutation contract. Temporary `authority_test_*`/`rf_test_*` logins are absent, and `talli_ledger_backend` is NOLOGIN.

The new bank tests establish that the bank-only recording step advances the scoped generation after the RF opening exists; transaction rollback restores the generation and bank state; the composed opening retains the exact amount; reverse cutover removes the bank trigger and full rollback restores the original public bank value. The ordinary read-role tests retain company/actor concealment and deny table/writer access.

The original Billing fixtures retain scoped synthetic evidence (`admitted` returns committed local fixture state without a teardown); the final total company count is reported rather than erased. No broad janitor or production permission relaxation was introduced.

## Evidence paths

- `/tmp/talli-151-final-rollback.{log,json}`
- `/tmp/talli-151-final-ledger-authority.{log,json}`
- `/tmp/talli-151-final-governance.{log,json}`
- `/tmp/talli-151-final-billing-corrected.{log,json}` (699 Python successes; subsequent original Node timestamp failure)
- `/tmp/talli-151-final-billing-node-clock-corrected.{log,json}` (valid corrected Node lifecycle success)
- `/tmp/talli-151-final-billing-clock-affected-complete-hashes.{log,json}`
- `/tmp/talli-151-final-recutover.{log,json}`
- `/tmp/talli-151-final-focused-final-role-bank-final.{log,json}`
- `/tmp/talli-151-final-combined-108.{log,json}`
- `/tmp/talli-151-final-topology-snapshot.json`
- `/tmp/talli-151-billing-clock-repro.json`
- `/tmp/talli-151-billing-clock-source-supplement.json`
- `/tmp/talli-151-billing-node-source-supplement.json`

## Evidence limits

The first wrapper inventory omitted three changed Python fixture files and the Node test file. Supplements state their actual post-start/post-run capture times; they are not represented as pre-run captures. The 34-case Python group and the final 108-case suite were run under the corrected complete backend source inventory. An optional second Node invocation intended to improve the manifest was rejected at its initial overlap-only assertion because the successful prior run had already contracted Billing; it performed no second lifecycle mutation. The valid Node pass remains separately identified above.

This is local SQL/runtime verification, not a full customer-ready gate or a final #151 exit. Final HTTP/feedback/browser verification follows under C's ownership. The finite 16-scope compatibility decision and full fresh RF browser remain outside this receipt.
