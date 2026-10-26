"""Current-source binding and submit-once policy through Tax's public interface."""
from dataclasses import FrozenInstanceError, dataclass
import json
from pathlib import Path
from uuid import uuid4

import pytest

from talli_backend.modules.company_tax_filing.public import (
    TaxDeliverySource, TaxMutationDisposition, TaxMutationIntent, TaxMutationKind,
    TaxMutationRecord, plan_tax_mutation, prepare_tax_delivery, tax_delivery_digest,
    verify_tax_review,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId

COMPANY = CompanyId('00000000-0000-4000-8000-000000000152')
ACTOR = ActorId(ActorKind.USER, UserId('00000000-0000-4000-8000-000000000153'))
CASES = json.loads((Path(__file__).resolve().parents[3] / 'architecture/evidence/issues/152/legacy-characterization.json').read_text())['cases']


def raw_source(case='supported-dividend'):
    value = json.loads(json.dumps(next(x['input'] for x in CASES if x['id'] == case)))
    annual, entries, actions = value['annualData'], value['ledgerEntries'], value['holdingActions']
    annual['answers']['company_tax_additional_attachments'] = 'none'
    for row in (annual, *entries, *actions):
        row['company_id'], row['income_year'] = str(COMPANY), 2025
    return dict(company_id=COMPANY, income_year=IncomeYear(2025), organization_number=value['companyOrgNumber'],
                annual_data=annual, ledger_entries=entries, holding_actions=actions,
                upstream_sha256={name: tax_delivery_digest(rows) for name, rows in
                                 [('annual', annual), ('ledger', entries), ('investments', actions)]})


def prepared(source=None):
    return prepare_tax_delivery(source or TaxDeliverySource(**raw_source()), party_number='123456',
                                current_document_reference='current-document-2025', schema_sha256='a' * 64)


def verify(envelope, **changes):
    return verify_tax_review(envelope, **(dict(expected_review_sha256=envelope.review_sha256,
        current_source=envelope.source, current_schema_sha256=envelope.schema_sha256,
        current_document_reference=envelope.current_document_reference) | changes))


@pytest.mark.parametrize('case', ['supported-dividend', 'no-activity-zero'])
def test_supported_sources_generate_the_two_statutory_documents_bound_to_current_reference(case):
    source = TaxDeliverySource(**raw_source(case)); envelope = prepared(source)
    assert '<skattemelding xmlns=' in envelope.tax_xml
    assert 'naeringsspesifikasjon' in envelope.business_xml
    assert '<dokumentidentifikator>current-document-2025</dokumentidentifikator>' in envelope.envelope_xml
    assert envelope.envelope_xml.count('<dokument>') == 2
    verify(envelope, current_source=source)


def test_source_copy_cannot_be_changed_by_nested_input_mutation():
    values = raw_source(); source = TaxDeliverySource(**values); digest = source.source_sha256
    values['annual_data']['answers']['shareholder_loans'] = True
    values['ledger_entries'].clear(); values['holding_actions'].clear()
    assert source.source_sha256 == digest
    with pytest.raises(TypeError): source.annual_data['answers']['shareholder_loans'] = True
    with pytest.raises(FrozenInstanceError): source.income_year = IncomeYear(2024)


def test_nested_mutable_objects_are_snapshotted_before_source_freezing():
    @dataclass
    class Metadata:
        references: list[str]
    value = Metadata(['original']); values = raw_source(); values['annual_data']['metadata'] = value
    source = TaxDeliverySource(**values); digest = source.source_sha256
    value.references.append('changed'); value.references = ['replacement']
    assert source.source_sha256 == digest
    assert source.annual_data['metadata']['references'] == ('original',)


@pytest.mark.parametrize('change', ['annual', 'ledger', 'investments', 'schema', 'current-reference', 'review-digest'])
def test_review_cannot_authorize_changed_source_or_payload(change):
    values = raw_source(); envelope = prepared(TaxDeliverySource(**values)); expected = envelope.review_sha256
    if change in ('annual', 'ledger', 'investments'):
        values['upstream_sha256'][change] = 'b' * 64
        with pytest.raises(ValueError): verify(envelope, current_source=TaxDeliverySource(**values))
    else:
        # Retain the original reviewed envelope and vary the independently read
        # current value. Altering the envelope would only test its own checksum.
        changed = ({'current_schema_sha256': 'b' * 64} if change == 'schema' else
                   {'current_document_reference': 'another-document'} if change == 'current-reference' else
                   {'expected_review_sha256': 'b' * 64})
        with pytest.raises(ValueError): verify(envelope, **changed)


def test_document_preparation_does_not_decide_common_annual_readiness():
    values = raw_source(); values['annual_data']['answers'].update(
        bank_balance_confirmed=False, has_unpaid_items=True, authority_to_submit_confirmed=False)
    # These facts remain in the immutable review. The application must consume
    # Annual's authoritative decision before it permits approval or effects.
    envelope = prepared(TaxDeliverySource(**values))
    assert envelope.source.annual_data['answers']['has_unpaid_items'] is True


def test_delivery_does_not_apply_2025_schemas_and_codes_to_a_different_income_year():
    values = raw_source()
    values['income_year'] = IncomeYear(2026)
    for row in (values['annual_data'], *values['ledger_entries'], *values['holding_actions']):
        row['income_year'] = 2026
    with pytest.raises(ValueError, match='2025 schema'):
        prepared(TaxDeliverySource(**values))


@pytest.mark.parametrize('answer', [None, True, False, '', 'unknown', 'required', 'NONE', ['none']])
def test_attachments_never_default_or_coerce_to_supported(answer):
    values = raw_source(); values['annual_data']['answers']['company_tax_additional_attachments'] = answer
    with pytest.raises(ValueError): prepared(TaxDeliverySource(**values))


@pytest.mark.parametrize('value', ['false', 0, [], None])
def test_boolean_truthiness_cannot_clear_a_tax_readiness_gate(value):
    values = raw_source(); values['annual_data']['answers']['shareholder_loans'] = value
    with pytest.raises(ValueError): prepared(TaxDeliverySource(**values))


def test_wrong_year_foreign_scope_duplicate_identity_nonfinite_and_missing_enumeration_refuse():
    for field in ('annual_data', 'ledger_entries', 'holding_actions'):
        values = raw_source(); row = values[field] if field == 'annual_data' else values[field][0]
        row['company_id'] = str(uuid4())
        with pytest.raises(ValueError): TaxDeliverySource(**values)
        values = raw_source(); row = values[field] if field == 'annual_data' else values[field][0]
        row['income_year'] = 2024
        with pytest.raises(ValueError): TaxDeliverySource(**values)
    values = raw_source(); values['ledger_entries'].append(values['ledger_entries'][0])
    with pytest.raises(ValueError): TaxDeliverySource(**values)
    values = raw_source(); values['annual_data']['annual_full_time_equivalents'] = float('nan')
    with pytest.raises(ValueError): TaxDeliverySource(**values)
    values = raw_source(); del values['upstream_sha256']['investments']
    with pytest.raises(ValueError): TaxDeliverySource(**values)


def intent(**changes):
    values = dict(filing_id='00000000-0000-4000-8000-000000000154', company_id=COMPANY,
                  income_year=IncomeYear(2025), approved_by=ACTOR, approval_sha256='a' * 64,
                  kind=TaxMutationKind.CREATE_INSTANCE, request_sha256='b' * 64)
    return TaxMutationIntent(**(values | changes))


def test_existing_uncertainty_never_authorizes_another_post_and_completed_replay_is_immutable():
    request = intent()
    assert plan_tax_mutation(request, None) is TaxMutationDisposition.EXECUTE
    assert plan_tax_mutation(request, TaxMutationRecord(request, 'uncertain')) is TaxMutationDisposition.RECONCILE
    result = {'instanceId': '12345/00000000-0000-4000-8000-000000000155'}
    completed = TaxMutationRecord(request, 'completed', result); result['instanceId'] = 'tampered'
    assert plan_tax_mutation(request, completed) is TaxMutationDisposition.REPLAY
    assert completed.result['instanceId'] != 'tampered'
    with pytest.raises(ValueError): TaxMutationRecord(request, 'completed')
    with pytest.raises(ValueError): TaxMutationRecord(request, 'uncertain', {})
    with pytest.raises(ValueError): TaxMutationRecord(request, 'completed', {})
    with pytest.raises(ValueError): TaxMutationRecord(request, 'completed', {'instanceId': 'unbound'})
    with pytest.raises(ValueError): TaxMutationRecord(request, 'completed', {'instanceId': completed.result['instanceId'], 'accessToken': 'must-not-be-retained'})


@pytest.mark.parametrize('changes', [
    {'company_id': CompanyId('00000000-0000-4000-8000-000000000156')},
    {'income_year': IncomeYear(2024)}, {'approval_sha256': 'c' * 64}, {'request_sha256': 'c' * 64},
    {'kind': TaxMutationKind.UPLOAD_ENVELOPE},
    {'approved_by': ActorId(ActorKind.USER, UserId('00000000-0000-4000-8000-000000000157'))},
])
def test_ambiguous_mutation_cannot_be_rebound_to_changed_authority_or_scope(changes):
    original = intent(); altered = intent(**changes)
    assert altered.identity_sha256 != original.identity_sha256
    with pytest.raises(ValueError): plan_tax_mutation(altered, TaxMutationRecord(original, 'uncertain'))
