"""Closed same-generation Is/In protocol. No process, file or provider operations.

Conditional state interventions only; preserved strict recovery verdict. CONFIG
is compiled from the paired accepted causal-branches formal plan V2.
"""
from copy import deepcopy
from dataclasses import dataclass
from functools import wraps
import hashlib
import json
import math
import re
import time

import rf1086_s0_protocol as s0
import rf1086_catalog_causal_capture as capture

CONFIG = {'completedControl': 'actual-image-control-v3',
 'branchReceipt': 'causal-branch-v1',
 'replay': {'tag': 'owned_identity_actual_replay_v3 ',
            'aadVersion': 3,
            'durableF2': 'UNCHANGED',
            'legacyPhases': 'UNCHANGED',
            'S0Receipt': 's0-checkpoint-v2'},
 'mode': 'S0_then_Is_then_In_separate_sequential_targets',
 'budgets': {'activeSeconds': 416,
             'outerCleanupSeconds': 58,
             'publicationReserveSeconds': 12,
             'upfrontSequenceSeconds': 360,
             'controlSeconds': 120,
             'phaseSeconds': [5, 40, 45, 15, 13, 2],
             'phaseCumulativeSeconds': [5, 45, 90, 105, 118, 120],
             'commandWorkSeconds': 43,
             'commandUnwindSeconds': 2,
             'anchorExchangeSeconds': 4,
             'cutExchangeSeconds': 6,
             'mutationLocalSeconds': 4,
             'mutationLocalUnwindSeconds': 2},
 'caps': {'script': 134217728,
          'strictCatalog': 8388608,
          'catalogRecords': 20000,
          'catalogDepth': 5,
          'catalogScalarUtf8': 65536,
          'fixedCatalog': 32768,
          'fixedQuery': 16384,
          'partialProjection': 2048,
          'retainedControlCuts': 3,
          'descriptor': 16384,
          'Praw': 2000,
          'Pcanonical': 2000,
          'Wraw': 2000,
          'Wcanonical': 288,
          'frame': 4096,
          'writerStdout': 1048576,
          'observerStdout': 49152,
          'stderr': 65536,
          'observerSuccessStderr': 0,
          'mutationSql': 2048,
          'probeRequests': 16384,
          'allInjectedBytes': 16384,
          'S0Receipt': 24576,
          'branchReceipt': 10240,
          'plaintext': 65536,
          'envelope': 98304,
          'retainedControlCanonicalEach': 32768,
          'retainedControlCanonicalTotal': 98304},
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
 'queries': {'P': "SELECT pg_catalog.concat('C1P/@N@/@SS@/', "
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
             'Q': "SELECT pg_catalog.concat('C1B/@N@/@SS@/', pg_catalog.pg_backend_pid());\n",
             'W': 'BEGIN ISOLATION LEVEL READ COMMITTED READ ONLY;\n'
                  "SET LOCAL statement_timeout = '1s';\n"
                  "SET LOCAL lock_timeout = '1s';\n"
                  'SET LOCAL search_path = pg_catalog;\n'
                  "SET LOCAL TimeZone = 'UTC';\n"
                  "SET LOCAL DateStyle = 'ISO, YMD';\n"
                  "SELECT pg_catalog.concat('C1O/@N@/@SS@/@R@/',\n"
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
                  'ROLLBACK;\n'},
 'queryPins': {'P': {'bytes': 926,
                     'sha256': '7a74fb3a914f4d30cb2e24546f81404d69711d5168897601fcb3f79fde8ac7cc'},
               'Q': {'bytes': 72,
                     'sha256': '1daaee2b1ee28e2fedfed912b5fdc619e0d424ce7c5eb9f13363921dbc69a150'},
               'W': {'bytes': 1012,
                     'sha256': '18fe2abdee0a79061138bab9631483aa19eee5b3ede3a487ce17df571809af68'}},
 'catalogQuery': {'path': 'scripts/rf1086_catalog_causal.sql',
                  'bytes': 7073,
                  'sha256': '26258eb31ea9862019667789e27f8d87acce756a4d451d209bfa38df79f325d5'},
 'strictCatalogQuery': {'path': 'scripts/rf1086_identity_restore.py',
                        'symbol': 'CATALOG_SQL',
                        'sourceSha256': '84676b841fe0077fb64befe7de3a972422e311e020e0a485696e95ee3b55ae2d',
                        'rewrite': 'none'},
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
 'sequence': {'domain': '00..06',
              'count': 'len(S0.exchanges)+1',
              'mapping': 'ordered original descriptor points; insert post at mutation cut immediately '
                         'after its pre cut',
              'postMapsTo': 'same cut and unchanged original input offset',
              'P': 'all decoded values equal mapped S0 except own PID; validate against own epoch '
                   'baseline',
              'W': 'fresh values, existing 17-field policy, exact C1 Q; retain per-witness database '
                   'OID/backend_start/activity capacity'},
 'Is': {'cut': 'later of fresh graphql_schema/graphql_public_schema cuts',
        'preAcl': 'M=counts.passRows.MAIN; Z=counts.zeroOccurrenceRows; L=M-Z>0; j=max(schema '
                  'occurrence); 0<=j<L; occurrence and byte-cut order agree',
        'schemaOrder': ['graphql', 'graphql_public'],
        'owner': 'supabase_admin',
        'actor': 'supabase_admin',
        'sourceSlots': 'default owner slot0 plus four distinct new owner-grantor USAGE pairs in source '
                       'raw ACL order',
        'safeRole': '[A-Za-z_][A-Za-z0-9_]{0,62}',
        'preAclProfile': 'raw NULL and exact default owner CREATE/USAGE two nongrantable tuples',
        'statementTemplate': 'GRANT USAGE ON SCHEMA "@SCHEMA@" TO @GRANTEE_SQL@@OPTION@;\n',
        'granteeSql': 'PUBLIC iff public flag, else double-quoted safeRole',
        'option': ['', ' WITH GRANT OPTION'],
        'publicWithOption': 'reject',
        'transactionPrefix': 'BEGIN;\n',
        'transactionSuffix': 'COMMIT;\n',
        'statementCount': 8,
        'rawCatalogRowMask': {'kind': 'schema', 'fieldIndexes': [3]},
        'projectionReplacements': {'schemas': {'slots': [0, 1], 'fields': [1, 2]}},
        'unmodified': 'all other fields including defaults/initial privileges/net'},
 'In': {'cut': 'fresh pg_net_extension true cut',
        'owner': 'supabase_admin',
        'actor': 'supabase_admin',
        'extension': {'name': 'pg_net',
                      'version': '0.20.3',
                      'namespace': 'exact fresh source namespace; also equal failed/S0 and selected '
                                   'ledger semantic binding; never inferred from function schema net',
                      'owner': 'supabase_admin'},
        'sourceAttributes': 'all nonintervened normalized fields equal source, excluding ONLY proacl; '
                            'see exact mask',
        'sourceConfig': '{search_path=net}',
        'sourceSecurityDefiner': True,
        'preConfig': None,
        'preSecurityDefiner': False,
        'defaultCounts': [3, 4],
        'support': None,
        'binary': None,
        'definitionPredicate': 'entire normalized fixed function with row[5:8] and definition_sha256 '
                               'excluded; retain body, owner, identity, attributes, types, '
                               'definition_attributes, extensions',
        'prefixAcl': 'exact fresh S0 at same original cut; preserve through mutation',
        'finalAcl': 'exact failed/S0-final AND source raw ACL',
        'sql': 'BEGIN;\n'
               'ALTER FUNCTION '
               '"net"."http_get"("pg_catalog"."text","pg_catalog"."jsonb","pg_catalog"."jsonb","pg_catalog"."int4") '
               'SECURITY DEFINER;\n'
               'ALTER FUNCTION '
               '"net"."http_get"("pg_catalog"."text","pg_catalog"."jsonb","pg_catalog"."jsonb","pg_catalog"."int4") '
               "SET search_path TO 'net';\n"
               'ALTER FUNCTION '
               '"net"."http_post"("pg_catalog"."text","pg_catalog"."jsonb","pg_catalog"."jsonb","pg_catalog"."jsonb","pg_catalog"."int4") '
               'SECURITY DEFINER;\n'
               'ALTER FUNCTION '
               '"net"."http_post"("pg_catalog"."text","pg_catalog"."jsonb","pg_catalog"."jsonb","pg_catalog"."jsonb","pg_catalog"."int4") '
               "SET search_path TO 'net';\n"
               'COMMIT;\n',
        'sqlBytes': 607,
        'sqlSha256': 'c15b0d52d2489d6a3b72cf5caff3376f97158b9d43ca0ed3197fd00abfeac1f4',
        'statementCount': 4,
        'rawCatalogRowMask': {'kind': 'function', 'fieldIndexes': [6, 7]},
        'projectionReplacements': {'net': {'slots': [0, 1], 'fields': [1, 2, 3]}},
        'unmodified': 'all other fields including stage-specific '
                      'ACL/body/owner/defaults/attributes/membership/schema fields'},
 'rawFinalRule': {'baseline': 'failed.catalog exact bound bytes',
                  'replacement': 'two literal source.catalog row byte spans, after exact identity/shape '
                                 'and only permitted scalar differences; all row gap bytes outside '
                                 'changed scalars identical',
                  'selection': 'first JSON aggregate only; bounded structural span locator, never text '
                               'search',
                  'expected': 'baseline gaps plus source row spans in baseline order, streaming '
                              'compare/hash; no reserialization or sorting',
                  'lines2and3': 'unchanged exact bytes including separators/terminators',
                  'count': 2,
                  'sourceCopy': 'source row bytes only, never source full catalog'},
 'factoring': {'canonical': 'sorted compact ensure_ascii=true allow_nan=false ASCII JSON SHA256',
               'lossless': 'admitted decoded observations only; validate entire fresh catalog and '
                           'projection before factoring',
               'before': 'ref exact full S0 projection including snapshot',
               'after': 'fixed slot tuple plus actual new snapshot hash; unchanged components exactly '
                        'same-prefix S0',
               'P': 'actual PID, rest exact S0 reference',
               'W': 'per witness [databaseOidText,backendStartText,activityCapacityText]',
               'finalEnriched': 'hash Fsql normalized fixed catalog with only declared source-valued '
                                'fields replaced; initial/default/hook/event/extension fields retained'},
 'reasonStages': {'unobserved': ['dependency',
                                 'worker_deadline',
                                 'worker_failed',
                                 'worker_result_invalid',
                                 'control_unavailable'],
                  'admission': ['headroom',
                                'summary_oversized',
                                'binding',
                                'descriptor',
                                'source_profile',
                                'raw_prediction',
                                'pre_acl_order',
                                'nonce_collision',
                                'control_unavailable'],
                  'setup': ['deadline',
                            'command',
                            'ownership',
                            'tool',
                            'initialized_mismatch',
                            'control_unavailable'],
                  'transport': ['deadline',
                                'command',
                                'input',
                                'frame',
                                'session',
                                'observer',
                                'partial_catalog',
                                'prefix_mismatch',
                                'source_profile',
                                'immediate_prediction_mismatch',
                                'collateral_change',
                                'control_unavailable'],
                  'final': ['deadline',
                            'command',
                            'raw_prediction_mismatch',
                            'fingerprint_mismatch',
                            'enriched_prediction_mismatch',
                            'control_unavailable'],
                  'cleanup': ['cleanup_unproved', 'parent_cleanup', 'control_unavailable'],
                  'composition': ['deadline', 'summary_oversized', 'control_unavailable']},
 'receiptKeys': {'unavailable': ['schema', 'kind', 'status', 'reason', 'stage', 'point'],
                 'positive': ['schema',
                              'kind',
                              'status',
                              'bindings',
                              'target',
                              'tool',
                              'nonce',
                              'mutation',
                              'admission',
                              'exchanges',
                              'delivery',
                              'final',
                              'cleanup'],
                 'bindings': ['s0', 'configuration', 'expectation'],
                 'target': ['id', 'previous', 'initialized'],
                 'mutation': ['point', 'sql'],
                 'admissionIs': ['controlSnapshot'],
                 'admissionIn': ['controlSnapshot', 'definition', 'prefixAcl'],
                 'exchange': ['point', 'input', 'pid', 'witnesses', 'observer', 'catalog'],
                 'catalogRef': ['mode'],
                 'catalogPatch': ['mode', 'snapshot', 'values'],
                 'delivery': ['original', 'probes', 'mutation', 'frames', 'writer'],
                 'final': ['fingerprint', 'enriched', 'raw'],
                 'raw': ['expected', 'actual', 'outside'],
                 'cleanup': ['children', 'resources'],
                 'expectation': ['schema',
                                 'kind',
                                 'configuration',
                                 'input',
                                 'source',
                                 'failed',
                                 'selected',
                                 'sql',
                                 'replacements',
                                 'sourceProfile',
                                 'raw'],
                 'expectationSourceAndFailed': ['strict', 'enriched'],
                 'expectationSelected': ['kind', 'index', 'offset', 'semanticSha256'],
                 'expectationRaw': ['expected', 'outside']},
 'positiveStatus': 'prediction_matched',
 'negativeStatus': 'unavailable',
 'cleanupPositive': {'children': 'reaped',
                     'resources': 'removed',
                     'requires': 'actual per-control owner empty/no uncertainty and confirmed '
                                 'owned-resource removal, plus parent publication gates'},
 'expectationSharing': 'No public full declaration: bindings.expectation is H(E). Reader rebuilds E '
                       'from validated same-envelope S0, authenticated phases, config and branch '
                       'raw.expected/outside attestations. Common input/script/ledger/descriptor '
                       'inherit S0; raw source-row substitution and prior-to-mutation timing remain '
                       'authenticated producer evidence, not reader-reconstructed raw proof.',
 'sourceProfileCommitments': {'Is': 'H([causal-is-slots-v1, two arrays of five [granteeIsPublic, '
                                    'granteeOrNull, grantor, rights, grantOption] slots in exact source '
                                    'ACL order; slot0 rights=UC, others=U])',
                              'In': 'two H([causal-net-definition-v1, slot, full normalized source '
                                    'function after deleting definition_sha256 and removing row '
                                    'indexes5,6,7 simultaneously]); original row identity/owner and '
                                    'every other object field remain'},
 'cache': {'retained': 'normalized snapshots only, no raw lines',
           'stageSeal': 'after that observer EOF/exit0/wait and owner completion',
           'wholeSeal': 'only after matched S0 and confirmed cleanup',
           'overflow': 'branch unavailable; otherwise valid S0 remains valid',
           'erase': 'after both branches or sequence exit/fatal failure'},
 's0Profile': {'schema': 's0-config-v2',
               'receipt': 's0-checkpoint-v2',
               'configuration': '175e7d6d253822d5f4a3d05369ddba54380f77e63bdd077c5839b8b0145e3f08',
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
                             'rf1086_causal_catalog.py']}}

