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
    AnnualCloseProposalCommand,
    ApproveOwnerDividendCommand,
    CorporateArtifactKind,
    CorporateGovernanceError,
    CorporateGovernanceErrorCode,
    FinalizeOwnerDividendCommand,
    OwnerDividendLifecycle,
    OwnerDividendProposalCommand,
    ProposedAnnualClose,
    ProposedOwnerDividend,
    RecordShareholderLoanCommand,
    RecordOwnerDividendPaymentCommand,
    RecordedShareholderLoan,
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
    PostShareholderLoanCommand,
    ShareholderLoanDirection as LedgerShareholderLoanDirection,
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
            proposed = await transaction.propose_owner_dividend(command, decision)
        return ProposedOwnerDividend(
            decision=proposed.decision,
            state=proposed.state,
            replayed=proposed.replayed,
            artifacts=self._service.render_corporate_documents(proposed.decision),
        )

    async def propose_annual_close(
        self,
        access_token: str,
        command: AnnualCloseProposalCommand,
    ) -> ProposedAnnualClose:
        session = await self._session(access_token, command.actor_id)
        decision = self._service.build_annual_close_decision(command)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            proposed = await transaction.propose_annual_close(command, decision)
        return ProposedAnnualClose(
            decision=proposed.decision,
            state=proposed.state,
            replayed=proposed.replayed,
            artifacts=self._service.render_corporate_documents(proposed.decision),
        )

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
                    declaration_debit_account=prepared.declaration_debit_account,
                    dividend_payable_account=prepared.dividend_payable_account,
                    accounting_policy_version=prepared.accounting_policy_version,
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
                    dividend_payable_account=prepared.dividend_payable_account,
                    bank_account=prepared.bank_account,
                    accounting_policy_version=prepared.accounting_policy_version,
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
                    action_reference=ExternalActionReference(str(command.holding_action_id)),
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

    async def record_shareholder_loan(
        self,
        access_token: str,
        command: RecordShareholderLoanCommand,
    ) -> RecordedShareholderLoan:
        session = await self._session(access_token, command.actor_id)
        loan = self._service.validate_shareholder_loan(command)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            prepared = await transaction.prepare_shareholder_loan(command, loan)
            if prepared.replay is not None:
                return prepared.replay
            if command.document_id is not None:
                documents = await self._documents_session_factory.session(access_token)
                if documents.actor_id != command.actor_id:
                    raise CorporateGovernanceError.forbidden()
                records = await documents.list_documents((command.company_id,))
                record = next(
                    (
                        item
                        for item in records
                        if str(item.document_id) == str(command.document_id)
                    ),
                    None,
                )
                if (
                    record is None
                    or record.company_id != command.company_id
                    or record.income_year != command.income_year
                    or record.status
                    in {DocumentStatus.QUARANTINED, DocumentStatus.REMOVED}
                ):
                    raise CorporateGovernanceError.precondition(
                        CorporateGovernanceErrorCode.INVALID_INPUT,
                        "Shareholder-loan document evidence does not match the company year.",
                    )
            ledger = self._ledger_facade_factory(transaction)
            directions = {
                "shareholder_to_company": LedgerShareholderLoanDirection.SHAREHOLDER_TO_COMPANY,
                "company_to_corporate_shareholder": LedgerShareholderLoanDirection.COMPANY_TO_CORPORATE_SHAREHOLDER,
            }
            posted = await ledger.post_shareholder_loan(
                PostShareholderLoanCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    action_id=LedgerSourceRecordId(str(command.action_id)),
                    counterparty_name=prepared.loan.counterparty_name,
                    direction=directions[prepared.loan.direction.value],
                    amount=_money_from_ore(prepared.loan.amount_ore),
                    ledger_entry_id=LedgerEntryId(str(command.ledger_entry_id)),
                )
            )
            if posted.entry_id != LedgerEntryId(str(command.ledger_entry_id)):
                raise CorporateGovernanceError.unavailable()
            if command.bank_transaction_id is not None:
                if (
                    prepared.bank_transaction_date is None
                    or prepared.bank_signed_amount is None
                    or prepared.bank_source_sha256 is None
                ):
                    raise CorporateGovernanceError.unavailable()
                await transaction.claim_transaction_for_external_action(
                    ClaimBankTransactionForExternalActionCommand(
                        company_id=command.company_id,
                        actor_id=command.actor_id,
                        correlation_id=command.correlation_id,
                        idempotency_key=command.idempotency_key,
                        income_year=command.income_year,
                        transaction_id=BankTransactionId(
                            str(command.bank_transaction_id)
                        ),
                        transaction_date=prepared.bank_transaction_date,
                        signed_amount=prepared.bank_signed_amount,
                        source_hash=prepared.bank_source_sha256,
                        action_reference=ExternalActionReference(
                            str(command.action_id)
                        ),
                    ),
                    accounting_entry_id=BankingAccountingEntryReference(
                        str(posted.entry_id)
                    ),
                )
            return await transaction.complete_shareholder_loan(
                command,
                AccountingEntryReference(str(posted.entry_id)),
                prepared,
            )


__all__ = ["CorporateGovernanceApplication", "LedgerFacadeFactory"]
