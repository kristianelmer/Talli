"""Recovery orchestration never allocates on admission failure or replays repair."""
import hashlib
import json
import signal
import sys
import time
from copy import deepcopy
from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace

import pytest

from test_rf1086_identity_restore_runner import identity, DB, AUTH, ENV, SOURCE_URL
import rf1086_restore_control as control
import test_rf1086_restore_metadata as metadata_fixtures


@pytest.fixture
def inventory_denial_model(monkeypatch):
    """Real verifier; deliberately admitted branches are not real Auth/SQL proof."""
    import base64
    import socket
    from collections import deque
    from pathlib import Path
    import ast
    from test_rf1086_company_test_retention import COMPANY, ACTOR, capture, record, wire
    from talli_backend.shared.kernel import ActorId, ActorKind, UserId
    import rf1086_company_test_inventory_identity_restore as inventory

    budget = control.RecoveryBudget(time.monotonic())
    budget.enter('actors')
    expected = capture(record())
    outsider = ActorId(ActorKind.USER, UserId('00000000-0000-0000-0000-000000000008'))
    owner_id, outsider_id, company_id = str(ACTOR.subject), str(outsider.subject), str(COMPANY)
    source_reader = 'postgresql://talli_ledger_backend@127.0.0.1:55001/postgres'
    target_url = 'postgresql://postgres@127.0.0.1:55002/postgres'
    stateless = 'generated.' + base64.urlsafe_b64encode(json.dumps({'sub': owner_id}).encode()).decode().rstrip('=') + '.signature'
    tokens = {'owner': 'generated-owner', 'outsider': 'generated-outsider', 'stateless': stateless}
    token_names = {value: key for key, value in tokens.items()}
    auth_order = [('owner', None), ('outsider', None), ('stateless', 'stateless'),
                  ('owner', None), ('outsider', None), ('owner', None), ('owner', None),
                  ('owner', None), ('owner', None), ('owner', None), ('owner', 'banned'),
                  ('owner', None), ('owner', None), ('outsider', None), ('owner', 'logout'),
                  ('owner', None), ('owner', 'deleted'), ('outsider', None)]
    pending_auth = deque(auth_order)
    state = dict(admit=None, fault=None, fault_at='auth', owner=True, outsider=False, accepted='generated-accepted',
                 role='owner', banned=None, logged_out=False, deleted=False, events=[],
                 auth=[], sql=[], connections=0, closes=0, http_open=0, http_close=0)
    recovery = SimpleNamespace(budget=budget, database_url=target_url,
        database_container='generated-target', bootstrap='generated-bootstrap',
        auth_url='http://127.0.0.1:55003', admin_key='generated-admin',
        reader_url=lambda _: source_reader, proof={key: True for key in (
            'independentClusterRestored', 'independentAuthRestored', 'authHttpTargetBindingVerified',
            'roleAttributesAndMembershipsRestored', 'ownershipGrantsAndRlsRestored', 'authRowsRestoredExactly')})

    def forbidden(*args, **kwargs):
        raise AssertionError('generated inventory test attempted external IO')
    monkeypatch.setattr(budget, 'command', forbidden)
    monkeypatch.setattr(control.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)

    class Session:
        def __init__(self, name, probe=None):
            self.name, self.probe = name, probe
            self.actor_id = outsider if name == 'outsider' else ACTOR
        async def read_company_test_retention(self, query):
            assert query.company_id == COMPANY and query.actor_id == self.actor_id
            state['events'].append(('read', self.name))
            if state['fault'] and state['fault'][0] == self.probe and state['fault_at'] == 'read':
                raise state['fault'][1]
            # The branch-injected success intentionally bypasses modeled membership
            # for logout/deleted and SID admission for stateless; it proves location only.
            allowed = state['outsider'] if self.name == 'outsider' else state['owner'] and state['accepted'] is not None
            if self.probe is None and not allowed:
                raise inventory.rf.ShareholderRegisterFilingError.not_found()
            return expected

    class Factory:
        def __init__(self, configuration):
            assert configuration.url == recovery.auth_url
        async def session(self, token):
            name = token_names[token]
            assert pending_auth, 'unexpected additional Auth invocation'
            required_name, probe = pending_auth.popleft()
            assert name == required_name
            state['auth'].append((name, probe)); state['events'].append(('auth', name, probe))
            if probe:
                if probe == 'banned': assert state['banned'] == 'future'
                if probe == 'logout': assert state['logged_out'] and not state['owner']
                if probe == 'deleted': assert state['deleted'] and not state['owner']
                fault = state['fault'] and state['fault'][0] == probe
                if fault and state['fault_at'] == 'auth':
                    raise state['fault'][1]
                if state['admit'] != probe and not fault:
                    raise inventory.ShareholderRegisterFilingAuthenticationError()
            return Session(name, probe=probe)
    monkeypatch.setattr(inventory, 'PostgresCompanyTestRetentionSessionFactory', Factory)

    sql_steps = deque([
        ('membership', 'select role,accepted_at from public.company_memberships where company_id=%s and user_id=%s', (company_id, owner_id), [('owner', 'generated-accepted')]),
        *[(role, 'update public.company_memberships set role=%s where company_id=%s and user_id=%s', (role, company_id, owner_id), []) for role in ('owner', 'reviewer', 'read_only')],
        ('unaccept', 'update public.company_memberships set role=%s,accepted_at=null where company_id=%s and user_id=%s', ('owner', company_id, owner_id), []),
        ('accept', 'update public.company_memberships set accepted_at=%s where company_id=%s and user_id=%s', ('generated-accepted', company_id, owner_id), []),
        ('ban_before', 'select banned_until from auth.users where id=%s', (owner_id,), [(None,)]),
        ('ban', "update auth.users set banned_until=now()+interval '1 hour' where id=%s", (owner_id,), []),
        ('unban', 'update auth.users set banned_until=%s where id=%s', (None, owner_id), []),
        ('outsider_before', 'select count(*) from public.company_memberships where company_id=%s and user_id=%s', (company_id, outsider_id), [(0,)]),
        ('successor', "insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',now())", (company_id, outsider_id), []),
        ('revoke_member', 'delete from public.company_memberships where company_id=%s and user_id=%s returning user_id', (company_id, owner_id), [(owner_id,)]),
        ('sessions', "select coalesce(jsonb_agg(to_jsonb(s)),'[]'::jsonb) from auth.sessions s where user_id=%s", (owner_id,), [([{'user_id': owner_id}],)]),
        ('restore_session', 'insert into auth.sessions select * from jsonb_populate_recordset(null::auth.sessions,%s::jsonb)', (json.dumps([{'user_id': owner_id}]),), []),
        ('deleted', 'select deleted_at is not null from auth.users where id=%s', (owner_id,), [(True,)]),
        ('erase', 'delete from auth.users where id=%s', (owner_id,), []),
    ])

    class Connection:
        def __enter__(self):
            state['connections'] += 1
            return self
        def __exit__(self, *args): self.close()
        def close(self): state['closes'] += 1
        def transaction(self, **kwargs):
            assert kwargs == {'force_rollback': True}
            return nullcontext()
        def execute(self, sql, params):
            if sql == "select set_config('statement_timeout',%s,false)":
                assert len(params) == 1 and int(params[0]) > 0
                return None
            assert sql_steps, 'unexpected additional SQL'
            label, required_sql, required_params, rows = sql_steps.popleft()
            assert (sql, params) == (required_sql, required_params)
            state['sql'].append(label); state['events'].append(('sql', label))
            if label in ('owner', 'reviewer', 'read_only'): state['role'] = label
            elif label == 'unaccept': state.update(role='owner', accepted=None)
            elif label == 'accept': state['accepted'] = 'generated-accepted'
            elif label == 'ban': state['banned'] = 'future'
            elif label == 'unban': state['banned'] = None
            elif label == 'successor': state['outsider'] = True
            elif label == 'revoke_member': state['owner'] = False
            elif label == 'restore_session': state['logged_out'] = False
            elif label == 'erase': raise inventory.psycopg.errors.ForeignKeyViolation('generated retained history')
            return SimpleNamespace(fetchone=lambda: rows[0], fetchall=lambda: rows)

    def verified(*args, **kwargs):
        assert args == (target_url, recovery.database_container, recovery.bootstrap)
        assert kwargs == {'budget': budget}
        state['events'].append(('target-proof',))
    def connect(dsn, **kwargs):
        assert state['events'][-1] == ('target-proof',)
        assert inventory.conninfo_to_dict(dsn)['port'] == '55002'
        return Connection()
    monkeypatch.setattr(inventory, 'verify_target_session', verified)
    monkeypatch.setattr(inventory.psycopg, 'connect', connect)

    class Client:
        def __init__(self, **kwargs):
            assert kwargs['trust_env'] is False and 0 < kwargs['timeout'] <= 15
        async def __aenter__(self):
            state['http_open'] += 1
            return self
        async def __aexit__(self, *args): state['http_close'] += 1
        async def post(self, url, *, headers):
            assert url == recovery.auth_url + '/auth/v1/logout?scope=global'
            assert headers == {'Authorization': 'Bearer ' + tokens['owner']}
            assert state['events'][-1] == ('target-proof',)
            state['events'].append(('http', 'logout')); state['logged_out'] = True
            return SimpleNamespace(status_code=204)
        async def request(self, method, url, *, headers, json):
            assert (method, url, headers, json) == ('DELETE', recovery.auth_url + '/auth/v1/admin/users/' + owner_id,
                {'Authorization': 'Bearer generated-admin'}, {'should_soft_delete': True})
            assert state['events'][-1] == ('target-proof',)
            state['events'].append(('http', 'delete')); state['deleted'] = True
            if 'delete_response' in state:
                return state['delete_response']
            return SimpleNamespace(status_code=200)
    monkeypatch.setattr(inventory.httpx, 'AsyncClient', Client)

    def run():
        return control.run_async(inventory.verify_company_test_inventory_actor_recovery(
            recovery, COMPANY, expected, hashlib.sha256(wire(expected).encode()).hexdigest(),
            source_reader_url=source_reader, anon_key='generated-anon', owner_token=tokens['owner'],
            outsider_token=tokens['outsider'], stateless_owner_token=tokens['stateless']), budget=budget)

    # Expected locations come from four guarded raise statements, never caught traceback.
    tree = ast.parse(Path(inventory.__file__).read_text())
    guards = sorted((node for node in ast.walk(tree) if isinstance(node, ast.If)
        and isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not)
        and isinstance(node.test.operand, ast.Await) and isinstance(node.test.operand.value, ast.Call)
        and isinstance(node.test.operand.value.func, ast.Name)
        and node.test.operand.value.func.id == 'authentication_is_denied'), key=lambda node: node.lineno)
    expected_lines = {name: node.body[0].lineno for name, node in zip(
        ('stateless', 'banned', 'logout', 'deleted'), guards)}
    expected_events = [
        ('auth', 'owner', None), ('auth', 'outsider', None), ('auth', 'stateless', 'stateless'),
        ('auth', 'owner', None), ('read', 'owner'), ('auth', 'outsider', None), ('read', 'outsider'),
        ('sql', 'membership'), ('sql', 'owner'), ('auth', 'owner', None), ('read', 'owner'),
        ('sql', 'reviewer'), ('auth', 'owner', None), ('read', 'owner'),
        ('sql', 'read_only'), ('auth', 'owner', None), ('read', 'owner'),
        ('sql', 'unaccept'), ('auth', 'owner', None), ('read', 'owner'),
        ('sql', 'accept'), ('auth', 'owner', None), ('read', 'owner'),
        ('sql', 'ban_before'), ('sql', 'ban'), ('auth', 'owner', 'banned'), ('sql', 'unban'),
        ('auth', 'owner', None), ('read', 'owner'), ('sql', 'outsider_before'),
        ('sql', 'successor'), ('sql', 'revoke_member'), ('auth', 'owner', None), ('read', 'owner'),
        ('auth', 'outsider', None), ('read', 'outsider'), ('sql', 'sessions'),
        ('http', 'logout'), ('auth', 'owner', 'logout'), ('sql', 'restore_session'),
        ('auth', 'owner', None), ('http', 'delete'), ('auth', 'owner', 'deleted'),
        ('sql', 'deleted'), ('sql', 'erase'), ('auth', 'outsider', None), ('read', 'outsider'),
    ]
    def events():
        return [event for event in state['events'] if event[0] != 'target-proof']
    def stopped_at(probe, *, read):
        name = 'stateless' if probe == 'stateless' else 'owner'
        point = expected_events.index(('auth', name, probe))
        required = expected_events[:point + 1]
        if read: required += [('read', name)]
        if probe == 'banned': required += [('sql', 'unban')]
        assert events() == required
    yield SimpleNamespace(run=run, state=state, budget=budget, inventory=inventory,
        expected=expected, expected_lines=expected_lines, pending_auth=pending_auth, sql_steps=sql_steps,
        auth_order=auth_order, expected_events=expected_events, events=events, stopped_at=stopped_at)
    assert state['connections'] == state['closes']
    assert state['http_open'] == state['http_close']
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


