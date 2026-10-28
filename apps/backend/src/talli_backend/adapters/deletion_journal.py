"""External local journal adapter for a finite offline recovery exercise.

Not a hosted journal, retention scheduler or custody claim. The path must be
outside the restorable customer root. OS access control is the writer authority;
chain hashes detect corruption and an independently supplied minimum head detects
rollback. Neither alone authenticates a malicious journal administrator.
"""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from uuid import UUID, uuid4

from talli_backend.application.company_disposition import JournalHead
from talli_backend.modules.company_access.public import AuthorizedCompanyDisposition, authorize_company_disposition

MAX_BODY = 1024 * 1024
MAX_JOURNAL = 16 * MAX_BODY
GENESIS = '0' * 64



def _digest(previous: str, sequence: int, body: str) -> str:
    return sha256((previous + '\n' + str(sequence) + '\n' + body).encode()).hexdigest()


class LocalDeletionJournal:
    def __init__(self, path: Path, *, customer_root: Path, stream: str):
        self.path = path.absolute()
        self.customer_root = customer_root.resolve()
        self.stream = str(UUID(stream))
        if self.path.resolve().is_relative_to(self.customer_root):
            raise ValueError('deletion_journal_inside_customer_snapshot')

    @classmethod
    def initialize(cls, path: Path, *, customer_root: Path):
        stream = str(uuid4())
        journal = cls(path, customer_root=customer_root, stream=stream)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        with journal._connection(write=True) as db:
            db.executescript('''
                create table identity(stream text not null);
                create table tombstones(sequence integer primary key, operation text unique not null,
                  previous text not null, body text not null, digest text not null);
                create table applied(target text not null, sequence integer not null, record text not null,
                  receipt text not null, primary key(target, sequence, record));
            ''')
            db.execute('insert into identity values(?)', (stream,))
        # Bind the newly created directory entry before any tombstone can be
        # acknowledged. SQLite FULL handles subsequent transaction durability.
        with path.open('rb') as source:
            os.fsync(source.fileno())
        parent = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(parent)
        finally: os.close(parent)
        return journal

    @contextmanager
    def _connection(self, *, write=False):
        if self.path.is_symlink() or self.path.resolve().is_relative_to(self.customer_root):
            raise ValueError('deletion_journal_path_changed')
        if not self.path.is_file() or self.path.stat().st_size > MAX_JOURNAL:
            raise ValueError('deletion_journal_unavailable')
        db = sqlite3.connect(self.path.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=.2)
        if write:
            db.execute('pragma synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def read(self, *, minimum: JournalHead | None = None):
        with self._connection() as db:
            if db.execute('select stream from identity').fetchall() != [(self.stream,)]:
                raise ValueError('deletion_journal_identity_changed')
            rows = db.execute('select sequence,operation,previous,body,digest from tombstones order by sequence limit 1001').fetchall()
        if len(rows) > 1000:
            raise ValueError('deletion_journal_bound_exceeded')
        digest = GENESIS; entries = []; total = 0
        for sequence, operation, previous, body, observed in rows:
            total += len(body.encode())
            if (sequence != len(entries) + 1 or previous != digest or len(body.encode()) > MAX_BODY
                    or total > MAX_JOURNAL or _digest(previous, sequence, body) != observed):
                raise ValueError('deletion_journal_incomplete')
            permit = AuthorizedCompanyDisposition.model_validate_json(body)
            if authorize_company_disposition(permit.plan, permit.facts, now=permit.authorized_at) != permit:
                raise ValueError('deletion_journal_authorization_changed')
            if str(permit.plan.operation_id) != operation:
                raise ValueError('deletion_journal_operation_changed')
            digest = observed; entries.append(permit)
        head = JournalHead(self.stream, len(entries), digest)
        if minimum is not None:
            if (minimum.stream != self.stream or minimum.sequence < 0 or minimum.sequence > head.sequence
                    or (minimum.sha256 != (GENESIS if minimum.sequence == 0 else rows[minimum.sequence-1][4]))):
                raise ValueError('deletion_journal_rollback_or_gap')
        return head, tuple(entries)

    def append(self, permit: AuthorizedCompanyDisposition) -> JournalHead:
        body = permit.model_dump_json()
        if len(body.encode()) > MAX_BODY:
            raise ValueError('deletion_journal_bound_exceeded')
        # Serialize writers before reading the chain; no acknowledged result can
        # precede a durably committed tombstone, including an unknown purge result.
        with self._connection(write=True) as db:
            db.execute('begin immediate')
            head, _ = self.read()
            prior = db.execute('select body from tombstones where operation=?', (str(permit.plan.operation_id),)).fetchone()
            if prior:
                if prior != (body,):
                    raise ValueError('deletion_journal_idempotency_conflict')
                return head
            validated = AuthorizedCompanyDisposition.model_validate_json(body)
            if authorize_company_disposition(validated.plan, validated.facts, now=validated.authorized_at) != validated:
                raise ValueError('deletion_journal_authorization_changed')
            if head.sequence >= 1000 or db.execute('select coalesce(sum(length(body)),0) from tombstones').fetchone()[0] + len(body.encode()) > MAX_JOURNAL:
                raise ValueError('deletion_journal_bound_exceeded')
            sequence = head.sequence + 1; digest = _digest(head.sha256, sequence, body)
            db.execute('insert into tombstones values(?,?,?,?,?)',
                       (sequence, str(permit.plan.operation_id), head.sha256, body, digest))
        return JournalHead(self.stream, sequence, digest)

    def applied(self, target: str, sequence: int, record: str, receipt: str) -> None:
        with self._connection(write=True) as db:
            prior = db.execute('select receipt from applied where target=? and sequence=? and record=?',
                               (target, sequence, record)).fetchone()
            if prior and prior != (receipt,):
                raise ValueError('deletion_replay_receipt_changed')
            db.execute('insert or ignore into applied values(?,?,?,?)', (target, sequence, record, receipt))


def write_replay_receipt(path: Path, target: str, head: JournalHead) -> None:
    """Durably publish only the verified terminal head for this fresh target."""
    raw = json.dumps({'target': target, 'stream': head.stream, 'sequence': head.sequence,
                      'sha256': head.sha256}, sort_keys=True).encode()
    temporary = path.with_name(path.name + '.' + uuid4().hex)
    try:
        with temporary.open('xb') as output:
            os.chmod(temporary, 0o600); output.write(raw); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def replay_is_current(journal: LocalDeletionJournal, *, receipt: Path, target: str, minimum: JournalHead) -> bool:
    try:
        if receipt.is_symlink() or not receipt.is_file() or receipt.stat().st_size > 4096:
            return False
        head, _ = journal.read(minimum=minimum)
        observed = json.loads(receipt.read_bytes())
        return (isinstance(observed, dict) and type(observed.get('sequence')) is int and observed == {
            'target': target, 'stream': head.stream, 'sequence': head.sequence, 'sha256': head.sha256,
        })
    except Exception:
        return False


class LocalReplayReceipt:
    def __init__(self, path: Path):
        self.path = path

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def publish(self, target: str, head: JournalHead) -> None:
        write_replay_receipt(self.path, target, head)