SCHEMA = CONFIG['branchReceipt']
CAPS = CONFIG['caps']
KINDS = ('Is', 'In')
OWNER = 'supabase_admin'
ROLE = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,62}')


class Unavailable(ValueError):
    """Finite failure only; rejected private values never enter exception text."""
    def __init__(self, reason='protocol_invalid'):
        allowed = {'protocol_invalid', 'source_profile', 'raw_prediction', 'pre_acl_order',
                   'prefix_mismatch', 'collateral_change', 'immediate_prediction_mismatch', 'deadline'}
        self.reason = reason if reason in allowed else 'protocol_invalid'
        super().__init__(self.reason)


def _require(condition, reason='protocol_invalid'):
    if not condition:
        raise Unavailable(reason)


def _closed(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Unavailable:
            raise
        except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
            raise Unavailable() from None
    return checked


def _check(deadline):
    _require(type(deadline) in (int, float) and math.isfinite(deadline))
    _require(time.monotonic() < deadline, 'deadline')


def _keys(value, names):
    _require(type(value) is dict and set(value) == set(names))


def _integer(value, low, high):
    _require(type(value) is int and low <= value <= high)


def _hash(value):
    _require(type(value) is str and s0.HASH.fullmatch(value) is not None)


def _kind(value):
    _require(type(value) is str and value in KINDS)
    return value


@_closed
def canonical(value):
    result = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                        separators=(',', ':')).encode('ascii')
    _require(len(result) <= CAPS['retainedControlCanonicalTotal'])
    return result


