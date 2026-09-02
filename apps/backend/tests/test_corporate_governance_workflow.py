from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from talli_backend.application.corporate_governance_workflow import (
    CorporateGovernanceApplication,
)
from talli_backend.modules.corporate_governance.public import (
    AccountingEntryReference,
    BankTransactionReference,
    CorporateArtifactId,
    CorporateArtifactKind,
    CorporateDecisionId,
    CorporateDocumentSetId,
    CorporateEventId,
    CorporateFinalizationId,
    CorporateGovernanceError,
    DocumentReference,
    FinalizeOwnerDividendCommand,
    OwnerDividendArtifactReference,
    OwnerDividendLifecycle,
    OwnerDividendState,
    PreparedOwnerDividendFinalization,
    PreparedOwnerDividendPayment,
    RecordOwnerDividendPaymentCommand,
    RegisterOwnerDividendDocumentsCommand,
)
from talli_backend.modules.documents.public import DocumentId, DocumentStatus
from talli_backend.modules.ledger.public import (
    LedgerEntryId,
    LedgerEntryKind,
    PostedLedgerEntry,
)
from talli_backend.shared.kernel import (
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    Money,
    Timestamp,
)

from test_corporate_governance import supported_proposal


ENTRY_ID = LedgerEntryId("99999999-9999-4999-8999-999999999999")
NOW = Timestamp(datetime(2026, 9, 2, tzinfo=UTC))
DECISION_HASH = "c" * 64


def lifecycle(
    state: OwnerDividendState,
    *,
    replayed: bool = False,
    accounting_entry_id: AccountingEntryReference | None = None,
) -> OwnerDividendLifecycle:
    return OwnerDividendLifecycle(
        decision_id=CorporateDecisionId("11111111-1111-4111-8111-111111111111"),
        document_set_id=CorporateDocumentSetId("44444444-4444-4444-8444-444444444444"),
        company_id=supported_proposal().company_id,
        income_year=IncomeYear(2025),
        decision_hash=DECISION_HASH,
        state=state,
        declared_amount_ore=10_000_001,
        paid_amount_ore=0,
        remaining_amount_ore=10_000_001,
        finalization_id=(
            CorporateFinalizationId("55555555-5555-4555-8555-555555555555")
            if state in {OwnerDividendState.FINALIZED, OwnerDividendState.PARTIALLY_PAID, OwnerDividendState.PAID}
            else None
        ),
        accounting_entry_id=accounting_entry_id,
        replayed=replayed,
    )


class GovernanceTransactionStub:
    def __init__(self) -> None:
        self.actor_id = supported_proposal().actor_id
        self.calls: list[tuple[str, object]] = []
        self.role = "owner"
        self.complete_failure = False
        self.finalization_replay: OwnerDividendLifecycle | None = None
        self.payment_replay: OwnerDividendLifecycle | None = None

    async def actor_role(self, company_id):
        self.calls.append(("actor_role", company_id))
        return self.role

    async def propose_owner_dividend(self, command, decision):
        self.calls.append(("propose", decision))
        return SimpleNamespace(decision=decision, state=OwnerDividendState.PROPOSED, replayed=False)

    async def register_owner_dividend_documents(self, command):
        self.calls.append(("register_documents", command))
        return lifecycle(OwnerDividendState.DOCUMENTS_REGISTERED)

    async def approve_owner_dividend(self, command):
        self.calls.append(("approve", command))
        return lifecycle(OwnerDividendState.FACTS_APPROVED)

    async def prepare_owner_dividend_finalization(self, command):
        self.calls.append(("prepare_finalization", command))
        return PreparedOwnerDividendFinalization(
            declared_amount_ore=10_000_001,
            replay=self.finalization_replay,
        )

    async def complete_owner_dividend_finalization(self, command, accounting_entry_id, prepared):
        self.calls.append(("complete_finalization", accounting_entry_id))
        if self.complete_failure:
            raise CorporateGovernanceError.unavailable()
        return lifecycle(
            OwnerDividendState.FINALIZED,
            accounting_entry_id=accounting_entry_id,
        )

    async def prepare_owner_dividend_payment(self, command):
        self.calls.append(("prepare_payment", command))
        return PreparedOwnerDividendPayment(
            payment_amount_ore=75_000,
            bank_transaction_date=LocalDate(date(2025, 7, 2)),
            bank_signed_amount=Money.nok("-750.00"),
            bank_source_sha256="d" * 64,
            replay=self.payment_replay,
        )

    async def complete_owner_dividend_payment(self, command, accounting_entry_id, prepared):
        self.calls.append(("complete_payment", accounting_entry_id))
        if self.complete_failure:
            raise CorporateGovernanceError.unavailable()
        return lifecycle(
            OwnerDividendState.PARTIALLY_PAID,
            accounting_entry_id=accounting_entry_id,
        )

    async def post_entry(self, command, **kwargs):
        raise AssertionError("Injected ledger facade must own posting policy")

    async def claim_transaction_for_external_action(self, command, *, accounting_entry_id):
        self.calls.append(("claim_bank", (command, accounting_entry_id)))


