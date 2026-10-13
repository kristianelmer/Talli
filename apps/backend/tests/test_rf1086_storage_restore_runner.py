"""Object restoration rejects foreign sources and cleans only its own resources."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import sys

import pytest
from talli_backend.modules.documents.public import (
    DocumentId, DocumentRecord, DocumentStatus, RetainedDocumentOriginal,
    RetainedDocumentOriginalReceipt, RetainedDocumentOriginalSnapshot,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
import rf1086_storage_restore as storage

SOURCE = {
    'Id': 'a' * 64, 'Name': '/supabase_storage_tallig9931', 'Image': 'sha256:' + 'b' * 64,
    'State': {'Running': True}, 'NetworkSettings': {'Networks': {'supabase_network_tallig9931': {}}},
    'Mounts': [{'Destination': '/mnt', 'Type': 'volume', 'Name': 'owned-source'}],
    'Config': {'Env': ['STORAGE_BACKEND=file', 'FILE_STORAGE_BACKEND_PATH=/mnt',
                      'DATABASE_URL=postgresql://storage:local@supabase_db_tallig9931:5432/postgres',
                      'VECTOR_DATABASE_URL=postgresql://storage:local@supabase_db_tallig9931:5432/postgres',
                      'SERVICE_KEY=local']},
}
ENV = dict(item.split('=', 1) for item in SOURCE['Config']['Env'])
CLONE = 'postgresql://postgres:local@127.0.0.1:55001/rf193_restore_' + 'c' * 32


def retained_generations():
    timestamp = datetime(2026, 9, 30, tzinfo=timezone.utc)
    content = b'%PDF-1.7\noriginal'
    document = DocumentRecord(DocumentId('00000000-0000-4000-8000-000000000001'),
        CompanyId('00000000-0000-4000-8000-000000000002'), IncomeYear(2025),
        'accounting_document', 'Original.pdf', 'workspace', DocumentStatus.ATTACHED, 5,
        'company/2025/document/original.pdf', 'application/pdf', len(content), sha256(content).hexdigest(),
        ActorId(ActorKind.USER, UserId('00000000-0000-4000-8000-000000000003')), timestamp, None, None)
    snapshots = []
    for index, record in enumerate((document, replace(document, name='Renamed.pdf'))):
        receipt = RetainedDocumentOriginalReceipt(f'00000000-0000-4000-8000-{index + 10:012d}', record.document_id, record.company_id,
            record.income_year, storage.document_metadata_sha256(record), record.content_sha256,
            len(content), timestamp + timedelta(seconds=index))
        snapshots.append(RetainedDocumentOriginalSnapshot(record, RetainedDocumentOriginal(receipt, content)))
    return snapshots


def test_distinct_generations_share_one_ordinary_object_and_metadata_selects_even_older_version():
    first, second = retained_generations()
    grouped = storage.ordinary_originals([second, first, deepcopy(first)])
    assert grouped == [(second.original, first.original)]
    assert storage.current_original(first.document, grouped[0]) == first.original
    assert storage.current_original(second.document, grouped[0]) == second.original


def test_same_metadata_identity_cannot_silently_replace_retained_bytes():
    first, _ = retained_generations()
    changed = replace(first, original=replace(first.original, content=b'changed'))
    with pytest.raises(ValueError, match='conflicting originals'):
        storage.ordinary_originals([first, changed])


@pytest.mark.parametrize('fault', ['missing', 'ambiguous', 'foreign_document'])
def test_current_object_never_falls_back_to_latest_or_wrong_retained_generation(fault):
    first, second = retained_generations()
    document, originals = first.document, [second.original]
    if fault == 'ambiguous': originals = [first.original, first.original]
    if fault == 'foreign_document':
        originals = [replace(first.original, receipt=replace(first.original.receipt,
            document_id=DocumentId('00000000-0000-4000-8000-000000000004')))]
    with pytest.raises(ValueError, match='no unique retained generation'):
        storage.current_original(document, originals)


@pytest.mark.parametrize('fault', [None, 'not_running', 'network', 'image', 'mount', 'remote_db',
                                   'source_db', 'query_override', 'backend', 'remote_auth', 'missing_key', 'gateway_port'])
def test_source_must_be_the_exact_owned_file_store(tmp_path, monkeypatch, fault):
    (tmp_path / 'supabase').mkdir()
    (tmp_path / 'supabase/config.toml').write_text('project_id="tallig9931"\n[api]\nport=55000\n')
    monkeypatch.setenv('SUPABASE_URL', 'http://127.0.0.1:55000')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'local')
    source = deepcopy(SOURCE)
    if fault == 'not_running': source['State']['Running'] = False
    if fault == 'network': source['NetworkSettings']['Networks'] = {'other': {}}
    if fault == 'image': source['Image'] = 'mutable-tag'
    if fault == 'mount': source['Mounts'][0]['Type'] = 'bind'
    replacements = {'remote_db': ('DATABASE_URL', 'postgresql://storage:local@remote:5432/postgres'),
                    'source_db': ('VECTOR_DATABASE_URL', 'postgresql://storage:local@supabase_db_tallig9931:5432/other'),
                    'query_override': ('DATABASE_URL', ENV['DATABASE_URL'] + '?host=remote'),
                    'backend': ('STORAGE_BACKEND', 's3')}
    if fault in replacements:
        key, value = replacements[fault]
        source['Config']['Env'] = [item for item in source['Config']['Env'] if not item.startswith(key + '=')] + [key + '=' + value]
    if fault == 'remote_auth': monkeypatch.setenv('SUPABASE_URL', 'https://remote.invalid')
    if fault == 'missing_key': monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', '')
    gateway = {'Name': '/supabase_kong_tallig9931', 'State': {'Running': True},
               'NetworkSettings': {'Networks': {'supabase_network_tallig9931': {}},
                                   'Ports': {'8000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '55001' if fault == 'gateway_port' else '55000'}]}}}
    verified = []
    boundary = SimpleNamespace(owned_source=lambda *_: ('db-id', 'postgres'),
        verify_source_session=lambda *args: verified.append(args),
        inspect_container=lambda name: source if name.startswith('supabase_storage_') else gateway if name.startswith('supabase_kong_') else SOURCE)
    if fault:
        with pytest.raises(ValueError): storage.storage_source(tmp_path, 'owned-url', boundary)
    else:
        actual, env, network = storage.storage_source(tmp_path, 'owned-url', boundary)
        assert actual is source and env == ENV and network == 'supabase_network_tallig9931'
    assert verified == [('owned-url', 'db-id')]


def test_clone_configuration_retargets_both_databases_and_excludes_unneeded_integrations():
    env = ENV | {'JWT_JWKS': '{}', 'IMGPROXY_URL': 'https://external.invalid', 'LOG_LEVEL': 'debug',
                 'DB_MIGRATIONS_FREEZE_AT': 'fixture-version', 'VECTOR_STORE_MIGRATIONS_ENABLED': 'false'}
    actual = storage.clone_environment(env, CLONE)
    for key in ('DATABASE_URL', 'VECTOR_DATABASE_URL'):
        assert actual[key].endswith('/rf193_restore_' + 'c' * 32)
        assert 'supabase_db_tallig9931:5432' in actual[key]
    assert actual['LOG_LEVEL'] == 'fatal' and 'IMGPROXY_URL' not in actual
    assert actual['STORAGE_BACKEND'] == 'file'
    assert actual['DB_MIGRATIONS_FREEZE_AT'] == 'fixture-version'
    assert actual['VECTOR_STORE_MIGRATIONS_ENABLED'] == 'false'
    with pytest.raises(ValueError): storage.clone_environment(env, CLONE.replace('rf193_restore_', 'existing_'))
    with pytest.raises(ValueError): storage.clone_environment(env | {'SERVICE_KEY': 'a\nb'}, CLONE)


class DockerModel:
    """Independent daemon state: CLI failure may follow a completed create."""
    def __init__(self):
        self.rows = {}; self.calls = []; self.next_id = 1; self.owner = None
        self.fail = None; self.error = RuntimeError('synthetic lost response')
        self.unknown_create = False; self.keep_removed = False; self.alter = None
        self.on_remove = None
        self.capture_stdout = b'[]'

    def kind(self, name):
        if name.startswith('rf193_objects_'): return 'volume'
        for kind in ('tar', 'attributes', 'capture'):
            if name.startswith('rf193_storage_' + kind + '_'): return kind
        return 'service'

    def run(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        resource, action = args[1:3]
        if resource in ('volume', 'container') and action == 'ls':
            selector = args[-1].split('=', 1)
            values = [row['Name'].lstrip('/') for row in self.rows.values()
                if (resource == 'volume') == ('Id' not in row)
                and (selector[1] in row['Name'] if selector[0] == 'name' else row.get('Id') == selector[1])]
            return SimpleNamespace(stdout=b''.join(json.dumps(x).encode()+b'\n' for x in values))
        if resource in ('volume', 'container') and action == 'inspect':
            if args[-1] == SOURCE['Id']: value = deepcopy(SOURCE)
            else: value = deepcopy(self.rows[args[-1]])
            if self.alter: value = self.alter(value)
            return SimpleNamespace(stdout=json.dumps([value]).encode())
        if resource == 'volume' and action == 'create' or resource == 'create':
            name = args[-1] if resource == 'volume' else args[args.index('--name')+1]
            kind = self.kind(name)
            record = json.loads(self.owner.record.read_bytes())
            assert kind in record['attempted'] and name == record['names'][kind]
            assert self.owner.record.stat().st_mode & 0o777 == 0o600
            label = args[args.index('--label')+1].split('=', 1)
            value = {'Name': name, 'Labels': dict([label])}
            if resource != 'volume':
                identity = f'{self.next_id:064x}'; self.next_id += 1
                mode = args[args.index('--network')+1]
                value = {'Name': '/'+name, 'Id': identity, 'Image': SOURCE['Image'],
                    'Config': {'Labels': dict([label])}, 'State': {'Running': False, 'Status': 'created', 'ExitCode': 0},
                    'HostConfig': {'NetworkMode': mode},
                    'NetworkSettings': {'Networks': {mode: {}}, 'Ports': {'5000/tcp': [{'HostIp':'127.0.0.1','HostPort':'55123'}]}},
                    'Mounts': [{'Type':'volume','Name':self.owner.names['volume'],'Destination':'/mnt','RW':True}]}
                if kind == 'service':
                    path = Path(args[args.index('--env-file')+1])
                    assert path.stat().st_mode & 0o777 == 0o600
                    assert '/rf193_restore_' in path.read_text()
            if not (self.unknown_create and self.fail == kind): self.rows[name] = value
            if self.fail == kind:
                self.fail = None
                raise self.error
            return SimpleNamespace(stdout=(value.get('Id', name)+'\n').encode())
        if resource == 'start':
            row = next(v for v in self.rows.values() if v.get('Id') == args[-1])
            kind = self.kind(row['Name'].lstrip('/'))
            if kind == 'tar': assert kwargs['stdin'].read() == b'synthetic-archive'
            if kind == 'attributes': assert kwargs['input'] == b'[]'
            row['State'] = {'Running': kind == 'service', 'Status': 'running' if kind == 'service' else 'exited', 'ExitCode': 0}
            if self.fail == 'start_'+kind:
                self.fail = None
                raise self.error
            return SimpleNamespace(stdout=self.capture_stdout if kind == 'capture' else b'')
        if resource in ('volume', 'container') and action == 'rm':
            if self.on_remove: self.on_remove()
            name = args[-1] if resource == 'volume' else next(k for k,v in self.rows.items() if v.get('Id') == args[-1])
            if not self.keep_removed: self.rows.pop(name)
            return SimpleNamespace(stdout=b'')
        raise AssertionError('Unexpected model command: '+repr(args[:3]))


@pytest.fixture
def docker_model(tmp_path, monkeypatch):
    import rf1086_storage_restore_owner as ownership
    import rf1086_restore_control as control
    model = DockerModel(); original = ownership.StorageOwner; mkdtemp = ownership.tempfile.mkdtemp
    class Owner(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs); model.owner = self
    monkeypatch.setattr(ownership, 'StorageOwner', Owner)
    monkeypatch.setattr(ownership.tempfile, 'mkdtemp', lambda **kwargs: mkdtemp(dir=tmp_path, **kwargs))
    monkeypatch.setattr(storage, 'checked', model.run)
    def bounded(budget, args, **kwargs):
        assert kwargs['end'] <= budget.end
        budget.remaining(end=kwargs['end'])
        return model.run(args, **kwargs)
    monkeypatch.setattr(ownership, 'io_checked', bounded)
    def snapshot(container, stream):
        assert container == SOURCE['Id']
        stream.write(b'synthetic-archive'); stream.seek(0)
        return 'same'
    monkeypatch.setattr(storage, 'snapshot', snapshot)
    monkeypatch.setattr(storage, 'attributes', lambda _: b'[]')
    @contextmanager
    def gateway(port):
        assert port == 55123
        yield 'http://127.0.0.1:55124'
    monkeypatch.setattr(storage, 'storage_gateway', gateway)
    @contextmanager
    def forwarding(ports): yield
    monkeypatch.setattr(storage, 'forwarded_ports', forwarding)
    class Client:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def get(self, *_, **__): return SimpleNamespace(status_code=200)
    monkeypatch.setattr(storage.httpx, 'Client', Client)
    monkeypatch.setattr(storage.subprocess, 'Popen', lambda *_, **__: pytest.fail('No resource process allowed'))
    model.budget = control.RecoveryBudget(control.time.monotonic())
    return model


def restored(model, *, budget=True):
    return storage.restored_storage(SOURCE, ENV, 'supabase_network_tallig9931', CLONE, None,
        budget=model.budget if budget else None)


def test_archive_file_acquisition_failure_precedes_owner_record(docker_model, monkeypatch):
    primary = OSError('synthetic file failure')
    def fail(): raise primary
    monkeypatch.setattr(storage.tempfile, 'TemporaryFile', fail)
    with pytest.raises(OSError) as caught:
        with restored(docker_model): pytest.fail('business')
    assert caught.value is primary and docker_model.owner is None and not docker_model.calls


@pytest.mark.parametrize('budgeted', [False, True])
def test_all_five_resources_registered_before_create_and_confirmed_removed(docker_model, budgeted):
    model = docker_model; end = model.budget.end
    with restored(model, budget=budgeted):
        assert set(model.rows) == {model.owner.names['volume'], model.owner.names['service']}
    assert not model.rows and not model.owner.directory.exists()
    assert model.owner.attempted == ['volume','tar','attributes','capture','service']
    assert model.budget.phase == 'construction' and model.budget.end == end
    commands = [args for args,_ in model.calls]
    assert not any(args[1] == 'run' or '--rm' in args for args in commands)
    creates = [args for args in commands if args[1] == 'create']
    assert len(creates) == 4 and len({args[args.index('--name')+1] for args in creates}) == 4
    assert all('--label' in args and SOURCE['Image'] in args for args in creates)
    assert all('owned-source:/mnt' not in args for args in commands)
    assert not any(args[1] in ('create','rm','start') and SOURCE['Id'] in args for args in commands)
    assert sum(args[1:3] == ['container','rm'] for args in commands) == 4
    assert sum(args[1:3] == ['volume','rm'] for args in commands) == 1


@pytest.mark.parametrize('kind', ['volume','tar','attributes','capture','service'])
@pytest.mark.parametrize('cancelled', [False, True])
def test_lost_create_response_reconciles_daemon_resource_and_preserves_primary(docker_model, kind, cancelled):
    model = docker_model; model.fail = kind
    primary = KeyboardInterrupt('synthetic') if cancelled else RuntimeError('lost response')
    model.error = primary
    with pytest.raises(type(primary)) as caught:
        with restored(model): pytest.fail('failed create reached business')
    assert caught.value is primary
    assert not model.rows and not model.owner.directory.exists()


@pytest.mark.parametrize('kind', ['tar','attributes','capture','service'])
def test_interrupted_start_removes_registered_helper_even_if_still_running(docker_model, kind):
    model = docker_model; model.fail = 'start_'+kind; primary = KeyboardInterrupt('synthetic')
    model.error = primary
    with pytest.raises(KeyboardInterrupt) as caught:
        with restored(model): pytest.fail('failed start reached business')
    assert caught.value is primary and not model.rows and not model.owner.directory.exists()


@pytest.mark.parametrize('change', ['label','image','mount','id','name'])
def test_foreign_or_replaced_service_is_not_removed(docker_model, change):
    model = docker_model; primary = RuntimeError('business failure')
    with pytest.raises(RuntimeError) as caught:
        with restored(model):
            row = model.rows[model.owner.names['service']]
            if change == 'label': row['Config']['Labels'] = {}
            if change == 'image': row['Image'] = 'sha256:'+'e'*64
            if change == 'mount': row['Mounts'][0]['Name'] = 'owned-source'
            if change == 'id': row['Id'] = 'f'*64
            if change == 'name':
                model.rows['renamed'] = model.rows.pop(model.owner.names['service']); row['Name'] = '/renamed'
            raise primary
    assert caught.value is primary and model.owner.record.exists()
    assert not model.owner.configuration.exists()
    assert model.owner.uncertain and model.budget.context.owner.uncertain
    assert not any(args[1:3] == ['container','rm'] and args[-1] in ('f'*64, model.owner.identities['service'])
        for args,_ in model.calls)
    assert 'SERVICE_KEY' not in model.owner.record.read_text()


def test_unknown_unobserved_acquisition_retains_record_even_when_name_absent(docker_model):
    model = docker_model; model.fail = 'volume'; model.unknown_create = True
    with pytest.raises(RuntimeError) as caught:
        with restored(model): pytest.fail('business')
    assert caught.value is model.error and model.owner.record.exists() and not model.rows
    assert model.budget.context.owner.uncertain


def test_removal_requires_confirmed_absence(docker_model):
    model = docker_model
    with pytest.raises(ValueError, match='removal_unproved'):
        with restored(model): model.keep_removed = True
    assert model.owner.record.exists() and model.owner.uncertain
    assert not model.owner.configuration.exists()


def test_source_identity_change_refuses_before_first_target_attempt(docker_model):
    model = docker_model
    def alter(value):
        if value.get('Id') == SOURCE['Id']: value['Image'] = 'sha256:'+'c'*64
        return value
    model.alter = alter
    with pytest.raises(ValueError, match='source_changed'):
        with restored(model): pytest.fail('business')
    assert not model.rows and model.owner.attempted == [] and not model.owner.directory.exists()


def test_foreign_volume_never_reaches_a_helper_or_removal(docker_model):
    model = docker_model
    def alter(value):
        if 'Id' not in value: value['Labels'] = {}
        return value
    model.alter = alter
    with pytest.raises(ValueError, match='ownership_mismatch'):
        with restored(model): pytest.fail('business')
    assert model.owner.attempted == ['volume'] and model.owner.record.exists()
    assert not any(args[1] == 'create' or args[1:3] == ['volume','rm'] for args,_ in model.calls)


@pytest.mark.parametrize('fault', ['attributes', 'source_changed'])
def test_existing_attribute_and_readonly_source_postchecks_still_reject(docker_model, monkeypatch, fault):
    model = docker_model
    if fault == 'attributes': model.capture_stdout = b'changed'
    with pytest.raises(ValueError, match='attributes differ|changed source'):
        with restored(model):
            assert fault == 'source_changed'
            monkeypatch.setattr(storage, 'snapshot', lambda *_: 'changed')
    assert not model.rows and not model.owner.directory.exists()


def test_expired_same_budget_cannot_start_cleanup_commands_or_hide_primary(docker_model):
    import time
    model = docker_model; primary = KeyboardInterrupt('synthetic')
    with pytest.raises(KeyboardInterrupt) as caught:
        with restored(model):
            count = len(model.calls)
            model.budget.end = model.owner.end = time.monotonic()-1
            raise primary
    assert caught.value is primary and len(model.calls) == count
    assert model.owner.record.exists() and not model.owner.configuration.exists()
    assert model.budget.phase == 'construction' and model.budget.context.owner.uncertain


@pytest.mark.parametrize('uncertainty', ['acquiring','process','uncertain'])
def test_unresolved_child_keeps_record_even_after_all_daemon_resources_removed(docker_model, uncertainty):
    model = docker_model; primary = RuntimeError('synthetic')
    with pytest.raises(RuntimeError) as caught:
        with restored(model):
            owner = model.budget.context.owner
            if uncertainty == 'acquiring': owner.slots[0].acquiring = True
            elif uncertainty == 'process': owner.slots[0].process = object()
            else: owner.uncertain = True; owner.primary = primary
            raise primary
    assert caught.value is primary and not model.rows and model.owner.record.exists()
    assert not model.owner.configuration.exists()


def test_repeat_termination_is_deferred_through_all_resource_removals(docker_model):
    import signal
    model = docker_model; primary = RuntimeError('first failure')
    seen = []
    def cancel_once():
        if not seen:
            seen.append(True); signal.raise_signal(signal.SIGTERM)
    with pytest.raises(RuntimeError) as caught:
        with restored(model):
            model.on_remove = cancel_once
            raise primary
    assert caught.value is primary and seen and model.budget.context.owner.cancelled
    assert not model.rows and not model.owner.directory.exists()


@pytest.mark.parametrize('budgeted', [False, True])
def test_documents_factory_receives_explicit_deadline_connector_only_when_enabled(monkeypatch, budgeted):
    import asyncio
    import rf1086_restore_control as control
    sentinel = object(); captured = []; selected = control.RecoveryBudget(control.time.monotonic()) if budgeted else None
    for key in ('SUPABASE_URL', 'SUPABASE_ANON_KEY', 'SUPABASE_SERVICE_ROLE_KEY'):
        monkeypatch.setenv(key, 'synthetic-only')
    def connector(budget):
        assert budget is selected
        return sentinel
    def factory(configuration, **kwargs):
        captured.append(kwargs)
        raise RuntimeError('stop before any actual I/O')
    monkeypatch.setattr(control, 'connection_factory', connector)
    monkeypatch.setattr(storage, 'SupabaseDocumentsAdapter', factory)
    with pytest.raises(RuntimeError, match='stop before'):
        asyncio.run(storage.verify_objects(CLONE, CLONE, 'http://local.invalid', [], budget=selected))
    assert captured == ([{'connect': sentinel}] if budgeted else [{}])


@pytest.mark.parametrize('timeout', [False, True])
def test_command_failures_do_not_disclose_configuration_or_signed_urls(monkeypatch, timeout):
    private = 'private-config-and-signed-object-url'
    def run(args, **kwargs):
        assert kwargs['timeout'] == 30
        if timeout:
            raise subprocess.TimeoutExpired(args, 30, stderr=private)
        return SimpleNamespace(returncode=1, stderr=private)
    monkeypatch.setattr(storage.subprocess, 'run', run)
    with pytest.raises(RuntimeError) as error:
        storage.checked(['docker', 'create', private])
    assert private not in str(error.value)
