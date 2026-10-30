"""Pure closed S0 wire/descriptor/projection contract; never execution acceptance.

Templates/configuration: accepted s0-checkpoint-formal-plan-v1. No file reads,
processes, environment mutation, or replay/controller imports in this module.
"""
from datetime import datetime
from functools import wraps
import hashlib
import json
import re

import rf1086_sql_ledger as ledger
import rf1086_catalog_causal_capture as capture
from rf1086_catalog_difference import _object, _reject_constant

CONFIG = {'schema': 's0-config-v2',
 'receipt': 's0-checkpoint-v2',
 'completedControl': 'actual-image-control-v3',
 'replay': {'tag': 'owned_identity_actual_replay_v3 ',
            'aadVersion': 3,
            'durableF2': 'unchanged-literal-S0-unavailable',
            'legacyPhases': 'unchanged',
            'thinReasons': ['consumer_failed',
                            'worker_deadline',
                            'worker_failed',
                            'worker_result_invalid']},
 'ledger': {'schema': 'rf1086-sql-ledger-v5',
            'lexicalRule': 'sql-lexical-scanner-v3',
            'profile': 'pg176-fifo-custom116-utf8-on-v1',
            'descriptorPolicy': {'schema': 's0-session-descriptor-v1',
                                 'anchor': 'before-exact-FIXED',
                                 'assignment': 'latest-actually-emitted-session-SET-semantic-UTF8-sha256',
                                 'null': 'same-epoch-baseline',
                                 'return': 'receipt-and-private-descriptor-once',
                                 'bytes': 16384}},
 'codeFiles': ['rf1086_identity_restore.py',
               'rf1086_catalog_causal.sql',
               'rf1086_catalog_causal_capture.py',
               'rf1086_actual_replay_package.py',
               'rf1086_actual_replay.py',
               'rf1086_catalog_semantics.py',
               'rf1086_raw_toc.py',
               'rf1086_sql_identifiers.py',
               'rf1086_sql_lexical.py',
               'rf1086_sql_ledger.py',
               'rf1086_catalog_difference.py',
               'rf1086_s0_protocol.py',
               'rf1086_s0_control.py',
               'rf1086_causal_protocol.py',
               'rf1086_causal_control.py',
               'rf1086_causal_catalog.py'],
 'encoding': {'canonical': 'ASCII-sorted-compact-ensure_ascii-true-allow_nan-false',
              'ioLowerBound': 'UTF8-compact-ensure_ascii-false',
              'hash': 'sha256-lowercase-hex',
              'partialDomain': 's0-partial-v1'},
 'clients': {'writerArgv': ['docker',
                            'exec',
                            '-i',
                            '@TARGET@',
                            'psql',
                            '-U',
                            'supabase_admin',
                            '-h',
                            '/tmp',
                            '-d',
                            'template1',
                            '-XqAt',
                            '-v',
                            'ON_ERROR_STOP=1'],
             'writerEnvironment': 'unchanged-inherited-no-added-PG-settings',
             'observerArgv': ['docker',
                              'exec',
                              '-i',
                              '-e',
                              'PGCLIENTENCODING=UTF8',
                              '-e',
                              'PGCONNECT_TIMEOUT=2',
                              '@TARGET@',
                              'psql',
                              '-U',
                              'supabase_admin',
                              '-h',
                              '/tmp',
                              '-d',
                              '@DB@',
                              '-XqAt',
                              '-v',
                              'ON_ERROR_STOP=1'],
             'toolArgv': ['docker',
                          'exec',
                          '@TARGET@',
                          'sh',
                          '-c',
                          'set -eu\n'
                          'binary=$(command -v psql)\n'
                          'case "$binary" in /*) ;; *) exit 1;; esac\n'
                          '[ -f "$binary" ] && [ -x "$binary" ]\n'
                          'version=$("$binary" --version)\n'
                          'hashed=$(sha256sum "$binary")\n'
                          'printf \'%s\\n%s\\n\' "$version" "${hashed%% *}"\n'],
             'toolStdoutBytes': 4096,
             'toolStderrBytes': 65536,
             'toolOutput': 'psql (PostgreSQL) 17.6\n<64 lowercase hex>\n',
             'stdio': 'ordinary-noninteractive-stdin-no-TTY',
             'clientProfile': 'conditional ordinary-stdin/simple-query profile; fresh -X and closed '
                              'ledger meta; preserved argv; no separately asserted SHOW_ALL_RESULTS '
                              'value'},
 'queries': {'P': "SELECT pg_catalog.concat('S0P/@N@/@SS@/', "
                  'pg_catalog.encode(pg_catalog.convert_to(pg_catalog.json_build_array(pg_catalog.current_database(), '
                  'pg_catalog.pg_backend_pid(), session_user::pg_catalog.text, '
                  "current_user::pg_catalog.text, pg_catalog.current_setting('statement_timeout'), "
                  "pg_catalog.current_setting('lock_timeout'), "
                  "pg_catalog.current_setting('idle_in_transaction_session_timeout'), "
                  "pg_catalog.current_setting('transaction_timeout'), "
                  "pg_catalog.current_setting('client_encoding'), "
                  "pg_catalog.current_setting('standard_conforming_strings'), "
                  "pg_catalog.current_setting('check_function_bodies'), "
                  "pg_catalog.current_setting('xmloption'), "
                  "pg_catalog.current_setting('client_min_messages'), "
                  "pg_catalog.current_setting('row_security'), "
                  "pg_catalog.current_setting('search_path'), "
                  "pg_catalog.current_setting('default_tablespace'), "
                  "pg_catalog.current_setting('default_table_access_method'))::pg_catalog.text, "
                  "'UTF8'), 'hex'));\n",
             'Q': "SELECT pg_catalog.concat('S0B/@N@/@SS@/', pg_catalog.pg_backend_pid());\n",
             'W': 'BEGIN ISOLATION LEVEL READ COMMITTED READ ONLY;\n'
                  "SET LOCAL statement_timeout = '1s';\n"
                  "SET LOCAL lock_timeout = '1s';\n"
                  'SET LOCAL search_path = pg_catalog;\n'
                  "SET LOCAL TimeZone = 'UTC';\n"
                  "SET LOCAL DateStyle = 'ISO, YMD';\n"
                  "SELECT pg_catalog.concat('S0O/@N@/@SS@/@R@/',\n"
                  '  pg_catalog.encode(pg_catalog.convert_to(pg_catalog.jsonb_build_array(\n'
                  '    pg_catalog.current_database(), d.oid::pg_catalog.text,\n'
                  '    a.pid, a.datid::pg_catalog.text, a.datname,\n'
                  '    a.backend_start::pg_catalog.text, a.state,\n'
                  '    a.xact_start::pg_catalog.text, a.backend_xid::pg_catalog.text,\n'
                  '    a.backend_xmin::pg_catalog.text, a.query,\n'
                  "    pg_catalog.current_setting('server_encoding'),\n"
                  "    pg_catalog.current_setting('client_encoding'),\n"
                  '    g.setting, g.unit, g.context, g.vartype\n'
                  "  )::pg_catalog.text, 'UTF8'), 'hex'))\n"
                  'FROM pg_catalog.pg_stat_activity AS a\n'
                  'JOIN pg_catalog.pg_database AS d\n'
                  '  ON d.datname = pg_catalog.current_database()\n'
                  'CROSS JOIN pg_catalog.pg_settings AS g\n'
                  "WHERE a.pid = @PID@ AND g.name = 'track_activity_query_size';\n"
                  'ROLLBACK;\n',
             'catalog': {'path': 'scripts/rf1086_catalog_causal.sql',
                         'bytes': 7073,
                         'sha256': '26258eb31ea9862019667789e27f8d87acce756a4d451d209bfa38df79f325d5'}},
 'substitution': {'@N@': '32 lowercase hex fresh nonce',
                  '@SS@': '00..05 exact exchange index',
                  '@R@': ['anchor', 'before', 'after'],
                  '@PID@': 'canonical decimal integer1..2147483647',
                  '@DB@': ['template1', 'postgres'],
                  '@TARGET@': 'owned full64 lowercase hex containerID'},
 'session': {'settings': ['statement_timeout',
                          'lock_timeout',
                          'idle_in_transaction_session_timeout',
                          'transaction_timeout',
                          'client_encoding',
                          'standard_conforming_strings',
                          'check_function_bodies',
                          'xmloption',
                          'client_min_messages',
                          'row_security',
                          'search_path',
                          'default_tablespace',
                          'default_table_access_method'],
             'users': ['supabase_admin', 'supabase_admin'],
             'anchorLexical': {'client_encoding': 'UTF8', 'standard_conforming_strings': 'on'},
             'cutFirst11': ['0', '0', '0', '0', 'UTF8', 'on', 'off', 'content', 'warning', 'off', ''],
             'cutLast2': 'descriptor-assignment-sha256-or-same-epoch-baseline-exact-text',
             'epochs': [2, 3],
             'cuts': 3,
             'databaseInitial': 'template1',
             'databaseRestored': 'postgres'},
 'witness': {'fields': ['observerDatabase',
                        'observerDatabaseOid',
                        'pid',
                        'activityDatabaseOid',
                        'activityDatabase',
                        'backendStart',
                        'state',
                        'xactStart',
                        'backendXid',
                        'backendXmin',
                        'query',
                        'serverEncoding',
                        'clientEncoding',
                        'activityCapacity',
                        'capacityUnit',
                        'capacityContext',
                        'capacityType'],
             'activityCapacity': [103, 1048576],
             'queryBytes': 98,
             'timestamp': 'YYYY-MM-DD HH:MM:SS[.1..6 digits]+00',
             'state': 'idle',
             'transactionFields': 'all-null',
             'encodings': ['UTF8', 'UTF8'],
             'capacityMetadata': ['B', 'postmaster', 'integer']},
 'projection': {'version': 1,
                'server': 170006,
                'keys': ['v', 'server', 'schemas', 'net', 'hooks', 'events', 'extensions', 'snapshot'],
                'schemas': ['graphql', 'graphql_public'],
                'net': 'exact pinned NET_IDENTITIES order',
                'hooks': ['grant_pg_net_access', 'grant_pg_graphql_access', 'set_graphql_placeholder'],
                'events': ['issue_pg_net_access',
                           'issue_pg_graphql_access',
                           'issue_graphql_placeholder'],
                'extensions': ['pg_net', 'pg_graphql'],
                'usage': 'omitted',
                'currentSchemas': 'omitted',
                'validation': 'fresh raw _validate_snapshot(result,None) once; final retained '
                              'validation unchanged'},
 'caps': {'Praw': 2000,
          'Pcanonical': 2000,
          'Wraw': 2000,
          'Wcanonical': 288,
          'frame': 4096,
          'writerStdout': 1048576,
          'writerStderr': 65536,
          'observerStdout': 49152,
          'observerStderrDrain': 65536,
          'observerSuccessStderr': 0,
          'catalogLine': 32768,
          'partialProjection': 2048,
          'receipt': 24576,
          'descriptor': 16384,
          'probeRequests': 16384,
          'pipeChunk': 65536,
          'originalSql': 134217728,
          'plaintext': 65536,
          'envelope': 98304},
 'seconds': {'total': 120,
             'phases': {'admission': 5,
                        'setup': 40,
                        'transport': 45,
                        'final': 15,
                        'cleanup': 13,
                        'composition': 2},
             'writerWork': 43,
             'sharedUnwind': 2,
             'anchorInclusive': 4,
             'cutInclusive': 6,
             'witnessStatement': 1,
             'catalogStatement': 3,
             'observerConnect': 2,
             'outerUnchanged': {'active': 416,
                                'cleanupWork': 58,
                                'commandWork': 43,
                                'publicationReserve': 12,
                                'fullSqlAdmission': 200,
                                'recoveryChild': 180,
                                'browserTest': 360}},
 'reasonStages': {'admission': ['dependency',
                                'headroom',
                                'descriptor_invalid',
                                'nonce_collision',
                                'summary_oversized'],
                  'setup': ['ownership',
                            'tool',
                            'initialized_mismatch',
                            'command',
                            'deadline',
                            'control_unavailable'],
                  'transport': ['session',
                                'frame',
                                'observer',
                                'partial_catalog',
                                'input',
                                'command',
                                'deadline',
                                'control_unavailable'],
                  'final': ['fingerprint_mismatch',
                            'enriched_mismatch',
                            'command',
                            'deadline',
                            'control_unavailable'],
                  'cleanup': ['cleanup_unproved', 'parent_cleanup', 'deadline', 'control_unavailable'],
                  'composition': ['summary_oversized', 'control_unavailable'],
                  'unobserved': ['worker_deadline',
                                 'worker_failed',
                                 'worker_result_invalid',
                                 'control_unavailable']},
 'policy': {'noFutureOriginalInputDuringPause': True,
            'ordinaryWriterOutput': 'bounded-discard-with-lifetime-reserved-frame-validation',
            'descriptorPublic': 'digest-and-necessary-reconstructible-references-only',
            'scope': 'conditional-matched-checkpoints-not-historical-purity',
            'ordinaryS0Failure': 'preserve-complete-Fsql-ledger-only-with-known-reaps-and-authoritative-cleanup',
            'uncertainReap': 'escape-ordinary-shielding',
            'cancellation': 'propagate-no-envelope-promise',
            'sizeFallback': 'S0-first-then-existing-ledger-Fsql',
            'workerLoss': 'confirmed-F2-only'}}

