# Corporate governance backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["corporate_governance.annual_close_artifacts","corporate_governance.annual_close_decisions","corporate_governance.annual_close_events","corporate_governance.annual_close_finalizations","corporate_governance.owner_dividend_accounting_policies","corporate_governance.owner_dividend_artifacts","corporate_governance.owner_dividend_decisions","corporate_governance.owner_dividend_events","corporate_governance.owner_dividend_finalizations","corporate_governance.owner_dividend_payments","corporate_governance.shareholder_loans","corporate_governance.supported_events"],"ports":["CorporateGovernancePersistence"],"publicEntryPoints":["talli_backend.modules.corporate_governance.public"]}
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

Registered capital events first perform a short guarded prepare/replay check.
If still new, independent register and original-byte verification runs outside
the guard. A second guarded prepare handles intervening completion; otherwise
RF current-observation and Documents retained-original assertions run on that
same connection before any Ledger posting. No provider or object-storage I/O
runs while this final guard is held. This binds the selected evidence for these
events; it does not establish a full-year RF approval/send freshness protocol.

Rollback suspends the guarded writer entry points while preserving data and
backstops. Reapply restores writes without publishing an unguarded API alias.
