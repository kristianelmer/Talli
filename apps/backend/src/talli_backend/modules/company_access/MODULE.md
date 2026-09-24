# Company access backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["public.companies","public.company_cancellations","public.company_deletion_reviews","public.company_eligibility_assessments","public.company_invitations","public.company_memberships","public.company_year_acceptances","public.company_year_admissions","public.customer_agreement_acceptances","public.support_access_grants","public.support_access_operation_receipts","public.support_case_openings","public.support_operators"],"ports":["CompanyAccessGateway","CompanyRegistryGateway"],"publicEntryPoints":["talli_backend.modules.company_access.public"]}
-->

## Purpose

`company_access` owns the versioned eligibility manifest, public provisional
check, definitive material-fact interview, immutable company-year admission and
acceptance evidence, authenticated company access, frozen agreement acceptance
and freshness, accepted-member company records, active operator
context and generated case-bound support grant/revoke/open/read, company invitations, reviewer/read-only
membership administration, and the cancellation-to-deletion lifecycle. It
independently validates the Supabase session and matching bearer subject before
installing a transaction-local actor context for restricted RLS execution.

## Owns and must not own

It owns `public.companies`, `public.company_cancellations`,
`public.company_deletion_reviews`, `public.company_invitations`,
`public.company_memberships`, `public.company_eligibility_assessments`,
`public.company_year_admissions`, `public.company_year_acceptances`,
`public.customer_agreement_acceptances`, `public.support_access_grants`,
`public.support_access_operation_receipts`, `public.support_case_openings`, and
`public.support_operators`, with
the latest ownership migration declared as
`20260924080208_company_access_rf_admission_guard.sql`. The backend system owns
`public.company_access_command_receipts` as technical idempotency state. It must
not claim eligibility outside the immutable active manifest, own physical
business-data deletion, or own unrestricted general operator workflows.
It must not use service-role access or bypass RLS for ordinary business calls.

## Public interface

Import only `talli_backend.modules.company_access.public`.

- Queries: owner-sensitive context, accepted-member company records, active
  operator context and one opened case-bound snapshot, provisional and definitive eligibility,
  invitation/cancellation listing,
  membership listing, and actor-derived pending side-effect continuations
- Commands: atomic company-year admission with eligibility plus current legal
  evidence, append-only company-year eligibility recheck, fail-closed legacy onboarding, owner agreement
  reacceptance, invite, accept, revoke, resend, reviewer/read-only membership
  transitions, owner cancellation request/resume, admin support grant/revoke,
  explicit operator case opening, case-bound independent deletion review,
  and owner finalization
- Error: `CompanyAccessError`
- Ports: `CompanyAccessGateway` and `CompanyRegistryGateway`

Business request contracts are immutable, reject undeclared fields, and live in
this public entry point rather than the composition root. The public names include
`CreateCompanyInvitationRequest`, `InvitationTokenRequest`, `AcceptCompanyInvitationRequest`,
`CompanyInvitationCommandRequest`, `AdministerCompanyMembershipRequest`,
`CompanyAccessService`, `CompanyContext`,
`CompanyContextResponse`, `CompanyInvitation`, `CompanyInvitationResponse`,
`CompanyInvitationListResponse`, `InvitationLookup`, `CompanyMembership`,
`CompanyMembershipResponse`, `CompanyMembershipListResponse`, `InvitationRole`,
`MembershipState`, `InvitationSideEffectContinuation`,
`InvitationSideEffectContinuationList`, `InvitationSideEffectCompletion`, and
`company_access_adapter`.

Onboarding and the backend-only company read boundary add
`CompanyOnboardingRequest`, `CompanyOnboardingResponse`,
`CompanyAgreementAcceptanceRequest`, `CompanyAgreementAcceptanceResponse`,
`CompanyAccessRecord`, `CompanyAccessRecordResponse`,
`OperatorContextResponse`, `GrantSupportAccessRequest`,
`RevokeSupportAccessRequest`, `OpenSupportCaseRequest`,
`SupportAccessGrantResponse`, `SupportCaseOpeningResponse`,
`SupportCaseResources`, `SupportCaseSnapshotResponse`, `CompanyRegistryGateway`, and
`company_registry_adapter`.

