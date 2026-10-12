"""Coherent public Governance/RF values; Documents and current-read authority are doubles."""
import asyncio
from dataclasses import fields, replace
from datetime import timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace

import pytest

from talli_backend.application.shareholder_register_source_context_v2 import build_verified_source_context_v2
from talli_backend.application.shareholder_register_source_workflow import build_verified_source_context
from talli_backend.modules.corporate_governance import public as gov
from talli_backend.modules.corporate_governance.service import CorporateGovernanceService
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import IncomeYear, LocalDate, Money
from test_corporate_governance_supported_events import command as governance_command, capital_facts, reduction_facts, bank
from test_rf1086_year_source_v2 import v2_basis, observation, identity, NOW
from test_supabase_corporate_register_evidence_amendment import chain_payload
from test_shareholder_register_source_workflow import Harness


def digest(value):
    return sha256(value.encode()).hexdigest()


def fact(observed):
    return gov.SupportedCorporateSourceFact(gov.CorporateSourceReference(observed.observation_id.value),
        observed.version, observed.fact_sha256)


def coherent(kind="loss_covering_reduction", count=1, phase="registered"):
    command, initial = v2_basis(kind)
    event = command.case.events[0]
    prototype = command.documents[0]
    documents = {}

    def document(number, *, source_year=None):
        content = digest(f"original {number}")
        row = replace(prototype, document_id=identity(number), content_sha256=content,
            content_version_sha256=content, metadata_sha256=digest(f"metadata {number}"),
            created_at=NOW - timedelta(days=20), source_income_year=source_year or command.income_year)
        documents[row.document_id] = row
        return row

    types = gov.SupportedCorporateEvidenceKind
    roles = (types.SIGNED_DECISION, types.AMENDED_ARTICLES, types.REGISTRATION_RECEIPT)
    if kind == "cash_issue":
        roles += (types.CONTRIBUTION_CONFIRMATION,)
    original_docs = tuple(document(500 + index) for index in range(len(roles)))
    command = replace(command, documents=(original_docs[0],),
        opening_document_ids=(original_docs[0].document_id,), closing_document_ids=(original_docs[0].document_id,),
        paid_in_document_ids=(original_docs[0].document_id,),
        event_evidence=(replace(command.event_evidence[0], document_ids=tuple(row.document_id for row in original_docs)),))
    def observe(number, selected, at):
        template = observation(command, 0, number, at).command
        register_documents = tuple(replace(row, **{field.name: getattr(selected, field.name)
            for field in fields(rf.Rf1086YearDocumentEvidence)}) for row in template.documents)
        record = replace(template, documents=register_documents)
        verified = rf.Rf1086VerifiedRegisterObservationContext(command.actor_id, True,
            command.company_id, command.income_year, register_documents, True)
        return rf.prepare_rf1086_register_observation(record, context=verified,
            observation_id=rf.Rf1086RegisterObservationId(identity(number)), confirmed_at=at)

    first = observe(1000, original_docs[0], NOW - timedelta(days=3))
    doc_facts = tuple(gov.SupportedCorporateDocumentFact(gov.DocumentReference(row.document_id), role,
        3, row.content_sha256) for row, role in zip(original_docs, roles, strict=True))
    economics = rf.rf1086_governance_economic_facts(event)
    if kind == "cash_issue":
        business = replace(capital_facts(), nominal_increase=Money.nok(str(economics['nominal_increase'])),
            share_premium=Money.nok(str(economics['share_premium'])), issued_share_count=economics['issued_share_count'])
        bank_fact = replace(bank(str(economics['nominal_increase'] + economics['share_premium'])),
            transaction_date=LocalDate(event.timestamp.date()))
        event_kind = gov.SupportedCorporateEventKind.CASH_CAPITAL_INCREASE
    else:
        business = replace(reduction_facts(), nominal_reduction=Money.nok(str(economics['nominal_reduction'])),
            old_share_capital=Money.nok(str(economics['old_share_capital'])),
            new_share_capital=Money.nok(str(economics['new_share_capital'])))
        bank_fact = None
        event_kind = gov.SupportedCorporateEventKind.LOSS_COVERAGE_CAPITAL_REDUCTION
    request = governance_command(kind=event_kind, phase=gov.SupportedCorporateEventPhase(phase),
        facts=business, documents=doc_facts, bank_fact=bank_fact, shareholder_register_fact=fact(first))
    request = replace(request, company_id=command.company_id, actor_id=command.actor_id,
        income_year=command.income_year, event_id=gov.SupportedCorporateEventId(command.event_evidence[0].governance_receipt_id),
        event_date=LocalDate(event.timestamp.date()))
    original = gov.RecordedSupportedCorporateEvent(CorporateGovernanceService().prepare_supported_event(request),
        gov.AccountingEntryReference(identity(700)), None, None, NOW - timedelta(days=2), False)
    anchor = gov.anchor_supported_corporate_event_evidence(original, original_actor_id=request.actor_id.subject)
    receipts = []
    current = first
    for revision in range(1, count + 1):
        replacement_doc = document(600 + revision, source_year=IncomeYear(2024))
        memo_doc = document(650 + revision)
        successor = observe(1000 + revision, replacement_doc, NOW + timedelta(hours=revision))
        memo = gov.SupportedCorporateDocumentFact(gov.DocumentReference(memo_doc.document_id),
            types.CORRECTION_MEMO, 3, memo_doc.content_sha256)
        amendment = gov.AmendSupportedCorporateRegisterEvidence(command.company_id, command.income_year,
            command.actor_id, original.event.event_id, anchor.anchor_sha256,
            receipts[-1].head if receipts else None,
            gov.CorporateRegisterWithdrawalReference(gov.CorporateSourceReference(identity(800 + revision)),
                digest(f"withdrawal {revision}"), fact(current)), fact(successor), memo, f"Repair {revision}")
        originals = tuple(gov.CorporateDocumentOriginalCommitment(gov.CorporateSourceReference(identity(900 + index)),
            gov.DocumentReference(row.document_id), row.company_id, row.source_income_year,
            3 if row.document_id != replacement_doc.document_id else 1,
            row.metadata_sha256, row.content_sha256, row.byte_length,
            successor.confirmed_at + timedelta(microseconds=1))
            for index, row in enumerate((*original_docs, memo_doc, replacement_doc)))
        receipt = gov.prepare_supported_corporate_register_evidence_amendment(amendment, anchor=anchor,
            amendment_id=gov.CorporateRegisterEvidenceAmendmentId(identity(750 + revision)),
            recorded_at=successor.confirmed_at + timedelta(seconds=1), originals=originals,
            previous=tuple(receipts))
        receipts.append(receipt)
        current = successor
    query = gov.CorporateReportingRegisterEvidenceQuery(command.company_id, command.income_year, command.actor_id)
    chain_query = gov.CorporateRegisterEvidenceQuery(command.company_id, command.income_year,
        command.actor_id, original.event.event_id)
    chain = gov.parse_corporate_register_evidence_chain_snapshot(chain_payload(anchor, tuple(receipts)), query=chain_query)
    basis = gov.CorporateReportingYearBasis(command.company_id, gov.CorporateLifecycleSnapshot((), (), (), (), ()), (original,))
    view = gov.build_reporting_year_register_evidence(query=query, basis=basis, amendments=(), register_chains=(chain,))
    command = replace(command, documents=tuple(documents.values()))
    calls = []

    async def current_observation(scope, observation_id):
        assert scope.company_id == command.company_id and scope.income_year == command.income_year
        assert scope.actor_id == session.actor_id
        calls.append(observation_id)
        return current if observation_id == current.observation_id else None

    session = SimpleNamespace(actor_id=command.actor_id, read_current_register_observation=current_observation)
    return SimpleNamespace(command=command, initial=initial, view=view, session=session, current=current,
        original=first, calls=calls, documents=documents, receipts=receipts)


