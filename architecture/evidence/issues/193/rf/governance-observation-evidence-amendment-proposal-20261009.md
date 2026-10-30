# Governance register-evidence repair dependency

**Proposed design, not an implementation decision or human approval.** Read-only
source review on 2026-10-09 at `f095b0c2898c5e3166dba8c1120f112af82ec457`.
This original review preceded the bounded Governance owner turn recorded below.
The proposal itself changes no code, grants, facade behavior or activation. The separate
[archive-owner proposal](withdrawal-owner-dependency-proposal-20261009.md) remains
pending; no answer to that decision is inferred here.

## Existing repair is not sufficient

The public [Governance contracts](../../../../../apps/backend/src/talli_backend/modules/corporate_governance/public.py)
offer record and reverse, but no evidence-only amendment. A recorded event freezes
canonical facts, the register reference, signed-document hashes, Ledger/Banking
references and `recorded_at`. Its finalization digest binds the facts and
Ledger/Banking/correction identities, but does **not** include recording time or
actor. A new amendment must bind both explicitly.
The [adapter](../../../../../apps/backend/src/talli_backend/adapters/supabase_corporate_governance.py)
always sends `correctionOfEventId=None` for a new record.
[Reversal](../../../../../apps/backend/src/talli_backend/application/corporate_governance_workflow.py)
calls Ledger's mechanical reversal; it does not repair the evidence binding.

RF's [`_build_capital_receipts`](../../../../../apps/backend/src/talli_backend/application/shareholder_register_source_workflow.py)
requires an uncorrected, recorded Governance event, reads its exact original
register reference, and requires observation capture at or before `recorded_at`.
[Reporting-year composition](../../../../../apps/backend/src/talli_backend/modules/corporate_governance/reporting_year.py)
also treats Ledger amendments as reversed/corrected blockers. Thus independent
recapture, reversal, or another ordinary record call is not a demonstrated repair
that preserves this event and its Ledger entry.

## Minimal final-SQL withdrawal backstop

Protect fresh inserts in
[`corporate_governance.complete_supported_event_v1(jsonb,text)`](../../../../../supabase/migrations/20260904220000_corporate_governance_supported_events.sql),
after authorized committed-replay handling and before insertion. Existing replay
compares only `factsSha256` and `accountingEntryId`; it is not a full-command exact
comparison. Preserve valid historical recovery, with NULL-safe immutable bindings
and stored/request company-year agreement before returning a receipt. Retain the
[company-first READ COMMITTED wrapper](../../../../../supabase/migrations/20260924080355_governance_ledger_company_write_guards.sql),
then the existing event lock. Use exactly the current
[`requires_register_observation`](../../../../../apps/backend/src/talli_backend/application/corporate_register_evidence.py)
cases: cash increase `registered`; loss-covering reduction `registered` or
`first_recognized_after_registration`. Do not apply this to earlier phases or loans.

Validate the selected nested `canonicalFacts.shareholderRegisterFact` ID, positive
integer revision and digest, and its agreement with `shareholderRegisterSourceId`.
Reject missing/null/malformed references. Bind the duplicated outer and canonical
company/year/kind/phase identities so choosing an unrelated outer kind cannot
skip the guard. Call RF's public
`assert_current_register_observation_v1(id,company,year,revision,sha,subject)` with
those exact values; its RF-owned withdrawal guard then closes the direct permitted
SQL path as well as the Python workflow. Preserve the old function OID, signature,
owner, ACL and committed replay result. No current-head check before replay.

**Grant prerequisite:** this completion function executes as
`corporate_governance_store_owner`, whereas the existing
[RF assertion grant](../../../../../supabase/migrations/20260924080249_documents_rf_consequential_company_guards.sql)
targets `corporate_governance_workflow_executor`. The store owner needs narrow RF
schema `USAGE` and this public assertion's `EXECUTE`; no RF table grant or role
membership. Declare the SQL/public-contract dependency and catalog it.

