"""Full-year production review transport never accepts caller-owned trusted facts."""
import pytest
from fastapi.testclient import TestClient

from talli_backend.main import create_app

BASE = '/api/v1/shareholder-register-filings'
HEADERS = {'Authorization': 'Bearer token', 'X-Request-ID': 'source-approval-api-proof'}
COMPANY = '00000000-0000-4000-8000-000000000001'
PREVIEW = '00000000-0000-4000-8000-000000000002'
ENTITLEMENT = '00000000-0000-4000-8000-000000000003'


def body(approval=False):
    value = {'companyId': COMPANY, 'incomeYear': 2025, 'previewId': PREVIEW, 'entitlementId': ENTITLEMENT}
    if approval:
        value.update(reviewSha256='a'*64, acknowledgedWarningCodes=[], realFilingConfirmed=True)
    return value


class NeverSessions:
    def __init__(self): self.calls = 0
    async def session(self, token):
        self.calls += 1
        raise AssertionError('Invalid transport input must not enter an authenticated session')


@pytest.fixture
def boundary():
    sessions = NeverSessions()
    return TestClient(create_app(shareholder_register_filing_session_factory=sessions)), sessions


@pytest.mark.parametrize('approval', [False, True], ids=['review', 'approval'])
@pytest.mark.parametrize('field,value', [
    ('companyId', None), ('companyId', 'invalid'), ('previewId', None), ('entitlementId', None),
    ('incomeYear', None), ('incomeYear', '2025'), ('incomeYear', True), ('incomeYear', 1999),
    ('actorId', COMPANY), ('trustedFacts', {}), ('sourceSha256', 'b'*64),
], ids=['null-company','invalid-company','null-preview','null-entitlement','null-year','string-year',
        'boolean-year','year-range','caller-actor','trusted-facts','caller-source-hash'])
def test_scope_and_unknown_fields_fail_before_authentication(boundary, approval, field, value):
    client, sessions = boundary
    command = {**body(approval), field: value}
    response = client.post(BASE+('/source-production-approvals' if approval else '/source-production-reviews'),
                           json=command, headers=HEADERS)
    assert response.status_code == 422
    assert sessions.calls == 0


@pytest.mark.parametrize('field,value', [
    ('reviewSha256', None), ('reviewSha256', 'A'*64), ('reviewSha256', 'a'*63), ('reviewSha256', 'a'*64+'\n'),
    ('acknowledgedWarningCodes', None), ('acknowledgedWarningCodes', ['']),
    ('acknowledgedWarningCodes', ['  ']), ('acknowledgedWarningCodes', ['warn','warn']),
    ('acknowledgedWarningCodes', [12]), ('realFilingConfirmed', None),
    ('realFilingConfirmed', 'true'), ('realFilingConfirmed', 1),
], ids=['null-hash','uppercase-hash','short-hash','newline-hash','null-warnings','empty-warning',
        'blank-warning','duplicate-warning','nonstring-warning','null-confirmation','string-confirmation','integer-confirmation'])
def test_approval_confirmation_hash_and_warning_types_are_exact(boundary, field, value):
    client, sessions = boundary
    response = client.post(BASE+'/source-production-approvals', json={**body(True),field:value}, headers=HEADERS)
    assert response.status_code == 422
    assert sessions.calls == 0


@pytest.mark.parametrize('field,value', [
    ('submissionId',None), ('manifestSha256','b'*63), ('reason',''), ('reason','\n  '), ('actorId',COMPANY),
], ids=['null-submission','invalid-manifest','empty-reason','blank-reason','caller-actor'])
def test_predecessor_is_typed_and_cannot_add_trusted_fields(boundary, field, value):
    client, sessions = boundary
    predecessor = {'submissionId': PREVIEW, 'manifestSha256':'b'*64, 'reason':'Corrected retained evidence',field:value}
    response = client.post(BASE+'/source-production-approvals', json={**body(True),'predecessor':predecessor}, headers=HEADERS)
    assert response.status_code == 422
    assert sessions.calls == 0


