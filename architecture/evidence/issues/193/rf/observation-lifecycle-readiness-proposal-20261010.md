# RF current evidence and observation lifecycle reads

**Proposal, not implementation approval or activation evidence.** Source review on
2026-10-10 (Europe/Oslo), HEAD `f095b0c2898c5e3166dba8c1120f112af82ec457` plus the
uncommitted RF reader and admission-guard changes. RF remains the active owner.
This slice changes no Governance business behavior or archive facade. The pending
[archive-owner decision](withdrawal-owner-dependency-proposal-20261009.md) is not
answered by this proposal. Withdrawal creation remains unavailable.

## Current evidence: fix the read wrappers, preserve replay

The [RF adapter](../../../../../apps/backend/src/talli_backend/adapters/postgres_shareholder_register_filing.py)
now excludes withdrawals in `_read_register_observation(..., current=True)`.
Both the ordinary session and `_SourceAdmission.read_current_register_observation`
use that implementation; the latter uses the held admission connection.
[`_build_capital_receipts` / `build_verified_source_context`](../../../../../apps/backend/src/talli_backend/application/shareholder_register_source_workflow.py)
already resolve each Governance event's exact register reference through that port.
[`ShareholderRegisterSourceAdmission.admit`](../../../../../apps/backend/src/talli_backend/application/shareholder_register_source_admission.py)
rebuilds this context under the existing company/year guard. Consequently its
`read_readiness`, `read_annual_readiness` and the
[`read_review` application path](../../../../../apps/backend/src/talli_backend/application/shareholder_register_source_approval.py)
can reject withdrawn evidence without another readiness algorithm. These two
readiness methods are application seams, not separately mounted HTTP endpoints.

The remaining direct-SQL read gap is precise:

| Existing public wrapper | Existing private shared implementation |
| --- | --- |
| [`read_source_approval_context_v1(uuid,uuid,text)`](../../../../../supabase/migrations/20260924091015_rf1086_source_approval_foundation.sql) | `source_approval_context_internal_v1` |
| [`read_source_approval_context_v2(uuid,uuid,text,text)`](../../../../../supabase/migrations/20260929173935_rf1086_annual_approval_binding.sql) | `source_approval_context_internal_v2` |

In an additive RF migration, make each wrapper call its existing internal function
first, then call
`assert_source_register_observations_active_internal_v1(company,year,sourceId,sourceSha256)`
using that trusted result, and only then return the original result minus
`reviewText`. A small PL/pgSQL wrapper makes execution ordering explicit. Keep the
existing signature, result shape, OID, owner, ACL, volatility and empty search path;
do not restore the v1 runtime grants revoked by annual-approval migration. The
private guard remains ungranted. Existing authorization, fresh MFA, READ COMMITTED
and company/year locks run first; do not acquire locks in another order or invent
an accepted-owner input. On stale evidence, raise the existing safe stale-source
error; do not return an unchanged positive review or invent a new review hash.

Do **not** add this check to `source_approval_context_internal_v1/v2`,
`assert_source_approval_guards_v1`, `lock_year_source_v1`, general source/preview
reads, or submission-head reads. Approval/claim/intent code can call shared context
before its exact replay return. The
[new mutation hooks](../../../../../supabase/migrations/20261009215302_rf1086_withdrawal_source_admission_guards.sql)
must stay after replay and before fresh effects. Keep capture receipt lookup,
retained source correction history, claim recovery, admitted-intent outcomes and
feedback recovery available. A historical receipt never asserts current readiness.

`ShareholderRegisterSourceWorkflow.read_source_preview` uses `_fresh_source`,
whose owner reads span transactions and already reach the same current-observation
predicate. Preserve `GET source-previews/{previewId}` and its existing access rules;
test withdrawal committed before that read. Do not silently reroute it through
`admit`: [Company Access consequential admission](../../../../../supabase/migrations/20260924080208_company_access_rf_admission_guard.sql)
adds fresh-MFA and company-year gates that this ordinary read does not currently
require. Its response is an assessment from its checks, not an atomic cross-owner
snapshot or lease. Guarded readiness/review methods retain their stronger held-scope
checks. `POST source-production-reviews` retains its deliberate bridge preparation.
No pure readiness codec change or additional HTTP readiness endpoint is needed.

## One additive lifecycle query

Add one RF-owned persistence port, illustratively
`read_register_observation_lifecycle_snapshot(Rf1086SourceQuery)`, returning a typed
scoped snapshot of all retained observations, canonical withdrawal receipts and
observation time. Read both families on one repeatable-read connection; verify
the actor and accepted owner on that connection. Retain the existing list's
company/identity eligibility in the application. Use no entitlement, fresh-MFA,
Documents-original, Governance or provider call to establish historical lifecycle.

Use the existing RF table SELECT/RLS grants, not a privileged login or foreign
table access. Parse canonical receipts and cross-check row identity/scope/digest.
Independent scoped counts should reject partial enumeration. No silent pagination,
schema-absence-to-empty fallback, or filtering out withdrawn rows. Missing storage,
permissions or malformed history returns safe unavailable. Invoke the existing
public [`derive_rf1086_register_observation_lifecycle`](../../../../../apps/backend/src/talli_backend/modules/shareholder_register_filing/public.py)
on the complete snapshot: it builds supersession before withdrawal, so withdrawing
a head cannot reactivate its ancestor. The pure helper alone proves neither
completeness nor current authorization.

