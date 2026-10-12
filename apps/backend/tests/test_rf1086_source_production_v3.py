"""Pure approval v3 binds retained v2 evidence; it grants no runtime authority."""
from dataclasses import fields, replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorKind, UserId
from test_rf1086_annual_readiness_v2 import inputs_for, uid
from test_rf1086_source_preview import preview_source
from test_rf1086_source_readiness_v2 import KINDS, recommit, record_mapping, replace_nested
from test_rf1086_source_production import manifest_basis as legacy_basis
from test_rf1086_year_source import basis as old_basis, prepare as old_prepare
from test_rf1086_year_source_v2 import CONFIRMED, prepare, v2_basis


def basis_v3(kind='cash_issue', *, amendments=2, source=None, annual_changes=None):
    source = source or prepare(*v2_basis(kind, amendments=amendments))
    preview = preview_source(source)[0]
    annual = rf.build_rf1086_annual_readiness_v2(source, preview,
        replace(inputs_for(source), **(annual_changes or {})))
    return rf.Rf1086SourceApprovalManifestBasisV3(source=source, preview=preview,
        annual_readiness=annual, actor_id=source.confirmed_by, entitlement_id=uid(70),
        review_sha256='f' * 64, acknowledged_warning_codes=annual.required_warning_codes)


def build(value):
    return rf.build_rf1086_source_approval_manifest_v3(value)


def check(approved, value):
    rf.assert_rf1086_source_approval_manifest_matches_v3(approved, value)


def serialize(approved):
    return rf.serialize_rf1086_source_approval_manifest_v3(approved)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('amendments', [0, 1, 2])
def test_manifest_v3_binds_explicit_source_codec_all_governance_digests_and_annual_v2(kind, amendments):
    value = basis_v3(kind, amendments=amendments)
    approved = build(value)
    manifest, source, preview = approved.manifest, value.source, value.preview
    assert type(approved) is rf.Rf1086SourceApprovalManifest
    assert manifest['schemaVersion'] == 'production-source-approval-v3'
    assert manifest['source'] == dict(codec='rf1086-year-source-v2', id=source.source_id.value,
        version=source.version, sha256=source.source_sha256, caseSha256=source.case_sha256)
    assert manifest['freshness'] == dict(companyIdentitySha256=source.freshness.company_identity_sha256,
        documentsSha256=source.freshness.documents_sha256,
        governanceReceiptsSha256=source.freshness.governance_receipts_sha256,
        governanceOriginalEnumerationSha256=source.freshness.governance_original_enumeration_sha256,
        governanceChainEnumerationSha256=source.freshness.governance_chain_enumeration_sha256,
        governanceProjectionSha256=source.freshness.governance_projection_sha256)
    assert 'governanceEnumerationSha256' not in manifest['freshness']
    proof_text = rf.serialize_rf1086_annual_readiness_v2(value.annual_readiness, source, preview)
    assert manifest['annualReadiness'] == dict(schemaVersion='rf1086-annual-readiness-binding-v2',
        proofSha256=value.annual_readiness.proof_sha256,
        proofTextSha256=sha256(proof_text.encode()).hexdigest(), proofText=proof_text)
    assert manifest['caseProfile'] == 'rf1086_full_year_v1'
    assert manifest['adapterVersion'] == 'rf1086-source-production-v1'
    assert manifest['documentOrderVersion'] == 'shareholder-id-utf8-sha256-v1'
    assert manifest['userId'] == str(value.actor_id.subject)
    assert manifest['entitlementId'] == value.entitlement_id
    assert manifest['review']['sha256'] == value.review_sha256
    assert manifest['predecessor'] is None
    text = serialize(approved)
    assert text == canonical(json.loads(text))
    assert approved.manifest_sha256 == sha256(text.encode()).hexdigest()
    check(approved, value)
    with pytest.raises(TypeError): manifest['source']['codec'] = 'rf1086-year-source-v1'
    with pytest.raises(TypeError): approved.underskjema_xml['other'] = '<changed/>'