@pytest.mark.parametrize('probe', ['stateless', 'banned', 'logout', 'deleted'])
def test_inventory_denial_callsite_branch_injection_has_distinct_location(inventory_denial_model, probe):
    """Deliberate normal return tests attribution, not actual Auth/SQL reachability."""
    model = inventory_denial_model
    model.state['admit'] = probe
    with pytest.raises(ValueError) as caught:
        model.run()
    assert str(caught.value) == 'Independent inventory accepted a revoked or deleted session'
    location = control._diagnostic_location(caught.value, model.budget, post_construction=True)
    assert location == {'module': 'inventory', 'line': model.expected_lines.get(probe),
                        'depth': 0, 'edge': 'primary'}, (probe, location, model.expected_lines)
    assert len(set(model.expected_lines.values())) == 4
    assert model.state['auth'] == model.auth_order[:len(model.state['auth'])]
    assert model.state['auth'][-1][1] == probe
    model.stopped_at(probe, read=True)
    if probe == 'banned':
        assert model.state['banned'] is None and model.state['sql'][-1] == 'unban'
    if probe in ('logout', 'deleted'):
        assert model.state['owner'] is False


def test_inventory_denial_callsite_expected_denials_continue_exact_lifecycle(inventory_denial_model):
    from dataclasses import asdict
    model = inventory_denial_model
    phase, end = model.budget.phase, model.budget.end
    report = model.run()
    assert asdict(report) == dict(
        record_count=model.expected.record_count, records_sha256=model.expected.records_sha256,
        target_observed_at=model.expected.observed_at,
        source_artifact_sha256=hashlib.sha256(model.inventory.rf.serialize_rf1086_company_test_retention(model.expected).encode()).hexdigest(),
        original_recorded_actors_preserved=True, current_membership_roles_verified=True,
        outsider_unaccepted_banned_and_revoked_denied=True, revoked_and_soft_deleted_sessions_denied=True,
        authorized_successor_recovered_inventory=True, stateless_owner_session_denied=True,
        physical_auth_user_erasure='blocked-by-preserved-historical-foreign-keys')
    assert model.state['auth'] == model.auth_order and not model.pending_auth and not model.sql_steps
    assert model.events() == model.expected_events
    assert model.state['owner'] is False and model.state['outsider'] is True
    assert model.state['banned'] is None and model.state['deleted'] is True
    assert (model.budget.phase, model.budget.end) == (phase, end)


@pytest.mark.parametrize('probe', ['stateless', 'banned', 'logout', 'deleted'])
@pytest.mark.parametrize('kind', ['domain', 'unavailable', 'ordinary', 'cancel', 'interrupt', 'exit'])
def test_inventory_denial_callsite_unexpected_error_identity_and_unwind(inventory_denial_model, probe, kind):
    import asyncio
    model = inventory_denial_model
    primary = {
        'domain': model.inventory.rf.ShareholderRegisterFilingError.not_found,
        'unavailable': model.inventory.rf.ShareholderRegisterFilingError.unavailable,
        'ordinary': lambda: ValueError('generated unexpected failure'),
        'cancel': lambda: asyncio.CancelledError('generated cancellation'),
        'interrupt': lambda: KeyboardInterrupt('generated interruption'),
        'exit': lambda: SystemExit('generated exit'),
    }[kind]()
    model.state['fault'] = (probe, primary)
    model.state['fault_at'] = 'read' if kind in ('domain', 'unavailable', 'ordinary') else 'auth'
    phase, end = model.budget.phase, model.budget.end
    with pytest.raises(type(primary)) as caught:
        model.run()
    assert caught.value is primary
    model.stopped_at(probe, read=model.state['fault_at'] == 'read')
    assert (model.budget.phase, model.budget.end) == (phase, end)
    if probe == 'banned':
        assert model.state['banned'] is None and model.state['sql'][-1] == 'unban'


@pytest.fixture
def postconstruction_model(repaired_model, tmp_path, monkeypatch):
    """Real repaired generator/receipt; generated transport and external services."""
    from test_rf1086_restore_control import postconstruction_inputs
    budget,state,calls,owners,_=repaired_model
    state['recoverPass']=True
    (tmp_path/'supabase').mkdir()
    (tmp_path/'supabase/config.toml').write_text('project_id="fixture"\n')
    monkeypatch.setattr(control,'internal_loopback_ports',lambda *a,**kw:nullcontext((19001,19003)))
    monkeypatch.setattr(identity,'auth_gateway',lambda *a,**kw:nullcontext('http://127.0.0.1:19002'))
    monkeypatch.setattr(identity,'verify_target_session',lambda *a,**kw:None)
    monkeypatch.setattr(identity,'verify_target_auth',lambda *a,**kw:None)
    monkeypatch.setattr(identity.httpx,'Client',lambda **kw:nullcontext(
        SimpleNamespace(get=lambda *a,**kw:SimpleNamespace(status_code=200))))
    boundary=SimpleNamespace(inspect_container=lambda *a,**kw:{'Config':{'Env':['SERVICE_KEY=fixture-key']}})
    generated=postconstruction_inputs()
    generated['prepared'].roles=SimpleNamespace(bootstrap='original_bootstrap',sql=b'persistent role program')
    generated['prepared'].script=b'original stream'
    monkeypatch.setattr(control,'prepare_archive',lambda *a,**kw:generated['prepared'])
    monkeypatch.setattr(control,'bind_tools',lambda *a,**kw:generated['prepared'].tools)
    def receipt(**kwargs):
        state['receipt']=kwargs;state['receiptCalls']=state.get('receiptCalls',0)+1
        for name in ('budget','source','target','image','before','recovered',
                     'cleanup_complete','source_postcheck','business_complete','reason'):
            if name in kwargs:generated[name]=kwargs[name]
        return state['constructionReceipt'](**generated)
    monkeypatch.setattr(control,'construction_receipt',receipt)
    return budget,state,calls,owners,boundary


@pytest.mark.parametrize('site,edge,business',[
    ('actors','before_yield',False),('auth','before_yield',False),
    ('caller','yield_boundary',False),('exit','after_yield',True)])
def test_postconstruction_marker_locates_context_edge_without_replacing_failure(
        postconstruction_model,tmp_path,monkeypatch,capsys,site,edge,business):
    from contextlib import contextmanager
    budget,state,calls,owners,boundary=postconstruction_model
    primary=ValueError('PRIVATE message/session/caller')
    def fail(*a,**kw):raise primary
    if site=='actors':monkeypatch.setattr(identity,'auth_environment',fail)
    if site=='auth':monkeypatch.setattr(identity,'verify_target_auth',fail)
    if site=='exit':
        @contextmanager
        def gateway(*a,**kw):
            yield 'http://127.0.0.1:19002'
            raise primary
        monkeypatch.setattr(identity,'auth_gateway',gateway)
    with pytest.raises(ValueError) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,boundary,budget=budget):
            if site=='caller':raise primary
    assert caught.value is primary and owners[0].cleaned
    assert state['postchecks']==3 and state['metadata']==3 and state['receiptCalls']==1
    assert state['targetCapture']._raw is None
    output=capsys.readouterr();assert output.out=='' and 'PRIVATE' not in output.err
    lines=output.err.splitlines()
    raw=next(line.split(' ',1)[1] for line in lines if line.startswith('owned_identity_restore_construction '))
    marker=[line.split(' ',1)[1] for line in lines
            if line.startswith('owned_identity_restore_post_construction_location ')]
    assert len(marker)==1
    value=json.loads(marker[0]);receipt=json.loads(raw)
    assert value['constructionSha256']==hashlib.sha256(raw.encode('ascii')).hexdigest()
    assert value['contextEdge']==edge and receipt['businessComplete'] is business
    assert value['location']['module']=='identity' and value['location']['edge']=='primary'
    assert receipt['status']=='constructed' and receipt['cleanupComplete'] and receipt['identitySourcePostcheck']
    assert control.validate_post_construction_location(value,construction_raw=raw) is value
    assert len(marker[0])+len(control.POST_CONSTRUCTION_PREFIX)+1<=4096


def test_postconstruction_inventory_invariant_keeps_real_frame_and_retained_binding(
        postconstruction_model,tmp_path,monkeypatch,capsys):
    import rf1086_company_test_inventory_identity_restore as inventory
    budget,state,calls,owners,boundary=postconstruction_model
    monkeypatch.setattr(inventory.rf,'serialize_rf1086_company_test_retention',lambda _: 'generated')
    def forbidden(*a,**kw):raise AssertionError('inventory target IO before first invariant')
    monkeypatch.setattr(inventory,'verify_target_session',forbidden)
    with pytest.raises(ValueError) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,boundary,budget=budget) as recovery:
            control.run_async(inventory.verify_company_test_inventory_actor_recovery(
                recovery,'selected',SimpleNamespace(company_id='different'),'a'*64,
                source_reader_url='postgresql://talli_ledger_backend@127.0.0.1/postgres',
                anon_key='generated',owner_token='generated',outsider_token='generated',
                stateless_owner_token='generated'),budget=budget)
    frames=[];tb=caught.value.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code is inventory.verify_company_test_inventory_actor_recovery.__code__:
            frames.append(tb.tb_lineno)
        tb=tb.tb_next
    assert len(frames)==1 and owners[0].cleaned
    default_location=control._diagnostic_location(caught.value,budget)
    assert default_location['module']=='control' and default_location['depth']==0
    assert control._diagnostic_location(caught.value,budget,post_construction=True)=={
        'module':'inventory','line':frames[0],'depth':0,'edge':'primary'}
    assert state['postchecks']==3 and state['metadata']==3 and state['receiptCalls']==1
    assert state['targetCapture']._raw is None
    output=capsys.readouterr();assert output.out==''
    lines=output.err.splitlines()
    raw=next(line.split(' ',1)[1] for line in lines if line.startswith('owned_identity_restore_construction '))
    markers=[json.loads(line.split(' ',1)[1]) for line in lines
             if line.startswith(control.POST_CONSTRUCTION_PREFIX)]
    assert len(markers)==1
    marker=markers[0]
    assert marker['location']=={'module':'inventory','line':frames[0],'depth':0,'edge':'primary'}
    assert marker['contextEdge']=='yield_boundary'
    assert marker['constructionSha256']==hashlib.sha256(raw.encode('ascii')).hexdigest()
    assert 'rf1086_company_test_inventory_identity_restore.py' in json.loads(raw)['code']
    assert control.validate_post_construction_location(marker,construction_raw=raw) is marker


@pytest.mark.parametrize('fault',['success','cleanup','source_post','cancel','system_exit',
                                  'write','write_cancel','classifier_cancel'])