@_closed
def commitment(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _stream(value, cap):
    _keys(value, ('bytes', 'sha256')); _integer(value['bytes'], 1, cap); _hash(value['sha256'])


def _point(value):
    _require(type(value) in (tuple, list) and len(value) == 2
             and type(value[0]) is str and value[0] in ('anchor', 'cut', 'post'))
    _integer(value[1], 0, 2)
    return tuple(value)


@_closed
def unavailable(kind, reason, stage, point=None):
    value = dict(schema=SCHEMA, kind=kind, status='unavailable', reason=reason,
                 stage=stage, point=None if point is None else list(point))
    return validate_unavailable(value)


@_closed
def validate_unavailable(value, *, kind=None):
    _keys(value, CONFIG['receiptKeys']['unavailable'])
    _require(value['schema'] == SCHEMA and value['status'] == 'unavailable')
    _kind(value['kind']); _require(kind is None or _kind(kind) == value['kind'])
    stage, reason = value['stage'], value['reason']
    _require(type(stage) is str and stage in CONFIG['reasonStages']
             and type(reason) is str and reason in CONFIG['reasonStages'][stage])
    if value['point'] is not None:
        _require(stage == 'transport' and type(value['point']) is list); _point(value['point'])
    return value


def _substitutions(nonce, sequence):
    _require(type(nonce) is str and s0.NONCE.fullmatch(nonce) is not None)
    _integer(sequence, 0, 6)
    return {'@N@': nonce, '@SS@': f'{sequence:02d}'}


@_closed
def probe(nonce, sequence):
    values = _substitutions(nonce, sequence)
    return tuple(s0._substitute(CONFIG['queries'][key], values).encode('ascii') for key in ('P', 'Q'))


@_closed
def witness_request(nonce, sequence, role, pid):
    values = _substitutions(nonce, sequence)
    _require(type(role) is str and role in ('anchor', 'before', 'after'))
    _integer(pid, 1, 2147483647)
    return s0._substitute(CONFIG['queries']['W'], values | {'@R@': role, '@PID@': str(pid)}).encode('ascii')


@_closed
def parse_session(payload, *, point, descriptor, baseline=None):
    kind, index = _point(point)
    return s0.parse_session(payload, point=('cut' if kind == 'post' else kind, index),
                            descriptor=descriptor, baseline=baseline)


@_closed
def parse_witness(payload, *, nonce, sequence, session, epoch_witness=None):
    query = probe(nonce, sequence)[1][:-1].decode('ascii')
    return s0._witness_fields(s0._json(payload, CAPS['Wraw']), session=session, query=query,
                              epoch_witness=epoch_witness)


def _normal(catalog):
    """Inputs are already deep-validated; enforce bounded normalized carrier here."""
    _keys(catalog, ('serverVersion', 'schemas', 'functions', 'hooks', 'events', 'extensions'))
    _integer(catalog['serverVersion'], 170006, 170006)
    for name, count in (('schemas', 2), ('functions', 2), ('hooks', 3), ('events', 3), ('extensions', 2)):
        _require(type(catalog[name]) is list and len(catalog[name]) <= count)
    _require(len(canonical(catalog)) <= CAPS['retainedControlCanonicalEach'])
    return catalog


def _item(catalog, group, identity):
    rows = [v for v in catalog[group] if type(v) is dict and v.get('identity') == identity]
    _require(len(rows) == 1, 'source_profile')
    return rows[0]


def _schema(catalog, index):
    item = _item(catalog, 'schemas', capture.SCHEMAS[index])
    _keys(item, ('identity', 'row', 'defaults', 'grants', 'default_grants', 'initial', 'extensions'))
    _require(type(item['row']) is list and len(item['row']) == 4
             and item['row'][:2] == capture.SCHEMAS[index] and item['row'][2] == OWNER, 'source_profile')
    return item


def _function(catalog, index):
    item = _item(catalog, 'functions', capture.NET_IDENTITIES[index])
    _keys(item, ('identity', 'row', 'definition_sha256', 'body_sha256', 'attributes',
                 'types', 'extensions', 'definition_attributes'))
    row = item['row']; attrs = item['attributes']
    _require(type(row) is list and len(row) == 8 and row[:4] == capture.NET_IDENTITIES[index]
             and row[4] == OWNER and type(row[6]) is bool
             and row[7] in (None, '{search_path=net}'), 'source_profile')
    _require(row[5] is None or type(row[5]) is str and len(row[5].encode('utf8')) <= 8192, 'source_profile')
    for key in ('definition_sha256', 'body_sha256'): _hash(item[key])
    _require(type(attrs) is list and len(attrs) == 8 and attrs[:3] == ['plpgsql', 'bigint', 'f']
             and attrs[3] in ('i', 's', 'v') and attrs[5] in ('s', 'r', 'u')
             and all(type(attrs[i]) is bool for i in (4, 6, 7)) and attrs[7] is False, 'source_profile')
    _require(item['types'] == [['pg_catalog', name] for name in capture.NET_TYPES[index]], 'source_profile')
    capture._definition_attributes(item['definition_attributes'], len(capture.NET_TYPES[index]))
    definition = item['definition_attributes']
    _require(definition['default_count'] == (3, 4)[index] and definition['support'] is None
             and definition['binary'] is None, 'source_profile')
    _require(item['extensions'] == [['pg_net', '0.20.3', OWNER]], 'source_profile')
    return item


def _extension(catalog):
    rows = [r for r in catalog['extensions'] if type(r) is list and r and r[0] == 'pg_net']
    _require(len(rows) == 1 and len(rows[0]) == 4 and rows[0][1] == '0.20.3'
             and rows[0][3] == OWNER and type(rows[0][2]) is str, 'source_profile')
    return rows[0]


def _default_grants():
    return [[OWNER, False, OWNER, right, False] for right in ('CREATE', 'USAGE')]


def _default_schema(item):
    _require(item['defaults'] == '{supabase_admin=UC/supabase_admin}'
             and item['default_grants'] == _default_grants(), 'source_profile')


def _schema_slots(source):
    slots, statements = [], []
    for index, schema in enumerate(CONFIG['Is']['schemaOrder']):
        item = _schema(source, index); _default_schema(item)
        raw = item['row'][3]
        _require(type(raw) is str and len(raw.encode('utf8')) <= 8192
                 and raw.startswith('{') and raw.endswith('}'), 'source_profile')
        parts = raw[1:-1].split(',')
        _require(len(parts) == 5 and parts[0] == f'{OWNER}=UC/{OWNER}', 'source_profile')
        current = [[False, OWNER, OWNER, 'UC', False]]
        grants, recipients = _default_grants(), set()
        for part in parts[1:]:
            matched = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]{0,62}|)=U(\*)?/supabase_admin', part)
            _require(matched is not None, 'source_profile')
            name, option = matched[1], matched[2] is not None
            public = not name
            _require(name != OWNER and name not in recipients and not (public and option), 'source_profile')
            recipients.add(name)
            current.append([public, None if public else name, OWNER, 'U', option])
            grants.append([OWNER, public, None if public else name, 'USAGE', option])
            grantee = 'PUBLIC' if public else '"'+name+'"'
            statements.append(s0._substitute(CONFIG['Is']['statementTemplate'], {
                '@SCHEMA@': schema, '@GRANTEE_SQL@': grantee,
                '@OPTION@': ' WITH GRANT OPTION' if option else ''}))
        _require(item['grants'] == sorted(grants, key=canonical), 'source_profile')
        slots.append(current)
    sql = (CONFIG['Is']['transactionPrefix']+''.join(statements)+CONFIG['Is']['transactionSuffix']).encode('ascii')
    _require(0 < len(sql) <= CAPS['mutationSql'])
    return slots, sql