def test_identical_filing_xml_keeps_distinct_original_one_and_two_amendment_approval_identity():
    bases = [basis_v3(amendments=n) for n in (0, 1, 2)]
    results = [build(value) for value in bases]
    assert len({value.preview.hovedskjema_xml for value in bases}) == 1
    assert all(value.preview.underskjema_xml == bases[0].preview.underskjema_xml for value in bases)
    assert len({result.manifest_sha256 for result in results}) == 3
    assert all(result.document_order == results[0].document_order for result in results)
    for result, changed in zip(results, bases[1:] + bases[:1]):
        with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'): check(result, changed)


@pytest.mark.parametrize('previous_codec', [1, 2])
def test_source_correction_ordinal_is_independent_of_source_and_approval_codec(previous_codec):
    command, context = v2_basis('no_activity')
    previous = old_prepare(*old_basis()) if previous_codec == 1 else prepare(command, context)
    corrected = prepare(replace(command, supersedes_source_id=previous.source_id,
        supersedes_source_sha256=previous.source_sha256, correction_reason='Corrected retained source'),
        context, previous=previous, source_id=rf.Rf1086YearSourceId(uid(9100)),
        confirmed_at=CONFIRMED + timedelta(days=1))
    value = basis_v3(source=corrected)
    approved = build(value)
    assert approved.manifest['source']['codec'] == 'rf1086-year-source-v2'
    assert approved.manifest['source']['version'] == 2
    assert approved.manifest['schemaVersion'] == 'production-source-approval-v3'
    assert approved.manifest['predecessor'] is None
    assert value.preview.hovedskjema_xml == preview_source(previous)[0].hovedskjema_xml
    other = build(basis_v3('no_activity'))
    assert approved.manifest_sha256 != other.manifest_sha256


@pytest.mark.parametrize('field,changed', [('actor_id', rf.ActorId(ActorKind.USER, UserId(uid(81)))),
    ('entitlement_id', uid(82)), ('review_sha256', 'a' * 64)])
def test_actor_entitlement_and_review_remain_part_of_approval_identity(field, changed):
    value = basis_v3()
    approved = build(value)
    alternative = replace(value, **{field: changed})
    assert build(alternative).manifest_sha256 != approved.manifest_sha256
    with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'): check(approved, alternative)


@pytest.mark.parametrize('family', ['opening', 'ledger', 'banking', 'interview', 'documents'])
def test_each_annual_owner_commitment_changes_approval_without_changing_xml(family):
    value = basis_v3()
    inputs = value.annual_readiness.annual_inputs
    proof = rf.build_rf1086_annual_readiness_v2(value.source, value.preview,
        replace(inputs, evidence_sha256=dict(inputs.evidence_sha256) | {family: 'b' * 64}))
    before, after = build(value), build(replace(value, annual_readiness=proof))
    assert before.document_order == after.document_order and before.underskjema_xml == after.underskjema_xml
    assert before.manifest_sha256 != after.manifest_sha256
    with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'):
        check(before, replace(value, annual_readiness=proof))


@pytest.mark.parametrize('field', ['companyIdentitySha256', 'documentsSha256', 'governanceReceiptsSha256',
    'governanceOriginalEnumerationSha256', 'governanceChainEnumerationSha256', 'governanceProjectionSha256'])
def test_rehashed_manifest_cannot_replace_any_freshness_commitment(field):
    value = basis_v3()
    approved = build(value)
    raw = json.loads(serialize(approved))
    raw['freshness'][field] = '0' * 64
    forged = replace(approved, manifest=raw, manifest_sha256=sha256(canonical(raw).encode()).hexdigest())
    with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'): check(forged, value)


@pytest.mark.parametrize('change', ['schema', 'codec', 'ordinal', 'source_hash', 'source_id', 'case_hash',
    'company', 'year_float', 'preview_id', 'profile', 'review_text', 'extra', 'missing',
    'annual_schema', 'annual_proof_hash', 'annual_text_hash', 'annual_text', 'xml', 'order', 'digest'])
