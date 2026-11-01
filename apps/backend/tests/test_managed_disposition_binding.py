"""Interop admission with real external journal/owner-prefix files; SQL ports are separate."""
import asyncio
import base64
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from uuid import uuid4, uuid5
from types import SimpleNamespace
from contextlib import asynccontextmanager

import pytest

from talli_backend.adapters.deletion_journal import LocalDeletionJournal, LocalReplayReceipt
from talli_backend.adapters.hosted_recovery_capture import ManagedCapture, digest, encoded
from talli_backend.adapters.managed_disposition_binding import FORMAT, TABLES, ManagedDispositionBinding
from talli_backend.adapters.native_disposition_recovery import native_backup_commitment
from talli_backend.adapters.postgres_document_disposition import native_document_generation
from talli_backend.application.company_disposition import replay_company_dispositions
from talli_backend.modules.company_access.public import (
    CompanyDispositionPlan, DispositionRecord, DispositionSession, LocalDocumentsFacts,
    authorize_local_documents_disposition,
)
from test_deletion_replay import SyntheticDocumentStore, document_body
from test_hosted_backup_recovery import snapshot, repin, private, operator

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def admitted_local_fixture(root):
    original = uuid4(); company = uuid5(original, 'local-documents-disposition-fixture-v1')
    owner, reviewer = uuid4(), uuid4(); rows = {}; objects = {}; records = []; files = []
    for year, action in ((2010, 'erase'), (2025, 'retain')):
        record = uuid4(); version = str(uuid4()); body = document_body(record)
        key = f'{company}/{year}/{record}/document.pdf'
        row = {'id': str(record), 'company_id': str(company), 'income_year': year,
            'storage_key': key, 'byte_length': len(body), 'content_sha256': digest(body)}
        item = {'path': 'stub/stub/company-documents/' + key + '/' + version,
            'bytes': len(body), 'sha256': digest(body)}
        rows[str(record)] = row; objects[str(record)] = {
            'storageKey': key, 'currentVersion': version, 'files': [item]}
        files.append({**item, 'base64': base64.b64encode(body).decode()})
        records.append(DispositionRecord(owner='documents', record_id=record, income_year=year,
            generation=native_document_generation(row, [item]), content_sha256=digest(body), action=action,
            retention_until=NOW + timedelta(days=3650 if action == 'retain' else -1)))
    generations = ((2010, 0), (2025, 0))
    # These hashes deliberately use the existing native codec.
    from talli_backend.adapters.native_disposition_preflight import _sha, _bytes
    generation = _sha({'generations': generations, 'snapshot': rows, 'objects': objects})
    plan = CompanyDispositionPlan(operation_id=uuid4(), company_id=company, choice='delete',
        years=(2010, 2025), generation=generation, records=tuple(records), inventory_sha256='0'*64,
        support_case_id=uuid4())
    plan = plan.model_copy(update={'inventory_sha256': plan.inventory_digest()})
    archive = {'scope': 'synthetic-local-documents-only', 'companyId': str(company),
        'generation': generation, 'documents': rows, 'references': [], 'originals': [], 'files': files}
    exported = private(root / 'held.documents-export.json', _bytes(archive))
    def session(subject, role):
        return DispositionSession(subject=subject, session_id=uuid4(), role=role,
            company_id=company, mfa_at=NOW)
    facts = LocalDocumentsFacts(target_id=original, source_sha256='a'*64,
        source_generations=generations, paid_expires_at=NOW-timedelta(days=400),
        recorded_export_until=NOW-timedelta(days=100), export_until=NOW-timedelta(days=100),
        documents_export_sha256=digest(exported.read_bytes()), owner=session(owner, 'owner'),
        reviewer=session(reviewer, 'reviewer'), review_plan_sha256=digest(plan.model_dump_json().encode()),
        support_case_id=plan.support_case_id)
    return authorize_local_documents_disposition(plan, facts, now=NOW), exported


