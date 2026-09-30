from __future__ import annotations

import asyncio
import inspect
import json
from datetime import UTC, date, datetime

from talli_backend.adapters.supabase_corporate_governance import (
    SupabaseCorporateGovernanceSession,
    SupabaseCorporateGovernanceTransaction,
)
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.banking.public import (
    AccountingEntryReference as BankingAccountingEntryReference,
    BankTransactionId,
    ClaimBankTransactionForExternalActionCommand,
    ExternalActionReference,
)
from talli_backend.modules.corporate_governance.public import (
    AttestAnnualCloseSignedArtifactCommand,
    CorporateArtifactId,
    CorporateArtifactKind,
    CorporateDecisionKind,
    CorporateDecisionId,
    CorporateDocumentSetId,
    ApproveOwnerDividendCommand,
    CorporateEventId,
    DocumentReference,
    OwnerDividendState,
    PreparedShareholderLoan,
    RecordedShareholderLoan,
)
from talli_backend.modules.corporate_governance.service import CorporateGovernanceService
from talli_backend.modules.ledger.public import (
    LedgerEntryKind,
    LedgerLine,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    PostOwnerDividendDeclaredCommand,
    PostShareholderLoanCommand,
    ShareholderLoanDirection as LedgerShareholderLoanDirection,
)
from talli_backend.shared.kernel import CorrelationId, IdempotencyKey, IncomeYear, LocalDate, Money

from test_corporate_governance import (
    supported_annual_close,
    supported_proposal,
    supported_shareholder_loan,
)
from test_corporate_governance_workflow import (
    DECISION_HASH,
    document_command,
    finalization_command,
    payment_command,
)


def bound_transaction() -> SupabaseCorporateGovernanceTransaction:
    command = supported_proposal()
    return SupabaseCorporateGovernanceTransaction(
        "postgresql://unused",
        _VerifiedActor(
            actor_id=command.actor_id,
            claims_json=(
                '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",'
                '"role":"authenticated","aal":"aal2"}'
            ),
        ),
        None,  # type: ignore[arg-type]
    )


def test_session_uses_only_non_bypass_governance_workflow_role_and_verified_context() -> None:
    source = inspect.getsource(SupabaseCorporateGovernanceSession.transaction)
    assert "set_isolation_level(psycopg.IsolationLevel.SERIALIZABLE)" in source
    assert "set local role corporate_governance_workflow_executor" in source
    assert "talli.verified_actor_id" in source
    assert "talli.verified_actor_claims" in source


def test_annual_data_uses_the_frozen_restricted_compatibility_reader() -> None:
    transaction = bound_transaction()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def rows(query: str, parameters: tuple[object, ...] = ()):
        calls.append((query, parameters))
        return [{"items": [{
                "sourceId": "33333333-3333-4333-8333-333333333333",
                "companyId": "22222222-2222-4222-8222-222222222222",
                "incomeYear": 2024,
                "answers": {"general_meeting_approved": True},
                "confirmations": [],
                "noActivityConfirmed": False,
                "annualFullTimeEquivalents": 0,
                "completedAt": "2025-05-01T10:00:00+00:00",
                "updatedAt": "2025-05-01T10:00:00+00:00",
            }]}]

    transaction._database_rows = rows  # type: ignore[method-assign]
    facts = asyncio.run(transaction.list_annual_data_compatibility(
        company_id=supported_proposal().company_id,
        income_year=IncomeYear(2025),
    ))

    assert int(facts[0].income_year) == 2024
    assert "list_annual_data_legacy_v1" in calls[0][0]


def test_annual_data_normalizes_legacy_null_fte_to_zero() -> None:
    transaction = bound_transaction()

    async def rows(query: str, parameters: tuple[object, ...] = ()):
        return [{"items": [{
                "sourceId": "33333333-3333-4333-8333-333333333333",
                "companyId": "22222222-2222-4222-8222-222222222222",
                "incomeYear": 2024,
                "answers": {"general_meeting_approved": True},
                "confirmations": [],
                "noActivityConfirmed": False,
                "annualFullTimeEquivalents": None,
                "completedAt": "2025-05-01T10:00:00+00:00",
                "updatedAt": "2025-05-01T10:00:00+00:00",
            }]}]

    transaction._database_rows = rows  # type: ignore[method-assign]
    facts = asyncio.run(transaction.list_annual_data_compatibility(
        company_id=supported_proposal().company_id,
        income_year=IncomeYear(2025),
    ))

    assert facts[0].annual_full_time_equivalents == 0


