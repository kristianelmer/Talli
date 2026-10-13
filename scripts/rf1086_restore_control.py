"""Owned construction mechanics; never a failed-restore replay admission path.

All deadlines descend from the recovery child's entry clock. Source metadata
and SQL are private inputs; public observations contain finite labels and hashes.
"""
from dataclasses import dataclass
from copy import deepcopy
from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
from pathlib import Path
import math
import re
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

import rf1086_catalog_semantics as commands
import rf1086_s0_control as pipes
import rf1086_s0_protocol as wire
import rf1086_sql_ledger as ledger
import rf1086_raw_toc as raw_toc
import rf1086_catalog_causal_capture as capture


SCHEMA = 'rf1086-restore-construction-v1'
MAX_ARCHIVE = 64 * 1024**2
MAX_SCRIPT = 128 * 1024**2
MAX_METADATA = 8 * 1024**2
MAX_ROLES = 1024**2
REASONS = frozenset(('source_binding', 'source_drift', 'metadata_profile', 'role_profile',
    'role_order', 'archive_profile', 'suffix_profile', 'creation_profile', 'prefix_binding',
    'postcondition', 'delivery', 'deadline', 'limit', 'child_failure', 'cleanup_uncertain',
    'cancelled', 'internal'))
PHASES = {'construction': 115, 'actors': 150, 'cleanup': 165, 'source_post': 178, 'output': 180}
PHASE_MAX = {'actors': 35, 'cleanup': 15, 'source_post': 13, 'output': 2}
CONFIG = {'schema': SCHEMA, 'archiveBytes': MAX_ARCHIVE, 'scriptBytes': MAX_SCRIPT,
          'metadataBytes': MAX_METADATA, 'rolesBytes': MAX_ROLES, 'cutKinds': ['Is','In','acl'],
          'phaseEndpoints': PHASES, 'phaseMaximumSeconds': PHASE_MAX,
          'targetHeadroomSeconds': 70, 'writerWorkSeconds': 43, 'writerUnwindSeconds': 2,
          'sourceConsistency': 'checked-M0-M1-final-not-atomic', 'legacyReplay': 'inapplicable'}
OFFLINE_RESTORE = ('test -p /proc/self/fd/0 && exec pg_restore --verbose '
                   '--clean --if-exists --create --file=- 2>/dev/null')
TOOL_COMMAND = '''set -eu
binary=$(command -v @TOOL@)
case "$binary" in /*) ;; *) exit 1;; esac
[ -f "$binary" ] && [ -x "$binary" ]
version=$("$binary" --version)
hashed=$(sha256sum "$binary")
printf '%s\\n%s\\n' "$version" "${hashed%% *}"
'''


class RestoreUnavailable(ValueError):
    def __init__(self, reason):
        self.reason = reason if reason in REASONS else 'internal'
        super().__init__('restore_construction_unavailable')


def require(condition, reason):
    if not condition:
        raise RestoreUnavailable(reason)


class _UnwindOwner(pipes.ChildOwner):
    """Record repeated termination while finishing the same finite cleanup."""
    def __init__(self, original, primary):
        super().__init__()
        self.original, self.initiating = original, primary

    def _cancel(self, error):
        if self.original.primary is None and self.initiating is not None:
            self.original.primary = self.initiating
        self.original._cancel(error)


def unwind_scope(budget):
    """Preserve the initiating exception; cleanup faults can never mint success."""
    # Capture in the caller's exception state, before entering a new generator.
    return _unwind_scope(budget, sys.exception())


@contextmanager
def _unwind_scope(budget, primary):
    original = budget.context
    cleanup = pipes.new_context()
    cleanup.owner = _UnwindOwner(original.owner, primary)
    budget.context = cleanup
    try:
        with cleanup.owner.deferred():
            yield
    except BaseException as error:
        original.owner._uncertain('restore_cleanup', error, primary)
        if primary is not None:
            raise primary
        raise
    finally:
        budget.context = original
        original.raise_if_fatal()


class RecoveryBudget:
    """One entry clock, cumulative endpoints; changing phase creates no time."""
    def __init__(self, started):
        require(type(started) in (int, float) and math.isfinite(started)
                and 0 < started <= time.monotonic(), 'deadline')
        self.started = started
        self.phase = 'construction'
        self.end = started + PHASES[self.phase]
        self.context = pipes.new_context()
        self.phase_started = started
        self.phase_elapsed = {}

    def enter(self, phase):
        require(phase in PHASES and PHASES[phase] >= PHASES[self.phase], 'deadline')
        if phase != self.phase:
            now = time.monotonic()
            self.phase_elapsed[self.phase] = now-self.phase_started
            self.phase_started = now
            self.phase = phase
            self.end = min(self.started + PHASES[phase], now + PHASE_MAX[phase])
        self.remaining()

    def remaining(self, *, reserve=0, end=None):
        self.context.raise_if_fatal()
        until = self.end if end is None else min(end, self.end)
        remaining = until - time.monotonic() - reserve
        require(remaining > 0, 'deadline')
        return remaining

    def before_target(self):
        require(self.phase == 'construction' and self.remaining() >= 70, 'deadline')

    def pause(self, seconds, *, end=None):
        time.sleep(min(seconds, self.remaining(end=end)))
        self.remaining(end=end)

    def command(self, args, *, data=None, archive=None, cap=1024**2, end=None,
                allow_early_stdin_close=False):
        """Two-slot owner drains/reaps even when acquisition or cancellation fails."""
        require(type(cap) is int and 0 < cap <= MAX_SCRIPT, 'limit')
        require(data is None or archive is None, 'internal')
        require(type(allow_early_stdin_close) is bool, 'internal')
        if allow_early_stdin_close:
            require(type(args) is list and len(args) == 7
                    and args[:3] == ['docker', 'exec', '-i']
                    and type(args[3]) is str and re.fullmatch(r'[a-f0-9]{64}', args[3]) is not None
                    and args[4:] == ['pg_restore', '--list', '--verbose']
                    and data is not None and archive is None, 'internal')
        reap_end = min(self.end, self.end if end is None else end)
        self.remaining(reserve=2, end=reap_end)
        work_end = min(reap_end-2, time.monotonic()+43)
        try:
            return commands._command(args, work_end, data=data, archive=archive,
                stdout_cap=cap, reap_deadline=min(reap_end, work_end+2),
                child_owner=self.context.owner, allow_early_stdin_close=allow_early_stdin_close)
        except commands.CommandFailure as error:
            self.context.raise_if_fatal()
            reason = {'deadline': 'deadline', 'stdout_limit': 'limit',
                      'stderr_limit': 'limit'}.get(error.observation['kind'], 'child_failure')
            raise RestoreUnavailable(reason) from None

    def checked(self, args, *, input=None, stdin=None, stdout=subprocess.PIPE,
                capture_cap=1024**2, end=None):
        """Narrow adapter for existing owned-resource helpers; never subprocess.run."""
        raw = self.command(args, data=input, archive=stdin, cap=capture_cap, end=end)
        if stdout not in (subprocess.PIPE, subprocess.DEVNULL):
            require(hasattr(stdout, 'write'), 'internal')
            stdout.write(raw)
            self.remaining(end=end)
            raw = None
        elif stdout == subprocess.DEVNULL:
            raw = None
        return SimpleNamespace(stdout=raw, returncode=0)