@pytest.fixture
def handoff(snapshot, tmp_path):
    permit, exported = admitted_local_fixture(tmp_path)
    store = SyntheticDocumentStore(tmp_path / 'native-owner-fixture', plan=permit.plan)
    journal = LocalDeletionJournal.initialize(tmp_path / 'journal.sqlite', customer_root=store.root)
    head = journal.append(permit); target = str(uuid4()); receipt = tmp_path / 'native-replay.json'
    asyncio.run(replay_company_dispositions(journal=journal, target=target,
        receipt=LocalReplayReceipt(receipt), minimum=head, stores={'documents': store}))
    backup = tmp_path / 'original-native-backup'; backup.mkdir(mode=0o700)
    for name in ('database.dump', 'roles.sql', 'storage_vectors.dump', 'objects.tar',
            'object-manifest.json', 'object-attributes.json', 'bindings.private.json'):
        private(backup / name, b'Independent native-restore fixture: ' + name.encode())
    backup_sha = native_backup_commitment(backup)
    login = 'talli_native_disposition_' + 'a'*16
    roles = json.loads((snapshot['directory'] / 'source-roles.private.json').read_bytes())
    roles['roles'].append([login, False, False, False, False, True, False, False, -1, None, None])
    repin(snapshot, 'source-roles.private.json', roles)
    native = private(tmp_path / 'independent-native-binding.json', {'version': 1,
        'target': target, 'sourceTarget': str(permit.facts.target_id),
        'systemIdentifier': '222', 'sourceSystemIdentifier': '111', 'operatorLogin': login,
        'backupSha256': backup_sha, 'journal': asdict(head),
        'authorizationSha256': digest(permit.model_dump_json().encode()),
        'nativeProfile': {'fixture': 'previous independently accepted native restore boundary'}})
    profile = json.loads((snapshot['directory'] / 'source-profile.json').read_bytes())
    profile.pop('projectRef'); profile.update(sourceNativeTarget=target,
        nativeOrigin={'target': target, 'systemIdentifier': '222', 'nativeBindingSha256': digest(native.read_bytes())})
    facts = json.loads((snapshot['directory'] / 'source-tables.private.json').read_bytes())
    for table, count in [('plans', 1), ('targets', 2), ('receipts', 1)]:
        profile['tables'].append(['documents', 'local_native_disposition_' + table])
        facts['documents.local_native_disposition_' + table] = {'rows': count,
            'sha256': digest(('independent native fixture ' + table).encode())}
    repin(snapshot, 'source-profile.json', profile); repin(snapshot, 'source-tables.private.json', facts)
    repin(snapshot, 'native-held-history.private.json', [])
    header = json.loads(snapshot['header'].read_bytes()); header.pop('projectRef')
    header.update(format=FORMAT, sourceNativeTarget=target); private(snapshot['header'], header)
    snapshot['header_sha256'] = digest(snapshot['header'].read_bytes())
    access = json.loads(snapshot['access'].read_bytes()); access.pop('sourceProject')
    access['sourceNativeTarget'] = target; private(snapshot['access'], access)
    snapshot['access_sha256'] = digest(snapshot['access'].read_bytes())
    proof = private(tmp_path / 'independent-handoff-proof.json', {'version': 1, 'profile': FORMAT,
        'nativeTarget': target, 'nativeSystemIdentifier': '222', 'operatorLogin': login,
        'journal': asdict(head), 'nativeBindingSha256': digest(native.read_bytes()),
        'nativeBackupSha256': backup_sha, 'exportSha256': [permit.facts.documents_export_sha256],
        'headerSha256': snapshot['header_sha256'], 'accessSha256': snapshot['access_sha256'],
        'nativeHistoryFiles': 0, 'nativeHistoryBytes': 0,
        'nativeTables': {k: v for k, v in facts.items() if k in TABLES}, 'publicationAuthorized': False})
    args = dict(proof=proof, proof_sha256=digest(proof.read_bytes()), journal=journal.path,
        minimum=asdict(head), receipt=receipt, native_binding=native,
        native_binding_sha256=digest(native.read_bytes()), backup=backup, backup_sha256=backup_sha,
        exports=[exported], customer_root=snapshot['directory'])
    return snapshot, args, journal, store


def test_terminal_native_history_has_explicit_managed_profile(handoff):
    capture, args, _, _ = handoff
    custody = ManagedDispositionBinding(**args)
    result = ManagedCapture.open(**capture, disposition=custody)
    assert result.source_project.startswith('native:')
    assert result.rows['documents.local_native_disposition_receipts']['rows'] == 1
    assert custody.summary()['publicationAuthorized'] is False
    with pytest.raises(ValueError, match='replay_adapter_required'):
        ManagedCapture.open(**capture)


@pytest.mark.parametrize('fault', ['missing_journal', 'tampered_journal', 'stale_minimum',
    'rollback', 'missing_export', 'changed_export', 'backup', 'binding', 'proof', 'head_only_receipt'])
