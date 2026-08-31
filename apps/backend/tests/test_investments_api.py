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
    InvestmentActivityKind,
    InvestmentActivityPage,
    InvestmentActivityView,
    InvestmentDocumentStatus,
    InvestmentLotHistoryStatus,
    InvestmentPositionPage,
    InvestmentPositionId,
    InvestmentPositionView,
    InvestmentTaxTreatment,
    PreparedReceivedDividend,
    RecordedReceivedDividend,
    RecordedSharePurchase,
    PreparedSharePurchase,
    PreparedShareSale,
    RecordedShareSale,
    ShareSaleAllocationId,
    ShareSaleAllocationPage,
    ShareSaleAllocationView,
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

    async def get_share_sale_replay(self, command):
        return None

    async def prepare_share_sale(self, command):
        self.commands.append(command)
        return PreparedShareSale(
            position_id=command.position_id,
            investment_name="Example AS",
            fifo_cost_basis_reduction=Money.nok("50.20"),
        )

    async def complete_share_sale(self, command, *, accounting_entry_id):
        return RecordedShareSale(
            action_id=command.action_id,
            position_id=command.position_id,
            accounting_entry_id=accounting_entry_id,
            replayed=False,
        )

    async def get_received_dividend_replay(self, command):
        return None

    async def prepare_received_dividend(self, command, *, taxable_add_back):
        self.commands.append(command)
        return PreparedReceivedDividend(
            position_id=command.position_id,
            investment_name="Example AS",
            paying_company_name=command.paying_company_name,
            taxable_add_back=taxable_add_back,
        )

    async def complete_received_dividend(
        self, command, *, prepared, accounting_entry_id
    ):
        return RecordedReceivedDividend(
            action_id=command.action_id,
            position_id=command.position_id,
            accounting_entry_id=accounting_entry_id,
            taxable_add_back=prepared.taxable_add_back,
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
                movement_count=1,
                movements=({"movement_type": "purchase"},),
                created_by=self.actor_id,
                created_at=Timestamp(datetime(2026, 4, 15, tzinfo=UTC)),
                updated_at=Timestamp(datetime(2026, 4, 15, tzinfo=UTC)),
            ),),
            next_cursor=None,
            has_more=False,
        )

    async def list_activity(self, **_query):
        return InvestmentActivityPage(
            items=(InvestmentActivityView(
                activity_id=supported_purchase().action_id,
                company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
                income_year=IncomeYear(2026),
                activity_kind=InvestmentActivityKind.DIVIDEND_RECEIVED,
                action_date=LocalDate(datetime(2026, 4, 15, tzinfo=UTC).date()),
                position_id=InvestmentPositionId("50000000-0000-0000-0000-000000000005"),
                investment_key="example-as",
                investment_name="Example AS",
                investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
                tax_treatment=InvestmentTaxTreatment.EXEMPTION_METHOD,
                org_number="123456789",
                acquisition_lot_id=None,
                share_count=None,
                purchase_amount=None,
                sold_share_count=None,
                proceeds=None,
                fifo_cost_basis_reduction=None,
                remaining_share_count=None,
                remaining_cost_basis=None,
                paying_company_name="Example AS",
                declared_date=LocalDate(datetime(2026, 4, 1, tzinfo=UTC).date()),
                gross_amount=Money.nok("125.50"),
                taxable_add_back=Money.nok("3.77"),
                gain_or_loss=None,
                bank_transaction_id=None,
                document_id=None,
                document_status=InvestmentDocumentStatus.NOT_REQUIRED,
                accounting_entry_id=AccountingEntryReference(
                    "70000000-0000-0000-0000-000000000007"
                ),
                created_by=self.actor_id,
                created_at=Timestamp(datetime(2026, 4, 15, tzinfo=UTC)),
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

    async def list_share_sale_allocations(self, **_query):
        return ShareSaleAllocationPage(
            items=(ShareSaleAllocationView(
                allocation_id=ShareSaleAllocationId(
                    "80000000-0000-0000-0000-000000000008"
                ),
                company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
                position_id=InvestmentPositionId(
                    "50000000-0000-0000-0000-000000000005"
                ),
                lot_id=AcquisitionLotId(
                    "60000000-0000-0000-0000-000000000006"
                ),
                sale_action_id=supported_purchase().action_id,
                allocation_order=1,
                acquisition_date=LocalDate(
                    datetime(2026, 4, 15, tzinfo=UTC).date()
                ),
                allocated_share_count=4,
                allocated_cost_basis=Money.nok("50.20"),
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


def test_supported_share_sale_uses_investments_http_contract() -> None:
    sessions = InvestmentsSessionStub()
    client = TestClient(create_app(investments_session_factory=sessions))

    response = client.post(
        "/api/v1/investments/share-sales",
        headers={
            "Authorization": "Bearer owner-token",
            "Idempotency-Key": "30000000-0000-4000-8000-000000000013",
            "X-Request-ID": "investments-supported-sale",
        },
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "incomeYear": 2026,
            "actionId": "40000000-0000-0000-0000-000000000014",
            "positionId": "50000000-0000-0000-0000-000000000015",
            "saleDate": "2026-06-01",
            "soldShareCount": 4,
            "proceeds": {"amount": "75.00", "currency": "NOK"},
            "bankTransactionId": None,
            "documentId": None,
            "documentStatus": "not_required",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json() == {
        "actionId": "40000000-0000-0000-0000-000000000014",
        "positionId": "50000000-0000-0000-0000-000000000015",
        "accountingEntryId": "70000000-0000-0000-0000-000000000007",
        "replayed": False,
    }
    assert sessions.tokens == ["owner-token"]
    assert len(sessions.commands) == 1
    assert sessions.commands[0].sold_share_count == 4


def test_supported_received_dividend_uses_investments_http_contract() -> None:
    sessions = InvestmentsSessionStub()
    client = TestClient(create_app(investments_session_factory=sessions))

    response = client.post(
        "/api/v1/investments/received-dividends",
        headers={
            "Authorization": "Bearer owner-token",
            "Idempotency-Key": "30000000-0000-4000-8000-000000000023",
            "X-Request-ID": "investments-supported-dividend",
        },
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "incomeYear": 2026,
            "actionId": "40000000-0000-0000-0000-000000000024",
            "positionId": "50000000-0000-0000-0000-000000000025",
            "payingCompanyName": "Example AS",
            "declaredDate": "2026-04-01",
            "paidDate": "2026-04-15",
            "grossAmount": {"amount": "125.50", "currency": "NOK"},
            "taxTreatment": "fritaksmetoden",
            "bankTransactionId": None,
            "documentId": None,
            "documentStatus": "not_required",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json() == {
        "actionId": "40000000-0000-0000-0000-000000000024",
        "positionId": "50000000-0000-0000-0000-000000000025",
        "accountingEntryId": "70000000-0000-0000-0000-000000000007",
        "taxableAddBack": {"amount": "3.77", "currency": "NOK"},
        "replayed": False,
    }
    assert sessions.tokens == ["owner-token"]
    assert len(sessions.commands) == 1
    assert sessions.commands[0].paying_company_name == "Example AS"


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
    allocations = client.get(
        "/api/v1/investments/share-sale-allocations?companyId=10000000-0000-0000-0000-000000000001",
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
    assert allocations.status_code == 200, allocations.text
    assert allocations.json()["items"][0]["allocatedCostBasis"] == {
        "amount": "50.20", "currency": "NOK"
    }
    activity = client.get(
        "/api/v1/investments/activity?companyId=10000000-0000-0000-0000-000000000001",
        headers=headers,
    )
    assert activity.status_code == 200, activity.text
    assert activity.json()["items"][0]["activityKind"] == "dividend_received"
    assert activity.json()["items"][0]["taxableAddBack"] == {
        "amount": "3.77", "currency": "NOK"
    }