class ResourceOwner:
    """Reconcile only nonce-owned resources; retain the private record on ambiguity."""
    label = 'talli.rf.identity.restore'

    def __init__(self, nonce, source, image, auth_image, budget):
        require(re.fullmatch(r'[a-f0-9]{32}', nonce) is not None
                and re.fullmatch(r'[a-f0-9]{64}', source) is not None
                and all(re.fullmatch(r'sha256:[a-f0-9]{64}', v) is not None
                        for v in (image, auth_image)), 'source_binding')
        self.nonce, self.source, self.budget = nonce, source, budget
        self.child_owner = budget.context.owner
        self.names = {'network': 'rf193_identity_net_'+nonce, 'volume': 'rf193_identity_data_'+nonce,
                      'init': 'rf193_identity_init_'+nonce, 'database': 'rf193_identity_db_'+nonce,
                      'auth': 'rf193_identity_auth_'+nonce}
        self.images = {'init': image, 'database': image, 'auth': auth_image}
        self.attempted, self.identities = [], {}
        self.directory = Path(tempfile.mkdtemp(prefix='talli-rf-restore-owner-'))
        os.chmod(self.directory, 0o700)
        self.record = self.directory/'owner.json'
        self._record()

    def _record(self):
        raw = ledger.canonical({'schema': 'rf1086-restore-owner-v1', 'nonce': self.nonce,
            'source': self.source, 'names': self.names, 'images': self.images,
            'attempted': self.attempted, 'identities': self.identities})
        temporary = self.directory/'owner.next'
        fd = os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary,self.record)
        finally:
            if temporary.exists():temporary.unlink()

    def acquire(self, kind, args, *, end):
        require(kind in self.names and kind not in self.attempted, 'internal')
        self.attempted.append(kind)
        self._record()
        self.budget.command(args, end=end, cap=4096)
        require(self.inspect(kind, end=end) is not None, 'source_binding')
        return self.identities[kind]

    def inspect(self, kind, *, end=None):
        resource = kind if kind in ('network','volume') else 'container'
        name = self.names[kind]
        args = ['docker', resource, 'ls'] + (['--all'] if resource == 'container' else [])
        args += ['--format', '{{json .Names}}' if resource == 'container' else '{{json .Name}}',
                 '--filter', 'name='+name]
        raw = self.budget.command(args, end=end, cap=4096)
        try:found = [json.loads(line) for line in raw.splitlines()]
        except Exception:raise RestoreUnavailable('cleanup_uncertain') from None
        require(all(type(item) is str for item in found), 'cleanup_uncertain')
        if name not in found:
            if resource!='volume' and kind in self.identities:
                # A renamed resource is not proof that our known identity went
                # away. Refuse rather than deleting an object with changed scope.
                identity_args=args[:-1]+['id='+self.identities[kind]]
                require(not self.budget.command(identity_args,end=end,cap=4096).strip(),
                        'cleanup_uncertain')
            return None
        raw = self.budget.command(['docker',resource,'inspect',name],end=end,cap=1024**2)
        try:
            rows = json.loads(raw); require(type(rows) is list and len(rows)==1,'cleanup_uncertain')
            value = rows[0]
            labels = value.get('Config',{}).get('Labels',{}) if resource=='container' else value.get('Labels',{})
            require(value.get('Name') == ('/'+name if resource=='container' else name)
                    and labels.get(self.label)==self.nonce, 'cleanup_uncertain')
            identity = value.get('Id') if resource != 'volume' else name
            if resource != 'volume':
                require(type(identity) is str and re.fullmatch(r'[a-f0-9]{64}',identity)
                        and identity != self.source, 'cleanup_uncertain')
            if resource == 'container':require(value.get('Image') == self.images[kind], 'cleanup_uncertain')
            if resource == 'network':require(value.get('Internal') is True,'cleanup_uncertain')
            require(kind not in self.identities or self.identities[kind]==identity,'cleanup_uncertain')
        except RestoreUnavailable:raise
        except Exception:raise RestoreUnavailable('cleanup_uncertain') from None
        self.identities[kind]=identity;self._record()
        return value

    def remove(self, kind):
        if self.inspect(kind) is None:
            # An unseen interrupted acquisition can still be pending in Docker.
            # Only a previously observed identity admits absence as removal proof.
            require(kind in self.identities, 'cleanup_uncertain')
            return
        resource = kind if kind in ('network','volume') else 'container'
        args = ['docker', resource, 'rm'] + (['-f'] if resource=='container' else [])
        self.budget.command(args+[self.identities[kind]],cap=4096)
        require(self.inspect(kind) is None,'cleanup_uncertain')

    def cleanup(self):
        errors=[]
        for kind in reversed(self.attempted):
            try:self.remove(kind)
            except BaseException as error:errors.append(error)
        if errors or self.child_owner.uncertain or any(s.acquiring or s.process is not None for s in self.child_owner.slots):
            raise RestoreUnavailable('cleanup_uncertain') from None
        require({p.name for p in self.directory.iterdir()}=={'owner.json'},'cleanup_uncertain')
        self.record.unlink();self.directory.rmdir()


def _substitutions(nonce, sequence):
    require(type(nonce) is str and re.fullmatch(r'[a-f0-9]{32}', nonce) is not None
            and type(sequence) is int and 0 <= sequence <= 8, 'delivery')
    return {'@N@': nonce, '@SS@': f'{sequence:02d}'}


def probe(nonce, sequence):
    values = _substitutions(nonce, sequence)
    return tuple(wire._substitute(wire.CONFIG['queries'][name].replace('S0', 'R1'),
                                 values).encode('ascii') for name in ('P', 'Q'))


def witness_request(nonce, sequence, role, pid):
    values = _substitutions(nonce, sequence)
    require(role in ('anchor', 'before', 'after') and type(pid) is int
            and 1 <= pid <= 2147483647, 'delivery')
    return wire._substitute(wire.CONFIG['queries']['W'].replace('S0', 'R1'),
        values | {'@R@': role, '@PID@': str(pid)}).encode('ascii')


def parse_session(payload, *, point, descriptor, baseline=None):
    # The three construction cuts retain the same exact session field rules;
    # post observations belong to their immediately preceding cut.
    mapped = ('cut', point[1]) if point[0] == 'post' else point
    try:
        return wire.parse_session(payload, point=mapped, descriptor=descriptor, baseline=baseline)
    except Exception:
        raise RestoreUnavailable('prefix_binding') from None


def parse_witness(payload, *, nonce, sequence, session, epoch_witness=None):
    try:
        return wire._witness_fields(wire._json(payload, 2000), session=session,
            query=probe(nonce, sequence)[1][:-1].decode('ascii'), epoch_witness=epoch_witness)
    except Exception:
        raise RestoreUnavailable('prefix_binding') from None


@dataclass(frozen=True, repr=False)
class ConstructionSchedule:
    descriptor: dict
    selections: tuple
    points: tuple


def construction_schedule(index, *, deadline):
    """Derive three construction cuts from the complete emitter, never old receipts."""
    require(type(index) is ledger.RestoreIndex and time.monotonic() < deadline, 'archive_profile')
    core, hook = index.core, index.pre_acl
    selected = {row['kind']: (row, session) for row, session in
                zip(core.selected, core.session_references['cuts'], strict=True)}
    require(set(selected) == {'graphql_schema', 'graphql_public_schema', 'pg_net_extension'},
            'archive_profile')
    schema = max((selected[k] for k in ('graphql_schema', 'graphql_public_schema')),
                 key=lambda item: item[0]['cut'])
    net = selected['pg_net_extension']
    selections = ({'kind': 'Is', 'cut': schema[0]['cut']},
                  {'kind': 'In', 'cut': net[0]['cut']},
                  {'kind': 'acl', 'cut': hook['cut']})
    # Detached copies: the frozen scheduling value cannot alias emitter lists.
    descriptor = {'database': 'postgres',
        'epochs': [list(row) for row in core.session_references['epochs']],
        'cuts': deepcopy([schema[1], net[1], hook['session']])}
    require(len(descriptor['epochs']) in (2, 3), 'archive_profile')
    points = [(('anchor', i), row[0]) for i, row in enumerate(descriptor['epochs'])]
    for i, selection in enumerate(selections):
        cut, epoch = selection['cut'], descriptor['cuts'][i][0]
        require(type(cut) is int and 0 < cut < core.script['bytes']
                and 0 < epoch < len(descriptor['epochs'])
                and descriptor['epochs'][epoch][1] <= cut
                and (epoch+1 == len(descriptor['epochs']) or cut < descriptor['epochs'][epoch+1][0]),
                'archive_profile')
        points.extend(((('cut', i), cut), (('post', i), cut)))
    require(len({v['cut'] for v in selections}) == 3
            and hook['cut'] > max(schema[0]['cut'], net[0]['cut']), 'archive_profile')
    return ConstructionSchedule(descriptor, selections, tuple(sorted(points, key=lambda item: item[1])))


def bounded_hash(raw, *, deadline, cap):
    require(type(raw) is bytes and 0 < len(raw) <= cap, 'limit')
    hashed = hashlib.sha256()
    for offset in range(0, len(raw), 65536):
        require(time.monotonic() < deadline, 'deadline')
        hashed.update(memoryview(raw)[offset:offset+65536])
    require(time.monotonic() < deadline, 'deadline')
    return {'bytes': len(raw), 'sha256': hashed.hexdigest()}


