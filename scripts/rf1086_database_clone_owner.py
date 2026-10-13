"""Reconcile only this rehearsal's database acquisition on its owned source."""
import json
import os
from pathlib import Path
import re
import tempfile

from rf1086_restore_control import RestoreUnavailable, io_checked, require


class DatabaseCloneOwner:
    def __init__(self, container, source, clone, budget):
        require(type(container) is str and re.fullmatch('[a-f0-9]{64}', container)
                and source == 'postgres' and type(clone) is str
                and re.fullmatch('rf193_restore_[a-f0-9]{32}', clone), 'source_binding')
        self.container, self.source, self.clone, self.budget = container, source, clone, budget
        self.child_owner = budget.context.owner
        self.system = self.oid = None
        self.absent_before = self.attempted = self.create_complete = False
        self.directory = Path(tempfile.mkdtemp(prefix='talli-rf-clone-owner-'))
        os.chmod(self.directory, 0o700)
        self.record = self.directory/'owner.json'
        self._record()

    def _record(self):
        raw = json.dumps({'schema':'rf1086-database-clone-owner-v1', 'container':self.container,
            'source':self.source, 'clone':self.clone, 'systemIdentifier':self.system,
            'databaseOid':self.oid, 'absentBefore':self.absent_before,
            'createAttempted':self.attempted, 'createComplete':self.create_complete},
            sort_keys=True, separators=(',', ':')).encode()
        temporary = self.directory/'owner.next'
        fd = os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, self.record)
        finally:
            temporary.unlink(missing_ok=True)

    def _call(self, args, **kwargs):
        return io_checked(self.budget, ['docker','exec','-i',self.container]+args, **kwargs)

    def inspect(self):
        # Only a validated nonce is interpolated, never a supplied identifier.
        sql = ("SELECT pg_catalog.jsonb_build_array(system_identifier::pg_catalog.text,pg_catalog.current_database(),"
            "(SELECT pg_catalog.jsonb_build_array(oid::pg_catalog.text,pg_catalog.pg_get_userbyid(datdba),datistemplate) "
            "FROM pg_catalog.pg_database WHERE datname='"+self.clone+"')) FROM pg_catalog.pg_control_system();\n")
        raw = self._call(['psql','-U','supabase_admin','-d',self.source,'-XqAt',
            '-v','ON_ERROR_STOP=1'],input=sql.encode(),capture_cap=4096).stdout
        try:
            value = json.loads(raw)
            require(type(value) is list and len(value)==3 and value[1]==self.source
                and type(value[0]) is str and re.fullmatch('[1-9][0-9]{0,19}',value[0])
                and int(value[0])<2**64, 'cleanup_uncertain')
            require(self.system is None or self.system==value[0], 'cleanup_uncertain')
            self.system = value[0]
            row = value[2]
            if row is not None:
                require(type(row) is list and len(row)==3 and row[1]=='supabase_admin' and row[2] is False
                    and type(row[0]) is str and re.fullmatch('[1-9][0-9]{0,9}',row[0])
                    and int(row[0])<2**32, 'cleanup_uncertain')
                require(self.oid is None or self.oid==row[0], 'cleanup_uncertain')
                if self.attempted:
                    self.oid = row[0]
            self._record()
            return row
        except RestoreUnavailable:
            raise
        except (ValueError, TypeError, KeyError, IndexError, UnicodeError):
            raise RestoreUnavailable('cleanup_uncertain') from None

    def create(self):
        require(not self.attempted and self.inspect() is None, 'source_binding')
        self.absent_before = self.attempted = True
        self._record()  # Intent survives a successful CREATE with lost CLI response.
        self._call(['createdb','-U','supabase_admin','--template=template0',self.clone])
        self.create_complete = True
        self._record()
        require(self.inspect() is not None, 'creation_profile')

    def cleanup(self):
        if self.attempted:
            require(self.absent_before, 'cleanup_uncertain')
            if self.inspect() is not None:
                self._call(['dropdb','-U','supabase_admin','--force',self.clone])
            require(self.inspect() is None, 'cleanup_uncertain')
            # A lost docker-exec response cannot prove its daemon-side createdb
            # finished. Keep the record even after a presently absent database.
            require(self.create_complete, 'cleanup_uncertain')
        require(not self.child_owner.uncertain and not any(s.acquiring or s.process is not None for s in self.child_owner.slots),
                'cleanup_uncertain')
        require({p.name for p in self.directory.iterdir()} == {'owner.json'}, 'cleanup_uncertain')
        self.record.unlink(); self.directory.rmdir()
