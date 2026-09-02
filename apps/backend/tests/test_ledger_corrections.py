from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date

import pytest

from talli_backend.modules.ledger.public import (
    AdministrativeCostBlock,
    AdministrativeCostCategory,
    AdministrativeCostCorrectionScope,
    AdministrativeCostCorrectionFacts,
    CorrectHoldingActionCommand,
    LedgerEntryId,
    LedgerError,
    LedgerFactReference,
    LedgerSourceCapability,
    LedgerSourceRecordId,
)
from talli_backend.modules.ledger.service import LedgerService
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


class CorrectionPersistenceStub:
    def __init__(self) -> None:
        self.corrections: list[dict[str, object]] = []

    async def correct_entry(self, command: object, **replacement: object) -> object:
        self.corrections.append({"command": command, **replacement})
        return object()


def source(capability: LedgerSourceCapability, record_id: str) -> LedgerFactReference:
    return LedgerFactReference(
        capability=capability,
        record_id=LedgerSourceRecordId(record_id),
        revision=1,
        fact_sha256="a" * 64,
    )


def correction_command() -> CorrectHoldingActionCommand:
    return CorrectHoldingActionCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ActorId(
            kind=ActorKind.USER,
            subject=UserId("20000000-0000-0000-0000-000000000002"),
        ),
        correlation_id=CorrelationId("guided-correction-test"),
        idempotency_key=IdempotencyKey("guided-correction-test-0001"),
        income_year=IncomeYear(2026),
        event_date=LocalDate(date(2026, 8, 27)),
        original_entry_id=LedgerEntryId("40000000-0000-0000-0000-000000000004"),
        reason="Wrong documented business category",
        primary_source=source(LedgerSourceCapability.DOCUMENTS, "correction-document"),
        corroborating_sources=(source(LedgerSourceCapability.BANKING, "bank-match"),),
        replacement=AdministrativeCostCorrectionFacts(
            category=AdministrativeCostCategory.LEGAL_ADVISORY,
            supplier_name="Advokat AS",
            document_date=LocalDate(date(2026, 8, 20)),
            delivery_date=LocalDate(date(2026, 8, 19)),
            description="Legal advice for the holding company",
            business_purpose="Documented corporate legal advice",
            amount=Money.nok("1250.00"),
            payment_confirmed=True,
            correction_scope=(
                AdministrativeCostCorrectionScope.CURRENT_COMPANY_YEAR
            ),
            blocks=(),
        ),
    )


def test_guided_correction_translates_replacement_without_accepting_lines() -> None:
    persistence = CorrectionPersistenceStub()
    command = correction_command()

    asyncio.run(LedgerService(persistence).correct_holding_action(command))

    lines = persistence.corrections[0]["lines"]
    assert tuple(
        (line.account, format(line.debit.amount, "f"), format(line.credit.amount, "f"))
        for line in lines
    ) == (
        ("6720", "1250.00", "0.00"),
        ("1920", "0.00", "1250.00"),
    )
    forbidden = {"account", "accounts", "line", "lines", "rule_version"}
    assert not (set(CorrectHoldingActionCommand.__dataclass_fields__) & forbidden)


def test_guided_correction_rejects_unapproved_source_topology_before_persistence() -> None:
    persistence = CorrectionPersistenceStub()
    command = replace(
        correction_command(),
        primary_source=source(LedgerSourceCapability.BANKING, "wrong-primary"),
    )

    with pytest.raises(LedgerError) as failure:
        asyncio.run(LedgerService(persistence).correct_holding_action(command))

    assert failure.value.code == "LEDGER_SOURCE_CAPABILITY_MISMATCH"
    assert persistence.corrections == []


def test_guided_correction_rejects_nonpositive_replacement_before_persistence() -> None:
    persistence = CorrectionPersistenceStub()
    command = replace(
        correction_command(),
        replacement=replace(correction_command().replacement, amount=Money.nok("0.00")),
    )

    with pytest.raises(LedgerError) as failure:
        asyncio.run(LedgerService(persistence).correct_holding_action(command))

    assert failure.value.code == "LEDGER_ADMINISTRATIVE_COST_NOT_POSITIVE"
    assert persistence.corrections == []


def test_guided_correction_rejects_event_outside_company_year() -> None:
    persistence = CorrectionPersistenceStub()
    command = replace(
        correction_command(),
        event_date=LocalDate(date(2025, 12, 31)),
    )

    with pytest.raises(LedgerError) as failure:
        asyncio.run(LedgerService(persistence).correct_holding_action(command))

    assert failure.value.code == "LEDGER_INVALID_INPUT"
    assert persistence.corrections == []


@pytest.mark.parametrize(
    "replacement",
    [
        replace(correction_command().replacement, business_purpose=""),
        replace(correction_command().replacement, payment_confirmed=False),
    ],
)
def test_guided_correction_requires_complete_ordinary_cost_evidence(
    replacement: AdministrativeCostCorrectionFacts,
) -> None:
    persistence = CorrectionPersistenceStub()

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).correct_holding_action(
                replace(correction_command(), replacement=replacement)
            )
        )

    assert failure.value.code == "LEDGER_ADMINISTRATIVE_COST_EVIDENCE_INCOMPLETE"
    assert persistence.corrections == []


def test_guided_correction_rejects_explicit_unsupported_cost_characteristic() -> None:
    persistence = CorrectionPersistenceStub()
    replacement = replace(
        correction_command().replacement,
        blocks=(AdministrativeCostBlock.VAT_BEARING_DOCUMENT,),
    )

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).correct_holding_action(
                replace(correction_command(), replacement=replacement)
            )
        )

    assert failure.value.code == "LEDGER_ADMINISTRATIVE_COST_UNSUPPORTED"
    assert persistence.corrections == []


def test_guided_correction_rejects_prior_year_without_frozen_policy() -> None:
    persistence = CorrectionPersistenceStub()
    replacement = replace(
        correction_command().replacement,
        correction_scope=AdministrativeCostCorrectionScope.PRIOR_YEAR_ERROR,
    )

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).correct_holding_action(
                replace(correction_command(), replacement=replacement)
            )
        )

    assert failure.value.code == "LEDGER_PRIOR_YEAR_CORRECTION_POLICY_UNRESOLVED"
    assert persistence.corrections == []
