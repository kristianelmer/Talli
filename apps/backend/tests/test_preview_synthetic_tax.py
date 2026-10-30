"""The finite synthetic composition grants preparation only, with current owner admission."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from talli_backend.adapters.preview_synthetic_tax import compose_preview_tax_preparation, _CLOSED
from talli_backend.application.company_tax_filing_workflow import CompanyTaxApplication
from talli_backend.application.private_preview_tax_preparation import COMPANY, OWNER, ORGANIZATION
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError, CompanyTaxSourceQuery, PrepareTaxDeliveryDraft, StoredTaxDeliveryDraft,
    TaxDeliverySource, TaxFilingSubmissionId,
)
from talli_backend.shared.kernel import (
    ActorId, ActorKind, CompanyId, CorrelationId, IdempotencyKey, IncomeYear, Timestamp, UserId,
)
from test_company_tax_delivery import raw_source

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
ACTOR = ActorId(ActorKind.USER, UserId(OWNER))
QUERY = CompanyTaxSourceQuery(CompanyId(COMPANY), IncomeYear(2025), ACTOR)


def environment():
    return dict(_CLOSED) | {
        'VERCEL': '1', 'VERCEL_ENV': 'preview', 'VERCEL_TARGET_ENV': 'preview',
        'VERCEL_PROJECT_ID': 'prj_u28yRnkslspXi3LSEDQHvTz8EWCD',
        'SUPABASE_URL': 'https://pkpyyxryfhfehrbhbynp.supabase.co',
        'TALLI_LEDGER_DATABASE_URL': 'postgresql://restricted.pkpyyxryfhfehrbhbynp@aws-0-eu.pooler.supabase.com:6543/postgres',
        'TALLI_PREVIEW_SYNTHETIC_REGISTRY_IDENTITY': json.dumps({'source': 'browser_test', 'org_number': ORGANIZATION}),
        'TALLI_PREVIEW_SYNTHETIC_TAX_PREPARATION': json.dumps({
            'purpose': 'synthetic_preparation_only_v1', 'expiresAt': (NOW + timedelta(hours=2)).isoformat()}),
    }


def context():
    return SimpleNamespace(id=COMPANY, org_number=ORGANIZATION, source='browser_test', created_by=OWNER,
        name='Synthetic private Preview 714f7b19', entity_type='AS', status_text='aktiv',
        address='Disposable private Preview synthetic fixture', postal_code='0155', city='OSLO',
        identity_confirmed_at=NOW, identity_locked_at=NOW, role='owner', aal='aal2',
        current_agreement_accepted=True, company_year_admission_id=str(uuid4()), admitted_accounting_year=2025,
        current_eligibility_decision='supported', consequential_operations_allowed=True)


class Access:
    def __init__(self): self.context=context(); self.calls=[]
    async def selected_context(self, token, **scope):
        assert self.session.active==0, 'Auth HTTP must stay outside SQL transactions'
        assert token == 'synthetic-owner-token'
        assert scope == {'company_id': COMPANY, 'accounting_year': 2025}
        self.calls.append(scope)
        return SimpleNamespace(selected_company=self.context)


class Session:
    actor_id=ACTOR
    def __init__(self): self.active=0; self.stored=None; self.guard_calls=0; self.deny=False
    async def session(self, _token): return self
    @asynccontextmanager
    async def transaction(self, *, snapshot=False):
        self.active+=1
        try: yield self
        finally: self.active-=1
    async def delivery_draft_by_key(self, query, key):
        assert query==QUERY and self.active
        return self.stored
    async def lock_delivery_draft_archive(self, query):
        assert query==QUERY and self.active
        self.guard_calls+=1
        if self.deny: raise CompanyTaxError.mfa_required()
    async def store_delivery_draft(self, draft):
        assert self.active
        self.stored=StoredTaxDeliveryDraft(draft, Timestamp(NOW))
        return self.stored
    async def assert_preparation_company_year(self, query):
        assert self.active and query==QUERY
        if not self.eligible():raise CompanyTaxError.forbidden()


def setup(monkeypatch):
    access=Access(); session=Session(); clock=[NOW]
    access.session=session
    session.eligible=lambda:access.context.consequential_operations_allowed
    factory=compose_preview_tax_preparation(access, environment=environment(), now=lambda: clock[0])
    app=CompanyTaxApplication(session, lambda tx: None, preparation_factory=factory)
    values=raw_source('no-activity-zero')
    values.update(company_id=QUERY.company_id, organization_number=ORGANIZATION)
    for row in (values['annual_data'], *values['ledger_entries'], *values['holding_actions']):
        row['company_id']=COMPANY
    source=TaxDeliverySource(**values)
    async def read(tx, query, **_):
        assert tx is session and tx.active and query==QUERY
        return source
    monkeypatch.setattr('talli_backend.application.company_tax_delivery_preparation.read_company_tax_delivery_source', read)
    command=PrepareTaxDeliveryDraft(QUERY.company_id, QUERY.income_year, ACTOR,
        TaxFilingSubmissionId(str(uuid4())), IdempotencyKey('synthetic-private-prepare'), CorrelationId('private-prepare'))
    return access, session, app, command, clock


def test_absent_flag_does_not_compose_or_inspect_other_configuration():
    assert compose_preview_tax_preparation(None, environment={}) is None


@pytest.mark.parametrize('key,value', [
    ('VERCEL', '0'), ('VERCEL_ENV', 'production'), ('VERCEL_TARGET_ENV', 'production'),
    ('VERCEL_PROJECT_ID', 'other'), ('SUPABASE_URL', 'https://other.supabase.co'),
    *[(key, 'true' if value=='false' else 'on') for key, value in _CLOSED.items()],
    ('TALLI_LEDGER_DATABASE_URL', 'postgresql://restricted.other@aws-0-eu.pooler.supabase.com/postgres'),
    ('TALLI_LEDGER_DATABASE_URL', 'postgresql://restricted@db.other.supabase.co/postgres'),
    ('TALLI_LEDGER_DATABASE_URL', 'host=db.pkpyyxryfhfehrbhbynp.supabase.co hostaddr=127.0.0.1'),
    ('TALLI_LEDGER_DATABASE_URL', 'service=other'), ('PGSERVICE', 'other'), ('PGHOSTADDR', '127.0.0.1'),
    ('TALLI_PREVIEW_SYNTHETIC_REGISTRY_IDENTITY', '{}'),
    ('TALLI_PREVIEW_SYNTHETIC_TAX_PREPARATION', 'invalid-private-configuration'),
    *[('TALLI_PREVIEW_SYNTHETIC_TAX_PREPARATION', json.dumps(value)) for value in [
        None, {}, [], {'purpose': 'submission', 'expiresAt': (NOW+timedelta(hours=1)).isoformat()},
        {'purpose': 'synthetic_preparation_only_v1', 'expiresAt': (NOW+timedelta(hours=25)).isoformat()},
        {'purpose': 'synthetic_preparation_only_v1', 'expiresAt': '2026-10-29T13:00:00'},
        {'purpose': 'synthetic_preparation_only_v1', 'expiresAt': (NOW+timedelta(hours=1)).isoformat(), 'extra': True},
    ]],
])
def test_configuration_denies_other_targets_open_modes_unbounded_or_invalid_profiles(key, value):
    with pytest.raises(ValueError, match='^Tax preparation requires the designated finite synthetic Preview scope$'):
        compose_preview_tax_preparation(Access(), environment=environment() | {key: value}, now=lambda: NOW)


def test_cold_start_after_finite_expiry_disables_preparation_without_disabling_archive_routes():
    assert compose_preview_tax_preparation(Access(), environment=environment(), now=lambda: NOW+timedelta(hours=3)) is None


@pytest.mark.parametrize('field,value', [
    ('id', '00000000-0000-4000-8000-000000000001'), ('org_number', '123456789'), ('source', 'brreg'), ('created_by', '00000000-0000-4000-8000-000000000002'),
    ('name', 'Another company'), ('entity_type', 'ASA'), ('status_text', 'slettet'),
    ('address', 'Other'), ('postal_code', '9999'), ('city', 'Other'),
    ('identity_confirmed_at', None), ('identity_locked_at', None), ('role', 'accountant'), ('aal', 'aal1'),
    ('current_agreement_accepted', False), ('company_year_admission_id', None), ('admitted_accounting_year', 2026),
    ('current_eligibility_decision', 'needs_clarification'), ('current_eligibility_decision', 'unsupported'),
    ('consequential_operations_allowed', False),
])
def test_current_owner_identity_agreement_and_eligibility_are_required_before_any_transaction(monkeypatch, field, value):
    access, session, app, command, _=setup(monkeypatch)
    setattr(access.context, field, value)
    async def exercise():
        with pytest.raises(CompanyTaxError) as error:
            await (await app.session('synthetic-owner-token')).prepare_delivery_draft(command)
        assert error.value.code=='COMPANY_TAX_FORBIDDEN'
    asyncio.run(exercise())
    assert session.guard_calls==0 and session.stored is None


def test_preparation_retains_exact_synthetic_bytes_and_replays_without_regeneration(monkeypatch):
    from talli_backend.adapters.preview_synthetic_tax import _ORIGINAL
    access, session, app, command, clock=setup(monkeypatch)
    async def exercise():
        actor=await app.session('synthetic-owner-token')
        stored=await actor.prepare_delivery_draft(command)
        assert stored.draft.current_document.response.raw_bytes==_ORIGINAL
        assert stored.draft.current_document.document_reference=='synthetic-private-preview-992803750-2025-v1'
        assert stored.draft.envelope.source.company_id==QUERY.company_id
        assert stored.draft.envelope.source.organization_number==ORGANIZATION
        assert stored.draft.current_document.party_number=='0'
        assert actor._submission is None
        async def fail(**_): pytest.fail('Replay must retain the exact original, without regeneration')
        actor._preparation._current.fetch_current_document=fail
        replay=await actor.prepare_delivery_draft(command)
        assert replay.draft.canonical_json==stored.draft.canonical_json
        clock[0]+=timedelta(hours=2)
        with pytest.raises(CompanyTaxError): await actor.prepare_delivery_draft(command)
    asyncio.run(exercise())
    assert session.guard_calls==4 and len(access.calls)==2


@pytest.mark.parametrize('change', ['eligibility', 'expiry', 'mfa'])
def test_current_admission_is_rechecked_after_current_read_before_storage(monkeypatch, change):
    access, session, app, command, clock=setup(monkeypatch)
    async def exercise():
        actor=await app.session('synthetic-owner-token')
        original=actor._preparation._current.fetch_current_document
        async def read(**scope):
            assert session.active==0
            value=await original(**scope)
            if change=='eligibility': access.context.consequential_operations_allowed=False
            elif change=='expiry': clock[0]+=timedelta(hours=2)
            else: session.deny=True
            return value
        actor._preparation._current.fetch_current_document=read
        with pytest.raises(CompanyTaxError): await actor.prepare_delivery_draft(command)
    asyncio.run(exercise())
    assert session.stored is None


@pytest.mark.parametrize('change', ['owner', 'company', 'actor'])
def test_scope_refuses_other_actor_company_or_year(monkeypatch, change):
    access, session, app, command, _=setup(monkeypatch)
    if change=='owner':
        session.actor_id=ActorId(ActorKind.USER, UserId(str(uuid4())))
        command=replace(command, actor_id=session.actor_id)
    elif change=='company': command=replace(command, company_id=CompanyId(str(uuid4())))
    else: command=replace(command, actor_id=ActorId(ActorKind.USER, UserId(str(uuid4()))))
    async def exercise():
        with pytest.raises(CompanyTaxError): await (await app.session('synthetic-owner-token')).prepare_delivery_draft(command)
    asyncio.run(exercise())
    assert not access.calls and not session.guard_calls and session.stored is None


@pytest.mark.parametrize('allowed', [True,False,None,'true'])
def test_transaction_recheck_uses_existing_company_access_contract_and_exact_boolean(allowed):
    from talli_backend.adapters.postgres_company_tax_filing import PostgresCompanyTaxTransaction
    tx=PostgresCompanyTaxTransaction(SimpleNamespace(actor_id=ACTOR),None)
    calls=[]
    async def row(sql,params):
        calls.append((sql,params));return {'allowed':allowed}
    tx._delivery_row=row
    async def exercise():
        if allowed is True:await tx.assert_preparation_company_year(QUERY)
        else:
            with pytest.raises(CompanyTaxError):await tx.assert_preparation_company_year(QUERY)
    asyncio.run(exercise())
    assert calls==[('select public.company_access_company_year_allows_consequential_v1(%s::uuid,%s::integer) as allowed',(COMPANY,2025))]


def test_finite_sql_scope_selectors_resolve_against_actual_preparation_codec(monkeypatch):
    """The operational SQL and durable typed codec must agree before hosted activation."""
    from pathlib import Path
    import re
    _,_,app,command,_=setup(monkeypatch)
    async def exercise():return await(await app.session('synthetic-owner-token')).prepare_delivery_draft(command)
    stored=asyncio.run(exercise())
    sql=(Path(__file__).resolve().parents[3]/'supabase/private-preview/20261029170000_synthetic_tax_current_draft.sql').read_text()
    wrapper=sql[sql.index('declare value jsonb:'):]
    assert "value jsonb:=(p_raw::jsonb)->'draft'" in wrapper
    paths=re.findall(r"value#>>?'\{([^}]+)\}'",wrapper)
    assert len(paths)==5
    root=json.loads(stored.draft.canonical_json)['draft']
    for path in paths:
        value=root
        for key in path.split(','):
            assert key in value, f'SQL scope path {path} is absent from the actual draft codec'
            value=value[key]
        assert value is not None