def test_manifest_assertion_rejects_rehashed_partial_or_misbound_payloads(change):
    value = basis_v3()
    approved = build(value)
    raw = json.loads(serialize(approved))
    if change == 'schema': raw['schemaVersion'] = 'production-source-approval-v2'
    if change == 'codec': raw['source']['codec'] = 'rf1086-year-source-v1'
    if change == 'ordinal': raw['source']['version'] = 3
    if change == 'source_hash': raw['source']['sha256'] = '0' * 64
    if change == 'source_id': raw['source']['id'] = uid(9101)
    if change == 'case_hash': raw['source']['caseSha256'] = '0' * 64
    if change == 'company': raw['companyId'] = uid(9102)
    if change == 'year_float': raw['incomeYear'] = float(raw['incomeYear'])
    if change == 'preview_id': raw['preview']['id'] = uid(9103)
    if change == 'profile': raw['preview']['renderingProfile'] = 'unknown'
    if change == 'review_text': raw['preview']['reviewTextSha256'] = '0' * 64
    if change == 'extra': raw['verified'] = True
    if change == 'missing': del raw['freshness']
    if change == 'annual_schema': raw['annualReadiness']['schemaVersion'] = 'rf1086-annual-readiness-binding-v1'
    if change == 'annual_proof_hash': raw['annualReadiness']['proofSha256'] = '0' * 64
    if change == 'annual_text_hash': raw['annualReadiness']['proofTextSha256'] = '0' * 64
    if change == 'annual_text': raw['annualReadiness']['proofText'] += '\n'
    updates = dict(manifest=raw, manifest_sha256=sha256(canonical(raw).encode()).hexdigest())
    if change == 'xml': updates['underskjema_xml'] = {approved.document_order[0]: '<changed/>'}
    if change == 'order': updates['document_order'] = ()
    if change == 'digest': updates['manifest_sha256'] = '0' * 64
    with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'):
        check(replace(approved, **updates), value)


@pytest.mark.parametrize('change', ['missing_annual', 'old_source', 'old_annual', 'source_hash', 'preview_scope',
    'preview_payload', 'preview_id', 'annual_scope', 'annual_shape', 'annual_omissions', 'blocked',
    'review_hash', 'entitlement', 'actor_kind', 'untyped_actor', 'predecessor_reason', 'predecessor_hash',
    'source_ordinal_bool', 'source_year_float', 'preview_year_float', 'actor_subject_type', 'predecessor_id_type'])