def _definition(item):
    value = {key: deepcopy(v) for key, v in item.items() if key != 'definition_sha256'}
    value['row'] = [deepcopy(v) for i, v in enumerate(item['row']) if i not in (5, 6, 7)]
    return value


def _definition_hash(item, index):
    return commitment(['causal-net-definition-v1', index, _definition(item)])


def _acl_hash(item, index):
    return commitment(['causal-net-acl-v1', index, item['row'][5]])


def _raw_binding(value):
    _keys(value, ('expected', 'outside')); _stream(value['expected'], CAPS['strictCatalog']); _hash(value['outside'])
    return value


def _selection(kind, ledger):
    rows = ledger['selected']
    _require(type(rows) is list and len(rows) == 3)
    names = ('graphql_schema', 'graphql_public_schema') if kind == 'Is' else ('pg_net_extension',)
    found = [(i, r) for i, r in enumerate(rows) if r['kind'] in names]
    _require(len(found) == len(names) and {r['kind'] for _, r in found} == set(names))
    if kind == 'Is':
        main, zero = ledger['counts']['passRows']['MAIN'], ledger['counts']['zeroOccurrenceRows']
        _integer(main, 0, 20000); _integer(zero, 0, 20000)
        limit = main-zero
        _require(limit > 0, 'pre_acl_order')
        for _, row in found:
            _integer(row['occurrence'], 0, 40000)
            _require(row['occurrence'] < limit, 'pre_acl_order')
        _require(len({r['occurrence'] for _, r in found}) == 2 and
                 sorted(found, key=lambda p: p[1]['cut']) == sorted(found, key=lambda p: p[1]['occurrence']),
                 'pre_acl_order')
    return max(found, key=lambda p: p[1]['cut'])


