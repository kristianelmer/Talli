# Corporate governance backend capability

<!-- architecture-inventory
{"dependencies":["command:shareholder_register_filing","query:company_access","query:documents","query:ledger","query:shareholder_register_filing"],"ownedTables":["corporate_governance.annual_close_artifacts","corporate_governance.annual_close_decisions","corporate_governance.annual_close_events","corporate_governance.annual_close_finalizations","corporate_governance.owner_dividend_accounting_policies","corporate_governance.owner_dividend_artifacts","corporate_governance.owner_dividend_decisions","corporate_governance.owner_dividend_events","corporate_governance.owner_dividend_finalizations","corporate_governance.owner_dividend_payments","corporate_governance.register_evidence_amendments","corporate_governance.shareholder_loans","corporate_governance.supported_events"],"ports":["CorporateGovernancePersistence"],"publicEntryPoints":["talli_backend.modules.corporate_governance.public"]}
-->

## Purpose and ownership

`corporate_governance` owns accounting-policy selection, corporate decisions,
shareholder loans, owner dividends, supported domestic capital, financing and
group-event facts, approval/finalization state, and deterministic corporate-document semantics. Generic document metadata and private object
storage remain owned by `documents`; accounting entries remain owned by
`ledger`; bank facts remain owned by `banking`.

Issue #144 is the first of three serialized slices. It moves the supported
owner-dividend proposal, distributable-basis validation, approval, declaration,
payment recognition, and readiness state. Issue #145 adds shareholder loans.
Issue #148 moves annual-close decisions, deterministic PDF rendering, signing,
the complete artifact lifecycle, and performs the capability-stage exit. Issue
#191 adds the versioned, fail-closed supported event boundary.

## Public interface

Consumers import only `talli_backend.modules.corporate_governance.public`.
The annual-close commands are `AnnualCloseProposalCommand`,
`RegisterAnnualCloseDocumentsCommand`, `ApproveAnnualCloseCommand`,
`RecordAnnualCloseEventCommand`, `AttestAnnualCloseSignedArtifactCommand`, and
`FinalizeAnnualCloseCommand`; their deterministic results are
`CanonicalAnnualCloseDecision`, `ProposedAnnualClose`, and
`RenderedCorporateArtifact`. Owner signing uses
`RecordOwnerDividendEventCommand` and
`AttestOwnerDividendSignedArtifactCommand`.

The unified read model is `CorporateLifecycleSnapshot`, composed from
`CorporateDecisionRecord`, `CorporateDocumentSetRecord`,
`CorporateArtifactRecord`, `CorporateEventRecord`, and
`CorporateFinalizationRecord`. Decision facts are represented by
`AnnualDataSourceFacts`, `CorporateAccountMovementFacts`,
`CorporateDecisionFactSources`, and `DerivedCorporateDecisionFacts`.
`CorporateDocumentReadiness`,
`CorporateDocumentReadinessBlocker`, and `CorporateReadinessSource` derive and
describe current source status, lifecycle blockers, signer requirements, and
payable state in Python. `AnnualCloseLifecycle`, `OwnerDividendLifecycle`,
`AnnualCloseEventKind`, `OwnerDividendEventKind`, `CorporateDecisionKind`, and
`CorporateArtifactVariant` close the lifecycle vocabulary.

`OwnerDividendProposalCommand` carries persisted identity/shareholder facts, an
approved annual-basis snapshot, the exact owner-reviewed facts, meeting facts,
confirmations, and an amount in integer øre. The service normalizes and sorts
those values, verifies the reviewed snapshot, derives the exact proportional
largest-remainder allocation, enforces the characterized hard blocks, and
produces `CanonicalOwnerDividendDecision` with stable source and decision hashes.

`RegisterOwnerDividendDocumentsCommand` accepts only opaque `DocumentReference`
values plus immutable content evidence. It contains no bucket, storage-key, or
object-operation vocabulary. `FinalizeOwnerDividendCommand` and
`RecordOwnerDividendPaymentCommand` carry opaque `AccountingEntryReference` and
`BankTransactionReference` identities; they expose no accounts, ledger lines,
provider fields, or bank credentials.

`RecordShareholderLoanCommand` carries only the owner's business intent and
opaque document, bank-transaction, action, and accounting-entry references. The
service blocks personal-shareholder lending and related-party security, while
the application verifies Documents evidence and coordinates the characterized
Ledger posting and optional Banking claim in the governance transaction.
The stable vocabulary is `ShareholderLoanDirection` and
`ShareholderLoanDocumentStatus`; normalization produces
`CanonicalShareholderLoan`, preparation exposes `PreparedShareholderLoan`, and
completion returns `RecordedShareholderLoan`.

