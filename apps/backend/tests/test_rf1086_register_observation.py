"""Public behavior of independent register observation foundation; no IO."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone, timedelta
from decimal import Decimal, localcontext
from uuid import UUID

import pytest

from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId
from talli_backend.modules.shareholder_register_filing.public import (
    RecordRf1086RegisterObservation, Rf1086RegisterDocumentEvidence,
    Rf1086RegisterHolding, Rf1086RegisteredShareState, Rf1086RegisterObservationError,
    Rf1086RegisterObservationId, Rf1086RegisterObservationMatchQuery,
    Rf1086VerifiedRegisterObservationContext, prepare_rf1086_register_observation,
    assert_rf1086_register_observation_integrity, verify_rf1086_register_observation,
)

COMPANY = CompanyId(str(UUID(int=1)))
ACTOR = ActorId(ActorKind.USER, UserId(str(UUID(int=2))))
YEAR = IncomeYear(2025)
ID = Rf1086RegisterObservationId(str(UUID(int=3)))
NOW = datetime(2025, 7, 1, 12, tzinfo=timezone.utc)


def basis(kind="cash_issue"):
    holder = Rf1086RegisterHolding("existing-owner", "Example AS", "norwegian_company", "123456789", 100)
    before = Rf1086RegisteredShareState(Decimal(60000), 100, Decimal(600), (holder,))
    if kind == "cash_issue":
        after = Rf1086RegisteredShareState(Decimal(120000), 200, Decimal(600), (replace(holder, share_count=200),))
    elif kind == "cash_nominal_increase":
        after = replace(before, share_capital=Decimal(120000), nominal_value=Decimal(1200))
    else:
        after = replace(before, share_capital=Decimal(30000), nominal_value=Decimal(300))
    docs = tuple(Rf1086RegisterDocumentEvidence(str(UUID(int=n)), COMPANY, str(n) * 64, str(n) * 64, 12,
                 "share_register", "attached", NOW - timedelta(days=1), "a" * 64, role)
                 for n, role in zip((4, 5, 6), ("register_before", "register_after", "registration")))
    command = RecordRf1086RegisterObservation(COMPANY, ACTOR, YEAR, datetime(2025, 6, 1, 12), kind,
        before, after, docs, True, True, True)
    context = Rf1086VerifiedRegisterObservationContext(ACTOR, True, COMPANY, YEAR, docs, True)
    return command, context


def prepare(command=None, context=None, **kwargs):
    default_command, default_context = basis()
    return prepare_rf1086_register_observation(command or default_command, context=context or default_context,
        observation_id=kwargs.pop("observation_id", ID), confirmed_at=kwargs.pop("confirmed_at", NOW), **kwargs)


def match(snapshot):
    command = snapshot.command
    return Rf1086RegisterObservationMatchQuery(snapshot.observation_id, snapshot.version, snapshot.fact_sha256,
        command.company_id, command.income_year, command.effective_at, command.event_kind, command.before, command.after)


@pytest.mark.parametrize("kind", ["cash_issue", "cash_nominal_increase", "loss_covering_reduction"])
def test_complete_registered_before_after_observation_and_exact_match(kind):
    command, context = basis(kind)
    snapshot = prepare(command, context)
    assert snapshot.command.before == command.before
    assert snapshot.command.after == command.after
    assert snapshot.version == 1
    assert_rf1086_register_observation_integrity(snapshot)
    assert verify_rf1086_register_observation(snapshot, match(snapshot)) is snapshot
    assert "paid_in" not in str(snapshot.__dataclass_fields__)
    with pytest.raises(FrozenInstanceError):
        snapshot.version = 9


def test_cash_issue_supports_all_holders_and_order_has_no_digest_effect():
    command, context = basis()
    newcomer = Rf1086RegisterHolding("documented-new-owner", "Example Person", "norwegian_person", "12345678901", 100)
    command = replace(command, after=replace(command.after, holdings=(newcomer, command.before.holdings[0])))
    snapshot = prepare(command, context)
    reordered = replace(command, after=replace(command.after, holdings=tuple(reversed(command.after.holdings))),
                        documents=tuple(reversed(command.documents)))
    assert prepare(reordered, context).fact_sha256 == snapshot.fact_sha256


@pytest.mark.parametrize("changes", [
    {"complete_register_confirmed": False}, {"registration_confirmed": 1},
    {"single_share_class_confirmed": False},
    {"income_year": IncomeYear(2024)}, {"event_kind": "formation"},
    {"effective_at": datetime(2025, 6, 1, tzinfo=timezone.utc)},
    {"effective_at": datetime(2025, 6, 1, microsecond=1)},
])
def test_unsupported_or_unconfirmed_input_is_closed(changes):
    command, context = basis()
    with pytest.raises(Rf1086RegisterObservationError):
        prepare(replace(command, **changes), context)


@pytest.mark.parametrize("changes", [
    {"share_count": True}, {"share_capital": Decimal("NaN")},
    {"share_capital": 120000.0}, {"share_capital": Decimal(120001)},
    {"nominal_value": Decimal("600.0000001")}, {"holdings": ()},
])
def test_registered_state_requires_exact_complete_economics(changes):
    command, context = basis()
    with pytest.raises(Rf1086RegisterObservationError):
        prepare(replace(command, after=replace(command.after, **changes)), context)


@pytest.mark.parametrize("changes", [
    {"shareholder_id": ""}, {"share_count": 199}, {"share_count": True},
    {"kind": "unknown"}, {"identifier": "not-an-id"},
    {"identifier": "987654321"}, {"name": "Another name"},
])
def test_missing_counts_or_unreviewed_identity_changes_fail(changes):
    command, context = basis()
    after = replace(command.after, holdings=(replace(command.after.holdings[0], **changes),))
    with pytest.raises(Rf1086RegisterObservationError):
        prepare(replace(command, after=after), context)


def test_duplicate_legal_identity_under_new_id_is_rejected():
    command, context = basis()
    old = command.before.holdings[0]
    after = replace(command.after, holdings=(old, replace(old, shareholder_id="alias")))
    with pytest.raises(Rf1086RegisterObservationError, match="holder_duplicate"):
        prepare(replace(command, after=after), context)


def test_issue_cannot_hide_transfer_away_from_existing_owner():
    command, context = basis()
    old = command.before.holdings[0]
    newcomer = Rf1086RegisterHolding("new", "New AS", "norwegian_company", "987654321", 150)
    after = replace(command.after, holdings=(replace(old, share_count=50), newcomer))
    with pytest.raises(Rf1086RegisterObservationError, match="issue_holder_transition"):
        prepare(replace(command, after=after), context)


@pytest.mark.parametrize("kind", ["cash_nominal_increase", "loss_covering_reduction"])
def test_nominal_events_cannot_change_holder_counts(kind):
    command, context = basis(kind)
    other = Rf1086RegisterHolding("other", "Other AS", "norwegian_company", "987654321", 50)
    after = replace(command.after, holdings=(replace(command.after.holdings[0], share_count=50), other))
    with pytest.raises(Rf1086RegisterObservationError, match="nominal_holder_transition"):
        prepare(replace(command, after=after), context)


def test_loss_cannot_reduce_below_supported_minimum():
    command, context = basis("loss_covering_reduction")
    after = replace(command.after, nominal_value=Decimal(100), share_capital=Decimal(10000))
    with pytest.raises(Rf1086RegisterObservationError, match="capital_below"):
        prepare(replace(command, after=after), context)


@pytest.mark.parametrize("changes", [
    {"accepted_owner": False}, {"independent_originals_verified": False},
    {"company_id": CompanyId(str(UUID(int=9)))}, {"income_year": IncomeYear(2024)},
    {"actor_id": ActorId(ActorKind.USER, UserId(str(UUID(int=9))))},
    {"documents": ()},
])
def test_capture_requires_exact_internal_owner_and_verified_original_context(changes):
    command, context = basis()
    with pytest.raises(Rf1086RegisterObservationError):
        prepare(command, replace(context, **changes))


@pytest.mark.parametrize("changes", [
    {"content_sha256": "a" * 64}, {"content_version_sha256": "a" * 64}, {"byte_length": 13},
    {"metadata_sha256": "b" * 64}, {"integrity_status": "signed_owner_attested"},
    {"document_type": "other"}, {"created_at": NOW},
    {"company_id": CompanyId(str(UUID(int=9)))}, {"document_id": "rf1086:source"},
    {"role": "year_source"}, {"byte_length": 0},
])
def test_changed_document_reference_or_unverified_content_fails(changes):
    command, context = basis()
    command = replace(command, documents=(replace(command.documents[0], **changes), *command.documents[1:]))
    with pytest.raises(Rf1086RegisterObservationError):
        prepare(command, context)


def test_no_omitted_register_side_or_duplicate_document_evidence():
    command, context = basis()
    for docs in (command.documents[1:], command.documents + command.documents[:1]):
        with pytest.raises(Rf1086RegisterObservationError):
            prepare(replace(command, documents=docs), replace(context, documents=docs))


def test_correction_is_immutable_new_version_exact_predecessor():
    command, context = basis()
    first = prepare(command, context)
    corrected = replace(command, supersedes_observation_id=ID, supersedes_observation_sha256=first.fact_sha256,
                        correction_reason="Correct reviewed documentary reference")
    second = prepare(corrected, context, previous=first, observation_id=Rf1086RegisterObservationId(str(UUID(int=9))),
                     confirmed_at=NOW + timedelta(seconds=1))
    assert second.version == 2
    assert first.version == 1
    assert second.fact_sha256 != first.fact_sha256
    assert_rf1086_register_observation_integrity(second)
    for changed in (replace(corrected, supersedes_observation_sha256="0" * 64),
                    replace(corrected, correction_reason=""), replace(corrected, event_kind="loss_covering_reduction")):
        with pytest.raises(Rf1086RegisterObservationError):
            prepare(changed, context, previous=first, observation_id=Rf1086RegisterObservationId(str(UUID(int=9))),
                    confirmed_at=NOW + timedelta(seconds=1))
    with pytest.raises(Rf1086RegisterObservationError):
        prepare(corrected, context, previous=first, confirmed_at=NOW + timedelta(seconds=1))
    with pytest.raises(Rf1086RegisterObservationError):
        prepare(corrected, context)


@pytest.mark.parametrize("changes", [
    {"version": 2}, {"fact_sha256": "a" * 64}, {"confirmed_at": NOW + timedelta(seconds=1)},
    {"observation_id": Rf1086RegisterObservationId(str(UUID(int=9)))},
])
def test_retained_snapshot_tampering_is_detected(changes):
    snapshot = prepare()
    with pytest.raises(Rf1086RegisterObservationError):
        assert_rf1086_register_observation_integrity(replace(snapshot, **changes))


@pytest.mark.parametrize("changes", [
    {"revision": 2}, {"revision": True}, {"fact_sha256": "a" * 64},
    {"observation_id": Rf1086RegisterObservationId(str(UUID(int=9)))},
    {"company_id": CompanyId(str(UUID(int=9)))}, {"income_year": IncomeYear(2024)},
    {"event_kind": "cash_nominal_increase"}, {"effective_at": datetime(2025, 6, 2, 12)},
])
def test_governance_reference_and_event_binding_cannot_be_reused(changes):
    snapshot = prepare()
    with pytest.raises(Rf1086RegisterObservationError):
        verify_rf1086_register_observation(snapshot, replace(match(snapshot), **changes))


def test_exact_before_capital_is_required_even_when_delta_same():
    snapshot = prepare()
    query = match(snapshot)
    before = replace(query.before, share_capital=Decimal(90000), nominal_value=Decimal(900))
    with pytest.raises(Rf1086RegisterObservationError, match="economic_binding"):
        verify_rf1086_register_observation(snapshot, replace(query, before=before))


def test_decimal_identity_does_not_depend_on_context_precision_or_trailing_zeroes():
    command, context = basis()
    baseline = prepare(command, context)
    with localcontext() as ctx:
        ctx.prec = 2
        assert prepare(command, context).fact_sha256 == baseline.fact_sha256
    changed = replace(command, before=replace(command.before, nominal_value=Decimal("600.000000")))
    assert prepare(changed, context).fact_sha256 == baseline.fact_sha256


def test_mutable_input_lists_are_detached():
    command, context = basis()
    holders = list(command.after.holdings)
    documents = list(command.documents)
    command = replace(command, after=replace(command.after, holdings=holders), documents=documents)
    holders.clear()
    documents.clear()
    assert len(prepare(command, context).command.documents) == 3


def test_verified_document_metadata_is_retained_without_false_signedness():
    snapshot = prepare()
    assert all(doc.integrity_status == "attached" for doc in snapshot.command.documents)
    assert all(doc.content_version_sha256 == doc.content_sha256 for doc in snapshot.command.documents)
    assert all(doc.metadata_sha256 == "a" * 64 for doc in snapshot.command.documents)


def test_verified_documents_must_exist_at_capture():
    command, context = basis()
    docs = tuple(replace(doc, created_at=NOW + timedelta(seconds=1)) for doc in command.documents)
    with pytest.raises(Rf1086RegisterObservationError, match="document_postdates_capture"):
        prepare(replace(command, documents=docs), replace(context, documents=docs))


def test_same_original_document_can_support_multiple_reviewed_roles_but_cannot_have_two_versions():
    command, context = basis()
    original = command.documents[0]
    docs = tuple(replace(original, role=doc.role) for doc in command.documents)
    snapshot = prepare(replace(command, documents=docs), replace(context, documents=docs))
    assert len({doc.document_id for doc in snapshot.command.documents}) == 1
    conflicting = (replace(docs[0], metadata_sha256="b" * 64), *docs[1:])
    with pytest.raises(Rf1086RegisterObservationError, match="document_version_conflict"):
        prepare(replace(command, documents=conflicting), replace(context, documents=conflicting))


def test_capture_needs_aware_time_and_cannot_precede_event_day():
    for timestamp in (datetime(2025, 7, 1), NOW - timedelta(days=60)):
        with pytest.raises(Rf1086RegisterObservationError):
            prepare(confirmed_at=timestamp)


def test_correction_updates_verified_original_and_invalidates_previous_reference():
    command, context = basis()
    first = prepare(command, context)
    docs = (replace(command.documents[0], content_version_sha256="b" * 64,
                    content_sha256="b" * 64, metadata_sha256="c" * 64), *command.documents[1:])
    changed = replace(command, documents=docs, supersedes_observation_id=ID,
                      supersedes_observation_sha256=first.fact_sha256, correction_reason="Corrected original")
    next_snapshot = prepare(changed, replace(context, documents=docs), previous=first,
        observation_id=Rf1086RegisterObservationId(str(UUID(int=9))), confirmed_at=NOW + timedelta(seconds=1))
    assert next_snapshot.command.documents[0].content_sha256 == "b" * 64
    assert first.command.documents[0].content_sha256 == "4" * 64
    with pytest.raises(Rf1086RegisterObservationError, match="reference_mismatch"):
        verify_rf1086_register_observation(next_snapshot, match(first))


def test_request_digest_is_validated_and_order_independent():
    from talli_backend.modules.shareholder_register_filing.public import rf1086_register_observation_request_digest
    command, _ = basis()
    assert rf1086_register_observation_request_digest(command) == rf1086_register_observation_request_digest(
        replace(command, documents=tuple(reversed(command.documents))))
    with pytest.raises(Rf1086RegisterObservationError):
        rf1086_register_observation_request_digest(replace(command, registration_confirmed=False))


def test_same_original_cannot_have_conflicting_document_income_years():
    command, context = basis()
    docs = tuple(replace(command.documents[0], role=doc.role, source_income_year=IncomeYear(2025)) for doc in command.documents)
    docs = (replace(docs[0], source_income_year=IncomeYear(2024)), *docs[1:])
    with pytest.raises(Rf1086RegisterObservationError, match="document_version_conflict"):
        prepare(replace(command, documents=docs), replace(context, documents=docs))