def generate_sql(source, archive, *, budget, end=None):
    """Read-only binary execution in the verified source image; stdin is a pipe."""
    require(type(source) is str and re.fullmatch(r'[a-f0-9]{64}', source) is not None,
            'source_binding')
    require(type(archive) is bytes and 0 < len(archive) <= MAX_ARCHIVE, 'limit')
    return budget.command(['docker', 'exec', '-i', source, 'sh', '-c', OFFLINE_RESTORE],
                          data=archive, cap=MAX_SCRIPT, end=end)


def bind_tools(container, *, budget, end=None):
    require(type(container) is str and re.fullmatch(r'[a-f0-9]{64}', container) is not None,
            'source_binding')
    result = {}
    for name in ('pg_restore', 'psql'):
        raw = budget.command(['docker', 'exec', container, 'sh', '-c',
                              TOOL_COMMAND.replace('@TOOL@', name)], cap=4096, end=end)
        match = re.fullmatch(name.encode()+rb' \(PostgreSQL\) (17\.6)\n([a-f0-9]{64})\n', raw)
        require(match is not None, 'source_binding')
        result[name] = {'version': match[1].decode('ascii'), 'sha256': match[2].decode('ascii')}
    return result


def bounded_file(path, *, cap):
    """Read at most one sentinel byte beyond an admitted local input size."""
    require(type(cap) is int and 0 < cap <= MAX_SCRIPT, 'limit')
    with Path(path).open('rb') as stream:
        value = stream.read(cap+1)
    require(0 < len(value) <= cap, 'limit')
    return value


def fixed_snapshot_statement():
    pinned=wire.CONFIG['queries']['catalog']
    statement=bounded_file(Path(__file__).with_name('rf1086_catalog_causal.sql'),cap=pinned['bytes'])
    require(len(statement)==pinned['bytes'] and hashlib.sha256(statement).hexdigest()==pinned['sha256'],
            'source_binding')
    return statement


def source_fixed_snapshot(source, *, budget):
    require(type(source) is str and re.fullmatch('[a-f0-9]{64}',source),'source_binding')
    return budget.command(['docker','exec','-i',source,'psql','-U','supabase_admin',
        '--dbname','postgres','-XqAt','-v','ON_ERROR_STOP=1'],data=fixed_snapshot_statement(),cap=32768)


@dataclass(frozen=True, repr=False)
class PreparedRestore:
    script: bytes
    index: ledger.RestoreIndex
    plan: object
    roles: object
    tools: dict
    archive_binding: dict
    roles_binding: dict
    code_binding: dict


DIAGNOSTIC_PREFIX = 'owned_identity_restore_pre_target_diagnostic '
DIAGNOSTIC_SCHEMA = 'rf1086-restore-pre-target-diagnostic-v1'
DIAGNOSTIC_STEPS = frozenset(('source_fingerprint', 'source_roles', 'source_metadata_query',
    'source_metadata_decode', 'source_snapshot', 'source_snapshot_bind', 'source_preload',
    'source_roles_dump', 'source_archive_dump', 'source_recheck', 'prepare_headroom',
    'archive_hash', 'roles_hash', 'role_program', 'tool_probe', 'archive_list', 'sql_generation',
    'raw_metadata', 'archive_profile', 'restore_ledger', 'metadata_index', 'acl_compile',
    'code_bindings', 'target_admission', 'unclassified'))
DIAGNOSTIC_METADATA_STEPS = frozenset(('source_metadata_decode', 'source_snapshot_bind',
    'role_program', 'metadata_index', 'acl_compile'))
DIAGNOSTIC_MODULES = dict(zip(('control', 'metadata', 'ledger', 'lexical', 'raw_toc',
    'identifiers', 'identity', 'capture', 'difference', 'semantics'),
    ('rf1086_restore_control', 'rf1086_restore_metadata', 'rf1086_sql_ledger',
     'rf1086_sql_lexical', 'rf1086_raw_toc', 'rf1086_sql_identifiers',
     'rf1086_identity_restore', 'rf1086_catalog_causal_capture',
     'rf1086_catalog_difference', 'rf1086_catalog_semantics'), strict=True))
DIAGNOSTIC_RAW_REASONS = frozenset(('archive_input_invalid', 'archive_profile_unsupported',
    'deadline_exhausted', 'deadline_invalid', 'decimal_invalid', 'decimal_range_invalid',
    'dependency_count_exceeded', 'description_invalid', 'entry_id_or_dumper_invalid',
    'header_string_empty', 'integer_invalid', 'length_invalid', 'list_entries_mismatch',
    'list_header_invalid', 'list_header_mismatch', 'list_input_invalid', 'list_timestamp_invalid',
    'metadata_oversized', 'metadata_truncated', 'offset_invalid', 'offset_out_of_range',
    'relkind_unsupported', 'rendered_list_oversized', 'required_string_missing', 'section_invalid',
    'string_encoding_invalid', 'string_length_invalid', 'string_nul', 'timestamp_invalid',
    'toc_count_invalid', 'version_multiline', 'with_oids_unsupported'))


def _diagnostic_keys(value, keys):
    require(type(value) is dict and value.keys() == set(keys), 'internal')


def _diagnostic_hash(value):
    require(type(value) is str and len(value) == 64
            and re.fullmatch('[0-9a-f]{64}', value) is not None, 'internal')


def _diagnostic_inputs(value):
    _diagnostic_keys(value, ('source', 'archive', 'roles', 'scriptBytes', 'script', 'archiveRows'))
    if value['source'] is not None:
        _diagnostic_keys(value['source'], ('roles', 'catalog', 'auth', 'companyMemberships'))
        for digest in value['source'].values(): _diagnostic_hash(digest)
    for name, cap in (('archive', MAX_ARCHIVE), ('roles', MAX_ROLES), ('script', MAX_SCRIPT)):
        bound = value[name]
        if bound is not None:
            _diagnostic_keys(bound, ('bytes', 'sha256'))
            require(type(bound['bytes']) is int and 1 <= bound['bytes'] <= cap, 'internal')
            _diagnostic_hash(bound['sha256'])
    for name, cap in (('scriptBytes', MAX_SCRIPT), ('archiveRows', raw_toc.MAX_ROWS)):
        require(value[name] is None or type(value[name]) is int and 1 <= value[name] <= cap, 'internal')
    require(value['script'] is None or value['script']['bytes'] == value['scriptBytes'], 'internal')


def _diagnostic_reason(component, reason, step):
    # No module import on the exception path. The compiler is already loaded
    # before any operation that can emit its typed refusal.
    metadata = sys.modules.get('rf1086_restore_metadata')
    if type(component) is not str or type(reason) is not str or len(reason) > 64:
        return False
    return ((component == 'control' and reason in REASONS)
        or (component == 'metadata' and step in DIAGNOSTIC_METADATA_STEPS
            and reason in getattr(metadata, 'REASONS', ()))
        or (component == 'raw_toc' and step == 'raw_metadata' and reason in ('deadline', 'metadata'))
        or (component == 'ledger' and step == 'restore_ledger' and reason in ledger.REASON_STAGES)
        or (component == 'lexical' and step == 'restore_ledger'
            and reason in ('deadline', 'limit', 'binding', 'profile', 'lexical'))
        or (component == 'identifiers' and step == 'restore_ledger' and reason == 'profile')
        or (component == 'unknown' and reason == 'internal'))