The proposal vocabulary is `PersistedCompanyFacts`,
`PersistedShareholderFacts`, `ApprovedAnnualBasis`,
`ReviewedOwnerDividendFacts`, `ReviewedShareholderFacts`, `BoardMeeting`,
`BoardParticipant`, `BoardRole`, `BoardTreatmentMethod`, `GeneralMeeting`,
`MeetingForm`, `ShareholderBallot`, and `ShareholderVote`. The canonical result
uses `CanonicalOwnerDividendDecision`, `CanonicalBoardParticipant`,
`CanonicalDecisionShareholder`, `OwnerDividendFinancialTotals`,
`OwnerDividendFacts`, `OwnerDividendAllocation`, `OwnerDividendConfirmations`,
`ProposedOwnerDividend`, `OwnerDividendLifecycle`, and `OwnerDividendState`.
`PreparedOwnerDividendFinalization` and `PreparedOwnerDividendPayment` expose
only the normalized amounts, locked bank fact, and versioned account mapping
selected by the append-only governance policy store. They do not expose
persistence rows, and the application does not choose accounts.

`RecordSupportedCorporateEventCommand` closes the ordinary domestic event set.
Its `CashCapitalIncreaseEventFacts`, `LossCoverageCapitalReductionEventFacts`,
`IntercompanyLoanEventFacts`, `OwnerLoanEventFacts`, `BankLoanEventFacts`, and
`GroupContributionEventFacts` variants are discriminated by
`SupportedCorporateEventKind` and `SupportedCorporateEventPhase`.
`SupportedCorporateDocumentFact`, `SupportedCorporateBankFact`, and
`SupportedCorporateSourceFact` freeze versioned evidence; the related
`SupportedCorporateEvidenceKind`, `SupportedCorporatePerspective`, and
`SupportedCorporateRelationship` enums keep unsupported structures outside the
contract. `CanonicalSupportedCorporateEvent`,
`PreparedSupportedCorporateEvent`, and `RecordedSupportedCorporateEvent` form
the immutable prepare/complete result. A recorded event is already finalized:
its `signed_artifact_hashes` exposes the exact verified Documents evidence and
its deterministic `finalization_sha256` binds the canonical facts, signed
artifacts, Ledger entry, Banking reference, and correction lineage into one
reproducible receipt. `SupportedCorporateEventId` and
`SupportedCorporateEventReference` are its stable identities.
`ReverseSupportedCorporateEventCommand` requires an immutable correction
document and produces `ReversedSupportedCorporateEvent` through Ledger's
mechanical reversal contract.

Stable owned identities are `CorporateDecisionId`, `CorporateDocumentSetId`,
`CorporateArtifactId`, `CorporateEventId`, `CorporateFinalizationId`, and
`CorporateSourceReference`. Cross-capability correlations are the opaque
`DocumentReference`, `AccountingEntryReference`, and
`BankTransactionReference`. `OwnerDividendArtifactReference` identifies the
exact `CorporateArtifactKind` and immutable content evidence without exposing
storage. `ApproveOwnerDividendCommand` represents the owner facts-approval
transition. Adapter binding is declared only by
`corporate_governance_persistence_adapter` against
`CorporateGovernancePersistence`.

Expected failures cross the boundary only as `CorporateGovernanceError` with a
declared `CorporateGovernanceErrorCode`. The public contract contains no
FastAPI, Pydantic, database, Supabase, or web types.

## Workflow and persistence seam

`CorporateGovernancePersistence` is the sole outbound capability port. The
request-bound application workflow authenticates one verified actor, opens a
restricted forced-RLS PostgreSQL transaction, asks governance to prepare or
replay its mutation, collaborates with `documents`, `ledger`, and `banking` only
through their public contracts, and completes governance-owned state in the same
transaction. The owner-dividend tables and canonical `shareholder_loans` table derive state
without mutable status columns. The executor has no table grants and reaches
Ledger and Banking only through governance-specific routines. Provider
selection, activation, credentials, consent, live calls, customer bank data, and
production banking remain outside this capability and blocked independently by
#189.

The supported-event query is also the only governance source used by the
company-year archive adapter. The archive stores the finalization receipt and
artifact manifest without copying document bytes or reading governance tables.
RF-1086, company-tax, annual-accounts, and SAF-T generators remain owned by
their later route capabilities; #191 publishes stable event/fact/evidence IDs
and golden projection expectations for those consumers instead of duplicating
their filing rules here.