def test_approval_requires_valid_v2_source_preview_annual_and_review_basis(change):
    value = basis_v3()
    if change == 'missing_annual': value = replace(value, annual_readiness=None)
    if change == 'old_source': value = replace(value, source=legacy_basis().source)
    if change == 'old_annual':
        legacy = legacy_basis()
        proof = rf.build_rf1086_annual_readiness(legacy.source, legacy.preview, inputs_for(legacy.source))
        value = replace(value, annual_readiness=proof)
    if change == 'source_hash': value = replace(value, source=replace(value.source, source_sha256='0' * 64))
    if change == 'preview_scope': value = replace(value, preview=replace(value.preview, company_id=rf.CompanyId(uid(9104))))
    if change == 'preview_payload': value = replace(value, preview=replace(value.preview, hovedskjema_xml='<changed/>'))
    if change == 'preview_id': value = replace(value, preview=replace(value.preview, preview_id=rf.PreviewId(uid(9105))))
    if change == 'annual_scope': value = replace(value, annual_readiness=replace(value.annual_readiness,
        annual_inputs=replace(value.annual_readiness.annual_inputs, income_year=rf.IncomeYear(2024))))
    if change == 'annual_shape': value = replace(value, annual_readiness=replace(value.annual_readiness,
        source=record_mapping(value.annual_readiness.source)))
    if change == 'annual_omissions': value = replace(value, annual_readiness=recommit(replace(value.annual_readiness, not_evaluated=())))
    if change == 'blocked': value = basis_v3(annual_changes={'has_unpaid_items': True})
    if change == 'review_hash': value = replace(value, review_sha256='invalid')
    if change == 'entitlement': value = replace(value, entitlement_id='not-uuid')
    if change == 'actor_kind': value = replace(value, actor_id=rf.ActorId(ActorKind.SYSTEM, value.actor_id.subject))
    if change == 'untyped_actor': value = replace(value, actor_id=record_mapping(value.actor_id))
    if change == 'source_ordinal_bool': value = replace(value, source=replace(value.source, version=True))
    if change == 'source_year_float': value = replace(value, source=replace(value.source,
        income_year=rf.IncomeYear(float(value.source.income_year.value))))
    if change == 'preview_year_float': value = replace(value, preview=replace(value.preview,
        income_year=rf.IncomeYear(float(value.preview.income_year.value))))
    if change == 'actor_subject_type': value = replace(value, actor_id=replace(value.actor_id,
        subject=rf.Rf1086YearSourceId(str(value.actor_id.subject))))
    if change == 'predecessor_id_type': value = replace(value, predecessor=rf.Rf1086SourceCorrectionPredecessor(
        rf.PreviewId(uid(60)), 'c' * 64, 'Reviewed'))
    if change in ('predecessor_reason', 'predecessor_hash'):
        value = replace(value, predecessor=rf.Rf1086SourceCorrectionPredecessor(rf.SubmissionId(uid(60)),
            'invalid' if change == 'predecessor_hash' else 'c' * 64,
            '  ' if change == 'predecessor_reason' else 'Reviewed'))
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'): build(value)


@pytest.mark.parametrize('path', [('annual_readiness', 'source', 'evidence'),
    ('annual_readiness', 'source', 'evidence', 'freshness'), ('annual_readiness', 'annual_inputs')])
def test_nested_record_to_mapping_substitution_never_becomes_an_approval(path):
    value = basis_v3()
    forged = replace_nested(value, path, record_mapping)
    assert rf.rf1086_year_source_digest(forged.annual_readiness) == rf.rf1086_year_source_digest(value.annual_readiness)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'): build(forged)


def subclass_record(value):
    kind = type('RecordSubtype', (type(value),), {})
    return kind(**record_mapping(value))


class StringSubtype(str):
    pass


@pytest.mark.parametrize('path,transform', [
    ((), subclass_record), (('source',), subclass_record), (('preview',), subclass_record),
    (('actor_id',), subclass_record), (('actor_id', 'subject'), subclass_record),
    (('annual_readiness',), subclass_record), (('predecessor',), subclass_record),
    (('preview', 'preview_id'), subclass_record), (('preview', 'preview_text'), StringSubtype),
    (('review_sha256',), StringSubtype), (('entitlement_id',), StringSubtype),
    (('predecessor', 'reason'), StringSubtype),
])
def test_new_basis_rejects_equivalent_record_and_scalar_subtypes(path, transform):
    value = replace(basis_v3(), predecessor=rf.Rf1086SourceCorrectionPredecessor(
        rf.SubmissionId(uid(60)), 'c' * 64, 'Reviewed'))
    forged = replace_nested(value, path, transform)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'): build(forged)


@pytest.mark.parametrize('change', ['subclass', 'digest_subclass', 'year_float', 'ordinal_bool',
    'manifest_string_subclass', 'document_key_subclass', 'xml_subclass'])
def test_assertion_and_serializer_require_exact_result_shapes(change):
    value = basis_v3()
    approved = build(value)
    changed = approved
    if change == 'subclass': changed = subclass_record(approved)
    if change == 'digest_subclass': changed = replace(approved, manifest_sha256=StringSubtype(approved.manifest_sha256))
    if change in ('year_float', 'ordinal_bool', 'manifest_string_subclass'):
        raw = json.loads(serialize(approved))
        if change == 'year_float': raw['incomeYear'] = float(raw['incomeYear'])
        if change == 'ordinal_bool': raw['source']['version'] = True
        if change == 'manifest_string_subclass': raw['companyId'] = StringSubtype(raw['companyId'])
        changed = replace(approved, manifest=raw, manifest_sha256=sha256(canonical(raw).encode()).hexdigest())
    if change == 'document_key_subclass': changed = replace(approved,
        document_order=tuple(StringSubtype(key) for key in approved.document_order))
    if change == 'xml_subclass': changed = replace(approved,
        underskjema_xml={key: StringSubtype(xml) for key, xml in approved.underskjema_xml.items()})
    with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'): check(changed, value)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'): serialize(changed)


