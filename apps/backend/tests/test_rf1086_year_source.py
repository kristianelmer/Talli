"""Behavioral tests for RF's new source API; no persistence/provider dependencies.

The public source API has no application persistence binding yet. No private
helper is called here.
"""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from pathlib import Path
from uuid import UUID

import pytest

from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId
from talli_backend.modules.shareholder_register_filing.public import parse_rf1086_case
from talli_backend.modules.shareholder_register_filing.public import (
    RecordRf1086YearSource, Rf1086PaidInSourceFacts, Rf1086VerifiedYearSourceContext,
    Rf1086YearDocumentEvidence, Rf1086YearEventEvidence, Rf1086YearGovernanceReceipt,
    Rf1086YearSourceError, Rf1086YearSourceId, assert_rf1086_year_source_fresh,
    prepare_rf1086_year_source, rf1086_governance_economic_facts, rf1086_year_source_digest,
)

ROOT = Path(__file__).resolve().parents[3]
COMPANY = CompanyId(str(UUID(int=1)))
ACTOR = ActorId(ActorKind.USER, UserId(str(UUID(int=2))))
YEAR = IncomeYear(2025)
SOURCE = Rf1086YearSourceId(str(UUID(int=3)))
NOW = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
DOCUMENT = str(UUID(int=4))
RECEIPT = str(UUID(int=5))
REGISTER = str(UUID(int=6))


def basis(kind="no_activity"):
    raw = json.loads((ROOT / "tests/fixtures/rf1086/no_activity.json").read_text())
    raw["share_snapshot"].update(previous_paid_in_premium=2000, current_paid_in_premium=2000)
    if kind == "dividend":
        raw["events"] = [{"type": "dividend", "timestamp": "2025-06-01T12:00:00",
            "total_amount": 1000, "per_share_amount": 10,
            "allocations": [{"shareholder_id": "owner", "amount": 1000, "share_count_basis": 100}]}]
    elif kind == "cash_issue":
        raw["events"] = [{"type": "cash_issue", "timestamp": "2025-06-01T12:00:00",
            "registration_confirmed": True, "issued_share_count": 100, "share_count_after": 200,
            "nominal_value": 300, "premium": 5,
            "allocations": [{"shareholder_id": "owner", "share_count": 100, "acquisition_value": 30500}]}]
        raw["share_snapshot"].update(current_share_capital=60000, current_paid_in_share_capital=60000,
            current_share_count=200, current_paid_in_premium=2500)
        raw["shareholder_snapshots"][0]["current_share_count"] = 200
    case = parse_rf1086_case(raw)
    shares = case.share_snapshot
    paid_in = Rf1086PaidInSourceFacts(shares.previous_paid_in_share_capital, shares.current_paid_in_share_capital,
        shares.previous_paid_in_premium, shares.current_paid_in_premium)
    doc = Rf1086YearDocumentEvidence(DOCUMENT, COMPANY, "a" * 64, "a" * 64, "shareholder_source", "stored", 100, NOW, "e" * 64, IncomeYear(2024))
    evidence = () if not case.events else (Rf1086YearEventEvidence(0, rf1086_year_source_digest(case.events[0]), (DOCUMENT,), RECEIPT),)
    receipts = () if not case.events else (Rf1086YearGovernanceReceipt(RECEIPT, COMPANY, YEAR, kind,
        rf1086_year_source_digest(rf1086_governance_economic_facts(case.events[0])), "b" * 64, (doc.content_sha256,), True,
        REGISTER if kind == "cash_issue" else None, "c" * 64 if kind == "cash_issue" else None),)
    command = RecordRf1086YearSource(COMPANY, ACTOR, YEAR, case, paid_in, (doc,), (DOCUMENT,), (DOCUMENT,),
        (DOCUMENT,), evidence, True, True, True, kind == "no_activity")
    context = Rf1086VerifiedYearSourceContext(ACTOR, True, COMPANY, YEAR, case.company, "d" * 64,
        (doc,), receipts, True, rf1086_year_source_digest(receipts))
    return command, context


def prepare(command, context, **kwargs):
    return prepare_rf1086_year_source(command, context=context, source_id=kwargs.pop("source_id", SOURCE),
        confirmed_at=kwargs.pop("confirmed_at", NOW), **kwargs)


