# Annual Accounts Filing

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["annual_accounts_filing.authority_permissions","annual_accounts_filing.authority_test_runs","annual_accounts_filing.filing_overrides","annual_accounts_filing.filing_previews","annual_accounts_filing.filing_review_comments","annual_accounts_filing.filing_submissions"],"ports":["AnnualAccountsAuthority","AnnualAccountsRehearsalIO","AnnualAccountsWorkspacePersistence","AnnualAccountsPreparationPersistence","AnnualAccountsEvidencePersistence"],"publicEntryPoints":["talli_backend.modules.annual_accounts_filing.public"]}
-->

## Purpose

Own the deterministic annual-accounts filing rules and RR0002 documents. Stage
#153 currently contains the pure calculation, XML and Accounts-specific readiness
slice and test rehearsal lifecycle. The legacy writer remains authoritative until the explicit database
cutover; authority work is accessible only through the existing explicitly
approved synthetic test gate and fixed TT02 adapter. Production stays disabled.

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
The legacy public writer remains active until a separately verified cutover.
No storage bucket is added.
`AnnualAccountsAuthority` declares the fixed TT02 operations and
`AnnualAccountsRehearsalIO` declares local file, clock, XML and credential seams.
`annual_accounts_authority_adapter` registers implementations.
`AnnualAccountsRehearsalConfiguration` holds nonsecret declarations, and
`AnnualAccountsAuthorityError` carries sanitized failure metadata.
Their registered adapters retain transport mechanics; Accounts owns the ordered
rehearsal guards, checkpoints, retries and human-signing continuation.
`rehearse_annual_accounts` returns an immutable summary.
`prepare_annual_accounts_for_signing` preserves create/upload/validate/lock/handoff
order and refuses to lock after validation errors. Neither contract signs.
The local CLI retains the exact explicit test gate, scopes, synthetic case and
organization checks. It writes intent before credentials or provider work, reuses
existing uploads, reads receipt state after human signing and replays completed
evidence without constructing a provider. Credential setup remains outside the
original provider error-catching block. Validation-failed status and sanitized
retryable/blocked errors retain their original behavior. The generated client and authenticated persistence boundary enforce accepted
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
latest state and the Archive invalidation behavior. Full stage-exit gates and
durable source attestation remain pending.

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