@dataclass(frozen=True, repr=False)
class Policy:
    """Private immutable normalized references; repr exposes no SQL/catalog values."""
    kind: str
    point: tuple
    sql: bytes
    _source: bytes
    _failed: bytes
    _selected: bytes
    _raw: bytes
    _profile: bytes

    @property
    def selected(self): return json.loads(self._selected)

    @property
    def raw_binding(self): return json.loads(self._raw)

    @property
    def source_catalog(self): return json.loads(self._source)

    @property
    def expected_final(self):
        return expected_catalog(self.kind, json.loads(self._failed), self.source_catalog)


@_closed
def expected_catalog(kind, control_catalog, source_catalog):
    _kind(kind); _normal(control_catalog); _normal(source_catalog)
    result = deepcopy(control_catalog)
    for index in range(2):
        if kind == 'Is':
            actual, source = _schema(result, index), _schema(source_catalog, index)
            actual['row'][3], actual['grants'] = source['row'][3], deepcopy(source['grants'])
        else:
            actual, source = _function(result, index), _function(source_catalog, index)
            actual['row'][6:8] = source['row'][6:8]
            actual['definition_sha256'] = source['definition_sha256']
    return result


@_closed
def prepare_policy(kind, *, source_catalog, failed_catalog, ledger, raw_binding, deadline):
    _check(deadline)
    result = _prepare_policy(kind, source_catalog, failed_catalog, ledger, raw_binding)
    _check(deadline)
    return result


def _prepare_policy(kind, source_catalog, failed_catalog, ledger, raw_binding):
    # Pure bounded reconstruction shared by producer and receipt validator. Only
    # the producer owns a runtime deadline; validation does not create a new one.
    _kind(kind); _normal(source_catalog); _normal(failed_catalog); _raw_binding(raw_binding)
    index, selected = _selection(kind, ledger)
    if kind == 'Is':
        slots, sql = _schema_slots(source_catalog)
        profile = commitment(['causal-is-slots-v1', slots])
        for i in range(2):
            a, b = _schema(source_catalog, i), _schema(failed_catalog, i)
            _require(a['row'][:3] == b['row'][:3] and a['row'][3] != b['row'][3], 'source_profile')
    else:
        _require(_extension(source_catalog) == _extension(failed_catalog), 'source_profile')
        sql = CONFIG['In']['sql'].encode('ascii'); profile = []
        for i in range(2):
            a, b = _function(source_catalog, i), _function(failed_catalog, i)
            _require(a['row'][6:] == [True, '{search_path=net}'] and b['row'][6:] == [False, None]
                     and a['row'][:6] == b['row'][:6], 'source_profile')
            profile.append(_definition_hash(a, i))
    _require(0 < len(sql) <= CAPS['mutationSql'])
    result = Policy(kind, ('cut', index), sql, canonical(source_catalog), canonical(failed_catalog),
                    canonical(selected), canonical(raw_binding), canonical(profile))
    # Final expected rows/shape are known before any mutation; no private input aliases.
    _normal(result.expected_final)
    return result