def validate_pre_target_diagnostic(value):
    """Closed failure observation, never a construction or Fsql admission."""
    _diagnostic_keys(value, ('schema', 'step', 'component', 'reason', 'inputs', 'ledger',
                             'lexicalLimit', 'location'))
    require(value['schema'] == DIAGNOSTIC_SCHEMA and type(value['step']) is str
            and value['step'] in DIAGNOSTIC_STEPS, 'internal')
    require(_diagnostic_reason(value['component'], value['reason'], value['step']), 'internal')
    inputs = value['inputs']; _diagnostic_inputs(inputs)
    nested = value['ledger']
    if nested is not None:
        require(value['step'] in ('raw_metadata', 'restore_ledger'), 'internal')
        _diagnostic_keys(nested, ('schema', 'status', 'reason', 'stage', 'context'))
        require(nested['status'] == 'unavailable' and type(nested['reason']) is str
                and type(nested['stage']) is str, 'internal')
        require(nested['stage'] in (('metadata',) if value['step'] == 'raw_metadata'
                                   else ledger.STAGES), 'internal')
        context = nested['context']
        _diagnostic_keys(context, ('rowIndex', 'dumpId', 'descriptor', 'offset', 'limit'))
        require(context['limit'] is None, 'internal')
        for name in ('rowIndex', 'dumpId', 'offset'):
            require(context[name] is None or type(context[name]) is int, 'internal')
        require(context['descriptor'] is None or type(context['descriptor']) is str
                and context['descriptor'] in (*raw_toc.DESCRIPTORS, 'unknown'), 'internal')
        ledger.validate_receipt(nested, fsql=None)
        expected = value['reason']
        if expected not in ledger.REASON_STAGES or nested['stage'] not in ledger.REASON_STAGES[expected]:
            expected = 'internal'
        require(nested['reason'] == expected, 'internal')
        require(context['rowIndex'] is None or inputs['archiveRows'] is None
                or context['rowIndex'] < inputs['archiveRows'], 'internal')
        require(context['offset'] is None or inputs['scriptBytes'] is not None
                and context['offset'] <= inputs['scriptBytes'], 'internal')
    detail = value['lexicalLimit']
    if detail is not None:
        require(value['component'] == 'lexical' and value['reason'] == 'limit'
                and nested is not None and nested['stage'] == 'lexical'
                and inputs['scriptBytes'] is not None, 'internal')
        ledger.lexical.validate_limit(detail, input_bytes=inputs['scriptBytes'])
    location = value['location']
    if location is not None:
        _diagnostic_keys(location, ('module', 'line', 'depth', 'edge'))
        require(type(location['module']) is str and location['module'] in DIAGNOSTIC_MODULES
                and type(location['line']) is int and 1 <= location['line'] <= 8192
                and type(location['depth']) is int and 0 <= location['depth'] <= 2
                and type(location['edge']) is str
                and location['edge'] in (('primary',) if location['depth'] == 0
                    else ('cause', 'context', 'suppressed_context')), 'internal')
    require(len(DIAGNOSTIC_PREFIX) + len(ledger.canonical(value)) + 1 <= 4096, 'internal')
    return value


def _diagnostic_location(error, budget):
    """Structural, bounded source attribution; no messages, locals or source I/O."""
    try:
        paths = {os.path.join(os.path.dirname(os.path.abspath(__file__)), name+'.py'): key
                 for key, name in DIAGNOSTIC_MODULES.items()}
        skips = {module.require.__code__ for module in
                 (sys.modules[__name__], ledger, ledger.lexical, raw_toc, ledger.identifiers)}
        metadata = sys.modules.get('rf1086_restore_metadata')
        if metadata is not None and hasattr(metadata, 'require'):
            skips.add(metadata.require.__code__)
        structural = lambda name, value: BaseException.__dict__[name].__get__(value, type(value))
        seen, frames, count, selected, edge = set(), set(), 0, None, 'primary'
        for depth in range(3):
            budget.remaining()
            if id(error) in seen: return None
            seen.add(id(error))
            trace = structural('__traceback__', error)
            candidate = None
            while trace is not None:
                budget.remaining()
                if count == 64 or id(trace) in frames: return None
                frames.add(id(trace)); count += 1
                code, line = trace.tb_frame.f_code, trace.tb_lineno
                module = paths.get(code.co_filename)
                if module is not None and code not in skips:
                    if type(line) is not int or not 1 <= line <= 8192: return None
                    candidate = {'module': module, 'line': line, 'depth': depth, 'edge': edge}
                trace = trace.tb_next
            if candidate is not None: selected = candidate
            cause = structural('__cause__', error)
            context = structural('__context__', error)
            suppressed = structural('__suppress_context__', error)
            error = cause if cause is not None else context
            if error is None: return selected
            edge = 'cause' if cause is not None else 'suppressed_context' if suppressed else 'context'
        return None
    except Exception:
        return None


def _diagnostic_classify(error, step):
    known = ((RestoreUnavailable, 'control'), (ledger.Unavailable, 'ledger'),
             (ledger.lexical.Unavailable, 'lexical'), (raw_toc.Unavailable, 'raw_toc'),
             (ledger.identifiers.Unavailable, 'identifiers'))
    metadata = sys.modules.get('rf1086_restore_metadata')
    known += ((getattr(metadata, 'MetadataUnavailable', None), 'metadata'),)
    component = next((name for kind, name in known if type(error) is kind), 'unknown')
    if component == 'unknown': return 'unknown', 'internal'
    fields = BaseException.__dict__['__dict__'].__get__(error, type(error))
    reason = fields.get('reason')
    if component == 'identifiers': reason = 'profile'
    elif type(reason) is not str or len(reason) > 64: return 'unknown', 'internal'
    elif component == 'raw_toc':
        if reason not in DIAGNOSTIC_RAW_REASONS: return 'unknown', 'internal'
        reason = 'deadline' if reason in ('deadline_invalid', 'deadline_exhausted') else 'metadata'
    elif component == 'lexical':
        if reason not in ledger.lexical.REASONS: return 'unknown', 'internal'
        reason = reason if reason in ('deadline', 'limit', 'binding', 'profile') else 'lexical'
    return (component, reason) if _diagnostic_reason(component, reason, step) else ('unknown', 'internal')


def _diagnostic_cancel(budget, error, primary):
    owner = budget.context.owner
    if owner.primary is None: owner.primary = primary
    owner._cancel(error)


class PreTargetDiagnostic:
    """One invocation's first propagated denial; never retains exception/raw data."""
    def __init__(self, budget):
        self.budget, self.enabled, self.attempted, self.failure = budget, True, False, None
        self.inputs = dict.fromkeys(('source', 'archive', 'roles', 'scriptBytes', 'script', 'archiveRows'))

    def remember(self, name, value):
        try:
            proposed = self.inputs | {name: value}
            _diagnostic_inputs(proposed)
            self.inputs = deepcopy(proposed)
        except Exception:
            pass  # An invalid observation is unavailable, never a new refusal.

    def disable(self):
        self.enabled = False

    def _capture(self, error, step, walk):
        safe_step = step if type(step) is str and step in DIAGNOSTIC_STEPS else 'unclassified'
        value = {'schema': DIAGNOSTIC_SCHEMA, 'step': safe_step, 'component': 'unknown',
            'reason': 'internal', 'inputs': deepcopy(self.inputs), 'ledger': None,
            'lexicalLimit': None, 'location': None}
        # Install the closed fallback before attempting optional projection.
        self.failure = value
        projected = deepcopy(value)
        projected['component'], projected['reason'] = _diagnostic_classify(error, safe_step)
        if walk is not None and safe_step in ('raw_metadata', 'restore_ledger'):
            stage, reason = walk.stage, projected['reason']
            if reason not in ledger.REASON_STAGES or stage not in ledger.REASON_STAGES[reason]:
                reason = 'internal'
            projected['ledger'] = ledger.unavailable(reason, stage, dict(walk.context))
            if projected['component'] == 'lexical' and reason == 'limit' and stage == 'lexical':
                projected['lexicalLimit'] = BaseException.__dict__['__dict__'].__get__(error, type(error)).get('limit')
        projected['location'] = _diagnostic_location(error, self.budget)
        validate_pre_target_diagnostic(projected)
        self.failure = deepcopy(projected)

    @contextmanager
    def operation(self, step, *, walk=None):
        try:
            yield
        except Exception as primary:
            if self.enabled and self.failure is None:
                try:
                    with self.budget.context.owner.deferred(primary):
                        self._capture(primary, step, walk)
                except BaseException as secondary:
                    if not isinstance(secondary, Exception):
                        _diagnostic_cancel(self.budget, secondary, primary)
            raise

    def publish(self, *, primary):
        if self.attempted or self.failure is None: return
        self.attempted = True
        owner = self.budget.context.owner
        original = owner.original if isinstance(owner, _UnwindOwner) else owner
        if owner.cancelled or owner.uncertain or original.cancelled or original.uncertain: return
        try:
            with owner.deferred(primary), io_deadline(self.budget):
                validate_pre_target_diagnostic(self.failure)
                line = DIAGNOSTIC_PREFIX + ledger.canonical(self.failure).decode('ascii') + '\n'
                sys.stderr.write(line)
                sys.stderr.flush()
        except BaseException as error:
            if not isinstance(error, Exception): _diagnostic_cancel(self.budget, error, primary)