Governance declares no direct Documents database dependency. The named
backend-system `corporate-governance` workflow invokes Governance persistence
and the Documents evidence-registration command atomically. Documents owns the
document-row lock and opaque evidence registry, while Governance receives no
Documents schema or function privilege and owns no cross-capability trigger.

Company identity is obtained through the `company_access` public service and
opening shareholders through the frozen Ledger opening-snapshot query. Until
#149 and #153 establish their future public contracts, the application owns one
narrow read-only compatibility seam for the selected legacy annual-data row.
Corporate governance projects only its predecessor decision basis—result,
equity, distributable equity, liquidity, and a governance-specific digest—from
immutable annual-data and Ledger facts. It does not construct or hash annual-
accounts filing payloads, statutory identifiers, filing fields, or filing
readiness. The backend-system SQL reader is owner-authenticated, executor-only,
and is removed when future annual-compliance ownership replaces it.

## Stage-exit state

Issue #148 completes the capability boundary. Both annual-close and
owner-dividend decisions expose one typed lifecycle query and immutable approval,
signing, attestation, rejection, and finalization commands. Deterministic PDFs
render in-process in Python. The web reads and mutates governance only through
the generated client, while Documents remains the sole storage authority and
Ledger/Banking remain coordinated through their public contracts.

The contract migration reconciles identities and hashes, removes governance rows
from `holding_actions`, removes all six predecessor `public.corporate_*` tables,
old RPCs and projection helpers, and moves archive invalidation and document
evidence checks to canonical tables. Rollback restores a read-only predecessor
projection without reviving a second writer; corrected recutover is repeatable.
The additive hosted-shape parity migration first restores immutable event IDs and
occurrence times that were absent from the already-deployed #144 table revision;
it is a no-op for fresh databases created from the current migration chain.

## Reporting-year evidence

`CorporateReportingYearBasis` reads the existing lifecycle and supported-event
public projections within one authenticated SERIALIZABLE transaction.
`CorporateGovernanceApplication.read_reporting_year_evidence` composes that basis
with Ledger's complete company-scoped `LedgerEntryAmendment` query in the same
transaction. Governance never reads Ledger tables. This closes the historical
case where `reverse_supported_event` returned a Ledger reversal without creating
a separate Governance reversal row.

The deterministic public `build_reporting_year_evidence` assembles these owner
projections. The immutable `CorporateGovernanceYearEvidence` contains
`CorporateYearDividendEvidence`, `CorporateYearSupportedEvidence`, and opaque
`CorporateLedgerAmendment` receipts. It retains pending, rejected, superseded,
reversed and corrected records, exact signed artifacts/finalizations, and
connected replacement chains. Its deterministic enumeration digest changes when
relevant decisions, events, signed evidence or amendments change. It is a source
projection, not filing readiness, external-source lease or production authority.
No filing capability dependency or new HTTP endpoint is introduced.

Cash capital increases use their explicit `SupportedCorporateEventReference`,
the same reference passed to Ledger's `CapitalIncreaseReferenceId`, to group
available binding-subscription, restricted-payment and registration records.
The registration remains the reportable receipt;
`CorporateYearSupportedEvidence.lifecycle_events` retains every original phase,
including prior-year anchors. All present phases must agree on economics,
policy, chronology and distinct Ledger entries; payment and registration must
also agree on bank evidence. A missing registration, conflicting originals, or
any phase's correction or Ledger amendment remains a blocker. The reporting
digest uses `corporate-reporting-year-2` and includes every retained original.

A successful owned registration is the existing authority for Ledger's required
subscription and payment prerequisites. An accepted `OpeningCapitalIncreaseComponent`
may supply either or both predecessors without corresponding Governance rows.
The projection therefore accepts coherent available subsets containing the
registration, including the existing standalone-registered path; it never
manufactures an opening record or treats missing Governance rows as proof of
missing Ledger anchors. Full original opening-component provenance would require
a separate Ledger-owned public evidence reader. In particular, amendments to an
opening anchor cannot be connected here when its entry identity is absent from
the Governance basis; that existing standalone-path limitation is not a claim
of complete opening-anchor amendment coverage. This change admits no nominal-
value increase and leaves loss-reduction first recognition unchanged.