The previous v1 operator-company search shape remains temporarily as a deprecated,
authenticated, always-empty mixed-revision overlap. It performs no customer-data
query and is outside the active generated web surface; removing the shape requires
the bounded API-major contraction governed by ADR-0012.

The accepted-member company record also has one versioned, read-only database
query contract for backend workflows that must compose company identity with
other capability facts in the same transaction. The function is owned by the
non-bypass `company_access_executor`, applies company-access RLS, binds the
explicit subject to transaction-local verified actor context, and grants callers
no direct access to `public.companies` or `public.company_memberships`.
Its company-access-owned expand and rollback migrations keep the contract's
lifecycle outside every consuming capability migration.

Pilot administration consumes a second company-access-owned database contract,
`company_access_is_accepted_owner_subject_v1`. The narrow security-definer
predicate requires a verified active admin with fresh MFA and returns only
whether the system-user request's initiating subject is still an accepted
owner. Billing receives `EXECUTE` only; it receives no membership-table grant,
row shape, or membership-policy ownership.

Eligibility and admission add `EligibilityAnswer`, `EligibilityDecision`,
`EligibilityPublicFacts`, `EligibilityQuestion`, `EligibilityPrecheckRequest`,
`EligibilityDefinitiveRequest`, `EligibilityDecisionResponse`,
`CompanyYearPromise`, `CompanyYearAdmissionRequest`,
`CompanyYearAdmissionResponse`, `CompanyYearAdmissionGatewayCommand`,
`EligibilityRecheckTrigger`, `CompanyYearEligibilityRecheckRequest`,
`CompanyYearEligibilityStateResponse`, and
`CompanyYearEligibilityRecheckGatewayCommand`. `capability_manifest.json` is the single
versioned support/clarify/block source. Its canonical JSON digest is returned by
both public operations and persisted with the accepted company year. Public
precheck uses registry facts only and is always visibly provisional. Definitive
evaluation asks exactly the manifest questions, treats unknown as clarification,
and lets a known hard block outrank clarification. Admission re-fetches registry
facts and repeats the evaluation before any write. The legacy AS-only onboarding
operation remains in v1 solely as a deprecated, fail-closed response and can no
longer create a company.

Cancellation contracts add `CompanyCancellation`, `CompanyCancellationListResponse`,
`CompanyDeletionReview`, `RequestCompanyCancellationRequest`,
`ResumeCompanyCancellationRequest`, `ReviewCompanyDeletionRequest`, and
`FinalizeCompanyDeletionRequest`. During the expand/deploy overlap, query
responses continue to decode legacy `export_required` rows; new requests never
create that state. Resume advances the exact revision-bound legacy row only after
a current authoritative archive receipt exists.