@_closed
def ordered_points(policy, descriptor, ledger):
    _require(type(policy) is Policy)
    result = []
    for point, offset in s0.ordered_points(descriptor, ledger):
        result.append((point, offset))
        if point == policy.point: result.append((('post', point[1]), offset))
    _require(len(result) in (6, 7) and sum(p[0] == 'post' for p, _ in result) == 1)
    return tuple(result)


@_closed
def admit_mutation(policy, actual_catalog, control_catalog):
    _require(type(policy) is Policy); _normal(actual_catalog); _normal(control_catalog)
    _require(canonical(actual_catalog) == canonical(control_catalog), 'prefix_mismatch')
    result = {'controlSnapshot': s0.snapshot_commitment(control_catalog)}
    if policy.kind == 'Is':
        for i in range(2):
            item = _schema(actual_catalog, i); _default_schema(item)
            _require(item['row'][3] is None and item['grants'] == _default_grants(), 'source_profile')
    else:
        source = policy.source_catalog
        _require(_extension(source) == _extension(actual_catalog), 'source_profile')
        definitions, acls = [], []
        for i in range(2):
            observed, expected = _function(actual_catalog, i), _function(source, i)
            _require(observed['row'][6:] == [False, None]
                     and canonical(_definition(observed)) == canonical(_definition(expected)), 'source_profile')
            definitions.append(_definition_hash(observed, i)); acls.append(_acl_hash(observed, i))
        result.update(definition=definitions, prefixAcl=acls)
    return result


@_closed
def factor_catalog(policy, actual_catalog, control_catalog, *, after, selected):
    _require(type(policy) is Policy and type(after) is bool)
    _normal(actual_catalog); _normal(control_catalog)
    expected = expected_catalog(policy.kind, control_catalog, policy.source_catalog) if after else control_catalog
    _require(canonical(actual_catalog) == canonical(expected), 'collateral_change' if after else 'prefix_mismatch')
    reference = json.loads(policy._failed)
    observed = s0.project_normalized(actual_catalog, selected=selected, reference_catalog=reference)
    base = s0.project_normalized(control_catalog, selected=selected, reference_catalog=reference)
    if not after:
        _require(observed == base, 'prefix_mismatch')
        return {'mode': 'ref'}
    group, fields = ('schemas', (1, 2)) if policy.kind == 'Is' else ('net', (1, 2, 3))
    values = [[observed[group][i][j] for j in fields] for i in range(2)]
    expanded = deepcopy(base); expanded['snapshot'] = observed['snapshot']
    for i in range(2):
        _require(expanded[group][i] is not None, 'collateral_change')
        for j, value in zip(fields, values[i], strict=True): expanded[group][i][j] = value
    _require(expanded == observed, 'collateral_change')
    s0._projection(expanded)
    return {'mode': 'patch', 'snapshot': observed['snapshot'], 'values': values}


def _replacements(policy):
    source = policy.source_catalog
    if policy.kind == 'Is':
        return [[s0._component('schema-acl', i, _schema(source, i)['row'][3]),
                 s0._component('schema-grants', i, _schema(source, i)['grants'])] for i in range(2)]
    return [[_function(source, i)['definition_sha256'], True, 1] for i in range(2)]


@_closed
def expectation(policy, *, s0_receipt, f2_input):
    _require(type(policy) is Policy)
    source, failed = policy.source_catalog, json.loads(policy._failed)
    return {'schema': 'causal-expectation-v1', 'kind': policy.kind, 'configuration': commitment(CONFIG),
        'input': s0_receipt['bindings']['input'],
        'source': {'strict': f2_input['before']['catalog'], 'enriched': s0.snapshot_commitment(source)},
        'failed': {'strict': f2_input['failed']['catalog'], 'enriched': s0.snapshot_commitment(failed)},
        'selected': {'kind': policy.selected['kind'], 'index': policy.point[1], 'offset': policy.selected['cut'],
                     'semanticSha256': policy.selected['semanticSha256']},
        'sql': {'bytes': len(policy.sql), 'sha256': hashlib.sha256(policy.sql).hexdigest()},
        'replacements': _replacements(policy), 'sourceProfile': json.loads(policy._profile),
        'raw': policy.raw_binding}


def _expanded_witness(dynamic, session, nonce, sequence):
    _require(type(dynamic) is list and len(dynamic) == 3)
    oid, started, capacity = dynamic
    return [session[0], oid, session[1], oid, session[0], started,
            'idle', None, None, None, probe(nonce, sequence)[1][:-1].decode('ascii'),
            'UTF8', 'UTF8', capacity, 'B', 'postmaster', 'integer']


def _catalog_patch(value, base, policy, *, after, selected, reference):
    if not after:
        _keys(value, CONFIG['receiptKeys']['catalogRef']); _require(value['mode'] == 'ref')
        result = deepcopy(base)
    else:
        _keys(value, CONFIG['receiptKeys']['catalogPatch']); _require(value['mode'] == 'patch')
        _hash(value['snapshot'])
        # Canonical equality preserves bool/int distinctions in the closed tuples.
        _require(canonical(value['values']) == canonical(_replacements(policy)))
        result = deepcopy(base); result['snapshot'] = value['snapshot']
        group, fields = ('schemas', (1, 2)) if policy.kind == 'Is' else ('net', (1, 2, 3))
        for i in range(2):
            _require(result[group][i] is not None)
            for j, replacement in zip(fields, value['values'][i], strict=True):
                result[group][i][j] = replacement
    s0._projection(result); s0._selected(result, selected, reference)
    return result


