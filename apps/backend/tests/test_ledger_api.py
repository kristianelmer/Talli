from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.application.opening_snapshot_compatibility import (
    LegacyOpeningShareholderView,
    LegacyOpeningSnapshotCursor,
    LegacyOpeningSnapshotPage,
    LegacyOpeningSnapshotView,
)
from talli_backend.main import create_app
from talli_backend.modules.ledger.public import (
    CompanyYearCloseAssessment,
    CompanyYearCloseAssessmentId,
    CompanyYearCloseLockId,
    CompanyYearCloseState,
    LedgerCursor,
    LedgerEntryId,
    LedgerEntryKind,
    LedgerEntryPage,
    LedgerEntryView,
    LedgerLine,
    LedgerPage,
    LedgerRiskCode,
    LedgerRiskFlag,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    PeriodLock,
    PeriodLockId,
    PeriodLockPage,
    PostedLedgerEntry,
    ReconstructionAssessment,
    ReconstructionAssessmentId,
    ReconstructionGapCode,
    ReconstructionState,
)
from talli_backend.modules.shareholder_register_filing.public import OpeningSnapshotId
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    IncomeYear,
    LocalDate,
    Money,
    Timestamp,
    UserId,
)

COMPANY_ID = CompanyId("10000000-0000-0000-0000-000000000001")
ACTOR_ID = ActorId(
    kind=ActorKind.USER,
    subject=UserId("20000000-0000-0000-0000-000000000002"),
)
ENTRY_ID = LedgerEntryId("40000000-0000-0000-0000-000000000004")
SETUP_ID = OpeningSnapshotId("60000000-0000-0000-0000-000000000006")
NOW = Timestamp(datetime(2026, 8, 27, 10, tzinfo=UTC))


class LedgerSessionStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.tokens: list[str] = []
        self.entry_items: tuple[LedgerEntryView, ...] = ()
        self.entry_next_cursor: LedgerCursor | None = LedgerCursor("opaque-next")
        self.opening_snapshots = LegacyOpeningSnapshotPage(
            items=(), next_cursor=None, has_more=False
        )
        self.reconstruction_assessment = ReconstructionAssessment(
            assessment_id=ReconstructionAssessmentId(
                "41000000-0000-0000-0000-000000000004"
            ),
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            as_of=LocalDate(date(2026, 8, 27)),
            state=ReconstructionState.BLOCKED,
            gap_codes=(ReconstructionGapCode.DOCUMENTS_INCOMPLETE,),
            evidence_digest="a" * 64,
            ledger_state_digest="d" * 64,
            recorded_at=NOW,
            replayed=False,
            economic_facts_digest="e" * 64,
            economic_fact_count=7,
            source_evidence_digest="a" * 64,
            source_evidence_count=13,
        )
        self.company_year_close_assessment = CompanyYearCloseAssessment(
            assessment_id=CompanyYearCloseAssessmentId(
                "42000000-0000-0000-0000-000000000004"
            ),
            close_lock_id=CompanyYearCloseLockId(
                "43000000-0000-0000-0000-000000000004"
            ),
            reconstruction_assessment_id=ReconstructionAssessmentId(
                "41000000-0000-0000-0000-000000000004"
            ),
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            period_end=LocalDate(date(2026, 12, 31)),
            state=CompanyYearCloseState.CLOSED,
            gap_codes=(),
            evidence_digest="b" * 64,
            ledger_state_digest="c" * 64,
            recorded_at=NOW,
            replayed=False,
            is_current=True,
        )

    @property
    def actor_id(self) -> ActorId:
        return ACTOR_ID

    async def session(self, access_token: str) -> LedgerSessionStub:
        self.tokens.append(access_token)
        return self

    @asynccontextmanager
    async def transaction(self):
        self.calls.append(("transaction", "begin"))
        yield self
        self.calls.append(("transaction", "commit"))

    async def claim_workflow(
        self, *, operation_name: str, command: object, request: dict[str, object]
    ) -> None:
        self.calls.append(
            ("claim_workflow", {"operation": operation_name, "request": request})
        )

    async def record_legacy_opening_snapshot(
        self, command: object, *, ledger_bank_balance: object
    ) -> OpeningSnapshotId:
        self.calls.append(
            ("record_legacy_opening_snapshot", {"command": command, "bank": ledger_bank_balance})
        )
        return SETUP_ID

    async def list_opening_snapshots(
        self, *, actor_id, company_ids, correlation_id, cursor, limit
    ) -> LegacyOpeningSnapshotPage:
        self.calls.append(
            (
                "list_opening_snapshots",
                {
                    "actor_id": actor_id,
                    "company_ids": company_ids,
                    "correlation_id": correlation_id,
                    "cursor": cursor,
                    "limit": limit,
                },
            )
        )
        return self.opening_snapshots

    async def complete_workflow(
        self,
        *,
        operation_name: str,
        command: object,
        request: dict[str, object],
        result: dict[str, object],
    ) -> None:
        self.calls.append(
            (
                "complete_workflow",
                {"operation": operation_name, "request": request, "result": result},
            )
        )

    async def prepare_administrative_cost(
        self, command: object
    ) -> dict[str, object]:
        self.calls.append(("prepare_administrative_cost", command))
        return {}

    async def complete_administrative_cost(
        self,
        command: object,
        posted_entry: PostedLedgerEntry,
        prepared: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append(
            (
                "complete_administrative_cost",
                {
                    "command": command,
                    "posted_entry": posted_entry,
                    "prepared": prepared,
                },
            )
        )
        return {}

    async def _prepare(
        self, operation: str, command: object, **facts: object
    ) -> dict[str, object]:
        self.calls.append((f"prepare_{operation}", command))
        return facts

    async def _complete(
        self,
        operation: str,
        command: object,
        posted_entry: PostedLedgerEntry | None,
        prepared: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append(
            (
                f"complete_{operation}",
                {
                    "command": command,
                    "posted_entry": posted_entry,
                    "prepared": prepared,
                },
            )
        )
        return {}

    async def prepare_investment_dividend(
        self, command: object
    ) -> dict[str, object]:
        return await self._prepare("investment_dividend", command)

    async def complete_investment_dividend(
        self, command: object, posted_entry: PostedLedgerEntry, prepared: dict[str, object]
    ) -> dict[str, object]:
        return await self._complete(
            "investment_dividend", command, posted_entry, prepared
        )

    async def prepare_shareholder_loan(
        self, command: object
    ) -> dict[str, object]:
        return await self._prepare("shareholder_loan", command)

    async def complete_shareholder_loan(
        self, command: object, posted_entry: PostedLedgerEntry, prepared: dict[str, object]
    ) -> dict[str, object]:
        return await self._complete("shareholder_loan", command, posted_entry, prepared)

    async def prepare_tax_settlement(
        self, command: object
    ) -> dict[str, object]:
        return await self._prepare("tax_settlement", command)

    async def complete_tax_settlement(
        self, command: object, posted_entry: PostedLedgerEntry, prepared: dict[str, object]
    ) -> dict[str, object]:
        return await self._complete("tax_settlement", command, posted_entry, prepared)

    async def prepare_investment_sale_fifo(
        self, command: object
    ) -> dict[str, object]:
        return await self._prepare(
            "investment_sale_fifo",
            command,
            investmentName="Example AS",
            fifoCostBasisReduction="80.00",
        )

    async def complete_investment_sale_fifo(
        self, command: object, posted_entry: PostedLedgerEntry, prepared: dict[str, object]
    ) -> dict[str, object]:
        return await self._complete(
            "investment_sale_fifo", command, posted_entry, prepared
        )

    async def prepare_corporate_decision_finalization(
        self, command: object
    ) -> dict[str, object]:
        return await self._prepare(
            "corporate_decision_finalization",
            command,
            decisionKind="owner_dividend",
            declaredAmount="100.00",
            declarationDebitAccount="2050",
            dividendPayableAccount="2920",
            accountingPolicyVersion="owner-dividend-v1",
        )

    async def complete_corporate_decision_finalization(
        self,
        command: object,
        posted_entry: PostedLedgerEntry | None,
        prepared: dict[str, object],
    ) -> dict[str, object]:
        return await self._complete(
            "corporate_decision_finalization", command, posted_entry, prepared
        )

    async def prepare_owner_dividend_payment(
        self, command: object
    ) -> dict[str, object]:
        return await self._prepare(
            "owner_dividend_payment",
            command,
            paymentAmount="100.00",
            dividendPayableAccount="2920",
            bankAccount="1920",
            accountingPolicyVersion="owner-dividend-v1",
        )

    async def complete_owner_dividend_payment(
        self, command: object, posted_entry: PostedLedgerEntry, prepared: dict[str, object]
    ) -> dict[str, object]:
        return await self._complete(
            "owner_dividend_payment", command, posted_entry, prepared
        )

    async def post_entry(self, command: object, **posting: object) -> PostedLedgerEntry:
        self.calls.append(("post_entry", {"command": command, **posting}))
        return PostedLedgerEntry(
            entry_id=ENTRY_ID,
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            entry_kind=posting["entry_kind"],
            posted_at=NOW,
            replayed=False,
        )

    async def rebuild_company_year_opening(
        self, command: object, **posting: object
    ) -> PostedLedgerEntry:
        self.calls.append(
            ("rebuild_company_year_opening", {"command": command, **posting})
        )
        return PostedLedgerEntry(
            entry_id=ENTRY_ID,
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.OPENING_BALANCE,
            posted_at=NOW,
            replayed=False,
        )

    async def lock_period(self, command: object) -> PeriodLock:
        self.calls.append(("lock_period", command))
        return PeriodLock(
            period_lock_id=PeriodLockId("50000000-0000-0000-0000-000000000005"),
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            reason=command.reason,
            locked_by=ACTOR_ID,
            locked_at=NOW,
            replayed=False,
        )

    async def list_entries(self, **query: object) -> LedgerEntryPage:
        self.calls.append(("list_entries", query))
        return LedgerEntryPage(
            items=self.entry_items,
            page=LedgerPage(
                next_cursor=self.entry_next_cursor,
                has_more=self.entry_next_cursor is not None,
            ),
        )

    async def list_period_locks(self, **query: object) -> PeriodLockPage:
        self.calls.append(("list_period_locks", query))
        return PeriodLockPage(
            items=(),
            page=LedgerPage(next_cursor=None, has_more=False),
        )

    async def get_reconstruction_assessment(
        self, **query: object
    ) -> ReconstructionAssessment:
        self.calls.append(("get_reconstruction_assessment", query))
        return self.reconstruction_assessment

    async def get_company_year_close_assessment(
        self, **query: object
    ) -> CompanyYearCloseAssessment:
        self.calls.append(("get_company_year_close_assessment", query))
        return self.company_year_close_assessment


def client_and_session() -> tuple[TestClient, LedgerSessionStub]:
    session = LedgerSessionStub()
    return TestClient(create_app(ledger_session_factory=session)), session


def entry_view() -> LedgerEntryView:
    return LedgerEntryView(
        entry_id=ENTRY_ID,
        company_id=COMPANY_ID,
        income_year=IncomeYear(2026),
        entry_kind=LedgerEntryKind.MANUAL_JOURNAL,
        source_capability=LedgerSourceCapability.LEDGER,
        source_record_id=LedgerSourceRecordId("manual:ledger-api-test"),
        created_at=NOW,
        memo="Manual correction",
        lines=(
            LedgerLine(
                account="1800",
                description="Investment",
                debit=Money.nok("100.00"),
                credit=Money.nok("0.00"),
            ),
            LedgerLine(
                account="1920",
                description="Bank",
                debit=Money.nok("0.00"),
                credit=Money.nok("100.00"),
            ),
        ),
        risk_flags=(
            LedgerRiskFlag(
                code=LedgerRiskCode.MANUAL_JOURNAL_SENSITIVE_ACCOUNT,
                account="1800",
            ),
        ),
        warning_accepted_by=None,
        warning_accepted_at=None,
        posted_by=ACTOR_ID,
        posted_at=NOW,
    )


class UnauthenticatedSessionFactory:
    async def session(self, _access_token: str) -> LedgerSessionStub:
        raise LedgerAuthenticationError


def headers(*, idempotency: bool = True) -> dict[str, str]:
    result = {
        "Authorization": "Bearer ledger-token",
        "X-Request-ID": "ledger-contract-test",
    }
    if idempotency:
        result["Idempotency-Key"] = "30000000-0000-4000-8000-000000000003"
    return result


def money(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "NOK"}


def administrative_cost_body() -> dict[str, object]:
    return {
        "companyId": str(COMPANY_ID),
        "incomeYear": 2026,
        "bankTransactionId": "70000000-0000-4000-8000-000000000007",
        "category": "BANK_FEE",
        "payee": "Bank",
        "amount": money("100.00"),
        "paidDate": "2026-08-27",
        "documentId": None,
    }


def manual_body() -> dict[str, object]:
    return {
        "companyId": str(COMPANY_ID),
        "incomeYear": 2026,
        "memo": "Manual sensitive correction",
        "warningAccepted": True,
        "lines": [
            {
                "account": "1800",
                "description": "Investment",
                "debit": money("100.00"),
                "credit": money("0.00"),
            },
            {
                "account": "1920",
                "description": "Bank",
                "debit": money("0.00"),
                "credit": money("100.00"),
            },
        ],
    }


def test_ledger_http_contract_exposes_only_ledger_owned_user_intents() -> None:
    client, _session = client_and_session()
    operations = {
        operation["operationId"]
        for path in client.app.openapi()["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and "operationId" in operation
    }

    assert {
        "ledgerListEntries",
        "ledgerListPeriodLocks",
        "ledgerLockPeriod",
        "ledgerPostAdministrativeCost",
        "ledgerPostInvestmentDividend",
        "ledgerPostInvestmentSale",
        "ledgerPostManualJournal",
        "ledgerPostOwnerDividendPayment",
        "ledgerPostShareholderLoan",
        "ledgerPostTaxSettlement",
        "ledgerFinalizeCorporateDecision",
        "ledgerStartNewYear",
        "ledgerListOpeningSnapshots",
    } <= operations
    assert not {
        "ledgerPostOwnerDividendDeclared",
        "ledgerPostStructuredEntry",
    } & operations
    assert not {
        "/api/v1/ledger/owner-dividends/declared",
        "/api/v1/ledger/opening-balances",
        "/api/v1/ledger/structured-entries",
    } & client.app.openapi()["paths"].keys()


def test_cross_capability_writers_bind_business_facts_to_one_ledger_result() -> None:
    operation_id = "70000000-0000-4000-8000-000000000070"
    bank_id = "70000000-0000-4000-8000-000000000071"
    document_id = "70000000-0000-4000-8000-000000000072"
    position_id = "70000000-0000-4000-8000-000000000073"
    decision_id = "70000000-0000-4000-8000-000000000074"
    set_id = "70000000-0000-4000-8000-000000000075"
    holding_action_id = "70000000-0000-4000-8000-000000000076"
    decision_hash = "a" * 64
    common = {"companyId": str(COMPANY_ID), "incomeYear": 2026}
    cases = (
        (
            "/api/v1/ledger/investment-dividends",
            "DIVIDEND_RECEIVED",
            {
                **common,
                "actionId": operation_id,
                "payingCompanyName": "Example AS",
                "declaredDate": "2026-04-01",
                "paidDate": "2026-04-15",
                "grossAmount": money("125.50"),
                "linkedInvestmentId": None,
                "taxTreatment": "fritaksmetoden",
                "bankTransactionId": bank_id,
                "documentId": document_id,
                "documentStatus": "attached",
            },
        ),
        (
            "/api/v1/ledger/shareholder-loans",
            "SHAREHOLDER_LOAN",
            {
                **common,
                "actionId": operation_id,
                "loanDate": "2026-04-15",
                "amount": money("125.50"),
                "direction": "shareholder_to_company",
                "counterpartyName": "Owner",
                "documentStatus": "attached",
                "interestModelled": True,
                "relatedPartySecurity": False,
                "bankTransactionId": bank_id,
                "documentId": document_id,
            },
        ),
        (
            "/api/v1/ledger/tax-settlements",
            "TAX_SETTLEMENT",
            {
                **common,
                "actionId": operation_id,
                "settlementDate": "2026-04-15",
                "amount": money("125.50"),
                "settlementKind": "payment",
                "documentStatus": "attached",
                "bankTransactionId": bank_id,
                "documentId": document_id,
            },
        ),
        (
            "/api/v1/ledger/investment-sales",
            "SHARE_SALE",
            {
                **common,
                "actionId": operation_id,
                "positionId": position_id,
                "saleDate": "2026-04-15",
                "soldShareCount": 5,
                "proceeds": money("125.50"),
                "bankTransactionId": bank_id,
                "documentId": document_id,
                "documentStatus": "attached",
            },
        ),
        (
            "/api/v1/ledger/corporate-decisions/finalizations",
            "OWNER_DIVIDEND_DECLARED",
            {
                **common,
                "decisionId": decision_id,
                "setId": set_id,
                "decisionHash": decision_hash,
                "finalizationId": operation_id,
                "holdingActionId": holding_action_id,
                "ledgerEntryId": str(ENTRY_ID),
            },
        ),
        (
            "/api/v1/ledger/owner-dividends/payments",
            "OWNER_DIVIDEND_PAYMENT",
            {
                **common,
                "decisionId": decision_id,
                "setId": set_id,
                "decisionHash": decision_hash,
                "bankTransactionId": bank_id,
                "holdingActionId": holding_action_id,
                "ledgerEntryId": str(ENTRY_ID),
            },
        ),
    )

    for path, expected_kind, body in cases:
        client, session = client_and_session()
        response = client.post(path, headers=headers(), json=body)

        assert response.status_code == 201, (path, response.text)
        assert response.json() == {
            "postedEntry": {
                "entryId": str(ENTRY_ID),
                "companyId": str(COMPANY_ID),
                "incomeYear": 2026,
                "entryKind": expected_kind,
                "postedAt": "2026-08-27T10:00:00Z",
                "replayed": False,
            },
            "replayed": False,
        }
        posting = next(value for name, value in session.calls if name == "post_entry")
        assert posting["command"].idempotency_key.value == headers()["Idempotency-Key"]
        raw_lines = client.post(path, headers=headers(), json={**body, "lines": []})
        assert raw_lines.status_code == 422, path


def test_annual_close_finalization_has_no_synthetic_ledger_entry() -> None:
    class AnnualCloseSession(LedgerSessionStub):
        async def prepare_corporate_decision_finalization(
            self, command: object
        ) -> dict[str, object]:
            return await self._prepare(
                "corporate_decision_finalization",
                command,
                decisionKind="annual_close",
            )

    session = AnnualCloseSession()
    client = TestClient(create_app(ledger_session_factory=session))
    body = {
        "companyId": str(COMPANY_ID),
        "incomeYear": 2026,
        "decisionId": "70000000-0000-4000-8000-000000000074",
        "setId": "70000000-0000-4000-8000-000000000075",
        "decisionHash": "a" * 64,
        "finalizationId": "70000000-0000-4000-8000-000000000070",
    }

    response = client.post(
        "/api/v1/ledger/corporate-decisions/finalizations",
        headers=headers(),
        json=body,
    )
    incomplete_owner_dividend_ids = client.post(
        "/api/v1/ledger/corporate-decisions/finalizations",
        headers=headers(),
        json={
            **body,
            "holdingActionId": "70000000-0000-4000-8000-000000000076",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json() == {"postedEntry": None, "replayed": False}
    assert not any(name == "post_entry" for name, _value in session.calls)
    assert incomplete_owner_dividend_ids.status_code == 422


def test_opening_snapshot_query_exposes_the_frozen_projection() -> None:
    client, session = client_and_session()
    shareholder_id = "70000000-0000-0000-0000-000000000007"
    session.opening_snapshots = LegacyOpeningSnapshotPage(
        items=(LegacyOpeningSnapshotView(
            setup_id=str(SETUP_ID),
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            bank_balance=Money.nok("45000.00"),
            share_capital=Money.nok("30000.00"),
            share_count=100,
            nominal_value=Money.nok("300.00"),
            locked_at=NOW,
            created_at=Timestamp(datetime(2026, 8, 27, 9, tzinfo=UTC)),
            created_by=ACTOR_ID,
            shareholders=(
                LegacyOpeningShareholderView(
                    shareholder_id=shareholder_id,
                    setup_id=str(SETUP_ID),
                    company_id=COMPANY_ID,
                    name="Owner",
                    shareholder_kind="norwegian_person",
                    national_id="01010112345",
                    org_number=None,
                    share_count=100,
                ),
            ),
        ),),
        next_cursor=LegacyOpeningSnapshotCursor("opaque-opening-next"),
        has_more=True,
    )

    response = client.get(
        f"/api/v1/ledger/opening-snapshots?companyId={COMPANY_ID}&limit=25",
        headers={"Authorization": "Bearer session-token"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [
            {
                "setupId": str(SETUP_ID),
                "companyId": str(COMPANY_ID),
                "incomeYear": 2026,
                "bankBalance": money("45000.00"),
                "shareCapital": money("30000.00"),
                "shareCount": 100,
                "nominalValue": money("300.00"),
                "lockedAt": "2026-08-27T10:00:00Z",
                "createdAt": "2026-08-27T09:00:00Z",
                "createdBy": str(ACTOR_ID.subject),
                "shareholders": [
                    {
                        "shareholderId": shareholder_id,
                        "setupId": str(SETUP_ID),
                        "companyId": str(COMPANY_ID),
                        "name": "Owner",
                        "shareholderKind": "norwegian_person",
                        "nationalId": "01010112345",
                        "orgNumber": None,
                        "shareCount": 100,
                    }
                ],
            }
        ],
        "nextCursor": "opaque-opening-next",
        "hasMore": True,
    }
    call = next(value for name, value in session.calls if name == "list_opening_snapshots")
    assert call["company_ids"] == (COMPANY_ID,)
    assert call["cursor"] is None
    assert call["limit"] == 25


def test_new_year_start_exposes_business_facts_without_raw_ledger_lines() -> None:
    client, session = client_and_session()
    body = {
        "companyId": str(COMPANY_ID),
        "incomeYear": 2026,
        "bankBalance": money("30000.00"),
        "shareCapital": money("30000.00"),
        "shareCount": 100,
        "nominalValue": money("300.00"),
        "shareholders": [
            {
                "name": "Owner",
                "shareholderKind": "norwegian_person",
                "nationalId": "01010112345",
                "orgNumber": None,
                "shareCount": 100,
            }
        ],
    }

    response = client.post(
        "/api/v1/new-year-starts", headers=headers(), json=body
    )

    assert response.status_code == 201, response.text
    assert response.json() == {
        "setupId": str(SETUP_ID),
        "postedEntry": {
            "entryId": str(ENTRY_ID),
            "companyId": str(COMPANY_ID),
            "incomeYear": 2026,
            "entryKind": "OPENING_BALANCE",
            "postedAt": "2026-08-27T10:00:00Z",
            "replayed": False,
        },
    }
    posting = next(
        value for name, value in session.calls
        if name == "rebuild_company_year_opening"
    )
    assert [line.account for line in posting["lines"]] == ["1920", "2000"]
    assert [component.component_kind for component in posting["components"]] == [
        "CLASSIFIED_BALANCE", "CLASSIFIED_BALANCE"
    ]

    raw_lines = client.post(
        "/api/v1/new-year-starts",
        headers=headers(),
        json={**body, "lines": []},
    )
    assert raw_lines.status_code == 422


def test_mutation_requires_bearer_and_idempotency_header() -> None:
    client, session = client_and_session()
    body = manual_body()

    assert client.post(
        "/api/v1/ledger/manual-journals",
        headers={"Idempotency-Key": headers()["Idempotency-Key"]},
        json=body,
    ).status_code == 401
    missing_key = client.post(
        "/api/v1/ledger/manual-journals",
        headers=headers(idempotency=False),
        json=body,
    )
    assert missing_key.status_code == 422
    assert missing_key.headers["content-type"].startswith("application/problem+json")
    assert session.calls == []


def test_invalid_bearer_is_an_authentication_failure_not_ledger_forbidden() -> None:
    client = TestClient(
        create_app(ledger_session_factory=UnauthenticatedSessionFactory())
    )

    response = client.post(
        "/api/v1/ledger/manual-journals",
        headers=headers(),
        json=manual_body(),
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"


def test_money_is_decimal_string_plus_nok_and_unknown_fields_fail() -> None:
    client, session = client_and_session()
    numeric = manual_body()
    numeric["lines"][0]["debit"]["amount"] = 100.0
    unknown = {**manual_body(), "operationId": "30000000-0000-4000-8000-000000000003"}

    first = client.post(
        "/api/v1/ledger/manual-journals", headers=headers(), json=numeric
    )
    second = client.post(
        "/api/v1/ledger/manual-journals", headers=headers(), json=unknown
    )

    assert first.status_code == 422
    assert second.status_code == 422
    assert session.calls == []


def test_malformed_opaque_values_are_reported_as_invalid_input() -> None:
    client, session = client_and_session()
    invalid_key = client.post(
        "/api/v1/ledger/manual-journals",
        headers={**headers(), "Idempotency-Key": "!!!!!!!!!!!!!!!!"},
        json=manual_body(),
    )
    administrative_cost = {
        "companyId": str(COMPANY_ID),
        "incomeYear": 2026,
        "bankTransactionId": "   ",
        "category": "BANK_FEE",
        "payee": "Bank",
        "amount": money("100.00"),
        "paidDate": "2026-08-27",
    }
    invalid_source = client.post(
        "/api/v1/ledger/administrative-costs",
        headers=headers(),
        json=administrative_cost,
    )

    for response in (invalid_key, invalid_source):
        assert response.status_code == 422
        assert response.json()["code"] == "LEDGER_INVALID_INPUT"
        assert response.headers["content-type"].startswith("application/problem+json")
    assert session.calls == []


def test_administrative_cost_success_must_match_the_exact_command_purpose() -> None:
    class AdministrativeSession(LedgerSessionStub):
        def __init__(
            self,
            *,
            company_id: CompanyId = COMPANY_ID,
            income_year: IncomeYear = IncomeYear(2026),
            entry_kind: LedgerEntryKind = LedgerEntryKind.ADMINISTRATIVE_COST,
        ) -> None:
            super().__init__()
            self.company_id = company_id
            self.income_year = income_year
            self.entry_kind = entry_kind

        async def post_entry(self, command: object, **posting: object) -> PostedLedgerEntry:
            self.calls.append(("post_entry", {"command": command, **posting}))
            return PostedLedgerEntry(
                entry_id=ENTRY_ID,
                company_id=self.company_id,
                income_year=self.income_year,
                entry_kind=self.entry_kind,
                posted_at=NOW,
                replayed=False,
            )

    valid = AdministrativeSession()
    valid_response = TestClient(
        create_app(ledger_session_factory=valid)
    ).post(
        "/api/v1/ledger/administrative-costs",
        headers=headers(),
        json=administrative_cost_body(),
    )
    assert valid_response.status_code == 201
    assert valid_response.json()["entryKind"] == "ADMINISTRATIVE_COST"

    inconsistent_results = (
        ("company", AdministrativeSession(
            company_id=CompanyId("10000000-0000-0000-0000-000000000099")
        )),
        ("year", AdministrativeSession(income_year=IncomeYear(2025))),
        ("kind", AdministrativeSession(entry_kind=LedgerEntryKind.MANUAL_JOURNAL)),
    )
    for mismatch, inconsistent in inconsistent_results:
        response = TestClient(
            create_app(ledger_session_factory=inconsistent)
        ).post(
            "/api/v1/ledger/administrative-costs",
            headers=headers(),
            json=administrative_cost_body(),
        )
        assert response.status_code == 503, mismatch
        assert response.json()["code"] == "LEDGER_DEPENDENCY_UNAVAILABLE"


def test_ledger_transport_bounds_queries_and_mutation_text() -> None:
    client, session = client_and_session()
    too_many_companies = "&".join(
        f"companyId={COMPANY_ID}" for _ in range(101)
    )
    oversized_query = client.get(
        f"/api/v1/ledger/entries?{too_many_companies}",
        headers=headers(idempotency=False),
    )
    oversized_cursor = client.get(
        f"/api/v1/ledger/entries?companyId={COMPANY_ID}&cursor={'x' * 4097}",
        headers=headers(idempotency=False),
    )
    oversized_journal = manual_body()
    oversized_journal["memo"] = "x" * 501
    oversized_mutation = client.post(
        "/api/v1/ledger/manual-journals",
        headers=headers(),
        json=oversized_journal,
    )

    assert oversized_query.status_code == 422
    assert oversized_cursor.status_code == 422
    assert oversized_mutation.status_code == 422
    assert session.calls == []


def test_manual_journal_uses_verified_actor_and_python_policy() -> None:
    client, session = client_and_session()
    response = client.post(
        "/api/v1/ledger/manual-journals",
        headers=headers(),
        json=manual_body(),
    )

    assert response.status_code == 201, response.text
    assert response.json() == {
        "entryId": str(ENTRY_ID),
        "companyId": str(COMPANY_ID),
        "incomeYear": 2026,
        "entryKind": "MANUAL_JOURNAL",
        "postedAt": "2026-08-27T10:00:00Z",
        "replayed": False,
    }
    posting = session.calls[0][1]
    assert posting["command"].actor_id == ACTOR_ID
    assert posting["command"].correlation_id.value == "ledger-contract-test"
    assert posting["risk_flags"][0].account == "1800"
    assert session.tokens == ["ledger-token"]


def test_unbalanced_journal_fails_before_persistence() -> None:
    client, session = client_and_session()
    body = manual_body()
    body["lines"][1]["credit"] = money("99.00")
    response = client.post(
        "/api/v1/ledger/manual-journals", headers=headers(), json=body
    )

    assert response.status_code == 422
    assert response.json()["code"] == "LEDGER_ENTRY_UNBALANCED"
    assert session.calls == []


def test_manual_journal_keeps_coded_account_validation_at_the_domain_boundary() -> None:
    client, session = client_and_session()
    body = manual_body()
    body["lines"][0]["account"] = "795"

    response = client.post(
        "/api/v1/ledger/manual-journals", headers=headers(), json=body
    )

    assert response.status_code == 422
    assert response.json()["code"] == "LEDGER_ACCOUNT_INVALID"
    assert session.calls == []


def test_oversized_money_is_a_bounded_validation_error() -> None:
    client, session = client_and_session()
    body = manual_body()
    body["lines"][0]["debit"]["amount"] = "9" * 100

    response = client.post(
        "/api/v1/ledger/manual-journals", headers=headers(), json=body
    )

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_VALIDATION_FAILED"
    assert session.calls == []


def test_ledger_queries_are_authenticated_and_cursor_paginated() -> None:
    client, session = client_and_session()
    response = client.get(
        f"/api/v1/ledger/entries?companyId={COMPANY_ID}&cursor=opaque-current&limit=25",
        headers={
            "Authorization": "Bearer ledger-token",
            "X-Request-ID": "ledger-query-test",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "page": {"nextCursor": "opaque-next", "hasMore": True},
    }
    query = session.calls[0][1]
    assert query["actor_id"] == ACTOR_ID
    assert str(query["cursor"]) == "opaque-current"
    assert query["limit"] == 25


def test_reconstruction_query_exposes_only_backend_derived_readiness() -> None:
    client, session = client_and_session()

    response = client.get(
        f"/api/v1/ledger/reconstruction-assessment?companyId={COMPANY_ID}&incomeYear=2026",
        headers={
            "Authorization": "Bearer ledger-token",
            "X-Request-ID": "ledger-reconstruction-query",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "assessmentId": "41000000-0000-0000-0000-000000000004",
        "companyId": str(COMPANY_ID),
        "incomeYear": 2026,
        "asOf": "2026-08-27",
        "state": "BLOCKED",
        "gapCodes": ["DOCUMENTS_INCOMPLETE"],
        "evidenceDigest": "a" * 64,
        "ledgerStateDigest": "d" * 64,
        "economicFactsDigest": "e" * 64,
        "economicFactCount": 7,
        "sourceEvidenceDigest": "a" * 64,
        "sourceEvidenceCount": 13,
        "recordedAt": "2026-08-27T10:00:00Z",
    }
    query = session.calls[0][1]
    assert query["actor_id"] == ACTOR_ID
    assert query["company_id"] == COMPANY_ID
    assert query["income_year"] == IncomeYear(2026)


def test_historical_reconstruction_exposes_missing_ledger_state_digest_as_null() -> None:
    client, session = client_and_session()
    session.reconstruction_assessment = replace(
        session.reconstruction_assessment,
        ledger_state_digest=None,
        economic_facts_digest=None,
        economic_fact_count=None,
        source_evidence_digest=None,
        source_evidence_count=None,
    )

    response = client.get(
        f"/api/v1/ledger/reconstruction-assessment?companyId={COMPANY_ID}&incomeYear=2026",
        headers={"Authorization": "Bearer ledger-token"},
    )

    assert response.status_code == 200
    assert response.json()["ledgerStateDigest"] is None
    assert response.json()["economicFactsDigest"] is None
    assert response.json()["economicFactCount"] is None
    assert response.json()["sourceEvidenceDigest"] is None
    assert response.json()["sourceEvidenceCount"] is None


def test_company_year_close_query_exposes_current_backend_assessment() -> None:
    client, session = client_and_session()

    response = client.get(
        f"/api/v1/ledger/company-year-close-assessment?companyId={COMPANY_ID}&incomeYear=2026",
        headers={
            "Authorization": "Bearer ledger-token",
            "X-Request-ID": "ledger-company-year-close-query",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "assessmentId": "42000000-0000-0000-0000-000000000004",
        "closeLockId": "43000000-0000-0000-0000-000000000004",
        "reconstructionAssessmentId": "41000000-0000-0000-0000-000000000004",
        "companyId": str(COMPANY_ID),
        "incomeYear": 2026,
        "periodEnd": "2026-12-31",
        "state": "CLOSED",
        "gapCodes": [],
        "evidenceDigest": "b" * 64,
        "ledgerStateDigest": "c" * 64,
        "recordedAt": "2026-08-27T10:00:00Z",
        "replayed": False,
        "isCurrent": True,
    }
    assert session.tokens == ["ledger-token"]
    operation, query = session.calls[0]
    assert operation == "get_company_year_close_assessment"
    assert query["actor_id"] == ACTOR_ID
    assert query["company_id"] == COMPANY_ID
    assert query["income_year"] == IncomeYear(2026)


def test_ledger_entry_source_projection_is_opt_in_during_expand() -> None:
    client, session = client_and_session()
    session.entry_items = (entry_view(),)
    session.entry_next_cursor = None

    legacy_response = client.get(
        f"/api/v1/ledger/entries?companyId={COMPANY_ID}",
        headers=headers(),
    )
    source_response = client.get(
        f"/api/v1/ledger/entries?companyId={COMPANY_ID}&includeSource=true",
        headers=headers(),
    )

    assert legacy_response.status_code == 200
    assert "sourceCapability" not in legacy_response.json()["items"][0]
    assert "sourceRecordId" not in legacy_response.json()["items"][0]
    assert "createdAt" not in legacy_response.json()["items"][0]
    assert legacy_response.json()["items"][0]["warningAcceptedBy"] is None
    assert legacy_response.json()["items"][0]["warningAcceptedAt"] is None
    assert legacy_response.json()["page"] == {"nextCursor": None, "hasMore": False}
    assert source_response.status_code == 200
    assert source_response.json()["items"][0]["sourceCapability"] == "LEDGER"
    assert source_response.json()["items"][0]["sourceRecordId"] == "manual:ledger-api-test"
    assert source_response.json()["items"][0]["createdAt"] == "2026-08-27T10:00:00Z"


def test_source_unaware_database_keeps_legacy_reads_but_blocks_source_queries() -> None:
    client, session = client_and_session()
    session.entry_items = (
        replace(
            entry_view(),
            source_capability=None,
            source_record_id=None,
            created_at=None,
        ),
    )
    session.entry_next_cursor = None

    legacy_response = client.get(
        f"/api/v1/ledger/entries?companyId={COMPANY_ID}",
        headers=headers(),
    )
    source_response = client.get(
        f"/api/v1/ledger/entries?companyId={COMPANY_ID}&includeSource=true",
        headers=headers(),
    )

    assert legacy_response.status_code == 200
    assert "sourceCapability" not in legacy_response.json()["items"][0]
    assert "createdAt" not in legacy_response.json()["items"][0]
    assert source_response.status_code == 503
    assert source_response.json()["code"] == "LEDGER_DEPENDENCY_UNAVAILABLE"