def _diagnostic_operation(diagnostic, step, *, walk=None):
    return nullcontext() if diagnostic is None else diagnostic.operation(step, walk=walk)


def _diagnostic_remember(diagnostic, name, value):
    if diagnostic is not None: diagnostic.remember(name, value)


def prepare_archive(source, *, archive, roles, metadata, budget, diagnostic=None):
    """Complete generation, attribution and source admission before any target."""
    import rf1086_restore_metadata as compiler
    end = budget.end - 70
    with _diagnostic_operation(diagnostic, 'prepare_headroom'):
        budget.remaining(end=end)
    with _diagnostic_operation(diagnostic, 'archive_hash'):
        archive_binding = bounded_hash(archive, deadline=end, cap=MAX_ARCHIVE)
    _diagnostic_remember(diagnostic, 'archive', archive_binding)
    with _diagnostic_operation(diagnostic, 'roles_hash'):
        roles_binding = bounded_hash(roles, deadline=end, cap=MAX_ROLES)
    _diagnostic_remember(diagnostic, 'roles', roles_binding)
    with _diagnostic_operation(diagnostic, 'role_program'):
        role_program = compiler.role_program(roles, metadata, deadline=end)
    with _diagnostic_operation(diagnostic, 'tool_probe'):
        tools = bind_tools(source, budget=budget, end=end)
    with _diagnostic_operation(diagnostic, 'archive_list'):
        listing = budget.command(['docker', 'exec', '-i', source, 'pg_restore', '--list', '--verbose'],
                                 data=archive, cap=2*1024**2, end=end, allow_early_stdin_close=True)
    with _diagnostic_operation(diagnostic, 'sql_generation'):
        script = generate_sql(source, archive, budget=budget, end=end)
    _diagnostic_remember(diagnostic, 'scriptBytes', len(script))
    with _diagnostic_operation(diagnostic, 'raw_metadata'):
        walk_budget = ledger.Budget(end)
    with _diagnostic_operation(diagnostic, 'raw_metadata', walk=walk_budget):
        walk_budget.phase('metadata')
        raw_archive, _ = raw_toc.inspect(archive, listing, walk_budget.deadline)
    _diagnostic_remember(diagnostic, 'archiveRows', len(raw_archive.entries))
    version = rb'17\.6(?: \([^\r\n]{1,128}\))?'
    with _diagnostic_operation(diagnostic, 'archive_profile'):
        require(raw_archive.database == b'postgres' and re.fullmatch(version, raw_archive.remote_version)
                and re.fullmatch(version, raw_archive.dump_version), 'archive_profile')
    with _diagnostic_operation(diagnostic, 'restore_ledger', walk=walk_budget):
        index = ledger.verify_restore_core(script, raw_archive, catalog=metadata.selected_catalog,
                                           budget=walk_budget)
    _diagnostic_remember(diagnostic, 'script', index.core.script)
    with _diagnostic_operation(diagnostic, 'metadata_index'):
        repair_index = compiler.restore_metadata_index(script, raw_archive, index, metadata, deadline=end)
    with _diagnostic_operation(diagnostic, 'acl_compile'):
        plan = compiler.compile_plan(metadata, script=script, archive=raw_archive,
                                     index=repair_index, deadline=end)
    code = {}
    with _diagnostic_operation(diagnostic, 'code_bindings'):
        for name in ('rf1086_restore_control.py','rf1086_restore_metadata.py','rf1086_identity_restore.py',
                     'rf1086_sql_ledger.py','rf1086_sql_lexical.py','rf1086_sql_identifiers.py','rf1086_raw_toc.py',
                     'rf1086_s0_control.py','rf1086_s0_protocol.py','rf1086_catalog_semantics.py',
                     'rf1086_catalog_causal_capture.py','rf1086_catalog_causal.sql','rf1086_catalog_difference.py'):
            code[name] = bounded_hash(bounded_file(Path(__file__).with_name(name),cap=256*1024),deadline=end,cap=256*1024)
    with _diagnostic_operation(diagnostic, 'target_admission'):
        budget.before_target()
    return PreparedRestore(script, index, plan, role_program, tools, archive_binding, roles_binding,code)


def stream_restore(target, *, script, index, plan, budget, end):
    """One writer, three source-defined interventions and checked postconditions."""
    import rf1086_restore_metadata as metadata
    schedule = construction_schedule(index, deadline=end)
    # Refuse mutable or stale caller references before acquiring either child.
    require(bounded_hash(script, deadline=end, cap=MAX_SCRIPT) == index.core.script,
            'source_binding')
    require(plan.pre_acl == schedule.selections[2]['cut']
            and plan.cuts == {'Is': schedule.selections[0]['cut'], 'In': schedule.selections[1]['cut']},
            'source_binding')
    statement = fixed_snapshot_statement()
    before, mutations = {}, {}

    def request(point, sequence, pid):
        database = 'template1' if point == ('anchor', 0) else 'postgres'
        args = wire.observer_argv(target, database)
        if point[0] == 'anchor':
            data = witness_request(nonce, sequence, 'anchor', pid)
        else:
            query = metadata.METADATA_SQL if point[1] == 2 else statement
            data = (witness_request(nonce, sequence, 'before', pid) + query
                    + witness_request(nonce, sequence, 'after', pid))
        return args, data

    def project(raw, selection):
        if selection['kind'] == 'acl':
            return metadata.decode_observation(raw, deadline=work_end)
        value = wire._json(raw, 32768)
        return capture._validate_snapshot(value, None)

    def complete(exchange):
        point = tuple(exchange['point'])
        if point[0] == 'anchor':
            return None
        kind = schedule.selections[point[1]]['kind']
        observed = exchange['catalog']
        if point[0] == 'cut':
            before[kind] = observed
            mutation = (metadata.pre_acl(plan, observed, deadline=work_end) if kind == 'acl'
                        else metadata.prefix_mutation(plan, kind, observed, deadline=work_end))
            mutations[kind] = mutation
            return mutation.sql
        if kind == 'acl':
            metadata.post_acl(plan, before[kind], observed, mutations[kind], deadline=work_end)
        else:
            metadata.prefix_postcheck(plan, kind, before[kind], observed, deadline=work_end)
        return None

    import secrets
    nonce = secrets.token_hex(16)
    reap_end = min(end, budget.end, time.monotonic()+45)
    work_end = reap_end-2
    budget.remaining(reserve=2, end=reap_end)
    try:
        result = pipes.restore_transport(script, schedule.descriptor, schedule.selections,
            context=budget.context, nonce=nonce, writer_args=wire.writer_argv(target),
            observer_request=request, parse_session=parse_session, parse_witness=parse_witness,
            project=project, probe=probe, points=schedule.points, work_end=work_end,
            reap_end=reap_end, exchange_complete=complete)
    except pipes.ControlFailure as error:
        raise RestoreUnavailable('deadline' if error.reason == 'deadline' else 'delivery') from None
    require(result['delivery']['original'] == index.core.script, 'delivery')
    return result, mutations