The system boundary injects `SupabaseCompanyAccessAdapter` and the bounded
`BrregCompanyRegistryAdapter`; capability policy never constructs Supabase,
PostgreSQL, or HTTP infrastructure. Production registry lookup is restricted to
the official HTTPS host; only loopback HTTP fixtures are accepted. Redirects,
oversized/non-JSON responses, malformed registry identities, and provider
failure fail closed before a business write. Owner context and administration
require accepted owner membership and AAL2. Invitation lookup and acceptance bind
the validated subject and normalized Auth email to a pending, unexpired token hash.
Acceptance and every role/removal transition execute in one database transaction
as the restricted `company_access_executor` NOLOGIN/NOINHERIT/NOBYPASSRLS role.
Pending recovery and completion use the separate restricted
`company_access_recovery_executor` role with only actor-owned receipt, exact audit
evidence, and workspace-invitation outbox policies. Explicit RLS policies remain
the authorization boundary even though the RPCs are security definers; neither
executor owns a table, inherits another role, or bypasses RLS.
Supabase's migration role cannot delegate `auth` schema usage. Versioned
migration-owned claim wrappers expose only the current request UID and JWT to
authenticated company-access policies and the two executor roles; public and
anonymous execution, direct Auth helper execution, Auth schema usage, and
executor schema creation remain denied. Function ownership transfer grants the
migration role only transient `SET` membership and grants the executors only
transient `CREATE` on `public`, revoking both in the same atomic block.
Forced RLS applies only to the technical command-receipt table; invitation and
membership RLS is genuine because the command executor is a non-owner with
NOBYPASSRLS.
Durable operation receipts replay consequential commands and optimistic expected
revisions reject competing resend, revoke, and membership changes. If a command's
transport outcome is unknown, the adapter retries the identical operation once;
the receipt returns the committed result instead of repeating the mutation.
Cancellation commands and their reconciliation RPC share an actor+operation
transaction lock. Reconciliation recomputes the normalized request fingerprint
from the original typed inputs, so an absent receipt is definitive before the
backend retries the exact operation ID and payload.
Invitation commands atomically leave their receipt continuation pending until the
web's exact actor+operation+purpose UUIDv8 audit evidence exists. The
recovery endpoint derives the actor from Auth, returns at most twenty of that
actor's continuations, never invokes a business command, and completion locks the
receipt, reauthorizes the actor's current accepted membership (and owner AAL2 for
owner commands), and verifies audit evidence. It then captures one advancing
post-lock timestamp for both the outbox RLS check and persistence decision, so it
atomically inserts/reconciles outbox evidence only while the receipt remains
unexpired. Even an already-completed retry must pass current authorization before
idempotent success. Completion clears the sole receipt token and scrubs legacy
delivery fields. Expired continuations
remain recoverable for audit evidence, but their token is cleared and obsolete
delivery is not queued; a new invite/resend is required if delivery is still
wanted.
Owner creation, demotion, and removal are not exposed. Public responses never
contain token hashes.

The admission RPC is backend-only and executor-owned. One short transaction
creates or reuses the company and owner membership, appends the current customer
agreement when needed, and appends the supported assessment, company-year
admission, privacy/terms/DPA/capability acceptance, and durable receipt. Exact
retries return the same company and admission IDs; a changed payload conflicts.
The admission row stores the exact canonical capability-manifest and complete
company-year-promise snapshots plus their digests. A later manifest version can
therefore never rewrite what the owner accepted. The three admission tables have RLS, no browser/service-role grants, and mutation
triggers that reject update or delete even for the migration owner. Failure at
any insert leaves no company, membership, evidence, admission, or receipt.

The eligibility-recheck RPC is also backend-only and executor-owned. It first
authorizes the accepted owner and locks the admitted company year, then appends
one assessment against the latest assessment ID with durable idempotency and
compare-and-swap protection. It accepts only the manifest's declared triggers,
re-fetches public registry facts, asks the complete current manifest, and records
one of `CONTINUE_COMPANY_YEAR`, `PAUSE_AND_CLARIFY`, or
`STOP_EXPORT_AND_CONTACT` with the exact Norwegian next step. Payment, filing,
and other consequential operations can consume the recorded fail-closed state as
their capabilities migrate; #187 does not change those future capability writers
under ADR-0013. Read access remains available, and the readiness of any existing
archive/export is not narrowed by the outcome.
Provider or Talli failure records no assessment and is never presented as an
eligibility rejection. The admission's accepted manifest and promise snapshots
remain unchanged across every recheck.

Before completion, a create/resend delivery token is stored in exactly one receipt
column; receipt JSON contains only token-independent delivery metadata. Atomic
completion builds delivery from that committed metadata and token, inserts the
outbox row, and clears/scrubs the receipt in one transaction. Acceptance,
revocation, newer resend, and expiry recovery apply the same receipt scrub.
After the staged `20260826101000` contract is applied, authenticated Data API,
anonymous, and service roles have no direct grant on any company-access business
table or RPC. The backend still validates `/auth/v1/user`, but every business
read and write uses the NOLOGIN/NOINHERIT/NOBYPASSRLS executor with
`talli.verified_actor_id` and bounded claims set transaction-locally. Missing or
mismatched bearer subjects fail closed. Authenticated Data API roles have no receipt-table grant. #160 adds no
clock-driven purge. An expired token is never returned, and a pending-side-effect
recovery read clears it. Until recovery or another clearing command touches the
receipt, the expired token can remain stored at rest. Retention/delivery migration
remains #156. This is delivery-secret persistence, never token-hash disclosure.

