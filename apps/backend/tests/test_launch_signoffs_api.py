from datetime import UTC, datetime
from dataclasses import replace

from fastapi.testclient import TestClient
import pytest

from talli_backend.main import create_app
from talli_backend.application.launch_signoffs import (
    LaunchSignoffAuthenticationError, LaunchSignoffError, LaunchSignoffKey,
    LaunchSignoffRecord, LaunchSignoffStatus,
)
from talli_backend.shared.kernel import ActorId, ActorKind, ErrorCategory, Timestamp, UserId

ACTOR=ActorId(ActorKind.USER,UserId('22345678-1234-4234-8234-123456789abc'))
PATH='/api/v1/operator-controls/launch-signoffs'
HEADERS={'Authorization':'Bearer local-signoff-session','X-Request-ID':'signoff-test'}
BODY=dict(key='security_restore',status='approved',reviewer=' Reviewer ',reviewedAt='2026-07-01T00:00:00Z',evidenceLink=' evidence ',decision=' approved ')


class Store:
    actor_id=ACTOR
    operator=True
    admin=True
    def __init__(self): self.rows=[]; self.authorizations=[]
    async def session(self, token):
        if token!='local-signoff-session': raise LaunchSignoffAuthenticationError()
        return self
    async def authorize_operator(self, *, admin):
        self.authorizations.append(admin)
        if not self.operator or (admin and not self.admin):
            raise LaunchSignoffError('launch_signoff_operator_required',ErrorCategory.FORBIDDEN)
    async def list_signoffs(self): return tuple(self.rows)
    async def record_signoff(self, command):
        row=LaunchSignoffRecord(command.key,command.status,command.reviewer,Timestamp(command.reviewed_at),
            command.evidence_link,command.decision,ACTOR.subject,Timestamp(datetime.now(UTC)))
        self.rows=[row]
        return row


def setup():
    store=Store()
    return TestClient(create_app(launch_signoff_session_factory=store)),store


def test_records_verified_admin_and_normalizes_existing_fields():
    api,store=setup()
    response=api.post(PATH,headers=HEADERS,json=BODY)
    assert response.status_code==200,response.text
    value=response.json()
    assert value['recordedBy']==str(ACTOR.subject)
    assert value['reviewer']=='Reviewer' and value['evidenceLink']=='evidence' and value['decision']=='approved'
    assert response.headers['cache-control']=='no-store'
    assert response.headers['x-request-id']=='signoff-test'
    assert api.get(PATH,headers=HEADERS).json()['signoffs']==[value]
    assert store.authorizations==[True,False]


@pytest.mark.parametrize('change',[{'recordedBy':str(ACTOR.subject)},{'updatedAt':'2026-01-01T00:00:00Z'},
    {'key':'other'},{'status':'ready'},{'reviewedAt':'2100-01-01T00:00:00Z'},{'reviewedAt':'invalid'},
    {'reviewer':' '},{'evidenceLink':''},{'decision':''}])
def test_rejects_invalid_or_caller_trusted_fields(change):
    api,store=setup()
    response=api.post(PATH,headers=HEADERS,json=BODY|change)
    assert response.status_code==422,response.text
    assert not store.rows and response.headers['cache-control']=='no-store'


def test_support_can_read_but_only_current_admin_can_record():
    api,store=setup()
    store.admin=False
    assert api.get(PATH,headers=HEADERS).status_code==200
    assert api.post(PATH,headers=HEADERS,json=BODY).status_code==403
    store.operator=False
    assert api.get(PATH,headers=HEADERS).status_code==403
    assert api.get(PATH).status_code==401
    assert not store.rows


def test_pending_signoff_preserves_empty_review_evidence():
    api,store=setup()
    response=api.post(PATH,headers=HEADERS,json=BODY|dict(status='pending',reviewer='',evidenceLink='',decision=''))
    assert response.status_code==200
    assert store.rows[0].status is LaunchSignoffStatus.PENDING