def context(h):
    return asyncio.run(build_verified_source_context_v2(h.session, h.command, h.command.case.company,
        h.initial.company_identity_sha256, h.command.documents, h.view))


def prepared(h, value):
    result = rf.prepare_rf1086_year_source_v2(h.command, context=value,
        source_id=rf.Rf1086YearSourceId(identity(1500)), confirmed_at=NOW + timedelta(days=2))
    rf.assert_rf1086_year_source_integrity_v2(result)
    assert rf.parse_rf1086_year_source_v2(rf.serialize_rf1086_year_source_v2(result)) == result
    return result


def rebuild_view(h, *, original=None, receipts=None, actor=None, year=None, ledger_amendments=()):
    recorded = original or h.view.register_chains[0].chain.anchor.original
    query = gov.CorporateReportingRegisterEvidenceQuery(h.command.company_id,
        year or h.command.income_year, actor or h.session.actor_id)
    anchor = gov.anchor_supported_corporate_event_evidence(recorded,
        original_actor_id=h.view.register_chains[0].chain.anchor.original_actor_id)
    chain_query = gov.CorporateRegisterEvidenceQuery(query.company_id, recorded.event.income_year,
        query.actor_id, recorded.event.event_id)
    chain = gov.parse_corporate_register_evidence_chain_snapshot(
        chain_payload(anchor, tuple(h.receipts if receipts is None else receipts)), query=chain_query)
    basis = gov.CorporateReportingYearBasis(query.company_id, gov.CorporateLifecycleSnapshot((), (), (), (), ()), (recorded,))
    return gov.build_reporting_year_register_evidence(query=query, basis=basis,
        amendments=tuple(ledger_amendments), register_chains=(chain,))


