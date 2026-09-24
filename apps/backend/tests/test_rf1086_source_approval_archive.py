"""Full-year approval archives retain their original identity after live facts change."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict, fields, replace
from hashlib import sha256
import json
from uuid import UUID

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_source_production import manifest_basis, source_for, source_case
from test_rf1086_year_source import ACTOR, NOW


def source_archive(kind='no_activity'):
    basis = manifest_basis(source_for(source_case(kind)))
    source, preview = basis.source, basis.preview
    company, year, actor = str(source.company_id), int(source.income_year), str(ACTOR.subject)
    payload = sha256(rf.serialize_rf1086_source_preview(preview).encode()).hexdigest()
    time = NOW.isoformat()
    bridge = rf.Rf1086ArchiveSourceReviewBridge(preview.preview_id.value, company, year,
        source.source_id.value, source.source_sha256, payload, actor, time)
    warnings = tuple(sorted({issue.code for issue in preview.readiness_issues}))
    review = {'version': 'rf1086-source-review-v1', 'binding': asdict(bridge),
        'scope': {'companyId': company, 'incomeYear': year, 'previewId': bridge.preview_id,
            'sourceId': bridge.source_id, 'sourceSha256': bridge.source_sha256,
            'entitlementId': basis.entitlement_id, 'warningCodes': list(warnings), 'blockers': []},
        'comments': [], 'overrides': [],
        'permission': {'company_id': company, 'obligation': 'aksjonaerregisteroppgaven',
            'submitter_user_id': actor, 'confirmed_by': actor, 'production_enabled': True},
        'pilot': {'id': basis.entitlement_id, 'company_id': company, 'income_year': year,
            'user_id': actor, 'obligation': 'aksjonaerregisteroppgaven', 'case_profile': 'rf1086_full_year_v1',
            'status': 'active', 'system_user_request_id': str(UUID(int=802)),
            'system_user_external_reference': 'retained-authority-reference'},
        'request': {'id': str(UUID(int=802)), 'company_id': company, 'initiating_owner_user_id': actor,
            'obligation': 'aksjonaerregisteroppgaven', 'status': 'accepted',
            'preflight_verified_at': time, 'external_ref': 'retained-authority-reference'},
        'storedReleaseReady': True, 'technicalReleaseReady': True}
    review_text = json.dumps(review, sort_keys=True, ensure_ascii=False)
    review_sha = sha256(review_text.encode()).hexdigest()
    approved = rf.build_rf1086_source_approval_manifest(replace(basis, review_sha256=review_sha,
        acknowledged_warning_codes=warnings))
    approval = rf.Rf1086ApprovalRecord(str(UUID(int=803)), basis.entitlement_id, bridge.preview_id,
        company, actor, year, 'aksjonaerregisteroppgaven', 'rf1086_full_year_v1',
        'rf1086-source-production-v1', payload, approved.manifest_sha256, approved.manifest,
        actor, time, None, None)
    projection = rf.Rf1086PreviewRecord(bridge.preview_id, company, None, year,
        'aksjonaerregisteroppgaven', preview.readiness_status, preview.readiness_issues,
        preview.preview_text, preview.hovedskjema_xml, approved.underskjema_xml, 'rf1086-full-year-v1', time)
    lineage = rf.Rf1086ArchiveSourceApprovalLineage(approval_id=approval.id, preview_id=bridge.preview_id,
        company_id=company, income_year=year, source_id=bridge.source_id, source_sha256=bridge.source_sha256,
        payload_sha256=payload, manifest_text=rf.serialize_rf1086_source_approval_manifest(approved),
        manifest_sha256=approved.manifest_sha256, review_sha256=review_sha, review_text=review_text,
        approved_by=actor, created_at=time, source=source, source_preview=preview, bridge=bridge)
    return rf.Rf1086ArchiveSnapshot(source.company_id, source.income_year, previews=(projection,),
        approvals=(approval,), source_approval_lineage=(lineage,))


def read(snapshot):
    class Store:
        async def archive_source(self, query): return snapshot
        async def read_current_year_source(self, query): raise AssertionError('historical read consulted current head')
    return asyncio.run(rf.create_rf1086_preparation_service(Store()).archive_source(
        rf.Rf1086ArchiveQuery(snapshot.company_id, snapshot.income_year, ACTOR)))


@pytest.mark.parametrize('kind', ['no_activity', 'formation', 'dividend', 'cash_issue', 'loss_covering_reduction'])
def test_original_source_approval_remains_readable_without_current_admission(kind):
    original = source_archive(kind)
    # Current actor/permission/readiness is irrelevant to this historical proof.
    original = replace(original, permissions=(), review_comments=())
    assert read(original) is original
    assert original.source_approval_lineage[0].source.command.documents
    assert original.source_approval_lineage[0].review_text
    with pytest.raises(TypeError): original.approvals[0].manifest['review']['sha256'] = 'changed'


@pytest.mark.parametrize('field,value', [
    ('approval_id', str(UUID(int=999))), ('preview_id', str(UUID(int=999))),
    ('source_id', str(UUID(int=999))), ('company_id', str(UUID(int=999))), ('income_year', 2024),
    ('source_sha256', 'a'*64), ('payload_sha256', 'a'*64), ('manifest_sha256', 'a'*64),
    ('review_sha256', 'a'*64), ('review_text', '{}'), ('manifest_text', '{}'), ('approved_by', str(UUID(int=999))),
])
def test_incomplete_or_changed_retained_binding_is_not_published(field, value):
    original = source_archive(); lineage = original.source_approval_lineage[0]
    with pytest.raises(rf.ShareholderRegisterFilingError):
        read(replace(original, source_approval_lineage=(replace(lineage, **{field: value}),)))


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'untyped', 'bridge', 'source', 'preview', 'projection', 'actor', 'unknown_manifest'])
def test_archive_rejects_missing_or_conflicting_lineage(change):
    original = source_archive(); line = original.source_approval_lineage[0]
    if change == 'missing': original = replace(original, source_approval_lineage=())
    if change == 'duplicate': original = replace(original, source_approval_lineage=(line,line))
    if change == 'untyped': original = replace(original, source_approval_lineage=({},))
    if change == 'bridge': original = replace(original, source_approval_lineage=(replace(line,bridge=replace(line.bridge,source_sha256='a'*64)),))
    if change == 'source': original = replace(original, source_approval_lineage=(replace(line,source=replace(line.source,case_sha256='a'*64)),))
    if change == 'preview': original = replace(original, source_approval_lineage=(replace(line,source_preview=replace(line.source_preview,preview_text='changed')),))
    if change == 'projection': original = replace(original,previews=(replace(original.previews[0],underskjema_xml={'wrong':'xml'}),))
    if change == 'actor': original = replace(original,approvals=(replace(original.approvals[0],approved_by=str(UUID(int=999))),))
    if change == 'unknown_manifest': original = replace(original,approvals=(replace(original.approvals[0],manifest=dict(original.approvals[0].manifest,extra='ignored?')),))
    with pytest.raises(rf.ShareholderRegisterFilingError): read(original)


def test_new_profile_cannot_fall_back_to_legacy_manifest_validation():
    original = source_archive()
    with pytest.raises(rf.ShareholderRegisterFilingError):
        read(replace(original, approvals=(replace(original.approvals[0],case_profile='rf1086_no_activity_v1'),),source_approval_lineage=()))


@pytest.mark.parametrize('change', ['permission', 'pilot', 'request', 'scope', 'release', 'binding'])
def test_rehashed_review_cannot_change_scope_actor_or_original_inputs(change):
    original = source_archive(); line = original.source_approval_lineage[0]
    review = json.loads(line.review_text)
    if change == 'permission': review['permission']['confirmed_by'] = str(UUID(int=999))
    if change == 'pilot': review['pilot']['case_profile'] = 'rf1086_no_activity_v1'
    if change == 'request': review['request']['external_ref'] = 'changed'
    if change == 'scope': review['scope']['previewId'] = str(UUID(int=999))
    if change == 'release': review['technicalReleaseReady'] = False
    if change == 'binding': review['binding']['source_sha256'] = 'a'*64
    text = json.dumps(review, sort_keys=True); digest = sha256(text.encode()).hexdigest()
    approval = original.approvals[0]
    basis = rf.Rf1086SourceApprovalManifestBasis(line.source,line.source_preview,ACTOR,approval.entitlement_id,digest,
        tuple(approval.manifest['review']['acknowledgedWarningCodes']))
    manifest = rf.build_rf1086_source_approval_manifest(basis)
    original = replace(original, approvals=(replace(approval,manifest=manifest.manifest,manifest_hash=manifest.manifest_sha256),),
        source_approval_lineage=(replace(line,review_text=text,review_sha256=digest,
            manifest_text=rf.serialize_rf1086_source_approval_manifest(manifest),manifest_sha256=manifest.manifest_sha256),))
    with pytest.raises(rf.ShareholderRegisterFilingError): read(original)


def test_full_year_submissions_remain_closed_until_their_archive_contract_exists():
    from test_rf1086_archive_source import production_snapshot
    original = source_archive(); approval = original.approvals[0]
    submission = replace(production_snapshot().production_submissions[0],
        company_id=approval.company_id,income_year=approval.income_year,approval_id=approval.id,
        entitlement_id=approval.entitlement_id,user_id=approval.user_id,payload_hash=approval.payload_hash,
        adapter_version=approval.adapter_version,case_profile=approval.case_profile,
        status='approved',feedback_state='not_started',feedback_artifact_count=0)
    with pytest.raises(rf.ShareholderRegisterFilingError):
        read(replace(original,production_submissions=(submission,)))


@pytest.mark.parametrize('missing', [None, 'binding', 'source', 'bridge'])
def test_actual_adapter_reads_original_lineage_on_same_snapshot_without_current_owner_calls(missing):
    from test_postgres_shareholder_register_filing import session
    original = source_archive(); line = original.source_approval_lineage[0]
    store = session({}); calls = []
    binding = {f.name: getattr(line, f.name) for f in fields(line)
               if f.name not in ('source','source_preview','bridge')}
    def row(record):
        return {f.name: getattr(record,f.name) for f in fields(record)}
    class Cursor:
        def __init__(self, rows): self.rows = rows
        async def fetchall(self): return self.rows
        async def fetchone(self): return self.rows[0] if self.rows else None
    class Connection:
        async def execute(self, sql, args):
            calls.append((sql,args))
            assert not any(name in sql for name in ('year_source_heads','lock_year_source','admission','documents.','authority_connections.','billing.'))
            if 'source_approval_bindings' in sql: return Cursor([] if missing=='binding' else [binding])
            if 'year_source_versions' in sql:
                assert args==(line.source_id,str(original.company_id),int(original.income_year))
                return Cursor([] if missing=='source' else [{'retained':True}])
            if 'source_review_bridges' in sql: return Cursor([] if missing=='bridge' else [asdict(line.bridge)])
            if 'filing_approval_snapshots' in sql: return Cursor([row(original.approvals[0])])
            if 'filing_previews t' in sql:
                data=row(original.previews[0]);data['issues']=[asdict(issue) for issue in original.previews[0].issues]
                return Cursor([data])
            return Cursor([])
    connection=Connection()
    @asynccontextmanager
    async def transaction(*,snapshot):
        assert snapshot is True
        yield connection
    async def source_preview(conn, preview_id):
        assert conn is connection and preview_id==line.source_preview.preview_id
        return line.source_preview
    store._transaction=transaction
    store._year_source=lambda row: line.source if row else None
    store._read_source_preview=source_preview
    query=rf.Rf1086ArchiveQuery(original.company_id,original.income_year,store.actor_id)
    async def run(): return await rf.create_rf1086_preparation_service(store).archive_source(query)
    if missing:
        with pytest.raises(rf.ShareholderRegisterFilingError): asyncio.run(run())
    else:
        actual=asyncio.run(run())
        assert actual.source_approval_lineage==original.source_approval_lineage
        assert any('source_approval_bindings' in sql for sql,args in calls)
