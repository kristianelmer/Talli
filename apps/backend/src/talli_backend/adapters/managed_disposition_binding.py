"""Independent native-owner completion prerequisite for a managed logical copy.

This carries an existing local-only replay result, never hosted erase authority.
OS custody remains the writer trust boundary, as with LocalDeletionJournal.
"""
from dataclasses import asdict
import base64
from pathlib import Path
import re
import os
from uuid import UUID

from talli_backend.adapters.deletion_journal import LocalDeletionJournal, replay_is_current
from talli_backend.adapters.hosted_recovery_capture import digest, json_bytes, private_read, require
from talli_backend.adapters.native_disposition_recovery import NativeDispositionRecovery, native_backup_commitment
from talli_backend.application.company_disposition import JournalHead
from talli_backend.modules.company_access.public import AuthorizedLocalDocumentsDisposition

FORMAT = 'talli-native-replayed-managed-capture-v1'
TABLES = frozenset('documents.local_native_disposition_' + name for name in
    ('plans', 'targets', 'receipts'))


def native_custody(*, journal, minimum, native_binding, native_binding_sha256,
        backup, backup_sha256, exports):
    """Validate independently held inputs before entering any owning erase phase."""
    require(type(minimum.sequence) is int and 1 <= minimum.sequence <= 8 and
        re.fullmatch('[a-f0-9]{64}', minimum.sha256) and str(UUID(minimum.stream)) == minimum.stream,
        'hosted_disposition_minimum_invalid')
    private_read(journal.path, 16 * 1024**2)
    head, entries = journal.read(minimum=minimum)
    require(head == minimum and 1 <= len(entries) <= 8 and
        all(isinstance(p, AuthorizedLocalDocumentsDisposition) for p in entries),
        'hosted_disposition_current_cut_required')
    require(len({(p.plan.company_id, p.facts.target_id, p.owner_subject) for p in entries}) == 1,
        'hosted_disposition_history_unsupported')
    raw = private_read(native_binding, 1024 * 1024)
    require(digest(raw) == native_binding_sha256, 'hosted_disposition_native_binding_changed')
    binding = json_bytes(raw)
    require(binding['backupSha256'] == backup_sha256 and binding['journal'] == asdict(head) and
        binding.get('nativeProfile') and binding['sourceTarget'] == str(entries[0].facts.target_id) and
        binding['sourceTarget'] != binding['target'] and
        binding['sourceSystemIdentifier'] != binding['systemIdentifier'],
        'hosted_disposition_native_binding_changed')
    expected = [digest(p.model_dump_json().encode()) for p in entries]
    require((binding['version'] == 1 and len(entries) == 1 and
            binding['authorizationSha256'] == expected[0]) or
        (binding['version'] == 2 and len(binding['operations']) == len(entries) and
            [o['authorizationSha256'] for o in binding['operations']] == expected),
        'hosted_disposition_authorization_changed')
    backup = Path(backup)
    require(backup.is_dir() and backup.stat().st_uid == os.getuid() and
        not backup.stat().st_mode & 0o077 and not any(p.is_symlink() for p in (backup, *backup.parents)),
        'hosted_disposition_backup_changed')
    for member in backup.iterdir():
        require(member.is_file() and not member.is_symlink() and member.stat().st_uid == os.getuid()
            and not member.stat().st_mode & 0o077 and member.stat().st_nlink == 1,
            'hosted_disposition_backup_changed')
    require(native_backup_commitment(backup) == backup_sha256, 'hosted_disposition_backup_changed')
    require(len(exports) == len(entries), 'hosted_disposition_exports_incomplete')
    for permit, path in zip(entries, exports):
        private_read(path, 32 * 1024**2)
        NativeDispositionRecovery._export(permit, path)
    return binding, head, entries


