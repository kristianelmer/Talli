"""Experimental catalog changes cannot replace strict recovery or publication gates."""
from copy import deepcopy
import hashlib
import time
from types import SimpleNamespace

import pytest

from test_rf1086_actual_replay import setup, key
from test_rf1086_full_sql_control import control, completed
from test_rf1086_causal_catalog import scenario, raw, expected
import rf1086_actual_replay as replay
import rf1086_actual_replay_package as package
import rf1086_identity_restore as identity


def digest(value):
    return hashlib.sha256(value).hexdigest()


@pytest.mark.parametrize('kind', ('Is', 'In'))
@pytest.mark.parametrize('fault', (None, 'roles', 'auth', 'companyMemberships', 'raw', 'enriched'))
def test_branch_final_uses_original_queries_exact_raw_and_all_other_fingerprints(
        tmp_path, monkeypatch, kind, fault):
    source, failed, source_catalog, failed_catalog = scenario()
    for catalog in (source_catalog, failed_catalog):
        catalog.update(serverVersion=170006, hooks=[], events=[], extensions=[])
    source_raw, failed_raw = raw(source), raw(failed)
    actual = raw(expected(kind))
    if fault == 'raw': actual = actual.replace(b'PRIVATE-CANARY', b'CHANGED-CANARY')
    predicted = deepcopy(failed_catalog)
    group, indices = ('schemas', (3,)) if kind == 'Is' else ('functions', (6, 7))
    for slot in (0, 1):
        for index in indices:
            predicted[group][slot]['row'][index] = source_catalog[group][slot]['row'][index]
    fingerprint = {'roles': digest(b'roles\n'), 'catalog': digest(failed_raw),
                   'auth': digest(b''), 'companyMemberships': digest(b'[]\n')}
    metadata = {'before': fingerprint | {'catalog': digest(source_raw)}, 'failed': fingerprint,
                'phases': {'source_pre_dump': {'catalog': source_catalog},
                           'mismatch': {'catalog': failed_catalog}}}
    calls, captures = [], []
    original_fingerprint = identity.fingerprint

    def track_capture(*args, catalog_capture, **kwargs):
        captures.append(catalog_capture)
        return original_fingerprint(*args, catalog_capture=catalog_capture, **kwargs)

    def run(args, deadline, **kwargs):
        statement = kwargs['data'].decode()
        calls.append(statement)
        if statement == identity.ROLE_SQL: return b'wrong' if fault == 'roles' else b'roles\n'
        if statement == identity.CATALOG_SQL: return actual
        if 'json_agg(tablename' in statement: return b'["a"]' if fault == 'auth' else b'[]'
        if 'from auth."a"' in statement: return b'["different"]'
        if 'public.company_memberships' in statement:
            return b'["different"]' if fault == 'companyMemberships' else b'[]\n'
        pytest.fail('unexpected query')

    def checked_snapshot(container, deadline, **kwargs):
        assert container == 'owned' and kwargs['target'] is True and kwargs['run'] is run
        assert kwargs['retained']._raw == actual
        return {'changed': True} if fault == 'enriched' else deepcopy(predicted)

    monkeypatch.setattr(identity, 'fingerprint', track_capture)
    monkeypatch.setattr(replay, '_snapshot', checked_snapshot)
    monkeypatch.setattr(replay, 'failed_state', lambda *a, **kw: pytest.fail('original failure comparator reused'))
    resources = replay._s0_resources(tmp_path, metadata, b'roles', failed_raw, {}, {}, source_raw=source_raw)
    policy = SimpleNamespace(kind=kind, expected_final=predicted)
    before_global = identity.checked
    if fault is None:
        result = resources.branch_final_state('owned', time.monotonic() + 10,
            run=run, branch_policy=policy, references=object())
        assert result['fingerprint'] == fingerprint | {'catalog': digest(actual)}
        assert result['raw']['expected'] == result['raw']['actual'] == {'bytes': len(actual), 'sha256': digest(actual)}
        assert result['enriched'] == replay.s0_protocol.snapshot_commitment(predicted)
    else:
        with pytest.raises((replay.PredictionUnavailable, replay.s0_control.ControlFailure)):
            resources.branch_final_state('owned', time.monotonic() + 10,
                run=run, branch_policy=policy, references=object())
    assert calls[:2] == [identity.ROLE_SQL, identity.CATALOG_SQL]
    assert captures and all(c._raw is None for c in captures)
    assert identity.checked is before_global
    assert metadata['failed']['catalog'] == digest(failed_raw)


