"""Predecessor rehearsals must restore the installed successor topology."""
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath

import pytest

import test_authority_connections_database_runtime as rehearsal


ROOT = Path(__file__).resolve().parents[3]
RULE = json.loads((ROOT / 'tests/fixtures/governance_completion_replay.json').read_text())
COMPLETION_PATH = 'supabase/migrations/' + RULE['migration']
COMPLETION_SOURCE = (ROOT / COMPLETION_PATH).read_text()
RECEIPT_REPLAY = '20261016134500_company_year_receipt_replay.sql'


def test_receipt_successor_is_detected_even_when_historical_select_policy_was_replaced():
    names = [layer['migration'] for layer in rehearsal.RF193_CONSEQUENTIAL]
    assert RECEIPT_REPLAY in names
    assert names.index(RECEIPT_REPLAY) > names.index('20260924080208_company_access_rf_admission_guard.sql')
    layer = next(layer for layer in rehearsal.RF193_CONSEQUENTIAL if layer['migration'] == RECEIPT_REPLAY)
    # The historical support rehearsal replaces SELECT, but retains this
    # installed UPDATE guard. Probing SELECT's repaired text would miss exactly
    # the damaged topology that the successor must restore.
    assert 'pg_policy' in layer['presenceQuery']
    assert 'company year receipts reject updates' in layer['presenceQuery']
    assert 'company access commands read receipts' not in layer['presenceQuery']


def test_receipt_successor_replay_recreates_both_update_checks_without_changing_actor_scope():
    source = rehearsal.read_rehearsal_migration(ROOT, RECEIPT_REPLAY)
    assert source == (ROOT / 'supabase/migrations' / RECEIPT_REPLAY).read_text()
    drop = source.index('drop policy if exists "company year receipts reject updates"')
    create = source.index('create policy "company year receipts reject updates"')
    assert drop < create
    assert 'actor_id = public.company_access_auth_uid_v1()' in source
    assert "command_name in ('accept_invitation', 'admit_company_year', 'recheck_company_year_eligibility')" in source
    assert 'as restrictive for update' in source
    assert 'to company_access_executor, company_access_recovery_executor' in source
    assert "using (command_name not in ('admit_company_year', 'recheck_company_year_eligibility'))" in source
    assert "with check (command_name not in ('admit_company_year', 'recheck_company_year_eligibility'))" in source


@pytest.mark.parametrize('phase',['legacy_overlap','canonical_overlap','contracted'])
@pytest.mark.parametrize('latest',[False,True])
def test_predecessor_restores_installed_successors_after_contract_even_when_body_fails(monkeypatch,phase,latest):
    legacy=[name for name,_ in rehearsal.RF193_LAYERS]
    successors=[layer['migration'] for layer in rehearsal.RF193_CONSEQUENTIAL]
    if not latest: successors=successors[:5]
    layers=legacy+successors;calls=[];present=set(successors);adapted_calls=[]
    by_query={layer['presenceQuery']:layer['migration'] for layer in rehearsal.RF193_CONSEQUENTIAL}
    class File:
        def __init__(self,path=''):self.path=path
        def __truediv__(self,part):return File(str(PurePosixPath(self.path)/part))
        def read_text(self):
            return COMPLETION_SOURCE if self.path == COMPLETION_PATH else self.path
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,statement):
            if statement.startswith('--') and RULE['after'] in statement:
                assert sha256(statement.encode()).hexdigest() == RULE['rehearsalSha256']
                adapted_calls.append(statement)
                statement = COMPLETION_PATH
            calls.append(statement)
            self.result=(statement in by_query and by_query[statement] in present,)
            if statement=='supabase/rollback/'+rehearsal.RF151_EXPAND:
                present.difference_update(name for name in present.copy() if 'rf1086' in name)
            if statement.startswith('supabase/migrations/'):
                name=PurePosixPath(statement).name
                if name in rehearsal.RF193_CONSEQUENTIAL_NAMES:present.add(name)
            return self
        def fetchone(self):return self.result
    monkeypatch.setattr(rehearsal,'ROOT',File())
    monkeypatch.setattr(rehearsal.psycopg,'connect',lambda *a,**kw:Connection())
    monkeypatch.setattr(rehearsal,'rf193_successor_topology',lambda connection:(phase,layers))
    monkeypatch.setattr(rehearsal,'ensure_fixture_admin_access',lambda connection:calls.append('restore_fixture_access'))
    generator=rehearsal.rf151_predecessor_topology.__wrapped__(None)
    next(generator)
    with pytest.raises(RuntimeError,match='predecessor body failed'):
        generator.throw(RuntimeError('predecessor body failed'))
    restored=[PurePosixPath(call).name for call in calls if call.startswith('supabase/migrations/')]
    assert restored[-len(successors):]==successors
    assert not any(call.startswith('supabase/rollback/') and PurePosixPath(call).name in successors for call in calls)
    assert present==set(successors)
    assert len(adapted_calls) == int(RULE['migration'] in successors)
    if phase=='contracted':
        contract=calls.index('supabase/contract-migrations/'+rehearsal.RF151_CONTRACT)
        assert all(calls.index('supabase/migrations/'+name)>contract for name in successors)
    assert calls[-1]=='restore_fixture_access'


def test_no_rf_schema_does_not_install_a_new_topology(monkeypatch):
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,*args):pytest.fail('No RF topology must remain untouched')
    monkeypatch.setattr(rehearsal.psycopg,'connect',lambda *a,**kw:Connection())
    monkeypatch.setattr(rehearsal,'rf193_successor_topology',lambda connection:(None,[]))
    generator=rehearsal.rf151_predecessor_topology.__wrapped__(None)
    next(generator)
    with pytest.raises(StopIteration):next(generator)