def test_no_activity_requires_explicit_tax_paid_in_and_prior_year_evidence_is_valid():
    command, context = basis()
    source = prepare(command, context)
    assert source.version == 1 and source.command.paid_in.opening_premium == Decimal("2000")
    assert source.command.documents[0].source_income_year == IncomeYear(2024)
    assert source.source_sha256 != source.case_sha256
    assert_rf1086_year_source_fresh(source, current_source_id=SOURCE,
        current_source_sha256=source.source_sha256, context=context)


@pytest.mark.parametrize("field", ["identities_reviewed", "complete_year_confirmed", "paid_in_reviewed", "no_activity_confirmed"])
def test_missing_owner_confirmation_blocks_capture(field):
    command, context = basis()
    with pytest.raises(Rf1086YearSourceError):
        prepare(replace(command, **{field: False}), context)


def test_paid_in_capital_cannot_be_inferred_or_silently_replaced():
    command, context = basis()
    with pytest.raises(Rf1086YearSourceError, match="paid_in_mismatch"):
        prepare(replace(command, paid_in=replace(command.paid_in, opening_premium=Decimal(0))), context)
    with pytest.raises(Rf1086YearSourceError, match="paid_in_required"):
        prepare(replace(command, paid_in=None), context)


@pytest.mark.parametrize("kind", ["dividend", "cash_issue"])
def test_final_governance_receipt_and_signed_evidence_corroborate_event(kind):
    command, context = basis(kind)
    source = prepare(command, context)
    assert source.governance_receipts[0].receipt_id == RECEIPT
    assert source.command.event_evidence[0].event_sha256 == rf1086_year_source_digest(command.case.events[0])


@pytest.mark.parametrize("change", ["inactive", "wrong_economics", "wrong_year", "unsigned", "missing", "extra", "partial_enumeration"])
def test_arbitrary_stale_or_incomplete_governance_evidence_cannot_validate_case(change):
    command, context = basis("dividend")
    receipt = context.governance_receipts[0]
    if change == "inactive": receipt = replace(receipt, active=False)
    if change == "wrong_economics": receipt = replace(receipt, economic_sha256="f" * 64)
    if change == "wrong_year": receipt = replace(receipt, income_year=IncomeYear(2024))
    if change == "unsigned": receipt = replace(receipt, signed_document_hashes=())
    context = replace(context, governance_receipts=(receipt,))
    if change == "missing": context = replace(context, governance_receipts=())
    if change == "extra": context = replace(context, governance_receipts=(receipt, replace(receipt, receipt_id=str(UUID(int=7)))))
    if change == "partial_enumeration": context = replace(context, complete_governance_enumeration=False)
    with pytest.raises(Rf1086YearSourceError): prepare(command, context)


def test_capital_finalization_cannot_depend_on_snapshot_being_created():
    command, context = basis("cash_issue")
    receipt = replace(context.governance_receipts[0], register_observation_id=SOURCE.value)
    with pytest.raises(Rf1086YearSourceError, match="circular_register_evidence"):
        prepare(command, replace(context, governance_receipts=(receipt,)))


@pytest.mark.parametrize("change", ["no_documents", "wrong_metadata_version", "cross_company", "no_paid_in_basis", "no_event_evidence", "changed_event_digest"])
def test_document_provenance_and_event_coverage_are_required(change):
    command, context = basis("dividend")
    if change == "no_documents": context = replace(context, documents=())
    if change == "wrong_metadata_version": context = replace(context, documents=(replace(context.documents[0], metadata_sha256="f" * 64),))
    if change == "cross_company":
        doc = replace(context.documents[0], company_id=CompanyId(str(UUID(int=10))))
        context = replace(context, documents=(doc,)); command = replace(command, documents=(doc,))
    if change == "no_paid_in_basis": command = replace(command, paid_in_document_ids=())
    if change == "no_event_evidence": command = replace(command, event_evidence=())
    if change == "changed_event_digest": command = replace(command, event_evidence=(replace(command.event_evidence[0], event_sha256="e" * 64),))
    with pytest.raises(Rf1086YearSourceError): prepare(command, context)


def test_context_must_be_verified_for_same_owner_company_and_year():
    command, context = basis()
    for changed in (replace(context, accepted_owner=False), replace(context, actor_id=ActorId(ActorKind.USER, UserId(str(UUID(int=12))))),
                    replace(context, company_id=CompanyId(str(UUID(int=11)))), replace(context, income_year=IncomeYear(2024))):
        with pytest.raises(Rf1086YearSourceError): prepare(command, changed)


