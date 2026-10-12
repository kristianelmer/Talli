"""Pure company-wide register overlays preserve the released reporting-year view."""
from dataclasses import FrozenInstanceError, replace
from datetime import date
from hashlib import sha256
import json

import pytest

from talli_backend.modules.corporate_governance import public as gov
from talli_backend.modules.corporate_governance.service import CorporateGovernanceService
from talli_backend.shared.kernel import IncomeYear, LocalDate
from test_corporate_register_evidence_amendment import fixture, follow, identifier, NOW
from test_corporate_governance_supported_events import command, document, capital_facts, reduction_facts, bank, source
from test_corporate_governance_reporting_year import lifecycle
from test_supabase_corporate_register_evidence_amendment import chain_payload


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return sha256(dumps(value).encode()).hexdigest()


def query(year=2026):
    anchor, cmd, _, _ = fixture()
    return gov.CorporateReportingRegisterEvidenceQuery(cmd.company_id, IncomeYear(year), cmd.actor_id)


def original(*, kind='loss_coverage_capital_reduction', phase='registered', year=2026, number=21, reference=None, anchored=True):
    """A legitimate canonical event from the existing owner service, not a new codec."""
    cash = kind == 'cash_capital_increase'
    kinds = gov.SupportedCorporateEvidenceKind
    docs = tuple(document(k, i + 1) for i, k in enumerate((kinds.SIGNED_DECISION, kinds.AMENDED_ARTICLES,
        kinds.REGISTRATION_RECEIPT) + ((kinds.CONTRIBUTION_CONFIRMATION,) if cash else ())))
    if phase == 'binding_subscription': docs = docs[:1]
    if phase == 'decided_not_registered': docs = docs[:2]
    cmd = command(kind=gov.SupportedCorporateEventKind(kind), phase=gov.SupportedCorporateEventPhase(phase),
        facts=capital_facts() if cash else reduction_facts(), documents=docs,
        bank_fact=bank('15000') if cash and phase != 'binding_subscription' else None,
        shareholder_register_fact=source(number) if phase in ('registered','first_recognized_after_registration') else None)
    cmd = replace(cmd, income_year=IncomeYear(year), event_date=LocalDate(date(year, 9, 1)),
        event_id=gov.SupportedCorporateEventId(identifier(number)),
        event_reference=reference or gov.SupportedCorporateEventReference(identifier(number + 100)))
    if cmd.bank_fact is not None: cmd = replace(cmd, bank_fact=replace(cmd.bank_fact, transaction_date=cmd.event_date))
    recorded = gov.RecordedSupportedCorporateEvent(CorporateGovernanceService().prepare_supported_event(cmd),
        gov.AccountingEntryReference(identifier(number + 200)), None, None, NOW, False)
    return gov.anchor_supported_corporate_event_evidence(recorded, original_actor_id=cmd.actor_id.subject) if anchored else recorded


def snapshot(anchor, receipts=()):
    q = gov.CorporateRegisterEvidenceQuery(anchor.original.event.company_id, anchor.original.event.income_year,
        query().actor_id, anchor.original.event.event_id)
    return gov.parse_corporate_register_evidence_chain_snapshot(chain_payload(anchor, receipts), query=q)


def basis(events=()):
    return gov.CorporateReportingYearBasis(query().company_id, lifecycle(), tuple(events))


def build(events=(), chains=(), amendments=(), year=2026):
    return gov.build_reporting_year_register_evidence(query=query(year), basis=basis(events),
        amendments=tuple(amendments), register_chains=tuple(chains))


def manifest(chains, *, year=2026):
    ordered = sorted(chains, key=lambda item: str(item.query.event_id))
    body = dict(company_id=str(query().company_id), income_year=year, chain_count=len(ordered), chains=[dict(
        event_id=str(item.query.event_id), income_year=int(item.query.income_year),
        anchor_sha256=item.chain.anchor.anchor_sha256, amendment_count=item.amendment_count,
        enumeration_sha256=item.enumeration_sha256) for item in ordered])
    return digest(['corporate-reporting-register-evidence-v1', body])


