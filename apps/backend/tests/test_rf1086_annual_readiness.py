"""Annual conditions are owned by RF and bound to exact source evidence."""
import asyncio
from dataclasses import fields, replace
from uuid import uuid4

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CorrelationId
from test_rf1086_source_readiness import source_and_preview
from test_rf1086_source_admission import AdmissionHarness, COMPANY, YEAR


def ready_inputs():
    opening = str(uuid4())
    return rf.Rf1086AnnualReadinessInputs(COMPANY, YEAR, (opening,), (opening,), (str(uuid4()),),
        3, 0, 1, str(uuid4()), True, False, True, (),
        {family: 'a' * 64 for family in ('opening', 'ledger', 'banking', 'interview', 'documents')})


def build(inputs=None):
    return rf.build_rf1086_annual_readiness(*source_and_preview(), inputs or ready_inputs())


def test_complete_proof_binds_all_inputs_and_explicit_release_omissions():
    inputs = ready_inputs()
    proof = build(inputs)
    assert proof.readiness_status == 'ready'
    assert not proof.issues and not proof.required_warning_codes
    assert 'annual_prerequisites' not in proof.not_evaluated
    assert proof.not_evaluated == ('current_review_comments', 'filing_overrides', 'authority_permission',
                                  'billing_entitlement', 'technical_release', 'warning_acknowledgements')
    assert rf.rf1086_year_source_digest({field.name: getattr(proof, field.name) for field in fields(proof)
                                        if field.name != 'proof_sha256'}) == proof.proof_sha256
    rf.assert_rf1086_annual_readiness_matches(proof, *source_and_preview(), inputs)
    for family in inputs.evidence_sha256:
        changed = replace(inputs, evidence_sha256=dict(inputs.evidence_sha256) | {family: 'b' * 64})
        assert build(changed).proof_sha256 != proof.proof_sha256
    with pytest.raises(TypeError): inputs.evidence_sha256['opening'] = 'f' * 64


@pytest.mark.parametrize('change,code', [
    ({'opening_snapshot_ids': ()}, 'opening_balance_missing'),
    ({'opening_bank_snapshot_ids': ()}, 'opening_bank_input_missing_or_mismatched'),
    ({'opening_bank_snapshot_ids': (str(uuid4()),)}, 'opening_bank_input_missing_or_mismatched'),
    ({'unmatched_bank_count': 1}, 'unmatched_bank_transactions'),
    ({'has_unpaid_items': True}, 'unpaid_items_not_supported'),
    ({'authority_to_submit_confirmed': False}, 'annual_authority_not_confirmed'),
])
def test_each_preserved_hard_condition_blocks(change, code):
    proof = build(replace(ready_inputs(), **change))
    assert proof.readiness_status == 'blocked'
    assert code in {item.code for item in proof.issues if item.level == 'error'}


@pytest.mark.parametrize('change,code', [({'period_lock_ids': ()}, 'period_not_locked'),
    ({'bank_balance_confirmed': False}, 'bank_balance_not_confirmed'),
    ({'interview_source_id': None, 'bank_balance_confirmed': None, 'has_unpaid_items': None,
      'authority_to_submit_confirmed': None}, 'annual_data_missing')])
def test_preserved_warning_requires_explicit_later_acknowledgement(change, code):
    proof = build(replace(ready_inputs(), **change))
    assert proof.readiness_status == 'warning' and proof.required_warning_codes == (code,)
    assert not proof.accepted_warning_codes


@pytest.mark.parametrize('link', ['aksjonaerregisteroppgaven', 'Aksjonærregisteroppgaven', 'RF-1086 evidence'])
def test_accepted_document_warning_is_retained_from_owner_status(link):
    item = rf.Rf1086AnnualDocumentStatus(str(uuid4()), link, 'missing_accepted_warning')
    proof = build(replace(ready_inputs(), documents=(item,)))
    assert proof.readiness_status == 'ready'
    assert proof.accepted_warning_codes == ('missing_documents_accepted',)
    assert not proof.required_warning_codes
    assert build(replace(ready_inputs(), documents=(replace(item, linked_to='skattemelding'),))).issues == ()