Runtime configuration requires `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and a
restricted backend connection in `TALLI_COMPANY_ACCESS_DATABASE_URL` whose login
role may `SET ROLE company_access_executor` (and the separately bounded recovery
executor). `BRREG_BASE_URL` defaults to `https://data.brreg.no`; a custom value is
accepted only when it is that provider or a loopback fixture. Optional
`BRREG_TIMEOUT_SECONDS` is bounded above by ten seconds.

Cancellation requests, legacy resume, and finalization require an accepted owner with an AAL2
authentication method no older than fifteen minutes. Independent approval or
rejection requires an active admin support operator with the same fresh MFA; an
owner cannot review their own request. The append-only deletion-review row is the
authoritative company-scoped legal/security evidence. Request and finalization
RPCs re-derive the archive audit, document, and artifact prerequisites while the
transaction is locked, and durable receipts replay an identical outcome after an
unknown transport result. Finalization records the lifecycle marker but never
physically deletes company business data. RLS conceals outsiders and permits only
accepted members or active support operators to list lifecycle evidence.
Legacy duplicate active rows are deterministically ranked by updated time,
request time, and ID. The survivor remains active; each loser becomes the terminal
`superseded` status with structured evidence and deterministic audit evidence.
Legacy authenticated table policies conceal superseded rows, while the generated
query RPC retains complete history.

The rollout is staged. Release A's automatic runner applies `20260801090000` only: it expands the
RPC/RLS boundary while the prior web policies still work. Release B deploys the
backend and generated-client web revision, verifies create/resend receipt replay,
and leaves that overlap in place. The destructive `20260801091000` artifact lives
under `supabase/contract-migrations`, outside the declared automatic runner.
Release C moves that immutable artifact into a later release's migration set; it
contracts only #160's direct invitation and membership policies. Before Release C,
rollback means returning to the prior web/backend revision while retaining the
additive database objects. After Release C, application rollback is bounded to a
generated-client revision; restoring the direct writer would require a reviewed
forward migration that reinstates the overlap and is not an implicit rollback.
The PostgreSQL runtime test executes the old direct writer, contract transition,
and new RPC writer in that exact sequence.

Cancellation follows the same expand/deploy/contract discipline. Release A applies
the additive `20260808120000` migration while the legacy direct writer remains
valid. Release B deploys the generated-client backend/web workflow and verifies
legacy `export_required` reads plus RPC receipt replay. Release C applies the
reviewed `20260808121000` contract artifact, revoking direct authenticated table
access while retaining the query and command RPCs. After that contraction, an
application rollback is bounded to a generated-client revision; restoring direct
persistence requires a new forward migration.

Ownership is authoritative here. Remaining compatibility adapters are registered
by exact path/rule/resource/operation. Until #157 owns published archive
projections, `company_access` consumes the bounded legacy generation/receipt
projection produced only by the existing server-side archive route; it does not
own archive composition or those three projection tables. Every source in
`architecture/company-archive-sources.json` participates in the same locked
generation protocol. A single company advisory-lock namespace serializes all
years and every company-wide source mutation, avoiding cross-year lock inversion.
The route begins the archive attempt before reading the company row and fails
closed if any declared read fails. Completion rejects the attempt if any source,
including company metadata, changed after begin. It
performs no write after receipt completion. Audit events remain archive inputs:
request and review audit writes intentionally stale the preceding receipt, so an
owner must export a new archive after independent approval before finalization.
Until #155 owns the
audit capability, lifecycle RPCs retain the exact append-only audit seam for
observable events, never as deletion authorization. Notification rows remain
owned by their exact technical scopes.

## Collaboration and tests

The backend-system company-access workflows serve the generated contract. Focused
policy and adapter coverage is in `apps/backend/tests/test_company_access.py`;
transactional schema coverage is in
`tests/company_access_invitations_schema.test.mjs` and
`tests/company_access_cancellation_schema.test.mjs`; fresh-PostgreSQL RLS coverage
is in `tests/company_access_database_runtime.test.mjs`.

## Compatibility and change rule

There are no direct-web company-access invitation, membership-administration, or
cancellation persistence exceptions. The manifest truthfully declares the
bounded #155 audit and #157 archive-projection dependencies described above.
Change this document and `module.json` together when its interface, ownership,
policy, or dependencies change.