@pytest.mark.parametrize('count', [0, 1, 2])
def test_chain_updates_overlay_without_rewriting_original_reporting_receipt(count):
    anchor, _, _, first = fixture()
    receipts = (first, follow(first))[:count]
    chain = snapshot(anchor, receipts)
    result = build((anchor.original,), (chain,))
    old = gov.build_reporting_year_evidence(basis=basis((anchor.original,)), income_year=IncomeYear(2026), amendments=())
    assert result.original == old and result.original.supported_events[0].recorded == anchor.original
    assert result.register_chains == (chain,) and result.chain_count == 1
    assert result.chain_enumeration_sha256 == manifest((chain,))
    assert result.enumeration_sha256 == digest(['corporate-reporting-register-evidence-projection-v1', dict(
        company_id=str(query().company_id), income_year=2026, original_enumeration_sha256=old.enumeration_sha256,
        chain_enumeration_sha256=result.chain_enumeration_sha256)])
    assert chain.chain.effective_register_fact == (receipts[-1].command.replacement if receipts else first.command.withdrawal.target)
    gov.assert_reporting_year_register_evidence(result, query=query())


def test_amendment_changes_new_digest_only_and_all_values_are_immutable():
    anchor, _, _, first = fixture()
    before = build((anchor.original,), (snapshot(anchor),))
    after = build((anchor.original,), (snapshot(anchor, (first,)),))
    assert before.original == after.original
    assert before.enumeration_sha256 != after.enumeration_sha256
    with pytest.raises(FrozenInstanceError): after.chain_count = 0
    with pytest.raises(TypeError): after.original.supported_events[0].recorded.event.canonical_facts['phase'] = 'funding'


@pytest.mark.parametrize('kind,phase', [('cash_capital_increase','registered'),
    ('loss_coverage_capital_reduction','registered'), ('loss_coverage_capital_reduction','first_recognized_after_registration')])
def test_every_exact_eligible_original_including_off_year_is_required(kind, phase):
    anchor = original(kind=kind, phase=phase, year=2025)
    with pytest.raises(gov.CorporateGovernanceError): build((anchor.original,))
    result = build((anchor.original,), (snapshot(anchor),))
    assert result.chain_count == 1 and not result.original.supported_events


@pytest.mark.parametrize('kind,phase', [('cash_capital_increase','binding_subscription'),
    ('cash_capital_increase','restricted_payment'), ('loss_coverage_capital_reduction','decided_not_registered')])
def test_earlier_phases_are_preserved_but_do_not_require_an_rf_anchor(kind, phase):
    row = original(kind=kind, phase=phase, anchored=False)
    result = build((row,))
    assert result.chain_count == 0 and result.original.supported_events


def test_registered_cash_without_governance_earlier_phases_preserves_opening_position_contract():
    anchor = original(kind='cash_capital_increase')
    result = build((anchor.original,), (snapshot(anchor),))
    assert result.original.supported_events[0].status == 'recorded'
    assert result.original.supported_events[0].lifecycle_events == (anchor.original,)


def test_cross_year_cash_correction_keeps_original_chain_and_unchanged_blocked_groups():
    anchor = original(kind='cash_capital_increase')
    correction = replace(original(kind='cash_capital_increase', year=2027, number=22).original,
        correction_of_event_id=anchor.original.event.event_id)
    rows = (correction, anchor.original)
    result = build(rows, (snapshot(anchor),))
    assert result.original == gov.build_reporting_year_evidence(basis=basis(rows), income_year=IncomeYear(2026), amendments=())
    assert len(result.original.supported_events) == 2
    assert any(item.status == 'corrected' for item in result.original.supported_events)
    assert result.chain_count == 1
    with pytest.raises(gov.CorporateGovernanceError): build(rows)


def test_correction_row_without_rf_anchor_is_retained_but_is_not_a_new_eligible_original():
    anchor = original(kind='cash_capital_increase')
    correction = original(kind='cash_capital_increase', year=2027, number=22).original
    facts = dict(correction.event.canonical_facts); facts.pop('shareholderRegisterFact')
    correction = replace(correction, event=replace(correction.event, canonical_facts=facts),
        correction_of_event_id=anchor.original.event.event_id)
    result = build((anchor.original, correction), (snapshot(anchor),))
    assert result.chain_count == 1
    assert correction in tuple(row for item in result.original.supported_events for row in item.lifecycle_events)


