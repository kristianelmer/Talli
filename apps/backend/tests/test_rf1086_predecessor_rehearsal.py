"""Predecessor rehearsals must restore the installed successor topology."""
from pathlib import PurePosixPath

import pytest

import test_authority_connections_database_runtime as rehearsal


@pytest.mark.parametrize('phase',['legacy_overlap','canonical_overlap','contracted'])
@pytest.mark.parametrize('latest',[False,True])
def test_predecessor_restores_installed_successors_after_contract_even_when_body_fails(monkeypatch,phase,latest):
    legacy=[name for name,_ in rehearsal.RF193_LAYERS]
    successors=[layer['migration'] for layer in rehearsal.RF193_CONSEQUENTIAL]
    if not latest: successors=successors[:5]
    layers=legacy+successors;calls=[];present=set(successors)
    by_query={layer['presenceQuery']:layer['migration'] for layer in rehearsal.RF193_CONSEQUENTIAL}
    class File:
        def __init__(self,path=''):self.path=path
        def __truediv__(self,part):return File(str(PurePosixPath(self.path)/part))
        def read_text(self):return self.path
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,statement):
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