Add `GET /api/v1/shareholder-register-filings/register-observations/lifecycle`
with generated operation `rf1086ReadRegisterObservationLifecycle` and new schemas.
Return company/year, observed-at and rows containing the existing receipt/draft
facts plus `status: active|superseded|withdrawn`, nullable `supersededBy` and nullable
withdrawal metadata (ID, time, reason, receipt digest). Bind withdrawal metadata to
the row's exact observation identity. Do not expose transport idempotency keys,
storage locators, a fabricated currentness flag, or mutation permission. Keep
draft review confirmations reset; withdrawn/superseded rows are historical views.
The existing RF middleware already supplies `Cache-Control: no-store` on success
and errors. Preserve bearer authentication, scoped authorization, bounded reads,
correlation and safe RFC 9457 errors.

Change only the implementation of the
[old list handler](../../../../../apps/backend/src/talli_backend/main.py), not its
path, operation ID or success/error schemas: consume the same atomic lifecycle
snapshot; when the requested company/year contains any withdrawal, return the
existing 409 problem shape with proposed code
`rf1086_register_lifecycle_upgrade_required`. With no withdrawals, produce exactly
the old receipt/draft/`isCurrent` projection and ordering. Do not map withdrawal to
`isCurrent=false` (the old UI labels that “erstattet”), hide a row using RLS, or
compute a separate withdrawal count in another transaction. Other scopes remain
usable. Current source and capture receipt reads stay unchanged.

## Generated transport and UI

Regenerate OpenAPI/client additively; compare old paths/schemas byte-for-byte.
Extend only the public RF feature export and
[generated-client transport](../../../../../apps/web/features/shareholder-register-filing/transport.ts)
with scoped, duplicate-ID and status/metadata consistency checks. New web on an old
backend may recognize **only route-absent 404** as unsupported lifecycle. Legacy
history may then be displayed with lifecycle unknown; it must not be relabeled
active or provide new lifecycle-dependent eligibility. Never downgrade 401/403,
domain-404, 409, 503, malformed success or incomplete history to an empty list.

The [register page/editor](../../../../../apps/web/app/(owner)/filing/aksjonaerregisteroppgaven/register/page.tsx)
should render explicit “gjeldende”, “erstattet” and “trukket tilbake” labels,
preserve originals, and allow correction only of an authoritative active row.
Update recovery copy: a committed receipt may later be superseded **or withdrawn**.
Keep attempt/key recovery and focus/status announcements intact; no withdrawal
button or fabricated repair action in this read-only slice.

Inventory all old RF-list consumers before activation: register page/editor,
`SupportedCorporateEventWizard`, its route loader, the server action at
`apps/web/app/actions.ts`, and
[`corporate-register-observation.ts`](../../../../../apps/web/app/lib/corporate-register-observation.ts).
They must consume the new RF projection or visibly fail closed for affected scopes.
Any later selector adaptation is transport/presentation work only; do not change
Governance economics, final SQL, recording or evidence-repair policy here. Retained
workspace preview status is historical; do not present it as newly verified readiness.

## Required proof and rollout

- SQL wrappers: both versions reject withdrawn references, preserve valid and
  reference-free results, retain owner/MFA/ACL behavior and reject stale isolation.
  Compare catalogs and review bytes; repeat migration/rollback. Re-run exact
  approval/claim/intent replay and outcome/reconciliation tests after wrapper edits.
- Application: source preview, source readiness, annual readiness and production
  review fail when withdrawal precedes their observation check; current independent
  roots still work. Barrier tests prove both lock orders for the guarded readiness
  and review seams; do not claim a lease for the ordinary preview read. Receipt lookup/history remain available
  after withdrawal and changed originals; no provider call or added bridge write
  occurs on the read paths.
- Lifecycle DB/API: active independent roots, superseded chain and withdrawn head;
  no ancestor revival; same-snapshot before/after withdrawal; exact counts,
  duplicates/corruption, missing table, outsider/revoked owner and cross-year scope.
  Old list succeeds unchanged without withdrawals and returns the scoped safe
  error otherwise. Historical receipt identity remains exact.
- Contracts/web/browser: frozen old schemas; both deployment orders; strict
  route-404 fallback; all three labels, read-only historical rows, accessible
  announcements, exact selected ID/version/hash and uncertain-capture recovery.
  Apply the React review checklist when editing the multiple TSX consumers.

Deploy the additive table/guards and read wrappers before routing the new reader;
missing schema is an unavailable dependency, not captured-empty history. Keep the
withdrawal writer ungranted. New-backend old-list errors cannot protect old binaries
that still SELECT observations and derive successor-only currentness, or old
application readiness paths that bypass the public SQL wrappers. Before the first
withdrawal, prove a route fence/drain covering those producers, reachable immutable
deployments, in-flight requests and rollback targets. Postactivation rollback may
suspend new commands but must retain lifecycle-aware reads and unconditional guards.
An empty-state expand overlap is not proof of postwithdrawal rollback safety.

This read slice does not satisfy archive completion/cancellation coverage or the
Governance evidence-repair dependency. Those remain separate blockers under
[ADR0012](../../../../../docs/adr/0012-govern-the-fastapi-web-and-operational-boundary.md)
and [ADR0013](../../../../../docs/adr/0013-enforce-the-architecture-and-migrate-serially.md).
The technical-first amendment grants no new facade exception or activation.