## Locked annual purchase evidence (#192)

`CompanyYearPurchaseBasis` and its `CompanyYearLegalEvidence` preserve the accepted
company-year promise, original and current assessment references, answers hashes,
manifest, acceptance identity/time, and current legal document evidence.
`CompanyAccessService.purchase_basis` consumes a supported `before_payment` recheck
and rejects mismatched scope, stale legal documents or a changed promise.

`supabase/migrations/20260905080550_annual_billing_purchase_basis.sql` adds
`company_access_purchase_basis_v1(uuid, integer, uuid, uuid)`, owned by the restricted
Company Access executor. Its caller must be an accepted owner with fresh MFA; it
holds the existing eligibility-recheck lock and matches the exact latest assessment
from the preceding five minutes. Billing has EXECUTE only and must re-read and
compare this basis inside the payment-claim transaction, including the expected
legal acceptance ID. It gains no direct access to Company Access tables. This
contract does not authorize a background worker to impersonate an owner. The
matching rollback removes the function and preserves all immutable evidence.
The locking projection uses an asynchronous connection, a ten-second total
deadline, five-second statements and a one-second lock timeout. A lock failure
returns the typed unavailable response and a later request reuses the same basis.


## Guarded RF admission projection (#193)

`public.company_access_read_rf_admission_v1(company_id, income_year, verified_subject)`
is the narrow Company Access SQL contract for RF consequential admission. Only
RF's restricted executor and store owner receive EXECUTE; no consumer receives
Company Access table privileges. The non-bypass Company Access executor owns the
SECURITY DEFINER function, with an empty search path and its existing RLS policies.
It verifies the explicit subject, accepted owner and fresh MFA, then acquires the
company-wide archive advisory guard before rereading owner, current agreement,
year eligibility and confirmed/locked active AS identity. Its JSON projection
contains only company/year, organization number, legal name, entity type, address,
postal code, city, identity timestamps and the two affirmative admission flags.
Failure returns no partially authorized identity.

This new VOLATILE admission query requires READ COMMITTED. Each post-wait query
therefore receives a fresh statement snapshot; a transaction snapshot established
before waiting is expressly rejected. The existing company-year eligibility
predicate now acquires company before its eligibility advisory lock, preserving
legacy read isolation compatibility. No claim of consequential freshness is made
for a legacy REPEATABLE READ caller. The existing MFA predicate now uses a
VOLATILE wall-clock check so its unchanged 15-minute rule also expires during a
guard wait, instead of continuing to compare with the outer statement start.

The additive migration acquires company guards before local locks in company-year
admission, agreement reacceptance, eligibility recheck, invitation acceptance,
membership administration, and cancellation request/resume/review/finalization.
Invitation acceptance binds its initial company lookup to the subsequent locked
reread. New company creation reaches its guard through the BEFORE INSERT trigger;
the removed AS-only onboarding SQL writer stays absent. Current function bodies,
legal constants, signatures, owners and ACLs are preserved by a checked,
idempotent entry-point rewrite. Authority-request/Billing-entitlement functions
are not rewritten by this migration.

Six owner-table INSERT/UPDATE/DELETE backstops cover companies, memberships,
eligibility assessments, admissions, year acceptances and customer agreement
acceptances. They lock changed company IDs in sorted order, including allowed
legacy direct writes in overlap topology. A row trigger by itself cannot establish
pre-row-lock order, so public commands acquire the guard first. Operator access
and invitation delivery state do not grant RF accepted-owner admission and are
outside this projection. Existing privileged maintenance still must respect
company-first ordering when deliberately taking local row locks before writes.

Safe rollback revokes only the new RF admission contract, preserving guarded
writers, evidence, role options and existing narrow helper grants. Migration
setup borrows only missing role SET, public-schema CREATE and trigger-function
EXECUTE privileges and restores their prior state. Replay restores
the admission grant. Mandatory two-session, ACL, isolation and migration replay
coverage is in `test_company_access_rf_admission_database.py`; collection is not
runtime acceptance. This owner contract alone does not complete RF's cross-owner
approval/send transaction, which must compose every owner projection before its
durable claim.