@pytest.mark.parametrize("kind,phase", [("cash_issue", "registered"),
    ("loss_covering_reduction", "registered"), ("loss_covering_reduction", "first_recognized_after_registration")])
@pytest.mark.parametrize("count", [0, 1, 2])
def test_public_owner_chain_pairs_with_full_effective_rf_observation(kind, phase, count):
    h = coherent(kind, count, phase)
    value = context(h)
    result = prepared(h, value)
    assert h.calls == [h.current.observation_id]
    assert value.governance_receipts[0].register_observation == h.current
    assert value.governance_receipts[0].original.register_observation_id == h.original.observation_id.value
    assert value.governance_projection.chain_count == 1
    assert value.governance_projection.chains[0].amendment_count == count
    assert result.command == h.command
    assert rf.rf1086_year_source_digest(result.command) == rf.rf1086_year_source_digest(h.command)
    assert {row.source_income_year for row in value.documents} == ({IncomeYear(2025)} if count == 0
        else {IncomeYear(2024), IncomeYear(2025)})


def test_old_current_original_policy_rejects_withdrawn_ancestor_and_new_context_uses_effective():
    h = coherent(count=2)
    with pytest.raises(rf.Rf1086YearSourceError, match="independent_register_unavailable"):
        asyncio.run(build_verified_source_context(h.session, h.command, h.command.case.company,
            h.initial.company_identity_sha256, h.command.documents, h.view.original))
    assert h.calls == [h.original.observation_id]
    value = context(h)
    assert h.calls == [h.original.observation_id, h.current.observation_id]
    prepared(h, value)


@pytest.mark.parametrize("number", [500, 501, 502, 601, 602, 651, 652])
def test_every_original_memo_and_intermediate_replacement_is_required(number):
    h = coherent(count=2)
    h.command = replace(h.command, documents=tuple(row for row in h.command.documents if row.document_id != identity(number)))
    with pytest.raises(rf.Rf1086YearSourceError):
        context(h)
    assert h.calls == []


@pytest.mark.parametrize("field", ['company_id', 'source_income_year', 'metadata_sha256', 'content_sha256', 'byte_length'])
def test_memo_retained_commitments_must_match_verified_document_projection(field):
    h = coherent(count=2)
    row = h.documents[identity(651)]
    changes = {'company_id': type(row.company_id)(identity(1700)), 'source_income_year': IncomeYear(2023),
        'metadata_sha256': 'f' * 64, 'content_sha256': 'e' * 64, 'byte_length': row.byte_length + 1}
    values = {field: changes[field]}
    if field == 'content_sha256': values['content_version_sha256'] = values[field]
    mutated = replace(row, **values)
    h.command = replace(h.command, documents=tuple(mutated if item.document_id == row.document_id else item for item in h.command.documents))
    expected_error = 'documents_unverified' if field == 'company_id' else 'register_original_changed'
    with pytest.raises(rf.Rf1086YearSourceError, match=expected_error):
        context(h)
    assert h.calls == []


@pytest.mark.parametrize("change", ['missing', 'hash', 'scope', 'postcutoff', 'state'])
def test_effective_observation_needs_full_current_match(change):
    h = coherent(count=1)
    selected = h.current
    if change == 'hash': selected = replace(selected, fact_sha256='f' * 64)
    if change == 'scope': selected = replace(selected, command=replace(selected.command, income_year=IncomeYear(2024)))
    if change == 'postcutoff': selected = replace(selected, confirmed_at=NOW + timedelta(days=3))
    if change == 'state': selected = replace(selected, command=replace(selected.command,
        after=replace(selected.command.after, share_capital=selected.command.after.share_capital + 1)))

    async def current(*args):
        return None if change == 'missing' else selected

    h.session.read_current_register_observation = current
    with pytest.raises((rf.Rf1086YearSourceError, rf.Rf1086RegisterObservationError)):
        context(h)


