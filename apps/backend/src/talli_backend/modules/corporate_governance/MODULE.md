# Corporate governance backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["corporate_governance.owner_dividend_accounting_policies","corporate_governance.owner_dividend_artifacts","corporate_governance.owner_dividend_decisions","corporate_governance.owner_dividend_events","corporate_governance.owner_dividend_finalizations","corporate_governance.owner_dividend_payments","corporate_governance.shareholder_loans"],"ports":["CorporateGovernancePersistence"],"publicEntryPoints":["talli_backend.modules.corporate_governance.public"]}
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

## Current slice state

The deterministic policy, forced-RLS store, restricted transaction adapter,
FastAPI transport, generated client, web cutover, legacy-writer contraction,
reconciliation import, rollback, and hosted migration verification are
implemented for #144. Issue #145 additionally owns supported shareholder-loan
policy, persistence, API transport, and atomic Ledger/Banking coordination; its
predecessor Ledger route and TypeScript policy have been removed. The existing
Python subprocess renderer is intentionally not
reclassified as complete governance ownership; #148 must move rendering
in-process and remove the bridge before the full capability exits.