def test_company_identity_uses_the_company_access_owned_query_contract() -> None:
    transaction = bound_transaction()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def rows(query: str, parameters: tuple[object, ...] = ()):
        calls.append((query, parameters))
        return [{"result": {
            "companyId": str(supported_proposal().company_id),
            "organizationNumber": "310279617",
            "legalName": "LOGISK ØDE TIGER AS",
        }}]

    transaction._database_rows = rows  # type: ignore[method-assign]
    facts = asyncio.run(
        transaction.read_company_facts(supported_proposal().company_id)
    )

    assert facts.organization_number == "310279617"
    assert facts.legal_name == "LOGISK ØDE TIGER AS"
    assert "company_access_read_company_identity_v1" in calls[0][0]


def test_proposal_sends_python_canonical_facts_without_account_policy() -> None:
    transaction = bound_transaction()
    command = supported_proposal()
    service = CorporateGovernanceService()
    decision = service.build_owner_dividend_decision(command)
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def rows(query: str, parameters: tuple[object, ...] = ()):
        calls.append((query, parameters))
        return [{"result": {
            "state": "proposed",
            "replayed": False,
        }}]

    transaction._database_rows = rows  # type: ignore[method-assign]
    result = asyncio.run(
        transaction.propose_owner_dividend(
            command,
            decision,
            service.canonical_payload(decision),
        )
    )
    request = json.loads(str(calls[0][1][0]))
    canonical = json.loads(str(calls[0][1][1]))

    assert result.decision == decision
    assert result.state is OwnerDividendState.PROPOSED
    assert "corporate_governance.propose_owner_dividend_v1" in calls[0][0]
    assert request["decisionId"] == str(command.decision_id)
    assert canonical["decisionHash"] == decision.decision_hash
    assert canonical["dividend"]["amountOre"] == 10_000_001
    assert "declarationDebitAccount" not in json.dumps(canonical)
    assert "accountingPolicyVersion" not in json.dumps(canonical)


def test_annual_close_proposal_uses_the_restricted_canonical_store() -> None:
    transaction = bound_transaction()
    command = supported_annual_close()
    service = CorporateGovernanceService()
    decision = service.build_annual_close_decision(command)
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def rows(query: str, parameters: tuple[object, ...] = ()):
        calls.append((query, parameters))
        return [{"result": {"state": "proposed", "replayed": False}}]

    transaction._database_rows = rows  # type: ignore[method-assign]
    artifacts = CorporateGovernanceService().render_corporate_documents(decision)
    result = asyncio.run(
        transaction.propose_annual_close(
            command,
            decision,
            service.canonical_payload(decision),
            artifacts,
        )
    )
    request = json.loads(str(calls[0][1][0]))
    canonical = json.loads(str(calls[0][1][1]))
    rendered = json.loads(str(calls[0][1][3]))

    assert result.decision == decision
    assert result.state is OwnerDividendState.PROPOSED
    assert "corporate_governance.propose_annual_close_v1" in calls[0][0]
    assert request["decisionId"] == str(command.decision_id)
    assert canonical["decisionKind"] == "annual_close"
    assert canonical["dividend"] is None
    assert rendered[0]["contentSha256"] == artifacts[0].content_sha256