def test_postconstruction_unavailable_observation_preserves_context_unwind(
        postconstruction_model,tmp_path,monkeypatch,capsys,fault):
    budget,state,calls,owners,boundary=postconstruction_model
    primary=(KeyboardInterrupt('PRIVATE') if fault=='cancel' else
             SystemExit('PRIVATE') if fault=='system_exit' else ValueError('PRIVATE'))
    if fault=='cleanup':state['cleanupFault']=True
    if fault=='source_post':
        command=budget.command
        def drift(args,**kw):
            result=command(args,**kw)
            return b'changed' if kw.get('data')==b'metadata' and state['metadata']==3 else result
        monkeypatch.setattr(budget,'command',drift)
    if fault=='classifier_cancel':
        def cancel(*a,**kw):raise KeyboardInterrupt('PRIVATE secondary')
        monkeypatch.setattr(control,'_diagnostic_location',cancel)
    if fault in ('write','write_cancel'):
        stderr=sys.stderr
        class Writer:
            def write(self,text):
                if text.startswith(control.POST_CONSTRUCTION_PREFIX):
                    if fault=='write_cancel':raise KeyboardInterrupt('PRIVATE secondary')
                    raise OSError('PRIVATE secondary')
                return stderr.write(text)
            def flush(self):return stderr.flush()
        monkeypatch.setattr(sys,'stderr',Writer())
    if fault=='success':
        with identity.restored_identity(SOURCE_URL,tmp_path,boundary,budget=budget):pass
    else:
        with pytest.raises(type(primary)) as caught:
            with identity.restored_identity(SOURCE_URL,tmp_path,boundary,budget=budget):raise primary
        assert caught.value is primary
    assert owners[0].cleaned and state['postchecks']==3 and state['metadata']==3
    assert state['receiptCalls']==1 and state['targetCapture']._raw is None
    assert not (tmp_path/'auth.env').exists()
    assert state['receipt']['cleanup_complete'] is (fault!='cleanup')
    assert state['receipt']['source_postcheck'] is (fault!='source_post')
    output=capsys.readouterr();assert output.out=='' and 'PRIVATE' not in output.err
    assert control.POST_CONSTRUCTION_PREFIX not in output.err
    if fault in ('write_cancel','classifier_cancel'):
        assert budget.context.owner.cancelled and budget.context.owner.primary is primary


def _empty_diagnostic_plan(raw):
    """Generated publisher-boundary fixture; no claim of database/source admission."""
    metadata=metadata_fixtures.m
    source=replace(metadata_fixtures.source(),objects=(),_catalog=raw)
    counts={'objects':0,'candidates':0,'archiveOnly':0,'unmodeled':0,'statements':0,'defaultAcls':0}
    binding={'profile':metadata.CONFIG_SHA256,'source':source.binding,
        'fixedSnapshot':source.snapshot_binding,
        'catalogObservation':{'bytes':len(raw) if isinstance(raw,bytes) else 0,
            'sha256':hashlib.sha256(raw if isinstance(raw,bytes) else b'').hexdigest()}}
    return metadata.RepairPlan(source,(),1,b'{}',metadata.canonical(counts),metadata.canonical(binding),())


@pytest.fixture
def repaired_model(tmp_path,monkeypatch):
    calls=[];owners=[];state={'metadata':0,'postchecks':0,'fault':None,'cleanupFault':False}
    role_raw=b'role observation'
    state['sourceCatalog']=b'[]\n{"datconnlimit":-1}\n[]\n'
    state['targetCatalog']=b'[]\n{"datconnlimit":10}\n[]\n'
    before=dict.fromkeys(('roles','catalog','auth','companyMemberships'),'a'*64)
    before['roles']=hashlib.sha256(role_raw).hexdigest()
    before['catalog']=hashlib.sha256(state['sourceCatalog']).hexdigest()
    plan=_empty_diagnostic_plan(state['sourceCatalog'])
    metadata=SimpleNamespace(METADATA_SQL=b'metadata',ROLE_ORDER_SQL=b'role order',
        Metadata=metadata_fixtures.m.Metadata,RepairPlan=metadata_fixtures.m.RepairPlan,
        Object=metadata_fixtures.m.Object,Candidate=metadata_fixtures.m.Candidate,
        CONFIG_SHA256=metadata_fixtures.m.CONFIG_SHA256,
        decode_metadata=lambda *a,**kw:plan.source,validate_role_order=lambda *a,**kw:None,
        bind_source_snapshot=lambda source,*a,**kw:source)
    monkeypatch.setitem(sys.modules,'rf1086_restore_metadata',metadata)
    monkeypatch.setattr(identity,'owned_identity_source',lambda *a:(DB,AUTH,ENV))
    monkeypatch.setattr(control,'require_local_docker',control.require_direct_loopback)
    def forbidden(*a,**kw):raise AssertionError('legacy diagnostic used during repaired restore')
    for name in ('CausalCapture','publish_actual_replay','emit_catalog_difference','emit_catalog_semantics'):
        monkeypatch.setattr(identity,name,forbidden)
    monkeypatch.setenv('TALLI_RF_REPLAY_DIR',str(tmp_path/'legacy-package-must-not-exist'))
    def fingerprint(container,**kwargs):
        if container==DB['Id']:
            state['postchecks']+=1
            if capture:=kwargs.get('catalog_capture'):capture.capture(state['sourceCatalog'])
            return dict(before)
        raw=state['sourceCatalog'] if state.get('recoverPass') else state['targetCatalog']
        if capture:=kwargs.get('catalog_capture'):
            capture.capture(raw);state['targetCapture']=capture
        return before|{'catalog':hashlib.sha256(raw).hexdigest()}
    monkeypatch.setattr(identity,'fingerprint',fingerprint)
    monkeypatch.setattr(identity,'source_query',lambda c,s,**kw:role_raw if s==identity.ROLE_SQL else b'pg_stat_statements')
    budget=control.RecoveryBudget(time.monotonic())
    def command(args,**kwargs):
        calls.append((args,kwargs))
        if kwargs.get('data')==b'metadata':
            state['metadata']+=1
            return b'drift' if state['fault']=='source_drift' and state['metadata']==2 else b'source metadata'
        if 'pg_dumpall' in args:return b'roles'
        if 'pg_dump' in args:return b'archive'
        if b"current_setting('hba_file')" in (kwargs.get('data') or b''):
            state['hbaReadback']=(budget.phase,kwargs['end'])
            if state.get('hbaFailure') is not None:raise state['hbaFailure']
            return state.get('hbaResult',b't\n')
        return b''
    monkeypatch.setattr(budget,'command',command)
    def prepare(*args,**kwargs):
        if state['fault']:raise control.RestoreUnavailable(state['fault'])
        return SimpleNamespace(roles=SimpleNamespace(bootstrap='original_bootstrap',sql=b'persistent role program'),
            tools={'bound':True},script=b'original stream',index=object(),plan=plan)
    monkeypatch.setattr(control,'prepare_archive',prepare)
    monkeypatch.setattr(control,'bind_tools',lambda *a,**kw:{'bound':True})
    monkeypatch.setattr(control,'source_fixed_snapshot',lambda *a,**kw:b'fixed snapshot')
    monkeypatch.setattr(control,'stream_restore',lambda *a,**kw:({'original':'complete'},{}))
    def receipt(**kwargs):
        state['receipt']=kwargs
        state['receiptCalls']=state.get('receiptCalls',0)+1
        if state.get('diagnosticReceipt'):
            return json.dumps({'schema':control.SCHEMA,'status':'unavailable',
                'bindings':{'plan':plan.binding},'counts':plan.counts,
                'fingerprints':{'source':kwargs['before'],'target':kwargs['recovered']}},
                sort_keys=True,separators=(',',':'))
        return '{"schema":"fixture-safe-receipt"}'
    state['constructionReceipt']=control.construction_receipt
    monkeypatch.setattr(control,'construction_receipt',receipt)
    real_owner=control.ResourceOwner
    state['realOwner']=real_owner
    class Owner:
        def __init__(self,nonce,*args):
            owners.append(self);self.cleaned=False;self.directory=tmp_path
            self.budget=budget;self.source=DB['Id'];self.identities={};self.attempted=[]
            self._hba_commitment=None
            self.names={k:'rf193_identity_'+k+'_'+nonce for k in ('network','volume','init','database','auth')}
            self.names['database']='rf193_identity_db_'+nonce
        def acquire(self,kind,args,**kw):
            self.attempted.append(kind);command(args,**kw)
            value={'init':'d'*64,'database':'e'*64}.get(kind,'f'*64)
            self.identities[kind]=value
            return value
        def inspect(self,kind,**kw):
            assert kind=='network' and self.attempted==['network']
            return {'Driver':'bridge','Scope':'local','Internal':True,'EnableIPv6':False,
                'IPAM':{'Config':[{'Subnet':'172.28.0.0/24','Gateway':'172.28.0.1'}]},'Containers':{}}
        bind_hba=real_owner.bind_hba
        verify_hba=real_owner.verify_hba
        def cleanup(self):
            self.cleaned=True
            if state['cleanupFault']:raise control.RestoreUnavailable('cleanup_uncertain')
    monkeypatch.setattr(control,'ResourceOwner',Owner)
    monkeypatch.setattr(identity,'query',lambda c,s,**kw:b'supabase_admin\n' if s=='select current_user;' else role_raw)
    preparations=[]
    monkeypatch.setattr(identity,'prepare_new_target_database',lambda *a,**kw:preparations.append((a,kw)))
    return budget,state,calls,owners,preparations


@pytest.mark.parametrize('fault',['archive_profile','suffix_profile','role_profile','deadline','source_drift'])
def test_failed_preparation_allocates_nothing_and_preserves_source_postcheck(repaired_model,tmp_path,fault,capsys):
    budget,state,calls,owners,_=repaired_model;state['fault']=fault
    with pytest.raises(control.RestoreUnavailable) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('unadmitted yield')
    assert caught.value.reason==fault and owners==[]
    assert not any(args[1] in ('create','network','volume') for args,_ in calls)
    assert state['postchecks']>=2 and state['metadata']==3
    captured=capsys.readouterr()
    assert captured.out==''
    lines=captured.err.splitlines()
    assert lines[:2]==[
        'owned_identity_restore_profile repair_profile_not_legacy_replay',
        'owned_identity_restore_construction {"schema":"fixture-safe-receipt"}']
    assert len(lines)==3 and lines[2].startswith(control.DIAGNOSTIC_PREFIX)
    observation=json.loads(lines[2][len(control.DIAGNOSTIC_PREFIX):])
    control.validate_pre_target_diagnostic(observation)
    assert observation['step']==('source_recheck' if fault=='source_drift' else 'unclassified')
    assert observation['reason']==fault and observation['inputs']['source']==state['receipt']['before']
    assert state['receipt']['cleanup_complete'] and state['receipt']['source_postcheck']
    assert not (tmp_path/'legacy-package-must-not-exist').exists()


@pytest.mark.parametrize('cleanup_fault',[False,True])
def test_strict_repaired_mismatch_never_publishes_old_replay_or_masks_original(repaired_model,tmp_path,cleanup_fault):
    budget,state,calls,owners,preparations=repaired_model;state['cleanupFault']=cleanup_fault
    with pytest.raises(ValueError,match='Independent recovery roles, ownership, ACLs or Auth rows differ; components=catalog'):
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('strict mismatch waived')
    assert len(owners)==1 and owners[0].cleaned and state['metadata']==3
    role_calls=[(args,kwargs) for args,kwargs in calls if kwargs.get('data')==b'persistent role program']
    assert len(role_calls)==1 and role_calls[0][0][role_calls[0][0].index('-U')+1]=='original_bootstrap'
    assert len(preparations)==1 and preparations[0][0][-1]=='original_bootstrap'
    assert preparations[0][1]['construction'] is True
    assert state['postchecks']==3 and not (tmp_path/'legacy-package-must-not-exist').exists()
    assert state['receipt']['cleanup_complete'] is (not cleanup_fault)
    assert state['receipt']['source_postcheck'] and not state['receipt']['business_complete']


def test_legacy_ssh_profile_refuses_before_source_or_target_work(repaired_model,tmp_path,monkeypatch):
    budget,state,calls,owners,_=repaired_model
    monkeypatch.setenv('TALLI_RF_RESTORE_SSH_CONFIG','/fixture/legacy-ssh')
    with pytest.raises(control.RestoreUnavailable) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('SSH profile admitted')
    assert caught.value.reason=='source_binding' and not calls and not owners
    assert state['postchecks']==0


