# RF downstream observation invalidation — proposed next slice

Date: 2026-10-09. Read-only design against the working tree after `f095b0c2`.
Originally an engineering proposal derived from the reviewed withdrawal plan
and current SQL. The subsequent [implementation record](withdrawal-admission-guards-20261009.json)
binds the staged guards and executed checks; live database proof remains pending.
No runtime withdrawal grant, acceptance or launch promotion is implied.

## Contract and limits

Required: a withdrawn or superseded exact observation cannot support a **new**
source, preview, bridge, approval, submission claim or provider-operation intent.
Keep immutable history, original capture/claim recovery, existing intent results
and outcome/reconciliation writes. Preserve unrelated sources and independent new
observation roots. Every old callable SQL path must enforce the same boundary.

Chosen implementation: two RF-private guard overloads, inserted after existing
exact-replay returns and before the first fresh mutation. This is an admission
backstop, not a new storage codec, withdrawal command, Governance policy or
source-facts rewrite. It preserves existing authorization/replay restrictions;
“replay survives withdrawal” does not override existing owner, manifest, source
head, MFA or authority checks.

## Exact source representation and private contracts

The frozen `rf1086-year-source-v1` codec stores references at:

```
snapshot.fields.governance_receipts[]
  record == "Rf1086YearGovernanceReceipt"
  fields.company_id.fields.value
  fields.income_year.fields.value
  fields.register_observation_id       # canonical UUID string or JSON null
  fields.register_observation_sha256   # lowercase SHA-256 string or JSON null
```

The receipt has ten fields: `receipt_id`, `company_id`, `income_year`,
`event_type`, `economic_sha256`, `finalization_sha256`, `signed_document_hashes`,
`active`, and the two register fields. There is **no observation version** in this
codec. Resolve the existing immutable observation by exact ID/company/year/hash
and use its stored version; do not add or invent a receipt version. Source time
is `snapshot.fields.confirmed_at.datetime`.

Proposed overloaded private function, both `VOLATILE SECURITY INVOKER`, fixed
empty `search_path`, owned by the RF store owner, no runtime/PUBLIC execute grant:

- `assert_source_register_observations_active_internal_v1(p_company uuid,
  p_year integer, p_snapshot text) returns void`: incoming-source guard after
  `append_year_source_v1` has checked its envelope against the typed arguments.
- `assert_source_register_observations_active_internal_v1(p_company uuid,
  p_year integer, p_source uuid, p_source_sha text) returns void`: load the exact
  persisted source row, validate row/envelope identity and time, then delegate.

