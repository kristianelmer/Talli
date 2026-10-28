"""Bounded local encrypted native generations; no scheduler or remote service.

The approved capture callback owns native snapshot consistency. This repository
owns encrypted publication, integrity, local freshness and expiry. Its catalog,
recovery key and deletion journal are outside all customer snapshots. OS custody
is trusted; neither this catalog nor the journal authenticates a hostile owner.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import base64
import fcntl
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tarfile
import time
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from talli_backend.adapters.native_disposition_recovery import NativeDispositionRecovery, native_backup_commitment
from talli_backend.application.company_disposition import JournalHead

MAX_BUNDLE = 256 * 1024**2
MAX_CIPHER = MAX_BUNDLE + 1024**2
MAX_GENERATIONS = 512
POLICY = {'intervalSeconds':1800,'completionBudgetSeconds':900,'maxUsableAgeSeconds':3600,'retentionSeconds':7*86400}


def _encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


def _sync(path):
    fd=os.open(path,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def _read(path,limit,*,private=False):
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb') as source:
        info=os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>limit
                or private and (info.st_uid!=os.getuid() or info.st_mode&0o077)):
            raise ValueError('backup_file_unavailable')
        raw=source.read(limit+1)
    if len(raw)>limit:raise ValueError('backup_file_unavailable')
    return raw


def _write(path,raw):
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as out:
        out.write(raw);out.flush();os.fsync(out.fileno())


def _head(value):return JournalHead(value['stream'],value['sequence'],value['sha256'])
def _cut(value):return {'stream':value.stream,'sequence':value.sequence,'sha256':value.sha256}


def _bundle(directory):
    commitment=native_backup_commitment(directory);files={};raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w') as archive:
        for path in sorted(directory.iterdir()):
            if len(path.name)>100 or not all(c.isalnum() or c in '.-_' for c in path.name):
                raise ValueError('backup_filename_unavailable')
            content=_read(path,MAX_BUNDLE)
            files[path.name]={'bytes':len(content),'sha256':sha256(content).hexdigest()}
            item=tarfile.TarInfo(path.name);item.size=len(content);item.mode=0o600
            archive.addfile(item,io.BytesIO(content))
    if sum(f['bytes'] for f in files.values())>MAX_BUNDLE or len(raw.getbuffer())>MAX_CIPHER-16:
        raise ValueError('backup_bundle_bound')
    if sha256(_encoded(files)).hexdigest()!=commitment:
        raise ValueError('backup_bundle_changed')
    return raw.getvalue(),files,commitment


def _extract(raw,directory,files):
    if not 7<=len(files)<=32:raise ValueError('backup_bundle_bound')
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
        members=archive.getmembers()
        if len(members)!=len(files) or {m.name for m in members}!=set(files):
            raise ValueError('backup_bundle_changed')
        for item in members:
            if (not item.isfile() or item.name!=Path(item.name).name or item.size<0
                    or item.size!=files[item.name]['bytes']):raise ValueError('backup_bundle_changed')
            content=archive.extractfile(item).read(MAX_BUNDLE+1)
            if len(content)!=item.size or sha256(content).hexdigest()!=files[item.name]['sha256']:
                raise ValueError('backup_bundle_changed')
            if directory is not None:_write(directory/item.name,content)


class LocalBackupGenerations:
    """Explicit local owner construction. Public key only during creation.

    initialize creates new private directories. Capture receives one nonexistent
    snapshot path and must write the approved complete native bundle there.
    No method publishes restored Auth/Storage, prunes a journal or buys resources.
    """
    def __init__(self,*,root,control,scratch,journal,obligations,public_key,clock=None):
        self.root=Path(root).absolute();self.control=Path(control).absolute();self.scratch=Path(scratch).absolute()
        self.journal=journal;self.obligations=Path(obligations).absolute();self.clock=clock or (lambda:datetime.now(timezone.utc))
        for path in (self.root,self.control,self.scratch,self.obligations):
            if path.is_symlink() or not path.is_dir() or path.stat().st_uid!=os.getuid() or path.stat().st_mode&0o077:
                raise ValueError('backup_private_directory_required')
        paths=[p.resolve() for p in (self.root,self.control,self.scratch)]
        if any(a.is_relative_to(b) or b.is_relative_to(a) for i,a in enumerate(paths) for b in paths[i+1:]):
            raise ValueError('backup_custody_overlap')
        if any(journal.path.resolve().is_relative_to(p) for p in (paths[0],paths[2])):
            raise ValueError('backup_journal_custody_overlap')
        if any(self.obligations.resolve().is_relative_to(p) or p.is_relative_to(self.obligations.resolve()) for p in (paths[0],paths[2])):
            raise ValueError('backup_obligation_custody_overlap')
        self.public=serialization.load_pem_public_key(public_key)
        if not isinstance(self.public,rsa.RSAPublicKey) or self.public.key_size!=3072:
            raise ValueError('backup_public_key_invalid')
        self.public_bytes=self.public.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        self.key_sha=sha256(self.public_bytes).hexdigest()
        self.identity=json.loads(_read(self.root/'repository.json',4096))
        expected={'version':1,'id':self.identity['id'],'root':str(self.root.resolve()),'control':str(self.control.resolve()),
                  'scratch':str(self.scratch.resolve()),'obligations':str(self.obligations.resolve()),'publicKeySha256':self.key_sha,'journalStream':journal.stream}
        UUID(self.identity['id'])
        if self.identity!=expected:raise ValueError('backup_repository_binding_changed')
        with self._db() as db:
            if [tuple(r) for r in db.execute('select body from identity').fetchall()]!=[(_encoded(expected).decode(),)]:
                raise ValueError('backup_catalog_binding_changed')

    @classmethod
    def initialize(cls,*,root,control,scratch,journal,obligations,public_key,clock=None):
        paths=[Path(p).absolute() for p in (root,control,scratch)]
        if any(p.exists() or p.is_symlink() for p in paths):raise ValueError('backup_directory_exists')
        if any(a.resolve().is_relative_to(b.resolve()) or b.resolve().is_relative_to(a.resolve()) for i,a in enumerate(paths) for b in paths[i+1:]):
            raise ValueError('backup_custody_overlap')
        public=serialization.load_pem_public_key(public_key)
        if not isinstance(public,rsa.RSAPublicKey) or public.key_size!=3072:raise ValueError('backup_public_key_invalid')
        for p in paths:p.mkdir(mode=0o700)
        identity={'version':1,'id':str(uuid4()),'root':str(paths[0].resolve()),'control':str(paths[1].resolve()),
                  'scratch':str(paths[2].resolve()),'obligations':str(Path(obligations).resolve()),'publicKeySha256':sha256(public.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest(),'journalStream':journal.stream}
        _write(paths[0]/'repository.json',_encoded(identity));(paths[0]/'generations').mkdir(mode=0o700);(paths[0]/'pending').mkdir(mode=0o700)
        with sqlite3.connect(paths[1]/'catalog.sqlite') as db:
            db.execute('pragma synchronous=FULL')
            db.executescript("""create table identity(body text not null); create table maintenance(status text not null); insert into maintenance values('idle'); create table attempts(id text primary key,status text not null,phase text not null,started real not null); create table generations(id text primary key,header text not null,header_sha text not null,cipher_sha text not null,completed real not null,state text not null);""")
            db.execute('insert into identity values(?)',(_encoded(identity).decode(),))
        (paths[1]/'catalog.sqlite').chmod(0o600)
        for p in paths:_sync(p)
        return cls(root=root,control=control,scratch=scratch,journal=journal,obligations=obligations,public_key=public_key,clock=clock)

    def _now(self):
        now=self.clock()
        if now.tzinfo is None:raise ValueError('backup_clock_invalid')
        return now.timestamp()

    def _guard(self):
        for path in (self.root,self.control,self.scratch,self.obligations,self.root/'generations',self.root/'pending'):
            if path.is_symlink() or not path.is_dir() or path.stat().st_uid!=os.getuid() or path.stat().st_mode&0o077:
                raise ValueError('backup_owned_directory_changed')

    @contextmanager
    def _db(self):
        self._guard()
        path=self.control/'catalog.sqlite';_read(path,64*1024**2)
        db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=1);db.row_factory=sqlite3.Row
        db.execute('pragma synchronous=FULL')
        try:
            if [tuple(r) for r in db.execute('select body from identity').fetchall()]!=[(_encoded(self.identity).decode(),)]:
                raise ValueError('backup_catalog_binding_changed')
            with db:yield db
        finally:db.close()

    @contextmanager
    def _lock(self):
        self._guard()
        path=self.control/'controller.lock'
        fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if json.loads(_read(self.root/'repository.json',4096))!=self.identity:
                raise ValueError('backup_repository_binding_changed')
            yield
        finally:os.close(fd)

    def _journal(self,minimum):
        head,entries=self.journal.read(minimum=minimum)
        if head!=minimum:raise ValueError('backup_current_journal_cut_required')
        if len(entries)>8:raise ValueError('backup_journal_profile_bound')
        for permit in entries:
            export=getattr(permit.facts,'documents_export_sha256',None)
            if not export:raise ValueError('backup_recovery_obligation_unavailable')
            NativeDispositionRecovery._export(permit,self.obligations/(export+'.documents-export.json'))
        return head

    def _verify(self,row):
        directory=self.root/'generations'/str(UUID(row['id']))
        if directory.is_symlink() or not directory.is_dir() or {p.name for p in directory.iterdir()}!={'header.json','payload.enc'}:
            raise ValueError('backup_generation_incomplete')
        header=_read(directory/'header.json',65536);cipher=_read(directory/'payload.enc',MAX_CIPHER)
        if sha256(header).hexdigest()!=row['header_sha'] or sha256(cipher).hexdigest()!=row['cipher_sha'] or header.decode()!=row['header']:
            raise ValueError('backup_generation_changed')
        value=json.loads(header)
        if value['repository']!=self.identity['id'] or value['generation']!=row['id'] or value['publicKeySha256']!=self.key_sha:
            raise ValueError('backup_generation_binding_changed')
        self.journal.read(minimum=_head(value['journal']))
        return value,cipher

    def _remove_owned(self,parent,identifier):
        path=parent/str(UUID(identifier))
        if path.is_symlink():raise ValueError('backup_owned_path_changed')
        if path.exists():shutil.rmtree(path);_sync(parent)

    def _abandon(self):
        with self._db() as db:
            rows=db.execute("select id,status from attempts where status in ('creating','failed')").fetchall()
            ready={r[0] for r in db.execute("select id from generations where state='ready'")}
            for row in rows:
                if row['id'] not in ready:
                    self._remove_owned(self.root/'pending',row['id']);self._remove_owned(self.root/'generations',row['id'])
                self._remove_owned(self.scratch,row['id'])
                if row['status']=='creating':db.execute("update attempts set status='failed',phase='interrupted' where id=?",(row['id'],))

    def _commit(self,identifier,header,cipher,completed):
        with self._db() as db:
            db.execute('insert into generations values(?,?,?,?,?,?)',(identifier,header.decode(),sha256(header).hexdigest(),sha256(cipher).hexdigest(),completed,'ready'))
            db.execute("update attempts set status='succeeded',phase='complete' where id=?",(identifier,))

    def create(self,*,capture,minimum):
        try:return self._create(capture=capture,minimum=minimum)
        finally:self.readiness(minimum=minimum)

    def _create(self,*,capture,minimum):
        with self._lock():
            self._journal(minimum);self._abandon();identifier=str(uuid4());started=self._now();wall=time.monotonic()
            with self._db() as db:
                if db.execute('select count(*) from attempts').fetchone()[0]>=MAX_GENERATIONS:raise ValueError('backup_repository_bound')
                db.execute('insert into attempts values(?,?,?,?)',(identifier,'creating','capture',started))
            work=self.scratch/identifier;work.mkdir(mode=0o700);pending=self.root/'pending'/identifier;pending.mkdir(mode=0o700);phase='capture'
            try:
                snapshot=work/'snapshot';capture(snapshot)
                if self._journal(minimum)!=minimum:raise ValueError('backup_journal_changed')
                finished=self._now()
                if finished<started or finished-started>POLICY['completionBudgetSeconds'] or time.monotonic()-wall>POLICY['completionBudgetSeconds']:
                    raise ValueError('backup_capture_deadline')
                payload,files,commitment=_bundle(snapshot);phase='encryption'
                with self._db() as db:db.execute("update attempts set phase='encryption' where id=?",(identifier,))
                key=AESGCM.generate_key(bit_length=256);nonce=os.urandom(12)
                wrapped=self.public.encrypt(key,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
                value={'version':1,'repository':self.identity['id'],'generation':identifier,'publicKeySha256':self.key_sha,
                       'capturedAt':started,'captureFinishedAt':finished,'journal':_cut(minimum),'files':files,'nativeBackupSha256':commitment,
                       'nonce':base64.b64encode(nonce).decode(),'wrappedKey':base64.b64encode(wrapped).decode()}
                header=_encoded(value);cipher=AESGCM(key).encrypt(nonce,payload,header)
                _write(pending/'header.json',header);_write(pending/'payload.enc',cipher);_sync(pending)
                # Verify actual readback and AEAD before the catalog can commit.
                observed_header=_read(pending/'header.json',65536);observed=_read(pending/'payload.enc',MAX_CIPHER)
                if observed_header!=header:raise ValueError('backup_header_changed')
                _extract(AESGCM(key).decrypt(nonce,observed,observed_header),None,files)
                if observed!=cipher:raise ValueError('backup_cipher_changed')
                self._journal(minimum);phase='publication'
                with self._db() as db:db.execute("update attempts set phase='publication' where id=?",(identifier,))
                os.rename(pending,self.root/'generations'/identifier);_sync(self.root/'generations');_sync(self.root/'pending')
                completed=self._now()
                if completed<started or completed-started>POLICY['completionBudgetSeconds'] or time.monotonic()-wall>POLICY['completionBudgetSeconds']:
                    raise ValueError('backup_completion_deadline')
                self._commit(identifier,header,cipher,completed)
                return identifier
            except BaseException as error:
                with self._db() as db:db.execute("update attempts set status='failed',phase=? where id=?",(phase,identifier))
                if isinstance(error,(KeyboardInterrupt,SystemExit)):raise
                raise ValueError('backup_generation_failed') from None
            finally:
                try:self._remove_owned(self.scratch,identifier)
                except BaseException:
                    with self._db() as db:db.execute("update attempts set status='failed',phase='cleanup' where id=?",(identifier,))
                    raise ValueError('backup_cleanup_failed') from None

    def readiness(self,*,minimum):
        now=self._now();valid=[];bad=[];reason=None
        try:self._journal(minimum)
        except Exception:reason='journal_unavailable'
        with self._db() as db:
            rows=db.execute("select * from generations where state='ready'").fetchall()
            attempt=db.execute('select status,phase,started from attempts order by rowid desc limit 1').fetchone()
            maintenance=db.execute('select status from maintenance').fetchone()[0]
            attempts=db.execute('select count(*) from attempts').fetchone()[0]
        for row in rows:
            try:
                header,_=self._verify(row)
                if header['capturedAt']>now or row['completed']>now:raise ValueError('backup_clock_regressed')
                valid.append((header['capturedAt'],row['id']))
            except Exception:bad.append(row['id'])
        latest=max(valid,default=None);age=now-latest[0] if latest else None
        active=False
        fd=os.open(self.control/'controller.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            try:fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
            except BlockingIOError:active=True
        finally:os.close(fd)
        if reason is None:
            reason=('repository_capacity_exhausted' if attempts>=MAX_GENERATIONS else 'generation_integrity_failed' if bad else 'rotation_incomplete' if maintenance not in ('idle','succeeded')
                    else 'creation_incomplete' if attempt and attempt['status']=='creating' and (not active or now-attempt['started']>POLICY['completionBudgetSeconds'])
                    else 'last_generation_failed' if attempt and attempt['status']=='failed'
                    else 'no_complete_generation' if latest is None else 'backup_stale' if age>POLICY['maxUsableAgeSeconds'] else 'fresh')
        result={'version':1,'observedAt':now,'ready':reason=='fresh','reason':reason,'usableGeneration':latest[1] if latest and reason!='journal_unavailable' else None,
                'usableAgeSeconds':age if reason!='journal_unavailable' else None,'completeGeneration':latest[1] if latest else None,'completeAgeSeconds':age,'recoverable':latest is not None and reason!='journal_unavailable','stale':age is None or age>POLICY['maxUsableAgeSeconds'],'capacityRemaining':MAX_GENERATIONS-attempts,'invalidGenerations':bad,'lastAttempt':dict(attempt) if attempt else None,'maintenance':maintenance,'captureInProgress':bool(attempt and attempt['status']=='creating' and active),
                'policy':POLICY,'journalRetention':'all admitted entries and held Documents exports; this controller never prunes either',
                'operatingAcceptance':False,'scope':'local sample only; separate recovery-key custody and operating resources remain required'}
        temporary=self.control/('status-'+uuid4().hex+'.tmp');_write(temporary,_encoded(result));os.replace(temporary,self.control/'readiness.json');_sync(self.control)
        return result

    def restore(self,*,generation,destination,recovery_key,minimum):
        with self._lock():
            head=self._journal(minimum);destination=Path(destination).absolute();key_path=Path(recovery_key).absolute()
            if any(key_path.resolve().is_relative_to(p.resolve()) for p in (self.root,self.scratch,destination)):
                raise ValueError('backup_recovery_key_custody_overlap')
            if destination.exists() or destination.is_symlink() or any(destination.resolve().is_relative_to(p.resolve()) or p.resolve().is_relative_to(destination.resolve()) for p in (self.root,self.control,self.scratch)):
                raise ValueError('backup_restore_destination_invalid')
            with self._db() as db:row=db.execute("select * from generations where id=? and state='ready'",(str(UUID(generation)),)).fetchone()
            if row is None:raise ValueError('backup_generation_unavailable')
            header,cipher=self._verify(row)
            private=serialization.load_pem_private_key(_read(key_path,16384,private=True),password=None)
            if not isinstance(private,rsa.RSAPrivateKey) or private.key_size!=3072 or private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)!=self.public_bytes:
                raise ValueError('backup_recovery_key_changed')
            key=private.decrypt(base64.b64decode(header['wrappedKey'],validate=True),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
            raw=AESGCM(key).decrypt(base64.b64decode(header['nonce'],validate=True),cipher,_encoded(header))
            destination.mkdir(mode=0o700)
            try:
                _extract(raw,destination,header['files'])
                if native_backup_commitment(destination)!=header['nativeBackupSha256']:raise ValueError('backup_restore_changed')
                self._journal(minimum);_sync(destination)
            except BaseException:
                shutil.rmtree(destination);raise
            return {'generation':row['id'],'directory':str(destination),'nativeBackupSha256':header['nativeBackupSha256'],
                    'capturedJournal':header['journal'],'requiredReplayHead':_cut(head),'publicationAuthorized':False}

    def rotate(self,*,minimum):
        with self._lock():
            with self._db() as db:db.execute("update maintenance set status='rotating'")
            try:
                result=self._rotate(minimum=minimum)
                with self._db() as db:db.execute("update maintenance set status='succeeded'")
            except BaseException:
                with self._db() as db:db.execute("update maintenance set status='failed'")
                raise
            finally:status=self.readiness(minimum=minimum)
            return {**result,'readiness':status}

    def _rotate(self,*,minimum):
        self._journal(minimum);self._abandon();now=self._now()
        with self._db() as db:rows=db.execute("select * from generations where state in ('ready','expiring')").fetchall()
        if any(json.loads(row['header'])['capturedAt']>now or row['completed']>now for row in rows):
            raise ValueError('backup_rotation_clock_regressed')
        healthy=[]
        for row in rows:
            if row['state']=='ready':
                try:
                    header,_=self._verify(row)
                    if header['capturedAt']>now or row['completed']>now:raise ValueError('backup_rotation_clock_regressed')
                    healthy.append((header['capturedAt'],row['id']))
                except Exception:pass
        if not healthy:raise ValueError('backup_rotation_survivor_unavailable')
        protected=max(healthy)[1];removed=[]
        for row in rows:
            header=json.loads(row['header'])
            if row['id']==protected:continue
            if row['state']=='expiring' or header['capturedAt']+POLICY['retentionSeconds']<=now:
                self._journal(minimum)
                with self._db() as db:db.execute("update generations set state='expiring' where id=?",(row['id'],))
                self._remove_owned(self.root/'generations',row['id'])
                with self._db() as db:db.execute("update generations set state='deleted' where id=?",(row['id'],))
                removed.append(row['id'])
        return {'removed':removed,'protectedGeneration':protected,'retentionOverdue':any(t+POLICY['retentionSeconds']<=now for t,identifier in healthy if identifier not in removed)}