def test_owned_hba_policy_is_installed_before_database_start(repaired_model,tmp_path):
    budget,_,calls,_,_=repaired_model
    with pytest.raises(ValueError,match='components=catalog'):
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            pytest.fail('strict mismatch admitted')
    created=[args for args,_ in calls if args[:2]==['docker','create']
             and '--user' in args and args[args.index('--user')+1]=='postgres']
    assert len(created)==1
    args=created[0]
    assert '-c hba_file=/tmp/rf-recovery/pg_hba.owned.conf' in args[-1]
    policy=next(value.split('=',1)[1] for value in args
                if value.startswith('RECOVERY_HBA='))
    assert 'host postgres supabase_auth_admin 172.28.0.0/24 scram-sha-256\n' in policy
    assert 'host postgres talli_ledger_backend 172.28.0.1/32 scram-sha-256\n' in policy


def test_owned_hba_initializer_is_fixed_exclusive_and_fail_before_exec():
    # Shell contract only: generated orchestration tests below cover startup refusal;
    # no shell/PG execution is claimed here.
    rows=identity.REPAIRED_INIT.splitlines()
    assert rows[:3]==identity.INIT.splitlines()[:3]
    assert rows[3:6]==['umask 077','set -C',
        'printf \'%s\' "$RECOVERY_HBA" > /tmp/rf-recovery/pg_hba.owned.conf']
    assert rows[0]=='set -eu' and len(rows)==7
    assert rows[-1]==identity.INIT.splitlines()[-1]+' -c hba_file=/tmp/rf-recovery/pg_hba.owned.conf'
    assert 'RECOVERY_HBA' not in identity.INIT and 'hba_file=' not in identity.INIT


@pytest.mark.parametrize('primary',[ValueError('generated readback fault'),KeyboardInterrupt('generated cancel'),
    SystemExit(23),control.RestoreUnavailable('deadline')])
@pytest.mark.parametrize('cleanup_fault',[False,True])
def test_owned_hba_readback_failure_never_reaches_auth_preserves_primary_and_sourcepost(
        repaired_model,tmp_path,primary,cleanup_fault):
    budget,state,calls,owners,_=repaired_model
    state.update(recoverPass=True,hbaFailure=primary,cleanupFault=cleanup_fault)
    with pytest.raises(type(primary)) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            pytest.fail('failed HBA readback yielded')
    assert caught.value is primary and owners[0].cleaned
    assert state['hbaReadback'][0]=='construction'
    assert state['receipt']['before']==state['receipt']['recovered']
    assert state['receipt']['source_postcheck'] and state['postchecks']==3
    assert state['receipt']['cleanup_complete'] is (not cleanup_fault)
    assert not any('--env-file' in args for args,_ in calls)
    assert not state['receipt']['business_complete'] and budget.phase=='source_post'


@pytest.mark.parametrize('reply',[b'f\n',b't\n\n',b''])
def test_owned_hba_readback_boolean_refusal_happens_before_actors(repaired_model,tmp_path,reply):
    budget,state,calls,owners,_=repaired_model
    state.update(recoverPass=True,hbaResult=reply)
    with pytest.raises(control.RestoreUnavailable) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):pytest.fail('invalid readback')
    assert caught.value.reason=='source_binding'
    assert owners[0].cleaned and state['receipt']['source_postcheck']
    assert not any('--env-file' in args for args,_ in calls)


@pytest.mark.parametrize('expire_fingerprint',[False,True])
def test_owned_hba_readback_shares_fingerprint_strict_end_without_reset(repaired_model,tmp_path,monkeypatch,expire_fingerprint):
    budget,state,calls,_,_=repaired_model;state['recoverPass']=True
    clock=[budget.started];ends=[]
    monkeypatch.setattr(control.time,'monotonic',lambda:clock[0])
    fingerprint=identity.fingerprint
    def observe(container,**kw):
        result=fingerprint(container,**kw)
        if container!=DB['Id']:
            ends.append(kw['checked_call'].keywords['end'])
            clock[0]+=10.01 if expire_fingerprint else 3
        return result
    monkeypatch.setattr(identity,'fingerprint',observe)
    primary=ValueError('stop after verifying unchanged deadline')
    state['hbaFailure']=primary
    with pytest.raises(control.RestoreUnavailable if expire_fingerprint else ValueError) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):pytest.fail('unexpected entry')
    assert ends==[budget.started+10]
    if expire_fingerprint:
        assert caught.value.reason=='deadline' and 'hbaReadback' not in state
    else:
        assert caught.value is primary and state['hbaReadback']==('construction',ends[0])
    assert state['receipt']['cleanup_complete'] and state['receipt']['source_postcheck']
    assert not any('--env-file' in args for args,_ in calls)


@pytest.mark.parametrize('fault',['constructor_record','acquire_record','create_lost','inspect_bad','bind_cancel'])
def test_owned_hba_real_constructor_and_early_network_failure_preserve_owner_scope(
        repaired_model,tmp_path,monkeypatch,fault):
    budget,state,calls,_,_=repaired_model
    real_owner=state['realOwner']; created=[];daemon={};primary=KeyboardInterrupt('generated early cancellation')
    directory=tmp_path/'real-owner';directory.mkdir()
    monkeypatch.setattr(control.tempfile,'mkdtemp',lambda **kw:str(directory))
    class Owner(real_owner):
        def __init__(self,*args):
            created.append(self);super().__init__(*args)
        def _record(self):
            if fault=='constructor_record' or fault=='acquire_record' and self.attempted:
                raise primary
            super()._record()
        def bind_hba(self,**kw):
            if fault=='bind_cancel':raise primary
            return super().bind_hba(**kw)
    monkeypatch.setattr(control,'ResourceOwner',Owner)
    original=budget.command
    def command(args,**kw):
        if args[:2]!=['docker','network']:return original(args,**kw)
        calls.append((args,kw));budget.remaining(end=kw.get('end'))
        if args[2]=='create':
            owner=created[0]
            assert json.loads(owner.record.read_bytes())['attempted']==['network']
            daemon[args[-1]]={'Id':'f'*64,'Name':args[-1],'Labels':{owner.label:owner.nonce},
                'Internal':True,'Driver':'overlay' if fault=='inspect_bad' else 'bridge',
                'Scope':'local','EnableIPv6':False,'Containers':{},
                'IPAM':{'Config':[{'Subnet':'172.28.0.0/24','Gateway':'172.28.0.1'}]}}
            if fault=='create_lost':raise primary
            return b'f'*64+b'\n'
        if args[2]=='ls':return b''.join((json.dumps(name)+'\n').encode() for name in daemon)
        if args[2]=='inspect':return json.dumps([daemon[args[-1]]]).encode()
        if args[2]=='rm':
            assert args[-1]=='f'*64;daemon.clear();return b''
        pytest.fail('unexpected network command')
    monkeypatch.setattr(budget,'command',command)
    with pytest.raises(control.RestoreUnavailable if fault=='inspect_bad' else KeyboardInterrupt) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):pytest.fail('invalid early binding')
    if fault!='inspect_bad':assert caught.value is primary
    assert state['receipt']['source_postcheck'] and not daemon
    assert not any(args[:3] in (['docker','volume','create'],['docker','create','--pull=never']) for args,_ in calls)
    if fault in ('constructor_record','acquire_record'):
        assert directory.exists()  # Failed local ownership acquisition is retained, not falsely erased.
        assert state['receipt']['cleanup_complete'] is (fault=='constructor_record')
    else:
        assert not directory.exists() and state['receipt']['cleanup_complete']


@pytest.mark.parametrize('fault',['start','policy_write_prevents_ready'])
def test_owned_hba_startup_failures_cannot_pass_readiness_or_reach_auth(repaired_model,tmp_path,monkeypatch,fault):
    budget,state,calls,owners,_=repaired_model;state['recoverPass']=True
    clock=[budget.started]
    monkeypatch.setattr(control.time,'monotonic',lambda:clock[0])
    original=budget.command;primary=control.RestoreUnavailable('child_failure')
    def command(args,**kw):
        if args==['docker','start','e'*64] and fault=='start':raise primary
        if 'pg_isready' in args:raise control.RestoreUnavailable('child_failure')
        return original(args,**kw)
    def pause(*args,**kw):clock[0]+=16;budget.remaining(end=kw['end'])
    monkeypatch.setattr(budget,'command',command);monkeypatch.setattr(budget,'pause',pause)
    with pytest.raises(control.RestoreUnavailable) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):pytest.fail('unready server yielded')
    if fault=='start':assert caught.value is primary
    else:assert caught.value.reason=='deadline'
    assert owners[0].cleaned and state['receipt']['source_postcheck']
    assert 'hbaReadback' not in state and not any('--env-file' in args for args,_ in calls)


@pytest.mark.parametrize('remaining',[100,4])
def test_final_fingerprints_share_ten_seconds_clipped_to_construction(repaired_model,tmp_path,monkeypatch,remaining):
    budget,state,calls,owners,_=repaired_model
    streamed=[]
    def stream(*args,**kw):
        now=time.monotonic();budget.end=now+remaining;streamed.append(now)
        return {'original':'complete'},{}
    monkeypatch.setattr(control,'stream_restore',stream)
    original=identity.fingerprint
    def fingerprint(container,**kwargs):
        if container!=DB['Id']:
            for i in range(4):kwargs['checked_call'](['strict-probe',str(i)])
        return original(container,**kwargs)
    monkeypatch.setattr(identity,'fingerprint',fingerprint)
    with pytest.raises(ValueError,match='components=catalog'):
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('strict mismatch waived')
    strict=[kw['end'] for args,kw in calls if args[0]=='strict-probe']
    assert len(strict)==4 and len(set(strict))==1
    assert streamed[0] < strict[0] <= streamed[0]+min(10.1,remaining)


def test_constructed_context_yields_same_budget_then_cleans_and_checks_source(repaired_model,tmp_path,monkeypatch,capsys):
    budget,state,calls,owners,_=repaired_model;state['recoverPass']=True
    (tmp_path/'supabase').mkdir()
    (tmp_path/'supabase/config.toml').write_text('project_id="fixture"\n')
    relays=[]
    def relay(owner,ports,*,budget):
        relays.append((owner,ports,budget))
        return nullcontext((19001,19003))
    monkeypatch.setattr(control,'internal_loopback_ports',relay)
    monkeypatch.setenv('TALLI_RF_IDENTITY_DB_PORT','19001')
    monkeypatch.setenv('TALLI_RF_IDENTITY_AUTH_PORT','19003')
    monkeypatch.setattr(identity,'auth_gateway',lambda *args,**kw:nullcontext('http://127.0.0.1:19002'))
    monkeypatch.setattr(identity,'verify_target_session',lambda *args,**kw:None)
    monkeypatch.setattr(identity,'verify_target_auth',lambda *args,**kw:None)
    monkeypatch.setattr(identity.httpx,'Client',lambda **kw:nullcontext(
        SimpleNamespace(get=lambda *a,**kw:SimpleNamespace(status_code=200))))
    boundary=SimpleNamespace(inspect_container=lambda *args,**kw:{'Config':{'Env':['SERVICE_KEY=fixture-key']}})
    with identity.restored_identity(SOURCE_URL,tmp_path,boundary,budget=budget) as recovered:
        assert budget.phase=='actors' and recovered.budget is budget
        assert recovered.proof['independentClusterRestored']
        assert (tmp_path/'auth.env').exists()
    assert budget.phase=='source_post' and owners[0].cleaned
    assert relays==[(owners[0],(19001,19003),budget)]
    readback_index=next(i for i,(_,kw) in enumerate(calls) if b"current_setting('hba_file')" in kw.get('data',b''))
    auth_index=next(i for i,(args,_) in enumerate(calls) if args[:2]==['docker','create'] and '--env-file' in args)
    assert readback_index<auth_index and state['hbaReadback'][0]=='construction'
    assert owners[0]._hba_commitment[3].endswith(
        b'host postgres talli_ledger_backend 172.28.0.1/32 scram-sha-256\n')
    assert all('-p' not in args for args,_ in calls if args[:2]==['docker','create'])
    assert not (tmp_path/'auth.env').exists()
    receipt=state['receipt']
    assert receipt['before']==receipt['recovered']
    assert receipt['cleanup_complete'] and receipt['source_postcheck'] and receipt['business_complete']
    expected={'status':'fixture_wrapper_complete'}
    print(json.dumps(expected))
    captured=capsys.readouterr()
    assert json.loads(captured.out)==expected
    assert captured.out==json.dumps(expected)+'\n'
    assert captured.err.splitlines()==[
        'owned_identity_restore_profile repair_profile_not_legacy_replay',
        'owned_identity_restore_construction {"schema":"fixture-safe-receipt"}']


