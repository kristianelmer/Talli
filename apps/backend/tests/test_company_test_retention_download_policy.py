"""CompanyAccess action policy with explicit Auth/gateway doubles, no live session proof."""
import asyncio
import base64
from datetime import datetime, timezone
import json

import pytest

from talli_backend.modules.company_access import public as access
from test_company_access import CompanyAccessGatewayStub
from test_rf1086_company_test_retention import COMPANY, ACTOR

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)
SESSION_ID = '00000000-0000-0000-0000-000000000077'


def token(**changes):
    claims = dict(sub=str(ACTOR.subject), session_id=SESSION_ID, aal='aal2',
        amr=[{'method':'totp', 'timestamp':NOW.timestamp()-1}])
    claims.update(changes)
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
    return 'synthetic.'+payload+'.signature'


class ArchiveGateway(CompanyAccessGatewayStub):
    def __init__(self, role='owner'):
        super().__init__(role)
        self.live, self.accepted = True, True

    async def session_subject(self, access_token):
        self.calls.append(('auth', None))
        if not self.live:
            raise access.CompanyAccessError(status=401,code='AUTHENTICATION_REQUIRED',title='Auth required',detail='Synthetic denied')
        return str(ACTOR.subject)

    async def memberships(self, access_token, subject):
        self.calls.append(('members', None))
        return [{'company_id':str(COMPANY),'role':self.role,'accepted_at':NOW.isoformat() if self.accepted else None}]

    async def companies(self, access_token, company_ids):
        self.calls.append(('companies', None))
        if company_ids != [str(COMPANY)]: return []
        row = (await super().companies(access_token,['10000000-0000-0000-0000-000000000001']))[0]
        return [{**row,'id':str(COMPANY),'created_by':str(ACTOR.subject)}]


@pytest.fixture(autouse=True)
def fixed_policy_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return NOW
    monkeypatch.setattr(access,'datetime',Clock)


@pytest.mark.parametrize('role',['owner','reviewer','read_only'])
def test_current_accepted_roles_can_download_with_fresh_signed_action_claims(role):
    gateway=ArchiveGateway(role)
    result=asyncio.run(access.CompanyAccessService(gateway).authorize_archive_download_step_up(token(),company_id=str(COMPANY)))
    assert str(result.company_id)==str(COMPANY) and str(result.subject_id)==str(ACTOR.subject)
    with pytest.raises(ValueError): result.company_id='changed'
    assert [name for name,_ in gateway.calls]==['auth','auth','members','companies']


@pytest.mark.parametrize('changes',[
    {'aal':'aal1'}, {'amr':[]}, {'amr':None}, {'amr':['invalid']},
    {'amr':[{'method':'totp','timestamp':NOW.timestamp()-901}]},
    {'amr':[{'method':'totp','timestamp':NOW.timestamp()+1}]},
    {'amr':[{'method':'totp','timestamp':True}]},
    {'amr':[{'method':'totp','timestamp':'123'}]},
    {'amr':[{'method':'totp','timestamp':float('nan')}]},
    {'amr':[{'method':'totp','timestamp':float('inf')}]},
    {'amr':[{'method':'password','timestamp':NOW.timestamp()}]},
    {'session_id':None},{'session_id':''},{'session_id':'00000000-0000-0000-0000-000000000000'},
    {'session_id':'not-uuid'},{'sub':'00000000-0000-0000-0000-000000000009'},
],ids=['aal1','no-mfa','null-amr','bad-amr','expired','future','bool','string','nan','inf','unsupported','null-session','empty-session','nil-session','bad-session','sub-mismatch'])
def test_invalid_action_claims_fail_closed(changes):
    gateway=ArchiveGateway()
    with pytest.raises(access.CompanyAccessError) as denied:
        asyncio.run(access.CompanyAccessService(gateway).authorize_archive_download_step_up(token(**changes),company_id=str(COMPANY)))
    assert denied.value.status==403 and denied.value.code=='FRESH_MFA_REQUIRED'


def test_exact_fifteen_minute_boundary_and_one_second_expired():
    service=access.CompanyAccessService(ArchiveGateway())
    asyncio.run(service.authorize_archive_download_step_up(token(amr=[{'method':'totp','timestamp':NOW.timestamp()-900}]),company_id=str(COMPANY)))
    with pytest.raises(access.CompanyAccessError):
        asyncio.run(service.authorize_archive_download_step_up(token(amr=[{'method':'totp','timestamp':NOW.timestamp()-901}]),company_id=str(COMPANY)))


@pytest.mark.parametrize('change',['unaccepted','revoked','foreign','auth'])
def test_current_access_denies_before_capture(change):
    gateway=ArchiveGateway()
    company=str(COMPANY)
    if change=='unaccepted': gateway.accepted=False
    elif change=='revoked': gateway.role='revoked'
    elif change=='foreign': company='00000000-0000-0000-0000-000000000099'
    elif change=='auth': gateway.live=False
    with pytest.raises(access.CompanyAccessError):
        asyncio.run(access.CompanyAccessService(gateway).authorize_archive_download_step_up(token(),company_id=company))


def test_duplicate_claims_reject_without_creating_an_authorization_scope():
    raw=json.dumps(dict(sub=str(ACTOR.subject),session_id=SESSION_ID,aal='aal2',amr=[]))
    raw=raw.replace('"session_id":','"session_id":"duplicate","session_id":',1)
    encoded=base64.urlsafe_b64encode(raw.encode()).decode().rstrip('=')
    gateway=ArchiveGateway()
    with pytest.raises(access.CompanyAccessError):
        asyncio.run(access.CompanyAccessService(gateway).authorize_archive_download_step_up('header.'+encoded+'.sig',company_id=str(COMPANY)))
    assert gateway.calls==[('auth',None)]


@pytest.mark.parametrize('overflow',['1e999','-1e999'])
@pytest.mark.parametrize('position',['extra','nested','unsupported-method'])
def test_overflowed_json_float_rejects_everywhere_before_membership(overflow,position):
    raw=base64.urlsafe_b64decode(token().split('.')[1]+'==').decode()
    if position=='extra':raw=raw[:-1]+',"extra":'+overflow+'}'
    elif position=='nested':raw=raw[:-1]+',"extra":{"nested":['+overflow+']}}'
    else:raw=raw.replace('"amr": [','"amr": [{"method":"password","timestamp":'+overflow+'},',1)
    encoded=base64.urlsafe_b64encode(raw.encode()).decode().rstrip('=')
    gateway=ArchiveGateway()
    with pytest.raises(access.CompanyAccessError) as denied:
        asyncio.run(access.CompanyAccessService(gateway).authorize_archive_download_step_up('header.'+encoded+'.sig',company_id=str(COMPANY)))
    assert denied.value.code=='FRESH_MFA_REQUIRED' and gateway.calls==[('auth',None)]


def test_ordinary_float_claims_and_timestamp_remain_accepted():
    result=asyncio.run(access.CompanyAccessService(ArchiveGateway()).authorize_archive_download_step_up(
        token(extra={'ordinary':1.25},amr=[{'method':'totp','timestamp':NOW.timestamp()-1.5}]),company_id=str(COMPANY)))
    assert str(result.company_id)==str(COMPANY)
