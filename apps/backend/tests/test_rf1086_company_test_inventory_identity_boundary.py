"""Fixed target boundary negative cases; doubles establish no live Auth proof."""
import asyncio
from hashlib import sha256
from types import SimpleNamespace

import pytest

from test_rf1086_company_test_retention_restore_runner import signed, CLAIMS
import rf1086_company_test_inventory_identity_restore as inventory
from test_rf1086_company_test_retention import COMPANY, ACTOR, capture, record, wire
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, UserId


PROOF = {key: True for key in ('independentClusterRestored', 'independentAuthRestored',
    'authHttpTargetBindingVerified', 'roleAttributesAndMembershipsRestored',
    'ownershipGrantsAndRlsRestored', 'authRowsRestoredExactly')}


def recovery():
    return SimpleNamespace(proof=dict(PROOF), database_url='owned-target', database_container='owned-target-id',
        bootstrap='owned-bootstrap', auth_url='http://127.0.0.1:55002', reader_url=lambda source: 'mapped-owned-reader')


@pytest.mark.parametrize('failure', ['source-sha', 'unavailable', 'company', 'reader-role', 'proof-false', 'proof-missing'])
def test_untrusted_scope_cannot_reach_target_or_auth(monkeypatch, failure):
    expected = capture(record())
    rec = recovery()
    reader = 'postgresql://talli_ledger_backend:synthetic@127.0.0.1:55001/postgres'
    company = COMPANY
    digest = sha256(wire(expected).encode()).hexdigest()
    if failure == 'source-sha': digest = '0'*64
    elif failure == 'unavailable':
        expected = rf.Rf1086CompanyTestRetentionSnapshot(COMPANY, 'unavailable', None, None, None, None)
        digest = sha256(wire(expected).encode()).hexdigest()
    elif failure == 'company': company = type(COMPANY)('00000000-0000-0000-0000-000000000009')
    elif failure == 'reader-role': reader = 'postgresql://postgres:synthetic@127.0.0.1:55001/postgres'
    elif failure == 'proof-false': rec.proof['independentClusterRestored'] = False
    else: del rec.proof['authHttpTargetBindingVerified']
    monkeypatch.setattr(inventory, 'verify_target_session', lambda *args: pytest.fail('reached target'))
    monkeypatch.setattr(inventory, 'PostgresCompanyTestRetentionSessionFactory', lambda *args: pytest.fail('reached Auth'))
    with pytest.raises(ValueError):
        asyncio.run(inventory.verify_company_test_inventory_actor_recovery(rec, company, expected, digest,
            source_reader_url=reader, anon_key='synthetic', owner_token='synthetic-owner', outsider_token='synthetic-outsider',
            stateless_owner_token='synthetic-stateless'))


@pytest.mark.parametrize('valid', [True, False])
def test_every_synthetic_target_connection_requires_live_container_proof_first(monkeypatch, valid):
    events = []
    def verify(*args):
        events.append('verify')
        if not valid: raise ValueError('not-owned-target')
    monkeypatch.setattr(inventory, 'verify_target_session', verify)
    class Connection:
        def __enter__(self): events.append('enter');return self
        def __exit__(self, *args): events.append('close')
    def connect(url):
        assert events[-1] == 'verify';events.append('connect');return Connection()
    monkeypatch.setattr(inventory.psycopg, 'connect', connect)
    if valid:
        with inventory._target_connection(recovery()): events.append('body')
        assert events == ['verify','connect','enter','body','close']
    else:
        with pytest.raises(ValueError, match='not-owned-target'):
            with inventory._target_connection(recovery()): pytest.fail('entered unowned target')
        assert events == ['verify']


@pytest.mark.parametrize('stateless', [
    'malformed', signed(CLAIMS),
    signed({**{k:v for k,v in CLAIMS.items() if k!='session_id'}, 'sub':'00000000-0000-0000-0000-000000000009'}),
    'x'*65537, 'no-historical-actor',
])
def test_stateless_probe_must_bind_original_owner_and_cannot_reach_fixture_mutations(monkeypatch, stateless):
    expected = capture(record())
    if stateless == 'no-historical-actor':
        expected = capture(record(recorded_by='00000000-0000-0000-0000-000000000009'))
    monkeypatch.setattr(inventory, 'verify_target_session', lambda *args: None)
    monkeypatch.setattr(inventory.psycopg, 'connect', lambda *args: pytest.fail('reached mutation'))
    actors = [ACTOR, ActorId(ActorKind.USER, UserId('00000000-0000-0000-0000-000000000008'))]
    class Factory:
        def __init__(self, config): self.actors=iter(actors)
        async def session(self, token): return SimpleNamespace(actor_id=next(self.actors))
    monkeypatch.setattr(inventory, 'PostgresCompanyTestRetentionSessionFactory', Factory)
    with pytest.raises(ValueError, match='original recorded actor' if stateless == 'no-historical-actor' else 'stateless probe'):
        asyncio.run(inventory.verify_company_test_inventory_actor_recovery(recovery(), COMPANY, expected,
            sha256(wire(expected).encode()).hexdigest(), source_reader_url='postgresql://talli_ledger_backend:synthetic@127.0.0.1:55001/postgres',
            anon_key='synthetic', owner_token='synthetic-owner', outsider_token='synthetic-outsider', stateless_owner_token=stateless))