@pytest.mark.parametrize('cleanup_fault', [False, True])
@pytest.mark.parametrize('primary', [ValueError('generated relay failure'), KeyboardInterrupt('generated cancellation')])
def test_relay_failure_preserves_primary_through_identity_cleanup_and_source_post(repaired_model,tmp_path,monkeypatch,cleanup_fault,primary):
    budget,state,calls,owners,_=repaired_model
    state['recoverPass']=True;state['cleanupFault']=cleanup_fault
    original_owner=control.ResourceOwner
    class Owner(original_owner):
        def __init__(self,*args):
            super().__init__(*args);self.budget=budget
        def internal_endpoints(self):return (('127.0.0.1',1),('127.0.0.1',2))
    monkeypatch.setattr(control,'ResourceOwner',Owner)
    def fail_setup(*args):raise primary
    monkeypatch.setattr(control._InternalRelay,'setup',fail_setup)
    with pytest.raises(type(primary)) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            pytest.fail('failed relay admitted identity')
    assert caught.value is primary and owners[0].cleaned
    assert state['postchecks']==3 and state['metadata']==3
    assert state['receipt']['source_postcheck']
    assert state['receipt']['cleanup_complete'] is (not cleanup_fault)
    assert not state['receipt']['business_complete']
    assert not (tmp_path/'auth.env').exists()


@pytest.mark.parametrize('step',[
    'source_fingerprint','source_roles','source_metadata_query','source_metadata_decode',
    'source_snapshot','source_snapshot_bind','source_preload','source_roles_dump',
    'source_archive_dump','source_recheck','target_admission',
])
def test_diagnostic_reports_only_the_actual_active_caller(repaired_model,tmp_path,monkeypatch,capsys,step):
    budget,state,calls,owners,_=repaired_model
    primary=ValueError('private source URL, SQL and error details')
    def fail(*args,**kwargs):raise primary
    module=sys.modules['rf1086_restore_metadata']
    if step=='source_fingerprint':monkeypatch.setattr(identity,'fingerprint',fail)
    elif step in ('source_roles','source_preload'):
        original=identity.source_query
        def source_query(container,statement,**kwargs):
            if (statement==identity.ROLE_SQL)==(step=='source_roles'):raise primary
            return original(container,statement,**kwargs)
        monkeypatch.setattr(identity,'source_query',source_query)
    elif step=='source_metadata_decode':monkeypatch.setattr(module,'decode_metadata',fail)
    elif step=='source_snapshot_bind':monkeypatch.setattr(module,'bind_source_snapshot',fail)
    elif step=='source_snapshot':monkeypatch.setattr(control,'source_fixed_snapshot',fail)
    elif step=='target_admission':monkeypatch.setattr(budget,'before_target',fail)
    else:
        original=budget.command
        metadata_calls=0
        def command(args,**kwargs):
            nonlocal metadata_calls
            if kwargs.get('data')==b'metadata':metadata_calls+=1
            if (step=='source_metadata_query' and metadata_calls==1
                or step=='source_recheck' and kwargs.get('data')==b'metadata' and metadata_calls==2
                or step=='source_roles_dump' and 'pg_dumpall' in args
                or step=='source_archive_dump' and 'pg_dump' in args):raise primary
            return original(args,**kwargs)
        monkeypatch.setattr(budget,'command',command)
    with pytest.raises(ValueError) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('unadmitted yield')
    assert caught.value is primary and not owners
    output=capsys.readouterr()
    assert output.out=='' and 'private source' not in output.err
    lines=[line for line in output.err.splitlines() if line.startswith(control.DIAGNOSTIC_PREFIX)]
    assert len(lines)==1
    value=json.loads(lines[0][len(control.DIAGNOSTIC_PREFIX):])
    assert value['step']==step and value['component']=='unknown' and value['reason']=='internal'
    assert state['receipt']['cleanup_complete']
    assert value['inputs']['source'] is None if step=='source_fingerprint' else value['inputs']['source'] is not None


def test_capture_is_disabled_before_uuid_or_any_target_setup(repaired_model,tmp_path,monkeypatch,capsys):
    budget,state,calls,owners,_=repaired_model
    primary=ValueError('later uuid error')
    def fail():raise primary
    monkeypatch.setattr(identity,'uuid4',fail)
    with pytest.raises(ValueError) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('unadmitted yield')
    assert caught.value is primary and not owners
    assert control.DIAGNOSTIC_PREFIX not in capsys.readouterr().err


def test_caller_cancellation_never_becomes_diagnostic_or_resource_admission(repaired_model,tmp_path,monkeypatch,capsys):
    budget,state,calls,owners,_=repaired_model
    primary=KeyboardInterrupt('private')
    original=budget.command
    def command(args,**kwargs):
        if 'pg_dump' in args:raise primary
        return original(args,**kwargs)
    monkeypatch.setattr(budget,'command',command)
    with pytest.raises(KeyboardInterrupt) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('unadmitted yield')
    assert caught.value is primary and not owners
    assert state['receipt']['cleanup_complete'] and state['receipt']['source_postcheck']
    assert control.DIAGNOSTIC_PREFIX not in capsys.readouterr().err


def test_final_catalog_diagnostic_commits_exact_once_emitted_receipt_after_cleanup(repaired_model,tmp_path,capsys):
    budget,state,_,owners,_=repaired_model;state['diagnosticReceipt']=True
    with pytest.raises(ValueError,match='components=catalog'):
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('strict mismatch waived')
    output=capsys.readouterr();assert output.out==''
    receipt_line=next(line for line in output.err.splitlines() if line.startswith('owned_identity_restore_construction '))
    diagnostic_lines=[line for line in output.err.splitlines() if line.startswith('owned_identity_restore_catalog_diagnostic ')]
    assert len(diagnostic_lines)==1
    value=json.loads(diagnostic_lines[0].split(' ',1)[1])
    assert value['schema']=='rf1086-restore-catalog-diagnostic-v2' and value['status']=='observed'
    assert value['relationProfiles']==[]
    assert value['constructionSha256']==hashlib.sha256(receipt_line.split(' ',1)[1].encode()).hexdigest()
    assert value['source']=={'bytes':len(state['sourceCatalog']),'sha256':state['receipt']['before']['catalog']}
    assert value['target']=={'bytes':len(state['targetCatalog']),'sha256':state['receipt']['recovered']['catalog']}
    assert value['difference']['summary']==[{'kind':'database','status':'changed','records':1,
        'fields':[{'field':'datconnlimit','change':'value','count':1}]}]
    assert state['receiptCalls']==1 and owners[0].cleaned and state['receipt']['source_postcheck']
    assert budget.phase=='source_post' and state['targetCapture']._raw is None
    assert len(diagnostic_lines[0].encode())+1<=20*1024


def _catalog_receipt(source,target):
    fingerprints={key:dict.fromkeys(('roles','catalog','auth','companyMemberships'),'a'*64)
                  for key in ('source','target')}
    for key,raw in (('source',source),('target',target)):
        fingerprints[key]['catalog']=hashlib.sha256(raw).hexdigest()
    return control.ledger.canonical({'schema':control.SCHEMA,'status':'unavailable',
                                    'fingerprints':fingerprints}).decode('ascii')


def _publish_catalog(source,target,*,receipt=None,budget=None,plan=None):
    receipt=receipt or _catalog_receipt(source,target)
    plan=plan or _empty_diagnostic_plan(source)
    parsed=json.loads(receipt)
    parsed.setdefault('bindings',{'plan':plan.binding});parsed.setdefault('counts',plan.counts)
    receipt=control.ledger.canonical(parsed).decode('ascii')
    if budget is None:
        budget=control.RecoveryBudget(time.monotonic());budget.enter('source_post')
    control.publish_catalog_postcondition(budget,construction_raw=receipt,
        source_metadata=plan.source,prepared=SimpleNamespace(plan=plan),target_capture=SimpleNamespace(_raw=target),
        primary=ValueError('private primary'))
    return receipt,budget


def _catalog_line(capsys):
    output=capsys.readouterr();assert output.out==''
    lines=output.err.splitlines()
    assert len(lines)==1 and lines[0].startswith(control.CATALOG_DIAGNOSTIC_PREFIX)
    assert len(output.err.encode())<=20*1024 and 'private-' not in output.err
    return json.loads(lines[0][len(control.CATALOG_DIAGNOSTIC_PREFIX):])


@pytest.mark.parametrize('kind',['schema','relation','function','default_acl','column_acl',
    'policy','database','unknown_database_fields','settings','representation','truncated'])
def test_catalog_projection_preserves_classifier_vocabulary_and_raw_hashes(kind,capsys):
    from test_rf1086_catalog_difference import raw,ROWS
    source=raw();rows=deepcopy(ROWS)
    if kind=='database':target=raw(database={'datconnlimit':10})
    elif kind=='unknown_database_fields':
        source=raw(database={'private-a':1,'private-b':2})
        target=raw(database={'private-a':3,'private-b':4})
    elif kind=='settings':target=raw(settings=[])
    elif kind=='representation':target=raw(list(reversed(rows)))
    elif kind=='truncated':
        source=raw(rows=[['schema',f'private-{i}','owner',None] for i in range(80)])
        target=raw(rows=[])
    else:
        target=raw(rows=[row for row in ROWS if row[0]!=kind])
    receipt,budget=_publish_catalog(source,target)
    value=_catalog_line(capsys)
    assert value['status']=='observed' and budget.phase=='source_post'
    control.validate_catalog_postcondition(value,construction_raw=receipt)
    assert value['source']['sha256']==hashlib.sha256(source).hexdigest()
    assert value['target']['sha256']==hashlib.sha256(target).hexdigest()
    if kind=='representation':assert value['difference']['status']=='representation-only'
    if kind=='truncated':assert value['difference']['truncated'] and len(value['difference']['details'])==32


@pytest.fixture
def observed_catalog_diagnostic(capsys):
    source=b'[]\n{"datconnlimit":-1}\n[]\n';target=b'[]\n{"datconnlimit":10}\n[]\n'
    receipt,_=_publish_catalog(source,target)
    return _catalog_line(capsys),receipt


@pytest.mark.parametrize('mutation',[
    lambda v:v.update(extra='private-raw'),
    lambda v:v.update(constructionSha256='f'*64),
    lambda v:v['source'].update(bytes=True),
    lambda v:v['target'].update(bytes=8*1024*1024+1),
    lambda v:v['target'].update(sha256=v['source']['sha256']),
    lambda v:v['difference'].update(status='equal'),
    lambda v:v['difference'].update(qualification='accepted'),
    lambda v:v['difference']['counts'].update(changed=True),
    lambda v:v['difference'].update(sourceRecords=v['difference']['sourceRecords']+1),
    lambda v:v['difference']['summary'][0].update(records=2),
    lambda v:v['difference']['summary'][0].update(kind='private-kind'),
    lambda v:v['difference']['details'][0].update(schema='private-schema'),
    lambda v:v['difference']['details'][0].update(kind=[]),
    lambda v:v['difference']['details'][0].update(raw='private-raw'),
    lambda v:v['difference']['details'][0]['fields'][0].update(field='private-field'),
    lambda v:v['difference']['details'][0]['fields'][0].update(change='private-change'),
    lambda v:v['difference']['details'].append(deepcopy(v['difference']['details'][0])),
    lambda v:v['difference'].update(truncated=True),
    lambda v:v.update(status='unavailable',reason='input'),
])
def test_catalog_reader_rejects_malformed_or_unbound_projection(observed_catalog_diagnostic,mutation):
    value,receipt=observed_catalog_diagnostic;mutation(value)
    with pytest.raises(ValueError):control.validate_catalog_postcondition(value,construction_raw=receipt)