def test_annual_close_signed_artifact_uses_restricted_canonical_store() -> None:
    transaction = bound_transaction()
    command = AttestAnnualCloseSignedArtifactCommand(
        company_id=supported_annual_close().company_id,
        actor_id=supported_annual_close().actor_id,
        correlation_id=CorrelationId("annual-close-board-signed"),
        idempotency_key=IdempotencyKey("annual-close-board-signed-0001"),
        decision_id=CorporateDecisionId(
            "11111111-1111-4111-8111-111111111111"
        ),
        document_set_id=CorporateDocumentSetId(
            "44444444-4444-4444-8444-444444444444"
        ),
        decision_hash="c" * 64,
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
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def rows(query: str, parameters: tuple[object, ...] = ()):
        calls.append((query, parameters))
        return [{"result": annual_lifecycle_payload("signed_owner_attested")}]

    transaction._database_rows = rows  # type: ignore[method-assign]
    result = asyncio.run(transaction.attest_annual_close_signed_artifact(command))
    request = json.loads(str(calls[0][1][0]))

    assert result.state is OwnerDividendState.SIGNED_OWNER_ATTESTED
    assert "backend_system.attest_corporate_governance_signed_artifact_v1" in calls[0][0]
    assert request["unsignedArtifactId"] == str(command.unsigned_artifact_id)
    assert request["signedArtifactId"] == str(command.signed_artifact_id)
    assert request["signers"] == ["Ola Nordmann"]


def test_document_approval_and_finalization_map_exact_replays() -> None:
    transaction = bound_transaction()
    proposal = supported_proposal()
    approval = ApproveOwnerDividendCommand(
        company_id=proposal.company_id,
        actor_id=proposal.actor_id,
        correlation_id=CorrelationId("owner-dividend-approval"),
        idempotency_key=IdempotencyKey("owner-dividend-approval-0001"),
        decision_id=proposal.decision_id,
        document_set_id=proposal.document_set_id,
        decision_hash=DECISION_HASH,
        approval_event_id=CorporateEventId("eeeeeeee-1111-4111-8111-111111111111"),
    )
    calls: list[tuple[str, tuple[object, ...]]] = []
    responses = iter([
        {"result": lifecycle_payload("documents_registered")},
        {"result": lifecycle_payload("facts_approved")},
        {"result": {
            "declaredAmountOre": 10_000_001,
            "accountingPolicyVersion": "no-holding-v1",
            "declarationDebitAccount": "2050",
            "dividendPayableAccount": "2920",
            "signedArtifactHashes": {
                "dividend_board_proposal": "a" * 64,
                "dividend_general_meeting_minutes": "b" * 64,
            },
            "replay": None,
        }},
        {"result": lifecycle_payload("finalized", accounting_entry_id=str(finalization_command().ledger_entry_id))},
    ])

    async def rows(query: str, parameters: tuple[object, ...] = ()):
        calls.append((query, parameters))
        return [next(responses)]

    transaction._database_rows = rows  # type: ignore[method-assign]
    assert asyncio.run(transaction.register_owner_dividend_documents(document_command())).state is OwnerDividendState.DOCUMENTS_REGISTERED
    assert asyncio.run(transaction.approve_owner_dividend(approval)).state is OwnerDividendState.FACTS_APPROVED
    prepared = asyncio.run(transaction.prepare_owner_dividend_finalization(finalization_command()))
    assert prepared.declared_amount_ore == 10_000_001
    completed = asyncio.run(transaction.complete_owner_dividend_finalization(
        finalization_command(), finalization_command().ledger_entry_id, prepared
    ))
    assert completed.state is OwnerDividendState.FINALIZED
    assert [name in query for name, query in [
        ("backend_system.register_corporate_governance_documents_v1", calls[0][0]),
        ("approve_owner_dividend_v1", calls[1][0]),
        ("prepare_owner_dividend_finalization_v1", calls[2][0]),
        ("complete_owner_dividend_finalization_v1", calls[3][0]),
    ]] == [True, True, True, True]


def test_ledger_and_banking_calls_use_governance_restricted_wrappers() -> None:
    transaction = bound_transaction()
    command = finalization_command()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def one_row(query: str, parameters: tuple[object, ...]):
        calls.append((query, parameters))
        return {
            "ledger_entry_id": str(command.ledger_entry_id),
            "company_id": str(command.company_id),
            "income_year": int(command.income_year),
            "entry_kind": "OWNER_DIVIDEND_DECLARED",
            "posted_at": datetime(2025, 6, 20, tzinfo=UTC),
            "replayed": False,
        }

    transaction._one_idempotent_row = one_row  # type: ignore[method-assign]
    ledger_command = PostOwnerDividendDeclaredCommand(
        company_id=command.company_id,
        actor_id=command.actor_id,
        correlation_id=command.correlation_id,
        idempotency_key=command.idempotency_key,
        income_year=command.income_year,
        finalization_id=LedgerSourceRecordId(str(command.finalization_id)),
        declared_amount=Money.nok("100000.01"),
        declaration_debit_account="2050",
        dividend_payable_account="2920",
        accounting_policy_version="no-holding-v1",
        ledger_entry_id=command.ledger_entry_id,
    )
    asyncio.run(transaction.post_entry(
        ledger_command,
        entry_kind=LedgerEntryKind.OWNER_DIVIDEND_DECLARED,
        memo="Declared owner dividend from finalized corporate decision",
        lines=(
            LedgerLine("2050", "Declared dividend to owners", Money.nok("100000.01"), Money.nok("0")),
            LedgerLine("2920", "Dividend payable to owners", Money.nok("0"), Money.nok("100000.01")),
        ),
        risk_flags=(),
        warning_accepted=False,
        source_capability=LedgerSourceCapability.CORPORATE_GOVERNANCE,
        source_record_id=ledger_command.finalization_id,
        requested_entry_id=ledger_command.ledger_entry_id,
    ))
    assert "ledger.post_corporate_governance_entry_v1" in calls[0][0]
    assert "ledger.post_entry_with_id_v1" not in calls[0][0]

    loan = supported_shareholder_loan()
    loan_command = PostShareholderLoanCommand(
        company_id=loan.company_id,
        actor_id=loan.actor_id,
        correlation_id=loan.correlation_id,
        idempotency_key=loan.idempotency_key,
        income_year=loan.income_year,
        action_id=LedgerSourceRecordId(str(loan.action_id)),
        counterparty_name=loan.counterparty_name,
        direction=LedgerShareholderLoanDirection.SHAREHOLDER_TO_COMPANY,
        amount=loan.amount,
        ledger_entry_id=loan.ledger_entry_id,
    )
    asyncio.run(transaction.post_entry(
        loan_command,
        entry_kind=LedgerEntryKind.SHAREHOLDER_LOAN,
        memo="Shareholder loan from Eier Holding AS",
        lines=(
            LedgerLine("1920", "Bank", Money.nok("1250.50"), Money.nok("0")),
            LedgerLine("2255", "Debt", Money.nok("0"), Money.nok("1250.50")),
        ),
        risk_flags=(),
        warning_accepted=False,
        source_capability=LedgerSourceCapability.CORPORATE_GOVERNANCE,
        source_record_id=loan_command.action_id,
        requested_entry_id=loan_command.ledger_entry_id,
    ))
    assert "ledger.post_corporate_governance_entry_v1" in calls[1][0]

    async def rows(query: str, parameters: tuple[object, ...] = ()):
        calls.append((query, parameters))
        return [{"result": {"transactionId": str(payment_command().bank_transaction_id)}}]

    transaction._database_rows = rows  # type: ignore[method-assign]
    payment = payment_command()
    asyncio.run(transaction.claim_transaction_for_external_action(
        ClaimBankTransactionForExternalActionCommand(
            company_id=payment.company_id,
            actor_id=payment.actor_id,
            correlation_id=payment.correlation_id,
            idempotency_key=payment.idempotency_key,
            income_year=payment.income_year,
            transaction_id=BankTransactionId(str(payment.bank_transaction_id)),
            transaction_date=LocalDate(date(2025, 7, 2)),
            signed_amount=Money.nok("-750.00"),
            source_hash="d" * 64,
            action_reference=ExternalActionReference(str(payment.payment_event_id)),
        ),
        accounting_entry_id=BankingAccountingEntryReference(str(payment.ledger_entry_id)),
    ))
    assert "banking.claim_corporate_governance_transaction_v1" in calls[2][0]
    assert "claim_transaction_for_external_action_v1" not in calls[2][0]


def test_payment_prepare_carries_the_declaration_policy_into_completion() -> None:
    transaction = bound_transaction()
    command = payment_command()
    calls: list[tuple[str, tuple[object, ...]]] = []
    responses = iter([
        {"result": {
            "paymentAmountOre": 75_000,
            "bankTransactionDate": "2025-07-02",
            "bankSignedAmount": "-750.00",
            "bankSourceSha256": "d" * 64,
            "accountingPolicyVersion": "no-holding-v1",
            "dividendPayableAccount": "2920",
            "bankAccount": "1920",
            "replay": None,
        }},
        {"result": lifecycle_payload(
            "partially_paid",
            accounting_entry_id=str(command.ledger_entry_id),
        )},
    ])

    async def rows(query: str, parameters: tuple[object, ...] = ()):
        calls.append((query, parameters))
        return [next(responses)]

    transaction._database_rows = rows  # type: ignore[method-assign]
    prepared = asyncio.run(transaction.prepare_owner_dividend_payment(command))
    assert prepared.accounting_policy_version == "no-holding-v1"
    assert prepared.dividend_payable_account == "2920"
    assert prepared.bank_account == "1920"
    asyncio.run(transaction.complete_owner_dividend_payment(
        command, command.ledger_entry_id, prepared
    ))
    completion_request = json.loads(str(calls[1][1][0]))
    assert completion_request["accountingPolicyVersion"] == "no-holding-v1"


def test_shareholder_loan_prepare_and_complete_use_canonical_governance_store() -> None:
    transaction = bound_transaction()
    command = supported_shareholder_loan()
    loan = CorporateGovernanceService().validate_shareholder_loan(command)
    calls: list[tuple[str, tuple[object, ...]]] = []
    responses = iter([
        {"result": {
            "loan": {
                "actionId": str(loan.action_id),
                "companyId": str(loan.company_id),
                "incomeYear": int(loan.income_year),
                "loanDate": loan.loan_date.value.isoformat(),
                "amountOre": loan.amount_ore,
                "direction": loan.direction.value,
                "counterpartyName": loan.counterparty_name,
                "documentStatus": loan.document_status.value,
                "interestModelled": loan.interest_modelled,
                "relatedPartySecurity": False,
                "bankTransactionId": None,
                "documentId": None,
            },
            "bankTransactionDate": None,
            "bankSignedAmount": None,
            "bankSourceSha256": None,
            "replay": None,
        }},
        {"result": {
            "loan": {
                "actionId": str(loan.action_id),
                "companyId": str(loan.company_id),
                "incomeYear": int(loan.income_year),
                "loanDate": loan.loan_date.value.isoformat(),
                "amountOre": loan.amount_ore,
                "direction": loan.direction.value,
                "counterpartyName": loan.counterparty_name,
                "documentStatus": loan.document_status.value,
                "interestModelled": loan.interest_modelled,
                "relatedPartySecurity": False,
                "bankTransactionId": None,
                "documentId": None,
            },
            "accountingEntryId": str(command.ledger_entry_id),
            "replayed": False,
        }},
    ])

    async def rows(query: str, parameters: tuple[object, ...] = ()):
        calls.append((query, parameters))
        return [next(responses)]

    transaction._database_rows = rows  # type: ignore[method-assign]
    prepared = asyncio.run(transaction.prepare_shareholder_loan(command, loan))
    assert isinstance(prepared, PreparedShareholderLoan)
    assert prepared.loan == loan
    result = asyncio.run(transaction.complete_shareholder_loan(
        command, command.ledger_entry_id, prepared
    ))
    assert isinstance(result, RecordedShareholderLoan)
    assert result.loan == loan
    assert result.accounting_entry_id == command.ledger_entry_id
    assert "corporate_governance.prepare_shareholder_loan_v1" in calls[0][0]
    assert "backend_system.complete_corporate_governance_shareholder_loan_v1" in calls[1][0]
    completion = json.loads(str(calls[1][1][0]))
    assert completion["ledgerEntryId"] == str(command.ledger_entry_id)


def lifecycle_payload(state: str, *, accounting_entry_id: str | None = None) -> dict[str, object]:
    command = supported_proposal()
    return {
        "decisionId": str(command.decision_id),
        "documentSetId": str(command.document_set_id),
        "companyId": str(command.company_id),
        "incomeYear": int(command.income_year),
        "decisionHash": DECISION_HASH,
        "state": state,
        "declaredAmountOre": 10_000_001,
        "paidAmountOre": 0,
        "remainingAmountOre": 10_000_001,
        "finalizationId": (
            str(finalization_command().finalization_id) if state == "finalized" else None
        ),
        "accountingEntryId": accounting_entry_id,
        "replayed": False,
    }


def annual_lifecycle_payload(state: str) -> dict[str, object]:
    command = supported_annual_close()
    return {
        "decisionId": str(command.decision_id),
        "documentSetId": str(command.document_set_id),
        "companyId": str(command.company_id),
        "incomeYear": int(command.income_year),
        "decisionHash": DECISION_HASH,
        "state": state,
        "generatedArtifactHashes": {
            "annual_board_minutes": "a" * 64,
            "annual_general_meeting_minutes": "b" * 64,
        },
        "signedArtifactHashes": {"annual_board_minutes": "e" * 64},
        "finalizationId": None,
        "replayed": False,
    }


def test_guarded_sessions_acquire_company_guard_after_identity_before_application_work(monkeypatch):
    from contextlib import asynccontextmanager
    import psycopg
    from talli_backend.adapters.supabase_ledger import SupabaseLedgerSession
    command = supported_proposal()
    verified = bound_transaction()._verified
    for session_type, schema in ((SupabaseCorporateGovernanceSession, 'corporate_governance'),
                                 (SupabaseLedgerSession, 'ledger')):
        events = []
        class Connection:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def set_isolation_level(self, value): events.append(('isolation', value))
            @asynccontextmanager
            async def transaction(self):
                events.append(('begin',))
                yield self
                events.append(('commit',))
            async def execute(self, query, params=()): events.append((query, params))
        async def connect(*args, **kwargs): return Connection()
        monkeypatch.setattr(psycopg.AsyncConnection, 'connect', connect)
        async def run():
            session = session_type('postgresql://unused', verified)
            async with session.transaction(guarded_company_id=command.company_id):
                events.append(('application',))
        asyncio.run(run())
        guard = next(i for i,e in enumerate(events) if f'{schema}.acquire_company_write_guard_v1' in e[0])
        identity = next(i for i,e in enumerate(events) if 'talli.verified_actor_claims' in e[0])
        application = events.index(('application',))
        assert identity < guard < application
        assert events[guard][1] == (str(command.company_id), str(command.actor_id.subject))
        assert ('isolation', psycopg.IsolationLevel.READ_COMMITTED) in events or ('set transaction isolation level read committed', ()) in events
        assert events[-1] == ('commit',)


def test_unguarded_governance_reads_keep_serializable_isolation(monkeypatch):
    from contextlib import asynccontextmanager
    import psycopg
    events = []
    class Connection:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def set_isolation_level(self, value): events.append(value)
        @asynccontextmanager
        async def transaction(self): yield self
        async def execute(self, query, params=()): events.append(query)
    async def connect(*args, **kwargs): return Connection()
    monkeypatch.setattr(psycopg.AsyncConnection, 'connect', connect)
    async def run():
        async with SupabaseCorporateGovernanceSession('postgresql://unused', bound_transaction()._verified).transaction():
            pass
    asyncio.run(run())
    assert events[0] == psycopg.IsolationLevel.SERIALIZABLE
    assert not any('acquire_company_write_guard' in str(e) for e in events)


def test_exact_register_and_retained_receipts_use_the_existing_governance_connection(monkeypatch):
    from types import SimpleNamespace
    from test_corporate_register_evidence import harness
    from talli_backend.adapters import supabase_corporate_governance as adapter
    h = harness()
    evidence = h.verify()
    transaction = bound_transaction()
    transaction._connection = object()
    calls = []
    async def rows(query, parameters=()):
        calls.append(('rf', query, parameters))
        return []
    transaction._database_rows = rows
    class Originals:
        def __init__(self, connection, actor):
            assert connection is transaction._connection and actor == transaction.actor_id
        async def assert_retained_original(self, receipt): calls.append(('original', receipt))
    monkeypatch.setattr(adapter, 'PostgresDocumentOriginals', Originals)
    asyncio.run(transaction.assert_register_evidence(evidence))
    assert 'assert_current_register_observation_v1' in calls[0][1]
    assert calls[0][2] == (evidence.observation.observation_id.value, str(evidence.observation.command.company_id),
                          int(evidence.observation.command.income_year), evidence.observation.version,
                          evidence.observation.fact_sha256, str(transaction.actor_id.subject))
    assert [c[1] for c in calls[1:]] == list(evidence.originals)


def test_final_evidence_errors_map_to_governance_precondition():
    from talli_backend.adapters.supabase_corporate_governance import _map_governance_database_error
    from talli_backend.modules.corporate_governance.public import CorporateGovernanceErrorCode
    for code in ('rf1086_register_predecessor_mismatch', 'documents_evidence_mismatch'):
        error = _map_governance_database_error(code)
        assert error.code is CorporateGovernanceErrorCode.CORPORATE_EVENT_EVIDENCE_INCOMPLETE