SCHEMA = CONFIG['receipt']
CAPS = CONFIG['caps']
FIXED_BYTES = len(ledger.FIXED)
HASH = re.compile(r'[a-f0-9]{64}')
NONCE = re.compile(r'[a-f0-9]{32}')
TIMESTAMP = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?\+00')


class Unavailable(ValueError):
    def __init__(self):
        self.reason = 's0_protocol_invalid'
        super().__init__(self.reason)


def _require(condition):
    if not condition:
        raise Unavailable()


def _closed(function):
    """Public validators expose one finite error, never rejected input text."""
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Unavailable:
            raise
        except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
            raise Unavailable() from None
    return checked


def _keys(value, names):
    _require(type(value) is dict and set(value) == set(names))


def _integer(value, low, high):
    _require(type(value) is int and low <= value <= high)


def _hash(value):
    _require(type(value) is str and HASH.fullmatch(value) is not None)


def _text(value, cap=2000):
    _require(type(value) is str and len(value) <= cap and len(value.encode('utf-8')) <= cap)


def _strings(value):
    if type(value) is str:
        value.encode('utf-8')  # Reject escaped unpaired surrogates, too.
    elif type(value) in (list, tuple):
        for item in value:
            _strings(item)
    elif type(value) is dict:
        for key, item in value.items():
            _require(type(key) is str)
            _strings(key); _strings(item)