@pytest.mark.parametrize(('fault','reason'),[
    ('missing','input'),('oversize','input'),('hash','binding'),('raw','classifier'),('classifier','classifier')])
def test_catalog_diagnostic_invalid_inputs_and_classifier_never_reflect_values(fault,reason,monkeypatch,capsys):
    source=b'[]\n{}\n[]\n';target=b'[]\n{"datconnlimit":10}\n[]\n'
    if fault=='raw':source=b'private-invalid-catalog'
    receipt=_catalog_receipt(source,target)
    if fault=='missing':source=None
    if fault=='oversize':source=b'x'*(8*1024*1024+1)
    if fault=='hash':source=b'private-different-value'
    if fault=='classifier':
        monkeypatch.setattr(control.difference,'catalog_difference',lambda *a:{'raw':'private-catalog'})
    receipt,_=_publish_catalog(source,target,receipt=receipt)
    value=_catalog_line(capsys)
    assert value['status']=='unavailable' and value['reason']==reason
    assert value['source'] is value['target'] is value['difference'] is None
    control.validate_catalog_postcondition(value,construction_raw=receipt)


@pytest.mark.parametrize('fault',['classifier','cancel_classifier','cancel_write','broken_write',
    'expired','blocked_write','cleanup','source_post','missing_retention','broken_retention','cancel_retention',
    'missing_plan','broken_plan','cancel_plan'])
def test_catalog_diagnostic_failure_preserves_primary_cleanup_and_clears_capture(
        repaired_model,tmp_path,monkeypatch,capsys,fault):
    budget,state,_,owners,_=repaired_model;state['diagnosticReceipt']=True
    if fault=='cleanup':state['cleanupFault']=True
    original_publish=control.publish_catalog_postcondition;seen=[]
    def publish(value,**kwargs):
        seen.append(kwargs['primary'])
        assert owners[0].cleaned and value.phase=='source_post' and state['metadata']==3
        if fault=='expired':value.end=time.monotonic()-1
        if fault=='blocked_write':value.end=time.monotonic()+.03
        if fault.endswith('retention'):
            if fault=='missing_retention':kwargs['source_metadata']=object()
            else:
                class Broken:
                    @property
                    def _catalog(self):
                        if fault=='cancel_retention':raise KeyboardInterrupt('private-retention')
                        raise RuntimeError('private-retention')
                kwargs['source_metadata']=Broken()
        if fault.endswith('_plan'):
            if fault=='missing_plan':kwargs['prepared']=None
            else:
                class BrokenPlan:
                    @property
                    def plan(self):
                        if fault=='cancel_plan':raise KeyboardInterrupt('private-plan')
                        raise RuntimeError('private-plan')
                kwargs['prepared']=BrokenPlan()
        return original_publish(value,**kwargs)
    monkeypatch.setattr(control,'publish_catalog_postcondition',publish)
    if fault in ('classifier','cancel_classifier'):
        def fail(*a):
            if fault=='cancel_classifier':raise KeyboardInterrupt('private-classifier')
            raise ValueError('private-classifier')
        monkeypatch.setattr(control.difference,'catalog_difference',fail)
    if fault.endswith('write'):
        stderr=sys.stderr
        class Writer:
            def write(self,text):
                if text.startswith(control.CATALOG_DIAGNOSTIC_PREFIX):
                    if fault=='cancel_write':raise KeyboardInterrupt('private-write')
                    if fault=='broken_write':raise OSError('private-write')
                    time.sleep(.3)
                return stderr.write(text)
            def flush(self):return stderr.flush()
        monkeypatch.setattr(sys,'stderr',Writer())
    if fault=='source_post':
        command=budget.command
        def changed(args,**kwargs):
            raw=command(args,**kwargs)
            return b'changed' if kwargs.get('data')==b'metadata' and state['metadata']==3 else raw
        monkeypatch.setattr(budget,'command',changed)
    started=time.monotonic()
    with pytest.raises(ValueError,match='components=catalog') as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('strict mismatch waived')
    assert seen==[caught.value] and state['targetCapture']._raw is None
    assert owners[0].cleaned and state['postchecks']==3 and state['receiptCalls']==1
    assert budget.context.owner.cancelled is fault.startswith('cancel_')
    output=capsys.readouterr();assert output.out=='' and 'private-' not in output.err
    if fault in ('expired','blocked_write'):
        assert control.CATALOG_DIAGNOSTIC_PREFIX not in output.err
    if fault=='blocked_write':assert time.monotonic()-started<.25
    assert signal.getitimer(signal.ITIMER_REAL)[0]==0


def test_non_catalog_mismatch_does_not_publish_catalog_diagnostic(repaired_model,tmp_path,monkeypatch,capsys):
    budget,state,_,_,_=repaired_model;state['recoverPass']=True
    original=identity.fingerprint
    def fingerprint(container,**kwargs):
        value=original(container,**kwargs)
        return value if container==DB['Id'] else value|{'auth':'f'*64}
    monkeypatch.setattr(identity,'fingerprint',fingerprint)
    with pytest.raises(ValueError,match='components=auth'):
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):pass
    assert control.CATALOG_DIAGNOSTIC_PREFIX not in capsys.readouterr().err
    assert state['targetCapture']._raw is None


def test_classifier_and_publication_share_one_end_no_write_after_elapsed(monkeypatch,capsys):
    source=b'[]\n{}\n[]\n';target=b'[]\n{"datconnlimit":10}\n[]\n'
    value=control.RecoveryBudget(time.monotonic());value.enter('source_post');end=value.end
    now=time.monotonic();clock=[now]
    original=control.difference.catalog_difference
    def classify(*args):
        assert 0<signal.getitimer(signal.ITIMER_REAL)[0]<=1
        result=original(*args);clock[0]=now+1.1;return result
    monkeypatch.setattr(control.difference,'catalog_difference',classify)
    monkeypatch.setattr(control.time,'monotonic',lambda:clock[0])
    _publish_catalog(source,target,budget=value)
    assert capsys.readouterr().err=='' and value.phase=='source_post' and value.end==end
    assert signal.getitimer(signal.ITIMER_REAL)[0]==0


def test_catalog_envelope_limit_is_total_line_and_unavailable_is_closed(monkeypatch,capsys):
    source=b'[]\n{}\n[]\n';target=b'[]\n{"datconnlimit":10}\n[]\n'
    fields=sorted(control.difference._DATABASE_FIELDS)
    changes=[{'field':field,'change':'value'} for field in fields]
    oversized={'status':'different','sourceRecords':32,'targetRecords':32,
        'counts':{'changed':32,'source-only':0,'target-only':0},
        'summary':[{'kind':'database','status':'changed','records':32,
                    'fields':[item|{'count':32} for item in changes]}],
        'details':[{'kind':'database','schema':'unclassified',
                    'identitySha256':hashlib.sha256(str(i).encode()).hexdigest(),
                    'status':'changed','fields':deepcopy(changes)} for i in range(32)],
        'truncated':False,'qualification':'diagnostic-only-strict-fingerprint-unchanged'}
    assert len(control.ledger.canonical(oversized))>20*1024
    monkeypatch.setattr(control.difference,'catalog_difference',lambda *a:oversized)
    receipt,_=_publish_catalog(source,target)
    value=_catalog_line(capsys)
    assert value['status']=='unavailable' and value['reason']=='limit'
    control.validate_catalog_postcondition(value,construction_raw=receipt)


def test_relation_branch_uses_same_compiled_plan_and_exact_unicode_identity(capsys):
    import test_rf1086_restore_metadata as fixtures
    wire=fixtures.fixture();wire['objects'][0]['identity'][2]='table_é'
    source,script,archive,index=fixtures.plan_data(wire)
    archive.entries[0].tag='table_é'.encode()
    plan=fixtures.compile_((source,script,archive,index))
    rows=json.loads(source._catalog.split(b'\n')[0]);rows[0][5]=None
    target=fixtures.encode(rows)+b'\n{}\n[]\n'
    receipt=json.loads(_catalog_receipt(source._catalog,target))
    receipt['bindings']={'plan':plan.binding}
    receipt['counts']=plan.counts
    receipt=control.ledger.canonical(receipt).decode('ascii')
    budget=control.RecoveryBudget(time.monotonic());budget.enter('source_post')
    control.publish_catalog_postcondition(budget,construction_raw=receipt,
        source_metadata=source,prepared=SimpleNamespace(plan=plan),target_capture=SimpleNamespace(_raw=target),
        primary=ValueError('private primary'))
    value=_catalog_line(capsys)
    assert value['schema']=='rf1086-restore-catalog-diagnostic-v2' and value['status']=='observed'
    # Literal UTF8 identity, independently of the ASCII ledger canonicalizer.
    digest=hashlib.sha256('["relation","public","table_é"]'.encode('utf8')).hexdigest()
    assert value['relationProfiles']==[{'identitySha256':digest,'branch':'candidate',
        'relationKind':'r','hasColumnAcls':False,'sourceAclEqualsDefault':True,
        'initialAclNull':True,'initialAclEqualsSource':False,'extensionMember':False,
        'candidateMaterialize':True,'ownerProfileFailures':[]}]
    control.validate_catalog_postcondition(value,construction_raw=receipt)


def _relation_plan_case(case):
    """Real metadata decoder/compiler; only the final generated catalog is changed."""
    f=metadata_fixtures;m=f.m
    wire=f.fixture(ordered=case in ('candidate','predicted','initial-equal'))
    obj=wire['objects'][0];suffix=b'';columns=()
    if case=='source-null':obj['acl']=None
    elif case in ('column','column-seed','column-partial','column-missing','column-nonowner'):
        obj['columnAclCount']=1
        columns=(['column_acl','public','t','id','{reader=r/supabase_admin}'],)
        if case=='column':obj['kind']='p'  # Outside the new ordinary-table domain.
        elif case=='column-partial':obj['acl']=f.acl([f.item(rights=('SELECT',))])
        elif case=='column-missing':obj['acl']=f.acl([f.item('reader',('SELECT',))])
        elif case=='column-nonowner':obj['acl']=f.acl([f.item(),f.item('reader',('SELECT',),grantor='writer')])
    elif case=='relkind':obj['kind']='i'
    elif case=='partial-owner':obj['acl']=f.acl([f.item(rights=('SELECT',))])
    elif case=='duplicate':obj['acl']=f.acl([f.item(),f.item()])
    elif case=='nonowner':obj['acl']=f.acl([f.item(),f.item('reader',('SELECT',),grantor='writer')])
    elif case=='empty-rights':obj['acl']=f.acl([f.item(),f.item('reader',())])
    elif case=='public-option':obj['acl']=f.acl([f.item(),f.item(None,('SELECT',),('SELECT',))])
    elif case=='initial-equal':
        obj['initialAcl']=deepcopy(obj['acl']);obj['initialPrivilegeType']='e'
    elif case=='extension':obj['extension']=[['private_extension','1.0',f.OWNER]]
    if case in ('candidate','predicted'):
        suffix=b'GRANT SELECT ON TABLE public.t TO reader;\n'
        if case=='candidate':obj['acl']=f.acl(list(reversed(obj['acl']['items'])))
    _,script,archive,index=f.plan_data(suffix=suffix)
    archive.entries[0].description=b'TABLE'
    source=f.source(wire,column_rows=columns)
    index['objects'][0]['kind']=obj['kind']
    plan=m.compile_plan(source,script=script,archive=archive,index=index,deadline=f.end())
    rows=json.loads(source._catalog.split(b'\n')[0])
    rows[0][5]=source.objects[0].default.raw if obj['acl'] is None else None
    target=f.encode(rows)+b'\n{}\n[]\n'
    return plan,target


