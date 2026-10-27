# Annual Accounts Filing

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["annual_accounts_filing.authority_permissions","annual_accounts_filing.authority_test_runs","annual_accounts_filing.filing_overrides","annual_accounts_filing.filing_previews","annual_accounts_filing.filing_review_comments","annual_accounts_filing.filing_submissions"],"ports":["AnnualAccountsAuthority","AnnualAccountsRehearsalIO","AnnualAccountsWorkspacePersistence","AnnualAccountsPreparationPersistence","AnnualAccountsEvidencePersistence","AnnualAccountsSourcePersistence"],"publicEntryPoints":["talli_backend.modules.annual_accounts_filing.public"]}
-->

## Purpose

Own deterministic annual-accounts filing rules, RR0002 documents, readiness,
preparation controls, evidence import, retained history and the test rehearsal
lifecycle. The complete web slice uses FastAPI and the generated client. Explicit
cutover establishes the owned store as the single writer; contract removes all
six generic filing tables. Authority work remains accessible only through the
existing explicitly approved synthetic test gate and fixed TT02 adapter.
Production stays disabled.

## Owns and must not own

Accounts owns its ordered 21-field projection, feedback and deterministic XML.
Ledger owns the accounting entries. Corporate Governance and Documents own close
and signed-artifact facts. Annual owns common readiness aggregation and Billing
owns commercial eligibility and refunds. The named application workflow supplies
immutable source snapshots; the capability cannot discover other owners' tables.

## Public interface

Import only `talli_backend.modules.annual_accounts_filing.public`.
`AnnualAccountsSource` copies and recursively freezes Annual and ordered Ledger
facts. `build_annual_accounts` returns `AnnualAccountsCandidate`, whose notes,
fields and feedback are also recursively immutable. The candidate is a preview,
not an authorization, completeness attestation or evidence of authority acceptance.

`AnnualAccountsRenderInput` binds the candidate to organization, company name,
contact, approval date and confirming representative. `render_annual_accounts`
returns `AnnualAccountsDocuments`, preserving the released header, field/ORID,
blocking-code, contact, period, currency, integer and consistency validation
order. Invalid content raises the characterized `ValueError` message. Static XML
templates preserve original namespaces, element order, escaping and final newline.

`assess_annual_accounts_readiness` returns ordered `AnnualAccountsReadinessIssue`
values. `AnnualAccountsCorporateReadiness` carries the existing enabled flag and
Corporate-owned blockers. The pure contract does not certify their origin; the
durable filing workflow must obtain them through the owning public contracts.
General meeting approval, ledger scope, payload feedback and accepted/unaccepted
manual warnings retain their original order. Common Annual gates remain separate.

## Data and effects