For the supported ordinary owner dividend, the reporting year uses the civil
general-meeting decision date, not the annual accounts basis, payment date or
persistence timestamp. [Skatteetaten's RF-1086 examples](https://www.skatteetaten.no/bedrift-og-organisasjon/rapportering-og-bransjer/aksjonarregisteroppgaven/eksempler-pa-utfylling-av-aksjonarregisteroppgaven/)
state that the general-meeting decision date determines dividend reporting time
(verified 2026-09-23). Mapping the persisted canonical `generalMeeting.meetingDate`
to that rule is the product inference. Registered capital facts retain their
owned `event_date` and phase without deriving a new legal registration date.
Corrections connected to selected-year records are retained even when their own
date falls in another year; consumers must consider their status before mapping.

### Company guard for consequential writes

The application mutation transactions acquire the shared company advisory guard
under READ COMMITTED before reading current owner/eligibility or taking local
Governance/Ledger locks. Read-only reporting transactions retain SERIALIZABLE.
Migration `20260924080355_governance_ledger_company_write_guards.sql` also wraps
owner write RPCs before their original bodies and adds company-scoped table
backstops, including lifecycle events and amendment receipts in Ledger.
The private row-trigger helper runs as its store owner solely to acquire the
company lock; the surrounding mutation retains its existing permissions and RLS.

Registered capital events first perform a short guarded prepare/replay check.
If still new, independent register and original-byte verification runs outside
the guard. A second guarded prepare handles intervening completion; otherwise
RF current-observation and Documents retained-original assertions run on that
same connection before any Ledger posting. No provider or object-storage I/O
runs while this final guard is held. This binds the selected evidence for these
events; it does not establish a full-year RF approval/send freshness protocol.

Rollback suspends the guarded writer entry points while preserving data and
backstops. Reapply restores writes without publishing an unguarded API alias.

### Guarded reporting projection for RF

`corporate_governance.read_guarded_reporting_year_inputs_v1(uuid,integer,text)`
returns complete company-scoped lifecycle, supported-event and Ledger amendment
projections under the caller's already-held company guard and READ COMMITTED
transaction. It verifies the current owner and exact authenticated subject. The
RF executor receives only this function and schema usage; the Governance owner
receives only Ledger's public amendment reader, with no Ledger table grants.

`PostgresCorporateReportingEvidence(connection, actor_id)` uses the existing
projection codecs and public `build_reporting_year_evidence` to return the same
`CorporateGovernanceYearEvidence` as the ordinary application read. Enumeration
retains cross-year corrections and historical amendments before domain year
selection. It opens no connection, sets no role or identity, and performs no
provider I/O. Rollback disables the RF entry point and preserves original rows.
The caller still owns admission, source reconciliation and approval/send policy.

A complete capability rollback explicitly retires the later Governance company
write guards and guarded reporting reader after their tables are removed, and
revokes only Governance's additive Ledger, Documents, register-observation and
company-lock grants before role retirement. Evidence assertions remain installed
under their original owners; their caller grants are restored during recutover,
with temporary role memberships restored exactly. Ledger keeps its own guard and reader authority. Recutover must replay
the company-write-guard and guarded-reporting successors after historical table
and routine recreation; the twice-run lifecycle rehearsal checks the restored
triggers, loan guard, RF reader and cross-owner grants.

The isolated historical Governance rehearsal replays only Governance definitions
from the combined company-write-guard successor. Ledger's independently rehearsed
older topology and routine bodies stay intact; the final combined cutover still
uses the complete strict migration. The scoped replay retains all Governance
missing-table checks and restores the existing Ledger guard grant needed by its
caller, without creating replacement Ledger tables.


### Final supported-event register currentness

`20261009223340_governance_register_observation_completion_guard.sql` preserves
`prepare_supported_event_v1` and `complete_supported_event_v1` signatures, OIDs,
ACLs, company-first/event-next locks and READ COMMITTED requirement. Existing
prepare replay comparisons are NULL-safe. Completion replay additionally binds
stored company/year and uses NULL-safe hash/entry comparisons before returning;
it is not full-command equality. Authorized historical replay precedes fresh
mutable register checks.

Fresh completion first requires strict outer/canonical identity and type agreement,
then exact frozen RF reference shape for registered cash capital increases and
registered/first-recognized-after-registration loss reductions. The store owner
receives only RF schema USAGE and EXECUTE on public
`assert_current_register_observation_v2`; it grants no RF table access. The closed
amendment successor below separately adds narrow public proof-reader permissions.
These directed public SQL query dependencies are declared in the manifest.
The assertion runs under the same transaction/company lock as insertion. A single
`statement_timestamp()` supplies both RF cutoff and explicit event `created_at`.
A capture newer than statement start is conservatively rejected after a lock wait;
the adapter maps that result to the existing evidence precondition.

This fence proves current exact identity and capture time only. It does not verify
original bytes, economics, canonical-facts digest provenance or arbitrary fabricated
payloads. Mutating both outer and canonical declarations can still describe another
apparent event; broader final-write parity remains unresolved and the owner workflow
must verify admitted ledger facts and original evidence. Earlier phases/loans are
not given a new register requirement. Rollback retains the safety fence and public
SQL dependency; no withdrawal writer, amendment or Archive policy is activated.

`20261010032531_governance_supported_event_replay_visibility.sql` repairs the
completion lookup under forced RLS. `supported_events` has SELECT/INSERT policies
and is immutable; `FOR UPDATE` applies the absent UPDATE policy and hides a
committed event. The repair removes only that row-lock clause. Existing company
and event advisory locks serialize writers, and normal SELECT preserves the
accepted-owner policy. It adds no UPDATE policy or runtime grant. Exact body
sentinels, function catalog identity, temporary role/schema authority restoration,
and retaining rollback preserve the rest of the completion contract. Fixture
reinstallation targets this successor; the frozen predecessor must not be
reapplied over its changed function body.

### Pure register-evidence amendment foundation

`anchor_supported_corporate_event_evidence` creates a
`SupportedCorporateEventEvidenceAnchor`. The domain command is
`AmendSupportedCorporateRegisterEvidence`, using
`CorporateRegisterEvidenceAmendmentHead`, `CorporateRegisterWithdrawalReference`
and `CorporateDocumentOriginalCommitment` values. The result is
`SupportedCorporateRegisterEvidenceAmendment`, identified by
`CorporateRegisterEvidenceAmendmentId`. Invalid pure values raise
`CorporateRegisterEvidenceAmendmentError` with a fixed safe code.

`corporate_register_evidence_amendment_request_digest` commits the business
request. `serialize_corporate_register_evidence_amendment_command` and
`parse_corporate_register_evidence_amendment_command` expose its strict canonical
business-only JSON without changing the existing receipt codec.
`prepare_supported_corporate_register_evidence_amendment` validates the
supplied predecessor history and builds its receipt;
`assert_corporate_register_evidence_amendment_integrity` and
`assert_corporate_register_evidence_amendment_replay` check retained receipts and
exact business replay. `derive_corporate_register_evidence_chain` returns a
`CorporateRegisterEvidenceChain`. Canonical persistence uses
`serialize_corporate_register_evidence_amendment` and
`parse_corporate_register_evidence_amendment`.

The additive public types and private `register_evidence_amendment.py` bind an
unchanged recorded capital event to a later evidence statement. The anchor adds
the stored original `UserId` and recording instant to a new digest; the existing
facts/finalization digests and `RecordedSupportedCorporateEvent` remain unchanged.
The original projection must have `replayed=False`: response-delivery metadata
is not a second version of stored history. Only an owner-backed storage projection
can establish where the original actor and timestamp came from.

The pure command identifies actor, company/year/event, expected anchor/head,
exact withdrawn RF reference, replacement reference, correction memo and exact
reason. It contains no idempotency key or correlation ID. Closed persistence below
binds the private actor-scoped key to the business request digest and recovers that
receipt before fresh-write checks or external I/O. Public historical receipts
must not disclose those transport values.

The `corporate-register-evidence-amendment-v1` codec binds the complete anchor,
command, amendment ID/revision/time, business request digest and immutable local
Documents commitments. The frozen original document references plus the correction
memo are a required subset. Additional same-company commitments can bind the
replacement RF observation's originals, with their own source years. Pure code
does not establish exact replacement coverage; the later RF public snapshot and
final owner assertions must do that. Their metadata is captured when verifying
the amendment; it does not claim historical metadata was frozen at original
recording. Revision is the event's semantic document reference, not a Documents
revision counter. An RF-only extra original uses revision 1 solely as the fixed
v1 receipt encoding convention; a shared Governance/memo identity retains its
existing semantic revision. The codec requires canonical UTC microseconds, exact UTF-8
reason text, strict primitive types and unique/known JSON fields. No verified
Boolean substitutes for public owner evidence.

Chain validation binds revision 1 to the original RF reference, each subsequent
head to its exact prior ID/digest, and each withdrawal target to the preceding
effective reference. It rejects forks, skipped/truncated prefixes, duplicate
receipts/withdrawals, reused observation IDs and non-increasing later times. A
valid prefix still cannot prove that storage contains no later amendment.

This foundation performs no IO, mutation, authorization, fresh-MFA, RF lifecycle,
original-byte, economic or Ledger checks, and certifies no full enumeration.
These remain application and final SQL obligations through declared public owner
contracts. It adds no persistence port, grant, HTTP operation, activation or
Archive behavior; old reporting and API/codec projections remain frozen.

### Closed register-evidence amendment persistence

`20261009234529_governance_register_evidence_amendments.sql` adds the immutable,
forced-RLS `corporate_governance.register_evidence_amendments` table and three versioned SQL contracts.
All runtime executors, PUBLIC, anonymous and service roles remain denied; this is
a closed persistence prefix. The application suffix below grants only its reviewed
workflow caller; HTTP, RF consumption and Archive activation remain absent.

`append_register_evidence_amendment_v1(command_text, originals, idempotency_key,
subject)` accepts only the canonical business command and a distinct document
commitment array. It derives the anchor from the actual unchanged original row,
including actor/time, recomputes original facts/finalization hashes, and mints the
amendment UUID, UTC instant, request digest and canonical receipt. The original
event and Ledger entry remain untouched. A scoped predecessor self-FK binds the
prior ID/revision/digest; unique revisions, immutable triggers, and full-prefix
validation reject forks, omissions, skipped heads and reused observations.

Company then supported-event locks serialize writes, recovery and enumeration at
READ COMMITTED. Actor/company/key lookup precedes fresh admission and evidence:
an exact committed command returns stored receipt bytes even with missing fresh
originals, expired MFA or subsequently withdrawn/reversed evidence. Wrong event,
year or request digest conflicts with an existing key. Current accepted ownership
and verified subject still apply. Public receipts never expose transport keys.

Fresh writes use the existing CompanyAccess current-clock MFA predicate after
locks and immediately before insertion, plus company-year admission. Narrow
owner grants consume RF's exact retained withdrawal and validated current snapshot,
Documents' current-row equality and historical metadata-integrity assertions,
and Ledger's unamended original-entry/context/ordered-source assertion and public
amendment list. Fresh cash admission checks all owned same-reference phases
across years for reversal/correction and phase, terms, date, recording-time and
payment-bank coherence, matching the reporting-year lifecycle. Registered-only
originals remain supported; absent Governance phases do not prove Ledger anchors. The MFA
grant runs as its actual unchanged function owner, not an assumed command role.
The full distinct document union is original Governance evidence, memo, and actual
replacement RF originals. Fresh originals require the existing four usable
Document statuses and no removal timestamp; historical recovery is independent.
Shared references must agree in every commitment;
RF-only revision 1 is an encoding convention. RF economics/date must match the
unchanged original capital facts. No foreign private helper or table is read.

`read_register_evidence_chain_v1(company, year, event, subject)` returns codec
`corporate-register-evidence-chain-v1`, actual anchor, ordered canonical receipt
strings, count, exact head, effective reference and enumeration SHA-256. Zero
requires a valid actual original event; missing data/schema is never an empty
history. `lookup_register_evidence_amendment_v1(company, year, event, key,
request_sha256, subject)` returns `recorded` with exact `receipt_text`,
`not_observed`, or `conflict`; operational failures map to unavailable at the application boundary. An absence describes this guarded
observation, not a permanent promise that no later write can commit.

These proofs bind retained claims and current owner state. They do not establish
legal signedness, original metadata at the old Governance recording time, current
Banking eligibility, an RF premium field, independent truth of original economics,
or fresh object-store bytes. Documents commits retained SQL bytes and metadata;
the seven raw SQL-only metadata fields remain outside its unchanged public hash.
The application suffix adds byte verification; HTTP activation and Archive
coverage remain separate.
Retentive rollback preserves rows, guards, recovery and narrow proof grants.
Prerequisite tests still check their closed stages, then restore this final suffix,
including after failed catalog assertions. No old public schemas/codecs change.


### Register-evidence amendment application admission

`20261010001936_governance_register_evidence_application.sql` adds
`prepare_register_evidence_amendment_v1(command_text, idempotency_key, subject)`.
It recovers an exact actor/company/key receipt before current MFA, admission or
owner evidence, returning `recorded` with canonical receipt text. New commands
require the existing CompanyAccess current-clock MFA predicate, admitted current
ownership, and a complete chain matching the expected anchor/head/withdrawal
target before returning `ready` with the chain. Company/event locks and READ
COMMITTED apply to prepare, chain, lookup and append. Ready is not a lease.

Only `corporate_governance_workflow_executor` receives the four public contracts;
private helpers, tables and foreign proof functions remain unavailable to it.
The frozen append still derives every receipt and rechecks all final owner,
MFA, head, RF, Documents and Ledger assertions. The suffix never rewrites the
original persistence functions. Retentive rollback closes its four grants while
preserving history and owner recovery; old-prefix fixtures restore both ordered
suffixes. Disposable teardown accepts the original exact 22-function inventory
or the additional exact prepare signature, and refuses retained amendment rows.

`CorporateGovernanceApplication.amend_supported_register_evidence` resolves
prepare inside a guarded transaction before even checking whether its evidence
verifier is configured. A recorded request returns without RF/Documents sessions
or bytes. A fresh ready result releases the transaction, then verifies every
distinct original Governance document, correction memo and actual current RF
original through public Documents byte verification. Shared identities must agree
in content/year and all RF metadata; original semantic revisions remain exact,
while RF-only revision 1 is the fixed receipt convention. Metadata is established
at amendment time, never retroactively at original recording. Bytes are read
without Governance/company locks. A separate guarded transaction calls final
append; concurrent revocation, stale evidence, expiry or head change can reject it.
There is no automatic append retry. Same-key prepare/lookup recovers uncertainty.

Typed chain, lookup and prepare values have strict public decoders. They validate
closed shapes, scope, canonical receipts, exact count/head/effective reference,
full supplied lineage and enumeration digest. Missing schemas or malformed
responses are unavailable, never empty histories or successful absence. A fully
recommitted truncated prefix cannot be disproved by a client alone: complete
storage enumeration remains the SQL owner's contract. Historical chain/lookup
requires current accepted ownership, but no fresh MFA or mutable evidence.
No HTTP route, RF consumer, Ledger posting, Banking freshness or Archive behavior
is activated by this slice; old public wire schemas and receipt/hash codecs stay
unchanged.

The additive public query/result types are `CorporateRegisterEvidenceQuery`,
`CorporateRegisterEvidenceChainSnapshot`, `CorporateRegisterEvidenceAmendmentLookup`
and `PreparedCorporateRegisterEvidenceAmendment`. Adapter and alternate-port
validation use `parse_corporate_register_evidence_chain_snapshot`,
`assert_corporate_register_evidence_chain_snapshot`,
`parse_corporate_register_evidence_amendment_lookup` and
`parse_prepared_corporate_register_evidence_amendment`.
`serialize_corporate_register_evidence_originals` emits the strict immutable
admission commitments; they do not form part of the actor-scoped request digest.

### Amendment row company-lock backstop

`20261010004653_governance_register_evidence_company_guard.sql` extends the
released all-company-table guard invariant to `register_evidence_amendments`.
The unconditional `aa_company_write_guard` runs before each INSERT, UPDATE or
DELETE through the unchanged private `lock_company_write_v1()` function. It
requires READ COMMITTED and locks the affected row company; table FORCE RLS,
immutable-update/delete and no-truncate rules still apply. It adds no runtime
authority. Reapplication preserves existing function bodies/ACLs and restores
any temporarily borrowed owner-role edge. Retentive rollback keeps the guard
and all amendments, so it cannot reintroduce the direct-row-write bypass.

The final-topology catalog and direct-row regressions live in
`apps/backend/tests/test_governance_register_evidence_company_guard_database.py`.

### Reporting year with register-evidence history

`CorporateReportingRegisterEvidenceQuery` and
`CorporateGovernanceYearRegisterEvidence` add a historical reporting projection.
`build_reporting_year_register_evidence` retains the unchanged
`corporate-reporting-year-2` view and hash, then binds every eligible original
from the complete company-wide supported-event input to exactly one validated
`CorporateRegisterEvidenceChainSnapshot`. `assert_reporting_year_register_evidence`
revalidates the carried scope, original-view hash and chain commitments at typed
application boundaries. Originals and effective register references remain
separate; amendments do not change the original economics, Ledger facts or
reporting status.

The eligible inventory includes non-correction cash `registered` originals and
loss-reduction `registered` or `first_recognized_after_registration` originals,
including other years. Correction rows and reversed/conflicting lifecycles stay
in the unchanged reporting inputs and year selection; correction rows are not
new amendment anchors. Registered-only cash remains supported. An eligible
legacy original missing valid RF evidence makes the new projection unavailable;
it cannot be omitted or represented as known-zero history. The old reader keeps
its existing behavior. Only a valid complete scope with no eligible originals
has zero chains.

`20261010005413_governance_reporting_register_evidence.sql` adds
`read_guarded_reporting_register_evidence_v1(company, year, subject)`. It delegates
to the unchanged guarded company-wide input reader and complete chain reader
under one held company guard at READ COMMITTED. The application and transaction
method `read_reporting_year_register_evidence` provide the Governance producer;
`PostgresCorporateReportingEvidence` has a separate same-connection method for a
future consumer. Both use one additive strict wire decoder and the existing
original parsers. Existing reader methods and accepted input formats are unchanged.

The versioned chain commitment covers sorted original-event IDs, their own years,
anchor hashes, amendment counts and chain enumeration hashes. The public
projection hash also binds the unchanged year-view hash. Arbitrary old lifecycle
JSON is not re-encoded through the strict amendment codec. These commitments
detect mismatches against the supplied complete basis; they cannot independently
prove SQL enumeration completeness or disprove a wholly recommitted omitted
owner input. Historical observation is not fresh admission or an evidence lease.

Only the Governance workflow executor receives the new public reader grant.
RF consumer grants, application consumption in RF, HTTP and Archive behavior are
not activated. Reinstallation closes unexpected grants; retentive rollback closes
only this producer grant and preserves history and old reader authority. The
empty disposable rehearsal recognizes exact 22/23/24-routine topologies and
refuses retained amendment history. Predecessor proof tests restore this suffix
when restoring the final topology. Coverage lives in
`test_corporate_governance_reporting_register_evidence.py`,
`test_postgres_corporate_reporting_register_evidence.py`, and
`test_governance_reporting_register_evidence_database.py`.


### Closed RF year-source proof producer

`20261010015851_governance_rf_year_source_proof.sql` adds the runtime-closed
`prepare_rf_year_source_governance_proof_v1(company uuid, year integer, source_sha
text, subject text) RETURNS void`. Under the caller's company guard it reads the
existing complete public reporting/register projection and translates its own
public anchor/receipt values to the explicit RF compact chain contract. RF's
public `receive_year_source_governance_proof_v1(uuid,integer,text,jsonb,text)`
also verifies the held RF-year guard, current subject/owner and READ COMMITTED.
Only the Governance store owner may execute the receiver and public
`invalidate_year_source_governance_proofs_v1(uuid)`; RF obtains no Governance
query/grant/import. The capability graph stays Governance → RF.

`rf_year_source_fact_internal_v1`, `rf_year_source_chain_internal_v1` and
`invalidate_rf_year_source_proof_internal_v1` are private helpers. Both owned
`supported_events` and `register_evidence_amendments` tables have exact AFTER
INSERT/UPDATE/DELETE row triggers and AFTER TRUNCATE statement triggers. A changed
company clears all its transaction-local proofs across years/actors/source hashes;
TRUNCATE clears all. Current/previous company are both invalidated if changed.
This covers successful same-transaction mutation; savepoint rollback restores
both owner facts and the preceding proof. Existing company guards serialize other
transactions. No stored event/economics/history is rewritten by this producer.

The RF-owned temp relation is never an archive/history record or an authorization
lease. Each use rechecks its catalog, full xid8, actor/scope/source SHA and exact
compact proof, then current RF evidence. The SQL proof commits complete chains;
old reporting-year selection/status/hash remains the unchanged public Python
builder's later same-connection responsibility. No full-byte/Banking proof,
source-writer, HTTP, RF workflow or Archive activation is introduced.
Reapplication restores only the two owner-to-owner grants and closes all four
new Governance routines to runtime callers. Retentive rollback preserves the
invalidation triggers/owner grants. Disposable empty-only rehearsal separately
recognizes the exact 28-routine topology (also preserving older 22/23/24 states),
drops only the four new triggers before their helper, and refuses populated
amendment history. The new RF database tests use fixture-only producer grants;
collection/native stubs do not claim full database execution.


### Deferred default source runtime cutover

The earlier staged slices remain closed during their database suites. The
separate CLI-created deferred contract
`supabase/contract-migrations/20261025104137_rf1086_source_runtime_v3_contract.sql`
then grants only the actual default V2/V3 callgraph to the RF executor. Its
retentive closure is
`supabase/rollback/20261025104137_rf1086_source_runtime_v3_contract.sql`.
The two Governance RPCs remain owner-verifying and guard-bound; internal
parsers/receivers/invalidators gain no runtime grant. Owner-to-owner proof
delegation, retained reads and history locks remain distinct from fresh effects.
Seven superseded RF source writers close without dropping their definitions or
records. No provider flag, tenant/MFA/legal control, table ownership or RLS rule
is relaxed. See `tests/rf1086_source_runtime_contract.test.mjs` for the focused
post-activation restricted-login and retentive-rollback checks.

Rollback profile `rf1086-v3-retentive-read-only-rollback-v1` intentionally keeps
`lock_source_claim_recovery_v3` newly enabled at activation: the actual dispatch
consumer reads confirmed/unknown history before configuration/provider admission.
It rechecks original actor and current OWNER and only reads/locks; the eight
other new entrypoints and all seven superseded writers close. This is not
pre-contract ACL restoration. The backend-system document names the actual
consumers and unchanged real revocation regressions.