def test_correction_is_new_version_and_preserves_previous_snapshot():
    command, context = basis()
    previous = prepare(command, context)
    updated = replace(command, supersedes_source_id=previous.source_id, supersedes_source_sha256=previous.source_sha256,
        correction_reason="Corrected source-document attribution")
    result = prepare(updated, context, previous=previous, source_id=Rf1086YearSourceId(str(UUID(int=20))), confirmed_at=NOW + timedelta(days=1))
    assert result.version == 2 and result.source_sha256 != previous.source_sha256
    assert previous.version == 1 and previous.command.supersedes_source_id is None
    assert result.case_sha256 == previous.case_sha256


@pytest.mark.parametrize("change", ["missing_link", "wrong_hash", "wrong_id", "empty_reason", "same_id", "older_time"])
def test_correction_requires_exact_predecessor_and_reason(change):
    command, context = basis()
    previous = prepare(command, context)
    updated = replace(command, supersedes_source_id=previous.source_id, supersedes_source_sha256=previous.source_sha256, correction_reason="Correction")
    identifier = Rf1086YearSourceId(str(UUID(int=20))); timestamp = NOW + timedelta(days=1)
    if change == "missing_link": updated = replace(updated, supersedes_source_id=None)
    if change == "wrong_hash": updated = replace(updated, supersedes_source_sha256="e" * 64)
    if change == "wrong_id": updated = replace(updated, supersedes_source_id=identifier)
    if change == "empty_reason": updated = replace(updated, correction_reason=" ")
    if change == "same_id": identifier = previous.source_id
    if change == "older_time": timestamp = NOW - timedelta(days=1)
    with pytest.raises(Rf1086YearSourceError):
        prepare(updated, context, previous=previous, source_id=identifier, confirmed_at=timestamp)


@pytest.mark.parametrize("change", ["source_head", "source_digest", "company", "document", "governance", "enumeration", "new_receipt"])
def test_full_freshness_vector_blocks_changed_sources(change):
    command, context = basis("dividend"); source = prepare(command, context)
    identifier = SOURCE; digest = source.source_sha256
    if change == "source_head": identifier = Rf1086YearSourceId(str(UUID(int=25)))
    if change == "source_digest": digest = "1" * 64
    if change == "company": context = replace(context, company_identity_sha256="e" * 64)
    if change == "document": context = replace(context, documents=(replace(context.documents[0], metadata_sha256="f" * 64),))
    if change == "governance": context = replace(context, governance_receipts=(replace(context.governance_receipts[0], active=False),))
    if change == "enumeration": context = replace(context, governance_enumeration_sha256="e" * 64)
    if change == "new_receipt": context = replace(context, governance_receipts=(*context.governance_receipts, replace(context.governance_receipts[0], receipt_id=str(UUID(int=30)))))
    with pytest.raises(Rf1086YearSourceError):
        assert_rf1086_year_source_fresh(source, current_source_id=identifier, current_source_sha256=digest, context=context)


def test_source_and_copied_sequences_are_immutable():
    command, context = basis()
    docs = list(command.documents)
    command = replace(command, documents=docs)
    docs.clear()
    source = prepare(command, context)
    assert len(source.command.documents) == 1
    with pytest.raises(FrozenInstanceError): source.version = 2


def test_canonical_digest_preserves_decimal_values_without_rounding():
    assert rf1086_year_source_digest({"amount": Decimal("100.100000")}) == rf1086_year_source_digest({"amount": 100.1})
    assert rf1086_year_source_digest({"amount": Decimal("100.100001")}) != rf1086_year_source_digest({"amount": Decimal("100.100002")})
    assert rf1086_year_source_digest({"amount": Decimal("9007199254740993.01")}) != rf1086_year_source_digest({"amount": Decimal("9007199254740992.01")})
    for value in (float("nan"), float("inf"), Decimal("NaN")):
        with pytest.raises(Rf1086YearSourceError): rf1086_year_source_digest({"amount": value})


def test_altered_persisted_snapshot_cannot_be_used_for_freshness_or_correction():
    command, context = basis()
    source = prepare(command, context)
    changed = replace(source, command=replace(command, complete_year_confirmed=False))
    with pytest.raises(Rf1086YearSourceError, match="snapshot_invalid"):
        assert_rf1086_year_source_fresh(changed, current_source_id=SOURCE,
            current_source_sha256=changed.source_sha256, context=context)
    correction = replace(command, supersedes_source_id=SOURCE, supersedes_source_sha256=source.source_sha256,
        correction_reason="Corrected")
    with pytest.raises(Rf1086YearSourceError, match="snapshot_invalid"):
        prepare(correction, context, previous=changed, source_id=Rf1086YearSourceId(str(UUID(int=99))),
            confirmed_at=NOW + timedelta(days=1))