This minimum guard proves current exact RF identity, not complete SQL parity with
the Python economic/original-byte verifier. In particular, the existing assertion
returns no capture time. If final SQL must enforce the existing observation-before-
recording invariant too, add an RF-owned versioned assertion accepting a
server-selected `not_after` instant; do not read the RF table from Governance.
Use the same instant for the new record's timestamp. Preserve the existing v1
assertion for old callers and test this additional contract explicitly.

## Proposed immutable evidence-amendment contract

One new Governance command, illustratively
`AmendSupportedCorporateRegisterEvidence`, accepts only scope, actor/idempotency
context, original event ID and expected original finalization digest, expected
amendment-head ID/digest (or explicit first amendment), the exact withdrawn
binding/withdrawal receipt, replacement RF ID/revision/digest, reason and a
versioned Documents correction-memo reference. It accepts no replacement economic
facts, accounting entry, event date, original actor or original recording time.

Governance appends an immutable receipt containing those links plus server-minted
identity/time/actor, request digest, original facts/finalization commitments,
Ledger entry identity and original recording time, and verified original-document
commitments. Bind the complete receipt with one versioned canonical codec.
Preserve the original event, `created_by`, `created_at`, canonical facts,
`facts_sha256`, `finalization_sha256`, signed evidence, phase, event reference,
Ledger entry and Banking claim byte-for-byte. Post no Ledger entry, reversal or
new Banking claim. The amendment is a later evidence statement, not retroactive
proof that the replacement observation existed when the event was recorded.

Required semantics:

- Only an existing supported registered event with the same company/year and
  unchanged economics is eligible. Reject reversed/corrected/conflicting events
  or Ledger amendments through Ledger's public owner query. Replacement evidence
  must match the event's kind/date and economic facts using the existing verifier;
  RF still checks the full before/after shareholder state against the filing case.
  A change in economics, legal event or accounting treatment needs the appropriate
  owner correction, not this command.
- RF must first publish a narrow retained lifecycle/withdrawal assertion or query.
  Governance must prove the old effective binding was withdrawn and the replacement
  is active, independently captured and exact. Private RF table access is not an
  alternative. Repeated repair forms a single append-only chain: the next receipt
  names the current amendment head and its now-withdrawn replacement. No forks,
  skipped head, deletion or ancestor reactivation.
- Preserve `replacement.confirmed_at <= amendment.recorded_at`, original recording
  time `<= amendment.recorded_at`, and the exact RF effective-event relationship.
  Do not change the original timestamp to satisfy the old RF check. Signed original
  Governance evidence remains required; retain new correction evidence separately.
- Read/verify original bytes outside locks. In the final short guarded transaction,
  recheck owner/admission, exact event and amendment head, RF withdrawal/currentness,
  retained Documents identities and relevant Ledger lifecycle. Use declared public
  assertions on the same connection. Every permitted completion call must bind the
  verified replacement to the immutable event; a caller `verified=true` is not proof.
- Resolve authorized exact replay before mutable evidence checks or external I/O.
  A changed command under the same actor-scoped key conflicts; lost responses recover
  the original receipt. Later withdrawal of the replacement blocks fresh downstream
  use but does not erase the amendment or break its historical replay.

## Authorization and freshness

Retain the verified-subject match, current accepted owner, current agreement and
company-year eligibility checks of
[`assert_owner_v1(...,true)`](../../../../../supabase/migrations/20260902040000_corporate_governance_owner_dividend.sql).
Its [Company Access admission helper](../../../../../supabase/migrations/20260827100000_ledger_capability.sql)
checks `aal2`, but does **not** establish MFA recency. For the new amendment require
the existing [Company Access fresh-MFA contract](../../../../../supabase/migrations/20260808120000_company_access_cancellation_lifecycle.sql),
`company_access_has_fresh_mfa_v1()`: supported MFA method and numeric AMR timestamp
within its 15-minute window. The later
[Company Access RF admission migration](../../../../../supabase/migrations/20260924080208_company_access_rf_admission_guard.sql)
preserves that policy, replaces both statement-time reads with `clock_timestamp()`
and marks the helper `VOLATILE`. Use this final topology so a lock wait cannot
reuse statement-start freshness. Grant only that public function to the Governance
store owner if needed. Check at command admission/final completion and retain the
post-lock owner recheck; do not trust an HTTP Boolean or copy the MFA rule into
Governance. Historical query authorization remains separate.