def construction_receipt(*, budget, prepared, delivery, mutations, source, target, image,
                         before, recovered, cleanup_complete, source_postcheck, business_complete,
                         reason=None):
    """Explicit safe projection. Private catalogs/session witnesses never escape."""
    def identity_hash(value):
        return hashlib.sha256(value.encode()).hexdigest() if type(value) is str else None
    def sized(value, cap):
        require(type(value) is dict and set(value)=={'bytes','sha256'}
                and type(value['bytes']) is int and 0 <= value['bytes'] <= cap
                and type(value['sha256']) is str and re.fullmatch('[a-f0-9]{64}',value['sha256']), 'internal')
        return dict(value)
    def io(value, stdout_cap, stderr_cap):
        require(type(value) is dict and set(value)=={'stdoutBytes','stderrBytes','stdoutEnd','stderrEnd','exitCode','reap'}
                and type(value['stdoutBytes']) is int and 0 <= value['stdoutBytes'] <= stdout_cap
                and type(value['stderrBytes']) is int and 0 <= value['stderrBytes'] <= stderr_cap
                and value['stdoutEnd']==value['stderrEnd']=='eof'
                and type(value['exitCode']) is int and value['exitCode']==0 and value['reap']=='waited', 'internal')
        return dict(value)
    counts = prepared.plan.counts if prepared is not None else None
    if counts is not None:
        require(set(counts)=={'objects','candidates','archiveOnly','unmodeled','statements','defaultAcls'}
                and all(type(v) is int and 0 <= v <= 32768 for v in counts.values()),'internal')
    complete = (prepared is not None and delivery is not None and recovered == before
                and before is not None and cleanup_complete and source_postcheck)
    fingerprints = {}
    for name,value in (('source',before),('target',recovered)):
        if value is not None:
            require(type(value) is dict and set(value)=={'roles','catalog','auth','companyMemberships'}
                and all(type(v) is str and re.fullmatch('[a-f0-9]{64}',v) for v in value.values()),'internal')
        fingerprints[name]=value
    observations = public_delivery = None
    if delivery is not None:
        require(type(delivery) is dict and set(delivery)=={'exchanges','delivery'}
                and type(delivery['exchanges']) is list and len(delivery['exchanges']) in (8,9),'internal')
        observations=[io(exchange['observer'],MAX_METADATA,0) for exchange in delivery['exchanges']]
        d=delivery['delivery'];require(set(d)=={'original','probes','frames','writer','mutation'},'internal')
        require(d['frames']==[len(observations),len(observations)],'internal')
        mutation=d['mutation'];require(set(mutation)=={'bytes','sha256','exchanges'},'internal')
        require(type(mutation['exchanges']) is list and len(mutation['exchanges'])==3,'internal')
        exchanges=[]
        for m in mutation['exchanges']:
            require(type(m) is dict and set(m)=={'point','bytes','sha256'}
                    and m['point'] in (['cut',0],['cut',1],['cut',2]),'internal')
            exchanges.append({'point':list(m['point']),**sized({k:m[k] for k in ('bytes','sha256')},MAX_ROLES)})
        require(len({m['point'][1] for m in exchanges})==3,'internal')
        public_delivery={'original':sized(d['original'],MAX_SCRIPT),'probes':sized(d['probes'],16384),
            'frames':list(d['frames']),'writer':io(d['writer'],1024**2,65536),
            'mutation':sized({k:mutation[k] for k in ('bytes','sha256')},MAX_ROLES)|{'exchanges':exchanges}}
    bindings=code=None
    if prepared is not None:
        p=prepared.plan.binding
        require(type(p) is dict and set(p)=={'profile','source','fixedSnapshot','catalogObservation','roleObservation','archive','script','index','supplement'}
                and type(p['profile']) is str and re.fullmatch('[a-f0-9]{64}',p['profile']),'internal')
        plan_binding={'profile':p['profile'],**{key:sized(p[key],cap) for key,cap in
            (('source',MAX_METADATA),('fixedSnapshot',32768),('catalogObservation',MAX_METADATA),
             ('roleObservation',MAX_ROLES),('archive',MAX_ARCHIVE),('script',MAX_SCRIPT),('index',MAX_METADATA),('supplement',MAX_ROLES))}}
        require(type(prepared.tools) is dict and set(prepared.tools)=={'pg_restore','psql'},'internal')
        for tool in prepared.tools.values():
            require(type(tool) is dict and set(tool)=={'version','sha256'} and tool['version']=='17.6'
                    and type(tool['sha256']) is str and re.fullmatch('[a-f0-9]{64}',tool['sha256']),'internal')
        require(type(prepared.code_binding) is dict and len(prepared.code_binding)<=32
                and all(type(k) is str and re.fullmatch(r'rf1086_[a-z0-9_]+\.(py|sql)',k) for k in prepared.code_binding),'internal')
        code={key:sized(value,256*1024) for key,value in prepared.code_binding.items()}
        bindings={'archive':sized(prepared.archive_binding,MAX_ARCHIVE),'roles':sized(prepared.roles_binding,MAX_ROLES),
            'script':sized(prepared.index.core.script,MAX_SCRIPT),'plan':plan_binding,'tools':deepcopy(prepared.tools)}
    public_mutations=None
    if mutations is not None:
        require(type(mutations) is dict and set(mutations)=={'Is','In','acl'},'internal')
        public_mutations={}
        for kind,value in mutations.items():
            require(type(value.sql) is bytes and len(value.sql)<=(MAX_ROLES if kind=='acl' else 2048)
                    and all(type(v) is int and 0 <= v <= 8192 for v in (value.applied,value.noop)),'internal')
            public_mutations[kind]={'applied':value.applied,'noop':value.noop,
                'bytes':len(value.sql),'sha256':hashlib.sha256(value.sql).hexdigest()}
    hooks=None
    if prepared is not None:
        require(type(prepared.plan.cuts) is dict and set(prepared.plan.cuts)=={'Is','In'}
                and all(type(v) is int and 0 < v < MAX_SCRIPT for v in prepared.plan.cuts.values())
                and type(prepared.plan.pre_acl) is int and max(prepared.plan.cuts.values()) < prepared.plan.pre_acl < MAX_SCRIPT,'internal')
        hooks=prepared.plan.cuts|{'acl':prepared.plan.pre_acl}
    require(all(type(v) is bool for v in (cleanup_complete,source_postcheck,business_complete)),'internal')
    elapsed={**budget.phase_elapsed,budget.phase:time.monotonic()-budget.phase_started}
    require(set(elapsed)<=set(PHASES) and all(type(v) in (int,float) and math.isfinite(v) and 0 <= v <= 180 for v in elapsed.values()),'internal')
    # Engine-owned values have a closed finite shape; copy only the three public
    # byte streams and known exit/reap facts, not its private exchange payloads.
    result = {'schema':SCHEMA,'status':'constructed' if complete else 'unavailable',
        'reason':None if complete else reason if reason in REASONS else 'internal',
        'configurationSha256':hashlib.sha256(ledger.canonical(CONFIG)).hexdigest(),
        'code':code,'bindings':bindings,
        'identities':{'source':identity_hash(source),'target':identity_hash(target),'image':identity_hash(image)},
        'counts':counts,'hooks':hooks,
        'mutations':public_mutations,
        'delivery':public_delivery,'observers':observations,'fingerprints':fingerprints,
        'cleanupComplete':bool(cleanup_complete),'identitySourcePostcheck':bool(source_postcheck),
        'businessComplete':bool(business_complete),'outerBusinessPostchecks':None,
        'phaseElapsedSeconds':elapsed}
    raw=ledger.canonical(result)
    require(len(raw)<=16384,'limit')
    return raw.decode('ascii')

# Shared I/O deadline adapters
# These adapters borrow a RecoveryBudget; none enters a phase or creates a clock.
import asyncio as _io_asyncio
from contextvars import ContextVar as _IOContextVar
from functools import wraps as _io_wraps
import signal as _io_signal
import threading as _io_threading

_IO_BUDGET = _IOContextVar('rf1086_recovery_io_budget', default=None)
_IO_CONNECTIONS = _IOContextVar('rf1086_recovery_owned_connections', default=())


def _close_expired_connections(budget, primary):
    # Explicit factory acquisitions only; never touch a process-global driver.
    # libpq close abandons the owned session without a rollback round trip.
    for connection in reversed(_IO_CONNECTIONS.get()):
        if connection.budget is budget:
            connection.abort(primary)


@contextmanager
def _connection_signals(budget):
    """Close before libpq sees cancellation and enters its own cancel/rollback wait."""
    saved = []
    try:
        for number in (_io_signal.SIGTERM, _io_signal.SIGINT):
            previous = _io_signal.getsignal(number)
            def cancelled(signum, frame, previous=previous):
                if previous == _io_signal.SIG_IGN:
                    return
                if callable(previous):
                    try:
                        previous(signum, frame)
                    except BaseException as primary:
                        _close_expired_connections(budget, primary)
                        raise
                    return  # An existing acquisition owner deferred this signal.
                primary = KeyboardInterrupt()
                _close_expired_connections(budget, primary)
                raise primary
            saved.append((number, previous))
            _io_signal.signal(number, cancelled)
        yield
    finally:
        for number, previous in reversed(saved):
            _io_signal.signal(number, previous)


def current_budget(budget=None):
    return budget if budget is not None else _IO_BUDGET.get()


@contextmanager
def budget_scope(budget):
    token = _IO_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _IO_BUDGET.reset(token)