def test_idempotency_replay_requires_exact_source_request():
    from talli_backend.modules.shareholder_register_filing.public import assert_rf1086_year_source_replay
    command, context = basis()
    source = prepare(command, context)
    assert_rf1086_year_source_replay(source, command)
    with pytest.raises(Rf1086YearSourceError, match="idempotency_conflict"):
        assert_rf1086_year_source_replay(source, replace(command, complete_year_confirmed=False))


def loss_reduction_basis(opening_capital):
    command, context = basis()
    raw = json.loads((ROOT / "tests/fixtures/rf1086/no_activity.json").read_text())
    opening_nominal = opening_capital // 100
    raw["share_snapshot"].update(previous_share_capital=opening_capital,
        current_share_capital=opening_capital - 10000, previous_nominal_value=opening_nominal,
        current_nominal_value=opening_nominal - 100, previous_paid_in_share_capital=opening_capital,
        current_paid_in_share_capital=opening_capital, previous_paid_in_premium=2000,
        current_paid_in_premium=2000)
    raw["events"] = [{"type": "loss_covering_reduction", "timestamp": "2025-06-01T12:00:00",
        "registration_confirmed": True, "capital_reduction": 10000, "nominal_value_reduction": 100,
        "nominal_value_after": opening_nominal - 100, "fund_issued_capital_before": 0}]
    case = parse_rf1086_case(raw)
    command = replace(command, case=case, paid_in=Rf1086PaidInSourceFacts(opening_capital, opening_capital, 2000, 2000),
        event_evidence=(Rf1086YearEventEvidence(0, rf1086_year_source_digest(case.events[0]), (DOCUMENT,), RECEIPT),),
        no_activity_confirmed=False)
    receipt = Rf1086YearGovernanceReceipt(RECEIPT, COMPANY, YEAR, "loss_covering_reduction",
        rf1086_year_source_digest(rf1086_governance_economic_facts(case.events[0])), "b" * 64,
        (context.documents[0].content_sha256,), True, REGISTER, "c" * 64)
    return command, replace(context, governance_receipts=(receipt,),
        governance_enumeration_sha256=rf1086_year_source_digest((receipt,)))


def test_loss_reduction_receipt_cannot_corroborate_a_different_registered_capital_history():
    first_command, first_context = loss_reduction_basis(40000)
    second_command, _ = loss_reduction_basis(50000)
    first = prepare(first_command, first_context)
    assert first.command.case.share_snapshot.current_share_capital == 30000
    # Dates, reduction, share count, document hashes and register observation are
    # deliberately identical. The immutable receipt belongs to 40k -> 30k only.
    with pytest.raises(Rf1086YearSourceError, match="governance_receipt_mismatch"):
        prepare(second_command, first_context)


def test_loss_reduction_projects_existing_governance_before_and_after_capital_fields():
    command, _ = loss_reduction_basis(40000)
    facts = rf1086_governance_economic_facts(command.case.events[0])
    assert facts == {"event_type": "loss_covering_reduction", "event_date": "2025-06-01",
        "nominal_reduction": Decimal("10000"), "old_share_capital": Decimal("40000"),
        "new_share_capital": Decimal("30000")}


@pytest.mark.parametrize("amount,nominal_delta", [(Decimal("10000"), Decimal("3")), (Decimal("10000"), Decimal(0))])
def test_loss_reduction_projection_never_rounds_an_invalid_share_count(amount, nominal_delta):
    command, _ = loss_reduction_basis(40000)
    event = replace(command.case.events[0], capital_reduction=amount, nominal_value_reduction=nominal_delta)
    with pytest.raises(Rf1086YearSourceError, match="reduction_basis_invalid"):
        rf1086_governance_economic_facts(event)


def test_loss_reduction_projection_preserves_exact_decimal_capital():
    command, _ = loss_reduction_basis(40000)
    event = replace(command.case.events[0], capital_reduction=Decimal("10.01"),
        nominal_value_reduction=Decimal("0.01"), nominal_value_after=Decimal("300.123456"))
    facts = rf1086_governance_economic_facts(event)
    assert facts["old_share_capital"] == Decimal("300433.589456")
    assert facts["new_share_capital"] == Decimal("300423.579456")
