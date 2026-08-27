from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from talli_backend.main import create_app
from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.modules.ledger.public import (
    LedgerCursor,
    LedgerEntryId,
    LedgerEntryKind,
    LedgerEntryPage,
    LedgerPage,
    LedgerSourceRecordId,
    PeriodLock,
    PeriodLockId,
    PeriodLockPage,
    PostedLedgerEntry,
)
from talli_backend.modules.shareholder_register_filing.public import OpeningSnapshotId
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    IncomeYear,
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
        return None

    async def record_legacy_opening_snapshot(
        self, command: object, *, ledger_bank_balance: object
    ) -> OpeningSnapshotId:
        self.calls.append(
            ("record_legacy_opening_snapshot", {"command": command, "bank": ledger_bank_balance})
        )
        return SETUP_ID

    async def complete_workflow(
        self,
        *,
        operation_name: str,
        command: object,
        result: dict[str, object],
    ) -> None:
        self.calls.append(
            ("complete_workflow", {"operation": operation_name, "result": result})
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
            items=(),
            page=LedgerPage(next_cursor=LedgerCursor("opaque-next"), has_more=True),
        )

    async def list_period_locks(self, **query: object) -> PeriodLockPage:
        self.calls.append(("list_period_locks", query))
        return PeriodLockPage(
            items=(),
            page=LedgerPage(next_cursor=None, has_more=False),
        )


def client_and_session() -> tuple[TestClient, LedgerSessionStub]:
    session = LedgerSessionStub()
    return TestClient(create_app(ledger_session_factory=session)), session


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
        "ledgerPostManualJournal",
        "ledgerStartNewYear",
    } <= operations
    assert not {
        "ledgerPostBankSuggestionOutcome",
        "ledgerPostInvestmentDividend",
        "ledgerPostInvestmentPurchase",
        "ledgerPostInvestmentSale",
        "ledgerPostOwnerDividendDeclared",
        "ledgerPostOwnerDividendPayment",
        "ledgerPostShareholderLoan",
        "ledgerPostStructuredEntry",
        "ledgerPostTaxSettlement",
    } & operations
    assert not {
        "/api/v1/ledger/bank-suggestion-outcomes",
        "/api/v1/ledger/investment-dividends",
        "/api/v1/ledger/investment-purchases",
        "/api/v1/ledger/investment-sales",
        "/api/v1/ledger/owner-dividends/declared",
        "/api/v1/ledger/owner-dividends/payments",
        "/api/v1/ledger/opening-balances",
        "/api/v1/ledger/shareholder-loans",
        "/api/v1/ledger/structured-entries",
        "/api/v1/ledger/tax-settlements",
    } & client.app.openapi()["paths"].keys()


def test_new_year_start_exposes_business_facts_without_raw_ledger_lines() -> None:
    client, session = client_and_session()
    body = {
        "companyId": str(COMPANY_ID),
        "incomeYear": 2026,
        "bankBalance": money("45000.00"),
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
    posting = next(value for name, value in session.calls if name == "post_entry")
    assert posting["source_record_id"] == LedgerSourceRecordId(
        f"opening-setup:{SETUP_ID}"
    )
    assert [line.account for line in posting["lines"]] == ["1920", "2000", "2050"]

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