@pytest.mark.parametrize('bad_binding', ('source', 'failed', 'source_row'))
def test_raw_prediction_checks_retained_bindings_before_any_query(tmp_path, bad_binding):
    source, failed, sc, fc = scenario()
    source_raw, failed_raw = raw(source), raw(failed)
    metadata = {'before': {'catalog': digest(source_raw)}, 'failed': {'catalog': digest(failed_raw)},
                'phases': {'source_pre_dump': {'catalog': sc}, 'mismatch': {'catalog': fc}}}
    if bad_binding == 'source': metadata['before']['catalog'] = '0' * 64
    if bad_binding == 'failed': metadata['failed']['catalog'] = '0' * 64
    if bad_binding == 'source_row': sc['schemas'][0]['row'][2] = 'changed'
    resources = replay._s0_resources(tmp_path, metadata, b'roles', failed_raw, {}, {}, source_raw=source_raw)
    with pytest.raises(replay.PredictionUnavailable):
        resources.raw_prediction('Is', time.monotonic() + 10)


@pytest.mark.parametrize('kind', ('Is', 'In'))
@pytest.mark.parametrize('value', ('unavailable', {}, None, {'kind': 'combined'}, True))
def test_full_v3_never_accepts_old_literals_or_untyped_branch_fields(control, kind, value):
    _, metadata, f2, optional, _, _ = control
    candidate = completed(f2, optional)
    candidate[kind] = value
    with pytest.raises(package.Unavailable):
        replay.validate_control(candidate, metadata)


@pytest.mark.parametrize('outcome', ('deadline', 'failed', 'result_invalid'))
def test_worker_loss_cannot_publish_branch_state_or_change_durable_literals(control, outcome):
    path, metadata, f2, optional, _, _ = control
    replay.checkpoint_f2(path, metadata, f2)
    saved = (path / 'f2.json').read_bytes()
    result = replay.fallback_result(path, metadata, outcome)
    assert replay.read_f2(path, metadata) == f2
    assert (path / 'f2.json').read_bytes() == saved
    assert (f2['S0'], f2['Is'], f2['In']) == (
        'unavailable', 'unavailable', 'archive_function_equivalence_unproved')
    for kind in ('Is', 'In'):
        assert result[kind]['status'] == 'unavailable'
        assert result[kind]['stage'] == 'unobserved'
        assert result[kind]['reason'] == replay.WORKER_REASONS[outcome]
    published = result | {'optionalWorkerOutcome': outcome, 'ownedCleanupComplete': True}
    assert replay.validate_published_control(published, metadata) == published
    for kind in ('Is', 'In'):
        changed = deepcopy(published)
        changed[kind]['reason'] = 'dependency'
        with pytest.raises(package.Unavailable): replay.validate_published_control(changed, metadata)


@pytest.mark.parametrize('missing', ('S0', 'Is', 'In'))
def test_parent_cleanup_must_redact_all_three_even_for_thin_results(control, missing):
    _, metadata, _, _, _, _ = control
    worker = replay.thin_control('worker_failed')
    result = worker | {'optionalWorkerOutcome': 'failed', 'ownedCleanupComplete': False,
                       'S0': replay.s0_protocol.unavailable('parent_cleanup', 'cleanup'),
                       **replay._unavailable_branches('parent_cleanup', 'cleanup')}
    assert replay.validate_published_control(result, metadata) == result
    result[missing] = worker[missing]
    with pytest.raises(package.Unavailable): replay.validate_published_control(result, metadata)


@pytest.mark.parametrize('branches', ({}, {'Is': {}}, {'Is': {}, 'In': {}, 'S0': {}}))
def test_composition_does_not_accept_arbitrary_top_level_overrides(control, branches):
    _, metadata, f2, optional, _, _ = control
    with pytest.raises(package.Unavailable):
        replay.fit_optional(f2, optional, metadata, branches=branches)


@pytest.fixture(params=(False, True), ids=('two-epochs', 'three-epochs'))
def positive_sequence(tmp_path, control, request):
    from test_rf1086_causal_protocol import valid_branch_context
    is_value, args, _, descriptor, _ = valid_branch_context(tmp_path, 'Is', extra_reconnect=request.param)
    in_value, other_args, _, _, _ = valid_branch_context(tmp_path, 'In', extra_reconnect=request.param)
    assert args == other_args
    in_value['target']['previous'] = is_value['target']['id']
    metadata = args['metadata']
    f2 = deepcopy(control[2])
    f2.update(fingerprint=metadata['failed'], catalog=metadata['phases']['mismatch']['catalog'],
              input=args['f2_input'], inventory=args['inventory'],
              sourceCommandSha256=metadata['phases']['source_pre_dump']['sourceCommandSha256'],
              sourceInstalledFiles=metadata['phases']['source_pre_dump']['files'])
    value = completed(f2, args['fsql']) | {'S0': args['s0_receipt'], 'Is': is_value, 'In': in_value}
    return value, f2, metadata, descriptor