def io_timeout(budget=None, maximum=15, *, reserve=0):
    budget = current_budget(budget)
    return maximum if budget is None else min(maximum, budget.remaining(reserve=reserve))


@contextmanager
def io_deadline(budget=None):
    """Bound synchronous waits and positive commit; no driver monkeypatch.

    Async callers also use this main-thread guard because asyncio cancellation
    cannot interrupt synchronous psycopg or file operations inside a coroutine.
    Existing/nested earlier alarms retain their original deadline and handler.
    """
    budget = current_budget(budget)
    if budget is None:
        yield
        return
    require(_io_threading.current_thread() is _io_threading.main_thread(), 'deadline')
    started = time.monotonic()
    duration = budget.remaining()
    previous = _io_signal.getsignal(_io_signal.SIGALRM)
    prior, interval = _io_signal.getitimer(_io_signal.ITIMER_REAL)
    earlier = prior > 0 and prior <= duration
    def expired(signum, frame):
        if earlier and callable(previous):
            try:
                previous(signum, frame)
            except BaseException as primary:
                _close_expired_connections(budget, primary)
                raise
        primary = RestoreUnavailable('deadline')
        _close_expired_connections(budget, primary)
        raise primary
    expired._rf_io_deadline = True
    _io_signal.signal(_io_signal.SIGALRM, expired)
    _io_signal.setitimer(_io_signal.ITIMER_REAL, min(duration, prior) if prior else duration)
    try:
        yield
        budget.remaining()
    finally:
        _io_signal.setitimer(_io_signal.ITIMER_REAL, 0)
        _io_signal.signal(_io_signal.SIGALRM, previous)
        if prior:
            left = prior - (time.monotonic() - started)
            if left > 0 or not getattr(previous, '_rf_io_deadline', False):
                _io_signal.setitimer(_io_signal.ITIMER_REAL, max(0.000001, left), interval)


def budgeted_sync(function):
    @_io_wraps(function)
    def call(*args, budget=None, **kwargs):
        selected = current_budget(budget)
        with budget_scope(selected), io_deadline(selected):
            return function(*args, **kwargs)
    return call


def budgeted_async(function):
    @_io_wraps(function)
    async def call(*args, budget=None, **kwargs):
        selected = current_budget(budget or (getattr(args[0], 'budget', None) if args else None))
        with budget_scope(selected), io_deadline(selected):
            if selected is None:
                return await function(*args, **kwargs)
            timeout = _io_asyncio.timeout(selected.remaining())
            try:
                async with timeout:
                    return await function(*args, **kwargs)
            except TimeoutError:
                if timeout.expired():
                    raise RestoreUnavailable('deadline') from None
                raise
    return call


def deadline_dsn(dsn, budget=None):
    """Connection and server query ceilings; whole-call deadline remains decisive."""
    budget = current_budget(budget)
    if budget is None:
        return dsn
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    remaining = budget.remaining()
    # libpq rounds connect_timeout below two seconds UP: refuse that last slice.
    require(remaining >= 2, 'deadline')
    options = conninfo_to_dict(dsn).get('options', '')
    return make_conninfo(dsn, connect_timeout=str(min(10, int(remaining))),
        options=(options + ' -c statement_timeout=' + str(max(1, int(remaining * 1000)))).strip())


class _DeadlineConnection:
    def __init__(self, connection, budget):
        self.connection, self.budget = connection, budget
        self.failure = None

    def abort(self, primary):
        if self.failure is not None:
            return
        self.failure = primary
        try:
            self.connection.close()
        except BaseException as secondary:
            self.budget.context.owner._uncertain('database_close', secondary, primary)

    def interrupted(self, primary):
        return (self.failure is not None or not isinstance(primary, Exception)
                or time.monotonic() >= self.budget.end
                or isinstance(primary, RestoreUnavailable) and primary.reason == 'deadline')

    def alive(self):
        if self.failure is not None:
            raise self.failure
        self.budget.remaining()

    def execute(self, *args, **kwargs):
        try:
            with io_deadline(self.budget):
                self.alive()
                milliseconds = max(1, int(self.budget.remaining() * 1000))
                self.connection.execute("select set_config('statement_timeout',%s,false)", (str(milliseconds),))
                result = self.connection.execute(*args, **kwargs)
                self.alive()
                return result
        except BaseException as primary:
            if self.interrupted(primary): self.abort(primary)
            if self.failure is not None: raise self.failure
            raise

    @contextmanager
    def transaction(self, *args, **kwargs):
        """No expired/cancelled path enters driver rollback; ordinary rollback stays live."""
        try:
            with io_deadline(self.budget):
                self.alive()
                manager = self.connection.transaction(*args, **kwargs)
                transaction = manager.__enter__()
        except BaseException as primary:
            self.abort(primary)
            raise self.failure
        try:
            yield transaction
        except BaseException as primary:
            if self.interrupted(primary):
                self.abort(primary)
                raise self.failure
            try:
                with io_deadline(self.budget):
                    suppressed = manager.__exit__(type(primary), primary, primary.__traceback__)
                    self.alive()
            except BaseException as secondary:
                self.abort(primary)
                self.budget.context.owner._uncertain('database_rollback', secondary, primary)
                raise primary
            if not suppressed:
                raise
        else:
            try:
                with io_deadline(self.budget):
                    self.alive()
                    manager.__exit__(None, None, None)
                    self.alive()
            except BaseException as primary:
                self.abort(primary)
                raise self.failure

    def __getattr__(self, name):
        return getattr(self.connection, name)


@contextmanager
def bounded_connection(connect, dsn, *, budget=None, **kwargs):
    budget = current_budget(budget)
    with io_deadline(budget):
        dsn = deadline_dsn(dsn, budget)
        if budget is not None and 'connect_timeout' in kwargs:
            kwargs['connect_timeout'] = min(kwargs['connect_timeout'], int(budget.remaining()))
        manager = connect(dsn, **kwargs)
        if budget is None:
            with manager as connection:
                yield connection
            return
        proxy = _DeadlineConnection(manager, budget)
        token = _IO_CONNECTIONS.set((*_IO_CONNECTIONS.get(), proxy))
        try:
            try:
                with _connection_signals(budget):
                    connection = manager.__enter__()
                    require(connection is manager, 'internal')
                    yield proxy
                    proxy.alive()
                    manager.__exit__(None, None, None)
                    proxy.alive()
            except BaseException as primary:
                proxy.abort(primary)
                raise proxy.failure
        finally:
            _IO_CONNECTIONS.reset(token)


def connection_factory(budget=None, *, connect=None):
    """Per-instance adapter injection. Defaults outside this rehearsal are untouched."""
    selected = current_budget(budget)
    def acquire(dsn, **kwargs):
        import psycopg
        return bounded_connection(connect or psycopg.connect, dsn, budget=selected, **kwargs)
    return acquire


def bounded_boundary(boundary, budget=None):
    """Bind existing ownership checks without mutating the imported module."""
    budget = current_budget(budget)
    if budget is None:
        return boundary
    if getattr(boundary, '_recovery_budget', None) is budget:
        return boundary
    class Boundary:
        _recovery_budget = budget
        def __getattr__(self, name):
            return getattr(boundary, name)
        def inspect_container(self, name):
            return boundary.inspect_container(name, budget=budget)
        def verify_source_session(self, source_url, container):
            return boundary.verify_source_session(source_url, container, budget=budget)
        def role_memberships(self, source_url):
            return boundary.role_memberships(source_url, budget=budget)
    return Boundary()