The text overload must reject missing, null, scalar or malformed receipt arrays;
only an explicit empty array means no references. Validate the known codec,
record wrappers, scope, timestamp, receipt fields and exact primitive types.
Reject duplicate JSON keys **before** conversion to `jsonb`: PostgreSQL 17's
`IS JSON OBJECT WITH UNIQUE KEYS` validates keys in nested objects too
([primary documentation](https://www.postgresql.org/docs/17/functions-json.html#FUNCTIONS-SQLJSON-TESTING)).
Reject malformed/missing reference pairs. Both null is permitted for a dividend;
non-dividend Governance receipts require the existing independent-register pair.
A supplied pair on any receipt must be checked. Validate receipt IDs against the
stored command's event-evidence bindings so deleting a referenced receipt does
not turn it into captured-empty. Do not recompute capital economics or query
foreign-owner tables; complete Governance enumeration remains an existing
workflow responsibility, not something this parser can prove.

For every supplied pair, require an exact retained observation, strict
`observation.confirmed_at < source.confirmed_at`, no successor, and no withdrawal.
Reuse `assert_register_observation_active_internal_v1` after resolving the row's
version. An independent observation or another source in the same year must not
cause a scope-wide block. No source/head/approval row is invalidated or rewritten.

## Lock and snapshot discipline

All checks must occur under the existing company-first, RF-year-next guards.
Use the existing private `assert_source_approval_guards_v1(company,year)` as the
held-lock/READ-COMMITTED assertion at the new guard entrance; do not modify that
shared routine. It verifies both held advisory locks, converts them to transaction
locks in public order and repeats existing preparation/year admission. Existing
append/preview/bridge calls already acquire the matching locks with
`lock_year_source_v1`; approval/claim/intent calls already assert them.

This also rejects stale REPEATABLE READ/SERIALIZABLE calls, even for an explicit
empty reference array. A lock acquired after withdrawal cannot refresh an old
transaction snapshot. New private guards must remain VOLATILE; no STABLE snapshot
shortcut. Do not add a global withdrawal check to a lock, RLS policy, member
assertion, submission-head reader or outcome writer.

## Old SQL seams and precise placement

All names below are in `shareholder_register_filing`; existing signatures, OIDs,
owners, ACLs, security modes and search paths remain unchanged.

| Existing function | New guard placement and source | Replay preserved |
| --- | --- | --- |
| `append_year_source_v1(uuid,uuid,int,int,text,text,text,uuid,text,text,text,timestamptz)` | After existing `payload` envelope/time checks, immediately before inserting `year_source_versions`; guard `p_snapshot`. | This SQL routine already rejects reused keys. Adapter capture replay and the read-only committed-receipt query occur before this append and remain untouched. |
| `append_source_preview_v1(uuid,uuid,int,uuid,text,text,text,text)` | After `return original.id` branch, before `source_previews` insert; guard exact `source` ID/hash. | Original ID/payload equality and existing current-source-head checks remain. Withdrawal adds no new check before the replay return. |
| `bridge_source_preview_v1(uuid,text,text)` | After existing projection/binding equality and `return p_preview`, before either new projection/bridge insert; guard `s.source_id/source_sha256`. | Retained matching bridge returns unchanged. |
| `append_source_approval_v1` and `append_source_approval_v2` `(uuid,uuid,text,text,text,text)` | After exact matching `result` return, **before** invalidating the previous approval; guard `s.source_id/source_sha256`. | Preserve original approval return and current manifest/context checks. v1 remains executor-revoked. |
| `claim_source_submission_v1(uuid,text,uuid,text)` and `v2(uuid,text,uuid,text,text)` | After the second post-lock exact-claim return and owner recheck, before first `submission_heads` insert; guard `b.source_id/source_sha256`. | Keep both pre-lock and post-lock replay returns. An explicit claim guard is required because delegated append-approval can itself return a replay. v1 remains revoked. |
| `prepare_source_operation_v1(uuid,text,text,text,uuid,uuid,text,text)` | After latest-event `newlyPrepared=false` return and expected-event checks, before any fresh prepared-event insert; guard `b.source_id/source_sha256` unconditionally for every operation. | Existing prepared/succeeded/unknown/blocked results remain recoverable. A retryable failed result with matching expected event creates a **new** intent and must be checked. |
| `prepare_source_operation_v2(uuid,text,text,text,uuid,uuid,text,uuid,text,text)` | No guard at wrapper entrance. Its unchanged authority/binding validation delegates to guarded v1. | No replay-breaking wrapper check; v2 remains the public runtime entry, v1 stays executor-revoked. |

Main, every child document, confirmation and every retry are covered by the same
fresh-event insert guard. A check only inside `p_operation='post_hovedskjema'`
would leave children and confirmation bypasses.

Leave `finish_source_operation_v1`, `read_source_submission_claim_v1`, capture
receipt lookups, historical source/observation/preview/archive reads and feedback
reconciliation unchanged. An intent committed before withdrawal already admitted
that bounded operation; recording its succeeded/failed/unknown result afterward
is required. Withdrawal cannot unsend it or authorize the next operation.

## Errors and compatibility

- Reuse `rf1086_source_register_observation_stale` for absent/mismatched,
  superseded, withdrawn or non-predating referenced observation. Catch only the
  existing active guard's exact predecessor-mismatch error when translating it.
- Reuse `rf1086_source_storage_invalid` for malformed source/reference structure
  or row/envelope mismatch; expose no IDs, payload, key or raw SQL diagnostic.
- Preserve `rf1086_source_approval_guard_required` for absent held locks or
  non-READ-COMMITTED calls; do not suppress other database failures.
- Add only the missing stale-source code to the adapter's existing
  `Rf1086YearSourceError` mapping if this slice includes error translation. The
  source API already maps that family to generic safe 409, and storage-invalid
  to 503. Old binaries may return their existing safe generic unavailable error;
  they still cannot commit the forbidden mutation. No API/schema/client changes.

Forward migration should use finite, unique body anchors with drift refusal and
idempotent markers. Capture and compare original OID/owner/ACL/config/security/
volatility/parallel attributes, including revoked v1 functions. Do not replace
ACLs with guessed grants. A retained-row rollback must refuse removal; an empty
rollback may be a documented no-op retaining unconditional guards. Never restore
an older unguarded admission function as rollback.

## Concrete files and validation

Proposed production scope:

- New matching forward/rollback files named `<timestamp>_rf1086_withdrawal_source_admission_guards.sql`.
- `apps/backend/src/talli_backend/modules/shareholder_register_filing/MODULE.md`
  and `module.json`: private guard/migration/test inventory and remaining limits.
- `scripts/rf-consequential-successors.json`: append this layer after the
  observation foundation; a function-marker presence query distinguishes it.
- `tests/ci_release_gate.test.mjs`: successor order and fail-stop expectation.
- `package.json`: register the new database test in the mandatory Authority lane.
- Optional bounded adapter error mapping and its focused test as described above.
  No business public-port, Governance, archive-facade, web or route changes.

New database test file:
`apps/backend/tests/test_rf1086_withdrawal_admission_database.py`. Build a real
restricted-RF observation and a valid cash-issue year source referencing it;
use the pure public source codec and existing owned document/annual/pilot fixture
machinery. Do not alter an already persisted source snapshot to inject a
reference. Factor only the minimum existing fixture construction needed to seed
that source before preview/approval/claim creation. Explicitly reapply current
successors after historical v1 fixture migrations, and restore their exact
prior role/function state on teardown. Temporary withdrawal/v1 test grants go
only to a unique owned NOLOGIN/NOBYPASSRLS role; normal executor ACLs stay closed.

Required real-database cases:

1. Direct legacy SQL calls at **every table row above**, bypassing updated Python
   freshness checks. Both v1/v2 approval and claim bodies are exercised via the
   confined fixture role; runtime revocations are separately asserted.
2. Withdrawal-first versus fresh admission: block after waiting, no new source,
   head, preview, bridge, approval invalidation, claim or prepared-event row.
3. Admission-first versus withdrawal: first receipt remains immutable; subsequent
   new stage fails. Parametrize source, preview, bridge, approval v1/v2, claim
   v1/v2, main, each child, confirmation and retry. Hold the actual company lock,
   observe bounded lock waiting, then commit; no sleep-based race inference.
4. Intent-first: after withdrawal, exact existing intent/claim replay succeeds;
   succeeded/failed/unknown outcomes and identical outcome replay persist;
   subsequent child/confirmation/retry admission fails. Withdrawal-first creates
   no intent. No provider call is necessary to prove these DB effects.
5. Snapshot isolation: a snapshot fixed before withdrawal under RR and SERIALIZABLE
   cannot create any new effect, including no-reference input. RC waiter sees the
   committed withdrawal. Preserve existing read-only recovery isolation.
6. Strict shape/binding: missing/null/non-array receipts, duplicate JSON keys,
   wrong record/field types, half-null pair, invalid UUID/hash, wrong company/year,
   deleted event-bound receipt, missing target, wrong hash, superseded target and
   non-predating time. Multiple references must check all entries. An explicit
   empty no-activity source and an unrelated valid observation remain usable.
7. History/replay: original capture lookup, stored preview/bridge/approval/claim
   equality, original bytes/IDs and source heads unchanged; changed request/key
   still conflicts under its existing contract. Historical recovery never implies
   fresh admission. Owner revocation remains effective.
8. Migration apply/replay, exact ACL/OID equivalence, successor recutover, retained
   rollback refusal and no runtime withdrawal/helper grant. Cleanup only exact
   owned rows/roles, restoring FORCE RLS and immutable triggers atomically.

Local checks: new test collection, focused adapter mapping tests if changed,
architecture, CI registration tests, diff check and unchanged OpenAPI. Full SQL,
RLS and both-order race proof requires the root-owned disposable database/CI;
collection or mocked harness results must not be called a database pass.

## Explicit follow-up before activation

The original broad plan mentioned guarding shared approval-context functions.
For this bounded replay-preserving slice, leave their shared internals unchanged:
append approval currently invokes them **before** its exact stored-result return.
A blanket context guard would reject historical replay. Current advisory approval
readiness can therefore still look ready although the new mutation seam rejects
it. Follow-up must separate current-readiness evaluation from retained receipt
recovery (for example guard the public context-read wrappers), with its own
contract and tests. Also pending: withdrawal-aware current-observation/list
transport, complete archive enumeration/generation and owner completion fence,
Governance final SQL admission and its immutable-event repair path. None is
supplied by this RF-only admission migration; withdrawal remains ungranted.
