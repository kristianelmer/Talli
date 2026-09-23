"""Private Supabase persistence for corporate-governance workflows."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

from talli_backend.adapters.supabase_ledger import (
    LedgerSupabaseConfiguration,
    SupabaseLedgerAdapter,
    SupabaseLedgerSession,
    SupabaseLedgerWorkflowTransaction,
    _VerifiedActor,
    _line_payload,
    _map_database_error,
    _posted_entry,
)
from talli_backend.application.annual_data_compatibility import LegacyAnnualDataView
from talli_backend.application.corporate_governance_session import (
    CorporateGovernanceAuthenticationError,
    CorporateGovernanceSessionFactory,
)
from talli_backend.application.corporate_governance_workflow import (
    CorporateGovernanceApplication,
)
from talli_backend.application.ledger_workflow import LedgerAuthenticationError
from talli_backend.modules.banking.public import (
    BankTransactionClaimPersistence,
    ClaimBankTransactionForExternalActionCommand,
    bank_transaction_claim_persistence_adapter,
)
from talli_backend.modules.corporate_governance.public import (
    AccountingEntryReference,
    AnnualCloseProposalCommand,
    AnnualCloseLifecycle,
    ApproveAnnualCloseCommand,
    AttestAnnualCloseSignedArtifactCommand,
    AttestOwnerDividendSignedArtifactCommand,
    ApproveOwnerDividendCommand,
    BankTransactionReference,
    CanonicalSupportedCorporateEvent,
    CanonicalAnnualCloseDecision,
    CanonicalShareholderLoan,
    CanonicalOwnerDividendDecision,
    CorporateArtifactId,
    CorporateArtifactKind,
    CorporateArtifactRecord,
    CorporateArtifactVariant,
    CorporateDecisionKind,
    CorporateDecisionId,
    CorporateDecisionRecord,
    CorporateDocumentSetId,
    CorporateDocumentSetRecord,
    CorporateEventId,
    CorporateEventRecord,
    CorporateFinalizationId,
    CorporateFinalizationRecord,
    CorporateGovernanceError,
    CorporateGovernanceErrorCode,
    CorporateGovernancePersistence,
    CorporateLifecycleSnapshot,
    CorporateReportingYearBasis,
    CorporateSourceReference,
    DocumentReference,
    FinalizeOwnerDividendCommand,
    FinalizeAnnualCloseCommand,
    OwnerDividendLifecycle,
    OwnerDividendProposalCommand,
    OwnerDividendState,
    PreparedOwnerDividendFinalization,
    PreparedOwnerDividendPayment,
    PreparedShareholderLoan,
    PreparedSupportedCorporateEvent,
    PersistedCompanyFacts,
    ProposedAnnualClose,
    ProposedOwnerDividend,
    RecordOwnerDividendPaymentCommand,
    RecordOwnerDividendEventCommand,
    RecordAnnualCloseEventCommand,
    RecordShareholderLoanCommand,
    RecordSupportedCorporateEventCommand,
    RecordedShareholderLoan,
    RecordedSupportedCorporateEvent,
    RegisterOwnerDividendDocumentsCommand,
    RegisterAnnualCloseDocumentsCommand,
    ShareholderLoanDirection,
    ShareholderLoanDocumentStatus,
    SupportedCorporateEventId,
    SupportedCorporateEventKind,
    SupportedCorporateEventPhase,
    SupportedCorporateEventReference,
    corporate_governance_persistence_adapter,
)
from talli_backend.modules.ledger.public import (
    LedgerCommand,
    LedgerEntryKind,
    LedgerError,
    LedgerLine,
    LedgerRiskFlag,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    PostOwnerDividendDeclaredCommand,
    PostOwnerDividendPaymentCommand,
    PostShareholderLoanCommand,
    RecognizeHoldingActionCommand,
)
from talli_backend.modules.documents.public import DocumentsSessionFactory
from talli_backend.modules.ledger.service import LedgerService
from talli_backend.shared.kernel import ActorId, CompanyId, IncomeYear, LocalDate, Money


def _proposal_request(
    command: OwnerDividendProposalCommand | AnnualCloseProposalCommand,
) -> dict[str, object]:
    return {
        "companyId": str(command.company_id),
        "incomeYear": int(command.income_year),
        "decisionId": str(command.decision_id),
        "documentSetId": str(command.document_set_id),
        "idempotencyKey": str(command.idempotency_key),
        "correlationId": str(command.correlation_id),
    }


def _canonical_decision(
    decision: CanonicalOwnerDividendDecision | CanonicalAnnualCloseDecision,
) -> dict[str, object]:
    return {
        "decisionKind": (
            "owner_dividend"
            if isinstance(decision, CanonicalOwnerDividendDecision)
            else "annual_close"
        ),
        "decisionId": str(decision.decision_id),
        "documentSetId": str(decision.document_set_id),
        "companyId": str(decision.company_id),
        "organizationNumber": decision.organization_number,
        "legalName": decision.legal_name,
        "incomeYear": int(decision.income_year),
        "annualCloseSourceId": str(decision.annual_close_source_id),
        "sourceHash": decision.source_hash,
        "templateFamily": decision.template_family,
        "templateVersion": decision.template_version,
        "annualBasisYear": int(decision.annual_basis_year),
        "financialTotals": {
            "resultAfterTaxOre": decision.financial_totals.result_after_tax_ore,
            "equityOre": decision.financial_totals.equity_ore,
            "availableDistributionOre": (
                decision.financial_totals.available_distribution_ore
            ),
            "cashOre": decision.financial_totals.cash_ore,
        },
        "boardMeeting": {
            "meetingDate": decision.board_meeting.meeting_date.value.isoformat(),
            "meetingTime": decision.board_meeting.meeting_time.isoformat(),
            "place": decision.board_meeting.place,
            "treatmentMethod": decision.board_meeting.treatment_method.value,
        },
        "boardParticipants": [
            {
                "participantId": participant.participant_id,
                "name": participant.name,
                "role": participant.role.value,
            }
            for participant in decision.board_participants
        ],
        "generalMeeting": {
            "meetingDate": decision.general_meeting.meeting_date.value.isoformat(),
            "meetingTime": decision.general_meeting.meeting_time.isoformat(),
            "place": decision.general_meeting.place,
            "meetingForm": decision.general_meeting.meeting_form.value,
            "chairName": decision.general_meeting.chair_name,
            "coSignerName": decision.general_meeting.co_signer_name,
        },
        "shareholders": [
            {
                "shareholderId": shareholder.shareholder_id,
                "name": shareholder.name,
                "shareCount": shareholder.share_count,
                "representedShareCount": shareholder.represented_share_count,
                "vote": shareholder.vote.value,
            }
            for shareholder in decision.shareholders
        ],
        "totalCompanyShares": decision.total_company_shares,
        "oneShareClassConfirmed": decision.one_share_class_confirmed,
        "dividend": (
            {
                "amountOre": decision.dividend.amount_ore,
                "paymentDate": decision.dividend.payment_date.value.isoformat(),
                "liquidityAfterPaymentOre": (
                    decision.dividend.liquidity_after_payment_ore
                ),
                "allocations": [
                    {
                        "shareholderId": allocation.shareholder_id,
                        "amountOre": allocation.amount_ore,
                    }
                    for allocation in decision.dividend.allocations
                ],
            }
            if decision.dividend is not None
            else None
        ),
        "annualResultAllocationOre": decision.annual_result_allocation_ore,
        "confirmations": {
            "latestApprovedAnnualAccounts": (
                decision.confirmations.latest_approved_annual_accounts
            ),
            "supportedDividendBasis": decision.confirmations.supported_dividend_basis,
            "fullBoardParticipation": decision.confirmations.full_board_participation,
            "fullShareRepresentation": (
                decision.confirmations.full_share_representation
            ),
            "unanimousBoard": decision.confirmations.unanimous_board,
            "unanimousShareholders": decision.confirmations.unanimous_shareholders,
            "proportionalAllocation": decision.confirmations.proportional_allocation,
            "prudentEquityAndLiquidity": (
                decision.confirmations.prudent_equity_and_liquidity
            ),
        },
        "decisionHash": decision.decision_hash,
    }


def _common_request(command: object) -> dict[str, object]:
    return {
        "companyId": str(command.company_id),
        "decisionId": str(command.decision_id),
        "documentSetId": str(command.document_set_id),
        "decisionHash": command.decision_hash,
        "idempotencyKey": str(command.idempotency_key),
        "correlationId": str(command.correlation_id),
    }


def _lifecycle(value: Mapping[str, object]) -> OwnerDividendLifecycle:
    finalization_id = value.get("finalizationId")
    accounting_entry_id = value.get("accountingEntryId")
    return OwnerDividendLifecycle(
        decision_id=CorporateDecisionId(str(value["decisionId"])),
        document_set_id=CorporateDocumentSetId(str(value["documentSetId"])),
        company_id=CompanyId(str(value["companyId"])),
        income_year=IncomeYear(int(value["incomeYear"])),
        decision_hash=str(value["decisionHash"]),
        state=OwnerDividendState(str(value["state"])),
        declared_amount_ore=int(value["declaredAmountOre"]),
        paid_amount_ore=int(value["paidAmountOre"]),
        remaining_amount_ore=int(value["remainingAmountOre"]),
        finalization_id=(
            CorporateFinalizationId(str(finalization_id))
            if finalization_id is not None
            else None
        ),
        accounting_entry_id=(
            AccountingEntryReference(str(accounting_entry_id))
            if accounting_entry_id is not None
            else None
        ),
        replayed=bool(value["replayed"]),
    )


def _annual_close_lifecycle(value: Mapping[str, object]) -> AnnualCloseLifecycle:
    finalization_id = value.get("finalizationId")
    generated = value.get("generatedArtifactHashes")
    signed = value.get("signedArtifactHashes")
    if not isinstance(generated, Mapping) or not isinstance(signed, Mapping):
        raise CorporateGovernanceError.unavailable()
    return AnnualCloseLifecycle(
        decision_id=CorporateDecisionId(str(value["decisionId"])),
        document_set_id=CorporateDocumentSetId(str(value["documentSetId"])),
        company_id=CompanyId(str(value["companyId"])),
        income_year=IncomeYear(int(value["incomeYear"])),
        decision_hash=str(value["decisionHash"]),
        state=OwnerDividendState(str(value["state"])),
        generated_artifact_hashes={str(key): str(item) for key, item in generated.items()},
        signed_artifact_hashes={str(key): str(item) for key, item in signed.items()},
        finalization_id=(
            CorporateFinalizationId(str(finalization_id))
            if finalization_id is not None
            else None
        ),
        replayed=bool(value["replayed"]),
    )


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    if isinstance(value, list):
        return [_plain_json(item) for item in value]
    return value


def _supported_event_request(
    command: RecordSupportedCorporateEventCommand,
    event: CanonicalSupportedCorporateEvent,
    *,
    accounting_entry_id: AccountingEntryReference | None = None,
) -> dict[str, object]:
    return {
        "eventId": str(event.event_id),
        "eventReference": str(event.event_reference),
        "companyId": str(event.company_id),
        "incomeYear": int(event.income_year),
        "eventDate": event.event_date.value.isoformat(),
        "eventKind": event.event_kind.value,
        "phase": event.phase.value,
        "policyVersion": event.policy_version,
        "canonicalFacts": _plain_json(event.canonical_facts),
        "factsSha256": event.facts_sha256,
        "documentFacts": [
            {
                "documentId": str(item.document_id),
                "evidenceKind": item.evidence_kind.value,
                "revision": item.revision,
                "contentSha256": item.content_sha256,
            }
            for item in command.document_facts
        ],
        "bankTransactionId": (
            str(command.bank_fact.transaction_id)
            if command.bank_fact is not None
            else None
        ),
        "shareholderRegisterSourceId": (
            str(command.shareholder_register_fact.record_id)
            if command.shareholder_register_fact is not None
            else None
        ),
        "taxCalculationSourceId": (
            str(command.tax_calculation_fact.record_id)
            if command.tax_calculation_fact is not None
            else None
        ),
        "accountingEntryId": (
            str(accounting_entry_id) if accounting_entry_id is not None else None
        ),
        "correctionOfEventId": None,
        "idempotencyKey": str(command.idempotency_key),
        "correlationId": str(command.correlation_id),
    }


def _recorded_supported_event(
    value: Mapping[str, object],
) -> RecordedSupportedCorporateEvent:
    bank_transaction_id = value.get("bankTransactionId")
    correction_id = value.get("correctionOfEventId")
    canonical_facts = value.get("canonicalFacts")
    if not isinstance(canonical_facts, Mapping):
        raise CorporateGovernanceError.unavailable()
    event = CanonicalSupportedCorporateEvent(
        event_id=SupportedCorporateEventId(str(value["eventId"])),
        event_reference=SupportedCorporateEventReference(
            str(value["eventReference"])
        ),
        company_id=CompanyId(str(value["companyId"])),
        income_year=IncomeYear(int(value["incomeYear"])),
        event_date=LocalDate(date.fromisoformat(str(value["eventDate"]))),
        event_kind=SupportedCorporateEventKind(str(value["eventKind"])),
        phase=SupportedCorporateEventPhase(str(value["phase"])),
        policy_version="corporate-governance-supported-events-2026.1",
        canonical_facts=dict(canonical_facts),
        facts_sha256=str(value["factsSha256"]),
    )
    return RecordedSupportedCorporateEvent(
        event=event,
        accounting_entry_id=AccountingEntryReference(
            str(value["accountingEntryId"])
        ),
        bank_transaction_id=(
            BankTransactionReference(str(bank_transaction_id))
            if bank_transaction_id is not None
            else None
        ),
        correction_of_event_id=(
            SupportedCorporateEventId(str(correction_id))
            if correction_id is not None
            else None
        ),
        recorded_at=_timestamp(value["recordedAt"]),
        replayed=bool(value["replayed"]),
    )


def _numeric(value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise CorporateGovernanceError.unavailable()
    decimal = Decimal(str(value))
    return int(decimal) if decimal == decimal.to_integral_value() else float(decimal)


def _lifecycle_snapshot(value: Mapping[str, object]) -> CorporateLifecycleSnapshot:
    def objects(name: str) -> list[Mapping[str, object]]:
        items = value.get(name)
        if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
            raise CorporateGovernanceError.unavailable()
        return items  # type: ignore[return-value]

    decisions = tuple(
        CorporateDecisionRecord(
            decision_id=CorporateDecisionId(str(item["decisionId"])),
            document_set_id=CorporateDocumentSetId(str(item["documentSetId"])),
            company_id=CompanyId(str(item["companyId"])),
            income_year=IncomeYear(int(item["incomeYear"])),
            decision_kind=CorporateDecisionKind(str(item["decisionKind"])),
            annual_close_source_id=CorporateSourceReference(
                str(item["annualCloseSourceId"])
            ),
            source_hash=str(item["sourceHash"]),
            canonical_input=dict(item["canonicalInput"]),
            decision_hash=str(item["decisionHash"]),
            supersedes_decision_id=(
                CorporateDecisionId(str(item["supersedesDecisionId"]))
                if item.get("supersedesDecisionId") is not None
                else None
            ),
            created_by=str(item["createdBy"]),
            created_at=_timestamp(item["createdAt"]),
            source_hash_uses_current_basis=bool(
                item["sourceHashUsesCurrentBasis"]
            ),
        )
        for item in objects("decisions")
    )
    document_sets = tuple(
        CorporateDocumentSetRecord(
            document_set_id=CorporateDocumentSetId(str(item["documentSetId"])),
            company_id=CompanyId(str(item["companyId"])),
            income_year=IncomeYear(int(item["incomeYear"])),
            decision_id=CorporateDecisionId(str(item["decisionId"])),
            template_family=str(item["templateFamily"]),
            template_version=str(item["templateVersion"]),
            decision_hash=str(item["decisionHash"]),
            supersedes_document_set_id=(
                CorporateDocumentSetId(str(item["supersedesDocumentSetId"]))
                if item.get("supersedesDocumentSetId") is not None
                else None
            ),
            created_by=str(item["createdBy"]),
            created_at=_timestamp(item["createdAt"]),
        )
        for item in objects("documentSets")
    )
    artifacts = tuple(
        CorporateArtifactRecord(
            artifact_id=CorporateArtifactId(str(item["artifactId"])),
            company_id=CompanyId(str(item["companyId"])),
            income_year=IncomeYear(int(item["incomeYear"])),
            document_set_id=CorporateDocumentSetId(str(item["documentSetId"])),
            artifact_kind=CorporateArtifactKind(str(item["artifactKind"])),
            variant=CorporateArtifactVariant(str(item["variant"])),
            document_id=DocumentReference(str(item["documentId"])),
            content_sha256=str(item["contentSha256"]),
            byte_length=int(item["byteLength"]),
            supersedes_artifact_id=(
                CorporateArtifactId(str(item["supersedesArtifactId"]))
                if item.get("supersedesArtifactId") is not None
                else None
            ),
            created_by=str(item["createdBy"]),
            created_at=_timestamp(item["createdAt"]),
        )
        for item in objects("artifacts")
    )
    events = tuple(
        CorporateEventRecord(
            event_id=CorporateEventId(str(item["eventId"])),
            company_id=CompanyId(str(item["companyId"])),
            income_year=IncomeYear(int(item["incomeYear"])),
            decision_id=CorporateDecisionId(str(item["decisionId"])),
            document_set_id=CorporateDocumentSetId(str(item["documentSetId"])),
            artifact_id=(
                CorporateArtifactId(str(item["artifactId"]))
                if item.get("artifactId") is not None
                else None
            ),
            event_kind=str(item["eventKind"]),
            actor_id=str(item["actorId"]),
            occurred_at=_timestamp(item["occurredAt"]),
            created_at=_timestamp(item["createdAt"]),
            decision_hash=str(item["decisionHash"]),
            content_sha256=(
                str(item["contentSha256"])
                if item.get("contentSha256") is not None
                else None
            ),
            metadata=dict(item["metadata"]),
            idempotency_key=str(item["idempotencyKey"]),
        )
        for item in objects("events")
    )
    finalizations = tuple(
        CorporateFinalizationRecord(
            finalization_id=CorporateFinalizationId(str(item["finalizationId"])),
            company_id=CompanyId(str(item["companyId"])),
            income_year=IncomeYear(int(item["incomeYear"])),
            decision_id=CorporateDecisionId(str(item["decisionId"])),
            finalization_kind=str(item["finalizationKind"]),
            holding_action_id=(
                CorporateEventId(str(item["holdingActionId"]))
                if item.get("holdingActionId") is not None
                else None
            ),
            accounting_entry_id=(
                AccountingEntryReference(str(item["accountingEntryId"]))
                if item.get("accountingEntryId") is not None
                else None
            ),
            annual_close_source_id=(
                CorporateSourceReference(str(item["annualCloseSourceId"]))
                if item.get("annualCloseSourceId") is not None
                else None
            ),
            decision_hash=str(item["decisionHash"]),
            signed_artifact_hashes={
                str(key): str(item_value)
                for key, item_value in dict(item["signedArtifactHashes"]).items()
            },
            accounting_policy_version=(
                str(item["accountingPolicyVersion"])
                if item.get("accountingPolicyVersion") is not None
                else None
            ),
            created_by=str(item["createdBy"]),
            created_at=_timestamp(item["createdAt"]),
        )
        for item in objects("finalizations")
    )
    return CorporateLifecycleSnapshot(
        decisions=decisions,
        document_sets=document_sets,
        artifacts=artifacts,
        events=events,
        finalizations=finalizations,
    )


def _shareholder_loan(value: Mapping[str, object]) -> CanonicalShareholderLoan:
    bank_transaction_id = value.get("bankTransactionId")
    document_id = value.get("documentId")
    return CanonicalShareholderLoan(
        action_id=CorporateEventId(str(value["actionId"])),
        company_id=CompanyId(str(value["companyId"])),
        income_year=IncomeYear(int(value["incomeYear"])),
        loan_date=LocalDate(date.fromisoformat(str(value["loanDate"]))),
        amount_ore=int(value["amountOre"]),
        direction=ShareholderLoanDirection(str(value["direction"])),
        counterparty_name=str(value["counterpartyName"]),
        document_status=ShareholderLoanDocumentStatus(str(value["documentStatus"])),
        interest_modelled=bool(value["interestModelled"]),
        related_party_security=bool(value["relatedPartySecurity"]),
        bank_transaction_id=(
            BankTransactionReference(str(bank_transaction_id))
            if bank_transaction_id is not None
            else None
        ),
        document_id=(
            DocumentReference(str(document_id)) if document_id is not None else None
        ),
    )


def _recorded_shareholder_loan(value: Mapping[str, object]) -> RecordedShareholderLoan:
    loan = value.get("loan")
    if not isinstance(loan, Mapping):
        raise CorporateGovernanceError.unavailable()
    return RecordedShareholderLoan(
        loan=_shareholder_loan(loan),
        accounting_entry_id=AccountingEntryReference(
            str(value["accountingEntryId"])
        ),
        replayed=bool(value["replayed"]),
    )


def _shareholder_loan_request(
    command: RecordShareholderLoanCommand,
    loan: CanonicalShareholderLoan,
) -> dict[str, object]:
    return {
        "companyId": str(command.company_id),
        "incomeYear": int(command.income_year),
        "actionId": str(command.action_id),
        "ledgerEntryId": str(command.ledger_entry_id),
        "loanDate": loan.loan_date.value.isoformat(),
        "amountOre": loan.amount_ore,
        "direction": loan.direction.value,
        "counterpartyName": loan.counterparty_name,
        "documentStatus": loan.document_status.value,
        "interestModelled": loan.interest_modelled,
        "relatedPartySecurity": loan.related_party_security,
        "bankTransactionId": (
            str(loan.bank_transaction_id)
            if loan.bank_transaction_id is not None
            else None
        ),
        "documentId": str(loan.document_id) if loan.document_id is not None else None,
        "idempotencyKey": str(command.idempotency_key),
        "correlationId": str(command.correlation_id),
    }


def _map_governance_database_error(message: str):
    if "corporate_governance_forbidden" in message:
        return CorporateGovernanceError.forbidden()
    if "corporate_governance_not_found" in message:
        return CorporateGovernanceError.not_found()
    if "corporate_governance_idempotency_conflict" in message:
        return CorporateGovernanceError.conflict()
    if "corporate_governance_finalized_declaration_required" in message:
        return CorporateGovernanceError.precondition(
            CorporateGovernanceErrorCode.FINALIZED_DECLARATION_REQUIRED,
            "A finalized owner-dividend declaration is required.",
        )
    if "corporate_governance_payment_exceeds_payable" in message:
        return CorporateGovernanceError.precondition(
            CorporateGovernanceErrorCode.PAYMENT_EXCEEDS_PAYABLE,
            "Owner-dividend payment exceeds the remaining payable.",
        )
    if "corporate_governance_accounting_policy_disabled" in message:
        return CorporateGovernanceError.precondition(
            CorporateGovernanceErrorCode.ACCOUNTING_POLICY_NOT_APPROVED,
            "An approved owner-dividend accounting policy is required.",
        )
    if "corporate_governance_missing_signed_artifacts" in message:
        return CorporateGovernanceError.precondition(
            CorporateGovernanceErrorCode.MISSING_SIGNED_ARTIFACTS,
            "Both required owner-attested signed documents are required.",
        )
    if "banking_transaction_already_reconciled" in message:
        return CorporateGovernanceError.precondition(
            CorporateGovernanceErrorCode.BANK_TRANSACTION_ALREADY_MATCHED,
            "Bank transaction is already matched.",
        )
    if "corporate_governance_invalid_input" in message:
        return CorporateGovernanceError.invalid(
            CorporateGovernanceErrorCode.INVALID_INPUT,
            "Corporate-governance persistence rejected invalid input.",
        )
    return _map_database_error(message)


class SupabaseCorporateGovernanceAdapter:
    """Authenticate one bearer and bind governance to one short DB transaction."""

    def __init__(self, configuration: LedgerSupabaseConfiguration) -> None:
        self._configuration = configuration
        self._ledger_authentication = SupabaseLedgerAdapter(configuration)

    @classmethod
    def from_environment(cls) -> SupabaseCorporateGovernanceAdapter:
        return cls(
            LedgerSupabaseConfiguration(
                url=os.environ.get("SUPABASE_URL", ""),
                anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
                database_url=os.environ.get("TALLI_LEDGER_DATABASE_URL", ""),
            )
        )

    async def session(self, access_token: str) -> SupabaseCorporateGovernanceSession:
        try:
            ledger_session: SupabaseLedgerSession = (
                await self._ledger_authentication.session(access_token)
            )
        except LedgerAuthenticationError:
            raise CorporateGovernanceAuthenticationError from None
        return SupabaseCorporateGovernanceSession(
            self._configuration.database_url,
            ledger_session._verified,
        )


@corporate_governance_persistence_adapter(CorporateGovernancePersistence)
class SupabaseCorporateGovernanceSession:
    def __init__(self, database_url: str, verified: _VerifiedActor) -> None:
        self._database_url = database_url
        self._verified = verified

    @property
    def actor_id(self) -> ActorId:
        return self._verified.actor_id

    @asynccontextmanager
    async def transaction(
        self,
    ) -> AsyncIterator[SupabaseCorporateGovernanceTransaction]:
        if not self._database_url:
            raise CorporateGovernanceError.unavailable()
        try:
            async with await psycopg.AsyncConnection.connect(
                self._database_url,
                connect_timeout=5,
                row_factory=dict_row,
            ) as connection:
                await connection.set_isolation_level(psycopg.IsolationLevel.SERIALIZABLE)
                async with connection.transaction():
                    await connection.execute(
                        "set local role corporate_governance_workflow_executor"
                    )
                    await connection.execute(
                        "select pg_catalog.set_config('talli.verified_actor_id', %s, true)",
                        (str(self.actor_id.subject),),
                    )
                    await connection.execute(
                        "select pg_catalog.set_config('talli.verified_actor_claims', %s, true)",
                        (self._verified.claims_json,),
                    )
                    yield SupabaseCorporateGovernanceTransaction(
                        self._database_url,
                        self._verified,
                        connection,
                    )
        except (CorporateGovernanceError, LedgerError):
            raise
        except psycopg.OperationalError:
            raise CorporateGovernanceError.unavailable() from None
        except psycopg.DatabaseError as error:
            raise _map_governance_database_error(str(error)) from None


@bank_transaction_claim_persistence_adapter(BankTransactionClaimPersistence)
class SupabaseCorporateGovernanceTransaction(SupabaseLedgerWorkflowTransaction):
    async def _database_rows(
        self,
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> list[Mapping[str, object]]:
        try:
            cursor = await self._connection.execute(query, parameters)
            return list(await cursor.fetchall())
        except psycopg.OperationalError:
            raise CorporateGovernanceError.unavailable() from None
        except psycopg.DatabaseError as error:
            raise _map_governance_database_error(str(error)) from None

    async def _governance_result(
        self,
        query: str,
        request: Mapping[str, object],
    ) -> Mapping[str, object]:
        rows = await self._database_rows(
            query,
            (
                json.dumps(request, separators=(",", ":")),
                str(self.actor_id.subject),
            ),
        )
        if len(rows) != 1 or not isinstance(rows[0].get("result"), Mapping):
            raise CorporateGovernanceError.unavailable()
        return rows[0]["result"]  # type: ignore[return-value]

    async def actor_role(self, company_id: CompanyId) -> str | None:
        rows = await self._database_rows(
            "select corporate_governance.actor_company_role_v1(%s::uuid, %s::text) as role",
            (str(company_id), str(self.actor_id.subject)),
        )
        if len(rows) != 1:
            raise CorporateGovernanceError.unavailable()
        role = rows[0].get("role")
        return str(role) if role is not None else None

    async def read_company_facts(
        self,
        company_id: CompanyId,
    ) -> PersistedCompanyFacts:
        rows = await self._database_rows(
            "select public.company_access_read_company_identity_v1("
            "%s::uuid, %s::text) as result",
            (str(company_id), str(self.actor_id.subject)),
        )
        if len(rows) != 1 or not isinstance(rows[0].get("result"), Mapping):
            raise CorporateGovernanceError.unavailable()
        result = rows[0]["result"]
        try:
            if str(result["companyId"]) != str(company_id):  # type: ignore[index]
                raise CorporateGovernanceError.unavailable()
            return PersistedCompanyFacts(
                company_id=company_id,
                organization_number=str(result["organizationNumber"]),  # type: ignore[index]
                legal_name=str(result["legalName"]),  # type: ignore[index]
            )
        except (KeyError, TypeError, ValueError):
            raise CorporateGovernanceError.unavailable() from None

    async def list_annual_data_compatibility(
        self,
        *,
        company_id: CompanyId,
        income_year: IncomeYear,
    ) -> tuple[LegacyAnnualDataView, ...]:
        rows = await self._database_rows(
            "select backend_system.list_annual_data_legacy_v1("
            "%s::uuid, %s::integer, %s::text) as items",
            (
                str(company_id),
                int(income_year),
                str(self.actor_id.subject),
            ),
        )
        if len(rows) != 1 or not isinstance(rows[0].get("items"), list):
            raise CorporateGovernanceError.unavailable()
        items = rows[0]["items"]
        if not all(isinstance(item, Mapping) for item in items):
            raise CorporateGovernanceError.unavailable()
        try:
            return tuple(
                LegacyAnnualDataView(
                    source_id=str(item["sourceId"]),
                    company_id=CompanyId(str(item["companyId"])),
                    income_year=IncomeYear(int(item["incomeYear"])),
                    answers=dict(item["answers"]),
                    confirmations=tuple(str(value) for value in item["confirmations"]),
                    no_activity_confirmed=bool(item["noActivityConfirmed"]),
                    annual_full_time_equivalents=_numeric(
                        item["annualFullTimeEquivalents"]
                        if item["annualFullTimeEquivalents"] is not None
                        else 0
                    ),
                    completed_at=(
                        item["completedAt"].isoformat()
                        if isinstance(item["completedAt"], datetime)
                        else str(item["completedAt"])
                    ),
                    updated_at=(
                        item["updatedAt"].isoformat()
                        if isinstance(item["updatedAt"], datetime)
                        else str(item["updatedAt"])
                    ),
                )
                for item in items
            )
        except (KeyError, TypeError, ValueError):
            raise CorporateGovernanceError.unavailable() from None

    async def read_reporting_year_basis(self, company_id: CompanyId) -> CorporateReportingYearBasis:
        # The authenticated session owns one SERIALIZABLE transaction. Both
        # existing owner RPCs therefore read the same coherent MVCC snapshot.
        return CorporateReportingYearBasis(company_id,
            await self.list_lifecycle((company_id,)), await self.list_supported_events((company_id,)))

    async def list_lifecycle(
        self,
        company_ids: tuple[CompanyId, ...],
    ) -> CorporateLifecycleSnapshot:
        rows = await self._database_rows(
            "select corporate_governance.read_corporate_lifecycle_v1("
            "%s::uuid[], null::uuid, %s::text) as result",
            ([str(company_id) for company_id in company_ids], str(self.actor_id.subject)),
        )
        if len(rows) != 1 or not isinstance(rows[0].get("result"), Mapping):
            raise CorporateGovernanceError.unavailable()
        return _lifecycle_snapshot(rows[0]["result"])  # type: ignore[arg-type]

    async def read_lifecycle(
        self,
        decision_id: CorporateDecisionId,
    ) -> CorporateLifecycleSnapshot:
        rows = await self._database_rows(
            "select corporate_governance.read_corporate_lifecycle_v1("
            "null::uuid[], %s::uuid, %s::text) as result",
            (str(decision_id), str(self.actor_id.subject)),
        )
        if len(rows) != 1 or not isinstance(rows[0].get("result"), Mapping):
            raise CorporateGovernanceError.unavailable()
        return _lifecycle_snapshot(rows[0]["result"])  # type: ignore[arg-type]

    async def list_supported_events(
        self,
        company_ids: tuple[CompanyId, ...],
    ) -> tuple[RecordedSupportedCorporateEvent, ...]:
        rows = await self._database_rows(
            "select corporate_governance.list_supported_events_v1("
            "%s::uuid[], %s::text) as result",
            (
                [str(company_id) for company_id in company_ids],
                str(self.actor_id.subject),
            ),
        )
        results: list[RecordedSupportedCorporateEvent] = []
        for row in rows:
            result = row.get("result")
            if not isinstance(result, Mapping):
                raise CorporateGovernanceError.unavailable()
            results.append(_recorded_supported_event(result))
        return tuple(results)

    async def propose_owner_dividend(
        self,
        command: OwnerDividendProposalCommand,
        decision: CanonicalOwnerDividendDecision,
        canonical_input: Mapping[str, object],
    ) -> ProposedOwnerDividend:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        rows = await self._database_rows(
            "select corporate_governance.propose_owner_dividend_v1("
            "%s::jsonb, %s::jsonb, %s::jsonb, %s::text) as result",
            (
                json.dumps(_proposal_request(command), separators=(",", ":")),
                json.dumps(_canonical_decision(decision), separators=(",", ":")),
                json.dumps(
                    canonical_input,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
                str(command.actor_id.subject),
            ),
        )
        if len(rows) != 1 or not isinstance(rows[0].get("result"), Mapping):
            raise CorporateGovernanceError.unavailable()
        result = rows[0]["result"]
        return ProposedOwnerDividend(
            decision=decision,
            state=OwnerDividendState(str(result["state"])),
            replayed=bool(result["replayed"]),
        )

    async def propose_annual_close(
        self,
        command: AnnualCloseProposalCommand,
        decision: CanonicalAnnualCloseDecision,
        canonical_input: Mapping[str, object],
        artifacts,
    ) -> ProposedAnnualClose:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        rows = await self._database_rows(
            "select corporate_governance.propose_annual_close_v1("
            "%s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::text) as result",
            (
                json.dumps(_proposal_request(command), separators=(",", ":")),
                json.dumps(_canonical_decision(decision), separators=(",", ":")),
                json.dumps(
                    canonical_input,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
                json.dumps(
                    [
                        {
                            "artifactKind": artifact.artifact_kind.value,
                            "filename": artifact.filename,
                            "templateVersion": artifact.template_version,
                            "decisionHash": artifact.decision_hash,
                            "contentSha256": artifact.content_sha256,
                            "byteLength": artifact.byte_length,
                        }
                        for artifact in artifacts
                    ],
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
                str(command.actor_id.subject),
            ),
        )
        if len(rows) != 1 or not isinstance(rows[0].get("result"), Mapping):
            raise CorporateGovernanceError.unavailable()
        result = rows[0]["result"]
        return ProposedAnnualClose(
            decision=decision,
            state=OwnerDividendState(str(result["state"])),
            replayed=bool(result["replayed"]),
        )

    async def register_owner_dividend_documents(
        self,
        command: RegisterOwnerDividendDocumentsCommand,
    ) -> OwnerDividendLifecycle:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        request = {
            **_common_request(command),
            "artifacts": [
                {
                    "artifactId": str(artifact.artifact_id),
                    "documentId": str(artifact.document_id),
                    "artifactKind": artifact.artifact_kind.value,
                    "contentSha256": artifact.content_sha256,
                    "byteLength": artifact.byte_length,
                }
                for artifact in command.artifacts
            ],
        }
        return _lifecycle(await self._governance_result(
            "select backend_system.register_corporate_governance_documents_v1("
            "'owner_dividend', %s::jsonb, %s::text) as result",
            request,
        ))

    async def register_annual_close_documents(
        self,
        command: RegisterAnnualCloseDocumentsCommand,
    ) -> AnnualCloseLifecycle:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        request = {
            **_common_request(command),
            "artifacts": [
                {
                    "artifactId": str(artifact.artifact_id),
                    "documentId": str(artifact.document_id),
                    "artifactKind": artifact.artifact_kind.value,
                    "contentSha256": artifact.content_sha256,
                    "byteLength": artifact.byte_length,
                }
                for artifact in command.artifacts
            ],
        }
        return _annual_close_lifecycle(await self._governance_result(
            "select backend_system.register_corporate_governance_documents_v1("
            "'annual_close', %s::jsonb, %s::text) as result",
            request,
        ))

    async def approve_owner_dividend(
        self,
        command: ApproveOwnerDividendCommand,
    ) -> OwnerDividendLifecycle:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        return _lifecycle(await self._governance_result(
            "select corporate_governance.approve_owner_dividend_v1("
            "%s::jsonb, %s::text) as result",
            {**_common_request(command), "approvalEventId": str(command.approval_event_id)},
        ))

    async def approve_annual_close(
        self,
        command: ApproveAnnualCloseCommand,
    ) -> AnnualCloseLifecycle:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        return _annual_close_lifecycle(await self._governance_result(
            "select corporate_governance.approve_annual_close_v1("
            "%s::jsonb, %s::text) as result",
            {
                **_common_request(command),
                "approvalEventId": str(command.approval_event_id),
            },
        ))

    async def record_annual_close_event(
        self,
        command: RecordAnnualCloseEventCommand,
    ) -> AnnualCloseLifecycle:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        return _annual_close_lifecycle(await self._governance_result(
            "select corporate_governance.record_annual_close_event_v1("
            "%s::jsonb, %s::text) as result",
            {
                **_common_request(command),
                "eventId": str(command.event_id),
                "eventKind": command.event_kind.value,
                "metadata": dict(command.metadata),
            },
        ))

    async def finalize_annual_close(
        self,
        command: FinalizeAnnualCloseCommand,
    ) -> AnnualCloseLifecycle:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        return _annual_close_lifecycle(await self._governance_result(
            "select corporate_governance.finalize_annual_close_v1("
            "%s::jsonb, %s::text) as result",
            {
                **_common_request(command),
                "finalizationId": str(command.finalization_id),
            },
        ))

    async def attest_annual_close_signed_artifact(
        self,
        command: AttestAnnualCloseSignedArtifactCommand,
    ) -> AnnualCloseLifecycle:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        return _annual_close_lifecycle(await self._governance_result(
            "select backend_system.attest_corporate_governance_signed_artifact_v1("
            "'annual_close', %s::jsonb, %s::text) as result",
            {
                **_common_request(command),
                "unsignedArtifactId": str(command.unsigned_artifact_id),
                "signedArtifactId": str(command.signed_artifact_id),
                "signedDocumentId": str(command.signed_document_id),
                "artifactKind": command.artifact_kind.value,
                "filename": command.filename,
                "contentSha256": command.content_sha256,
                "byteLength": command.byte_length,
                "signers": list(command.signers),
            },
        ))

    async def record_owner_dividend_event(
        self,
        command: RecordOwnerDividendEventCommand,
    ) -> OwnerDividendLifecycle:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        return _lifecycle(await self._governance_result(
            "select corporate_governance.record_owner_dividend_event_v1("
            "%s::jsonb, %s::text) as result",
            {
                **_common_request(command),
                "eventId": str(command.event_id),
                "eventKind": command.event_kind.value,
                "metadata": dict(command.metadata),
            },
        ))

    async def attest_owner_dividend_signed_artifact(
        self,
        command: AttestOwnerDividendSignedArtifactCommand,
    ) -> OwnerDividendLifecycle:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        return _lifecycle(await self._governance_result(
            "select backend_system.attest_corporate_governance_signed_artifact_v1("
            "'owner_dividend', %s::jsonb, %s::text) as result",
            {
                **_common_request(command),
                "unsignedArtifactId": str(command.unsigned_artifact_id),
                "signedArtifactId": str(command.signed_artifact_id),
                "signedDocumentId": str(command.signed_document_id),
                "artifactKind": command.artifact_kind.value,
                "filename": command.filename,
                "contentSha256": command.content_sha256,
                "byteLength": command.byte_length,
                "signers": list(command.signers),
            },
        ))

    async def prepare_owner_dividend_finalization(
        self,
        command: FinalizeOwnerDividendCommand,
    ) -> PreparedOwnerDividendFinalization:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        result = await self._governance_result(
            "select corporate_governance.prepare_owner_dividend_finalization_v1("
            "%s::jsonb, %s::text) as result",
            {
                **_common_request(command),
                "incomeYear": int(command.income_year),
                "finalizationId": str(command.finalization_id),
                "holdingActionId": str(command.holding_action_id),
                "ledgerEntryId": str(command.ledger_entry_id),
            },
        )
        replay = result.get("replay")
        return PreparedOwnerDividendFinalization(
            declared_amount_ore=int(result["declaredAmountOre"]),
            accounting_policy_version=str(result["accountingPolicyVersion"]),
            declaration_debit_account=str(result["declarationDebitAccount"]),
            dividend_payable_account=str(result["dividendPayableAccount"]),
            signed_artifact_hashes={
                str(key): str(value)
                for key, value in dict(result["signedArtifactHashes"]).items()
            },
            replay=_lifecycle(replay) if isinstance(replay, Mapping) else None,
        )

    async def complete_owner_dividend_finalization(
        self,
        command: FinalizeOwnerDividendCommand,
        accounting_entry_id: AccountingEntryReference,
        prepared: PreparedOwnerDividendFinalization,
    ) -> OwnerDividendLifecycle:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        return _lifecycle(await self._governance_result(
            "select corporate_governance.complete_owner_dividend_finalization_v1("
            "%s::jsonb, %s::text) as result",
            {
                **_common_request(command),
                "incomeYear": int(command.income_year),
                "finalizationId": str(command.finalization_id),
                "holdingActionId": str(command.holding_action_id),
                "ledgerEntryId": str(accounting_entry_id),
                "declaredAmountOre": prepared.declared_amount_ore,
                "accountingPolicyVersion": prepared.accounting_policy_version,
                "signedArtifactHashes": dict(prepared.signed_artifact_hashes),
            },
        ))

    async def prepare_owner_dividend_payment(
        self,
        command: RecordOwnerDividendPaymentCommand,
    ) -> PreparedOwnerDividendPayment:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        result = await self._governance_result(
            "select corporate_governance.prepare_owner_dividend_payment_v1("
            "%s::jsonb, %s::text) as result",
            {
                **_common_request(command),
                "incomeYear": int(command.income_year),
                "paymentEventId": str(command.payment_event_id),
                "holdingActionId": str(command.holding_action_id),
                "ledgerEntryId": str(command.ledger_entry_id),
                "bankTransactionId": str(command.bank_transaction_id),
            },
        )
        replay = result.get("replay")
        return PreparedOwnerDividendPayment(
            payment_amount_ore=int(result["paymentAmountOre"]),
            bank_transaction_date=LocalDate(
                date.fromisoformat(str(result["bankTransactionDate"]))
            ),
            bank_signed_amount=Money.nok(str(result["bankSignedAmount"])),
            bank_source_sha256=str(result["bankSourceSha256"]),
            accounting_policy_version=str(result["accountingPolicyVersion"]),
            dividend_payable_account=str(result["dividendPayableAccount"]),
            bank_account=str(result["bankAccount"]),
            replay=_lifecycle(replay) if isinstance(replay, Mapping) else None,
        )

    async def complete_owner_dividend_payment(
        self,
        command: RecordOwnerDividendPaymentCommand,
        accounting_entry_id: AccountingEntryReference,
        prepared: PreparedOwnerDividendPayment,
    ) -> OwnerDividendLifecycle:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        return _lifecycle(await self._governance_result(
            "select corporate_governance.complete_owner_dividend_payment_v1("
            "%s::jsonb, %s::text) as result",
            {
                **_common_request(command),
                "incomeYear": int(command.income_year),
                "paymentEventId": str(command.payment_event_id),
                "holdingActionId": str(command.holding_action_id),
                "ledgerEntryId": str(accounting_entry_id),
                "bankTransactionId": str(command.bank_transaction_id),
                "paymentAmountOre": prepared.payment_amount_ore,
                "bankTransactionDate": prepared.bank_transaction_date.value.isoformat(),
                "bankSignedAmount": format(prepared.bank_signed_amount.amount, "f"),
                "bankSourceSha256": prepared.bank_source_sha256,
                "accountingPolicyVersion": prepared.accounting_policy_version,
            },
        ))

    async def prepare_shareholder_loan(
        self,
        command: RecordShareholderLoanCommand,
        loan: CanonicalShareholderLoan,
    ) -> PreparedShareholderLoan:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        result = await self._governance_result(
            "select corporate_governance.prepare_shareholder_loan_v1("
            "%s::jsonb, %s::text) as result",
            _shareholder_loan_request(command, loan),
        )
        result_loan = result.get("loan")
        if not isinstance(result_loan, Mapping):
            raise CorporateGovernanceError.unavailable()
        replay = result.get("replay")
        bank_transaction_date = result.get("bankTransactionDate")
        bank_signed_amount = result.get("bankSignedAmount")
        bank_source_sha256 = result.get("bankSourceSha256")
        return PreparedShareholderLoan(
            loan=_shareholder_loan(result_loan),
            bank_transaction_date=(
                LocalDate(date.fromisoformat(str(bank_transaction_date)))
                if bank_transaction_date is not None
                else None
            ),
            bank_signed_amount=(
                Money.nok(Decimal(str(bank_signed_amount)))
                if bank_signed_amount is not None
                else None
            ),
            bank_source_sha256=(
                str(bank_source_sha256)
                if bank_source_sha256 is not None
                else None
            ),
            replay=(
                _recorded_shareholder_loan(replay)
                if isinstance(replay, Mapping)
                else None
            ),
        )

    async def complete_shareholder_loan(
        self,
        command: RecordShareholderLoanCommand,
        accounting_entry_id: AccountingEntryReference,
        prepared: PreparedShareholderLoan,
    ) -> RecordedShareholderLoan:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        result = await self._governance_result(
            "select backend_system.complete_corporate_governance_shareholder_loan_v1("
            "%s::jsonb, %s::text) as result",
            {
                **_shareholder_loan_request(command, prepared.loan),
                "ledgerEntryId": str(accounting_entry_id),
                "bankTransactionDate": (
                    prepared.bank_transaction_date.value.isoformat()
                    if prepared.bank_transaction_date is not None
                    else None
                ),
                "bankSignedAmount": (
                    format(prepared.bank_signed_amount.amount, "f")
                    if prepared.bank_signed_amount is not None
                    else None
                ),
                "bankSourceSha256": prepared.bank_source_sha256,
            },
        )
        return _recorded_shareholder_loan(result)

    async def prepare_supported_event(
        self,
        command: RecordSupportedCorporateEventCommand,
        event: CanonicalSupportedCorporateEvent,
    ) -> PreparedSupportedCorporateEvent:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        result = await self._governance_result(
            "select corporate_governance.prepare_supported_event_v1("
            "%s::jsonb, %s::text) as result",
            _supported_event_request(command, event),
        )
        replay = result.get("replay")
        return PreparedSupportedCorporateEvent(
            event=event,
            replay=(
                _recorded_supported_event(replay)
                if isinstance(replay, Mapping)
                else None
            ),
        )

    async def complete_supported_event(
        self,
        command: RecordSupportedCorporateEventCommand,
        accounting_entry_id: AccountingEntryReference,
        prepared: PreparedSupportedCorporateEvent,
    ) -> RecordedSupportedCorporateEvent:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        result = await self._governance_result(
            "select corporate_governance.complete_supported_event_v1("
            "%s::jsonb, %s::text) as result",
            _supported_event_request(
                command,
                prepared.event,
                accounting_entry_id=accounting_entry_id,
            ),
        )
        return _recorded_supported_event(result)

    async def claim_transaction_for_external_action(
        self,
        command: ClaimBankTransactionForExternalActionCommand,
        *,
        accounting_entry_id,
    ) -> None:
        if command.actor_id != self.actor_id:
            raise CorporateGovernanceError.forbidden()
        rows = await self._database_rows(
            "select banking.claim_corporate_governance_transaction_v1("
            "%s::jsonb, %s::uuid, %s::text) as result",
            (
                json.dumps(
                    {
                        "companyId": str(command.company_id),
                        "incomeYear": int(command.income_year),
                        "transactionId": str(command.transaction_id),
                        "transactionDate": command.transaction_date.value.isoformat(),
                        "signedAmount": format(command.signed_amount.amount, "f"),
                        "sourceHash": command.source_hash,
                        "actionReference": str(command.action_reference),
                    },
                    separators=(",", ":"),
                ),
                str(accounting_entry_id),
                str(command.actor_id.subject),
            ),
        )
        if len(rows) != 1 or not isinstance(rows[0].get("result"), Mapping):
            raise CorporateGovernanceError.unavailable()

    async def post_entry(
        self,
        command: LedgerCommand,
        *,
        entry_kind: LedgerEntryKind,
        memo: str,
        lines: tuple[LedgerLine, ...],
        risk_flags: tuple[LedgerRiskFlag, ...],
        warning_accepted: bool,
        source_capability: LedgerSourceCapability,
        source_record_id: LedgerSourceRecordId,
        requested_entry_id=None,
    ):
        if isinstance(command, RecognizeHoldingActionCommand):
            return await super().post_entry(
                command,
                entry_kind=entry_kind,
                memo=memo,
                lines=lines,
                risk_flags=risk_flags,
                warning_accepted=warning_accepted,
                source_capability=source_capability,
                source_record_id=source_record_id,
                requested_entry_id=requested_entry_id,
            )
        expected_kind = (
            LedgerEntryKind.OWNER_DIVIDEND_DECLARED
            if isinstance(command, PostOwnerDividendDeclaredCommand)
            else (
                LedgerEntryKind.OWNER_DIVIDEND_PAYMENT
                if isinstance(command, PostOwnerDividendPaymentCommand)
                else (
                    LedgerEntryKind.SHAREHOLDER_LOAN
                    if isinstance(command, PostShareholderLoanCommand)
                    else None
                )
            )
        )
        if (
            command.actor_id != self.actor_id
            or expected_kind is None
            or entry_kind is not expected_kind
            or risk_flags
            or warning_accepted
            or source_capability is not LedgerSourceCapability.CORPORATE_GOVERNANCE
            or requested_entry_id is None
        ):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        row = await self._one_idempotent_row(
            """
            select * from ledger.post_corporate_governance_entry_v1(
              %s::text, %s::uuid, %s::integer, %s::text, %s::text,
              %s::jsonb, %s::text, %s::text, %s::text, %s::text,
              %s::uuid
            )
            """,
            (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                entry_kind.value,
                memo,
                json.dumps([_line_payload(line) for line in lines], separators=(",", ":")),
                source_capability.value,
                str(source_record_id),
                str(command.correlation_id),
                str(command.actor_id.subject),
                str(requested_entry_id),
            ),
        )
        return _posted_entry(row)


def compose_corporate_governance_application(
    sessions: CorporateGovernanceSessionFactory | None,
    documents: DocumentsSessionFactory,
) -> CorporateGovernanceApplication:
    return CorporateGovernanceApplication(
        sessions or SupabaseCorporateGovernanceAdapter.from_environment(),
        documents,
        LedgerService,
    )


__all__ = [
    "SupabaseCorporateGovernanceAdapter",
    "SupabaseCorporateGovernanceSession",
    "SupabaseCorporateGovernanceTransaction",
    "compose_corporate_governance_application",
]
