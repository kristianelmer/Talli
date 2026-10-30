"""Ownership of the five fixed disposable Storage restore resources.

The record contains resource identities, never captured configuration or objects.
Docker CLI completion alone does not prove daemon-side acquisition or removal.
"""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time

from rf1086_restore_control import io_checked, io_deadline


LABEL = 'talli.rf.restore'
KINDS = ('volume', 'tar', 'attributes', 'capture', 'service')


def require(condition, reason):
    if not condition:
        raise ValueError('Owned Storage ownership unavailable: ' + reason)


class StorageOwner:
    def __init__(self, source, network, nonce, *, budget, legacy_checked):
        require(type(nonce) is str and re.fullmatch('[a-f0-9]{32}', nonce), 'nonce')
        self.source = self.source_identity(source, network)
        self.network, self.nonce = network, nonce
        self.image = self.source['image']
        self.budget, self.legacy_checked = budget, legacy_checked
        self.end = budget.end if budget is not None else None
        self.child_owner = budget.context.owner if budget is not None else None
        self.names = {'volume': 'rf193_objects_' + nonce, 'service': 'rf193_storage_' + nonce,
                      **{kind: 'rf193_storage_' + kind + '_' + nonce for kind in KINDS[1:4]}}
        require(self.names['volume'] != self.source['volume'], 'source_volume')
        self.attempted, self.completed, self.identities = [], [], {}
        self.uncertain = False
        self.directory = Path(tempfile.mkdtemp(prefix='talli-rf-storage-owner-'))
        self.directory.chmod(0o700)
        info = self.directory.stat()
        self.directory_identity = (info.st_dev, info.st_ino)
        self.record = self.directory / 'owner.json'
        self.configuration = self.directory / 'storage.env'
        self._record()

    @staticmethod
    def source_identity(value, network):
        require(type(value) is dict and type(network) is str and bool(network), 'source')
        identity, image, name = value.get('Id'), value.get('Image'), value.get('Name')
        require(type(identity) is str and re.fullmatch('[a-f0-9]{64}', identity)
                and type(image) is str and re.fullmatch('sha256:[a-f0-9]{64}', image)
                and type(name) is str and re.fullmatch('/supabase_storage_[a-zA-Z0-9_-]+', name), 'source')
        mounts = [m for m in value.get('Mounts', []) if m.get('Destination') == '/mnt']
        require(value.get('State', {}).get('Running') is True
                and set(value.get('NetworkSettings', {}).get('Networks', {})) == {network}
                and len(mounts) == 1 and mounts[0].get('Type') == 'volume'
                and type(mounts[0].get('Name')) is str and bool(mounts[0]['Name']), 'source')
        return {'id': identity, 'name': name, 'image': image, 'volume': mounts[0]['Name']}

    def _root(self):
        info = self.directory.lstat()
        require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
                and (info.st_dev, info.st_ino) == self.directory_identity, 'record_directory')

    def _record(self):
        self._root()
        if self.budget is not None:
            self.budget.remaining(end=self.end)
        raw = json.dumps({'schema': 'rf1086-storage-owner-v1', 'source': self.source,
            'network': self.network, 'nonce': self.nonce, 'names': self.names,
            'attempted': self.attempted, 'completed': self.completed,
            'identities': self.identities, 'uncertain': self.uncertain},
            sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        require(len(raw) <= 16384, 'record_limit')
        pending = self.directory / 'owner.next'
        with io_deadline(self.budget):
            fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(raw); output.flush(); os.fsync(output.fileno())
                os.replace(pending, self.record)
            finally:
                pending.unlink(missing_ok=True)

    def command(self, args, *, data=None, archive=None, cap=1024**2):
        require(data is None or archive is None, 'input')
        kwargs = {'stdout': subprocess.PIPE}
        if data is not None: kwargs['input'] = data
        if archive is not None: kwargs['stdin'] = archive
        if self.budget is not None:
            result = io_checked(self.budget, args, capture_cap=cap,
                end=min(self.end, time.monotonic()+30), **kwargs)
        else:
            result = self.legacy_checked(args, **kwargs)
        require(type(result.stdout) is bytes and len(result.stdout) <= cap, 'output')
        return result.stdout

    def _json(self, raw):
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise ValueError('Owned Storage ownership unavailable: inspect') from None

    def verify_source(self):
        rows = self._json(self.command(['docker', 'container', 'inspect', self.source['id']]))
        require(type(rows) is list and len(rows) == 1
                and self.source_identity(rows[0], self.network) == self.source, 'source_changed')

    def inspect(self, kind):
        require(kind in KINDS, 'kind')
        resource = 'volume' if kind == 'volume' else 'container'
        name = self.names[kind]
        args = ['docker', resource, 'ls'] + (['--all'] if resource == 'container' else [])
        args += ['--format', '{{json .Name}}' if resource == 'volume' else '{{json .Names}}',
                 '--filter', 'name=' + name]
        found = [self._json(line) for line in self.command(args, cap=4096).splitlines()]
        require(all(type(item) is str for item in found) and found.count(name) <= 1, 'listing')
        if name not in found:
            if resource == 'container' and kind in self.identities:
                require(not self.command(args[:-1]+['id='+self.identities[kind]], cap=4096).strip(),
                        'renamed_container')
            return None
        rows = self._json(self.command(['docker', resource, 'inspect', name]))
        require(type(rows) is list and len(rows) == 1 and type(rows[0]) is dict, 'inspect')
        value = rows[0]
        labels = value.get('Labels', {}) if resource == 'volume' else value.get('Config', {}).get('Labels', {})
        require(value.get('Name') == (name if resource == 'volume' else '/' + name)
                and type(labels) is dict and labels.get(LABEL) == self.nonce, 'ownership_mismatch')
        identity = name if resource == 'volume' else value.get('Id')
        if resource == 'container':
            require(type(identity) is str and re.fullmatch('[a-f0-9]{64}', identity)
                    and identity != self.source['id'] and value.get('Image') == self.image, 'container_identity')
            mounts = [m for m in value.get('Mounts', []) if m.get('Destination') == '/mnt']
            require(len(mounts) == 1 and mounts[0].get('Type') == 'volume'
                    and mounts[0].get('Name') == self.names['volume']
                    and mounts[0].get('RW') is True, 'container_mount')
            mode = self.network if kind == 'service' else 'none'
            require(value.get('HostConfig', {}).get('NetworkMode') == mode, 'container_network')
            if kind == 'service':
                require(set(value.get('NetworkSettings', {}).get('Networks', {})) == {self.network},
                        'container_network')
        require(kind not in self.identities or self.identities[kind] == identity, 'replaced_resource')
        if kind not in self.identities:
            self.identities[kind] = identity
            self._record()
        return value

    def acquire(self, kind, args):
        require(kind in KINDS and kind not in self.attempted, 'acquisition')
        # Durable attempt precedes the mutating CLI; no return-value-only ownership.
        self.attempted.append(kind)
        self._record()
        self.command(args, cap=4096)
        require(self.inspect(kind) is not None, 'acquisition_absent')
        self.completed.append(kind)
        self._record()
        return self.identities[kind]

    def helper(self, kind, args, *, data=None, archive=None, cap=1024**2):
        require(kind in KINDS[1:4], 'helper')
        identity = self.acquire(kind, ['docker', 'create', '--pull=never', '--name', self.names[kind],
            '--label', LABEL+'='+self.nonce, '--network', 'none', '--user', '0',
            '--entrypoint', args[0], '-i', '-v', self.names['volume']+':/mnt', self.image, *args[1:]])
        raw = self.command(['docker', 'start', '-a', '-i', identity], data=data, archive=archive, cap=cap)
        value = self.inspect(kind)
        require(value is not None and value.get('State', {}).get('Running') is False
                and value['State'].get('Status') == 'exited'
                and type(value['State'].get('ExitCode')) is int and value['State']['ExitCode'] == 0, 'helper_exit')
        self.remove(kind)
        return raw

    def write_configuration(self, values):
        self._root()
        raw = ''.join(key+'='+value+'\n' for key, value in values.items()).encode()
        require(len(raw) <= 1024**2, 'configuration_limit')
        with io_deadline(self.budget):
            fd = os.open(self.configuration, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as output: output.write(raw)
        return self.configuration

    def remove(self, kind):
        if self.inspect(kind) is None:
            # An interrupted create that was never seen may still be in the daemon.
            require(kind in self.completed or kind in self.identities, 'unresolved_acquisition')
            return
        args = ['docker', 'volume', 'rm'] if kind == 'volume' else ['docker', 'container', 'rm', '-f']
        self.command(args+[self.identities[kind]], cap=4096)
        require(self.inspect(kind) is None, 'removal_unproved')

    def cleanup(self, primary=None):
        errors = []
        # Never retain copied secrets alongside an uncertainty record.
        try:
            self._root()
            self.configuration.unlink(missing_ok=True)
        except BaseException as error: errors.append(error)
        for kind in reversed(self.attempted):
            try: self.remove(kind)
            except BaseException as error: errors.append(error)
        active = self.child_owner is not None and (self.child_owner.uncertain
            or any(s.acquiring or s.process is not None for s in self.child_owner.slots))
        if errors or active:
            self.uncertain = True
            if primary is None:
                primary = next((error for error in errors if not isinstance(error, Exception)), None)
            try: self._record()
            except BaseException: pass  # The pre-acquisition owner record already exists.
            if self.child_owner is not None:
                self.child_owner._uncertain('storage_cleanup', errors[0] if errors else
                    ValueError('Owned Storage ownership unavailable: child_uncertain'), primary)
            if primary is not None: raise primary
            raise ValueError('Owned Storage ownership unavailable: cleanup_uncertain') from None
        self._root()
        require({p.name for p in self.directory.iterdir()} == {'owner.json'}, 'record_contents')
        self.record.unlink(); self.directory.rmdir()