class GovernanceSessionStub:
    def __init__(self, transaction: GovernanceTransactionStub) -> None:
        self.actor_id = transaction.actor_id
        self.transaction_stub = transaction
        self.rolled_back = False

    @asynccontextmanager
    async def transaction(self):
        try:
            yield self.transaction_stub
        except Exception:
            self.rolled_back = True
            raise


class GovernanceSessionFactoryStub:
    def __init__(self, session: GovernanceSessionStub) -> None:
        self.session_stub = session

    async def session(self, access_token: str):
        assert access_token == "access-token"
        return self.session_stub


class DocumentsSessionStub:
    def __init__(self) -> None:
        self.actor_id = supported_proposal().actor_id
        self.records = (
            SimpleNamespace(
                document_id=DocumentId("66666666-6666-4666-8666-666666666666"),
                company_id=supported_proposal().company_id,
                linked_to="corporate_decision:11111111-1111-4111-8111-111111111111",
                status=DocumentStatus.GENERATED_UNSIGNED,
                content_sha256="a" * 64,
                byte_length=101,
            ),
            SimpleNamespace(
                document_id=DocumentId("77777777-7777-4777-8777-777777777777"),
                company_id=supported_proposal().company_id,
                linked_to="corporate_decision:11111111-1111-4111-8111-111111111111",
                status=DocumentStatus.GENERATED_UNSIGNED,
                content_sha256="b" * 64,
                byte_length=202,
            ),
        )

    async def list_documents(self, company_ids):
        assert company_ids == (supported_proposal().company_id,)
        return self.records


class DocumentsSessionFactoryStub:
    def __init__(self, session: DocumentsSessionStub) -> None:
        self.session_stub = session

    async def session(self, access_token: str):
        assert access_token == "access-token"
        return self.session_stub


class LedgerFacadeStub:
    def __init__(self, transaction: GovernanceTransactionStub) -> None:
        self.transaction = transaction
        self.commands: list[object] = []

    async def post_owner_dividend_declared(self, command):
        self.commands.append(command)
        return PostedLedgerEntry(
            ENTRY_ID,
            command.company_id,
            command.income_year,
            LedgerEntryKind.OWNER_DIVIDEND_DECLARED,
            NOW,
            False,
        )

    async def post_owner_dividend_payment(self, command):
        self.commands.append(command)
        return PostedLedgerEntry(
            ENTRY_ID,
            command.company_id,
            command.income_year,
            LedgerEntryKind.OWNER_DIVIDEND_PAYMENT,
            NOW,
            False,
        )


def application():
    transaction = GovernanceTransactionStub()
    session = GovernanceSessionStub(transaction)
    documents = DocumentsSessionStub()
    ledgers: list[LedgerFacadeStub] = []

    def ledger_factory(active_transaction):
        assert active_transaction is transaction
        ledger = LedgerFacadeStub(transaction)
        ledgers.append(ledger)
        return ledger

    app = CorporateGovernanceApplication(
        GovernanceSessionFactoryStub(session),
        DocumentsSessionFactoryStub(documents),
        ledger_factory,
    )
    return app, transaction, session, documents, ledgers


def test_proposal_is_owner_authorized_and_persists_python_canonical_facts() -> None:
    app, transaction, _, _, _ = application()
    result = asyncio.run(app.propose_owner_dividend("access-token", supported_proposal()))
    assert result.decision.decision_hash
    assert transaction.calls[0][0] == "actor_role"
    assert transaction.calls[1][0] == "propose"

    transaction.role = "reviewer"
    with pytest.raises(CorporateGovernanceError):
        asyncio.run(app.propose_owner_dividend("access-token", supported_proposal()))


def document_command() -> RegisterOwnerDividendDocumentsCommand:
    proposal = supported_proposal()
    return RegisterOwnerDividendDocumentsCommand(
        company_id=proposal.company_id,
        actor_id=proposal.actor_id,
        correlation_id=CorrelationId("owner-dividend-documents"),
        idempotency_key=IdempotencyKey("owner-dividend-documents-0001"),
        decision_id=proposal.decision_id,
        document_set_id=proposal.document_set_id,
        decision_hash=DECISION_HASH,
        artifacts=(
            OwnerDividendArtifactReference(
                CorporateArtifactId("88888888-8888-4888-8888-888888888881"),
                DocumentReference("66666666-6666-4666-8666-666666666666"),
                CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL,
                "a" * 64,
                101,
            ),
            OwnerDividendArtifactReference(
                CorporateArtifactId("88888888-8888-4888-8888-888888888882"),
                DocumentReference("77777777-7777-4777-8777-777777777777"),
                CorporateArtifactKind.DIVIDEND_GENERAL_MEETING_MINUTES,
                "b" * 64,
                202,
            ),
        ),
    )


