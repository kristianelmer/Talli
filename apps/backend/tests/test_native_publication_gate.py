import asyncio
from pathlib import Path
import sys
from uuid import uuid4

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'scripts'))
import rf1086_identity_restore as identity

from talli_backend.adapters.restored_publication import publication_is_current
from talli_backend.adapters.deletion_journal import LocalDeletionJournal, LocalReplayReceipt
from talli_backend.application.company_disposition import replay_company_dispositions
from test_deletion_replay import authorization_fixture, SyntheticDocumentStore, NOW
from talli_backend.modules.company_access.public import authorize_company_disposition


def test_publication_requires_each_exact_target_owner_prefix(tmp_path):
    plan,facts=authorization_fixture();permit=authorize_company_disposition(plan,facts,now=NOW)
    store=SyntheticDocumentStore(tmp_path/'customer',plan=plan)
    journal=LocalDeletionJournal.initialize(tmp_path/'journal.sqlite',customer_root=store.root)
    head=journal.append(permit);target=str(uuid4());receipt=LocalReplayReceipt(store.root/'ready.json')
    args={'journal':journal.path,'receipt':receipt.path,'target':target,'stream':journal.stream,
          'minimum_sequence':head.sequence,'minimum_sha256':head.sha256}
    receipt.publish(target,head)
    assert not publication_is_current(**args)  # a head-only receipt cannot release pending work
    asyncio.run(replay_company_dispositions(journal=journal,target=target,receipt=receipt,minimum=head,stores={'documents':store}))
    assert publication_is_current(**args)
    with journal._connection(write=True) as db:db.execute('delete from applied where target=?',(target,))
    assert not publication_is_current(**args)


def test_core_native_auth_probe_is_deferred_until_verified_publication(monkeypatch):
    events=[]
    class Gate:
        opened=False
        def require_open(self):
            events.append('gate')
            if not self.opened:raise ValueError('quarantined')
        def revoke(self):events.append('revoke')
    gate=Gate()
    monkeypatch.setattr(identity,'verify_target_auth',lambda *a,**k:events.append('auth'))
    target=identity.RecoveredIdentity('private','private','private','owned','supabase_admin',{},publication=gate)
    with pytest.raises(ValueError,match='quarantined'):target.verify_publication()
    assert events==['gate','revoke'] and not target.proof
    events.clear();gate.opened=True;target.verify_publication()
    assert events==['gate','auth'] and target.proof['authHttpTargetBindingVerified']


def test_failed_native_auth_binding_revokes_publication(monkeypatch):
    events=[]
    class Gate:
        def require_open(self):events.append('gate')
        def revoke(self):events.append('revoke')
    def failure(*a,**k):raise ValueError('wrong auth database')
    monkeypatch.setattr(identity,'verify_target_auth',failure)
    target=identity.RecoveredIdentity('private','private','private','owned','supabase_admin',{},publication=Gate())
    with pytest.raises(ValueError,match='wrong auth'):target.verify_publication()
    assert events==['gate','revoke'] and not target.proof


def test_opted_in_constructor_never_allocates_default_raw_auth_relay():
    from contextlib import contextmanager
    from types import SimpleNamespace
    events=[];owner=object();budget=object()
    def raw(*a,**k):raise AssertionError('raw Auth relay was allocated')
    class Gate:
        def bind(self,value):assert value is owner;events.append('bind')
        @contextmanager
        def ingress(self,value,ports,*,budget):
            assert value is owner and ports==(0,0)
            events.append('gated ingress')
            yield (123,456)
    with identity._restored_ingress(SimpleNamespace(internal_loopback_ports=raw),owner,(0,0),budget=budget,publication=Gate()) as ports:
        assert ports==(123,456)
    assert events==['bind','gated ingress']
    with pytest.raises(AttributeError):
        identity._restored_ingress(SimpleNamespace(internal_loopback_ports=raw),owner,(0,0),budget=budget,publication=SimpleNamespace(bind=lambda value:None))


def test_body_read_gate_closure_prevents_auth_mutation_dispatch(monkeypatch):
    from types import SimpleNamespace
    import native_restored_gateway as gateway
    opened=True;requests=[];denied=[]
    class Body:
        def read(self,length):
            nonlocal opened
            opened=False
            return b'x'
    class Upstream:
        def request(self,*a,**k):requests.append(a)
        def close(self):pass
    monkeypatch.setattr(gateway,'allowed',lambda config:opened)
    monkeypatch.setattr(gateway,'HTTPConnection',lambda *a,**k:Upstream())
    handler=object.__new__(gateway.RequestHandler)
    handler.server=SimpleNamespace(config={'auth_host':'owned_auth'},mode='auth')
    handler.headers={'Content-Length':'1'};handler.command='POST';handler.path='/token'
    handler.rfile=Body();handler.connection=SimpleNamespace(settimeout=lambda value:None)
    handler.unavailable=lambda code=503:denied.append(code)
    handler.forward()
    assert denied==[503] and requests==[]


def test_native_control_stream_survives_active_replay_but_expires_when_idle(monkeypatch):
    import socket
    import threading
    from types import SimpleNamespace
    import native_restored_gateway as gateway

    client,request=socket.socketpair();upstream,database=socket.socketpair()
    client.settimeout(2);database.settimeout(2);clock=[0.0]
    monkeypatch.setattr(gateway,'socket',SimpleNamespace(create_connection=lambda *a,**k:upstream))
    monkeypatch.setattr(gateway,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    handler=object.__new__(gateway.ControlHandler)
    handler.request=request;handler.server=SimpleNamespace(config={'database_host':'owned_database'})
    def proxy():
        try:handler.handle()
        finally:request.close()
    def echo():
        try:
            while raw:=database.recv(1024):database.sendall(raw)
        except OSError:pass
        finally:database.close()
    proxy_thread=threading.Thread(target=proxy,daemon=True)
    database_thread=threading.Thread(target=echo,daemon=True)
    database_thread.start();proxy_thread.start()
    try:
        for instant,message in ((0,b'prepare'),(20,b'retire'),(40,b'finalize')):
            clock[0]=instant;client.sendall(message)
            assert client.recv(1024)==message, 'active replay connection was closed at the absolute time limit'
        clock[0]=100
        proxy_thread.join(2)
        assert not proxy_thread.is_alive(), 'idle control connections must still expire'
        assert client.recv(1024)==b''
    finally:
        clock[0]=1000;client.close()
        proxy_thread.join(2);database_thread.join(2)
