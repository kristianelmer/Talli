# RF source facts independent review

Reviewed the working source after checkpoint `3e8bf518`, on 2026-09-09. Read-only review of `source_facts.py`, its public source DTOs, the source snapshot adapter, relevant original readiness behavior and persisted reconciliation event shape against `architecture/evidence/issues/151/source-contract-requirements.md`. This is a source-contract review, not #151 acceptance or proof of the migration lifecycle. I did not certify my own production/workflow implementation. No database, hosted service or provider was used; repository source was not edited.

## Actionable findings

1. **Accepted advisory overrides disappear from the RF source handoff.** Requirement 1, line 51: “Preserve existing supported-case/rule/schema semantics, accepted warnings and review facts.” The frozen `apps/web/app/lib/annual-readiness.ts:157–165` treats every applicable non-block override, including `advisory`, as an accepted warning. `apps/backend/src/talli_backend/modules/shareholder_register_filing/source_facts.py:137` keeps only `risk_level == 'warning'`. A valid owner-confirmed advisory override therefore produces ready with an empty warning tuple. Further, `public.py:1124` exposes only text, so consumers cannot preserve the required accepted/source distinction even for retained warning overrides. Preserve the existing non-block override and acceptance facts through an immutable RF-owned representation without adding a billing decision.

2. **Successfully reconciled negative authority outcomes lose discovery facts.** Requirement 4, line 54: “attest only RF-owned failure/outcome facts, including … event/discovery timing and attributable cause where evidence supports it.” `source_facts.py:161–162` publishes incidents only for journal operation states `failed` or `unknown`. The actual reconciliation SQL, `supabase/migrations/20260909190548_shareholder_register_filing_capability.sql:1715–1726`, records a known `rejected` or `action_required` result as operation state `succeeded` with the negative `resulting_status`. A retained rejected artifact plus such an event yields complete coverage and a rejected attempt, but zero incident/outcome facts. The attempt’s only timestamp remains the first successful mutation (11:00 in the reproduction), not rejection discovery (12:00). Preserve the known outcome event/status and its observation time; do not manufacture a transport failure or commercial attribution. Existing unknown attribution remains appropriate.

## Reproduction

`/tmp/talli-151-source-facts-repro.py` uses the existing synthetic source fixtures and real `build_source_facts`; `/tmp/talli-151-source-facts-repro.jsonl` records the observed output. Both cases ran locally with no I/O adapters. Re-run from the worktree:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=apps/backend/src:apps/backend/tests apps/backend/.venv/bin/python /tmp/talli-151-source-facts-repro.py
```

Observed: advisory → `ready`, no warnings; rejected reconciliation → complete history, rejected attempt, zero incidents, earliest mutation timestamp only. The second fixture matches the shipped SQL’s operation-state/resulting-status distinction and includes its rejected receipt artifact.

## Scope checks without further actionable findings

- Coverage explicitly means `talli_recorded_rf1086`; absent rows do not become world-wide no-submission proof. Missing/partial inventory, quarantine, incomplete enumeration and broken retained links fail closed.
- Snapshot reading is repeatable-read and scope-bound. Owner-only artifact visibility prevents another accepted role from receiving an unsupported complete-history claim.
- Currentness is content-based and bound to company/year/obligation/reference/version/digest, with a future-time rejection. The separately versioned digest retains raw opening/journal extent and does not rewrite historical payload hashes.
- Production, simulations and corrections remain distinct; superseded attempts remain in the source extent. Missing parents invalidate completeness. Partial/unknown operation states are retained and do not infer a terminal acceptance.
- RF readiness contains no billing-entitlement dependency. This review does not assert other obligation readiness, target-year admission, final #192 financial eligibility, or a supported correction writer.

## Independent correction recheck — both findings closed

Read the author’s follow-up in `source_facts.py`, `public.py`, and `test_rf1086_source_facts.py`. `Rf1086WarningFact` now retains the warning’s source/id/code/reason/risk and acceptance actor/time; advisory and warning overrides are included, preview warnings remain explicitly unaccepted, and equal messages do not collapse distinct source records. Blocking overrides remain blocks.

`Rf1086OutcomeFact` now exposes successful reconciliation observations separately from transport incidents and mutation observations. Its original resulting status/event/submission/time are retained, including rejected and action_required; attribution stays unknown. Unknown reconciliations remain incidents. This does not infer an authority event time or a financial liability decision.

Independently replayed both original reproductions as assertions through the real source builder: `/tmp/talli-151-source-facts-correction-repro.py`, with output `/tmp/talli-151-source-facts-correction-repro.jsonl`. The advisory fixture now retains its accepted source facts. The rejected fixture now has a 12:00 outcome observation while its original mutation stays at 11:00; no transport failure is invented. The author’s committed-style regression cases additionally cover advisory/warning, ordinary preview warnings, equal messages/different sources, blocked overrides, accepted/rejected/action_required/received outcomes, unknown incidents, immutability and digest invalidation. The supplied combined log records 92 passes; I did not repeat that entire suite.

No additional actionable defect in this correction. This closes the two source findings only, excluding my own production/workflow code and unexecuted database/migration/provider acceptance.
