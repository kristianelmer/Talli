from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from talli_backend.application.corporate_governance_workflow import (
    CorporateGovernanceApplication,
)
from talli_backend.modules.corporate_governance.public import (
    AccountingEntryReference,
    AttestAnnualCloseSignedArtifactCommand,
    BankTransactionReference,
    CorporateArtifactId,
    CorporateArtifactKind,
    CorporateDecisionKind,
    CorporateDecisionId,
    CorporateDecisionRecord,
    CorporateDocumentSetId,
    CorporateDocumentSetRecord,
    CorporateEventId,
    CorporateEventRecord,
    CorporateFinalizationId,
    CorporateGovernanceError,
    CorporateGovernanceErrorCode,
    CorporateLifecycleSnapshot,
    DocumentReference,
    FinalizeAnnualCloseCommand,
    FinalizeOwnerDividendCommand,
    OwnerDividendArtifactReference,
    OwnerDividendLifecycle,
    OwnerDividendState,
    PersistedCompanyFacts,
    PreparedOwnerDividendFinalization,
    PreparedOwnerDividendPayment,
    PreparedShareholderLoan,
    PreparedSupportedCorporateEvent,
    RecordedShareholderLoan,
    RecordedSupportedCorporateEvent,
    RecordOwnerDividendPaymentCommand,
    RegisterOwnerDividendDocumentsCommand,
)
from talli_backend.modules.corporate_governance.service import (
    CorporateGovernanceService,
    canonical_annual_close_payload,
    canonical_owner_dividend_payload,
)
from talli_backend.modules.documents.public import DocumentId, DocumentStatus
from talli_backend.modules.ledger.public import (
    LedgerEntryId,
    LedgerEntryKind,
    PostedLedgerEntry,
    ReversedLedgerEntry,
    ShareholderLoanDirection as LedgerShareholderLoanDirection,
)
from talli_backend.shared.kernel import (
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    Money,
    Timestamp,
)