@pytest.mark.parametrize("change", ['actor', 'company', 'year', 'projection_hash', 'chain_count', 'duplicate_document', 'duplicate_event'])
def test_scope_complete_projection_and_unique_input_correspondence_are_required(change):
    h = coherent()
    if change == 'actor': h.session.actor_id = replace(h.command.actor_id, subject=type(h.command.actor_id.subject)(identity(1700)))
    if change == 'company': h.view = replace(h.view, query=replace(h.view.query, company_id=type(h.command.company_id)(identity(1700))))
    if change == 'year': h.view = replace(h.view, query=replace(h.view.query, income_year=IncomeYear(2024)))
    if change == 'projection_hash': h.view = replace(h.view, enumeration_sha256='f' * 64)
    if change == 'chain_count': h.view = replace(h.view, chain_count=0)
    if change == 'duplicate_document': h.command = replace(h.command, documents=h.command.documents + (h.command.documents[0],))
    if change == 'duplicate_event': h.command = replace(h.command, event_evidence=h.command.event_evidence * 2)
    with pytest.raises(rf.Rf1086YearSourceError):
        context(h)
    assert h.calls == []


@pytest.mark.parametrize('kind', ['formation', 'no_activity'])
def test_no_governance_events_uses_real_known_empty_owner_projection(kind):
    command, initial = v2_basis(kind)
    query = gov.CorporateReportingRegisterEvidenceQuery(command.company_id, command.income_year, command.actor_id)
    view = gov.build_reporting_year_register_evidence(query=query,
        basis=gov.CorporateReportingYearBasis(command.company_id, gov.CorporateLifecycleSnapshot((), (), (), (), ()), ()),
        amendments=(), register_chains=())
    session = SimpleNamespace(actor_id=command.actor_id)
    h = SimpleNamespace(command=command, initial=initial, session=session, view=view)
    value = context(h)
    assert value.governance_projection.chain_count == 0 and value.governance_receipts == ()
    prepared(h, value)


def test_off_year_complete_commitments_do_not_invent_local_original_bytes_or_observations():
    old = coherent(count=2)
    command, initial = v2_basis('no_activity')
    command = replace(command, income_year=IncomeYear(2026),
        case=replace(command.case, company=replace(command.case.company, income_year=2026)))
    view = rebuild_view(old, year=command.income_year)
    assert not view.original.supported_events and view.chain_count == 1
    session = SimpleNamespace(actor_id=command.actor_id)  # No RF read or foreign byte port.
    h = SimpleNamespace(command=command, initial=initial, session=session, view=view)
    value = context(h)
    assert value.documents == command.documents
    assert not set(old.documents).intersection(row.document_id for row in value.documents)
    assert value.governance_projection.chain_count == 1 and value.governance_receipts == ()
    assert value.governance_projection.chains[0].income_year == IncomeYear(2025)
    prepared(h, value)


def test_new_current_owner_keeps_historical_governance_and_rf_actors():
    h = coherent(count=2)
    original_actor = h.current.command.actor_id
    owner = replace(original_actor, subject=type(original_actor.subject)(identity(1750)))
    h.command = replace(h.command, actor_id=owner)
    h.session.actor_id = owner
    h.view = rebuild_view(h, actor=owner)
    value = context(h)
    result = prepared(h, value)
    assert result.confirmed_by == owner
    assert value.governance_receipts[0].register_observation.command.actor_id == original_actor
    assert h.view.register_chains[0].chain.anchor.original_actor_id == original_actor.subject
    assert all(row.command.actor_id == original_actor for row in h.view.register_chains[0].chain.amendments)


def test_shared_document_conflicting_retained_metadata_rejects_even_valid_owner_chain():
    h = coherent(count=2)
    previous, second = h.receipts
    commitments = tuple(replace(row, metadata_sha256='f' * 64)
        if row.document_id.value == identity(500) else row for row in second.originals)
    changed = gov.prepare_supported_corporate_register_evidence_amendment(second.command,
        anchor=second.anchor, amendment_id=second.amendment_id, recorded_at=second.recorded_at,
        originals=commitments, previous=(previous,))
    h.view = rebuild_view(h, receipts=(previous, changed))
    gov.assert_reporting_year_register_evidence(h.view, query=h.view.query)
    with pytest.raises(rf.Rf1086YearSourceError, match='register_original_changed'):
        context(h)
    assert h.calls == []