Six successor tables in `annual_accounts_filing` are declared and owned:
`authority_permissions`, `authority_test_runs`, `filing_overrides`,
`filing_previews`, `filing_review_comments`, and `filing_submissions`.
They have FORCE RLS. Read and preparation policies require cutover or contracted
phase, accepted membership and the appropriate owner/reviewer role. Expansion
remains unavailable through every owned business contract.
Before explicit cutover, the legacy public writer remains authoritative. Cutover
reconciles all six families by count and digest and fences the legacy tables;
contract removes them. Paired rollback restores the latest owned rows and original
access definitions before returning authority to the legacy writer. Owned
contracts fail closed during expansion and after rollback.
On [PostgreSQL17](https://www.postgresql.org/docs/17/role-attributes.html), a non-superuser CREATEROLE migration principal receives the
engine's bootstrap-granted ADMIN membership only for newly created owner/executor
roles. This is real role-management authority: ADMIN can subsequently grant access.
The expansion suppresses optional creator SET/INHERIT self-grants. Every preexisting
membership and borrowed execution grant is restored exactly, including its grantor
and Boolean options; the tests allow only the two positively identified creation
management grants and retain exact outer-rollback checks.

No storage bucket is added.
`AnnualAccountsAuthority` declares the fixed TT02 operations and
`AnnualAccountsRehearsalIO` declares exclusive evidence ownership, local file, clock, XML and credential seams.
`annual_accounts_authority_adapter` registers implementations.
`AnnualAccountsRehearsalConfiguration` holds nonsecret declarations, and
`AnnualAccountsAuthorityError` carries sanitized failure metadata.
Their registered adapters retain transport mechanics; Accounts owns the ordered
rehearsal guards, checkpoints, retries and human-signing continuation.
`rehearse_annual_accounts` returns an immutable summary.
`prepare_annual_accounts_for_signing` preserves create/upload/validate/lock/handoff
order and refuses to lock after validation errors. Neither contract signs.
The local CLI retains the exact explicit test gate, scopes, synthetic case and
organization checks. A nonblocking lock on the canonical evidence path is held
from before case/evidence reads through the final checkpoint. The local adapter
locks a persistent sidecar so atomic evidence replacement cannot release ownership.
Concurrent runs, including separate processes and directory aliases, fail before
credentials; all exits and process termination release the lock. The sidecar must
remain in place between runs. This contract coordinates the local POSIX filesystem;
changing evidence paths is not authority reconciliation.
It writes intent before credentials or provider work, reuses
existing uploads, reads receipt state after human signing and replays completed
evidence without constructing a provider. Credential setup remains outside the
provider error-catching block. Before create-instance and signing-lock calls, a
durable pending-operation marker is saved. Lost responses, malformed results,
interruption or failed success-checkpoint writes preserve that marker and block
rerun before credentials or provider access. Legacy ambiguous checkpoints also
require reconciliation. A confirmed lock with a lost handoff resumes through
submission reads; it cannot relock. Same-payload uploads to known data identities
retain their original PUT retry behavior.

Successful HTTP validation requires a recognized issue list and severities.
Malformed evidence and unknown severities block before lock. Official numeric
severity 1 is an error; 2–5 retain their documented nonblocking meanings. Existing
named severities and their output casing remain supported. Lock and handoff
responses must positively identify the signing task. These #132 safety corrections
intentionally tighten inherited ambiguous-failure behavior; frozen statutory
payloads, valid TT02 documents and successful request order remain unchanged. The generated client and authenticated persistence boundary enforce accepted
membership and fresh MFA where required. The old direct RLS observations do not authorize
unaccepted membership or skipping fresh MFA in the future request boundary.

## Compatibility and failures

Live calculations retain ECMAScript binary64 reduction order, Number coercion,
half-up rounding toward positive infinity and signed zero. XML uses UTF-16 text
length, ECMAScript whitespace, safe whole integers and the Date.UTC year-0–99
rejection. These rules are local to the released Accounts profile, not shared
accounting policy or a dependency on Tax internals.

The offline public-data profile has distinct 22-field, Python-rounding,
account-coverage and attachment semantics. `AnnualAccountsOfflineSource` receives
the existing common Annual totals, common readiness issues and Accounts flags.
`build_annual_accounts_offline_payload`, `assess_annual_accounts_offline` and
`simulate_annual_accounts_offline` own the Accounts projection, attachment rules,
ordered Accounts blockers, preview and simulated receipt. The simulation returns
`AnnualAccountsOfflineSimulation`; all nested outputs are immutable. This profile
does not emit live XML or certify production readiness.

The existing root `holding_core.annual` public functions now adapt source/output
shapes to these contracts. Their Accounts-specific implementations are removed.
Common AnnualData totals, common readiness, Tax and Archive behavior remain byte
unchanged at the function/class definition level. These are existing common
source facts, not a second Accounts calculation or a new shared-kernel package.
The CLI remains a consumer of the same root public interface, preserving its
JSON, text, exit status and errors. Backend capability code never imports the
legacy root model.

`AnnualAccountsEvidenceInput` freezes an untrusted TT02 document and binds it to
the company, actor and workflow-supplied recording time. The pure
`import_annual_accounts_evidence` returns `AnnualAccountsEvidenceProjection` with
the original ordered validations, hash composition, references and Norwegian
errors. The result remains `pending`; a signed and archived TT02 receipt does
not imply accepted evidence or production readiness. The workflow must authenticate
the actor, authorize membership and MFA, and persist the projection separately.

The released importer accepts V8's permissive finite `Date.parse` inputs after
ECMAScript trimming. A local parser adaptation preserves this compatibility;
its BSD license is included as `V8-LICENSE`. It only tests finite acceptance and
does not assign an authority timestamp. At TimeClip endpoints it uses the existing
PyICU dependency and process timezone, matching the pinned Node ICU behavior.
Recording time is explicitly supplied by the workflow, so this pure operation
does not read the clock. Unlike the Tax profile, this released Accounts profile
does not validate otherwise unused income-year or secrets flags.

## Tests

`apps/backend/tests/test_annual_accounts_filing.py` compares the public contracts
against immutable predecessor outputs: 67 payload cases, 175 exact XML/error cases,
11 readiness cases and nested immutability. The review follow-up includes deeply
nested ignored metadata and signed integer overflow probes. Architecture enforcement reconciles
the module manifest, documentation and language-aware dependency evidence.
`tests/test_annual_accounts_offline_migration.py` verifies 46 frozen root API cases
and 14 actual CLI executions against pre-migration output. Existing Annual, Tax
and Archive tests remain active. `test_annual_accounts_evidence.py` checks 43 frozen
evidence results, 1,804 actual importer date cases, 4,320 TimeClip cases across six
timezones, and immutable inputs/results. The old standalone transport path and final Node payload subprocess are retired.
The CLI maps directly to the owned Python calculation and XML contracts.
The generated web workflow reads and writes through the owned boundary. Explicit
cutover, contract and paired rollback artifacts preserve source provenance,
latest state and the Archive invalidation behavior. The durable source contract below carries positive history coverage. Full
stage-exit gates and protected integration are tracked separately in issue #153.

## Authenticated filing boundary

`AnnualAccountsWorkspaceQuery` and `AnnualAccountsFilingRows` expose complete,
immutable Accounts rows scoped to company and optional year. Permissions and
test evidence retain their predecessor company-wide scope. Invalid identities,
cross-company/year rows, missing linked previews or test evidence and non-Accounts
obligations fail closed. `AnnualAccountsPreparationPersistence` owns normalized
override/review controls and owner acknowledgement, permission and manual evidence.
Company Access supplies accepted-role and fresh-MFA decisions through its public
contracts. `AnnualAccountsEvidencePersistence` reads Company Access identity and
inserts the pure TT02 projection once per request. Audit remains the existing
subsequent web continuation; no provider call or Tax-style combined submission
or deduplication is added. The verified application session binds every actor;
PostgreSQL functions run only via the restricted executor with phase-gated RLS.
Web workspace, Annual and Archive composition use the generated HTTP boundary;
Audit and Notification continuations retain their existing persistence chains.

`AnnualAccountsRecordId` and `AnnualAccountsRecordQuery` identify an owned record.
`RecordAnnualAccountsOverride`, `AddAnnualAccountsReviewComment`,
`ConfirmAnnualAccountsPermission`, and `RecordAnnualAccountsTestEvidence` carry
actor-bound control inputs; `AnnualAccountsRecordedResult` returns the persisted
identity and scope. `normalize_annual_accounts_override`,
`normalize_annual_accounts_review`, and `normalize_annual_accounts_test_evidence`
preserve the released text trimming, validation order and messages.
`AnnualAccountsError` distinguishes forbidden, missing, invalid and unavailable
operations. `annual_accounts_persistence_adapter` declares the registered adapter.
`ImportAnnualAccountsEvidence` freezes the untrusted document,
`AnnualAccountsCompanyIdentity` carries Company Access's organization, and
`ImportedAnnualAccountsEvidence` returns the inserted ID and TT02 reference for
the subsequent Audit continuation.

## Explicit physical cutover

The cutover requires exact source structures and inventoried function definitions,
positive Accounts provenance and six matching count/digest reconciliations. It
rejects quarantine and untraceable successor rows, then fences the empty generic
tables before enabling owned writes. The contract drops those six empty tables.
Contract rollback restores their schema, access, indexes and triggers with the
write fences intact. Full rollback restores the latest owned rows, including new
evidence and acknowledgements, and fences owned writes before returning authority
to the generic store. Migration phases are transactionally locked.

RF blocking-override checks, Documents evidence retention and Company Access
support history call restricted Accounts-owned factual contracts. Tax's
predecessor-retirement coverage accepts the verified final generic retirement.
Only those four inventoried callers are rebound. The revoked historical
`public.remove_unlinked_document` and migration-only RF legacy classifier remain
historical definitions; neither is a live Accounts consumer. These artifacts are
explicit release steps; adding them to the repository does not apply them to a
hosted database or authorize production filing.

## Immutable source handoff

`AnnualAccountsSourceQuery` binds a company, year and verified owner to one
repeatable-read `AnnualAccountsSourceSnapshot`. `AnnualAccountsSourcePersistence`
returns complete owned rows, technical migration coverage and observation time.
`project_annual_accounts_source` publishes immutable `AnnualAccountsSourceFacts`:
evidence identity/version/digest, readiness, history coverage, recorded submissions,
potential production attempts, correction links, incidents and outcomes. The
source HTTP query and generated client expose that public factual contract.
`AnnualAccountsSourceEvidence` binds identity, version, digest and observation time.
`AnnualAccountsHistoryCoverage` states the proven extent and missing evidence.
`AnnualAccountsSubmissionFact`, `AnnualAccountsIncidentFact`,
`AnnualAccountsOutcomeFact` and `AnnualAccountsCorrectionLink` retain recorded
history without inferring external effects or commercial eligibility.
`verify_annual_accounts_source` rechecks the same scope and evidence against a
later complete snapshot; changed state, future evidence or missing coverage fails.

Coverage is limited to Talli-recorded Accounts company/year history. Complete
history requires all six declared families, valid preserved source/inventory
hashes, reconciliation, retained submission identities, exact writer fences or
verified final generic retirement, original mode constraints and complete current
enumeration. Absent coverage is unavailable; other incomplete evidence never
proves no production. A production-labelled or unknown mode remains an unknown
attempt. Local timestamps remain observation times, incident attribution remains
unknown, and test receipts are never authority acceptance for production.

Production-disabled is a decisive Accounts-owned readiness block. This source
contract does not certify missing Corporate close or signed-artifact prerequisites,
and a stored permission or TT02 receipt cannot lift it. Billing alone applies
commercial classification, charges and refunds. Raw caller-supplied readiness
previews are separate from this durable snapshot and never certify history.


## Pinned durable-delivery document boundary

`AnnualAccountsDocumentsInspection` binds exact raw main/company XML hashes,
organization, year and a content-pinned resource generation. It carries no filing
readiness, signature, submission or acceptance assertion.
`AnnualAccountsSchemaValidator` and `annual_accounts_schema_adapter` declare the
offline `talli_backend.adapters.annual_accounts_schemas.PinnedAnnualAccountsSchemas`
implementation. Its four exact public resources were fetched from the RR0002
TT02 app on 2026-10-26: application metadata, BPMN and both JSON model schemas.
The two task identifiers are `Utfylling` and `Signering`; the public process
separates confirm from sign, and system-user authority cannot perform person
signing.

The local validator derives a strict XML subset from the pinned JSON models'
XSD annotations, internal definitions, required/occurrence constraints, fixed
attributes, scalar bounds and enums. Unknown schema constructs, external
references, extra XML, DTD/entities, processing instructions, non-UTF8, oversized
or over-deep documents fail. The local profile additionally restricts the packet
to 2025, AS/small-enterprise, NOK/whole kroner, standalone unaudited statements.
It rejects upstream wildcard attributes rather than ignoring them. This is not
an upstream XSD and does not certify the authority's custom validation. The
existing renderer and its frozen byte contract remain unchanged.

<!-- architecture-inventory
{"ports":["AnnualAccountsSchemaValidator"]}
-->

## Complete local preparation

`AnnualAccountsDeliverySource` retains complete owning Annual history, Ledger
reporting history including amendments and effective entries, and Corporate
current-source readiness plus lifecycle evidence from one verified repeatable
snapshot. `annual_accounts_delivery_digest` binds immutable canonical facts.
Accounts does not reproduce Annual's common readiness or Corporate's lifecycle
policy. Corporate reuses its owner-authorized current-source query on the same
connection; the adapter borrows only the existing restricted read roles and
restores them through savepoints. No session or provider HTTP occurs in that read.

`prepare_annual_accounts_delivery` derives the approval date from the current
finalized signed annual-close decision and renders the unchanged RR0002 pair.
Its narrow projection rejects unknown accounts, missing workforce, unsupported
regimes or attachments, unreviewed warnings, fractional net account balances,
contra expenses and amounts outside its declared precision bound. Ledger owns
which amended entries remain effective; Accounts nets these effective account
movements before using the frozen calculator, retaining every original.

`AnnualAccountsDeliveryDraft` binds exact rendered XML, source, owner command and
local schema inspection. `decode_annual_accounts_delivery_draft` rejects changed
bytes, duplicate or unknown keys/versions, noncanonical JSON, wrong scope, invalid
actors and mismatched source/document hashes. A draft is prepared evidence only.
It grants no common readiness, runtime admission, signature or filing permission.
Correction lineage and actual signed-session desktop/touch verification remain
required before this capability's delivery journey is complete.

## Reader-first delivery retention

`PrepareAnnualAccountsDeliveryDraft`, `StoredAnnualAccountsDeliveryDraft` and
`AnnualAccountsDeliveryDraftPersistence` bind a command to one exact draft. The
`AnnualAccountsDeliveryDraftFact` source projection says `prepared_only`.
`annual_accounts_filing.delivery_drafts` and the reserved
`annual_accounts_filing.delivery_events` extent are immutable, RLS protected and
archive tracked. Source v2 requires positive exact eight-table coverage, retained
counts and hashes, unchanged retention guards/keys, and an empty event journal.
Nonempty events require a successor codec; they are never silently omitted.
Source v1 keeps its bytes and cannot cover the added stores.

The deferred CLI-created contract
`supabase/contract-migrations/20261026221935_annual_accounts_delivery_store_v1.sql`
starts draft writes closed. Its same-named rollback closes writes while preserving
all originals, immutable guards and readers. Preparation performs authorized exact
replay first, then reads current owning source in a repeatable snapshot while the
published company write guard is held, and rechecks current owner/MFA before
storage. There is no provider I/O, event append, signature or dispatch in this
stage; no runtime API is wired by default.

<!-- architecture-inventory
{"ownedTables":["annual_accounts_filing.delivery_drafts","annual_accounts_filing.delivery_events"],"ports":["AnnualAccountsDeliveryDraftPersistence"]}
-->

## Exact delivery read originals

`AnnualAccountsReadPurpose` and `AnnualAccountsDeliveryOriginal` retain bounded
exact base64 bytes with the known instance/data identity, media type, HTTP status
and observation time. `AnnualAccountsDataElement` and
`AnnualAccountsInstanceInspection` describe the strict standalone instance subset
from `inspect_annual_accounts_instance`. Only known owner/app scope, supported
Utfylling/data or Signering/signing tasks, coherent end/archive times, exactly one
Hovedskjema and Underskjema, and bounded generated PDF/signature references are
admitted. Attachments, duplicate/unknown data and contradictory process metadata
block the supported path. Pinned XML/PDF/signature scan-disabled types admit absent
scan results; explicit pending, unsafe or unknown results do not prove progress.
`inspect_annual_accounts_validation` requires a recognized complete validation
array or sole validationIssues wrapper; unknown controlling flags, duplicate JSON
keys and unrecognized severities fail. Raw originals remain separate from these
interpretations. No signature authenticity, registry acceptance or dispatch is
asserted by an original or inspection.

`AnnualAccountsDeliveryBinding`, `AnnualAccountsDeliveryReview`,
`AnnualAccountsFiniteAdmission`, `AnnualAccountsDeliveryIntent` and
`AnnualAccountsDeliveryCompletion` describe exact immutable local operation
records. `AnnualAccountsDeliveryStage` separates prepare, confirmation review and
person signing review. `AnnualAccountsAuthorityPort` separates system user,
person and known-read admission; `AnnualAccountsDeliveryAction` fixes the five
allowed POST/PUT operations. Admissions are exact loopback, actor/company/year/
draft/database/credential bound, at most 300 seconds with bounded budgets. The
system port cannot sign, the person port is fixed to its retained review and
known instance, and known-read admission carries no mutation authority. Intents
bind exact fixed paths and reviewed XML or confirm/sign JSON. Completion retains
response bytes or an explicit uncertainty, without effect/acceptance claims.
These record contracts alone neither persist nor execute an operation.

`AnnualAccountsDeliveryObservation` links an exact known-instance read to its
retained draft, finite admission and intent. `decode_annual_accounts_delivery_record`
restores the known review/admission/intent/completion/observation/frame
generations, enforcing exact canonical bytes, complete keys and typed scope. It
retains opaque HTTP responses separately from observed effects.

`AnnualAccountsFrameKind` and `AnnualAccountsDeliveryFrameRecord` bind a bounded
ordered set of retained observations. `inspect_annual_accounts_delivery_frame`
returns `AnnualAccountsDeliveryFrameInspection` only for complete known-instance
reads: metadata brackets files without changing, byte lengths/media/data IDs
match metadata, both structured files match the exact prepared pair, and local
pinned validation still agrees. Confirmation and signing frames retain all
recognized validation issues; errors block their process action. Signing review
requires every generated PDF and the unsigned Signering task. Technical archive
inspection requires observed process end/archive, the exact structured pair and
all generated PDF/signature originals. Signature content stays unclassified.
Stable review hashes omit local observation times; prerequisite hashes bind the
exact retained frame. Consequential callers separately enforce the 60-second
freshness window, current source/owner/MFA, finite admission and committed intent.

`StoredAnnualAccountsDeliveryEvent` and
`inspect_annual_accounts_delivery_journal` validate retained sequence/slot identity,
review/admission/intent/response links, known instance/data references, finite
budgets and fresh action-specific frames. `AnnualAccountsDeliveryJournalInspection`
is a historical technical frontier; current source/owner/MFA and live finite
admission must still be checked before use. A received process acknowledgment is
never a terminal effect. Missing creation identity blocks mutation and lookup; a
positive scoped creation identity permits only known reads until a complete
metadata frame exists. Unknown uploads/confirm/sign outcomes progress only through
known reads. Archive requires observed process end plus exact original coverage,
and makes no authenticity or regulatory-acceptance claim. Each mutation grant is
issued after its specific committed review; prepare and confirm have separate
budgets/deadlines, while person signing remains a distinct port.

Journal inspection requires the positive stored event-ID/hash enumeration
commitment, in addition to ordered dependency and commit times. PG identities are
global and may have gaps across filings/aborts; contiguous IDs are not a coverage
proof. Every file observation must reference a previously retained positive
metadata ID/type, even if no frame later uses it. Historical known references
remain usable for retaining in-flight read results after metadata changes.
Received headerless or opaque HTTP bodies remain exact, without invented media;
interpretation checks normalized known media separately. Request-start and
response-observation times are distinct: finite admission applies at request
start, and a valid in-flight response remains retainable after expiry. Frames
require files to be requested and observed within the metadata bracket, and
process end/archive timestamps cannot lie after their observation.

`AnnualAccountsDeliveryJournalPersistence` retains exact canonical operation records through restricted RPCs. Source v3 positively enumerates every sequence/hash and pins executable helpers, checks and retention policies; v2 remains incomplete for nonempty events. Complete enumeration does not validate the effect graph: callers inspect the full typed journal and pinned frame originals before HTTP. Staged finite system preparation/confirmation and separately reviewed person signing remain distinct; only known GET frames establish byte effects. Opaque acknowledgments, signatures and PDFs prove no regulatory acceptance or authenticity. Containment rollback preserves bound late results and originals.

<!-- architecture-inventory
{"ports":["AnnualAccountsDeliveryJournalPersistence"]}
-->

`AnnualAccountsDeliveryTransport` binds four separate finite loopback adapters for system preparation, system confirmation, person signing, and known reads. Each role has a distinct credential, a staged immutable admission and an atomic request budget. Trusted composition alone can supply them; default composition has no runtime grant. The application commits and elects an intent before HTTP, closes every SQL context, then retains exact responses. Workspace reads consume no authority budget; original downloads require current owner/MFA independently of source changes or grant expiry.

<!-- architecture-inventory
{"ports":["AnnualAccountsDeliveryTransport"]}
-->


The local correction successor adds `AnnualAccountsCorrectionReadGrant`,
`AnnualAccountsCorrectionParentAdmission`, `AnnualAccountsCorrectionParentAttempt`, `AnnualAccountsCorrectionParentObservation`
and `AnnualAccountsCorrectionParentFrame`. `decode_annual_accounts_delivery_record_v2`
preserves all predecessor record bytes. `assert_annual_accounts_correction_source`
requires changed owning source and a new finalized signed Corporate decision.
`inspect_annual_accounts_correction_parent` checks fresh exact archive originals;
`inspect_annual_accounts_delivery_history` checks the complete unforked chain.
A child receives separate mutation reviews, credentials and budgets. Parent reads
use one five-minute grant, at most 27 GETs and three explicitly requested proof
frames. Each read attempt commits before HTTP and immediately closes child creation until a complete frame covers that latest attempt. Failed and late originals remain independent records; older-attempt responses cannot invalidate a later successful proof or an already-created child. Containment closes
new work while retaining known responses and access-controlled originals.


## Company-year archive and isolated copy

The owner-scoped `company-year-archive` query holds the current company archive
lock across a repeatable Accounts snapshot, then rechecks current ownership/MFA.
It exports `annual-accounts-company-year-archive-v1`: exact legacy rows, declared
eight-table coverage, original draft/event JSON and recorded times, including
Corporate-backed source facts, correction-parent reads and opaque PDF/signature
bytes. `build_annual_accounts_company_archive` and
`parse_annual_accounts_company_archive` are the owning serialization/copy
contracts. The parser checks the external archive digest, original company/year,
strict codecs, enumeration commitments, exact prepared byte pairs and complete finite
history, retaining historical schema pins without reloading schema files. It rejects missing parents, events, changed originals and unsupported
extents; an unresolved predecessor effect alone does not erase retained evidence.

The shared company archive consumes this projection under its existing export
generation receipt. Its manifest retains the Accounts digest and draft/event/
original counts. Isolated copies preserve original company/user/filing identities;
changing fixture target metadata never rewrites evidence or grants access.
Missing Accounts coverage fails restore integrity. The standalone copy checker
reconstructs through the same owning parser in another process. This contract
and fixture do not authorize a runtime database import, new provider operation,
production activation or a whole-service recovery claim.

Shared copy acceptance requires `verify_annual_accounts_company_archive`, exposed
by the read-only `company-year-archive-verifications` query under the current
owner/MFA guard. Its exact archive/source digests, original catalog and counts
must match. TypeScript checks only portable scope/bytes/enumeration; they never
replace owning journal interpretation. Raw restored fixtures remain unverified.
The preceding workspace may support an explicitly empty delivery overlap on an
older backend; this preserves export availability, not complete restore coverage.