def _visible_targets(value, s0_receipt, metadata, other):
    target = value['target']; _keys(target, CONFIG['receiptKeys']['target'])
    for item in target.values(): _hash(item)
    old = s0_receipt['target']
    _require(target['initialized'] == old['initialized'])
    _require(target['id'] not in {target['previous'], old['id'], old['previous'],
                                 metadata['source'], metadata['sourceAuth']})
    _require(target['previous'] not in {old['previous'], metadata['source'], metadata['sourceAuth']})
    if value['kind'] == 'Is': _require(target['previous'] == old['id'])
    _substitutions(value['nonce'], 0); _require(value['nonce'] != s0_receipt['nonce'])
    if other is not None:
        _require(type(other) is dict and other.get('kind') in KINDS and other['kind'] != value['kind'])
        if other.get('status') == 'unavailable':
            validate_unavailable(other)
        else:
            _require(other.get('schema') == SCHEMA and other.get('status') == CONFIG['positiveStatus'])
            _keys(other['target'], CONFIG['receiptKeys']['target'])
            for item in other['target'].values(): _hash(item)
            _substitutions(other['nonce'], 0)
            _require(target['id'] != other['target']['id'] and value['nonce'] != other['nonce'])
            is_value, in_value = (value, other) if value['kind'] == 'Is' else (other, value)
            _require(in_value['target']['previous'] == is_value['target']['id'])
    # A failed sibling has no public target: its identity/order stays an explicit
    # producer attestation. This never substitutes for the runtime all-ID check.


@_closed
def validate_receipt(value, *, s0_receipt, fsql, f2_input, metadata, inventory=None,
                     published=False, worker_outcome=None, owned_cleanup=None, other=None):
    if type(value) is dict and value.get('status') == 'unavailable':
        return validate_unavailable(value)
    _keys(value, CONFIG['receiptKeys']['positive'])
    _require(value['schema'] == SCHEMA and value['status'] == CONFIG['positiveStatus']
             and len(canonical(value)) <= CAPS['branchReceipt'])
    _kind(value['kind'])
    _require(type(published) is bool)
    if published:
        _require(worker_outcome == 'completed' and owned_cleanup is True)
    else:
        _require(worker_outcome is None and owned_cleanup is None)
    _require(s0.SCHEMA == CONFIG['s0Profile']['receipt']
             and s0.CONFIG['codeFiles'] == CONFIG['s0Profile']['codeFiles']
             and commitment(s0.CONFIG) == CONFIG['s0Profile']['configuration'])
    s0.validate_receipt(s0_receipt, fsql=fsql, f2_input=f2_input, metadata=metadata,
        inventory=inventory, published=published, worker_outcome=worker_outcome, owned_cleanup=owned_cleanup)
    _require(s0_receipt['status'] == 'matched')
    ledger = fsql['ledger']; D = s0._descriptor(s0_receipt['references'], ledger)
    final = value['final']; _keys(final, CONFIG['receiptKeys']['final'])
    raw = final['raw']; _keys(raw, CONFIG['receiptKeys']['raw'])
    _stream(raw['actual'], CAPS['strictCatalog'])
    raw_binding = _raw_binding({'expected': raw['expected'], 'outside': raw['outside']})
    _require(raw['actual'] == raw['expected'])
    policy = _prepare_policy(value['kind'], metadata['phases']['source_pre_dump']['catalog'],
                             fsql['catalog'], ledger, raw_binding)
    _keys(value['bindings'], CONFIG['receiptKeys']['bindings'])
    _require(value['bindings'] == {'s0': commitment(s0_receipt), 'configuration': commitment(CONFIG),
        'expectation': commitment(expectation(policy, s0_receipt=s0_receipt, f2_input=f2_input))})
    _visible_targets(value, s0_receipt, metadata, other)
    _keys(value['tool'], ('version', 'sha256'))
    _require(value['tool']['version'] == '17.6'); _hash(value['tool']['sha256'])
    mutation = value['mutation']; _keys(mutation, CONFIG['receiptKeys']['mutation'])
    _require(type(mutation['point']) is list and _point(mutation['point']) == policy.point)
    expected_sql = {'bytes': len(policy.sql), 'sha256': hashlib.sha256(policy.sql).hexdigest()}
    _stream(mutation['sql'], CAPS['mutationSql']); _require(mutation['sql'] == expected_sql)
    controls = {tuple(v['point']): v for v in s0_receipt['exchanges']}
    admission = value['admission']; _keys(admission, CONFIG['receiptKeys']['admission'+policy.kind])
    _hash(admission['controlSnapshot'])
    _require(admission['controlSnapshot'] == controls[policy.point]['catalog']['snapshot'])
    if policy.kind == 'In':
        _require(admission['definition'] == json.loads(policy._profile))
        _require(type(admission['prefixAcl']) is list and len(admission['prefixAcl']) == 2)
        for item in admission['prefixAcl']: _hash(item)
        # The private raw ACL comparisons were made before factoring. A compound
        # net-other commitment cannot independently reveal those two ACL hashes.
    points = ordered_points(policy, D, ledger); exchanges = value['exchanges']
    _require(type(exchanges) is list and len(exchanges) == len(points))
    baselines, witnesses = {}, {}
    after, writer_minimum = False, 0
    for sequence, (exchange, (point, offset)) in enumerate(zip(exchanges, points, strict=True)):
        _keys(exchange, CONFIG['receiptKeys']['exchange'])
        _require(type(exchange['point']) is list and _point(exchange['point']) == point)
        _require(type(exchange['input']) is list and len(exchange['input']) == 2)
        for item in exchange['input']: _integer(item, offset, offset)
        kind, index = point; mapped = ('cut', index) if kind == 'post' else point
        control = controls[mapped]
        epoch = index if kind == 'anchor' else D['cuts'][index][0]
        _integer(exchange['pid'], 1, 2147483647)
        session = deepcopy(control['session']); session[1] = exchange['pid']
        s0._session(session, point=mapped, descriptor=D,
                    baseline=None if kind == 'anchor' else baselines[epoch])
        roles = ('anchor',) if kind == 'anchor' else ('before', 'after')
        records = exchange['witnesses']
        _require(type(records) is list and len(records) == len(roles))
        minimum, expanded = 0, []
        for record, role in zip(records, roles, strict=True):
            witness = _expanded_witness(record, session, value['nonce'], sequence)
            s0._witness_fields(witness, session=session,
                query=probe(value['nonce'], sequence)[1][:-1].decode('ascii'),
                epoch_witness=None if kind == 'anchor' else witnesses[epoch])
            frame_size = len(f"C1O/{value['nonce']}/{sequence:02d}/{role}/")+2*len(s0._utf8(witness))+1
            _require(frame_size <= CAPS['frame']); minimum += frame_size; expanded.append(witness)
        s0._io(exchange['observer'], CAPS['observerStdout'], 0, minimum)
        if kind == 'anchor':
            _require(exchange['catalog'] is None)
            if epoch: _require((session[1], expanded[0][5]) != (witnesses[epoch-1][2], witnesses[epoch-1][5]))
            baselines[epoch], witnesses[epoch] = session, expanded[0]
        else:
            if kind == 'post': after = True
            _catalog_patch(exchange['catalog'], control['catalog'], policy, after=after,
                           selected=ledger['selected'][index], reference=fsql['catalog'])
        p_size = 40+2*len(s0._utf8(session))+1
        _require(p_size <= CAPS['frame']); writer_minimum += p_size+40+len(str(session[1]))+1
    delivery = value['delivery']; _keys(delivery, CONFIG['receiptKeys']['delivery'])
    _stream(delivery['original'], CAPS['script']); _require(delivery['original'] == fsql['stream'])
    probes = b''.join(part for seq in range(len(points)) for part in probe(value['nonce'], seq))
    _require(len(probes) <= CAPS['probeRequests'] and len(probes)+len(policy.sql) <= CAPS['allInjectedBytes'])
    _stream(delivery['probes'], CAPS['probeRequests'])
    _require(delivery['probes'] == {'bytes': len(probes), 'sha256': hashlib.sha256(probes).hexdigest()})
    _stream(delivery['mutation'], CAPS['mutationSql']); _require(delivery['mutation'] == expected_sql)
    _require(type(delivery['frames']) is list and len(delivery['frames']) == 2)
    for item in delivery['frames']: _integer(item, len(points), len(points))
    s0._io(delivery['writer'], CAPS['writerStdout'], CAPS['stderr'], writer_minimum)
    _keys(final['fingerprint'], ('roles', 'catalog', 'auth', 'companyMemberships'))
    for digest in final['fingerprint'].values(): _hash(digest)
    _require(final['fingerprint'] == (metadata['failed'] | {'catalog': raw['expected']['sha256']}))
    _require(final['enriched'] == s0.snapshot_commitment(policy.expected_final))
    _keys(value['cleanup'], CONFIG['receiptKeys']['cleanup'])
    _require(value['cleanup'] == {'children': 'reaped', 'resources': 'removed'})
    return value