def test_reversed_original_remains_a_blocker_in_complete_owner_projection():
    h = coherent(count=0)
    recorded = h.view.register_chains[0].chain.anchor.original
    amendment = gov.CorporateLedgerAmendment(recorded.accounting_entry_id, gov.AccountingEntryReference(identity(1760)),
        None, h.command.company_id, h.command.income_year, 'Reverse', h.command.actor_id, NOW)
    h.view = rebuild_view(h, ledger_amendments=(amendment,))
    assert h.view.original.supported_events[0].status == 'reversed'
    with pytest.raises(rf.Rf1086YearSourceError, match='governance_unresolved'):
        context(h)
    assert h.calls == []


def test_valid_public_governance_economics_must_still_match_rf_case():
    h = coherent('cash_issue', count=0)
    recorded = h.view.register_chains[0].chain.anchor.original
    base = governance_command(kind=gov.SupportedCorporateEventKind.CASH_CAPITAL_INCREASE,
        phase=gov.SupportedCorporateEventPhase.REGISTERED,
        facts=replace(capital_facts(), nominal_increase=Money.nok('29900'), share_premium=Money.nok('500')),
        documents=tuple(gov.SupportedCorporateDocumentFact(gov.DocumentReference(row.document_id), kind, 3, row.content_sha256)
            for row, kind in zip(tuple(h.documents.values())[:4], (gov.SupportedCorporateEvidenceKind.SIGNED_DECISION,
                gov.SupportedCorporateEvidenceKind.AMENDED_ARTICLES, gov.SupportedCorporateEvidenceKind.REGISTRATION_RECEIPT,
                gov.SupportedCorporateEvidenceKind.CONTRIBUTION_CONFIRMATION), strict=True)),
        bank_fact=replace(bank('30400'), transaction_date=LocalDate(h.command.case.events[0].timestamp.date())),
        shareholder_register_fact=fact(h.original))
    base = replace(base, company_id=h.command.company_id, actor_id=h.command.actor_id,
        income_year=h.command.income_year, event_id=recorded.event.event_id, event_date=recorded.event.event_date)
    changed = replace(recorded, event=CorporateGovernanceService().prepare_supported_event(base))
    h.view = rebuild_view(h, original=changed)
    with pytest.raises(rf.Rf1086YearSourceError, match='governance_receipt_mismatch'):
        context(h)
    assert h.calls == []


def test_dividend_uses_rebuilt_owner_reporting_basis_and_preserves_old_receipt():
    original = Harness('dividend')
    item = original.view.dividends[0]
    document_set = gov.CorporateDocumentSetRecord(item.decision.document_set_id, item.decision.company_id,
        item.decision.income_year, item.decision.decision_id, 'owner_dividend', 'v1', item.decision.decision_hash,
        None, item.decision.created_by, item.decision.created_at)
    lifecycle = gov.CorporateLifecycleSnapshot((item.decision,), (document_set,), item.artifacts,
        item.events, item.finalizations)
    query = gov.CorporateReportingRegisterEvidenceQuery(original.command.company_id,
        original.command.income_year, original.command.actor_id)
    view = gov.build_reporting_year_register_evidence(query=query,
        basis=gov.CorporateReportingYearBasis(query.company_id, lifecycle, ()), amendments=(), register_chains=())
    assert len(view.original.dividends) == 1
    # Obtain the same exact verified Documents projection used by the old path.
    original.view = view.original
    original.capture()
    old = original.context
    h = SimpleNamespace(command=original.command, initial=old,
        session=SimpleNamespace(actor_id=old.actor_id), view=view)
    value = context(h)
    baseline = asyncio.run(build_verified_source_context(h.session, h.command, h.command.case.company,
        old.company_identity_sha256, h.command.documents, view.original))
    assert tuple(row.original for row in value.governance_receipts) == baseline.governance_receipts
    assert all(row.register_observation is None for row in value.governance_receipts)
    prepared(h, value)