@pytest.mark.parametrize('case,branch,failures',[
    ('source-null','source-acl-null',[]),('column','unsupported-column',[]),
    ('column-seed','candidate',[]),('column-partial','candidate',['owner-item-not-default']),
    ('column-missing','candidate',['owner-item-not-default']),
    ('column-nonowner','owner-profile-rejected',['nonowner-grantor']),
    ('relkind','unsupported-relkind',[]),('partial-owner','owner-profile-rejected',['owner-item-not-default']),
    ('duplicate','owner-profile-rejected',['duplicate-pairs','owner-item-not-default']),
    ('nonowner','owner-profile-rejected',['nonowner-grantor']),
    ('empty-rights','owner-profile-rejected',['empty-privileges']),
    ('public-option','owner-profile-rejected',['public-grant-option']),
    ('materialize','candidate',[]),('candidate','candidate',[]),
    ('predicted','predicted-source-archive-only',[]),('initial-equal','predicted-source-archive-only',[]),
    ('extension','candidate',[]),
])
def test_real_compiler_branch_traits_are_diagnostic_not_a_mutation_claim(case,branch,failures,capsys):
    plan,target=_relation_plan_case(case)
    receipt,_=_publish_catalog(plan.source._catalog,target,plan=plan)
    value=_catalog_line(capsys);assert value['status']=='observed'
    traits=value['relationProfiles'][0]
    assert traits['branch']==branch and traits['ownerProfileFailures']==failures
    assert traits['hasColumnAcls'] is case.startswith('column')
    assert traits['sourceAclEqualsDefault'] is (case in ('column','column-seed','relkind','materialize','extension'))
    assert traits['initialAclNull'] is (case!='initial-equal')
    assert traits['initialAclEqualsSource'] is (case in ('source-null','initial-equal'))
    assert traits['extensionMember'] is (case=='extension')
    assert traits['candidateMaterialize']==(case in ('materialize','extension','column-seed') if branch=='candidate' else None)
    assert not any(key in traits for key in ('name','acl','owner','grantor','sql','applied','noop'))
    encoded=json.dumps(value)
    assert all(text not in encoded for text in ('supabase_admin','private_extension','=arwdDxtm/','"reader"'))
    control.validate_catalog_postcondition(value,construction_raw=receipt)
    if case=='candidate':
        # Selected candidate can be a real compiler no-op; publication does not imply SQL ran.
        wire=metadata_fixtures.fixture(ordered=True)
        wire['objects'][0]['acl']=metadata_fixtures.acl(list(reversed(wire['objects'][0]['acl']['items'])))
        mutation=metadata_fixtures.m.pre_acl(plan,metadata_fixtures.target(wire,explicit=True),
                                            deadline=metadata_fixtures.end())
        assert mutation.noop==1 and mutation.applied==0 and mutation.sql==b''


@pytest.mark.parametrize('case,mutation',[
    ('materialize',lambda v:v.update(relationProfiles=None)),
    ('materialize',lambda v:v.update(relationProfiles=[])),
    ('materialize',lambda v:v['relationProfiles'].append(deepcopy(v['relationProfiles'][0]))),
    ('materialize',lambda v:v['relationProfiles'][0].update(identitySha256='f'*64)),
    ('materialize',lambda v:v['relationProfiles'][0].update(raw='private-secret')),
    ('materialize',lambda v:v['relationProfiles'][0].update(branch='private-secret')),
    ('materialize',lambda v:v['relationProfiles'][0].update(relationKind='private-secret')),
    ('materialize',lambda v:v['relationProfiles'][0].update(hasColumnAcls=1)),
    ('materialize',lambda v:v['relationProfiles'][0].update(extensionMember=0)),
    ('materialize',lambda v:v['relationProfiles'][0].update(initialAclNull=0)),
    ('materialize',lambda v:v['relationProfiles'][0].update(initialAclEqualsSource=True)),
    ('materialize',lambda v:v['relationProfiles'][0].update(candidateMaterialize=1)),
    ('materialize',lambda v:v['relationProfiles'][0].update(candidateMaterialize=False)),
    ('materialize',lambda v:v['relationProfiles'][0].update(ownerProfileFailures=['private-secret'])),
    ('materialize',lambda v:v['relationProfiles'][0].update(branch='unsupported-column',candidateMaterialize=None)),
    ('materialize',lambda v:v['relationProfiles'][0].update(branch='unsupported-relkind',candidateMaterialize=None)),
    ('materialize',lambda v:v['relationProfiles'][0].update(branch='owner-profile-rejected',candidateMaterialize=None)),
    ('materialize',lambda v:v['relationProfiles'][0].update(branch='source-acl-null',
        sourceAclEqualsDefault=False,initialAclEqualsSource=True,candidateMaterialize=None)),
    ('source-null',lambda v:v['relationProfiles'][0].update(branch='predicted-source-archive-only',initialAclEqualsSource=False)),
    ('duplicate',lambda v:v['relationProfiles'][0].update(ownerProfileFailures=['owner-item-not-default','duplicate-pairs'])),
    ('duplicate',lambda v:v['relationProfiles'][0].update(ownerProfileFailures=['duplicate-pairs','duplicate-pairs'])),
    ('column',lambda v:v['relationProfiles'][0].update(branch='candidate',candidateMaterialize=True)),
    ('column-seed',lambda v:v['relationProfiles'][0].update(extensionMember=True)),
    ('column-seed',lambda v:v['relationProfiles'][0].update(initialAclNull=False)),
    ('column-seed',lambda v:v['relationProfiles'][0].update(branch='unsupported-column',candidateMaterialize=None)),
    ('column-partial',lambda v:v['relationProfiles'][0].update(ownerProfileFailures=['nonowner-grantor','owner-item-not-default'])),
    ('materialize',lambda v:v.update(schema='rf1086-restore-catalog-diagnostic-v1')),
])
def test_relation_profile_forgery_rejected_even_with_matching_outer_hashes(case,mutation,capsys):
    plan,target=_relation_plan_case(case)
    receipt,_=_publish_catalog(plan.source._catalog,target,plan=plan)
    value=_catalog_line(capsys);assert value['status']=='observed'
    mutation(value)
    with pytest.raises(ValueError):control.validate_catalog_postcondition(value,construction_raw=receipt)


@pytest.mark.parametrize('case',['source-null','materialize'])
def test_non_acl_changes_do_not_invent_source_acl_state(case,capsys):
    plan,_=_relation_plan_case(case)
    rows=json.loads(plan.source._catalog.split(b'\n')[0]);rows[0][6]=True
    target=metadata_fixtures.encode(rows)+b'\n{}\n[]\n'
    receipt,_=_publish_catalog(plan.source._catalog,target,plan=plan)
    value=_catalog_line(capsys)
    assert value['status']=='observed' and value['difference']['details'][0]['fields']==[
        {'field':'rls','change':'value'}]
    assert value['relationProfiles'][0]['branch']==('source-acl-null' if case=='source-null' else 'candidate')
    control.validate_catalog_postcondition(value,construction_raw=receipt)


@pytest.mark.parametrize('fault',['missing-prepared','missing-plan','foreign-plan','source-copy',
    'binding','catalog-binding','wire-binding','profile','counts','candidate-object',
    'candidate-duplicate','candidate-missing','duplicate-source','missing-source','object-cap'])
def test_branch_binding_failure_never_infers_archive_only(fault,capsys):
    plan,target=_relation_plan_case('materialize');source=plan.source
    receipt=json.loads(_catalog_receipt(source._catalog,target))
    receipt.update(bindings={'plan':plan.binding},counts=plan.counts)
    if fault=='source-copy':plan=replace(plan,source=replace(source))
    elif fault in ('binding','catalog-binding','wire-binding','profile'):
        binding=plan.binding
        if fault=='binding':binding['source']['sha256']='f'*64
        elif fault=='catalog-binding':binding['catalogObservation']['bytes']+=1
        elif fault=='wire-binding':source=replace(source,_wire=b'private-mutated');plan=replace(plan,source=source)
        else:binding['profile']='f'*64
        plan=replace(plan,_binding=control.ledger.canonical(binding))
        receipt['bindings']['plan']=binding
    elif fault=='counts':receipt['counts']['candidates']=0
    elif fault=='candidate-object':
        obj=replace(plan.candidates[0].object,owner='private-owner')
        plan=replace(plan,candidates=(replace(plan.candidates[0],object=obj),))
    elif fault=='candidate-duplicate':
        plan=replace(plan,candidates=plan.candidates*2)
        counts=plan.counts;counts['candidates']=2
        plan=replace(plan,_counts=control.ledger.canonical(counts));receipt['counts']=counts
    elif fault=='candidate-missing':
        obj=replace(plan.candidates[0].object,identity=('relation','public','private-absent'))
        plan=replace(plan,candidates=(replace(plan.candidates[0],object=obj),))
    elif fault in ('duplicate-source','missing-source','object-cap'):
        objects=source.objects+(source.objects[0],) if fault=='duplicate-source' else (
            source.objects[1:] if fault=='missing-source' else (source.objects[0],)*8193)
        source=replace(source,objects=objects);counts=plan.counts;counts['objects']=len(objects)
        plan=replace(plan,source=source,_counts=control.ledger.canonical(counts));receipt['counts']=counts
    prepared=SimpleNamespace(plan=plan)
    if fault=='missing-prepared':prepared=None
    elif fault=='missing-plan':prepared=object()
    elif fault=='foreign-plan':prepared=SimpleNamespace(plan=object())
    raw=control.ledger.canonical(receipt).decode('ascii')
    budget=control.RecoveryBudget(time.monotonic());budget.enter('source_post')
    control.publish_catalog_postcondition(budget,construction_raw=raw,
        source_metadata=source,prepared=prepared,target_capture=SimpleNamespace(_raw=target),
        primary=ValueError('private primary'))
    value=_catalog_line(capsys)
    assert value['status']=='unavailable' and value['reason']=='binding'
    assert value['relationProfiles'] is value['difference'] is value['source'] is value['target'] is None
    control.validate_catalog_postcondition(value,construction_raw=raw)


def _many_relation_plan(count):
    f=metadata_fixtures;m=f.m
    wire=f.fixture();_,script,archive,index=f.plan_data()
    original=wire['objects'][0];wire['objects']=wire['objects'][1:]
    for i in range(count):
        row=deepcopy(original);row['identity'][2]=f't_{i:02}';row['objectOid']+=i
        # Source-null rows need no lifecycle/seed and still exercise actual compiler classification.
        row['acl']=None;wire['objects'].append(row)
    source=f.source(wire);index['objects']=[]
    plan=m.compile_plan(source,script=script,archive=archive,index=index,deadline=f.end())
    rows=json.loads(source._catalog.split(b'\n')[0])
    for row in rows:
        if row[0]=='relation':row[5]=original['defaultAcl']['raw']
    return plan,f.encode(rows)+b'\n{}\n[]\n'


@pytest.mark.parametrize('count',[32,33])
def test_relation_profiles_exact_retained_order_and_truncation_not_full_coverage(count,capsys):
    plan,target=_many_relation_plan(count)
    receipt,_=_publish_catalog(plan.source._catalog,target,plan=plan)
    value=_catalog_line(capsys);assert value['status']=='observed'
    assert len(value['relationProfiles'])==32 and value['difference']['counts']['changed']==count
    assert value['difference']['truncated'] is (count==33)
    assert [p['identitySha256'] for p in value['relationProfiles']]==[
        d['identitySha256'] for d in value['difference']['details']]
    assert all(p['branch']=='source-acl-null' for p in value['relationProfiles'])
    value['relationProfiles'].reverse()
    with pytest.raises(ValueError):control.validate_catalog_postcondition(value,construction_raw=receipt)


