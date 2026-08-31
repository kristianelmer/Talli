from __future__ import annotations

from fastapi.testclient import TestClient

from talli_backend.main import create_app
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from talli_backend.modules.investments.public import (
    AccountingEntryReference,
    AcquisitionLotPage,
    AcquisitionLotId,
    AcquisitionLotView,
    InvestmentKind,
    InvestmentLotHistoryStatus,
    InvestmentPositionPage,
    InvestmentPositionId,
    InvestmentPositionView,
    InvestmentTaxTreatment,
    RecordedSharePurchase,
    PreparedSharePurchase,
)
from talli_backend.modules.ledger.public import LedgerEntryId, LedgerEntryKind, PostedLedgerEntry
from talli_backend.shared.kernel import CompanyId, IncomeYear, LocalDate, Money, Timestamp

from test_investments import supported_purchase


class InvestmentsSessionStub:
    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.commands: list[object] = []

    @property
    def actor_id(self):
        return supported_purchase().actor_id

    async def session(self, access_token: str):
        self.tokens.append(access_token)
        return self

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def get_share_purchase_replay(self, command):
        return None

    async def prepare_share_purchase(self, command):
        self.commands.append(command)
        return PreparedSharePurchase(
            position_id=InvestmentPositionId(
                "50000000-0000-0000-0000-000000000005"
            ),
            lot_id=AcquisitionLotId("60000000-0000-0000-0000-000000000006"),
            position_created=True,
            investment_name=command.investment_name,
            purchase_amount=Money.nok("125.50"),
        )

    async def post_entry(self, command, **_facts):
        return PostedLedgerEntry(
            entry_id=LedgerEntryId("70000000-0000-0000-0000-000000000007"),
            company_id=command.company_id,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.SHARE_PURCHASE,
            posted_at=Timestamp(datetime(2026, 8, 31, tzinfo=UTC)),
            replayed=False,
        )

    async def complete_share_purchase(
        self, command, *, prepared, accounting_entry_id
    ):
        return RecordedSharePurchase(
            action_id=command.action_id,
            position_id=prepared.position_id,
            lot_id=prepared.lot_id,
            accounting_entry_id=accounting_entry_id,
            position_created=True,
            replayed=False,
        )

    async def list_positions(self, **_query):
        return InvestmentPositionPage(
            items=(InvestmentPositionView(
                position_id=InvestmentPositionId("50000000-0000-0000-0000-000000000005"),
                company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
                investment_key="example-as", name="Example AS",
                kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
                tax_treatment=InvestmentTaxTreatment.EXEMPTION_METHOD,
                org_number="123456789", share_count=10,
                cost_basis=Money.nok("125.50"),
                lot_history_status=InvestmentLotHistoryStatus.COMPLETE,
                movement_count=1, created_by=self.actor_id,
                created_at=Timestamp(datetime(2026, 4, 15, tzinfo=UTC)),
                updated_at=Timestamp(datetime(2026, 4, 15, tzinfo=UTC)),
            ),),
            next_cursor=None,
            has_more=False,
        )

    async def list_acquisition_lots(self, **_query):
        return AcquisitionLotPage(
            items=(AcquisitionLotView(
                lot_id=AcquisitionLotId("60000000-0000-0000-0000-000000000006"),
                company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
                position_id=InvestmentPositionId("50000000-0000-0000-0000-000000000005"),
                acquisition_action_id=supported_purchase().action_id,
                acquisition_date=LocalDate(datetime(2026, 4, 15, tzinfo=UTC).date()),
                original_share_count=10, remaining_share_count=10,
                original_cost_basis=Money.nok("125.50"),
                remaining_cost_basis=Money.nok("125.50"),
                created_by=self.actor_id,
                created_at=Timestamp(datetime(2026, 4, 15, tzinfo=UTC)),
            ),),
            next_cursor=None,
            has_more=False,
        )


def test_supported_share_purchase_uses_investments_http_contract() -> None:
    sessions = InvestmentsSessionStub()
    client = TestClient(create_app(investments_session_factory=sessions))
    command = supported_purchase()

    response = client.post(
        "/api/v1/investments/share-purchases",
        headers={
            "Authorization": "Bearer owner-token",
            "Idempotency-Key": str(command.idempotency_key),
            "X-Request-ID": str(command.correlation_id),
        },
        json={
            "companyId": str(command.company_id),
            "incomeYear": int(command.income_year),
            "actionId": str(command.action_id),
            "investmentKey": "example-as",
            "investmentName": "Example AS",
            "investmentKind": "norwegian_private_company",
            "taxTreatment": "fritaksmetoden",
            "acquisitionDate": "2026-04-15",
            "shareCount": 10,
            "purchaseAmount": {"amount": "125.50", "currency": "NOK"},
            "orgNumber": "123456789",
            "bankTransactionId": None,
            "documentId": None,
            "documentStatus": "not_required",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json() == {
        "actionId": str(command.action_id),
        "positionId": "50000000-0000-0000-0000-000000000005",
        "acquisitionLotId": "60000000-0000-0000-0000-000000000006",
        "accountingEntryId": "70000000-0000-0000-0000-000000000007",
        "positionCreated": True,
        "replayed": False,
    }
    assert sessions.tokens == ["owner-token"]
    assert len(sessions.commands) == 1
    assert sessions.commands[0].investment_name == "Example AS"


def test_previous_web_revision_uses_hidden_overlap_alias() -> None:
    sessions = InvestmentsSessionStub()
    client = TestClient(create_app(investments_session_factory=sessions))
    command = supported_purchase()

    response = client.post(
        "/api/v1/ledger/investment-purchases",
        headers={
            "Authorization": "Bearer owner-token",
            "Idempotency-Key": str(command.idempotency_key),
            "X-Request-ID": str(command.correlation_id),
        },
        json={
            "companyId": str(command.company_id),
            "incomeYear": int(command.income_year),
            "actionId": str(command.action_id),
            "investmentKey": "example-as",
            "investmentName": "Example AS",
            "investmentKind": "norwegian_private_company",
            "taxTreatment": "fritaksmetoden",
            "acquisitionDate": "2026-04-15",
            "shareCount": 10,
            "purchaseAmount": {"amount": "125.50", "currency": "NOK"},
            "orgNumber": "123456789",
            "bankTransactionId": None,
            "documentId": None,
            "documentStatus": "not_required",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json() == {"postedEntry": None, "replayed": False}
    assert "/api/v1/ledger/investment-purchases" not in client.app.openapi()["paths"]
    assert len(sessions.commands) == 1


def test_positions_and_lots_use_investments_query_contract() -> None:
    sessions = InvestmentsSessionStub()
    client = TestClient(create_app(investments_session_factory=sessions))
    headers = {"Authorization": "Bearer owner-token"}

    positions = client.get(
        "/api/v1/investments/positions?companyId=10000000-0000-0000-0000-000000000001",
        headers=headers,
    )
    lots = client.get(
        "/api/v1/investments/acquisition-lots?companyId=10000000-0000-0000-0000-000000000001",
        headers=headers,
    )

    assert positions.status_code == 200, positions.text
    assert positions.json()["items"][0]["movementCount"] == 1
    assert positions.json()["items"][0]["costBasis"] == {
        "amount": "125.50", "currency": "NOK"
    }
    assert lots.status_code == 200, lots.text
    assert lots.json()["items"][0]["acquisitionActionId"] == str(
        supported_purchase().action_id
    )