@pytest.mark.parametrize('numeric_type', [int, float, Decimal])
def test_source_owner_retains_accepted_economic_numeric_representations(numeric_type):
    command, context = v2_basis('no_activity')
    paid_in = replace(command.paid_in, **{field.name: numeric_type(getattr(command.paid_in, field.name))
        for field in fields(command.paid_in)})
    value = basis_v3(source=prepare(replace(command, paid_in=paid_in), context))
    approved = build(value)
    check(approved, value)
    assert approved.manifest_sha256 == sha256(serialize(approved).encode()).hexdigest()


@pytest.mark.parametrize('required', [False, True])
def test_accepted_document_warning_is_distinct_from_required_owner_acknowledgements(required):
    item = rf.Rf1086AnnualDocumentStatus(uid(9011), 'RF-1086 evidence', 'missing_accepted_warning')
    changes = {'documents': (item,)} | ({'period_lock_ids': (), 'bank_balance_confirmed': False} if required else {})
    value = basis_v3(annual_changes=changes)
    approved = build(value)
    assert approved.manifest['review']['acknowledgedWarningCodes'] == value.annual_readiness.required_warning_codes
    assert value.annual_readiness.accepted_warning_codes == ('missing_documents_accepted',)
    assert build(replace(value, acknowledged_warning_codes=tuple(reversed(value.acknowledged_warning_codes)))) == approved
    for wrong in (('missing_documents_accepted',), ('unknown',), (*value.acknowledged_warning_codes, 'unknown'),
                  (*value.acknowledged_warning_codes, *value.acknowledged_warning_codes) if required else ('unknown', 'unknown')):
        with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
            build(replace(value, acknowledged_warning_codes=wrong))
    if required:
        with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
            build(replace(value, acknowledged_warning_codes=()))


def test_exact_submission_predecessor_reason_and_identity_are_separate_from_source_correction():
    prior = rf.Rf1086SourceCorrectionPredecessor(rf.SubmissionId(uid(60)), 'c' * 64, '  Reviewed — årsak\n  ')
    value = replace(basis_v3(), predecessor=prior)
    approved = build(value)
    assert approved.manifest['predecessor'] == dict(submissionId=prior.submission_id.value,
        manifestSha256=prior.manifest_sha256, reason=prior.reason)
    assert value.source.version == 1
    for changed in (None, replace(prior, reason=prior.reason.strip()), replace(prior, manifest_sha256='d' * 64),
                    replace(prior, submission_id=rf.SubmissionId(uid(61)))):
        with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'):
            check(approved, replace(value, predecessor=changed))


def test_utf8_shareholder_order_and_journal_keys_preserve_exact_non_uuid_names():
    command, context = v2_basis('no_activity')
    names = ('😀', 'é', 'e\u0301', ' A ')
    case = command.case
    case = replace(case, shareholders=tuple(replace(case.shareholders[0], id=name,
        name=f'Owner {index}', national_id=str(99000000000 + index)) for index, name in enumerate(names)),
        shareholder_snapshots=tuple(replace(case.shareholder_snapshots[0], shareholder_id=name,
            previous_share_count=25, current_share_count=25) for name in names))
    value = basis_v3(source=prepare(replace(command, case=case), context))
    approved = build(value)
    ordered = sorted(names, key=lambda name: name.encode())
    keys = tuple('source_' + sha256(('rf1086-source-shareholder-v1:' + name).encode()).hexdigest() for name in ordered)
    assert [row['shareholderId'] for row in approved.manifest['documentHashes'][1:]] == ordered
    assert approved.document_order == keys
    assert approved.underskjema_xml == dict(zip(keys, [value.preview.underskjema_xml[name] for name in ordered]))
    assert all(len('post_underskjema:' + key) <= 120 for key in keys)
    reversed_preview = replace(value.preview, underskjema_xml=dict(reversed(tuple(value.preview.underskjema_xml.items()))))
    reversed_annual = rf.build_rf1086_annual_readiness_v2(value.source, reversed_preview, value.annual_readiness.annual_inputs)
    assert build(replace(value, preview=reversed_preview, annual_readiness=reversed_annual)) == approved


