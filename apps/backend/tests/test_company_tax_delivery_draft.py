"""Retained draft byte identity and source-v2 coverage through public contracts."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from uuid import uuid4

import pytest

from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError, TaxDeliveryDraft, StoredTaxDeliveryDraft, decode_tax_delivery_draft,
    project_company_tax_source, verify_company_tax_source,
)
from talli_backend.shared.kernel import IdempotencyKey, Timestamp
from test_company_tax_delivery import ACTOR, COMPANY
from test_company_tax_schemas import prepared
from test_company_tax_source_facts import parse, source


@pytest.fixture(scope='module')
def draft():
    validator = PinnedTax2025Schemas()
    from talli_backend.modules.company_tax_filing.public import TaxDeliverySource
    from test_company_tax_delivery import raw_source
    envelope = prepared(validator, TaxDeliverySource(**raw_source()))
    return TaxDeliveryDraft(str(uuid4()), IdempotencyKey('retained-tax-draft-command'), ACTOR,
        envelope, validator.validate(envelope))


def test_retained_draft_restores_exact_xml_source_and_proof(draft):
    restored = decode_tax_delivery_draft(draft.canonical_json, draft.sha256)
    assert restored == draft and restored.canonical_json == draft.canonical_json
    assert restored.envelope.envelope_xml.encode() == draft.envelope.envelope_xml.encode()
    with pytest.raises(TypeError): restored.envelope.source.annual_data['answers']['changed'] = True


@pytest.mark.parametrize('change', ['space', 'duplicate', 'unicode', 'version', 'nonfinite', 'scope',
    'proof', 'xml', 'actor', 'uuid', 'extra', 'key', 'year-type', 'depth'])
def test_ambiguous_or_changed_retained_draft_never_decodes_even_with_a_new_storage_hash(draft, change):
    raw = draft.canonical_json
    value = json.loads(raw)
    body = value['draft']
    if change == 'space': raw += ' '
    elif change == 'duplicate': raw = raw.replace('"version":', '"version":"ignored","version":')
    elif change == 'unicode':
        body['envelope']['source']['annual_data']['note'] = 'ø'
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    elif change == 'depth': raw = '[' * 1100 + ']' * 1100
    else:
        if change == 'version': value['version'] = 'future'
        elif change == 'nonfinite': body['envelope']['source']['annual_data']['x'] = float('nan')
        elif change == 'scope': body['envelope']['source']['company_id']['value'] = str(uuid4())
        elif change == 'proof': body['validation']['review_sha256'] = 'b'*64
        elif change == 'xml': body['envelope']['tax_xml'] += '\n'
        elif change == 'actor': body['prepared_by']['kind'] = 'SYSTEM'
        elif change == 'uuid': body['filing_id'] = body['filing_id'].upper()
        elif change == 'extra': body['unexpected'] = True
        elif change == 'key': body['command_key']['value'] = 'short'
        elif change == 'year-type': body['envelope']['source']['income_year']['value'] = '2025'
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    with pytest.raises(ValueError): decode_tax_delivery_draft(raw, hashlib.sha256(raw.encode()).hexdigest())


def delivery_snapshot(draft):
    raw = source(True)
    raw.update(companyId=str(COMPANY), incomeYear=2025)
    raw['coverage'].update(companyId=str(COMPANY), incomeYear=2025)
    for values in raw['workspace'].values():
        for row in values:
            row['company_id'] = str(COMPANY)
    query, snapshot = parse(raw)
    proof = dict(snapshot.coverage) | {'companyId': str(COMPANY), 'declaredExtentValid': False,
        'contractVersion': 'company-tax-source-v2', 'declaredDeliveryExtentValid': True,
        'deliveryDraftArchiveTrackingValid': True,
        'declaredTables': sorted(['authority_permissions','authority_test_runs','delivery_drafts',
            'filing_overrides','filing_previews','filing_review_comments','filing_submissions','settlements']),
        'deliveryDraftCount': 1, 'deliveryDraftDigests': {draft.filing_id: draft.sha256}}
    retained = StoredTaxDeliveryDraft(draft, Timestamp(snapshot.as_of.value-timedelta(seconds=1)))
    return query, replace(snapshot, coverage=proof, contract_version='company-tax-source-v2', delivery_drafts=(retained,))


def test_v2_covers_retained_drafts_but_keeps_them_out_of_submission_and_authority_history(draft):
    query, snapshot = delivery_snapshot(draft)
    facts = project_company_tax_source(query, snapshot)
    assert facts.history_coverage.status == 'complete', facts.history_coverage.reasons
    assert facts.evidence.version.startswith('company-tax-source-v2:')
    assert facts.delivery_drafts[0].status == 'prepared_only'
    assert facts.recorded_submissions == facts.production_attempts == facts.outcomes == ()
    assert facts.readiness_status == 'blocked'
    assert verify_company_tax_source(query, facts.evidence, snapshot)
    assert not verify_company_tax_source(query, facts.evidence, replace(snapshot, delivery_drafts=()))


@pytest.mark.parametrize('change', ['extent', 'declared', 'legacy', 'count', 'digest', 'contract', 'omitted', 'v1', 'archive-tracking'])
def test_v2_cannot_claim_complete_coverage_with_a_missing_store_or_draft(draft, change):
    query, snapshot = delivery_snapshot(draft)
    proof = dict(snapshot.coverage)
    if change == 'extent': proof['declaredDeliveryExtentValid'] = False
    if change == 'declared': proof['declaredTables'] = proof['declaredTables'][:-1]
    if change == 'legacy': proof['declaredExtentValid'] = True
    if change == 'count': proof['deliveryDraftCount'] = True
    if change == 'digest': proof['deliveryDraftDigests'] = {draft.filing_id: 'b'*64}
    if change == 'contract': proof.pop('contractVersion')
    if change == 'archive-tracking': proof['deliveryDraftArchiveTrackingValid'] = False
    snapshot = replace(snapshot, coverage=proof)
    if change == 'omitted': snapshot = replace(snapshot, delivery_drafts=())
    if change == 'v1': snapshot = replace(snapshot, contract_version='company-tax-source-v1')
    assert project_company_tax_source(query, snapshot).history_coverage.status == 'incomplete'


def test_foreign_duplicate_future_or_unknown_version_history_is_unavailable(draft):
    query, snapshot = delivery_snapshot(draft)
    for changed in (replace(snapshot, contract_version='future'),
            replace(snapshot, delivery_drafts=snapshot.delivery_drafts*2),
            replace(snapshot, delivery_drafts=(replace(snapshot.delivery_drafts[0],
                recorded_at=Timestamp(snapshot.as_of.value+timedelta(seconds=1))),))):
        with pytest.raises(CompanyTaxError): project_company_tax_source(query, changed)


def test_archive_keeps_the_exact_original_under_positive_versioned_coverage(draft):
    from talli_backend.modules.company_tax_filing.public import archive_tax_delivery_drafts
    query,snapshot = delivery_snapshot(draft)
    result = archive_tax_delivery_drafts(query,snapshot)
    assert result.drafts[0].draft.canonical_json == draft.canonical_json
    assert result.source_sha256 == project_company_tax_source(query,snapshot).evidence.digest
    with pytest.raises(CompanyTaxError):
        archive_tax_delivery_drafts(query,replace(snapshot,coverage=None))
    with pytest.raises(CompanyTaxError):
        archive_tax_delivery_drafts(query,replace(snapshot,delivery_drafts=()))