@pytest.mark.parametrize('approval', [False, True], ids=['review','approval'])
def test_bearer_is_required_before_workflow(boundary, approval):
    client, sessions = boundary
    response = client.post(BASE+('/source-production-approvals' if approval else '/source-production-reviews'),json=body(approval))
    assert response.status_code == 401
    assert sessions.calls == 0


def approval_api():
    from test_rf1086_source_admission import AdmissionHarness
    from talli_backend.application.shareholder_register_filing_session import ShareholderRegisterFilingAuthenticationError
    from talli_backend.modules.shareholder_register_filing import public as rf
    h = AdmissionHarness()
    h.review_hash, h.blockers, h.manifests = 'd'*64, (), []
    async def bridge(preview):
        assert h.held and 'original' in h.calls and 'governance' in h.calls
        h.calls.append('bridge')
        return preview.preview_id
    async def context(preview_id, entitlement_id):
        assert h.held and h.calls[-1] == 'bridge'
        h.calls.append('review')
        return rf.Rf1086SourceApprovalReview(h.source.company_id,h.source.income_year,h.preview.preview_id,
            h.source.source_id,h.source.source_sha256,entitlement_id,h.review_hash,
            tuple(sorted({issue.code for issue in h.preview.readiness_issues if issue.level=='warning'})),
            h.blockers,not h.blockers)
    async def append(preview, entitlement_id, manifest, review_sha256):
        assert h.held and h.calls[-1] == 'review'
        assert manifest.manifest['review']['sha256'] == review_sha256
        h.manifests.append(manifest)
        h.calls.append('approval')
        return rf.Rf1086RecordedResult(PREVIEW,h.source.company_id,h.source.income_year)
    h.transaction.bridge_source_preview = bridge
    h.transaction.read_source_approval_context = context
    h.transaction.append_source_approval = append
    class Sessions:
        async def session(self, token):
            if token != 'token': raise ShareholderRegisterFilingAuthenticationError()
            return await h.workflow._sessions.session(token)
    client = TestClient(create_app(shareholder_register_filing_session_factory=Sessions(),
                                  documents_session_factory=h.workflow._documents))
    scope = {'companyId':str(h.source.company_id),'incomeYear':int(h.source.income_year),
             'previewId':h.preview.preview_id.value,'entitlementId':ENTITLEMENT}
    return client,h,scope


def test_actual_http_review_and_approval_use_guarded_workflow_and_authenticated_manifest():
    client,h,scope = approval_api()
    reviewed = client.post(BASE+'/source-production-reviews',json=scope,headers=HEADERS)
    assert reviewed.status_code == 200, reviewed.text
    review = reviewed.json()
    assert review == {**scope,'sourceId':h.source.source_id.value,'sourceSha256':h.source.source_sha256,
                      'reviewSha256':h.review_hash,'warningCodes':[],'blockers':[],'canApprove':True}
    assert h.calls.index('bytes') < h.calls.index('guard') < h.calls.index('review') < h.calls.index('release')
    command = {**scope,'reviewSha256':review['reviewSha256'],'acknowledgedWarningCodes':[],
               'realFilingConfirmed':True,'predecessor':None}
    approved = client.post(BASE+'/source-production-approvals',json=command,headers=HEADERS)
    assert approved.status_code == 200, approved.text
    assert approved.json() == {'recordId':PREVIEW,'companyId':scope['companyId'],'incomeYear':scope['incomeYear']}
    manifest = h.manifests[0].manifest
    assert manifest['caseProfile'] == 'rf1086_full_year_v1'
    assert manifest['source']['sha256'] == h.source.source_sha256
    assert manifest['review']['sha256'] == h.review_hash
    assert manifest['predecessor'] is None
    assert h.calls[-2:] == ['approval','release'] and h.committed


@pytest.mark.parametrize('mode', ['false-confirmation','changed-review','extra-warning','blocked','stale-original'])
def test_actual_http_approval_refuses_unconfirmed_or_changed_guarded_basis(mode):
    client,h,scope = approval_api()
    command = {**scope,'reviewSha256':h.review_hash,'acknowledgedWarningCodes':[],'realFilingConfirmed':True}
    if mode == 'false-confirmation': command['realFilingConfirmed'] = False
    if mode == 'changed-review': h.review_hash = 'e'*64
    if mode == 'extra-warning': command['acknowledgedWarningCodes'] = ['not-an-actual-warning']
    if mode == 'blocked': h.blockers = ('synthetic_blocker',)
    if mode == 'stale-original': h.receipt_failure = True
    response = client.post(BASE+'/source-production-approvals',json=command,headers=HEADERS)
    assert response.status_code == (422 if mode == 'false-confirmation' else 409), response.text
    assert h.manifests == [] and not h.committed


