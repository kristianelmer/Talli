"""Owner observation discovery preserves exact history without reverifying originals."""
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from talli_backend.modules.shareholder_register_filing.public import Rf1086RegisterObservationError
from test_shareholder_register_source_api import ApiHarness, BASE, HEADERS, draft
from test_rf1086_year_source import COMPANY, YEAR


def listing(api, **scope):
    return api.client.get(BASE+'/register-observations',params={
        'companyId':str(COMPANY),'incomeYear':int(YEAR),**scope},headers=HEADERS)


def capture(api, body=None):
    result=api.client.post(BASE+'/register-observations',json=body or draft(api.h.register_command),headers=HEADERS)
    assert result.status_code==200,result.text
    return result.json()


def test_empty_observation_list_is_explicit_and_scoped():
    api=ApiHarness(capital=True)
    assert listing(api).json()=={'companyId':str(COMPANY),'incomeYear':int(YEAR),'observations':[]}
    assert 'verify_document' not in api.h.calls and not api.h.register_saved


def test_list_edit_correct_preserves_original_exact_values_and_resets_confirmations():
    api=ApiHarness(capital=True);command=api.h.register_command
    nominal=Decimal('300.000001')
    api.h.register_command=replace(command,
        before=replace(command.before,nominal_value=nominal,share_capital=nominal*command.before.share_count),
        after=replace(command.after,nominal_value=nominal,share_capital=nominal*command.after.share_count))
    first=capture(api);original=api.h.register_saved[0]
    api.h.calls.clear();api.h.document_failure=True
    result=listing(api);assert result.status_code==200,result.text
    row=result.json()['observations'][0];body=row['draft']
    assert row['receipt']==first and row['isCurrent'] is True
    assert body['before']['nominalValue']=='300.000001'
    assert body['before']['shareCapital']=='30000.000100'
    assert body['effectiveAt']==command.effective_at.isoformat()
    assert {doc['role'] for doc in body['documents']}=={'register_before','register_after','registration'}
    assert {doc['sourceIncomeYear'] for doc in body['documents']}=={2024}
    assert body['supersedesObservationId']==first['observationId']
    assert body['supersedesObservationSha256']==first['factSha256'] and body['correctionReason'] is None
    for field in ('completeRegisterConfirmed','registrationConfirmed','singleShareClassConfirmed'):
        assert body[field] is False
        body[field]=True
    assert 'verify_document' not in api.h.calls and api.h.register_saved==[original]
    assert all(secret not in result.text for secret in ('actor_id','trusted','codec','storageKey'))
    body['correctionReason']='Correct owner-reviewed name'
    for state in ('before','after'):body[state]['holdings'][0]['name']='Corrected name'
    api.h.document_failure=False
    second=capture(api,body)
    assert second['version']==2 and api.h.register_saved[0]==original
    rows=listing(api).json()['observations']
    assert [row['isCurrent'] for row in rows]==[False,True]
    assert rows[0]['draft']['supersedesObservationId']==first['observationId']
    assert rows[1]['draft']['supersedesObservationId']==second['observationId']
    assert rows[0]['draft']['before']['holdings'][0]['name']!=rows[1]['draft']['before']['holdings'][0]['name']


@pytest.mark.parametrize('change',['reviewer','unconfirmed','unlocked','not_as','wrong_company','revoked'])
def test_discovery_denies_ineligible_owner_without_reading_history(change):
    api=ApiHarness(capital=True)
    if change=='reviewer':api.h.company.role='reviewer'
    elif change=='unconfirmed':api.h.company.identity_confirmed_at=None
    elif change=='unlocked':api.h.company.identity_locked_at=None
    elif change=='not_as':api.h.company.entity_type='ENK'
    elif change=='wrong_company':api.h.company.id=str(uuid4())
    else:api.auth_failure=True
    response=listing(api)
    assert response.status_code in (401,403,404),response.text
    assert 'list_observations' not in api.h.calls


def test_discovery_requires_auth_and_valid_year_and_never_lists_other_company():
    api=ApiHarness(capital=True);capture(api)
    assert api.client.get(BASE+'/register-observations',params={'companyId':str(COMPANY),'incomeYear':int(YEAR)}).status_code==401
    assert listing(api,incomeYear=1999).status_code==422
    assert listing(api,companyId=str(uuid4())).status_code in (403,404)
    assert listing(api,incomeYear=int(YEAR)+1).json()['observations']==[]