def test_independent_custody_loss_never_admits_native_history(handoff, fault, tmp_path):
    capture, args, journal, store = handoff
    if fault == 'missing_journal': journal.path.unlink()
    elif fault == 'tampered_journal':
        with sqlite3.connect(journal.path) as db: db.execute("update tombstones set body='{}'")
    elif fault == 'stale_minimum':
        other = tmp_path / 'other'; other.mkdir(mode=0o700)
        permit, _ = admitted_local_fixture(other); journal.append(permit)
    elif fault == 'rollback':
        with sqlite3.connect(journal.path) as db: db.execute('delete from tombstones')
    elif fault == 'missing_export': Path(args['exports'][0]).unlink()
    elif fault == 'changed_export': private(Path(args['exports'][0]), b'changed held bytes')
    elif fault == 'backup': private(Path(args['backup']) / 'roles.sql', b'changed original backup')
    elif fault == 'binding': private(Path(args['native_binding']), b'{}')
    elif fault == 'proof': private(Path(args['proof']), b'{}')
    elif fault == 'head_only_receipt':
        with sqlite3.connect(journal.path) as db: db.execute('delete from applied')
    with pytest.raises(Exception):
        ManagedCapture.open(**capture, disposition=ManagedDispositionBinding(**args))


def test_current_cut_is_rechecked_before_restore_and_missing_custody_does_not_block_containment(
        handoff, tmp_path, monkeypatch):
    capture, args, journal, _ = handoff
    custody = ManagedDispositionBinding(**args)
    instance, target = operator({**capture, 'disposition': custody}, tmp_path, monkeypatch)
    result = instance.restore(expected_plan_sha256=instance.plan_sha)
    assert result['phase'] == 'verified_quarantined'
    assert result['verification']['dispositionReplayCurrent'] is True
    journal.path.unlink()
    assert instance.inspect()['dispositionReplayCurrent'] is False
    from talli_backend.adapters.hosted_backup_recovery import HostedBackupRecovery
    reopened = HostedBackupRecovery.from_state(target=target, work=instance.work,
        expected_plan_sha256=instance.plan_sha)
    assert reopened.inspect()['dispositionReplayCurrent'] is False
    assert reopened.contain(expected_plan_sha256=instance.plan_sha)['phase'] == 'contained'
    assert reopened.contain(expected_plan_sha256=instance.plan_sha)['phase'] == 'contained'


@pytest.mark.parametrize('fault', ['journal', 'export', 'backup', 'binding', 'receipt_alias'])
def test_producer_refuses_bad_custody_before_entering_owner_replay(handoff, fault, tmp_path, monkeypatch):
    from talli_backend.adapters import native_managed_handoff as producer
    capture, args, journal, _ = handoff
    custody = ManagedDispositionBinding(**args); events = []
    target = SimpleNamespace(target=custody.body['nativeTarget'], system='222',
        login=custody.body['operatorLogin'], validate=lambda: events.append('identity_read'))
    values = {k: args[k] for k in ('receipt', 'native_binding', 'native_binding_sha256',
        'backup', 'backup_sha256', 'exports')}
    if fault == 'journal':
        other = tmp_path / 'other-source'; other.mkdir(mode=0o700)
        permit, _ = admitted_local_fixture(other); journal.append(permit)
    elif fault == 'export': private(Path(values['exports'][0]), b'changed held bytes')
    elif fault == 'backup': private(Path(values['backup']) / 'roles.sql', b'changed backup')
    elif fault == 'binding': private(Path(values['native_binding']), b'changed binding')
    elif fault == 'receipt_alias': values['receipt'] = values['exports'][0]
    def forbidden(*args):
        events.append('owner_constructed'); raise AssertionError('must refuse before owner replay')
    monkeypatch.setattr(producer, 'PostgresDocumentDisposition', forbidden)
    with pytest.raises(Exception):
        asyncio.run(producer.capture_native_managed_handoff(target=target,
            journal=journal, minimum=custody.minimum, destination=tmp_path / 'new-handoff',
            pg_restore='/must-not-run', **values))
    assert events == ['identity_read']
    assert not (tmp_path / 'new-handoff').exists()


@pytest.mark.parametrize('fault', ['erased', 'unknown', 'payload', 'duplicate', 'current', 'bound'])
def test_retained_history_carrier_cannot_resurrect_or_accept_unheld_bytes(handoff, fault):
    capture, args, _, _ = handoff
    archive = json.loads(Path(args['exports'][0]).read_bytes())
    item = dict(next(f for f in archive['files'] if '/2025/' in f['path']))
    if fault == 'erased': item = dict(next(f for f in archive['files'] if '/2010/' in f['path']))
    if fault == 'unknown': item['path'] += '-unknown'
    if fault == 'payload': item['base64'] = base64.b64encode(b'wrong retained payload').decode()
    if fault == 'current':
        raw = base64.b64decode(item['base64']); name = 'object-' + digest(raw) + '.bin'
        repin(capture, name, raw)
        prefix, version = item['path'].removeprefix('stub/stub/company-documents/').rsplit('/', 1)
        repin(capture, 'object-manifest.private.json', [{'bucket': 'company-documents', 'name': prefix,
            'file': name, 'bytes': len(raw), 'sha256': digest(raw), 'nativeCurrentVersion': version}])
    history = [item] * (257 if fault == 'bound' else 2 if fault == 'duplicate' else 1)
    repin(capture, 'native-held-history.private.json', history)
    # Even with a newly pinned malformed candidate, owner-held facts must win.
    proof = json.loads(Path(args['proof']).read_bytes()); proof['headerSha256'] = capture['header_sha256']
    private(Path(args['proof']), proof); args['proof_sha256'] = digest(Path(args['proof']).read_bytes())
    with pytest.raises(ValueError, match='history_'):
        ManagedCapture.open(**capture, disposition=ManagedDispositionBinding(**args))