@pytest.mark.parametrize('version', [1, 2])
def test_old_and_new_builders_and_serializers_do_not_cross_versions(version):
    legacy = legacy_basis()
    if version == 2:
        legacy = replace(legacy, annual_readiness=rf.build_rf1086_annual_readiness(
            legacy.source, legacy.preview, inputs_for(legacy.source)))
    old = rf.build_rf1086_source_approval_manifest(legacy)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'): build(legacy)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'): serialize(old)
    value = basis_v3()
    new = build(value)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        rf.build_rf1086_source_approval_manifest(value)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        rf.serialize_rf1086_source_approval_manifest(new)


@pytest.mark.parametrize('change', ['schema', 'codec', 'binding', 'digest', 'untyped'])
def test_new_serializer_requires_explicit_version_markers_and_exact_hash(change):
    approved = build(basis_v3())
    raw = json.loads(serialize(approved))
    if change == 'schema': raw['schemaVersion'] = 'production-source-approval-v2'
    if change == 'codec': raw['source']['codec'] = 'rf1086-year-source-v1'
    if change == 'binding': raw['annualReadiness']['schemaVersion'] = 'rf1086-annual-readiness-binding-v1'
    changed = replace(approved, manifest=raw, manifest_sha256=sha256(canonical(raw).encode()).hexdigest())
    if change == 'digest': changed = replace(changed, manifest_sha256='0' * 64)
    if change == 'untyped': changed = record_mapping(changed)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'): serialize(changed)


def test_new_manifest_does_not_activate_legacy_claim_inspection_or_archive_preparation():
    from test_rf1086_source_approval_archive import source_archive, read
    original = source_archive()
    assert read(original) is original
    value = basis_v3('no_activity')
    approved = build(value)
    payload = sha256(rf.serialize_rf1086_source_preview(value.preview).encode()).hexdigest()
    old_approval, line = original.approvals[0], original.source_approval_lineage[0]
    approval = replace(old_approval, preview_id=value.preview.preview_id.value,
        user_id=str(value.actor_id.subject), approved_by=str(value.actor_id.subject),
        payload_hash=payload, manifest_hash=approved.manifest_sha256, manifest=approved.manifest)
    retained = rf.Rf1086RetainedSourceApproval(approval, serialize(approved))
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        rf.inspect_rf1086_retained_source_approval(retained, approval_id=rf.ApprovalId(approval.id),
            manifest_sha256=approved.manifest_sha256, actor_id=value.actor_id)
    changed = replace(original, approvals=(approval,), source_approval_lineage=(replace(line,
        source=value.source, source_preview=value.preview, source_id=value.source.source_id.value,
        source_sha256=value.source.source_sha256, payload_sha256=payload,
        manifest_text=serialize(approved), manifest_sha256=approved.manifest_sha256),))
    with pytest.raises(rf.ShareholderRegisterFilingError): read(changed)


def test_pure_v3_basis_does_not_open_runtime_approval_admission():
    from test_rf1086_source_approval import ApprovalHarness
    harness = ApprovalHarness()
    value = basis_v3('no_activity')
    harness.source, harness.current, harness.preview = value.source, value.source, value.preview
    with pytest.raises(rf.Rf1086YearSourceError): harness.approve()
    assert harness.writes == [] and not harness.held and not harness.committed
