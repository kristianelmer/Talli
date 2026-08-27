from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from talli_backend.application.shareholder_register_compatibility import (
    LegacyShareholderRegisterFilingFacade,
)
from talli_backend.modules.shareholder_register_filing.public import (
    OpeningShareholder,
    OpeningSnapshotId,
    RecordOpeningSnapshotCommand,
    ShareholderRegisterFilingError,
)
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    Money,
    UserId,
)


ACTOR = ActorId(
    kind=ActorKind.USER,
    subject=UserId("20000000-0000-0000-0000-000000000002"),
)


def command() -> RecordOpeningSnapshotCommand:
    return RecordOpeningSnapshotCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ACTOR,
        correlation_id=CorrelationId("shareholder-register-contract"),
        idempotency_key=IdempotencyKey(
            "50000000-0000-4000-8000-000000000005"
        ),
        income_year=IncomeYear(2026),
        share_capital=Money.nok("30000"),
        share_count=100,
        nominal_value=Money.nok("300"),
        shareholders=(
            OpeningShareholder(
                name="Owner",
                shareholder_kind="norwegian_person",
                national_id="01010112345",
                org_number=None,
                share_count=100,
            ),
        ),
    )


def test_frozen_opening_snapshot_is_reached_only_through_the_public_contract() -> None:
    class Persistence:
        actor_id = ACTOR
        seen = None

        async def record_legacy_opening_snapshot(
            self, value, *, ledger_bank_balance
        ):
            self.seen = value
            assert ledger_bank_balance == Money.nok("45000")
            return OpeningSnapshotId("60000000-0000-0000-0000-000000000006")

    persistence = Persistence()
    result = asyncio.run(
        LegacyShareholderRegisterFilingFacade(
            persistence,
            Money.nok("45000"),
        )
        .record_opening_snapshot(command())
    )

    assert persistence.seen == command()
    assert str(result) == "60000000-0000-0000-0000-000000000006"


def test_opening_snapshot_rejects_cross_contract_inconsistency() -> None:
    with pytest.raises(ShareholderRegisterFilingError) as raised:
        replace(command(), share_count=99)
    assert raised.value.code == "SHAREHOLDER_REGISTER_FILING_INVALID_INPUT"


def test_frozen_contract_allows_both_identifiers_and_owns_no_bank_fact() -> None:
    shareholder = OpeningShareholder(
        name="Owner",
        shareholder_kind="norwegian_person",
        national_id="01010112345",
        org_number="999999999",
        share_count=100,
    )

    both_identifiers = replace(command(), shareholders=(shareholder,))

    assert both_identifiers.shareholders[0].org_number == "999999999"
    assert not hasattr(both_identifiers, "bank_balance")