def test_actual_http_blocked_review_remains_reviewable_and_wrong_bearer_is_rejected():
    client,h,scope = approval_api()
    h.blockers = ('synthetic_blocker',)
    response = client.post(BASE+'/source-production-reviews',json=scope,headers=HEADERS)
    assert response.status_code == 200
    assert response.json()['blockers'] == ['synthetic_blocker'] and not response.json()['canApprove']
    h.calls.clear()
    response = client.post(BASE+'/source-production-reviews',json=scope,headers={'Authorization':'Bearer wrong'})
    assert response.status_code == 401 and h.calls == []


def test_actual_http_predecessor_fields_are_preserved_in_canonical_manifest():
    client,h,scope = approval_api()
    predecessor = {'submissionId':PREVIEW,'manifestSha256':'b'*64,'reason':'Owner reviewed correction'}
    response = client.post(BASE+'/source-production-approvals',headers=HEADERS,json={**scope,
        'reviewSha256':h.review_hash,'acknowledgedWarningCodes':[],'realFilingConfirmed':True,
        'predecessor':predecessor})
    assert response.status_code == 200,response.text
    assert h.manifests[0].manifest['predecessor'] == predecessor


@pytest.mark.parametrize('kind', ['no_activity','formation','dividend','cash_issue','loss_covering_reduction'])
def test_actual_http_archive_exports_exact_original_source_and_approval_lineage(kind):
    from test_rf1086_source_approval_archive import source_archive
    from test_rf1086_year_source import ACTOR
    snapshot = source_archive(kind)
    lineage = snapshot.source_approval_lineage[0]
    class Session:
        actor_id = ACTOR
        async def archive_source(self, query):
            assert query.company_id == snapshot.company_id and query.income_year == snapshot.income_year
            return snapshot
    class Sessions:
        async def session(self, token):
            assert token == 'token'
            return Session()
    client = TestClient(create_app(shareholder_register_filing_session_factory=Sessions()))
    response = client.get(BASE+'/archive-source/production',headers=HEADERS,
        params={'companyId':str(snapshot.company_id),'incomeYear':int(snapshot.income_year)})
    assert response.status_code == 200,response.text
    wire = response.json()['sourceApprovalLineage'][0]
    assert response.json()['approvals'][0]['caseProfile'] == 'rf1086_full_year_v1'
    assert wire['reviewText'] == lineage.review_text
    assert wire['manifestText'] == lineage.manifest_text
    assert wire['bridge']['payloadSha256'] == lineage.payload_sha256
    assert wire['sourcePreview']['hovedskjemaXml'] == lineage.source_preview.hovedskjema_xml
    assert wire['sourcePreview']['underskjemaXml'] == dict(lineage.source_preview.underskjema_xml)
    assert wire['createdAt'] == lineage.created_at
    source = wire['source']
    assert set(source) == {'receipt','command'}
    assert source['receipt']['sourceSha256'] == lineage.source_sha256
    assert source['command']['identitiesReviewed'] == lineage.source.command.identities_reviewed
    assert source['command']['completeYearConfirmed'] == lineage.source.command.complete_year_confirmed
    assert source['command']['paidInReviewed'] == lineage.source.command.paid_in_reviewed
    assert source['command']['noActivityConfirmed'] == lineage.source.command.no_activity_confirmed
    assert source['command']['supersedesSourceId'] is None
    assert source['command']['supersedesSourceSha256'] is None
    assert source['command']['correctionReason'] is None
    assert source['command']['paidIn']['openingCapital'] == str(lineage.source.command.paid_in.opening_capital)
    assert 'actorId' not in source['command'] and 'freshness' not in source and 'context' not in source