@pytest.mark.parametrize('change', [
    {'company_id': type(COMPANY)(str(uuid4()))}, {'income_year': type(YEAR)(int(YEAR)-1)},
    {'bank_transaction_count': True}, {'unmatched_bank_count': -1}, {'unmatched_bank_count': 3},
    {'period_lock_ids': ('invalid',)}, {'opening_snapshot_ids': (str(uuid4()), str(uuid4()))},
    {'bank_balance_confirmed': 'true'}, {'has_unpaid_items': None},
    {'interview_source_id': None}, {'evidence_sha256': {}},
    {'documents': (rf.Rf1086AnnualDocumentStatus(str(uuid4()), 'rf-1086', 'unknown'),)},
])
def test_malformed_or_incomplete_owner_projection_is_unavailable(change):
    with pytest.raises(rf.Rf1086YearSourceError): build(replace(ready_inputs(), **change))


def test_forged_proof_cannot_remove_warnings_or_exclusions():
    inputs = replace(ready_inputs(), period_lock_ids=())
    proof = build(inputs)
    for changed in (replace(proof, readiness_status='ready'), replace(proof, issues=()),
                    replace(proof, not_evaluated=()), replace(proof, required_warning_codes=()),
                    replace(proof, proof_sha256='f' * 64)):
        with pytest.raises(rf.Rf1086YearSourceError):
            rf.assert_rf1086_annual_readiness_matches(changed, *source_and_preview(), inputs)


def annual_harness(h=None):
    from decimal import Decimal
    from talli_backend.application.annual_data_compatibility import LegacyAnnualDataView
    from talli_backend.application.shareholder_register_annual_documents import Rf1086AnnualDocumentInputs
    from talli_backend.application.shareholder_register_annual_ledger import Rf1086AnnualLedgerInputs
    from talli_backend.application.shareholder_register_annual_opening import Rf1086AnnualOpeningInputs
    from talli_backend.modules.ledger.public import OpeningBankInput, PeriodLock, PeriodLockId
    from talli_backend.modules.banking.public import BankYearReconciliation, BankYearReconciliationEvidence
    from talli_backend.shared.kernel import Money, Timestamp
    from test_rf1086_year_source import NOW
    from test_rf_annual_document_inputs import document
    h = h or AdmissionHarness()
    identity = str(uuid4())
    h.annual = {
        'annual_opening_inputs': Rf1086AnnualOpeningInputs(COMPANY, YEAR,
            (rf.Rf1086OpeningSource(COMPANY, rf.OpeningSnapshotId(identity), YEAR, 'a'*64, 1),)),
        'annual_ledger_inputs': Rf1086AnnualLedgerInputs(COMPANY, YEAR,
            (OpeningBankInput(identity, COMPANY, YEAR, Money(Decimal('123.45'), 'NOK'), h.actor, Timestamp(NOW)),),
            (PeriodLock(PeriodLockId(str(uuid4())), COMPANY, YEAR, 'Reviewed period', h.actor, Timestamp(NOW), False),)),
        'bank_year_evidence': BankYearReconciliationEvidence(BankYearReconciliation(COMPANY, YEAR, Timestamp(NOW), 3, 0, 1), 'b'*64),
        'annual_interview': LegacyAnnualDataView(str(uuid4()), COMPANY, YEAR,
            {'bank_balance_confirmed': True, 'has_unpaid_items': False, 'authority_to_submit_confirmed': True},
            (), False, 0, NOW.isoformat(), NOW.isoformat()),
        'annual_document_inputs': Rf1086AnnualDocumentInputs(COMPANY, YEAR, (document(),)),
    }
    def reader(name):
        async def run(*args):
            assert h.held
            h.calls.append(name)
            value = h.annual[name]
            if isinstance(value, Exception): raise value
            return value
        return run
    for name in h.annual: setattr(h.transaction, name, reader(name))
    return h


