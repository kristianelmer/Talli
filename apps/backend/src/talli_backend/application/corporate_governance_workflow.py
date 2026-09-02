"""Authenticated owner-dividend workflows and atomic capability composition."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from talli_backend.application.corporate_governance_session import (
    CorporateGovernanceSessionFactory,
    CorporateGovernanceWorkflowTransaction,
)
from talli_backend.modules.banking.public import (
    AccountingEntryReference as BankingAccountingEntryReference,
    BankTransactionId,
    ClaimBankTransactionForExternalActionCommand,
    ExternalActionReference,
)
from talli_backend.modules.corporate_governance.public import (
    AccountingEntryReference,
    ApproveOwnerDividendCommand,
    CorporateArtifactKind,
    CorporateGovernanceError,
    CorporateGovernanceErrorCode,
    FinalizeOwnerDividendCommand,
    OwnerDividendLifecycle,
    OwnerDividendProposalCommand,
    ProposedOwnerDividend,
    RecordOwnerDividendPaymentCommand,
    RegisterOwnerDividendDocumentsCommand,
    SHA256_PATTERN,
)
from talli_backend.modules.corporate_governance.service import (
    CorporateGovernanceService,
)
from talli_backend.modules.documents.public import (
    DocumentStatus,
    DocumentsSessionFactory,
)
from talli_backend.modules.ledger.public import (
    LedgerCommands,
    LedgerEntryId,
    LedgerPersistence,
    LedgerSourceRecordId,
    PostOwnerDividendDeclaredCommand,
    PostOwnerDividendPaymentCommand,
)
from talli_backend.shared.kernel import ActorId, Money


LedgerFacadeFactory = Callable[[LedgerPersistence], LedgerCommands]
_REQUIRED_ARTIFACT_KINDS = {
    CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL,
    CorporateArtifactKind.DIVIDEND_GENERAL_MEETING_MINUTES,
}


def _money_from_ore(value: int) -> Money:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CorporateGovernanceError.unavailable()
    return Money.nok(Decimal(value) / Decimal(100))


class CorporateGovernanceApplication:
    def __init__(
        self,
        session_factory: CorporateGovernanceSessionFactory,
        documents_session_factory: DocumentsSessionFactory,
        ledger_facade_factory: LedgerFacadeFactory,
    ) -> None:
        self._session_factory = session_factory
        self._documents_session_factory = documents_session_factory
        self._ledger_facade_factory = ledger_facade_factory
        self._service = CorporateGovernanceService()

    async def authenticated_actor_id(self, access_token: str) -> ActorId:
        """Resolve the verified actor without accepting an actor from transport input."""

        return (await self._session_factory.session(access_token)).actor_id

    async def _session(self, access_token: str, actor_id):
        session = await self._session_factory.session(access_token)
        if session.actor_id != actor_id:
            raise CorporateGovernanceError.forbidden()
        return session

    @staticmethod
    async def _require_owner(
        transaction: CorporateGovernanceWorkflowTransaction,
        company_id,
    ) -> None:
        if await transaction.actor_role(company_id) != "owner":
            raise CorporateGovernanceError.forbidden()

    async def propose_owner_dividend(
        self,
        access_token: str,
        command: OwnerDividendProposalCommand,
    ) -> ProposedOwnerDividend:
        session = await self._session(access_token, command.actor_id)
        decision = self._service.build_owner_dividend_decision(command)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            return await transaction.propose_owner_dividend(command, decision)

    async def register_owner_dividend_documents(
        self,
        access_token: str,
        command: RegisterOwnerDividendDocumentsCommand,
    ) -> OwnerDividendLifecycle:
        session = await self._session(access_token, command.actor_id)
        documents = await self._documents_session_factory.session(access_token)
        if documents.actor_id != command.actor_id:
            raise CorporateGovernanceError.forbidden()
        if (
            len(command.artifacts) != 2
            or {artifact.artifact_kind for artifact in command.artifacts}
            != _REQUIRED_ARTIFACT_KINDS
            or len({str(artifact.artifact_id) for artifact in command.artifacts}) != 2
            or len({str(artifact.document_id) for artifact in command.artifacts}) != 2
        ):
            raise CorporateGovernanceError.invalid(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                "Owner-dividend documents must contain the exact required artifacts.",
            )
        records = await documents.list_documents((command.company_id,))
        by_id = {str(record.document_id): record for record in records}
        for artifact in command.artifacts:
            record = by_id.get(str(artifact.document_id))
            if (
                record is None
                or record.company_id != command.company_id
                or record.linked_to != f"corporate_decision:{command.decision_id}"
                or record.status is not DocumentStatus.GENERATED_UNSIGNED
                or not SHA256_PATTERN.fullmatch(artifact.content_sha256)
                or record.content_sha256 != artifact.content_sha256
                or artifact.byte_length <= 0
                or record.byte_length != artifact.byte_length
            ):
                raise CorporateGovernanceError.precondition(
                    CorporateGovernanceErrorCode.UNSUPPORTED_DIVIDEND_BASIS,
                    "Document evidence does not match the owner-dividend proposal.",
                )
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            return await transaction.register_owner_dividend_documents(command)

    async def approve_owner_dividend(
        self,
        access_token: str,
        command: ApproveOwnerDividendCommand,
    ) -> OwnerDividendLifecycle:
        session = await self._session(access_token, command.actor_id)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            return await transaction.approve_owner_dividend(command)

    async def finalize_owner_dividend(
        self,
        access_token: str,
        command: FinalizeOwnerDividendCommand,
    ) -> OwnerDividendLifecycle:
        session = await self._session(access_token, command.actor_id)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            prepared = await transaction.prepare_owner_dividend_finalization(command)
            if prepared.replay is not None:
                return prepared.replay
            policy = self._service.owner_dividend_accounting_policy()
            ledger = self._ledger_facade_factory(transaction)
            posted = await ledger.post_owner_dividend_declared(
                PostOwnerDividendDeclaredCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    finalization_id=LedgerSourceRecordId(str(command.finalization_id)),
                    declared_amount=_money_from_ore(prepared.declared_amount_ore),
                    declaration_debit_account=policy.declaration_debit_account,
                    dividend_payable_account=policy.dividend_payable_account,
                    accounting_policy_version=policy.version,
                    ledger_entry_id=LedgerEntryId(str(command.ledger_entry_id)),
                )
            )
            if posted.entry_id != LedgerEntryId(str(command.ledger_entry_id)):
                raise CorporateGovernanceError.unavailable()
            return await transaction.complete_owner_dividend_finalization(
                command,
                AccountingEntryReference(str(posted.entry_id)),
                prepared,
            )

    async def record_owner_dividend_payment(
        self,
        access_token: str,
        command: RecordOwnerDividendPaymentCommand,
    ) -> OwnerDividendLifecycle:
        session = await self._session(access_token, command.actor_id)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            prepared = await transaction.prepare_owner_dividend_payment(command)
            if prepared.replay is not None:
                return prepared.replay
            policy = self._service.owner_dividend_accounting_policy()
            ledger = self._ledger_facade_factory(transaction)
            posted = await ledger.post_owner_dividend_payment(
                PostOwnerDividendPaymentCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    payment_event_id=LedgerSourceRecordId(str(command.payment_event_id)),
                    payment_amount=_money_from_ore(prepared.payment_amount_ore),
                    dividend_payable_account=policy.dividend_payable_account,
                    bank_account=policy.bank_account,
                    accounting_policy_version=policy.version,
                    ledger_entry_id=LedgerEntryId(str(command.ledger_entry_id)),
                )
            )
            if posted.entry_id != LedgerEntryId(str(command.ledger_entry_id)):
                raise CorporateGovernanceError.unavailable()
            await transaction.claim_transaction_for_external_action(
                ClaimBankTransactionForExternalActionCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    transaction_id=BankTransactionId(str(command.bank_transaction_id)),
                    transaction_date=prepared.bank_transaction_date,
                    signed_amount=prepared.bank_signed_amount,
                    source_hash=prepared.bank_source_sha256,
                    action_reference=ExternalActionReference(str(command.payment_event_id)),
                ),
                accounting_entry_id=BankingAccountingEntryReference(
                    str(posted.entry_id)
                ),
            )
            return await transaction.complete_owner_dividend_payment(
                command,
                AccountingEntryReference(str(posted.entry_id)),
                prepared,
            )


__all__ = ["CorporateGovernanceApplication", "LedgerFacadeFactory"]