class _SizingReceipt(dict):
    """Serialized width bound only; exact-type positive validation rejects it."""


@_closed
def maximum_receipt(kind, *, fsql, f2_input, metadata, inventory, descriptor):
    _kind(kind)
    ledger = s0._dependencies(fsql, f2_input, metadata, inventory)
    D = s0.validate_descriptor(descriptor, ledger, fsql['stream'])
    # No source admission is needed to calculate maximum widths. The eventual
    # receipt may be unavailable. Use the later schema cut or the extension cut.
    names = ('graphql_schema', 'graphql_public_schema') if kind == 'Is' else ('pg_net_extension',)
    index, selected = max(((i, v) for i, v in enumerate(ledger['selected']) if v['kind'] in names),
                          key=lambda pair: pair[1]['cut'])
    h, nonce, pid = 'f'*64, 'f'*32, 2147483647
    io = lambda out, err: dict(stdoutBytes=out, stderrBytes=err, stdoutEnd='eof', stderrEnd='eof', exitCode=0, reap='waited')
    points = []
    for point, offset in s0.ordered_points(D, ledger):
        points.append((point, offset))
        if point == ('cut', index): points.append((('post', index), offset))
    exchanges = []
    for point, offset in points:
        # A patch at every cut is wider than any valid ref/patch scheduling.
        patch = {'mode': 'patch', 'snapshot': h,
                 'values': [[h, h] if kind == 'Is' else [h, True, 1] for _ in range(2)]}
        exchanges.append({'point': list(point), 'input': [offset, offset], 'pid': pid,
            'witnesses': [['4294967295', '9999-12-31 23:59:59.999999+00', '1048576']
                          for _ in range(1 if point[0] == 'anchor' else 2)],
            'observer': io(CAPS['observerStdout'], 0), 'catalog': None if point[0] == 'anchor' else patch})
    admission = {'controlSnapshot': h}
    if kind == 'In': admission.update(definition=[h, h], prefixAcl=[h, h])
    stream = {'bytes': CAPS['strictCatalog'], 'sha256': h}
    result = _SizingReceipt(schema=SCHEMA, kind=kind, status=CONFIG['positiveStatus'],
        bindings={key: h for key in CONFIG['receiptKeys']['bindings']},
        target={'id': h, 'previous': h, 'initialized': h}, tool={'version': '17.6', 'sha256': h}, nonce=nonce,
        mutation={'point': ['cut', index], 'sql': {'bytes': CAPS['mutationSql'], 'sha256': h}},
        admission=admission, exchanges=exchanges,
        delivery={'original': fsql['stream'], 'probes': {'bytes': CAPS['probeRequests'], 'sha256': h},
            'mutation': {'bytes': CAPS['mutationSql'], 'sha256': h}, 'frames': [len(points)]*2,
            'writer': io(CAPS['writerStdout'], CAPS['stderr'])},
        final={'fingerprint': {key: h for key in ('roles', 'catalog', 'auth', 'companyMemberships')},
               'enriched': h, 'raw': {'expected': stream, 'actual': stream.copy(), 'outside': h}},
        cleanup={'children': 'reaped', 'resources': 'removed'})
    _require(len(canonical(result)) <= CAPS['branchReceipt'])
    return result
