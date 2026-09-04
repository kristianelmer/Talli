# Corporate governance backend capability

<!-- architecture-inventory
{"dependencies":["query:documents"],"ownedTables":["corporate_governance.annual_close_artifacts","corporate_governance.annual_close_decisions","corporate_governance.annual_close_events","corporate_governance.annual_close_finalizations","corporate_governance.owner_dividend_accounting_policies","corporate_governance.owner_dividend_artifacts","corporate_governance.owner_dividend_decisions","corporate_governance.owner_dividend_events","corporate_governance.owner_dividend_finalizations","corporate_governance.owner_dividend_payments","corporate_governance.shareholder_loans"],"ports":["CorporateGovernancePersistence"],"publicEntryPoints":["talli_backend.modules.corporate_governance.public"]}
-->

## Purpose and ownership

`corporate_governance` owns accounting-policy selection, corporate decisions,
shareholder loans, owner dividends, approval/finalization state, and deterministic
corporate-document semantics. Generic document metadata and private object
storage remain owned by `documents`; accounting entries remain owned by
`ledger`; bank facts remain owned by `banking`.

Issue #144 is the first of three serialized slices. It moves the supported
owner-dividend proposal, distributable-basis validation, approval, declaration,
payment recognition, and readiness state. Issue #145 adds shareholder loans.
Issue #148 moves annual-close decisions, deterministic PDF rendering, signing,
the complete artifact lifecycle, and performs the capability-stage exit.

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

Governance declares one acyclic `query:documents` database dependency. Its
artifact and optional shareholder-loan reference triggers can execute only
`documents.register_evidence_reference_v1`; Documents owns the document-row
lock and opaque evidence registry, while Governance receives no Documents table
access.

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