class ManagedDispositionBinding:
    """Explicit external custody; the current minimum is never learned from a snapshot."""
    def __init__(self, *, proof, proof_sha256, journal, minimum, receipt,
            native_binding, native_binding_sha256, backup, backup_sha256, exports,
            customer_root):
        require(set(minimum) == {'stream', 'sequence', 'sha256'} and
            type(minimum['sequence']) is int and 1 <= minimum['sequence'] <= 8 and
            re.fullmatch('[a-f0-9]{64}', minimum['sha256']) and
            str(UUID(minimum['stream'])) == minimum['stream'], 'hosted_disposition_minimum_invalid')
        self.minimum = JournalHead(**minimum)
        self.proof_path, self.receipt_path = Path(proof), Path(receipt)
        self.binding_path, self.backup = Path(native_binding), Path(backup)
        self.exports = tuple(Path(p) for p in exports)
        self.expected = (proof_sha256, native_binding_sha256, backup_sha256)
        self.journal = LocalDeletionJournal(Path(journal), customer_root=Path(customer_root),
            stream=self.minimum.stream)
        require(len(self.exports) == self.minimum.sequence, 'hosted_disposition_exports_incomplete')
        self.require_external(Path(customer_root))
        self.body = self._proof()
        self.check_current()

    def require_external(self, root):
        root = root.absolute()
        for path in (self.proof_path, self.receipt_path, self.binding_path, self.backup,
                self.journal.path, *self.exports):
            require(path.is_absolute() and path == path.resolve() and not path.is_relative_to(root) and
                not any(p.is_symlink() for p in (path, *path.parents)),
                'hosted_disposition_custody_overlap')

    def _proof(self):
        raw = private_read(self.proof_path, 65536)
        require(digest(raw) == self.expected[0], 'hosted_disposition_proof_changed')
        value = json_bytes(raw)
        require(set(value) == {'version', 'profile', 'nativeTarget', 'nativeSystemIdentifier',
            'operatorLogin', 'journal', 'nativeBindingSha256', 'nativeBackupSha256',
            'exportSha256', 'headerSha256', 'accessSha256', 'nativeTables',
            'nativeHistoryFiles', 'nativeHistoryBytes', 'publicationAuthorized'} and
            type(value['nativeHistoryFiles']) is int and 0 <= value['nativeHistoryFiles'] <= 256 and
            type(value['nativeHistoryBytes']) is int and 0 <= value['nativeHistoryBytes'] <= 16 * 1024**2 and
            value['version'] == 1 and value['profile'] == FORMAT and
            value['publicationAuthorized'] is False and value['journal'] == asdict(self.minimum) and
            value['nativeBindingSha256'] == self.expected[1] and
            value['nativeBackupSha256'] == self.expected[2] and
            str(UUID(value['nativeTarget'])) == value['nativeTarget'] and
            re.fullmatch('[0-9]{1,20}', value['nativeSystemIdentifier']) and
            re.fullmatch('talli_native_disposition_[a-f0-9]{16,32}', value['operatorLogin']) and
            set(value['nativeTables']) == TABLES and all(set(v) == {'rows', 'sha256'} and
                type(v['rows']) is int and v['rows'] >= 0 and re.fullmatch('[a-f0-9]{64}', v['sha256'])
                for v in value['nativeTables'].values()),
            'hosted_disposition_proof_invalid')
        return value

    def check_current(self):
        value = self._proof()
        # Verify private ownership/ancestry before SQLite or native export readers.
        private_read(self.receipt_path, 4096)
        binding, head, entries = native_custody(journal=self.journal, minimum=self.minimum,
            native_binding=self.binding_path, native_binding_sha256=self.expected[1],
            backup=self.backup, backup_sha256=self.expected[2], exports=self.exports)
        require(binding['target'] == value['nativeTarget'] and
            binding['systemIdentifier'] == value['nativeSystemIdentifier'] and
            binding['operatorLogin'] == value['operatorLogin'],
            'hosted_disposition_native_binding_changed')
        export_hashes = [permit.facts.documents_export_sha256 for permit in entries]
        require(export_hashes == value['exportSha256'] and
            replay_is_current(self.journal, receipt=self.receipt_path,
                target=value['nativeTarget'], minimum=head),
            'hosted_disposition_owner_replay_required')
        return value

    def verify_capture(self, capture, *, header_sha256, access_sha256):
        value = self.check_current()
        require(capture.source_project == 'native:' + value['nativeTarget'] and
            capture.profile.get('nativeOrigin') == {
                'target': value['nativeTarget'], 'systemIdentifier': value['nativeSystemIdentifier'],
                'nativeBindingSha256': self.expected[1]} and
            header_sha256 == value['headerSha256'] and access_sha256 == value['accessSha256'] and
            {k: v for k, v in capture.rows.items() if k in TABLES} == value['nativeTables'] and
            not any(v['rows'] for k, v in capture.rows.items()
                if k.startswith('documents.local_native_disposition_') and k not in TABLES) and
            capture.rows['documents.local_native_disposition_plans']['rows'] == self.minimum.sequence and
            capture.rows['documents.local_native_disposition_targets']['rows'] >= 2 and
            capture.rows['documents.local_native_disposition_receipts']['rows'] == sum(
                r.action == 'erase' for p in self.journal.read(minimum=self.minimum)[1] for r in p.plan.records) and
            any(role[0] == value['operatorLogin'] for role in capture.roles['roles']),
            'hosted_disposition_capture_changed')
        remaining = {}; held = {}
        entries = self.journal.read(minimum=self.minimum)[1]
        for permit, path in zip(entries, self.exports):
            for record in permit.plan.records:
                if record.action == 'erase': remaining.pop(record.record_id, None)
                else: remaining[record.record_id] = (permit.plan.company_id, record.income_year)
            for item in NativeDispositionRecovery._export(permit, path)['files']:
                fact = {k: item[k] for k in ('path', 'bytes', 'sha256')}
                require(item['path'] not in held or held[item['path']] == fact,
                    'hosted_disposition_history_inventory_invalid')
                held[item['path']] = fact
        paths = set(); total = 0
        current = {'stub/stub/' + o['bucket'] + '/' + o['name'] + '/' + o['nativeCurrentVersion']
            for o in capture.objects}
        for item in capture.native_history:
            require(set(item) == {'path', 'bytes', 'sha256', 'base64'} and
                isinstance(item['path'], str) and 0 < len(item['path'].encode()) <= 2048 and
                type(item['bytes']) is int and item['bytes'] >= 0 and item['path'] not in paths and
                item['path'] not in current and held.get(item['path']) == {
                    k: item[k] for k in ('path', 'bytes', 'sha256')} and
                any(item['path'].startswith(f'stub/stub/company-documents/{company}/{year}/{record}/')
                    for record, (company, year) in remaining.items()),
                'hosted_disposition_history_inventory_invalid')
            body = base64.b64decode(item['base64'], validate=True); total += len(body)
            require(len(body) == item['bytes'] <= 8 * 1024**2 and digest(body) == item['sha256'] and
                total <= 16 * 1024**2, 'hosted_disposition_history_bytes_changed')
            paths.add(item['path'])
        require(len(paths) == value['nativeHistoryFiles'] and total == value['nativeHistoryBytes'],
            'hosted_disposition_history_inventory_invalid')

    def summary(self):
        return {'profile': FORMAT, 'proofSha256': self.expected[0],
            'nativeTarget': self.body['nativeTarget'], 'journal': asdict(self.minimum),
            'nativeBindingSha256': self.expected[1], 'publicationAuthorized': False,
            'nativeHistoryFiles': self.body['nativeHistoryFiles'],
            'nativeHistoryBytes': self.body['nativeHistoryBytes']}