def test_journal_advance_between_preflight_and_replay_cannot_expand_the_bound_cut(handoff, tmp_path, monkeypatch):
    from talli_backend.adapters import native_managed_handoff as producer
    capture, args, journal, _ = handoff
    custody = ManagedDispositionBinding(**args); entered = []
    target = SimpleNamespace(target=custody.body['nativeTarget'], system='222',
        login=custody.body['operatorLogin'], validate=lambda: None)
    class ForbiddenOwner:
        @asynccontextmanager
        async def replay_scope(self, commands):
            entered.append('owner'); raise AssertionError('expanded cut reached owner')
            yield
    monkeypatch.setattr(producer, 'PostgresDocumentDisposition', lambda target: ForbiddenOwner())
    original = producer.replay_company_dispositions
    async def append_before_replay(**values):
        other = tmp_path / 'other-admission'; other.mkdir(mode=0o700)
        permit, _ = admitted_local_fixture(other); journal.append(permit)
        return await original(**values)
    monkeypatch.setattr(producer, 'replay_company_dispositions', append_before_replay)
    values = {k: args[k] for k in ('receipt', 'native_binding', 'native_binding_sha256',
        'backup', 'backup_sha256', 'exports')}
    with pytest.raises(ValueError, match='current_cut_required'):
        asyncio.run(producer.capture_native_managed_handoff(target=target, journal=journal,
            minimum=custody.minimum, destination=tmp_path / 'expanded-cut', pg_restore='/must-not-run', **values))
    assert entered == []


@pytest.mark.parametrize('count', [32, 64])
def test_native_sidecar_and_distinct_objects_fit_the_capture_member_bound(handoff, count):
    capture, args, _, _ = handoff
    objects = []
    for index in range(count):
        body = ('distinct bounded object ' + str(index)).encode()
        sha = digest(body); name = 'object-' + sha + '.bin'
        repin(capture, name, body)
        objects.append({'bucket': 'company-documents', 'name': 'document-' + str(index),
            'sha256': sha, 'bytes': len(body), 'file': name, 'nativeCurrentVersion': str(uuid4())})
    repin(capture, 'object-manifest.private.json', objects)
    proof = json.loads(Path(args['proof']).read_bytes())
    proof['headerSha256'] = capture['header_sha256']
    private(Path(args['proof']), proof)
    args['proof_sha256'] = digest(Path(args['proof']).read_bytes())
    result = ManagedCapture.open(**capture, disposition=ManagedDispositionBinding(**args))
    assert len(result.files) == count + 9 and len(result.objects) == count


def test_native_producer_rejects_65_objects_before_storage_access():
    from talli_backend.adapters.native_managed_handoff import _objects
    class Snapshot:
        target = None
        def query(self, sql):
            if 'from storage.buckets' in sql:
                return [['company-documents', False]]
            assert 'from storage.objects' in sql
            return [[str(index), str(uuid4()), 'application/pdf'] for index in range(65)]
    with pytest.raises(ValueError, match='native_object_profile_unsupported'):
        _objects(Snapshot(), {})


def test_original_managed_profile_still_rejects_33_logical_objects(snapshot):
    body = b'one shared object body'; sha = digest(body); name = 'object-' + sha + '.bin'
    repin(snapshot, name, body)
    repin(snapshot, 'object-manifest.private.json', [{'bucket': 'company-documents',
        'name': 'document-' + str(index), 'sha256': sha, 'bytes': len(body), 'file': name}
        for index in range(33)])
    with pytest.raises(ValueError, match='object_inventory_invalid'):
        ManagedCapture.open(**snapshot)


def test_oversized_database_history_path_stops_before_payload_fetch():
    from talli_backend.adapters.hosted_backup_recovery import HostedBackupRecovery
    from test_hosted_backup_recovery import Cursor
    class DB:
        def execute(self, sql):
            assert sql.startswith('select count(*),coalesce(sum(octet_length(payload))')
            assert 'max(octet_length(path))' in sql
            return Cursor([(1, 1, 1, 2049)])
    recovery = object.__new__(HostedBackupRecovery)
    recovery._private_control_current = lambda db: True
    assert not recovery._history_current(DB(), {'nativeHistorySha256': 'a'*64})