def test_document_registration_uses_only_documents_public_records() -> None:
    app, transaction, _, documents, _ = application()
    result = asyncio.run(
        app.register_owner_dividend_documents("access-token", document_command())
    )
    assert result.state is OwnerDividendState.DOCUMENTS_REGISTERED
    assert transaction.calls[-1][0] == "register_documents"

    documents.records[0].content_sha256 = "f" * 64
    with pytest.raises(CorporateGovernanceError):
        asyncio.run(
            app.register_owner_dividend_documents("access-token", document_command())
        )


def finalization_command() -> FinalizeOwnerDividendCommand:
    proposal = supported_proposal()
    return FinalizeOwnerDividendCommand(
        company_id=proposal.company_id,
        actor_id=proposal.actor_id,
        correlation_id=CorrelationId("owner-dividend-finalization"),
        idempotency_key=IdempotencyKey("owner-dividend-finalization-0001"),
        income_year=proposal.income_year,
        decision_id=proposal.decision_id,
        document_set_id=proposal.document_set_id,
        decision_hash=DECISION_HASH,
        finalization_id=CorporateFinalizationId("55555555-5555-4555-8555-555555555555"),
        holding_action_id=CorporateEventId("aaaaaaaa-1111-4111-8111-111111111111"),
        ledger_entry_id=AccountingEntryReference(str(ENTRY_ID)),
    )


def test_finalization_posts_characterized_declaration_once_and_replays() -> None:
    app, transaction, _, _, ledgers = application()
    result = asyncio.run(
        app.finalize_owner_dividend("access-token", finalization_command())
    )
    assert result.state is OwnerDividendState.FINALIZED
    ledger_command = ledgers[0].commands[0]
    assert ledger_command.declared_amount == Money.nok("100000.01")
    assert ledger_command.declaration_debit_account == "2050"
    assert ledger_command.dividend_payable_account == "2920"
    assert ledger_command.accounting_policy_version == "no-holding-v1"

    transaction.finalization_replay = lifecycle(
        OwnerDividendState.FINALIZED,
        replayed=True,
        accounting_entry_id=AccountingEntryReference(str(ENTRY_ID)),
    )
    replay = asyncio.run(
        app.finalize_owner_dividend("access-token", finalization_command())
    )
    assert replay.replayed is True
    assert len(ledgers) == 1


def payment_command() -> RecordOwnerDividendPaymentCommand:
    proposal = supported_proposal()
    return RecordOwnerDividendPaymentCommand(
        company_id=proposal.company_id,
        actor_id=proposal.actor_id,
        correlation_id=CorrelationId("owner-dividend-payment"),
        idempotency_key=IdempotencyKey("owner-dividend-payment-0001"),
        income_year=proposal.income_year,
        decision_id=proposal.decision_id,
        document_set_id=proposal.document_set_id,
        decision_hash=DECISION_HASH,
        payment_event_id=CorporateEventId("bbbbbbbb-1111-4111-8111-111111111111"),
        holding_action_id=CorporateEventId("cccccccc-1111-4111-8111-111111111111"),
        ledger_entry_id=AccountingEntryReference(str(ENTRY_ID)),
        bank_transaction_id=BankTransactionReference("dddddddd-1111-4111-8111-111111111111"),
    )


def test_payment_posts_then_claims_bank_then_completes_in_one_transaction() -> None:
    app, transaction, _, _, ledgers = application()
    result = asyncio.run(
        app.record_owner_dividend_payment("access-token", payment_command())
    )
    assert result.state is OwnerDividendState.PARTIALLY_PAID
    ledger_command = ledgers[0].commands[0]
    assert ledger_command.payment_amount == Money.nok("750.00")
    assert ledger_command.dividend_payable_account == "2920"
    assert ledger_command.bank_account == "1920"
    assert [name for name, _ in transaction.calls[-3:]] == [
        "prepare_payment",
        "claim_bank",
        "complete_payment",
    ]
    bank_command, accounting_reference = transaction.calls[-2][1]
    assert str(bank_command.transaction_id) == str(payment_command().bank_transaction_id)
    assert bank_command.signed_amount == Money.nok("-750.00")
    assert str(accounting_reference) == str(ENTRY_ID)


def test_posted_ledger_effect_rolls_back_when_governance_completion_fails() -> None:
    app, transaction, session, _, ledgers = application()
    transaction.complete_failure = True
    with pytest.raises(CorporateGovernanceError):
        asyncio.run(
            app.finalize_owner_dividend("access-token", finalization_command())
        )
    assert len(ledgers[0].commands) == 1
    assert session.rolled_back is True
