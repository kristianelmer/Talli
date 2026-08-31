from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date

import pytest

from talli_backend.modules.investments.public import (
    AcquisitionLotId,
    InvestmentActionId,
    InvestmentDocumentStatus,
    InvestmentKind,
    InvestmentsError,
    InvestmentsErrorCode,
    InvestmentPositionId,
    InvestmentSourceReference,
    InvestmentTaxTreatment,
    PreparedReceivedDividend,
    PreparedSharePurchase,
    PreparedShareSale,
    RecordReceivedDividendCommand,
    RecordSharePurchaseCommand,
    RecordShareSaleCommand,
)
from talli_backend.modules.investments.service import InvestmentsService
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    Money,
    UserId,
)


class InvestmentsPersistenceStub:
    def __init__(
        self, prepared: PreparedSharePurchase | PreparedShareSale | PreparedReceivedDividend
    ) -> None:
        self.prepared = prepared
        self.command: RecordSharePurchaseCommand | RecordShareSaleCommand | RecordReceivedDividendCommand | None = None

    async def prepare_share_purchase(
        self, command: RecordSharePurchaseCommand
    ) -> PreparedSharePurchase:
        self.command = command
        assert isinstance(self.prepared, PreparedSharePurchase)
        return self.prepared

    async def prepare_share_sale(
        self, command: RecordShareSaleCommand
    ) -> PreparedShareSale:
        self.command = command
        assert isinstance(self.prepared, PreparedShareSale)
        return self.prepared

    async def prepare_received_dividend(
        self,
        command: RecordReceivedDividendCommand,
        *,
        taxable_add_back: Money,
    ) -> PreparedReceivedDividend:
        self.command = command
        assert isinstance(self.prepared, PreparedReceivedDividend)
        assert taxable_add_back == Money.nok("3.77")
        return self.prepared


def supported_purchase() -> RecordSharePurchaseCommand:
    return RecordSharePurchaseCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ActorId(
            ActorKind.USER,
            UserId("20000000-0000-0000-0000-000000000002"),
        ),
        correlation_id=CorrelationId("investments-supported-purchase"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000003"),
        income_year=IncomeYear(2026),
        action_id=InvestmentActionId("40000000-0000-0000-0000-000000000004"),
        investment_key="  example-as  ",
        investment_name="  Example AS  ",
        investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
        tax_treatment=InvestmentTaxTreatment.EXEMPTION_METHOD,
        acquisition_date=LocalDate(date(2026, 4, 15)),
        share_count=10,
        purchase_amount=Money.nok("125.50"),
        org_number="123456789",
        bank_transaction_id=None,
        document_id=None,
        document_status=InvestmentDocumentStatus.NOT_REQUIRED,
    )


def supported_sale() -> RecordShareSaleCommand:
    return RecordShareSaleCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ActorId(
            ActorKind.USER,
            UserId("20000000-0000-0000-0000-000000000002"),
        ),
        correlation_id=CorrelationId("investments-supported-sale"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000013"),
        income_year=IncomeYear(2026),
        action_id=InvestmentActionId("40000000-0000-0000-0000-000000000014"),
        position_id=InvestmentPositionId(
            "50000000-0000-0000-0000-000000000015"
        ),
        sale_date=LocalDate(date(2026, 6, 1)),
        sold_share_count=4,
        proceeds=Money.nok("75.00"),
        bank_transaction_id=None,
        document_id=None,
        document_status=InvestmentDocumentStatus.NOT_REQUIRED,
    )


def supported_received_dividend() -> RecordReceivedDividendCommand:
    return RecordReceivedDividendCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ActorId(
            ActorKind.USER,
            UserId("20000000-0000-0000-0000-000000000002"),
        ),
        correlation_id=CorrelationId("investments-supported-dividend"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000023"),
        income_year=IncomeYear(2026),
        action_id=InvestmentActionId("40000000-0000-0000-0000-000000000024"),
        position_id=InvestmentPositionId(
            "50000000-0000-0000-0000-000000000025"
        ),
        paying_company_name="  Example AS  ",
        declared_date=LocalDate(date(2026, 4, 1)),
        paid_date=LocalDate(date(2026, 4, 15)),
        gross_amount=Money.nok("125.50"),
        tax_treatment=InvestmentTaxTreatment.EXEMPTION_METHOD,
        bank_transaction_id=None,
        document_id=None,
        document_status=InvestmentDocumentStatus.NOT_REQUIRED,
    )


def test_supported_received_dividend_is_normalized_and_taxed_by_investments() -> None:
    prepared = PreparedReceivedDividend(
        position_id=supported_received_dividend().position_id,
        investment_name="Example AS",
        paying_company_name="Example AS",
        taxable_add_back=Money.nok("3.77"),
    )
    persistence = InvestmentsPersistenceStub(prepared)

    result = asyncio.run(
        InvestmentsService(persistence).prepare_received_dividend(
            supported_received_dividend()
        )
    )

    assert result == prepared
    assert persistence.command is not None
    assert persistence.command.paying_company_name == "Example AS"