def read_annual(h):
    return asyncio.run(h.workflow.read_annual_readiness('token', company_id=COMPANY, income_year=YEAR,
        preview_id=h.preview.preview_id, correlation_id=CorrelationId('annual-readiness')))


def test_workflow_reads_every_owner_and_builds_policy_inside_admission(monkeypatch):
    h = annual_harness()
    builder = rf.build_rf1086_annual_readiness
    def checked(*args):
        assert h.held
        h.calls.append('annual_policy')
        return builder(*args)
    monkeypatch.setattr(rf, 'build_rf1086_annual_readiness', checked)
    proof = read_annual(h)
    assert proof.readiness_status == 'ready' and h.committed
    assert h.calls == ['bytes','guard','identity','source','preview','original','governance',
                       *h.annual, 'annual_policy', 'release']
    assert not hasattr(h.transaction, 'read_source_approval_context')


def test_same_count_metadata_changes_alter_proof_but_read_observation_time_does_not():
    from datetime import timedelta
    from talli_backend.shared.kernel import Timestamp
    h = annual_harness()
    first = read_annual(h)
    bank = h.annual['bank_year_evidence']
    h.annual['bank_year_evidence'] = replace(bank, reconciliation=replace(bank.reconciliation,
        observed_at=Timestamp(bank.reconciliation.observed_at.value + timedelta(seconds=1))))
    assert read_annual(h) == first
    documents = h.annual['annual_document_inputs']
    h.annual['annual_document_inputs'] = replace(documents, documents=(replace(documents.documents[0], name='Changed name'),))
    changed = read_annual(h)
    assert changed.issues == first.issues and changed.proof_sha256 != first.proof_sha256


@pytest.mark.parametrize('reader', ['annual_opening_inputs', 'annual_ledger_inputs', 'bank_year_evidence',
                                    'annual_interview', 'annual_document_inputs'])
def test_failed_owner_read_never_becomes_successful_empty_evidence(reader):
    h = annual_harness()
    h.annual[reader] = rf.ShareholderRegisterFilingError.unavailable()
    with pytest.raises(rf.ShareholderRegisterFilingError): read_annual(h)
    assert not h.committed and not h.held


@pytest.mark.parametrize('reader', ['annual_opening_inputs','annual_ledger_inputs','annual_interview','annual_document_inputs'])
def test_foreign_scope_owner_result_cannot_enter_proof(reader):
    h = annual_harness()
    h.annual[reader] = replace(h.annual[reader], income_year=type(YEAR)(int(YEAR)-1))
    with pytest.raises(rf.Rf1086YearSourceError): read_annual(h)
    assert not h.committed


def test_interview_changed_after_preflight_is_used_and_missing_answers_preserve_false_semantics():
    h = annual_harness()
    interview = h.annual['annual_interview']
    h.on_guard = lambda: h.annual.update(annual_interview=replace(interview, answers={'has_unpaid_items': True}))
    proof = read_annual(h)
    assert proof.readiness_status == 'blocked'
    assert {item.code for item in proof.issues} == {'unpaid_items_not_supported',
        'bank_balance_not_confirmed', 'annual_authority_not_confirmed'}


@pytest.mark.parametrize('kind', ['no_activity', 'formation', 'dividend', 'cash_issue',
                                  'cash_nominal_increase', 'loss_covering_reduction', 'mixed'])
def test_annual_input_proof_supports_full_year_events_without_replacing_them_with_opening(kind):
    from test_rf1086_source_production import source_case, source_for
    from test_rf1086_source_preview import preview_source
    case = source_case(kind)
    if kind == 'mixed':
        case = replace(case, share_snapshot=replace(case.share_snapshot, previous_paid_in_premium=0))
    source = source_for(case)
    preview = preview_source(source)[0]
    inputs = replace(ready_inputs(), company_id=source.company_id, income_year=source.income_year)
    proof = rf.build_rf1086_annual_readiness(source, preview, inputs)
    assert proof.readiness_status == 'ready'
    assert proof.source.evidence.source_sha256 == source.source_sha256
    assert proof.source.evidence.preview_id == preview.preview_id
