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
    PreparedSharePurchase,
    RecordSharePurchaseCommand,
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
    def __init__(self, prepared: PreparedSharePurchase) -> None:
        self.prepared = prepared
        self.command: RecordSharePurchaseCommand | None = None

    async def prepare_share_purchase(
        self, command: RecordSharePurchaseCommand
    ) -> PreparedSharePurchase:
        self.command = command
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