@pytest.mark.parametrize('change',['digest','scope','duplicate','missing_predecessor','unavailable'])
def test_corrupt_or_incomplete_history_never_becomes_partial_success(change):
    api=ApiHarness(capital=True);capture(api);original=api.h.register_saved[0]
    if change=='digest':api.observations=(replace(original,fact_sha256='0'*64),)
    elif change=='scope':
        # A legitimate snapshot returned by a broken adapter in the wrong scope
        # must fail even though its own integrity is valid.
        response=api.client.get(BASE+'/register-observations',params={'companyId':str(COMPANY),'incomeYear':int(YEAR)+1},headers=HEADERS)
        assert response.status_code==200
        api.observations=(original,)
        response=api.client.get(BASE+'/register-observations',params={'companyId':str(COMPANY),'incomeYear':int(YEAR)+1},headers=HEADERS)
        assert response.status_code!=200;return
    elif change=='duplicate':api.observations=(original,original)
    elif change=='missing_predecessor':
        body=listing(api).json()['observations'][0]['draft']
        body.update(completeRegisterConfirmed=True,registrationConfirmed=True,singleShareClassConfirmed=True,correctionReason='Correction')
        capture(api,body);api.observations=(api.h.register_saved[-1],)
    else:api.persistence_error=Rf1086RegisterObservationError('rf1086_register_storage_invalid')
    assert listing(api).status_code!=200


def observation_row(snapshot):
    from talli_backend.modules.shareholder_register_filing.public import serialize_rf1086_register_observation, rf1086_register_observation_request_digest
    command=snapshot.command
    return {'id':snapshot.observation_id.value,'company_id':str(command.company_id),'income_year':int(command.income_year),
        'version':snapshot.version,'fact_sha256':snapshot.fact_sha256,'actor_id':str(command.actor_id.subject),
        'confirmed_at':snapshot.confirmed_at,'predecessor_id':command.supersedes_observation_id.value if command.supersedes_observation_id else None,
        'predecessor_sha256':command.supersedes_observation_sha256,'correction_reason':command.correction_reason,
        'request_sha256':rf1086_register_observation_request_digest(command),'snapshot_text':serialize_rf1086_register_observation(snapshot)}


def adapter_with_rows(rows, *, allowed=True):
    from contextlib import asynccontextmanager
    from test_postgres_shareholder_register_filing import session
    store=session({});queries=[]
    class Connection:
        async def execute(self,sql,parameters):queries.append((sql,parameters));return self
        async def fetchone(self):return {'allowed':allowed}
        async def fetchall(self):return rows
    @asynccontextmanager
    async def transaction(*,snapshot):
        assert snapshot is True
        yield Connection()
    store._transaction=transaction
    return store,queries


def test_adapter_enumerates_all_rows_and_binds_tenant_and_year_in_one_snapshot():
    import asyncio
    from talli_backend.modules.shareholder_register_filing.public import Rf1086SourceQuery
    api=ApiHarness(capital=True);capture(api);capture(api)
    store,queries=adapter_with_rows([observation_row(row) for row in api.h.register_saved])
    query=Rf1086SourceQuery(COMPANY,YEAR,store.actor_id)
    assert asyncio.run(store.list_register_observations(query))==tuple(api.h.register_saved)
    assert len(queries)==2 and queries[1][1]==(str(COMPANY),int(YEAR))
    assert 'limit' not in queries[1][0].lower()
    assert 'company_id=%s::uuid and v.income_year=%s' in queries[1][0]


@pytest.mark.parametrize('change',['owner_revoked','wrong_actor','row_scope','codec'])
def test_adapter_fails_closed_before_returning_untrusted_rows(change):
    import asyncio
    from talli_backend.modules.shareholder_register_filing.public import Rf1086SourceQuery, ShareholderRegisterFilingError
    api=ApiHarness(capital=True);capture(api);row=observation_row(api.h.register_saved[0])
    if change=='row_scope':row['company_id']=str(uuid4())
    if change=='codec':row['snapshot_text']='{"codec":"wrong"}'
    store,queries=adapter_with_rows([row],allowed=change!='owner_revoked')
    query=Rf1086SourceQuery(COMPANY,YEAR,api.h.actor if change=='wrong_actor' else store.actor_id)
    with pytest.raises((ShareholderRegisterFilingError,Rf1086RegisterObservationError)):
        asyncio.run(store.list_register_observations(query))
    if change=='wrong_actor':assert not queries
    if change=='owner_revoked':assert len(queries)==1


def test_independent_observations_are_all_current_without_arbitrary_page_limit():
    api=ApiHarness(capital=True)
    first=capture(api);second=capture(api)
    rows=listing(api).json()['observations']
    assert {row['receipt']['observationId'] for row in rows}=={first['observationId'],second['observationId']}
    assert all(row['isCurrent'] for row in rows)


@pytest.mark.parametrize('kind',['cash_nominal_increase','loss_covering_reduction'])
def test_observation_draft_projects_each_registered_nominal_transition(kind):
    api=ApiHarness(capital=True);command=api.h.register_command
    if kind=='cash_nominal_increase':
        after=replace(command.before,nominal_value=Decimal('600'),share_capital=Decimal('60000'))
        before=command.before
    else:
        before=replace(command.before,nominal_value=Decimal('600'),share_capital=Decimal('60000'))
        after=command.before
    api.h.register_command=replace(command,event_kind=kind,before=before,after=after)
    capture(api)
    value=listing(api).json()['observations'][0]['draft']
    assert value['eventKind']==kind and value['before']['nominalValue']==str(before.nominal_value)
    assert value['after']['nominalValue']==str(after.nominal_value)