## RF consumption and proof

Publish an additive Governance projection containing the **unchanged original**,
complete amendment chain and effective evidence binding. Version its enumeration
digest; freeze `corporate-reporting-year-2` and old API projections. Do not graft
the replacement onto `canonicalFacts` or call it a corrected economic event.

RF intake and `_build_capital_receipts` consume that public projection. With no
amendment, retain the original capture-time rule. With a valid amendment, require
the exact base finalization, current complete chain, replacement identity and
`confirmed_at <= amendment.recorded_at`; bind the amendment ID/digest into the new
RF source receipt/freshness commitment. Keep the original economic/finalization
commitments. Version the affected RF source/receipt codecs and archives additively;
do not change old source hashes. Recheck the effective binding on consequential
admission. Existing source/approval/submission history stays readable, while a new
withdrawal or amendment makes stale future use fail closed.

Required tests: direct old SQL after withdrawal; committed replay; malformed or
divergent reference fields; exact hash/actor/time preservation; fresh versus stale
MFA and owner revocation across a lock wait; cross-tenant concealment; changed
economics and Ledger reversal rejection; replacement withdrawal races in both
orders; concurrent same-key replay and competing heads; missing/tampered originals;
lost-response lookup; no Ledger/Banking writes; old-codec goldens; full-chain
enumeration/truncation; rollback retaining receipts and guards. Real SQL/RLS/race
execution remains required; this source review supplies none of that runtime proof.

Sequence, if selected: RF public prerequisites → bounded canonical Governance
owner turn → RF consumer work, one owner at a time. Until implemented and proved,
the already-recorded-event scenario remains blocked technical work. This option
does not resolve archive completeness, authorize a frozen facade change, cure a
substantively invalid corporate event, or imply production/filing activation.

## 2026-10-10 engineering checkpoint (Europe/Oslo)

RF's additive prerequisites are committed at `c0c3f59a`:
[`assert_current_register_observation_v2`](../../../../../supabase/migrations/20261009222053_rf1086_observation_evidence_assertions.sql)
binds a supplied finite cutoff; `read_retained_register_observation_withdrawal_v1`
binds the canonical retained withdrawal and its exact target. Both remain
ungranted to runtime callers. The
[bounded evidence record](observation-evidence-assertions-20261009.json) distinguishes
16 native checks with authorization stubs, 106 harness checks and 37 full database
cases collected only. These are prerequisites, not implemented amendment support.

The next selected engineering slice is a bounded **canonical Governance** owner
turn for the existing final-SQL backstop. It consumes v2, validates the duplicated
outer/canonical identities before choosing the guarded kind/phase, and grants only
the necessary public assertion and schema access to the Governance store owner.
Use one `statement_timestamp()` value as cutoff and explicit new `created_at` to
preserve current timestamp semantics. If a capture commits after this statement
starts while it waits for the company lock, the cutoff rejects it conservatively;
retry with a fresh statement. Do not describe this cutoff as minted after the lock.
Currentness still rechecks after the company lock, under READ COMMITTED.

Source review also identified a replay concern: the old completion selects by
`event_id` without company/year and uses nullable `<>` comparisons. The new slice
must prove scope concealment and reject missing/mismatched immutable replay
bindings. No mutable currentness check belongs before a valid historical replay.
This is a source finding pending the new guard's execution, not a completed race
or authorization test.

This selected implementation work uses the existing serial canonical-owner rule.
It neither grants a future Archive-facade exception nor resolves the pending
Archive decision. Amendment persistence, workflow, browser recovery and RF
consumption remain subsequent owned work; the migration pointer and all acceptance
criteria remain unchanged.