def test_full_positive_sequence_needs_all_independent_and_parent_gates(positive_sequence):
    value, _, metadata, _ = positive_sequence
    assert replay.validate_control(value, metadata) is value
    published = value | {'optionalWorkerOutcome': 'completed', 'ownedCleanupComplete': True}
    assert replay.validate_published_control(published, metadata) is published
    for patch in ({'optionalWorkerOutcome': 'failed'}, {'ownedCleanupComplete': False},
                  {'schema': 'actual-image-control-v2'}):
        with pytest.raises(package.Unavailable):
            replay.validate_published_control(published | patch, metadata)


@pytest.mark.parametrize('corruption', ('same_target', 'wrong_previous', 'same_nonce', 'swapped_kind',
                                       'missing_s0', 'missing_ledger', 'old_s0', 'missing_code'))
def test_full_sequence_rejects_dangling_cross_branch_or_legacy_evidence(positive_sequence, corruption):
    original, _, metadata, _ = positive_sequence
    value, metadata = deepcopy((original, metadata))
    if corruption == 'same_target': value['In']['target']['id'] = value['Is']['target']['id']
    if corruption == 'wrong_previous': value['In']['target']['previous'] = value['S0']['target']['id']
    if corruption == 'same_nonce': value['In']['nonce'] = value['Is']['nonce']
    if corruption == 'swapped_kind': value['Is'], value['In'] = value['In'], value['Is']
    if corruption == 'missing_s0': value['S0'] = replay.s0_protocol.unavailable('dependency', 'admission')
    if corruption == 'missing_ledger': value['Fsql']['ledger'] = replay.sql_ledger.unavailable('summary', 'summary')
    if corruption == 'old_s0': value['S0']['schema'] = 's0-checkpoint-v1'
    if corruption == 'missing_code':
        del metadata['code']['rf1086_causal_catalog.py']
        value['input']['code'] = deepcopy(metadata['code'])
        value['S0']['bindings']['input'] = replay.causal_protocol.commitment(value['input'])
    with pytest.raises(package.Unavailable): replay.validate_control(value, metadata)


def test_sizing_redacts_both_dependents_before_the_control(positive_sequence, monkeypatch):
    value, f2, metadata, _ = positive_sequence
    fallback = value | replay._unavailable_branches('summary_oversized', 'composition')
    parent = {'optionalWorkerOutcome': 'result_invalid', 'ownedCleanupComplete': False}
    monkeypatch.setattr(replay, 'MAX_PLAINTEXT', len(package._encoded(fallback | parent)))
    result = replay.fit_optional(f2, value['Fsql'], metadata, s0=value['S0'],
                                branches={kind: value[kind] for kind in ('Is', 'In')})
    assert result == fallback and result['S0']['status'] == 'matched'
    smaller = fallback | {'S0': replay.s0_protocol.unavailable('summary_oversized', 'composition')}
    monkeypatch.setattr(replay, 'MAX_PLAINTEXT', len(package._encoded(smaller | parent)))
    result = replay.fit_optional(f2, value['Fsql'], metadata, s0=value['S0'],
                                branches={kind: value[kind] for kind in ('Is', 'In')})
    assert result == smaller and result['Fsql']['ledger']['status'] == 'verified_conditional'


def test_maximum_whole_envelope_is_sized_without_minting_evidence(positive_sequence):
    value, f2, metadata, descriptor = positive_sequence
    arguments = dict(fsql=value['Fsql'], f2_input=f2['input'], metadata=metadata,
                     inventory=f2['inventory'], descriptor=descriptor)
    maximum = value | {'S0': replay.s0_protocol.maximum_receipt(**arguments),
                      **{kind: replay.causal_protocol.maximum_receipt(kind, **arguments)
                         for kind in ('Is', 'In')}}
    assert replay.summary_fits(maximum, metadata)
    assert len(package._encoded(value)) <= len(package._encoded(maximum))
    for candidate in (maximum, package.load_json(package._encoded(maximum))):
        with pytest.raises(package.Unavailable): replay.validate_control(candidate, metadata)