@pytest.mark.parametrize('replacement', [False, True])
def test_ledger_reversed_and_corrected_originals_still_require_their_exact_chain(replacement):
    anchor = original()
    amendment = gov.CorporateLedgerAmendment(anchor.original.accounting_entry_id,
        gov.AccountingEntryReference(identifier(500)), gov.AccountingEntryReference(identifier(501)) if replacement else None,
        query().company_id, IncomeYear(2027), 'Historical reversal', query().actor_id, NOW)
    result = build((anchor.original,), (snapshot(anchor),), (amendment,))
    assert result.original.supported_events[0].status == ('corrected' if replacement else 'reversed')
    assert result.chain_count == 1
    with pytest.raises(gov.CorporateGovernanceError): build((anchor.original,), amendments=(amendment,))


def test_conflicting_cash_lifecycle_keeps_every_eligible_original_chain():
    first = original(kind='cash_capital_increase')
    second = original(kind='cash_capital_increase', number=22, reference=first.original.event.event_reference)
    rows = (first.original, second.original); chains = (snapshot(first), snapshot(second))
    result = build(rows, chains)
    assert result.original.supported_events[0].status == 'conflicting' and result.chain_count == 2
    assert result.chain_enumeration_sha256 == manifest(chains)
    assert result == build(tuple(reversed(rows)), chains)
    with pytest.raises(gov.CorporateGovernanceError): build(rows, tuple(reversed(chains)))


@pytest.mark.parametrize('attack', ['missing', 'duplicate', 'extra', 'wrong_original', 'wrong_company', 'wrong_actor',
    'wrong_year', 'wrong_event', 'wrong_count', 'wrong_head', 'wrong_effective', 'wrong_digest'])
def test_exact_bijection_and_carried_chain_commitments_fail_closed(attack):
    anchor = original(); chain = snapshot(anchor); rows = (anchor.original,); chains = (chain,)
    if attack == 'missing': chains = ()
    elif attack == 'duplicate': chains *= 2
    elif attack == 'extra': chains += (snapshot(original(number=23)),)
    elif attack == 'wrong_original': rows = (replace(anchor.original, recorded_at=NOW.replace(microsecond=123457)),)
    elif attack in ('wrong_company','wrong_actor','wrong_year','wrong_event'):
        changes = {'wrong_company':dict(company_id=type(chain.query.company_id)(identifier(800))),
            'wrong_actor':dict(actor_id=replace(chain.query.actor_id, subject=type(chain.query.actor_id.subject)(identifier(801)))),
            'wrong_year':dict(income_year=IncomeYear(2025)), 'wrong_event':dict(event_id=gov.SupportedCorporateEventId(identifier(802)))}
        chains = (replace(chain, query=replace(chain.query, **changes[attack])),)
    elif attack == 'wrong_count': chains = (replace(chain, amendment_count=True),)
    elif attack == 'wrong_head': chains = (replace(chain, chain=replace(chain.chain, head=fixture()[3].head)),)
    elif attack == 'wrong_effective': chains = (replace(chain, chain=replace(chain.chain, effective_register_fact=source(999))),)
    else: chains = (replace(chain, enumeration_sha256='f' * 64),)
    with pytest.raises(gov.CorporateGovernanceError): build(rows, chains)


@pytest.mark.parametrize('field', ['chain_count', 'chain_enumeration_sha256', 'enumeration_sha256', 'original', 'register_chains', 'query'])
def test_public_result_validation_rejects_untrusted_typed_port_claims(field):
    anchor = original(); value = build((anchor.original,), (snapshot(anchor),))
    replacements = dict(chain_count=True, chain_enumeration_sha256='f'*64, enumeration_sha256='f'*64,
        original=replace(value.original, enumeration_sha256='f'*64), register_chains=(), query=query(2025))
    with pytest.raises(gov.CorporateGovernanceError):
        gov.assert_reporting_year_register_evidence(replace(value, **{field:replacements[field]}), query=query())


def test_no_eligible_events_is_distinct_from_invalid_legacy_anchor():
    assert build().chain_count == 0
    row = original().original
    facts = dict(row.event.canonical_facts); facts.pop('shareholderRegisterFact')
    legacy = replace(row, event=replace(row.event, canonical_facts=facts))
    # The old year builder accepts this retained legacy shape. The additive
    # register projection cannot silently turn the missing anchor into zero.
    assert gov.build_reporting_year_evidence(basis=basis((legacy,)), income_year=IncomeYear(2026), amendments=()).supported_events
    with pytest.raises(gov.CorporateGovernanceError): build((legacy,))