@pytest.mark.parametrize(
    "changes",
    [
        {"paying_company_name": "  "},
        {"gross_amount": Money.nok("0")},
        {"declared_date": LocalDate(date(2025, 12, 31))},
        {"paid_date": LocalDate(date(2025, 12, 31))},
        {"tax_treatment": "outside_fritaksmetoden"},
        {"document_status": "unknown"},
        {"document_status": InvestmentDocumentStatus.ATTACHED},
        {
            "bank_transaction_id": InvestmentSourceReference(
                "70000000-0000-0000-0000-000000000007"
            )
        },
        {
            "document_id": InvestmentSourceReference(
                "80000000-0000-0000-0000-000000000008"
            )
        },
    ],
)
def test_invalid_received_dividend_facts_fail_before_persistence(
    changes: dict[str, object],
) -> None:
    persistence = InvestmentsPersistenceStub(
        PreparedReceivedDividend(
            position_id=supported_received_dividend().position_id,
            investment_name="Example AS",
            paying_company_name="Example AS",
            taxable_add_back=Money.nok("3.77"),
        )
    )

    with pytest.raises(InvestmentsError) as failure:
        asyncio.run(
            InvestmentsService(persistence).prepare_received_dividend(
                replace(supported_received_dividend(), **changes)
            )
        )

    assert failure.value.code == InvestmentsErrorCode.INVALID_INPUT.value
    assert persistence.command is None


def test_supported_share_sale_is_prepared_through_investments_interface() -> None:
    prepared = PreparedShareSale(
        position_id=InvestmentPositionId(
            "50000000-0000-0000-0000-000000000015"
        ),
        investment_name="Example AS",
        fifo_cost_basis_reduction=Money.nok("50.20"),
    )
    persistence = InvestmentsPersistenceStub(prepared)

    result = asyncio.run(
        InvestmentsService(persistence).prepare_share_sale(supported_sale())
    )

    assert result == prepared
    assert persistence.command == supported_sale()


@pytest.mark.parametrize(
    "changes",
    [
        {"sold_share_count": 0},
        {"sold_share_count": 1.5},
        {"proceeds": Money.nok("0")},
        {"sale_date": LocalDate(date(2025, 12, 31))},
        {"document_status": "unknown"},
        {"document_status": InvestmentDocumentStatus.ATTACHED},
        {
            "bank_transaction_id": InvestmentSourceReference(
                "70000000-0000-0000-0000-000000000007"
            )
        },
        {
            "document_id": InvestmentSourceReference(
                "80000000-0000-0000-0000-000000000008"
            )
        },
    ],
)
def test_invalid_share_sale_facts_fail_before_persistence(
    changes: dict[str, object],
) -> None:
    persistence = InvestmentsPersistenceStub(
        PreparedShareSale(
            position_id=supported_sale().position_id,
            investment_name="Example AS",
            fifo_cost_basis_reduction=Money.nok("50.20"),
        )
    )

    with pytest.raises(InvestmentsError) as failure:
        asyncio.run(
            InvestmentsService(persistence).prepare_share_sale(
                replace(supported_sale(), **changes)
            )
        )

    assert failure.value.code == InvestmentsErrorCode.INVALID_INPUT.value
    assert persistence.command is None


def test_supported_share_purchase_is_normalized_and_prepared() -> None:
    prepared = PreparedSharePurchase(
        position_id=InvestmentPositionId("50000000-0000-0000-0000-000000000005"),
        lot_id=AcquisitionLotId("60000000-0000-0000-0000-000000000006"),
        position_created=True,
        investment_name="Example AS",
        purchase_amount=Money.nok("125.50"),
    )
    persistence = InvestmentsPersistenceStub(prepared)

    result = asyncio.run(
        InvestmentsService(persistence).prepare_share_purchase(supported_purchase())
    )

    assert result == prepared
    assert persistence.command is not None
    assert persistence.command.investment_key == "example-as"
    assert persistence.command.investment_name == "Example AS"


def test_non_positive_share_quantity_fails_before_persistence() -> None:
    prepared = PreparedSharePurchase(
        position_id=InvestmentPositionId("50000000-0000-0000-0000-000000000005"),
        lot_id=AcquisitionLotId("60000000-0000-0000-0000-000000000006"),
        position_created=True,
        investment_name="Example AS",
        purchase_amount=Money.nok("125.50"),
    )
    persistence = InvestmentsPersistenceStub(prepared)

    with pytest.raises(InvestmentsError) as failure:
        asyncio.run(
            InvestmentsService(persistence).prepare_share_purchase(
                replace(supported_purchase(), share_count=0)
            )
        )

    assert failure.value.code == InvestmentsErrorCode.INVALID_INPUT.value
    assert persistence.command is None


@pytest.mark.parametrize(
    "changes",
    [
        {"share_count": 1.5},
        {"purchase_amount": Money.nok("0")},
        {"acquisition_date": LocalDate(date(2025, 12, 31))},
        {"investment_key": "  "},
        {"investment_name": "  "},
        {"investment_kind": "simple_listed_security"},
        {"tax_treatment": "needs_accountant"},
        {"org_number": "123"},
        {"document_status": "unknown"},
        {"document_status": InvestmentDocumentStatus.ATTACHED},
        {
            "bank_transaction_id": InvestmentSourceReference(
                "70000000-0000-0000-0000-000000000007"
            )
        },
        {
            "document_id": InvestmentSourceReference(
                "80000000-0000-0000-0000-000000000008"
            )
        },
    ],
)
def test_invalid_share_purchase_facts_fail_before_persistence(
    changes: dict[str, object],
) -> None:
    prepared = PreparedSharePurchase(
        position_id=InvestmentPositionId("50000000-0000-0000-0000-000000000005"),
        lot_id=AcquisitionLotId("60000000-0000-0000-0000-000000000006"),
        position_created=True,
        investment_name="Example AS",
        purchase_amount=Money.nok("125.50"),
    )
    persistence = InvestmentsPersistenceStub(prepared)

    with pytest.raises(InvestmentsError) as failure:
        asyncio.run(
            InvestmentsService(persistence).prepare_share_purchase(
                replace(supported_purchase(), **changes)
            )
        )

    assert failure.value.code == InvestmentsErrorCode.INVALID_INPUT.value
    assert persistence.command is None