def test_nominal_increase_without_supported_governance_producer_cannot_look_empty():
    command, initial = v2_basis('cash_nominal_increase')
    query = gov.CorporateReportingRegisterEvidenceQuery(command.company_id, command.income_year, command.actor_id)
    view = gov.build_reporting_year_register_evidence(query=query,
        basis=gov.CorporateReportingYearBasis(command.company_id, gov.CorporateLifecycleSnapshot((), (), (), (), ()), ()),
        amendments=(), register_chains=())
    h = SimpleNamespace(command=command, initial=initial, session=SimpleNamespace(actor_id=command.actor_id), view=view)
    with pytest.raises(rf.Rf1086YearSourceError, match='governance_events_omitted'):
        context(h)


@pytest.mark.parametrize('field,value', [('document_type', 'other_source'), ('integrity_status', 'attached'),
    ('created_at', NOW - timedelta(days=19))])
def test_effective_original_common_fields_match_beyond_governance_commitment(field, value):
    h = coherent(count=1)
    row = h.documents[identity(601)]
    changed = replace(row, **{field: value})
    assert getattr(changed, field) != getattr(row, field)
    h.command = replace(h.command, documents=tuple(changed if item.document_id == row.document_id else item
        for item in h.command.documents))
    with pytest.raises(rf.Rf1086YearSourceError, match='register_original_changed'):
        context(h)
    assert h.calls == [h.current.observation_id]


def test_documents_instant_comparison_preserves_authoritative_offset_in_source_command():
    h = coherent(count=1)
    row = h.documents[identity(601)]
    changed = replace(row, created_at=row.created_at.astimezone(timezone(timedelta(hours=2))))
    h.command = replace(h.command, documents=tuple(changed if item.document_id == row.document_id else item
        for item in h.command.documents))
    value = context(h)
    result = prepared(h, value)
    assert result.command.documents[-2].created_at.isoformat().endswith('+02:00')
    assert value.governance_receipts[0].register_observation.command.documents[0].created_at.isoformat().endswith('+00:00')


def test_valid_observation_and_recommitted_owner_reference_cannot_postdate_cutoff():
    h = coherent(count=1)
    current = rf.prepare_rf1086_register_observation(h.current.command,
        context=rf.Rf1086VerifiedRegisterObservationContext(h.command.actor_id, True, h.command.company_id,
            h.command.income_year, h.current.command.documents, True),
        observation_id=h.current.observation_id, confirmed_at=NOW + timedelta(days=1))
    previous = h.receipts[0]
    changed = gov.prepare_supported_corporate_register_evidence_amendment(
        replace(previous.command, replacement=fact(current)), anchor=previous.anchor,
        amendment_id=previous.amendment_id, recorded_at=previous.recorded_at, originals=previous.originals)
    h.current = current
    h.view = rebuild_view(h, receipts=(changed,))
    async def lookup(scope, observation_id):
        assert scope.actor_id == h.session.actor_id and observation_id == current.observation_id
        h.calls.append(observation_id)
        return current
    h.session.read_current_register_observation = lookup
    rf.assert_rf1086_register_observation_integrity(current)
    gov.assert_reporting_year_register_evidence(h.view, query=h.view.query)
    with pytest.raises(rf.Rf1086YearSourceError, match='register_postdates_governance'):
        context(h)


def test_missing_complete_owner_projection_cannot_become_known_empty():
    h = coherent()
    h.view = None
    with pytest.raises(rf.Rf1086YearSourceError, match='governance_receipt_invalid'):
        context(h)
    assert h.calls == []


@pytest.mark.parametrize('scenario', ['formation_basis', 'no_activity_basis', 'extra_nonselected_capital'])
def test_all_documents_stay_company_scoped_before_any_owner_read(scenario):
    if scenario == 'extra_nonselected_capital':
        h = coherent()
        foreign = replace(h.command.documents[0], document_id=identity(1801),
            company_id=type(h.command.company_id)(identity(1800)))
        h.command = replace(h.command, documents=h.command.documents + (foreign,))
    else:
        kind = 'formation' if scenario == 'formation_basis' else 'no_activity'
        command, initial = v2_basis(kind)
        foreign = replace(command.documents[0], company_id=type(command.company_id)(identity(1800)))
        h = SimpleNamespace(command=replace(command, documents=(foreign,)), initial=initial,
            session=SimpleNamespace(actor_id=command.actor_id), view=None, calls=[])
    with pytest.raises(rf.Rf1086YearSourceError, match='documents_unverified'):
        context(h)
    assert h.calls == []