@contextmanager
def bounded_gateway(port, *, prefix, body_cap, budget, unavailable):
    """Owned loopback bridge with absolute socket cutoff and bounded thread joins.

    It supplies no credentials/authority. The caller owns the upstream service.
    Unlike an inactivity timeout, the watchdog also bounds a slowly dripping peer.
    """
    from http.client import HTTPConnection
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import socket
    budget = current_budget(budget)
    require(budget is not None, 'deadline')
    end = budget.end
    budget.remaining(reserve=0.25, end=end)
    lock = _io_threading.Lock()
    active, handlers = set(), set()
    close_errors = []
    closing = _io_threading.Event()
    def remaining():
        return budget.remaining(reserve=0.15, end=end)
    def close_one(value):
        sock = value if isinstance(value, socket.socket) else getattr(value, 'sock', None)
        if sock is not None:
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        try: value.close()
        except BaseException as error: close_errors.append(error)
    def close_all():
        closing.set()
        with lock: values = tuple(active)
        for value in values: close_one(value)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self): self.forward()
        def do_POST(self): self.forward()
        def do_DELETE(self): self.forward()
        def forward(self):
            upstream = None
            try:
                self.connection.settimeout(min(10, remaining()))
                length = int(self.headers.get('Content-Length', '0'))
                path_ok = self.path.startswith(prefix + ('/object/' if prefix == '/storage/v1' else '/'))
                if not path_ok or not 0 <= length <= 4096:
                    self.send_error(404)
                    return
                upstream = HTTPConnection('127.0.0.1', port, timeout=min(10, remaining()))
                with lock:
                    if closing.is_set(): raise RestoreUnavailable('deadline')
                    active.add(upstream)
                headers = {key: value for key, value in self.headers.items()
                    if key.lower() in ('authorization', 'apikey', 'content-type')}
                body = self.rfile.read(length) if length else None
                remaining()
                upstream.request(self.command, self.path[len(prefix):], body, headers)
                remaining()
                response = upstream.getresponse()
                payload = response.read(body_cap+1)
                remaining()
                require(len(payload) <= body_cap, 'limit')
                self.send_response(response.status)
                self.send_header('Content-Type', response.getheader('Content-Type', 'application/octet-stream'))
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception:
                if not closing.is_set():
                    try: self.send_error(502, unavailable)
                    except OSError: pass
            finally:
                if upstream is not None:
                    close_one(upstream)
                    with lock: active.discard(upstream)
    class Server(ThreadingHTTPServer):
        daemon_threads = True
        block_on_close = False
        def process_request(self, request, address):
            with lock:
                if closing.is_set():
                    self.shutdown_request(request)
                    return
                active.add(request)
            def handle():
                try:
                    request.settimeout(min(10, remaining()))
                    self.process_request_thread(request, address)
                except Exception:
                    self.shutdown_request(request)
                finally:
                    with lock: active.discard(request)
            child = _io_threading.Thread(target=handle, daemon=True)
            with lock:
                if closing.is_set():
                    self.shutdown_request(request)
                    active.discard(request)
                    return
                handlers.add(child)
                child.start()
    server = Server(('127.0.0.1', 0), Handler)
    thread = _io_threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
    timer = _io_threading.Timer(remaining(), close_all)
    timer.daemon = True
    primary = None
    try:
        with budget.context.owner.deferred():
            thread.start(); timer.start()
        yield 'http://127.0.0.1:' + str(server.server_address[1])
        budget.remaining(end=end)
    except BaseException as error:
        primary = error
        raise
    finally:
        with unwind_scope(budget):
            errors = []
            try: close_all()
            except BaseException as error: errors.append(error)
            timer.cancel()
            try:
                if thread.is_alive():
                    with io_deadline(budget): server.shutdown()
            except BaseException as error: errors.append(error)
            try: server.server_close()
            except BaseException as error: errors.append(error)
            with lock: owned = (thread, timer, *handlers)
            for child in owned:
                if child.ident is not None:
                    try: child.join(timeout=max(0, min(end, budget.end)-time.monotonic()))
                    except BaseException as error: errors.append(error)
                if child.is_alive(): errors.append(RestoreUnavailable('cleanup_uncertain'))
            errors.extend(close_errors)
            if errors:
                for error in errors: budget.context.owner._uncertain('gateway_close', error, primary)
                if primary is None: raise RestoreUnavailable('cleanup_uncertain') from None


from contextlib import asynccontextmanager as _io_asynccontextmanager


@_io_asynccontextmanager
async def async_scope(budget=None):
    budget = current_budget(budget)
    with budget_scope(budget), io_deadline(budget):
        if budget is None:
            yield
            return
        timeout = _io_asyncio.timeout(budget.remaining())
        try:
            async with timeout:
                yield
        except TimeoutError:
            if timeout.expired():
                raise RestoreUnavailable('deadline') from None
            raise


@contextmanager
def command_io_scope():
    """Never inject an I/O SIGALRM into the command owner's acquisition/unwind."""
    if _io_threading.current_thread() is not _io_threading.main_thread():
        yield
        return
    handler = _io_signal.getsignal(_io_signal.SIGALRM)
    if not getattr(handler, '_rf_io_deadline', False):
        yield
        return
    left, interval = _io_signal.getitimer(_io_signal.ITIMER_REAL)
    started = time.monotonic()
    _io_signal.setitimer(_io_signal.ITIMER_REAL, 0)
    try:
        yield
    finally:
        if left:
            remaining = left-(time.monotonic()-started)
            if remaining > 0:
                _io_signal.setitimer(_io_signal.ITIMER_REAL, remaining, interval)


def io_command(budget, args, **kwargs):
    with command_io_scope():
        return budget.command(args, **kwargs)


def io_checked(budget, args, **kwargs):
    with command_io_scope():
        return budget.checked(args, **kwargs)


from concurrent.futures import ThreadPoolExecutor as _IOThreadPoolExecutor, Future as _IOFuture


class _InlineDeadlineExecutor(_IOThreadPoolExecutor):
    """Private runner executor: original to_thread callbacks, no worker thread.

    Blocking adapters keep their exact SQL/Auth/error mapping, but execute under
    the main-thread absolute timer. Cancelling an await cannot orphan I/O behind
    asyncio.run's executor shutdown. This is installed only on a fresh owned loop.
    """
    def __init__(self, budget):
        super().__init__(max_workers=1)
        self.budget = budget
        self.interruption = None

    def submit(self, function, /, *args, **kwargs):
        if self._shutdown:
            raise RuntimeError('cannot schedule new futures after shutdown')
        future = _IOFuture()
        future.set_running_or_notify_cancel()
        try:
            with budget_scope(self.budget), io_deadline(self.budget):
                result = function(*args, **kwargs)
        except BaseException as error:
            if (self.interruption is None and (not isinstance(error, Exception)
                    or isinstance(error, RestoreUnavailable) and error.reason == 'deadline')):
                self.interruption = error
            future.set_exception(error)
        else:
            future.set_result(result)
        return future


def run_async(awaitable, *, budget=None):
    budget = current_budget(budget)
    if budget is None:
        return _io_asyncio.run(awaitable)
    loop = _io_asyncio.new_event_loop()
    executor = _InlineDeadlineExecutor(budget)
    loop.set_default_executor(executor)
    # No default exception rendering of private adapter locals/exception text.
    loop.set_exception_handler(lambda _loop, _context: None)
    async def run():
        timeout = _io_asyncio.timeout(budget.remaining(reserve=2))
        with budget_scope(budget):
            try:
                async with timeout:
                    return await awaitable
            except TimeoutError:
                if timeout.expired(): raise RestoreUnavailable('deadline') from None
                raise
    primary = None
    try:
        with io_deadline(budget):
            return loop.run_until_complete(run())
    except BaseException as error:
        # A due asyncio timeout can win delivery of an already-interrupted
        # synchronous Future. Preserve the actual initiating exception object.
        primary = executor.interruption if executor.interruption is not None else error
        raise primary
    finally:
        errors = []
        pending = _io_asyncio.all_tasks(loop)
        for task in pending: task.cancel()
        try:
            if pending:
                with io_deadline(budget):
                    loop.run_until_complete(_io_asyncio.gather(*pending, return_exceptions=True))
            if budget.end > time.monotonic():
                with io_deadline(budget): loop.run_until_complete(loop.shutdown_asyncgens())
        except BaseException as error:
            errors.append(error)
        if any(not task.done() for task in pending):
            errors.append(RestoreUnavailable('cleanup_uncertain'))
        # The private executor never starts a thread; loop.close cannot leave an
        # executor callback running beyond this phase or enter another phase.
        loop.close()
        if hasattr(awaitable, 'close'): awaitable.close()
        if errors:
            for error in errors: budget.context.owner._uncertain('async_close', error, primary)
            if primary is None: raise errors[0]


def require_direct_loopback(budget=None):
    """Legacy Colima forwarding has independent clocks; do not claim this profile."""
    if current_budget(budget) is not None:
        require(not os.environ.get('TALLI_RF_RESTORE_SSH_CONFIG')
                and not os.environ.get('TALLI_RF_RESTORE_SSH_HOST'), 'source_binding')