def _canonical(value):
    _strings(value)
    return ledger.canonical(value)


def _commit(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _utf8(value):
    _strings(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def _json(payload, cap):
    _require(type(payload) is bytes and 0 < len(payload) <= cap)
    value = json.loads(payload.decode('utf-8'), object_pairs_hook=_object, parse_constant=_reject_constant)
    _strings(value)
    return value


def _point(value):
    _require(type(value) in (tuple, list) and len(value) == 2 and type(value[0]) is str
             and value[0] in ('anchor', 'cut'))
    _integer(value[1], 0, 2)
    return value[0], value[1]


@_closed
def unavailable(reason, stage, point=None):
    value = {'schema': SCHEMA, 'status': 'unavailable', 'reason': reason,
             'stage': stage, 'point': None if point is None else list(_point(point))}
    return validate_unavailable(value)


@_closed
def validate_unavailable(value):
    _keys(value, ('schema', 'status', 'reason', 'stage', 'point'))
    _require(value['schema'] == SCHEMA and value['status'] == 'unavailable')
    stage, reason = value['stage'], value['reason']
    _require(type(stage) is str and stage in CONFIG['reasonStages']
             and type(reason) is str and reason in CONFIG['reasonStages'][stage])
    point = value['point']
    if stage != 'transport':
        _require(point is None)
    elif point is not None:
        _require(type(point) is list)
        _point(point)
    if stage == 'transport' and reason in ('session', 'observer', 'partial_catalog'):
        _require(point is not None)
        if reason == 'partial_catalog':
            _require(point[0] == 'cut')
    return value


def _stream(value):
    _keys(value, ('bytes', 'sha256'))
    _integer(value['bytes'], 1, CAPS['originalSql']); _hash(value['sha256'])


@_closed
def validate_descriptor(D, ledger, stream):
    """Ledger must already have passed independent production validation."""
    _stream(stream)
    _require(ledger['schema'] == CONFIG['ledger']['schema']
             and ledger['status'] == 'verified_conditional' and ledger['inputs']['script'] == stream)
    _keys(D, ('schema', 'ledgerSha256', 'database', 'epochs', 'cuts'))
    _require(D['schema'] == CONFIG['ledger']['descriptorPolicy']['schema']
             and D['ledgerSha256'] == _commit(ledger) and D['database'] == 'postgres')
    epochs, cuts = D['epochs'], D['cuts']
    _require(type(epochs) is list and 2 <= len(epochs) <= 3
             and type(cuts) is list and len(cuts) == 3)
    _integer(ledger['counts']['reconnects'], 1, 2)
    _require(len(epochs) == ledger['counts']['reconnects']+1)
    previous = -1
    for row in epochs:
        _require(type(row) is list and len(row) == 2)
        a, z = row
        _integer(a, 0, stream['bytes']); _integer(z, 0, stream['bytes'])
        _require(previous <= a < z and z-a == FIXED_BYTES)
        previous = z
    _require(type(ledger['selected']) is list and len(ledger['selected']) == 3)
    last = -1
    prior_epoch, prior_references = None, None
    offsets = [row[0] for row in epochs]
    for row, selected in zip(cuts, ledger['selected'], strict=True):
        _require(type(row) is list and len(row) == 3)
        epoch, tablespace, tableam = row
        _integer(epoch, 1, len(epochs)-1)
        cut = selected['cut']; _integer(cut, 1, stream['bytes']-1)
        end = epochs[epoch+1][0] if epoch+1 < len(epochs) else stream['bytes']
        _require(last < cut and epochs[epoch][1] <= cut < end)
        offsets.append(cut)
        for slot, reference in enumerate((tablespace, tableam)):
            if reference is not None:
                _require(type(reference) is list and len(reference) == 2)
                _integer(reference[0], epochs[epoch][1]+1, cut); _hash(reference[1])
            if prior_epoch == epoch:
                previous_reference = prior_references[slot]
                # An assignment cannot be forgotten or changed retroactively.
                _require(reference == previous_reference or
                         reference is not None and reference[0] > last)
        prior_epoch, prior_references, last = epoch, (tablespace, tableam), cut
    _require(len(offsets) == len(set(offsets)) and len(_canonical(D)) <= CAPS['descriptor'])
    return D


@_closed
def ordered_points(D, ledger):
    validate_descriptor(D, ledger, ledger['inputs']['script'])
    points = [(('anchor', i), row[0]) for i, row in enumerate(D['epochs'])]
    points.extend((('cut', i), row['cut']) for i, row in enumerate(ledger['selected']))
    return tuple(sorted(points, key=lambda item: item[1]))


def _nonce_sequence(nonce, sequence):
    _require(type(nonce) is str and NONCE.fullmatch(nonce) is not None)
    _integer(sequence, 0, 5)
    return {'@N@': nonce, '@SS@': f'{sequence:02d}'}


def _substitute(template, values):
    for key, value in values.items():
        template = template.replace(key, value)
    return template


@_closed
def probe(nonce, sequence):
    values = _nonce_sequence(nonce, sequence)
    return tuple(_substitute(CONFIG['queries'][name], values).encode('ascii') for name in ('P', 'Q'))


@_closed
def witness_request(nonce, sequence, role, pid):
    values = _nonce_sequence(nonce, sequence)
    _require(type(role) is str and role in ('anchor', 'before', 'after'))
    _integer(pid, 1, 2147483647)
    return _substitute(CONFIG['queries']['W'], values | {'@R@': role, '@PID@': str(pid)}).encode('ascii')


def _argv(name, target, database=None):
    _hash(target)
    return [_substitute(value, {'@TARGET@': target, '@DB@': database or ''})
            for value in CONFIG['clients'][name]]


@_closed
def writer_argv(target):
    return _argv('writerArgv', target)


@_closed
def observer_argv(target, database):
    _require(type(database) is str and database in ('template1', 'postgres'))
    return _argv('observerArgv', target, database)


@_closed
def tool_argv(target):
    return _argv('toolArgv', target)


def _session(value, *, point, descriptor, baseline=None):
    kind, index = _point(point)
    _require(type(value) is list and len(value) == 17)
    epoch = index if kind == 'anchor' else descriptor['cuts'][index][0]
    _integer(epoch, 0, len(descriptor['epochs'])-1)
    database = 'template1' if kind == 'anchor' and index == 0 else 'postgres'
    _require(value[0] == database and value[2:4] == ['supabase_admin', 'supabase_admin'])
    _integer(value[1], 1, 2147483647)
    for text in value[4:]: _text(text)
    _require(len(_canonical(value)) <= CAPS['Pcanonical'] and value[8:10] == ['UTF8', 'on'])
    if kind == 'anchor':
        _require(baseline is None)
    else:
        _require(epoch > 0 and value[4:15] == CONFIG['session']['cutFirst11'])
        _session(baseline, point=('anchor', epoch), descriptor=descriptor)
        for slot, reference in zip((15, 16), descriptor['cuts'][index][1:], strict=True):
            if reference is None:
                _require(value[slot] == baseline[slot])
            else:
                _require(hashlib.sha256(value[slot].encode('utf-8')).hexdigest() == reference[1])
    return value


@_closed
def parse_session(payload, *, point, descriptor, baseline=None):
    return _session(_json(payload, CAPS['Praw']), point=point, descriptor=descriptor, baseline=baseline)


def _oid(value):
    _require(type(value) is str and re.fullmatch(r'[1-9][0-9]{0,9}', value) is not None)
    _integer(int(value), 1, 4294967295)


def _epoch(value):
    return value[2], value[5], value[1], value[0]


def _witness(value, *, nonce, sequence, session, epoch_witness=None):
    return _witness_fields(value, session=session, query=probe(nonce, sequence)[1][:-1].decode('ascii'),
                           epoch_witness=epoch_witness)


def _witness_fields(value, *, session, query, epoch_witness=None):
    """Shared field checks; only closed protocol wrappers derive expected query."""
    _require(type(value) is list and len(value) == 17 and len(_canonical(value)) <= CAPS['Wcanonical'])
    _require(value[0] == value[4] == session[0] and value[2] == session[1])
    _integer(value[2], 1, 2147483647)
    _oid(value[1]); _oid(value[3]); _require(value[1] == value[3])
    _require(type(value[5]) is str and TIMESTAMP.fullmatch(value[5]) is not None)
    datetime.fromisoformat(value[5])
    _require(value[6:10] == ['idle', None, None, None]
             and value[10] == query
             and value[11:13] == ['UTF8', 'UTF8'] and value[14:] == ['B', 'postmaster', 'integer'])
    _require(type(value[13]) is str and re.fullmatch(r'[1-9][0-9]{0,6}', value[13]) is not None)
    _integer(int(value[13]), *CONFIG['witness']['activityCapacity'])
    if epoch_witness is not None:
        _require(_epoch(value) == _epoch(epoch_witness))
    return value


@_closed
def parse_witness(payload, *, nonce, sequence, session, epoch_witness=None):
    return _witness(_json(payload, CAPS['Wraw']), nonce=nonce, sequence=sequence,
                    session=session, epoch_witness=epoch_witness)


def _component(tag, slot, value):
    return _commit(['s0-partial-v1', tag, slot, value])


@_closed
def snapshot_commitment(normalized):
    _keys(normalized, ('serverVersion', 'schemas', 'functions', 'hooks', 'events', 'extensions'))
    _require(type(normalized['serverVersion']) is int and normalized['serverVersion'] == 170006)
    return _component('snapshot', 0, normalized)


def _projection(value):
    _keys(value, CONFIG['projection']['keys'])
    _require(type(value['v']) is int and value['v'] == 1
             and type(value['server']) is int and value['server'] == 170006)
    for group, count in (('schemas', 2), ('net', 2), ('hooks', 3), ('events', 3), ('extensions', 2)):
        _require(type(value[group]) is list and len(value[group]) == count)
        for item in value[group]:
            if item is None: continue
            if group == 'hooks':
                _hash(item); continue
            _require(type(item) is list)
            if group == 'schemas':
                _require(len(item) == 4)
                for h in item: _hash(h)
            elif group == 'net':
                _require(len(item) == 5 and type(item[2]) is bool)
                _integer(item[3], 0, 1)
                for i in (0, 1, 4): _hash(item[i])
            elif group == 'events':
                _require(len(item) == 3 and type(item[0]) is str and item[0] in ('O', 'D', 'R', 'A'))
                _integer(item[1], 0, 2); _hash(item[2])
                _require(value['hooks'][item[1]] is not None)
            else:
                _require(len(item) == 3 and type(item[0]) is str and capture.VERSION.fullmatch(item[0]) is not None)
                _hash(item[1]); _hash(item[2])
    _hash(value['snapshot'])
    _require(len(_canonical(value)) <= CAPS['partialProjection'])
    return value


def _selected(value, selected, reference_catalog):
    kind = selected['kind']
    semantics = ledger.selected_semantics(reference_catalog)
    _require(kind in semantics and selected['semanticSha256'] == semantics[kind][1])
    group, slot, field = {'graphql_schema': ('schemas', 0, 0),
                         'graphql_public_schema': ('schemas', 1, 0),
                         'pg_net_extension': ('extensions', 0, 1)}[kind]
    _require(value[group][slot] is not None and value[group][slot][field] == semantics[kind][1])


@_closed
def project(raw_catalog, *, selected, reference_catalog):
    """Decode/validate fresh raw JSON once; normalized references are never reparsed."""
    return project_with_reference(raw_catalog, selected=selected, reference_catalog=reference_catalog)[0]


@_closed
def project_with_reference(raw_catalog, *, selected, reference_catalog):
    """One raw validation; return a separate projection and owned normalized graph."""
    catalog = capture._validate_snapshot(_json(raw_catalog, CAPS['catalogLine']), None)
    return project_normalized(catalog, selected=selected, reference_catalog=reference_catalog), catalog


@_closed
def project_normalized(catalog, *, selected, reference_catalog):
    """Project already validated normalized input; never reparse hashed hooks."""
    _require(catalog['serverVersion'] == 170006)
    expected_extensions = CONFIG['projection']['extensions']
    seen = [row[0] for row in catalog['extensions']]
    _require(len(seen) == len(set(seen)) and set(seen) <= set(expected_extensions))
    result = {'v': 1, 'server': 170006, 'schemas': [], 'net': [], 'hooks': [], 'events': [], 'extensions': [],
              'snapshot': snapshot_commitment(catalog)}
    for i, identity in enumerate(capture.SCHEMAS):
        item = next((row for row in catalog['schemas'] if row['identity'] == identity), None)
        result['schemas'].append(None if item is None else [
            _commit(['schema', identity[1], item['row'][2]]), _component('schema-acl', i, item['row'][3]),
            _component('schema-grants', i, item['grants']),
            _component('schema-other', i, [item[k] for k in ('defaults', 'default_grants', 'initial', 'extensions')])])
    for i, identity in enumerate(capture.NET_IDENTITIES):
        item = next((row for row in catalog['functions'] if row['identity'] == identity), None)
        result['net'].append(None if item is None else [item['body_sha256'], item['definition_sha256'],
            item['row'][6], 0 if item['row'][7] is None else 1,
            _component('net-other', i, [item['identity'], item['row'][4], item['row'][5], item['attributes'],
                                      item['types'], item['definition_attributes'], item['extensions']])])
    for i, identity in enumerate(capture.HOOKS):
        item = next((row for row in catalog['hooks'] if row['identity'] == identity), None)
        result['hooks'].append(None if item is None else _component('hook', i, item))
    for i, name in enumerate(capture.EVENTS):
        item = next((row for row in catalog['events'] if row['name'] == name), None)
        result['events'].append(None if item is None else [item['enabled'], capture.HOOKS.index(item['function']),
                                                         _component('event', i, item)])
    for i, name in enumerate(expected_extensions):
        row = next((row for row in catalog['extensions'] if row[0] == name), None)
        result['extensions'].append(None if row is None else [row[1], _commit(['extension', name, row[2]]),
                                                            _component('extension-owner', i, row[3])])
    _projection(result); _selected(result, selected, reference_catalog)
    return result


def _dependencies(fsql, f2_input, metadata, inventory=None):
    """The caller first validates full F2/Fsql with authenticated inventory."""
    _require(type(fsql) is dict and fsql['status'] == 'full_sql_verified')
    _stream(fsql['stream'])
    _keys(fsql['tool'], ('version', 'sha256'))
    _require(fsql['tool']['version'] == '17.6'); _hash(fsql['tool']['sha256'])
    for name in ('initializedEqualsOriginal', 'freshTarget', 'FsqlEqualsF2', 'causalSnapshotEqualsF2'):
        _require(fsql[name] is True)
    for name in ('recoveryAccepted', 'causalAttributionAccepted'):
        _require(fsql[name] is False)
    _require(fsql['fingerprint'] == metadata['failed']
             and fsql['catalog'] == metadata['phases']['mismatch']['catalog'])
    _keys(metadata['code'], CONFIG['codeFiles'])
    for digest in metadata['code'].values(): _hash(digest)
    _require(type(f2_input) is dict and f2_input['code'] == metadata['code'])
    # The original business rehearsal failed. Only source postchecks are positive.
    for obj in (metadata, f2_input):
        _require(obj['cleanupComplete'] is True and obj['identitySourcePostcheck'] is True
                 and obj['outerBusinessPostchecks'] is False)
    _require(all(key in metadata and item == metadata[key] for key, item in f2_input.items()))
    value = ledger.validate_receipt(fsql['ledger'], fsql=fsql, inventory=inventory,
        archive_binding=metadata['files']['archive.dump'], code=metadata['code'], catalog=fsql['catalog'])
    _require(value['status'] == 'verified_conditional')
    return value


def _descriptor(references, ledger_value):
    _keys(references, ('epochs', 'cuts'))
    return {'schema': CONFIG['ledger']['descriptorPolicy']['schema'],
            'ledgerSha256': _commit(ledger_value), 'database': 'postgres', **references}


def _io(value, stdout_cap, stderr_cap, minimum):
    _keys(value, ('stdoutBytes', 'stderrBytes', 'stdoutEnd', 'stderrEnd', 'exitCode', 'reap'))
    _integer(value['stdoutBytes'], minimum, stdout_cap)
    _integer(value['stderrBytes'], 0, stderr_cap)
    _integer(value['exitCode'], 0, 0)
    _require(value['stdoutEnd'] == value['stderrEnd'] == 'eof' and value['reap'] == 'waited')


def _witness_size(value, nonce, sequence, role):
    # UTF8 compact JSON is a lower bound on server rendering, unlike ASCII C().
    return len(f'S0O/{nonce}/{sequence:02d}/{role}/')+2*len(_utf8(value))+1


@_closed
def validate_receipt(value, *, fsql, f2_input, metadata, published=False,
                     worker_outcome=None, owned_cleanup=None, inventory=None):
    if type(value) is dict and value.get('status') == 'unavailable':
        return validate_unavailable(value)
    _keys(value, ('schema', 'status', 'bindings', 'target', 'tool', 'nonce',
                  'references', 'exchanges', 'delivery', 'final'))
    _require(value['schema'] == SCHEMA and value['status'] == 'matched'
             and len(_canonical(value)) <= CAPS['receipt'])
    _require(type(published) is bool)
    if published:
        _require(worker_outcome == 'completed' and owned_cleanup is True)
    else:
        _require(worker_outcome is None and owned_cleanup is None)
    ledger_value = _dependencies(fsql, f2_input, metadata, inventory)
    D = _descriptor(value['references'], ledger_value)
    validate_descriptor(D, ledger_value, fsql['stream'])
    _keys(value['bindings'], ('input', 'configuration', 'ledger', 'descriptor'))
    _require(value['bindings'] == {'input': _commit(f2_input), 'configuration': _commit(CONFIG),
                                  'ledger': _commit(ledger_value), 'descriptor': _commit(D)})
    target = value['target']; _keys(target, ('id', 'previous', 'initialized'))
    for digest in target.values(): _hash(digest)
    _require(target['id'] != target['previous']
             and not {target['id'], target['previous']} & {metadata['source'], metadata['sourceAuth']})
    _require(target['initialized'] == snapshot_commitment(metadata['phases']['target_initialized']['catalog']))
    _keys(value['tool'], ('version', 'sha256'))
    _require(value['tool']['version'] == '17.6'); _hash(value['tool']['sha256'])
    nonce = value['nonce']; _nonce_sequence(nonce, 0)
    points = ordered_points(D, ledger_value)
    exchanges = value['exchanges']
    _require(type(exchanges) is list and len(exchanges) == len(points))
    baselines, witnesses = {}, {}
    writer_minimum = 0
    for sequence, (exchange, (point, offset)) in enumerate(zip(exchanges, points, strict=True)):
        _keys(exchange, ('point', 'input', 'session', 'barrierPid', 'witnesses', 'observer', 'catalog'))
        _require(type(exchange['point']) is list and tuple(exchange['point']) == point)
        _point(exchange['point'])
        _require(type(exchange['input']) is list and len(exchange['input']) == 2)
        for item in exchange['input']: _integer(item, offset, offset)
        kind, index = point
        epoch = index if kind == 'anchor' else D['cuts'][index][0]
        session = _session(exchange['session'], point=point, descriptor=D,
                           baseline=None if kind == 'anchor' else baselines[epoch])
        _integer(exchange['barrierPid'], 1, 2147483647)
        _require(exchange['barrierPid'] == session[1])
        records = exchange['witnesses']; roles = ('anchor',) if kind == 'anchor' else ('before', 'after')
        _require(type(records) is list and len(records) == len(roles))
        minimum = 0
        for record, role in zip(records, roles, strict=True):
            _witness(record, nonce=nonce, sequence=sequence, session=session,
                     epoch_witness=None if kind == 'anchor' else witnesses[epoch])
            frame_bytes = _witness_size(record, nonce, sequence, role)
            _require(frame_bytes <= CAPS['frame']); minimum += frame_bytes
        _io(exchange['observer'], CAPS['observerStdout'], CAPS['observerSuccessStderr'], minimum)
        if kind == 'anchor':
            _require(exchange['catalog'] is None)
            if epoch:
                _require((records[0][2], records[0][5]) != (witnesses[epoch-1][2], witnesses[epoch-1][5]))
            baselines[epoch], witnesses[epoch] = session, records[0]
        else:
            _projection(exchange['catalog'])
            _selected(exchange['catalog'], ledger_value['selected'][index], fsql['catalog'])
        p_size = 40+2*len(_utf8(session))+1
        _require(p_size <= CAPS['frame'])
        writer_minimum += p_size+40+len(str(session[1]))+1
    delivery = value['delivery']; _keys(delivery, ('original', 'probes', 'frames', 'writer'))
    _stream(delivery['original']); _require(delivery['original'] == fsql['stream'])
    # At most six fixed pairs: this allocation is below the 16 KiB probe cap.
    probes = b''.join(part for sequence in range(len(points)) for part in probe(nonce, sequence))
    _require(len(probes) <= CAPS['probeRequests'])
    _keys(delivery['probes'], ('bytes', 'sha256'))
    _integer(delivery['probes']['bytes'], len(probes), len(probes))
    _require(delivery['probes']['sha256'] == hashlib.sha256(probes).hexdigest())
    _require(type(delivery['frames']) is list and len(delivery['frames']) == 2)
    for item in delivery['frames']: _integer(item, len(points), len(points))
    _io(delivery['writer'], CAPS['writerStdout'], CAPS['writerStderr'], writer_minimum)
    _keys(value['final'], ('fingerprint', 'enriched'))
    _keys(value['final']['fingerprint'], ('roles', 'catalog', 'auth', 'companyMemberships'))
    for digest in value['final']['fingerprint'].values(): _hash(digest)
    _require(value['final']['fingerprint'] == metadata['failed'] == fsql['fingerprint']
             and value['final']['enriched'] == snapshot_commitment(fsql['catalog']))
    return value


class _SizingReceipt(dict):
    """JSON-serializable upper bound, deliberately rejected by exact-type validators."""


@_closed
def maximum_receipt(*, fsql, f2_input, metadata, descriptor, inventory=None):
    """Conservative size-only skeleton; includes impossible maximum combinations.

    W's exact query slot is padded to the canonical cap for sizing only. Neither
    this subclass nor its invalid vectors may be used as positive evidence.
    """
    value = _dependencies(fsql, f2_input, metadata, inventory)
    D = validate_descriptor(descriptor, value, fsql['stream'])
    nonce, h, pid = 'f'*32, 'f'*64, 2147483647
    projection = {'v': 1, 'server': 170006, 'schemas': [[h]*4 for _ in range(2)],
        'net': [[h, h, False, 1, h] for _ in range(2)], 'hooks': [h]*3,
        'events': [['O', 2, h] for _ in range(3)],
        'extensions': [['999.999.999', h, h] for _ in range(2)], 'snapshot': h}
    exchanges = []
    io = lambda out, err: dict(stdoutBytes=out, stderrBytes=err, stdoutEnd='eof', stderrEnd='eof', exitCode=0, reap='waited')
    for sequence, (point, offset) in enumerate(ordered_points(D, value)):
        database = 'template1' if point == ('anchor', 0) else 'postgres'
        session = [database, pid, 'supabase_admin', 'supabase_admin', *CONFIG['session']['cutFirst11'], '', '']
        session[-1] = 'x'*(CAPS['Pcanonical']-len(_canonical(session)))
        witness = [database, '4294967295', pid, '4294967295', database,
            '9999-12-31 23:59:59.999999+00', 'idle', None, None, None,
            probe(nonce, sequence)[1][:-1].decode('ascii'), 'UTF8', 'UTF8', '1048576', 'B', 'postmaster', 'integer']
        witness[10] += 'x'*(CAPS['Wcanonical']-len(_canonical(witness)))
        exchanges.append({'point': list(point), 'input': [offset, offset], 'session': session,
            'barrierPid': pid, 'witnesses': [witness]*(1 if point[0] == 'anchor' else 2),
            'observer': io(CAPS['observerStdout'], 0), 'catalog': None if point[0] == 'anchor' else projection})
    probes = b''.join(part for seq in range(len(exchanges)) for part in probe(nonce, seq))
    result = _SizingReceipt(schema=SCHEMA, status='matched',
        bindings={'input': _commit(f2_input), 'configuration': _commit(CONFIG), 'ledger': _commit(value), 'descriptor': _commit(D)},
        target={'id': h, 'previous': h, 'initialized': h}, tool={'version': '17.6', 'sha256': h}, nonce=nonce,
        references={k: D[k] for k in ('epochs', 'cuts')}, exchanges=exchanges,
        delivery={'original': fsql['stream'], 'probes': {'bytes': len(probes), 'sha256': hashlib.sha256(probes).hexdigest()},
                  'frames': [len(exchanges)]*2, 'writer': io(CAPS['writerStdout'], CAPS['writerStderr'])},
        final={'fingerprint': {k: h for k in ('roles', 'catalog', 'auth', 'companyMemberships')}, 'enriched': h})
    _require(len(_canonical(result)) <= CAPS['receipt'])
    return result