from test_corporate_governance import (
    supported_annual_close,
    supported_fact_sources,
    supported_ledger_lines,
    supported_proposal,
    supported_shareholder_loan,
)


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
            if state in {
                OwnerDividendState.FINALIZED,
                OwnerDividendState.PARTIALLY_PAID,
                OwnerDividendState.PAID,
            }
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
        self.shareholder_loan_replay: RecordedShareholderLoan | None = None
        self.supported_events: tuple[RecordedSupportedCorporateEvent, ...] = ()
        self.shareholder_loan_bank = False
        self.source_facts_changed = False
        self.source_facts_unavailable = False
        self.shareholder_order_changed = False
        self.list_snapshot = CorporateLifecycleSnapshot((), (), (), (), ())

    def source_facts(self, annual_year: int):
        if self.source_facts_unavailable:
            raise CorporateGovernanceError.unavailable()
        sources = supported_fact_sources(annual_year)
        if not self.source_facts_changed:
            return sources
        annual_data = sources.annual_data[0]
        return replace(
            sources,
            annual_data=(
                replace(
                    annual_data,
                    answers={**annual_data.answers, "facts_changed_after_approval": True},
                ),
            ),
        )

    async def read_company_facts(self, company_id):
        self.calls.append(("read_company_facts", company_id))
        return self.source_facts(2025).company

    async def list_opening_snapshots(self, **kwargs):
        self.calls.append(("list_opening_snapshots", kwargs))
        sources = self.source_facts(2025)
        shareholders = sorted(sources.shareholders, key=lambda value: value.order)
        if self.shareholder_order_changed:
            shareholders.reverse()
        return SimpleNamespace(
            items=(
                SimpleNamespace(
                    company_id=sources.company.company_id,
                    income_year=IncomeYear(2025),
                    shareholders=tuple(
                        SimpleNamespace(
                            shareholder_id=item.shareholder_id,
                            name=item.name,
                            share_count=item.share_count,
                        )
                        for item in shareholders
                    ),
                ),
            ),
            has_more=False,
            next_cursor=None,
        )

    async def list_annual_data_compatibility(self, **kwargs):
        self.calls.append(("list_annual_data_compatibility", kwargs))
        return tuple(
            SimpleNamespace(
                source_id=str(item.source_id),
                company_id=item.company_id,
                income_year=item.income_year,
                answers=item.answers,
                confirmations=item.confirmations,
                no_activity_confirmed=item.no_activity_confirmed,
                annual_full_time_equivalents=item.annual_full_time_equivalents,
                completed_at=item.completed_at,
                updated_at=item.updated_at,
            )
            for year in (2025, 2024)
            for item in self.source_facts(year).annual_data
            if int(item.income_year) <= int(kwargs["income_year"])
        )

    async def list_entries(self, **kwargs):
        return SimpleNamespace(
            items=tuple(
                SimpleNamespace(
                    income_year=IncomeYear(year),
                    lines=tuple(
                        SimpleNamespace(
                            account=line.account,
                            debit=Money.nok(Decimal(line.debit_ore) / Decimal(100)),
                            credit=Money.nok(Decimal(line.credit_ore) / Decimal(100)),
                        )
                        for line in supported_ledger_lines(year)
                    ),
                )
                for year in (2024, 2025)
            ),
            page=SimpleNamespace(has_more=False, next_cursor=None),
        )

    async def list_lifecycle(self, company_ids):
        self.calls.append(("list_lifecycle", company_ids))
        return self.list_snapshot

    async def list_supported_events(self, company_ids):
        self.calls.append(("list_supported_events", company_ids))
        return self.supported_events

    async def read_lifecycle(self, decision_id):
        self.calls.append(("read_lifecycle", decision_id))
        service = CorporateGovernanceService()
        if decision_id == supported_annual_close().decision_id:
            decision = service.build_annual_close_decision(supported_annual_close())
            decision_kind = CorporateDecisionKind.ANNUAL_CLOSE
        else:
            decision = service.build_owner_dividend_decision(supported_proposal())
            decision_kind = CorporateDecisionKind.OWNER_DIVIDEND
        return CorporateLifecycleSnapshot(
            decisions=(CorporateDecisionRecord(
                decision_id=decision.decision_id,
                document_set_id=decision.document_set_id,
                company_id=decision.company_id,
                income_year=decision.income_year,
                decision_kind=decision_kind,
                annual_close_source_id=decision.annual_close_source_id,
                source_hash=decision.source_hash,
                canonical_input=(
                    canonical_annual_close_payload(decision)
                    if decision_kind is CorporateDecisionKind.ANNUAL_CLOSE
                    else canonical_owner_dividend_payload(decision)
                ),
                decision_hash=decision.decision_hash,
                supersedes_decision_id=None,
                created_by=str(decision.company_id),
                created_at=NOW.value,
            ),),
            document_sets=(CorporateDocumentSetRecord(
                document_set_id=decision.document_set_id,
                company_id=decision.company_id,
                income_year=decision.income_year,
                decision_id=decision.decision_id,
                template_family=decision.template_family,
                template_version=decision.template_version,
                decision_hash=decision.decision_hash,
                supersedes_document_set_id=None,
                created_by=str(decision.company_id),
                created_at=NOW.value,
            ),),
            artifacts=(),
            events=(),
            finalizations=(),
        )

    async def actor_role(self, company_id):
        self.calls.append(("actor_role", company_id))
        return self.role

    async def propose_owner_dividend(self, command, decision, canonical_input):
        self.calls.append(("propose", decision))
        assert canonical_input["request_id"] == str(decision.decision_id)
        return SimpleNamespace(decision=decision, state=OwnerDividendState.PROPOSED, replayed=False)

    async def propose_annual_close(self, command, decision, canonical_input, artifacts):
        self.calls.append(("propose_annual_close", decision))
        assert canonical_input["request_id"] == str(decision.decision_id)
        assert len(artifacts) == 2
        return SimpleNamespace(
            decision=decision,
            state=OwnerDividendState.PROPOSED,
            replayed=False,
        )

    async def register_owner_dividend_documents(self, command):
        self.calls.append(("register_documents", command))
        return lifecycle(OwnerDividendState.DOCUMENTS_REGISTERED)

    async def register_annual_close_documents(self, command):
        self.calls.append(("register_annual_close_documents", command))
        return SimpleNamespace(
            decision_id=command.decision_id,
            document_set_id=command.document_set_id,
            company_id=command.company_id,
            income_year=IncomeYear(2025),
            decision_hash=command.decision_hash,
            state=OwnerDividendState.DOCUMENTS_REGISTERED,
            generated_artifact_hashes={
                artifact.artifact_kind.value: artifact.content_sha256
                for artifact in command.artifacts
            },
            signed_artifact_hashes={},
            finalization_id=None,
            replayed=False,
        )

    async def approve_owner_dividend(self, command):
        self.calls.append(("approve", command))
        return lifecycle(OwnerDividendState.FACTS_APPROVED)

    async def approve_annual_close(self, command):
        self.calls.append(("approve_annual_close", command))
        return self.annual_lifecycle(command, OwnerDividendState.FACTS_APPROVED)

    async def record_annual_close_event(self, command):
        self.calls.append(("record_annual_close_event", command))
        return self.annual_lifecycle(command, OwnerDividendState(command.event_kind.value))

    async def finalize_annual_close(self, command):
        self.calls.append(("finalize_annual_close", command))
        return self.annual_lifecycle(command, OwnerDividendState.FINALIZED)

    async def attest_annual_close_signed_artifact(self, command):
        self.calls.append(("attest_annual_close_signed_artifact", command))
        return self.annual_lifecycle(command, OwnerDividendState.SIGNED_OWNER_ATTESTED)

    @staticmethod
    def annual_lifecycle(command, state):
        return SimpleNamespace(
            decision_id=command.decision_id,
            document_set_id=command.document_set_id,
            company_id=command.company_id,
            income_year=IncomeYear(2025),
            decision_hash=command.decision_hash,
            state=state,
            generated_artifact_hashes={},
            signed_artifact_hashes={},
            finalization_id=(
                command.finalization_id
                if state is OwnerDividendState.FINALIZED
                else None
            ),
            replayed=False,
        )

    async def prepare_owner_dividend_finalization(self, command):
        self.calls.append(("prepare_finalization", command))
        return PreparedOwnerDividendFinalization(
            declared_amount_ore=10_000_001,
            accounting_policy_version="approved-policy-v1",
            declaration_debit_account="2050",
            dividend_payable_account="2920",
            signed_artifact_hashes={
                "dividend_board_proposal": "a" * 64,
                "dividend_general_meeting_minutes": "b" * 64,
            },
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
            accounting_policy_version="approved-policy-v1",
            dividend_payable_account="2920",
            bank_account="1920",
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

    async def prepare_shareholder_loan(self, command, loan):
        self.calls.append(("prepare_shareholder_loan", loan))
        return PreparedShareholderLoan(
            loan=loan,
            bank_transaction_date=(
                LocalDate(date(2025, 3, 1)) if self.shareholder_loan_bank else None
            ),
            bank_signed_amount=(
                Money.nok("1250.50") if self.shareholder_loan_bank else None
            ),
            bank_source_sha256="e" * 64 if self.shareholder_loan_bank else None,
            replay=self.shareholder_loan_replay,
        )

    async def complete_shareholder_loan(self, command, accounting_entry_id, prepared):
        self.calls.append(("complete_shareholder_loan", accounting_entry_id))
        if self.complete_failure:
            raise CorporateGovernanceError.unavailable()
        return RecordedShareholderLoan(
            loan=prepared.loan,
            accounting_entry_id=accounting_entry_id,
            replayed=False,
        )

    async def prepare_supported_event(self, command, event):
        self.calls.append(("prepare_supported_event", event))
        return PreparedSupportedCorporateEvent(event=event, replay=None)

    async def complete_supported_event(self, command, accounting_entry_id, prepared):
        self.calls.append(("complete_supported_event", accounting_entry_id))
        result = RecordedSupportedCorporateEvent(
            event=prepared.event,
            accounting_entry_id=accounting_entry_id,
            bank_transaction_id=(
                command.bank_fact.transaction_id if command.bank_fact else None
            ),
            correction_of_event_id=None,
            recorded_at=NOW.value,
            replayed=False,
        )
        self.supported_events = (*self.supported_events, result)
        return result

    async def post_entry(self, command, **kwargs):
        raise AssertionError("Injected ledger facade must own posting policy")

    async def claim_transaction_for_external_action(self, command, *, accounting_entry_id):
        self.calls.append(("claim_bank", (command, accounting_entry_id)))


class GovernanceSessionStub:
    def __init__(self, transaction: GovernanceTransactionStub) -> None:
        self.actor_id = transaction.actor_id
        self.transaction_stub = transaction
        self.rolled_back = False
        self.commit_failures = 0

    @asynccontextmanager
    async def transaction(self, *, guarded_company_id=None):
        try:
            yield self.transaction_stub
            if self.commit_failures:
                self.commit_failures -= 1
                raise CorporateGovernanceError.unavailable()
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
                income_year=IncomeYear(2025),
            ),
            SimpleNamespace(
                document_id=DocumentId("77777777-7777-4777-8777-777777777777"),
                company_id=supported_proposal().company_id,
                linked_to="corporate_decision:11111111-1111-4111-8111-111111111111",
                status=DocumentStatus.GENERATED_UNSIGNED,
                content_sha256="b" * 64,
                byte_length=202,
                income_year=IncomeYear(2025),
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

    async def list_entries(self, **kwargs):
        return await self.transaction.list_entries(**kwargs)

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

    async def post_shareholder_loan(self, command):
        self.commands.append(command)
        return PostedLedgerEntry(
            command.ledger_entry_id,
            command.company_id,
            command.income_year,
            LedgerEntryKind.SHAREHOLDER_LOAN,
            NOW,
            False,
        )

    async def recognize_holding_action(self, command):
        self.commands.append(command)
        return PostedLedgerEntry(
            ENTRY_ID,
            command.company_id,
            command.income_year,
            LedgerEntryKind.CAPITAL_INCREASE,
            NOW,
            False,
        )

    async def reverse_supported_holding_action(self, command):
        self.commands.append(command)
        return ReversedLedgerEntry(
            original_entry_id=command.original_entry_id,
            reversal_entry_id=LedgerEntryId(
                "98989898-9898-4898-8989-989898989898"
            ),
            company_id=command.company_id,
            income_year=command.income_year,
            reversed_at=NOW,
            replayed=False,
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


def test_decision_facts_read_company_identity_in_governance_transaction() -> None:
    app, transaction, _, _, _ = application()

    facts = asyncio.run(
        app.derive_decision_facts(
            "access-token",
            company_id=supported_proposal().company_id,
            income_year=supported_proposal().income_year,
            decision_kind=CorporateDecisionKind.OWNER_DIVIDEND,
            correlation_id=supported_proposal().correlation_id,
        )
    )

    assert facts.company == supported_fact_sources(2025).company
    assert ("read_company_facts", supported_proposal().company_id) in transaction.calls


def test_proposal_is_owner_authorized_and_persists_python_canonical_facts() -> None:
    app, transaction, _, _, _ = application()
    result = asyncio.run(app.propose_owner_dividend("access-token", supported_proposal()))
    assert result.decision.decision_hash
    assert transaction.calls[0][0] == "actor_role"
    assert transaction.calls[-1][0] == "propose"

    transaction.role = "reviewer"
    with pytest.raises(CorporateGovernanceError):
        asyncio.run(app.propose_owner_dividend("access-token", supported_proposal()))


def test_proposal_ignores_claimed_source_facts_and_rederives_them() -> None:
    app, _, _, _, _ = application()
    command = supported_proposal()
    claimed = replace(
        command,
        company=PersistedCompanyFacts(
            command.company_id,
            "999999999",
            "CLAIMED COMPANY",
        ),
        annual_basis=replace(
            command.annual_basis,
            available_distribution_ore=999_999_999,
            cash_ore=999_999_999,
        ),
    )

    result = asyncio.run(app.propose_owner_dividend("access-token", claimed))

    assert result.decision.organization_number == "310279617"
    assert result.decision.legal_name == "LOGISK ØDE TIGER AS"
    assert result.decision.financial_totals.available_distribution_ore == 30_000_000


def test_annual_close_proposal_is_owner_authorized_and_persists_canonical_facts() -> None:
    app, transaction, _, _, _ = application()
    result = asyncio.run(app.propose_annual_close("access-token", supported_annual_close()))
    assert result.decision.decision_hash == (
        "22d6b2d7ddb555022813b56ebd554bdfef6a78ac5b0dd6654a3f2d208c3111d6"
    )
    assert result.decision.dividend is None
    assert transaction.calls[0][0] == "actor_role"
    assert transaction.calls[-1][0] == "propose_annual_close"

    transaction.role = "reviewer"
    with pytest.raises(CorporateGovernanceError):
        asyncio.run(app.propose_annual_close("access-token", supported_annual_close()))


def test_readiness_derives_current_source_server_side_and_marks_stale_evidence() -> None:
    app, transaction, _, _, _ = application()
    transaction.list_snapshot = asyncio.run(
        transaction.read_lifecycle(supported_proposal().decision_id)
    )
    transaction.calls.clear()

    current = asyncio.run(
        app.read_readiness(
            "access-token",
            company_id=supported_proposal().company_id,
            income_year=IncomeYear(2025),
            decision_kind=CorporateDecisionKind.OWNER_DIVIDEND,
            correlation_id=CorrelationId("read-current-governance-source"),
        )
    )
    assert current.current_source_matches is True

    transaction.source_facts_changed = True
    stale = asyncio.run(
        app.read_readiness(
            "access-token",
            company_id=supported_proposal().company_id,
            income_year=IncomeYear(2025),
            decision_kind=CorporateDecisionKind.OWNER_DIVIDEND,
            correlation_id=CorrelationId("read-stale-governance-source"),
        )
    )

    assert stale.current_source_matches is False
    assert "corporate_documents_current_hash_mismatch" in {
        blocker.code for blocker in stale.blockers
    }

    transaction.source_facts_changed = False
    transaction.shareholder_order_changed = True
    reordered = asyncio.run(
        app.read_readiness(
            "access-token",
            company_id=supported_proposal().company_id,
            income_year=IncomeYear(2025),
            decision_kind=CorporateDecisionKind.OWNER_DIVIDEND,
            correlation_id=CorrelationId("read-reordered-governance-source"),
        )
    )
    assert reordered.current_source_matches is False
    assert reordered.current_source_hash == transaction.list_snapshot.decisions[0].source_hash
    assert reordered.current_source_hash != "0" * 64


def test_readiness_returns_missing_decision_without_reading_mutable_sources() -> None:
    app, transaction, _, _, _ = application()

    readiness = asyncio.run(
        app.read_readiness(
            "access-token",
            company_id=supported_proposal().company_id,
            income_year=IncomeYear(2025),
            decision_kind=CorporateDecisionKind.OWNER_DIVIDEND,
            correlation_id=CorrelationId("read-missing-governance-decision"),
        )
    )

    assert [blocker.code for blocker in readiness.blockers] == [
        "corporate_documents_decision_missing"
    ]
    assert [name for name, _ in transaction.calls] == [
        "actor_role",
        "list_lifecycle",
    ]


def test_readiness_preserves_terminal_state_when_current_sources_are_unavailable() -> None:
    app, transaction, _, _, _ = application()
    snapshot = asyncio.run(
        transaction.read_lifecycle(supported_proposal().decision_id)
    )
    decision = snapshot.decisions[0]
    transaction.list_snapshot = replace(
        snapshot,
        events=(
            CorporateEventRecord(
                event_id=CorporateEventId(
                    "23232323-2323-4232-8232-232323232323"
                ),
                company_id=decision.company_id,
                income_year=decision.income_year,
                decision_id=decision.decision_id,
                document_set_id=decision.document_set_id,
                artifact_id=None,
                event_kind="superseded",
                actor_id=str(decision.company_id),
                occurred_at=NOW.value,
                created_at=NOW.value,
                decision_hash=decision.decision_hash,
                content_sha256=None,
                metadata={},
                idempotency_key="terminal-readiness",
            ),
        ),
    )
    transaction.calls.clear()
    transaction.source_facts_unavailable = True

    readiness = asyncio.run(
        app.read_readiness(
            "access-token",
            company_id=decision.company_id,
            income_year=decision.income_year,
            decision_kind=CorporateDecisionKind.OWNER_DIVIDEND,
            correlation_id=CorrelationId("read-terminal-governance-decision"),
        )
    )

    assert readiness.state is OwnerDividendState.SUPERSEDED
    assert "corporate_documents_terminal_decision" in {
        blocker.code for blocker in readiness.blockers
    }
    assert [name for name, _ in transaction.calls] == [
        "actor_role",
        "list_lifecycle",
    ]


def test_annual_close_signed_artifact_uses_documents_evidence_and_governance_store() -> None:
    app, transaction, _, documents, _ = application()
    command = AttestAnnualCloseSignedArtifactCommand(
        company_id=supported_annual_close().company_id,
        actor_id=supported_annual_close().actor_id,
        correlation_id=CorrelationId("annual-close-board-signed"),
        idempotency_key=IdempotencyKey("annual-close-board-signed-0001"),
        decision_id=supported_annual_close().decision_id,
        document_set_id=supported_annual_close().document_set_id,
        decision_hash=DECISION_HASH,
        unsigned_artifact_id=CorporateArtifactId(
            "88888888-8888-4888-8888-888888888881"
        ),
        signed_artifact_id=CorporateArtifactId(
            "88888888-8888-4888-8888-888888888891"
        ),
        signed_document_id=DocumentReference(
            "99999999-9999-4999-8999-999999999991"
        ),
        artifact_kind=CorporateArtifactKind.ANNUAL_BOARD_MINUTES,
        filename="signert-styreprotokoll.pdf",
        content_sha256="e" * 64,
        byte_length=303,
        signers=("Ola Nordmann",),
    )
    documents.records += (
        SimpleNamespace(
            document_id=DocumentId(str(command.signed_document_id)),
            company_id=command.company_id,
            linked_to=f"corporate_decision:{command.decision_id}",
            status=DocumentStatus.SIGNED_OWNER_ATTESTED,
            content_sha256=command.content_sha256,
            byte_length=command.byte_length,
            income_year=IncomeYear(2025),
        ),
    )

    result = asyncio.run(
        app.attest_annual_close_signed_artifact("access-token", command)
    )

    assert result.state is OwnerDividendState.SIGNED_OWNER_ATTESTED
    assert [call[0] for call in transaction.calls] == [
        "actor_role",
        "read_lifecycle",
        "attest_annual_close_signed_artifact",
    ]
    assert transaction.calls[-1][1].signers == ("Jørgen Østby", "Åse Nordmann")

    documents.records = documents.records[:-1]
    with pytest.raises(CorporateGovernanceError):
        asyncio.run(
            app.attest_annual_close_signed_artifact("access-token", command)
        )


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


def test_shareholder_loan_uses_governance_policy_and_narrow_ledger_contract() -> None:
    app, transaction, _, _, ledgers = application()
    result = asyncio.run(
        app.record_shareholder_loan("access-token", supported_shareholder_loan())
    )

    assert result.loan.counterparty_name == "Eier Holding AS"
    assert result.accounting_entry_id == supported_shareholder_loan().ledger_entry_id
    assert [call[0] for call in transaction.calls] == [
        "actor_role",
        "prepare_shareholder_loan",
        "complete_shareholder_loan",
    ]
    posted = ledgers[0].commands[0]
    assert posted.direction is LedgerShareholderLoanDirection.SHAREHOLDER_TO_COMPANY
    assert posted.amount == Money.nok("1250.50")
    assert posted.ledger_entry_id == LedgerEntryId(
        str(supported_shareholder_loan().ledger_entry_id)
    )


def test_shareholder_loan_verifies_document_and_claims_optional_bank_atomically() -> None:
    app, transaction, session, _, ledgers = application()
    transaction.shareholder_loan_bank = True
    command = replace(
        supported_shareholder_loan(),
        document_id=DocumentReference("66666666-6666-4666-8666-666666666666"),
        bank_transaction_id=BankTransactionReference(
            "abababab-abab-4bab-8bab-abababababab"
        ),
    )
    result = asyncio.run(app.record_shareholder_loan("access-token", command))

    assert result.replayed is False
    assert [call[0] for call in transaction.calls][-2:] == [
        "claim_bank",
        "complete_shareholder_loan",
    ]
    claim = [call for call in transaction.calls if call[0] == "claim_bank"][0][1][0]
    assert claim.signed_amount == Money.nok("1250.50")

    transaction.complete_failure = True
    with pytest.raises(CorporateGovernanceError):
        asyncio.run(app.record_shareholder_loan("access-token", command))
    assert session.rolled_back is True


def test_committed_shareholder_loan_replay_precedes_mutable_document_check() -> None:
    app, transaction, _, documents, ledgers = application()
    command = replace(
        supported_shareholder_loan(),
        document_id=DocumentReference("66666666-6666-4666-8666-666666666666"),
    )
    committed = asyncio.run(app.record_shareholder_loan("access-token", command))
    transaction.shareholder_loan_replay = replace(committed, replayed=True)
    documents.records = ()

    replay = asyncio.run(app.record_shareholder_loan("access-token", command))

    assert replay.replayed is True
    assert len(ledgers) == 1
    assert [call[0] for call in transaction.calls][-2:] == [
        "actor_role",
        "prepare_shareholder_loan",
    ]


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


def annual_finalization_command() -> FinalizeAnnualCloseCommand:
    proposal = supported_annual_close()
    decision = CorporateGovernanceService().build_annual_close_decision(proposal)
    return FinalizeAnnualCloseCommand(
        company_id=proposal.company_id,
        actor_id=proposal.actor_id,
        correlation_id=CorrelationId("annual-close-finalization"),
        idempotency_key=IdempotencyKey("annual-close-finalization-0001"),
        decision_id=proposal.decision_id,
        document_set_id=proposal.document_set_id,
        decision_hash=decision.decision_hash,
        finalization_id=CorporateFinalizationId(
            "abababab-abab-4bab-8bab-abababababab"
        ),
    )


def test_finalization_posts_characterized_declaration_once_and_replays() -> None:
    app, transaction, _, _, ledgers = application()
    result = asyncio.run(
        app.finalize_owner_dividend("access-token", finalization_command())
    )
    assert result.state is OwnerDividendState.FINALIZED
    ledger_command = next(ledger.commands[0] for ledger in ledgers if ledger.commands)
    assert ledger_command.declared_amount == Money.nok("100000.01")
    assert ledger_command.declaration_debit_account == "2050"
    assert ledger_command.dividend_payable_account == "2920"
    assert ledger_command.accounting_policy_version == "approved-policy-v1"

    transaction.finalization_replay = lifecycle(
        OwnerDividendState.FINALIZED,
        replayed=True,
        accounting_entry_id=AccountingEntryReference(str(ENTRY_ID)),
    )
    replay = asyncio.run(
        app.finalize_owner_dividend("access-token", finalization_command())
    )
    assert replay.replayed is True
    assert sum(len(ledger.commands) for ledger in ledgers) == 1


def test_finalization_blocks_changed_source_before_any_writer_runs() -> None:
    app, transaction, session, _, ledgers = application()
    transaction.source_facts_changed = True

    with pytest.raises(CorporateGovernanceError) as owner_error:
        asyncio.run(
            app.finalize_owner_dividend("access-token", finalization_command())
        )
    assert owner_error.value.code is CorporateGovernanceErrorCode.REVIEWED_FACTS_CHANGED
    assert [name for name, _ in transaction.calls] == [
        "actor_role",
        "prepare_finalization",
        "read_lifecycle",
        "read_company_facts",
        "list_opening_snapshots",
        "list_annual_data_compatibility",
    ]
    assert all(not ledger.commands for ledger in ledgers)
    assert session.rolled_back is True

    transaction.calls.clear()
    session.rolled_back = False
    with pytest.raises(CorporateGovernanceError) as annual_error:
        asyncio.run(
            app.finalize_annual_close("access-token", annual_finalization_command())
        )
    assert annual_error.value.code is CorporateGovernanceErrorCode.REVIEWED_FACTS_CHANGED
    assert [name for name, _ in transaction.calls] == [
        "actor_role",
        "read_lifecycle",
        "read_company_facts",
        "list_opening_snapshots",
        "list_annual_data_compatibility",
    ]
    assert "finalize_annual_close" not in {name for name, _ in transaction.calls}
    assert session.rolled_back is True


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
    assert ledger_command.accounting_policy_version == "approved-policy-v1"
    assert [name for name, _ in transaction.calls[-3:]] == [
        "prepare_payment",
        "claim_bank",
        "complete_payment",
    ]
    bank_command, accounting_reference = transaction.calls[-2][1]
    assert str(bank_command.transaction_id) == str(payment_command().bank_transaction_id)
    assert str(bank_command.action_reference) == str(payment_command().holding_action_id)
    assert bank_command.signed_amount == Money.nok("-750.00")
    assert str(accounting_reference) == str(ENTRY_ID)


def test_posted_ledger_effect_rolls_back_when_governance_completion_fails() -> None:
    app, transaction, session, _, ledgers = application()
    transaction.complete_failure = True
    with pytest.raises(CorporateGovernanceError):
        asyncio.run(
            app.finalize_owner_dividend("access-token", finalization_command())
        )
    assert sum(len(ledger.commands) for ledger in ledgers) == 1
    assert session.rolled_back is True