@pytest.mark.parametrize('fault',['broken','cancel','expired'])
def test_plan_retention_failure_is_shielded_and_cancellation_sticky(fault,capsys):
    plan,target=_relation_plan_case('materialize');source=plan.source
    receipt=json.loads(_catalog_receipt(source._catalog,target))
    receipt.update(bindings={'plan':plan.binding},counts=plan.counts)
    raw=control.ledger.canonical(receipt).decode('ascii')
    budget=control.RecoveryBudget(time.monotonic());budget.enter('source_post')
    phase,end=budget.phase,budget.end;primary=ValueError('private original')
    class Prepared:
        @property
        def plan(self):
            assert 0<signal.getitimer(signal.ITIMER_REAL)[0]<=1
            if fault=='cancel':raise KeyboardInterrupt('private secondary')
            if fault=='expired':raise control.RestoreUnavailable('deadline')
            raise AttributeError('private missing plan')
    control.publish_catalog_postcondition(budget,construction_raw=raw,
        source_metadata=source,prepared=Prepared(),target_capture=SimpleNamespace(_raw=target),primary=primary)
    assert budget.phase==phase and budget.end==end
    assert signal.getitimer(signal.ITIMER_REAL)[0]==0
    assert budget.context.owner.cancelled is (fault=='cancel')
    if fault=='broken':
        value=_catalog_line(capsys);assert value['status']=='unavailable' and value['reason']=='binding'
    else:assert capsys.readouterr().err==''


# Response injection is generated; no actual Auth response or mutation is claimed.
def _softdelete_location_lines(inventory):
    import ast
    from pathlib import Path
    tree = ast.parse(Path(inventory.__file__).read_text())
    labels = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name) and node.test.left.id == 'category'
                and len(node.test.ops) == 1 and isinstance(node.test.ops[0], ast.Eq)
                and len(node.test.comparators) == 1 and isinstance(node.test.comparators[0], ast.Constant)
                and len(node.body) == 1 and isinstance(node.body[0], ast.Raise)):
            labels[node.test.comparators[0].value] = node.body[0].lineno
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Attribute) and node.test.left.attr == 'status_code'
                and isinstance(node.test.left.value, ast.Name) and node.test.left.value.id == 'response'
                and isinstance(node.test.ops[0], ast.NotEq)
                and isinstance(node.test.comparators[0], ast.Constant)
                and node.test.comparators[0].value == 200
                and isinstance(node.body[-1], ast.Raise)):
            labels['other_non200'] = node.body[-1].lineno
    return labels


def test_inventory_softdelete_status_has_distinct_source_location(inventory_denial_model):
    model = inventory_denial_model
    model.state['delete_response'] = SimpleNamespace(status_code=401, content=b'generated private response')
    with pytest.raises(ValueError) as caught:
        model.run()
    assert str(caught.value) == 'Independent inventory Auth soft deletion failed'
    location = control._diagnostic_location(caught.value, model.budget, post_construction=True)
    expected = _softdelete_location_lines(model.inventory)
    assert len(expected) == 14, (location, expected)
    assert location == dict(module='inventory', line=expected['http_401'], depth=0, edge='primary')
    assert caught.value.__context__ is None


_SOFTDELETE_MESSAGES = [
    ('load_user', 'Database error loading user'),
    ('audit', 'Error recording audit log entry'),
    ('soft_user', 'Error soft deleting user'),
    ('soft_identities', 'Error soft deleting user identities'),
    ('factors', "Error deleting user's factors"),
    ('webauthn', "Error deleting user's WebAuthn credentials"),
    ('sessions', "Error deleting user's sessions"),
    ('hard_user', 'Database error deleting user'),
]


def _assert_softdelete_stopped(model):
    point = model.expected_events.index(('http', 'delete'))
    assert model.events() == model.expected_events[:point + 1]
    assert list(model.pending_auth) == [('owner', 'deleted'), ('outsider', None)]
    assert [step[0] for step in model.sql_steps] == ['deleted', 'erase']
    assert model.state['connections'] == model.state['closes']
    assert model.state['http_open'] == model.state['http_close'] == 1


def _assert_softdelete_category(model, response, category, capsys):
    model.state['delete_response'] = response
    phase, end = model.budget.phase, model.budget.end
    with pytest.raises(ValueError) as caught:
        model.run()
    assert type(caught.value) is ValueError
    assert str(caught.value) == 'Independent inventory Auth soft deletion failed'
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    lines = _softdelete_location_lines(model.inventory)
    assert len(lines) == len(set(lines.values())) == 14
    location = control._diagnostic_location(caught.value, model.budget, post_construction=True)
    assert location == dict(module='inventory', line=lines[category], depth=0, edge='primary')
    assert 'PRIVATE' not in json.dumps(location)
    output = capsys.readouterr()
    assert output.out == output.err == ''
    assert (model.budget.phase, model.budget.end) == (phase, end)
    _assert_softdelete_stopped(model)


@pytest.mark.parametrize('status,category', [
    (401, 'http_401'), (403, 'http_403'), (404, 'http_404'), (502, 'http_502'),
    (201, 'other_non200'), (204, 'other_non200'), (429, 'other_non200'), (503, 'other_non200'),
])
def test_inventory_softdelete_non500_never_reads_body(inventory_denial_model, capsys, status, category):
    class Response:
        status_code = status
        @property
        def content(self):
            raise AssertionError('non500 content must not be inspected')
    _assert_softdelete_category(inventory_denial_model, Response(), category, capsys)


@pytest.mark.parametrize('category,message', _SOFTDELETE_MESSAGES)
@pytest.mark.parametrize('shape', ['legacy', 'legacy_id', 'new'])
def test_inventory_softdelete_exact_public_message_locations(inventory_denial_model, capsys, category, message, shape):
    body = ({'code': 'unexpected_failure', 'message': message} if shape == 'new' else
            {'code': 500, 'error_code': 'unexpected_failure', 'msg': message})
    if shape == 'legacy_id':
        body['error_id'] = 'PRIVATE ignored identifier'
    _assert_softdelete_category(inventory_denial_model,
        SimpleNamespace(status_code=500, content=json.dumps(body).encode()), category, capsys)


@pytest.mark.parametrize('body', [
    b'', b'{', b'\xff', b'\xed\xa0\x80', b'\xef\xbb\xbf{}', b'null', b'[]', b'500', b'true', b'"PRIVATE"',
    b'[' * 2000 + b']' * 2000,
    b'{"code":500,"code":500,"error_code":"unexpected_failure","msg":"Error soft deleting user"}',
    br'{"code":500,"error_code":"unexpected_failure","msg":"Error soft deleting user","m\u0073g":"Error soft deleting user"}',
    b'{"code":500,"error_code":"unexpected_failure","msg":{"x":1,"x":2}}',
    b'{"code":NaN,"error_code":"unexpected_failure","msg":"Error soft deleting user"}',
    b'{"code":Infinity,"error_code":"unexpected_failure","msg":"Error soft deleting user"}',
    b'{"code":-Infinity,"error_code":"unexpected_failure","msg":"Error soft deleting user"}',
    *[json.dumps(body).encode() for body in [
        {},
        {'code': True, 'error_code': 'unexpected_failure', 'msg': 'Error soft deleting user'},
        {'code': 500.0, 'error_code': 'unexpected_failure', 'msg': 'Error soft deleting user'},
        {'code': '500', 'error_code': 'unexpected_failure', 'msg': 'Error soft deleting user'},
        {'code': 401, 'error_code': 'unexpected_failure', 'msg': 'Error soft deleting user'},
        {'code': 500, 'error_code': 'PRIVATE', 'msg': 'Error soft deleting user'},
        {'code': 500, 'error_code': 'unexpected_failure', 'msg': ['Error soft deleting user']},
        {'code': 500, 'error_code': 'unexpected_failure', 'msg': 'Error soft deleting user', 'error_id': None},
        {'code': 500, 'error_code': 'unexpected_failure', 'msg': 'Error soft deleting user', 'message': 'Error soft deleting user'},
        {'code': 500, 'error_code': 'unexpected_failure', 'msg': 'Error soft deleting user', 'internal_error': 'PRIVATE'},
        {'code': 500, 'msg': 'Error soft deleting user'},
        {'code': 'unexpected_failure', 'message': 'PRIVATE Error soft deleting user'},
        {'code': 'unexpected_failure', 'message': 'Error soft deleting user PRIVATE'},
        {'code': 'unexpected_failure', 'message': 'error soft deleting user'},
        {'code': 'unexpected_failure', 'message': 'Error soft deleting user\n'},
        {'code': 'unexpected_failure', 'message': None},
        {'code': 'unexpected_failure', 'message': {'PRIVATE': 'Error soft deleting user'}},
        {'code': 'unexpected_failure', 'message': 'Error soft deleting user', 'error_id': 'PRIVATE'},
        {'code': 'unexpected_failure', 'message': 'Error soft deleting user', 'extra': 'PRIVATE'},
        {'code': 500, 'message': 'Error soft deleting user'},
        {'code': 'PRIVATE', 'message': 'Error soft deleting user'},
    ]],
    'PRIVATE nonbytes', None,
])
def test_inventory_softdelete_invalid_body_stays_generic_without_context(inventory_denial_model, capsys, body):
    _assert_softdelete_category(inventory_denial_model,
        SimpleNamespace(status_code=500, content=body), 'http_500', capsys)


@pytest.mark.parametrize('length,category', [(4096, 'soft_user'), (4097, 'http_500')])
def test_inventory_softdelete_body_byte_cap(inventory_denial_model, capsys, length, category):
    raw = b'{"code":"unexpected_failure","message":"Error soft deleting user"}'
    raw += b' ' * (length - len(raw))
    assert len(raw) == length
    _assert_softdelete_category(inventory_denial_model,
        SimpleNamespace(status_code=500, content=raw), category, capsys)


def test_inventory_softdelete_success_body_unread_exact_lifecycle(inventory_denial_model):
    from dataclasses import asdict
    model = inventory_denial_model
    class Response:
        status_code = 200
        @property
        def content(self):
            raise AssertionError('200 content must not be inspected')
    model.state['delete_response'] = Response()
    phase, end = model.budget.phase, model.budget.end
    result = asdict(model.run())
    assert result['revoked_and_soft_deleted_sessions_denied'] is True
    assert result['physical_auth_user_erasure'] == 'blocked-by-preserved-historical-foreign-keys'
    assert model.events() == model.expected_events
    assert model.state['auth'] == model.auth_order and not model.pending_auth and not model.sql_steps
    assert (model.budget.phase, model.budget.end) == (phase, end)


@pytest.mark.parametrize('seam', ['content', 'decode', 'object_hook'])
@pytest.mark.parametrize('kind', ['deadline', 'limit', 'ordinary', 'cancel', 'interrupt', 'exit'])
def test_inventory_softdelete_unexpected_failure_identity(inventory_denial_model, monkeypatch, seam, kind):
    import asyncio
    model = inventory_denial_model
    primary = {
        'deadline': lambda: control.RestoreUnavailable('deadline'),
        'limit': lambda: control.RestoreUnavailable('limit'),
        'ordinary': lambda: ValueError('PRIVATE unexpected'),
        'cancel': lambda: asyncio.CancelledError('PRIVATE cancellation'),
        'interrupt': lambda: KeyboardInterrupt('PRIVATE interrupt'),
        'exit': lambda: SystemExit('PRIVATE exit'),
    }[kind]()
    content = b'{"code":"unexpected_failure","message":"Error soft deleting user"}'
    class Response:
        status_code = 500
        @property
        def content(self):
            if seam == 'content':
                raise primary
            return content
    saved_loads = model.inventory.json.loads
    def loads(value, **kwargs):
        if 'object_pairs_hook' not in kwargs:
            return saved_loads(value, **kwargs)
        if seam == 'decode':
            raise primary
        if seam == 'object_hook':
            hook = kwargs['object_pairs_hook']
            def pairs(items):
                yield items[0]
                raise primary
            kwargs['object_pairs_hook'] = lambda items: hook(pairs(items))
        return saved_loads(value, **kwargs)
    monkeypatch.setattr(model.inventory.json, 'loads', loads)
    model.state['delete_response'] = Response()
    phase, end = model.budget.phase, model.budget.end
    with pytest.raises(type(primary)) as caught:
        model.run()
    assert caught.value is primary
    assert (model.budget.phase, model.budget.end) == (phase, end)
    _assert_softdelete_stopped(model)
