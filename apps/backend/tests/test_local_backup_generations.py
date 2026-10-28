"""Real file/crypto publication tests; native DB/object capture is rehearsed separately."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import subprocess
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from talli_backend.adapters.deletion_journal import LocalDeletionJournal
from talli_backend.adapters.local_backup_generations import LocalBackupGenerations

NAMES=('database.dump','roles.sql','storage_vectors.dump','objects.tar','object-manifest.json','object-attributes.json','bindings.private.json')


def capture(path):
    path.mkdir(mode=0o700)
    for name in NAMES:
        (path/name).write_bytes(b'private synthetic native input: '+name.encode())
        (path/name).chmod(0o600)


@pytest.fixture(scope='module')
def keys():
    private=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    return (private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()),
            private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))


@pytest.fixture
def repository(tmp_path,keys):
    private,public=keys;key=tmp_path/'separate-key.pem';key.write_bytes(private);key.chmod(0o600)
    journal=LocalDeletionJournal.initialize(tmp_path/'journal.sqlite',customer_root=tmp_path/'customer')
    (tmp_path/'obligations').mkdir(mode=0o700)
    head=journal.read()[0];clock=[datetime(2026,10,28,tzinfo=timezone.utc)]
    args=dict(root=tmp_path/'encrypted',control=tmp_path/'independent-control',scratch=tmp_path/'scratch',journal=journal,obligations=tmp_path/'obligations',public_key=public,clock=lambda:clock[0])
    return LocalBackupGenerations.initialize(**args),head,clock,key,args


def test_complete_encrypted_generation_roundtrip_and_source_age(repository,tmp_path):
    repo,head,clock,key,_=repository
    def slow_capture(path):
        capture(path);clock[0]+=timedelta(minutes=10)
    identifier=repo.create(capture=slow_capture,minimum=head)
    report=repo.readiness(minimum=head)
    assert report['ready'] and report['usableAgeSeconds']==600
    assert b'private synthetic native input' not in (repo.root/'generations'/identifier/'payload.enc').read_bytes()
    assert not any(repo.scratch.iterdir())
    receipt=repo.restore(generation=identifier,destination=tmp_path/'restored',recovery_key=key,minimum=head)
    assert receipt['capturedJournal']==receipt['requiredReplayHead'] and not receipt['publicationAuthorized']
    for name in NAMES:assert (tmp_path/'restored'/name).read_bytes()==b'private synthetic native input: '+name.encode()
    clock[0]+=timedelta(hours=1)
    assert repo.readiness(minimum=head)['reason']=='backup_stale'


def test_failed_capture_preserves_last_usable_and_emits_failure(repository):
    repo,head,clock,_,_=repository;identifier=repo.create(capture=capture,minimum=head)
    def broken(path):
        path.mkdir();(path/'partial.dump').write_bytes(b'incomplete');raise RuntimeError('private exception must not enter sink')
    with pytest.raises(ValueError,match='backup_generation_failed'):repo.create(capture=broken,minimum=head)
    report=json.loads((repo.control/'readiness.json').read_bytes())
    assert not report['ready'] and report['reason']=='last_generation_failed' and report['usableGeneration']==identifier
    assert 'private exception' not in json.dumps(report) and report['usableAgeSeconds']==0
    clock[0]+=timedelta(hours=2)
    assert repo.readiness(minimum=head)['usableAgeSeconds']==7200
    assert not any(repo.scratch.iterdir())


def test_expiry_physically_removes_old_owned_generation_but_not_journal(repository,tmp_path):
    repo,head,clock,key,_=repository;old=repo.create(capture=capture,minimum=head)
    original_journal=repo.journal.path.read_bytes();clock[0]+=timedelta(days=8)
    kept=repo.create(capture=capture,minimum=head)
    result=repo.rotate(minimum=head)
    assert result['removed']==[old] and result['protectedGeneration']==kept and result['readiness']['ready']
    assert not (repo.root/'generations'/old).exists() and (repo.root/'generations'/kept/'payload.enc').is_file()
    assert repo.journal.path.read_bytes()==original_journal
    repo.restore(generation=kept,destination=tmp_path/'restored',recovery_key=key,minimum=head)
    with pytest.raises(ValueError,match='unavailable'):repo.restore(generation=old,destination=tmp_path/'expired',recovery_key=key,minimum=head)


def test_last_expired_backup_is_protected_and_readiness_is_stale(repository):
    repo,head,clock,_,_=repository;identifier=repo.create(capture=capture,minimum=head);clock[0]+=timedelta(days=8)
    result=repo.rotate(minimum=head)
    assert result['removed']==[] and result['protectedGeneration']==identifier and result['retentionOverdue']
    assert not result['readiness']['ready'] and result['readiness']['reason']=='backup_stale'


def test_corrupt_cipher_and_wrong_key_cannot_restore_or_refresh_age(repository,tmp_path,keys):
    repo,head,clock,key,_=repository;good=repo.create(capture=capture,minimum=head)
    clock[0]+=timedelta(minutes=10);bad=repo.create(capture=capture,minimum=head)
    cipher=repo.root/'generations'/bad/'payload.enc';raw=cipher.read_bytes();cipher.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
    report=repo.readiness(minimum=head)
    assert not report['ready'] and report['usableGeneration']==good and report['usableAgeSeconds']==600
    assert report['invalidGenerations']==[bad]
    with pytest.raises(ValueError):repo.restore(generation=bad,destination=tmp_path/'corrupt',recovery_key=key,minimum=head)
    wrong=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    other=tmp_path/'wrong.pem';other.write_bytes(wrong.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));other.chmod(0o600)
    with pytest.raises(ValueError,match='key_changed'):repo.restore(generation=good,destination=tmp_path/'wrong',recovery_key=other,minimum=head)
    assert not (tmp_path/'corrupt').exists() and not (tmp_path/'wrong').exists()


def test_real_process_interruption_after_rename_never_becomes_complete(repository,tmp_path,keys):
    repo,head,clock,key,args=repository;good=repo.create(capture=capture,minimum=head)
    public=tmp_path/'public.pem';public.write_bytes(keys[1])
    code='''
from pathlib import Path
from datetime import datetime,timezone
import os,sys
from talli_backend.adapters.deletion_journal import LocalDeletionJournal
from talli_backend.adapters.local_backup_generations import LocalBackupGenerations
p=Path(sys.argv[1]);j=LocalDeletionJournal(p/'journal.sqlite',customer_root=p/'customer',stream=sys.argv[2])
r=LocalBackupGenerations(root=p/'encrypted',control=p/'independent-control',scratch=p/'scratch',journal=j,obligations=p/'obligations',public_key=(p/'public.pem').read_bytes(),clock=lambda:datetime(2026,10,28,tzinfo=timezone.utc))
r._commit=lambda *a:os._exit(73)
def capture(d):
 d.mkdir(mode=0o700)
 for name in ('database.dump','roles.sql','storage_vectors.dump','objects.tar','object-manifest.json','object-attributes.json','bindings.private.json'):(d/name).write_bytes(b'private synthetic input')
r.create(capture=capture,minimum=j.read()[0])
'''
    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
    completed=subprocess.run([sys.executable,'-c',code,str(tmp_path),head.stream],env=env,capture_output=True,timeout=20)
    assert completed.returncode==73
    fresh=LocalBackupGenerations(**args);report=fresh.readiness(minimum=head)
    assert report['reason']=='creation_incomplete' and report['usableGeneration']==good and not report['ready']
    assert len(list((repo.root/'generations').iterdir()))==2
    fresh.rotate(minimum=head)
    assert len(list((repo.root/'generations').iterdir()))==1 and not any(repo.scratch.iterdir())
    fresh.restore(generation=good,destination=tmp_path/'restored',recovery_key=key,minimum=head)


def test_interrupted_expiry_is_not_restorable_and_resumes(repository,tmp_path):
    repo,head,clock,key,_=repository;old=repo.create(capture=capture,minimum=head)
    clock[0]+=timedelta(days=8);kept=repo.create(capture=capture,minimum=head)
    original=repo._remove_owned;failed=[]
    def interrupted(parent,identifier):
        if parent==repo.root/'generations' and identifier==old and not failed:
            (parent/identifier/'payload.enc').unlink();failed.append(True);raise OSError('injected after real unlink')
        return original(parent,identifier)
    repo._remove_owned=interrupted
    with pytest.raises(OSError):repo.rotate(minimum=head)
    assert not repo.readiness(minimum=head)['ready']
    assert repo.readiness(minimum=head)['usableGeneration']==kept
    with pytest.raises(ValueError,match='unavailable'):repo.restore(generation=old,destination=tmp_path/'partial',recovery_key=key,minimum=head)
    repo._remove_owned=original;result=repo.rotate(minimum=head)
    assert result['removed']==[old] and result['readiness']['ready']
    assert not (repo.root/'generations'/old).exists()
    repo.restore(generation=kept,destination=tmp_path/'kept',recovery_key=key,minimum=head)


def test_clock_regression_refuses_rotation(repository):
    repo,head,clock,_,_=repository;first=repo.create(capture=capture,minimum=head)
    clock[0]+=timedelta(days=8);second=repo.create(capture=capture,minimum=head)
    clock[0]-=timedelta(hours=1)
    with pytest.raises(ValueError,match='clock_regressed'):repo.rotate(minimum=head)
    assert {p.name for p in (repo.root/'generations').iterdir()}=={first,second}
    assert not repo.readiness(minimum=head)['ready']


def test_publication_budget_cannot_be_hidden_by_fast_source_capture(repository,monkeypatch):
    repo,head,clock,_,_=repository;good=repo.create(capture=capture,minimum=head)
    import talli_backend.adapters.local_backup_generations as module
    original=module._extract
    def delayed_verify(*args):
        value=original(*args);clock[0]+=timedelta(minutes=16);return value
    monkeypatch.setattr(module,'_extract',delayed_verify)
    with pytest.raises(ValueError,match='backup_generation_failed'):repo.create(capture=capture,minimum=head)
    report=repo.readiness(minimum=head)
    assert report['usableGeneration']==good and report['usableAgeSeconds']==960 and not report['ready']
