"""Focused diagnostics cannot turn a rejected or incomplete restore into proof."""
from contextlib import contextmanager, nullcontext
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("focused_restore_driver", ROOT / "scripts/rf1086_focused_restore_check.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def receipt(*, success=False, clean=True, source_post=True, reason="postcondition"):
    before = dict.fromkeys(("roles", "catalog", "auth", "companyMemberships"), "a" * 64)
    return {
        "schema": driver.control.SCHEMA,
        "status": "constructed" if success else "unavailable",
        "reason": None if success else reason,
        "configurationSha256": "c" * 64,
        "code": None, "bindings": None, "identities": None, "counts": None,
        "hooks": None, "mutations": None, "delivery": None, "observers": None,
        "fingerprints": {"source": before, "target": dict(before) if success else before | {"catalog": "b" * 64}},
        "cleanupComplete": clean, "identitySourcePostcheck": source_post,
        "businessComplete": success, "outerBusinessPostchecks": None,
        "phaseElapsedSeconds": {},
    }


def install_context(monkeypatch, value, *, error=None, yield_context=False, repeats=1, extra=""):
    @contextmanager
    def restore(*args, **kwargs):
        try:
            if yield_context:
                yield object()
            elif error is not None:
                raise error
            else:
                raise ValueError("private rejection details")
        finally:
            for _ in range(repeats):
                print(driver.CONSTRUCTION_PREFIX + driver.control.ledger.canonical(value).decode("ascii"), file=sys.stderr)
            if extra:
                print(extra, file=sys.stderr)
    monkeypatch.setattr(driver.identity, "restored_identity", restore)


def observe():
    return driver.run_context("postgresql://private", "http://127.0.0.1:54321", Path("/private/fixture"),
                              object(), driver.control.RecoveryBudget(time.monotonic()))


def auth_startup_value():
    return {'schema':'rf1086-auth-startup-tail-v2','evidence':'source-pattern-compatible-only',
        'sourceIdentitySha256':'1'*64,'targetIdentitySha256':'2'*64,
        'authIdentitySha256':'3'*64,'authImageSha256':'4'*64,
        'state':{'status':'exited','exitCode':1,'oomKilled':False},
        'tail':{'bytes':250,'sha256':'5'*64,'records':1,'fatalRecords':1},
        'classification':{'stage':'migration_connection_check','reportedSQLSTATE':'28P01'}}


def auth_startup_receipt():
    value=receipt(success=True)
    original={'bytes':100,'sha256':'6'*64}
    value.update(identities={'source':'1'*64,'target':'2'*64,'image':'7'*64},
        bindings={'script':dict(original)},delivery={'original':original,
        'writer':{'stdoutEnd':'eof','stderrEnd':'eof','exitCode':0,'reap':'waited'}})
    return value


def test_auth_startup_export_is_same_primary_receipt_bound_closed_copy(monkeypatch,capsys):
    primary=driver.control.EndpointAdmissionFailure('auth','running');primary.auth_startup=auth_startup_value()
    install_context(monkeypatch,auth_startup_receipt(),error=primary,extra='private-output-canary')
    result=observe();failure=result['postConstructionFailure']
    assert failure['schema']=='rf1086-focused-post-construction-failure-v4'
    assert failure['authStartup']==primary.auth_startup and failure['authStartup'] is not primary.auth_startup
    assert failure['authStartup']['classification']['reportedSQLSTATE']=='28P01'
    assert failure['constructionSha256']==result['constructionReceiptSha256']
    assert result['identityOutcome']=='unavailable' and not result['identityContextEntered']
    primary.auth_startup['state']['status']='private-mutated'
    assert failure['authStartup']['state']['status']=='exited' and capsys.readouterr()==('','')


@pytest.mark.parametrize('code', [None,'28P01','28000','3D000','42501'])
def test_auth_startup_migration_reported_code_export_stays_qualified_and_receipt_bound(monkeypatch, code):
    primary = driver.control.EndpointAdmissionFailure('auth','running')
    primary.auth_startup = auth_startup_value()
    primary.auth_startup['classification'] = {'stage':'migration_apply','reportedSQLSTATE':code}
    install_context(monkeypatch, auth_startup_receipt(), error=primary)
    value = observe(); failure = value['postConstructionFailure']
    assert failure['schema'] == 'rf1086-focused-post-construction-failure-v4'
    assert failure['constructionSha256'] == value['constructionReceiptSha256']
    assert failure['authStartup']['schema'] == 'rf1086-auth-startup-tail-v2'
    assert failure['authStartup']['classification'] == {'stage':'migration_apply','reportedSQLSTATE':code}
    assert failure['authStartup']['evidence'] == 'source-pattern-compatible-only'
    assert value['identityOutcome'] == 'unavailable'
    assert not value['identityContextEntered'] and not value['identityContextCompleted']


@pytest.mark.parametrize('stage', ['serve_config','http_listen','http_serve',
    'initial_config','logging_level','serve_database'])
def test_auth_startup_other_simple_stages_still_reject_reported_codes(monkeypatch, stage):
    primary = driver.control.EndpointAdmissionFailure('auth','running')
    primary.auth_startup = auth_startup_value()
    primary.auth_startup['classification']['stage'] = stage
    install_context(monkeypatch, auth_startup_receipt(), error=primary)
    failure = observe()['postConstructionFailure']
    assert failure['authStartup'] is None
    assert failure['endpointAdmission'] == {'service':'auth','predicate':'running'}


@pytest.mark.parametrize('fault',['source','target','same-auth','missing','extra','schema','evidence',
    'state-status','state-exit-bool','state-oom','tail-count-bool','tail-empty-hash','tail-overflow',
    'tail-fatal-count','stage','code','code-simple','extra-nested','hash-uppercase',
    'old-schema','code-bool','code-int','migration-code-unknown'])
def test_auth_startup_export_rejects_forged_finite_fields_preserving_endpoint(monkeypatch,fault):
    primary=driver.control.EndpointAdmissionFailure('auth','running');value=auth_startup_value()
    if fault=='source':value['sourceIdentitySha256']='a'*64
    elif fault=='target':value['targetIdentitySha256']='b'*64
    elif fault=='same-auth':value['authIdentitySha256']=value['targetIdentitySha256']
    elif fault=='missing':del value['state']
    elif fault=='extra':value['private']='canary'
    elif fault=='schema':value['schema']='private'
    elif fault=='old-schema':value['schema']='rf1086-auth-startup-tail-v1'
    elif fault=='evidence':value['evidence']='proved-cause'
    elif fault=='state-status':value['state']['status']='running'
    elif fault=='state-exit-bool':value['state']['exitCode']=True
    elif fault=='state-oom':value['state']['oomKilled']=0
    elif fault=='tail-count-bool':value['tail']['records']=True
    elif fault=='tail-empty-hash':value['tail'].update(bytes=0,records=0,fatalRecords=0)
    elif fault=='tail-overflow':value['tail']['bytes']=65537
    elif fault=='tail-fatal-count':value['tail']['fatalRecords']=0
    elif fault=='stage':value['classification']['stage']='private'
    elif fault=='code':value['classification']['reportedSQLSTATE']='99999'
    elif fault=='code-simple':value['classification']['stage']='serve_database'
    elif fault=='code-bool':value['classification']['reportedSQLSTATE']=True
    elif fault=='code-int':value['classification']['reportedSQLSTATE']=28000
    elif fault=='migration-code-unknown':value['classification']={'stage':'migration_apply','reportedSQLSTATE':'XX999'}
    elif fault=='extra-nested':value['classification']['private']='canary'
    elif fault=='hash-uppercase':value['authImageSha256']='A'*64
    primary.auth_startup=value
    install_context(monkeypatch,auth_startup_receipt(),error=primary)
    failure=observe()['postConstructionFailure']
    assert failure['authStartup'] is None and failure['endpointAdmission']=={'service':'auth','predicate':'running'}
    assert 'private' not in json.dumps(failure)


@pytest.mark.parametrize('fault',['no-delivery','stdout','stderr','exit','exit-bool','reap','original',
    'no-identities','other-service','other-predicate','ordinary','subclass'])
def test_auth_startup_export_requires_original_delivery_and_exact_primary(monkeypatch,fault):
    primary=driver.control.EndpointAdmissionFailure('auth','running');value=auth_startup_receipt()
    if fault=='no-delivery':value['delivery']=None
    elif fault in ('stdout','stderr'):value['delivery']['writer'][fault+'End']='truncated'
    elif fault=='exit':value['delivery']['writer']['exitCode']=1
    elif fault=='exit-bool':value['delivery']['writer']['exitCode']=False
    elif fault=='reap':value['delivery']['writer']['reap']='unknown'
    elif fault=='original':value['delivery']['original']['sha256']='a'*64
    elif fault=='no-identities':value['identities']=None
    elif fault=='other-service':primary=driver.control.EndpointAdmissionFailure('database','running')
    elif fault=='other-predicate':primary=driver.control.EndpointAdmissionFailure('auth','paused')
    elif fault=='ordinary':primary=ValueError('private')
    elif fault=='subclass':
        class Derived(driver.control.EndpointAdmissionFailure):pass
        primary=Derived('auth','running')
    primary.auth_startup=auth_startup_value()
    install_context(monkeypatch,value,error=primary)
    assert observe()['postConstructionFailure']['authStartup'] is None


@pytest.mark.parametrize('error',[KeyboardInterrupt('private-cancel'),SystemExit(4)])
@pytest.mark.parametrize('stage',['migration_connection_check','migration_apply'])
def test_auth_startup_export_cancellation_preserves_token_and_clears_private(monkeypatch,error,stage):
    primary=driver.control.EndpointAdmissionFailure('auth','running');primary.auth_startup=auth_startup_value()
    primary.auth_startup['classification']['stage']=stage
    private=driver.PrivateOutput();monkeypatch.setattr(driver,'PrivateOutput',lambda:private)
    install_context(monkeypatch,auth_startup_receipt(),error=primary,extra='private-canary')
    def cancel(*args,**kwargs):raise error
    monkeypatch.setattr(driver.control,'validate_auth_startup',cancel)
    with pytest.raises(type(error)) as caught:observe()
    assert caught.value is error and private.parts==[] and private.bytes==0


def test_auth_startup_export_ordinary_validator_failure_cannot_hide_sticky_primary(monkeypatch):
    primary=driver.control.EndpointAdmissionFailure('auth','running');primary.auth_startup=auth_startup_value()
    budget=driver.control.RecoveryBudget(time.monotonic())
    def fail(*args,**kwargs):
        budget.context.owner._uncertain('close',ValueError('secondary'),primary)
        raise ValueError('private-parser')
    monkeypatch.setattr(driver.control,'validate_auth_startup',fail)
    with pytest.raises(driver.control.EndpointAdmissionFailure) as caught:
        driver.failure_details(primary,budget,construction=auth_startup_receipt())
    assert caught.value is primary


def test_rejected_catalog_is_a_diagnostic_result_not_recovery_success(monkeypatch, capsys):
    value = receipt()
    install_context(monkeypatch, value, extra="private row contents that must not be echoed")
    result = observe()
    assert result["identityOutcome"] == "catalog_postcondition_rejected"
    assert not result["identityContextEntered"] and not result["identityContextCompleted"]
    assert result["constructionReceiptSha256"] == hashlib.sha256(driver.control.ledger.canonical(value)).hexdigest()
    assert capsys.readouterr() == ("", "")
    assert "private row contents" not in json.dumps(result)


def test_empty_caller_completion_is_only_identity_context_completion(monkeypatch):
    install_context(monkeypatch, receipt(success=True), yield_context=True)
    result = observe()
    assert result["identityOutcome"] == "identity_context_completed"
    assert result["identityContextEntered"] and result["identityContextCompleted"]
    # The outer envelope always qualifies the no-op caller as business-unverified.
    assert "businessVerified" not in result


@pytest.mark.parametrize("changes", [{"clean": False}, {"source_post": False}, {"reason": "cleanup_uncertain"}, {"reason": "deadline"}])
def test_incomplete_cleanup_source_check_or_different_failure_stays_unavailable(monkeypatch, changes):
    install_context(monkeypatch, receipt(**changes))
    assert observe()["identityOutcome"] == "unavailable"


def test_matching_hashes_without_completed_context_are_not_success(monkeypatch):
    install_context(monkeypatch, receipt(success=True))
    result = observe()
    assert result["identityOutcome"] == "unavailable"
    assert result['postConstructionFailure']['location'] is None
    assert result['postConstructionFailure']['endpointAdmission'] is None


def test_post_construction_endpoint_primary_is_closed_and_bound(monkeypatch, capsys):
    primary = driver.control.EndpointAdmissionFailure('auth', 'port_bindings')
    install_context(monkeypatch, receipt(success=True), error=primary,
                    extra='private-inspection-output-canary')
    result = observe()
    diagnostic = result['postConstructionFailure']
    assert diagnostic['schema'] == 'rf1086-focused-post-construction-failure-v4'
    assert set(diagnostic) == {'schema', 'constructionSha256', 'location', 'endpointAdmission', 'authStartup'}
    assert diagnostic['constructionSha256'] == result['constructionReceiptSha256']
    assert diagnostic['endpointAdmission'] == {'service':'auth', 'predicate':'port_bindings'}
    assert result['identityOutcome'] == 'unavailable' and not result['identityContextEntered']
    assert 'private-' not in json.dumps(result) and capsys.readouterr() == ('', '')


@pytest.mark.parametrize('case', ['ordinary', 'subclass', 'cause', 'context', 'forged-attributes'])
def test_endpoint_details_never_promote_other_primary_or_chain(monkeypatch, case):
    typed = driver.control.EndpointAdmissionFailure('auth', 'running')
    primary = ValueError('private-primary-canary')
    if case == 'subclass':
        class Derived(driver.control.EndpointAdmissionFailure): pass
        primary = Derived('auth', 'running')
    elif case == 'cause': primary.__cause__ = typed
    elif case == 'context': primary.__context__ = typed
    elif case == 'forged-attributes': primary.service, primary.predicate = 'auth', 'running'
    install_context(monkeypatch, receipt(success=True), error=primary)
    result = observe()
    assert result['postConstructionFailure']['endpointAdmission'] is None
    assert 'private-' not in json.dumps(result)


@pytest.mark.parametrize('field,value', [('service', 'private-service'), ('service', False),
    ('predicate', 'private-predicate'), ('predicate', 1)])
def test_endpoint_details_revalidate_mutated_enum_values(monkeypatch, field, value):
    primary = driver.control.EndpointAdmissionFailure('database', 'exists')
    setattr(primary, field, value)
    install_context(monkeypatch, receipt(success=True), error=primary)
    result = observe()
    assert result['postConstructionFailure']['endpointAdmission'] is None
    assert 'private-' not in json.dumps(result)


@pytest.mark.parametrize('fault', ['missing', 'string-subclass'])
def test_endpoint_details_reject_missing_or_nonexact_attributes(monkeypatch, fault):
    primary = driver.control.EndpointAdmissionFailure('database', 'exists')
    if fault == 'missing': del primary.service
    else:
        class Text(str): pass
        primary.service = Text('database')
    install_context(monkeypatch, receipt(success=True), error=primary)
    assert observe()['postConstructionFailure']['endpointAdmission'] is None


@pytest.mark.parametrize('case', ['completed', 'entered-failure', 'catalog', 'pretarget', 'cleanup', 'source'])
def test_endpoint_classification_never_bypasses_postfailure_eligibility(monkeypatch, case):
    primary = driver.control.EndpointAdmissionFailure('database', 'running')
    value = receipt(success=case not in ('catalog', 'pretarget'), clean=case != 'cleanup',
                    source_post=case != 'source')
    if case == 'pretarget': value['fingerprints']['target'] = None
    if case == 'entered-failure':
        @contextmanager
        def restore(*args, **kwargs):
            try:
                yield object()
                raise primary
            finally:
                print(driver.CONSTRUCTION_PREFIX + driver.control.ledger.canonical(value).decode('ascii'), file=sys.stderr)
        monkeypatch.setattr(driver.identity, 'restored_identity', restore)
    else: install_context(monkeypatch, value, error=primary, yield_context=case == 'completed')
    def forbidden(*args): raise AssertionError('ineligible diagnostic extraction')
    monkeypatch.setattr(driver, 'failure_details', forbidden)
    result = observe()
    assert result['postConstructionFailure'] is None
    assert result['identityContextCompleted'] is (case == 'completed')


@pytest.mark.parametrize('short_end', [False, True])
def test_endpoint_classification_and_location_share_one_live_window(monkeypatch, short_end):
    primary = driver.control.EndpointAdmissionFailure('auth', 'paused')
    primary.add_note('private-note-canary')
    budget = driver.control.RecoveryBudget(time.monotonic())
    if short_end: budget.end = time.monotonic() + .1
    original_end = budget.end
    seen = []
    def read(self, name):
        if name in ('service', 'predicate'):
            seen.append((name, signal.getitimer(signal.ITIMER_REAL)[0]))
        return object.__getattribute__(self, name)
    def location(*args):
        seen.append(('location', signal.getitimer(signal.ITIMER_REAL)[0]))
        return None
    monkeypatch.setattr(driver.control.EndpointAdmissionFailure, '__getattribute__', read)
    monkeypatch.setattr(driver.control, '_diagnostic_location', location)
    result = driver.failure_details(primary, budget)
    assert result == {'location':None, 'endpointAdmission':{'service':'auth', 'predicate':'paused'}, 'authStartup':None}
    assert [name for name, _ in seen] == ['service', 'predicate', 'location']
    left = [remaining for _, remaining in seen]
    assert 0 < left[2] <= left[1] <= left[0] <= (.1 if short_end else .250)
    assert budget.end == original_end and budget.phase == 'construction'
    assert 'private-' not in json.dumps(result)


def test_post_construction_failure_reports_bound_location_without_private_values(monkeypatch, capsys):
    value = receipt(success=True)
    @contextmanager
    def restore(*args, **kwargs):
        try:
            driver.identity.auth_environment({
                'GOTRUE_DB_DATABASE_URL':'postgres://private-user:private-pass@private-host/postgres',
                'GOTRUE_JWT_SECRET':'private-signing-canary\nprivate-line'}, 'rf193_identity_db_' + 'a'*32)
            yield object()
        finally:
            print(driver.CONSTRUCTION_PREFIX + driver.control.ledger.canonical(value).decode('ascii'), file=sys.stderr)
    monkeypatch.setattr(driver.identity, 'restored_identity', restore)
    budget = driver.control.RecoveryBudget(time.monotonic())
    result = driver.run_context('postgresql://private', 'http://127.0.0.1:54321', Path('/private/fixture'), object(), budget)
    diagnostic = result['postConstructionFailure']
    assert diagnostic['schema'] == 'rf1086-focused-post-construction-failure-v4'
    assert diagnostic['constructionSha256'] == result['constructionReceiptSha256']
    assert diagnostic['endpointAdmission'] is None
    location = diagnostic['location']
    assert location['module'] == 'identity' and location['depth'] == 0 and location['edge'] == 'primary'
    line = (ROOT/'scripts/rf1086_identity_restore.py').read_text().splitlines()[location['line']-1]
    assert "raise ValueError('Auth environment cannot contain line breaks')" in line
    assert result['identityOutcome'] == 'unavailable'
    assert not result['identityContextEntered'] and not result['identityContextCompleted']
    assert 'private-' not in json.dumps(result) and capsys.readouterr() == ('', '')


@pytest.mark.parametrize('case', ['completed', 'catalog', 'pretarget', 'cleanup', 'source'])
def test_post_construction_location_is_failure_only_after_clean_matching_construction(monkeypatch, case):
    value = receipt(success=case not in ('catalog', 'pretarget'), clean=case != 'cleanup', source_post=case != 'source')
    if case == 'pretarget': value['fingerprints']['target'] = None
    install_context(monkeypatch, value, yield_context=case == 'completed')
    def forbidden(*args): raise AssertionError('ineligible extraction')
    monkeypatch.setattr(driver, 'failure_details', forbidden)
    assert observe()['postConstructionFailure'] is None


@pytest.mark.parametrize('error', [ValueError('private-error'), driver.control.RestoreUnavailable('deadline')])
def test_failure_details_ordinary_extraction_error_is_unknown(monkeypatch, error):
    def fail(*args): raise error
    monkeypatch.setattr(driver.control, '_diagnostic_location', fail)
    budget = driver.control.RecoveryBudget(time.monotonic())
    assert driver.failure_details(ValueError('private-primary'), budget) == {
        'location':None, 'endpointAdmission':None, 'authStartup':None}


@pytest.mark.parametrize('error', [KeyboardInterrupt('private-cancel'), SystemExit('private-exit')])
def test_failure_details_cancellation_identity_propagates(monkeypatch, error):
    def fail(*args): raise error
    monkeypatch.setattr(driver.control, '_diagnostic_location', fail)
    budget = driver.control.RecoveryBudget(time.monotonic())
    with pytest.raises(type(error)) as caught:
        driver.failure_details(driver.control.EndpointAdmissionFailure('auth', 'running'), budget)
    assert caught.value is error


def test_failure_details_cancellation_still_clears_private_output(monkeypatch):
    private = driver.PrivateOutput()
    monkeypatch.setattr(driver, 'PrivateOutput', lambda: private)
    install_context(monkeypatch, receipt(success=True),
                    error=driver.control.EndpointAdmissionFailure('auth', 'running'),
                    extra='private-output-canary')
    error = KeyboardInterrupt('private-cancel')
    def fail(*args): raise error
    monkeypatch.setattr(driver.control, '_diagnostic_location', fail)
    with pytest.raises(KeyboardInterrupt) as caught: observe()
    assert caught.value is error and private.parts == [] and private.bytes == 0


def test_failure_details_preserves_sticky_fatal_identity(monkeypatch):
    error = driver.control.RestoreUnavailable('cleanup_uncertain')
    def fail(): raise error
    budget = driver.control.RecoveryBudget(time.monotonic())
    monkeypatch.setattr(budget.context, 'raise_if_fatal', fail)
    with pytest.raises(type(error)) as caught:
        driver.failure_details(driver.control.EndpointAdmissionFailure('auth', 'running'), budget)
    assert caught.value is error


@pytest.mark.parametrize('short_end', [False, True])
def test_failure_details_postcheck_discards_both_results_after_clipped_expiry(monkeypatch, short_end):
    budget = driver.control.RecoveryBudget(time.monotonic())
    if short_end: budget.end = time.monotonic() + 0.1
    calls = []
    def remaining(*, end):
        calls.append(end)
        if len(calls) == 2: raise driver.control.RestoreUnavailable('deadline')
        return min(end, budget.end) - time.monotonic()
    monkeypatch.setattr(budget, 'remaining', remaining)
    monkeypatch.setattr(driver.control, '_diagnostic_location', lambda *args: {'module':'identity','line':1,'depth':0,'edge':'primary'})
    started = time.monotonic()
    assert driver.failure_details(driver.control.EndpointAdmissionFailure('auth', 'running'), budget) == {
        'location':None, 'endpointAdmission':None, 'authStartup':None}
    assert len(calls) == 2 and calls[0] == calls[1]
    assert started < calls[0] <= min(budget.end, time.monotonic() + 0.250)
    if short_end: assert calls[0] == budget.end
    assert budget.phase == 'construction' and budget.phase_elapsed == {}


def test_failure_details_retains_earlier_alarm_and_restores_handler(monkeypatch):
    original_handler = signal.getsignal(signal.SIGALRM)
    original_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    def prior(*args): raise KeyboardInterrupt('private-alarm')
    observed = []
    def location(*args):
        observed.append(signal.getitimer(signal.ITIMER_REAL)[0])
        return None
    monkeypatch.setattr(driver.control, '_diagnostic_location', location)
    try:
        signal.signal(signal.SIGALRM, prior)
        signal.setitimer(signal.ITIMER_REAL, 0.15)
        budget = driver.control.RecoveryBudget(time.monotonic())
        assert driver.failure_details(ValueError('private-primary'), budget) == {
            'location':None, 'endpointAdmission':None, 'authStartup':None}
        assert 0 < observed[0] <= 0.15
        assert signal.getsignal(signal.SIGALRM) is prior
        assert 0 < signal.getitimer(signal.ITIMER_REAL)[0] <= observed[0]
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, original_handler)
        if original_timer[0]:
            signal.setitimer(signal.ITIMER_REAL, max(0.000001, original_timer[0]-(time.monotonic()-started)), original_timer[1])


def test_repeated_receipt_rejects_ambiguous_result(monkeypatch):
    install_context(monkeypatch, receipt(), repeats=2)
    with pytest.raises(ValueError, match="^producer_output$"):
        observe()


def test_diagnostic_must_bind_the_same_construction_receipt(monkeypatch):
    diagnostic = {"schema": driver.control.CATALOG_DIAGNOSTIC_SCHEMA, "status": "unavailable",
                  "reason": "input", "constructionSha256": "0" * 64,
                  "source": None, "target": None, "difference": None, "relationProfiles": None}
    install_context(monkeypatch, receipt(), extra=driver.CATALOG_PREFIX + driver.control.ledger.canonical(diagnostic).decode("ascii"))
    with pytest.raises(ValueError):
        observe()


def test_bound_unavailable_diagnostic_remains_explicit(monkeypatch):
    value = receipt()
    diagnostic = {"schema": driver.control.CATALOG_DIAGNOSTIC_SCHEMA, "status": "unavailable",
                  "reason": "input", "constructionSha256": hashlib.sha256(driver.control.ledger.canonical(value)).hexdigest(),
                  "source": None, "target": None, "difference": None, "relationProfiles": None}
    install_context(monkeypatch, value, extra=driver.CATALOG_PREFIX + driver.control.ledger.canonical(diagnostic).decode("ascii"))
    assert observe()["catalogDiagnostic"] == diagnostic


def test_preparation_refusal_retains_only_existing_closed_diagnostic(monkeypatch):
    diagnostic = {"schema": driver.control.DIAGNOSTIC_SCHEMA, "step": "unclassified",
                  "component": "unknown", "reason": "internal",
                  "inputs": dict.fromkeys(("source", "archive", "roles", "scriptBytes", "script", "archiveRows")),
                  "ledger": None, "lexicalLimit": None, "location": None}
    value = receipt(reason="metadata_profile")
    value["fingerprints"]["target"] = None
    install_context(monkeypatch, value, extra=driver.control.DIAGNOSTIC_PREFIX + driver.control.ledger.canonical(diagnostic).decode("ascii"))
    result = observe()
    assert result["identityOutcome"] == "unavailable"
    assert result["preTargetDiagnostic"] == diagnostic


def test_preparation_diagnostic_extra_private_fields_reject(monkeypatch):
    install_context(monkeypatch, receipt(), extra=driver.control.DIAGNOSTIC_PREFIX + '{"private":"must-not-escape"}')
    with pytest.raises(ValueError):
        observe()


def test_unknown_top_level_receipt_fields_never_escape(monkeypatch):
    install_context(monkeypatch, receipt() | {"privateValue": "sensitive"})
    with pytest.raises(ValueError, match="^producer_output$"):
        observe()


@pytest.mark.parametrize("payload", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'])
def test_ambiguous_nonfinite_producer_json_rejects(payload):
    with pytest.raises(ValueError):
        driver.strict_json(payload)


def test_private_output_cap_fails_without_retaining_overflow():
    private = driver.PrivateOutput()
    private.write("x" * driver.MAX_OUTPUT)
    with pytest.raises(ValueError, match="^producer_output$"):
        private.write("sensitive overflow")
    assert private.bytes == driver.MAX_OUTPUT and len(private.parts) == 1
    private.clear()
    assert private.parts == [] and private.bytes == 0


def test_noncanonical_carrier_is_not_admitted():
    private = driver.PrivateOutput()
    private.write(driver.CONSTRUCTION_PREFIX + '{ "schema" : "x" }\n')
    with pytest.raises(ValueError, match="^producer_output$"):
        private.records(driver.CONSTRUCTION_PREFIX)


def test_cancellation_identity_environment_and_private_capture_are_preserved(monkeypatch):
    primary = KeyboardInterrupt()
    install_context(monkeypatch, receipt(), error=primary)
    monkeypatch.setenv("DATABASE_URL", "original-private")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    cleared = []
    original = driver.PrivateOutput.clear
    def clear(self):
        original(self)
        cleared.append(self.bytes == 0 and self.parts == [])
    monkeypatch.setattr(driver.PrivateOutput, "clear", clear)
    with pytest.raises(KeyboardInterrupt) as caught:
        observe()
    assert caught.value is primary
    assert os.environ["DATABASE_URL"] == "original-private"
    assert "SUPABASE_URL" not in os.environ and cleared == [True]


@pytest.mark.parametrize("error", [ValueError("secret SQL"), RuntimeError("private password")])
def test_main_projects_only_closed_failure_reason(monkeypatch, capsys, error):
    def fail():
        raise error
    monkeypatch.setattr(driver, "check", fail)
    assert driver.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"schema": driver.SCHEMA, "status": "unavailable", "reason": "focused_restore_unavailable"}
    assert str(error) not in captured.err


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit("private cancellation message")])
def test_main_cancellation_is_finite_failure(monkeypatch, capsys, error):
    def fail():
        raise error
    monkeypatch.setattr(driver, "check", fail)
    assert driver.main() == 130
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {"schema": driver.SCHEMA, "status": "unavailable", "reason": "cancelled"}
    assert "private" not in captured.err and captured.out == ""


@pytest.fixture
def bound_driver(monkeypatch, tmp_path):
    workdir = tmp_path / "talli-supabase-local.generated"
    (workdir / "supabase").mkdir(parents=True)
    (workdir / "supabase/config.toml").write_text('project_id = "tallig123"\n')
    for key, value in {"TALLI_FOCUSED_WORKDIR": str(workdir), "GITHUB_RUN_ID": "123",
                       "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "focused-restore", "GITHUB_SHA": "a" * 40}.items():
        monkeypatch.setenv(key, value)
    state = {"head": "a" * 40, "image": driver.IMAGE, "version": "17.6", "contexts": 0, "commands": []}
    class Budget:
        def __init__(self, started):
            self.end = started + 115
        def enter(self, phase):
            state["phase"] = phase
        def command(self, args, **kwargs):
            state["commands"].append(args)
            if args[:2] == ["git", "rev-parse"]:
                return state["head"].encode() + b"\n"
            if args[0] == "npm":
                return b'{"DB_URL":"postgresql://private","API_URL":"http://127.0.0.1:54321","ANON_KEY":"generated-anon","SERVICE_ROLE_KEY":"generated-service","SECRET_KEY":"must-never-escape"}'
            if args[1] == "inspect":
                return state["image"].encode() + b"\n"
            if "psql" in args:
                return state["version"].encode() + b"\n"
            return b"pg_dump (PostgreSQL) 17.6\n"
    def context(*args):
        state["contexts"] += 1
        return {"identityOutcome": "catalog_postcondition_rejected", "identityContextEntered": False,
                "identityContextCompleted": False, "construction": receipt(),
                "constructionReceiptSha256": "c" * 64, "catalogDiagnostic": None, "preTargetDiagnostic": None}
    monkeypatch.setattr(driver.control, "RecoveryBudget", Budget)
    monkeypatch.setattr(driver.control, "io_deadline", lambda *a, **k: nullcontext())
    monkeypatch.setattr(driver, "source_bindings", lambda: {"fixture": "b" * 64})
    monkeypatch.setattr(driver, "run_context", context)
    monkeypatch.setattr(driver, "focused_owner_session", lambda *a, **k: nullcontext(), raising=False)
    return state


def test_outer_report_never_promotes_diagnostic_to_business_or_historical_proof(bound_driver, capsys):
    assert driver.check(time.monotonic()) == 1
    value = json.loads(capsys.readouterr().out)
    assert value["identityOutcome"] == "catalog_postcondition_rejected"
    assert value["businessVerified"] is False and value["originalArchiveReplayed"] is False
    assert value["originalFailureCauseKnown"] is False
    assert value["diagnosticComplete"] is False
    assert value["scope"] == "generated_same_image_production_identity_context"
    assert "must-never-escape" not in json.dumps(value)
    assert bound_driver["contexts"] == 1 and bound_driver["phase"] == "output"


@pytest.mark.parametrize("key,bad,reason", [("head", "b" * 40, "candidate_binding"),
                                           ("image", "sha256:" + "0" * 64, "image_binding"),
                                           ("version", "17.11", "version_binding")])
def test_wrong_candidate_image_or_version_never_enters_recovery(bound_driver, key, bad, reason):
    bound_driver[key] = bad
    with pytest.raises(ValueError, match=f"^{reason}$"):
        driver.check(time.monotonic())
    assert bound_driver["contexts"] == 0


def test_check_requires_private_owner_fixture_before_recovery(bound_driver, monkeypatch, capsys):
    events = []
    monkeypatch.setenv('TALLI_RF_RESTORE_OWNER_TOKEN', 'inherited-must-not-be-used')
    @contextmanager
    def fixture(database_url, api_url, workdir, boundary, budget, *, anon_key, service_key):
        assert (anon_key, service_key) == ('generated-anon', 'generated-service')
        events.append('fixture')
        old = os.environ['TALLI_RF_RESTORE_OWNER_TOKEN']
        os.environ['TALLI_RF_RESTORE_OWNER_TOKEN'] = 'generated-private-token'
        try:
            yield
        finally:
            events.append('fixture_restore')
            os.environ['TALLI_RF_RESTORE_OWNER_TOKEN'] = old
    previous = driver.run_context
    def context(*args):
        assert os.environ['TALLI_RF_RESTORE_OWNER_TOKEN'] == 'generated-private-token'
        events.append('recovery')
        return previous(*args)
    monkeypatch.setattr(driver, 'focused_owner_session', fixture)
    monkeypatch.setattr(driver, 'run_context', context)
    assert driver.check(time.monotonic()) == 1
    assert events == ['fixture', 'recovery', 'fixture_restore']
    assert os.environ['TALLI_RF_RESTORE_OWNER_TOKEN'] == 'inherited-must-not-be-used'
    assert 'generated-private-token' not in capsys.readouterr().out


# The fixture seams are private HTTP, owned child pipes, and the pre-M0 scope.
# All protocol bodies/credentials below are generated; no Auth service is used.
ACTOR = '11111111-1111-4111-8111-111111111111'
SESSION = '22222222-2222-4222-8222-222222222222'


def fixture_token(**changes):
    import base64
    claims = {'sub': ACTOR, 'session_id': SESSION, 'role': 'authenticated',
              'exp': int(time.time()) + 3600}
    claims.update(changes)
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')
    return encode({'alg': 'HS256'}) + '.' + encode(claims) + '.c2ln'


def fixture_input():
    return {'schema': driver.FIXTURE_INPUT_SCHEMA, 'nonce': 'c' * 32,
            'api_url': 'http://127.0.0.1:54321', 'anon_key': 'generated-anon',
            'service_key': 'generated-service', 'work_end': time.monotonic() + 7,
            'min_expiry': time.time() + 210}


def fixture_reply(value, **changes):
    return driver.control.ledger.canonical({'schema': driver.FIXTURE_OUTPUT_SCHEMA,
        'nonce': value['nonce'], 'actor_id': ACTOR, 'access_token': fixture_token(), **changes})


def mock_auth(*, fault=None, close_error=None):
    calls = []
    class Stream(driver.httpx.SyncByteStream):
        def __init__(self, raw): self.raw = raw
        def __iter__(self):
            for start in range(0, len(self.raw), 1031): yield self.raw[start:start+1031]
        def close(self):
            calls.append('response_close')
            if close_error: raise close_error
    def handle(request):
        index = sum(isinstance(x, dict) for x in calls)
        body = json.loads(request.content) if request.content else None
        calls.append({'method': request.method, 'url': str(request.url),
                      'headers': dict(request.headers), 'body': body})
        replies = [{'id': ACTOR, 'role': 'authenticated'},
                   {'user': {'id': ACTOR}, 'token_type': 'bearer', 'access_token': fixture_token(), 'expires_in': 3600},
                   {'id': ACTOR}]
        assert index < 3, 'fixture must not retry or refresh'
        response = {'status': 200, 'body': replies[index], 'headers': {'Content-Type': 'application/json'}}
        if fault: fault(index, response)
        raw = response.get('raw', json.dumps(response['body']).encode())
        return driver.httpx.Response(response['status'], headers=response['headers'], stream=Stream(raw))
    class Transport(driver.httpx.MockTransport):
        def close(self):
            calls.append('transport_close')
            if close_error: raise close_error
    return Transport(handle), calls


def test_owner_fixture_three_private_calls_agree_before_close_and_no_public_output(capsys):
    transport, calls = mock_auth()
    value = driver._fixture_input(driver.control.ledger.canonical(fixture_input()))
    result = driver._fixture_http(value, transport=transport)
    requests = [c for c in calls if isinstance(c, dict)]
    assert [(c['method'], c['url']) for c in requests] == [
        ('POST', 'http://127.0.0.1:54321/auth/v1/admin/users'),
        ('POST', 'http://127.0.0.1:54321/auth/v1/token?grant_type=password'),
        ('GET', 'http://127.0.0.1:54321/auth/v1/user')]
    create, signin, user = requests
    assert create['body']['email_confirm'] is True
    assert set(create['body']) == {'email', 'password', 'email_confirm'}
    assert signin['body'] == {k: create['body'][k] for k in ('email', 'password')}
    assert create['body']['email'].startswith('rf-focused-') and create['body']['email'].endswith('@example.test')
    assert 40 <= len(create['body']['password']) <= 72
    assert create['headers']['apikey'] == 'generated-service'
    assert create['headers']['authorization'] == 'Bearer generated-service'
    assert signin['headers']['apikey'] == user['headers']['apikey'] == 'generated-anon'
    assert signin['headers']['authorization'] == 'Bearer generated-anon'
    assert user['headers']['authorization'] == 'Bearer ' + result['access_token']
    assert all('cookie' not in c['headers'] and c['headers']['accept-encoding'] == 'identity' for c in requests)
    assert calls[-1] == 'transport_close'
    assert result == {'schema': driver.FIXTURE_OUTPUT_SCHEMA, 'nonce': 'c'*32,
                      'actor_id': ACTOR, 'access_token': result['access_token']}
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('fault', ['status', 'redirect', 'cookie', 'encoding', 'media', 'length', 'length_mismatch',
    'overcap', 'utf8', 'duplicate', 'nan', 'depth', 'created_id', 'created_role', 'signin_id',
    'get_id', 'token_type', 'expires_bool', 'expires_large', 'expires_at_bool', 'expires_at_mismatch'])
def test_owner_fixture_protocol_refusals_never_retry_or_return_session(fault):
    def change(index, response):
        at = 1 if fault.startswith(('signin', 'token_', 'expires')) else 2 if fault == 'get_id' else 0
        if index != at: return
        if fault == 'status': response['status'] = 400
        elif fault == 'redirect': response.update(status=302, headers={'location':'https://private.invalid','content-type':'application/json'})
        elif fault == 'cookie': response['headers']['Set-Cookie'] = 'private=canary'
        elif fault == 'encoding': response['headers']['Content-Encoding'] = 'gzip'
        elif fault == 'media': response['headers']['Content-Type'] = 'text/plain'
        elif fault == 'length': response['headers']['Content-Length'] = '-1'
        elif fault == 'length_mismatch': response['headers']['Content-Length'] = '1'
        elif fault == 'overcap': response['raw'] = b' ' * 65537
        elif fault == 'utf8': response['raw'] = b'\xff'
        elif fault == 'duplicate': response['raw'] = b'{"id":"a","id":"b"}'
        elif fault == 'nan': response['raw'] = b'{"id":NaN}'
        elif fault == 'depth': response['raw'] = b'{"x":' + b'['*16 + b'0' + b']'*16 + b'}'
        elif fault == 'created_id': response['body']['id'] = '00000000-0000-0000-0000-000000000000'
        elif fault == 'created_role': response['body']['role'] = 'service_role'
        elif fault == 'signin_id': response['body']['user']['id'] = SESSION
        elif fault == 'get_id': response['body']['id'] = SESSION
        elif fault == 'token_type': response['body']['token_type'] = 'Bearer'
        elif fault == 'expires_bool': response['body']['expires_in'] = True
        elif fault == 'expires_large': response['body']['expires_in'] = 86401
        elif fault == 'expires_at_bool': response['body']['expires_at'] = True
        elif fault == 'expires_at_mismatch': response['body']['expires_at'] = 1
    transport, calls = mock_auth(fault=change)
    with pytest.raises((ValueError, driver.httpx.HTTPError)):
        driver._fixture_http(fixture_input(), transport=transport)
    assert sum(isinstance(c, dict) for c in calls) <= 3
    assert calls[-1] == 'transport_close'


@pytest.mark.parametrize('changes', [{'sub': SESSION}, {'sub': ACTOR.upper()}, {'sub': None},
    {'session_id': None}, {'session_id': '0'*36}, {'session_id': '00000000-0000-0000-0000-000000000000'},
    {'role': 'service_role'}, {'exp': True}, {'exp': 1}, {'exp': int(time.time()) + 180}])
def test_owner_fixture_token_requires_ordinary_stateful_long_lived_session(changes):
    # ACTOR is numeric; use a UUID containing letters for a noncanonical case.
    if changes == {'sub': ACTOR.upper()}: changes = {'sub': 'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA'}
    with pytest.raises(ValueError):
        driver._fixture_token(fixture_token(**changes), ACTOR, time.time()+210)


@pytest.mark.parametrize('token', ['', 'a.b', 'a.b.c.d', 'e30=.e30.c2ln', 'e30.e30.+', 'x'*16385,
                                  'e30.eyJzdWIiOiIxIiwic3ViIjoiMiJ9.c2ln'])
def test_owner_fixture_token_framing_is_closed(token):
    with pytest.raises((ValueError, TypeError)):
        driver._fixture_token(token, ACTOR, time.time()+210)


@pytest.mark.parametrize('error', [RuntimeError('private-close-canary'), KeyboardInterrupt(), SystemExit('private')])
def test_owner_fixture_close_failure_never_produces_private_success(error, monkeypatch, capsys):
    transport, calls = mock_auth(close_error=error)
    with pytest.raises(BaseException) as caught:
        driver._fixture_http(fixture_input(), transport=transport)
    assert caught.value is error and calls[-1] == 'transport_close'
    def fail(_): raise error
    import io
    monkeypatch.setattr(driver.sys, 'stdin', type('Input', (), {'buffer':io.BytesIO(driver.control.ledger.canonical(fixture_input()))})())
    monkeypatch.setattr(driver, '_fixture_http', fail)
    assert driver._fixture_child_main() == 1
    output = capsys.readouterr()
    assert output.out == '' and output.err == 'fixture_session_unavailable\n'


@pytest.mark.parametrize('key,value', [('api_url','http://localhost:54321'), ('api_url','http://[::1]:54321'),
    ('api_url','https://127.0.0.1:54321'), ('api_url','http://127.0.0.1:54321/x'),
    ('api_url','http://127.0.0.1:54321?x=1'), ('api_url','http://127.0.0.1:054321'),
    ('api_url','http://127.0.0.1:65536'), ('anon_key',''), ('anon_key','a b'), ('service_key','x\r\ny'),
    ('service_key','é'), ('anon_key','a'*8193), ('work_end',True), ('work_end',0),
    ('work_end',float('inf')), ('min_expiry',True), ('nonce','A'*32), ('schema','unknown')])
def test_owner_fixture_input_is_bounded_closed_and_loopback_only(key, value):
    data = fixture_input(); data[key] = value
    with pytest.raises((ValueError, TypeError)):
        driver._fixture_input(json.dumps(data).encode())


def test_owner_fixture_json_depth16_and_unknown_bounded_fields():
    raw = b'{"x":' + b'['*15 + b'0' + b']'*15 + b'}'
    assert driver._fixture_json(raw, 65536)['x']
    transport, _ = mock_auth(fault=lambda i, r: r['body'].update(extra={'bounded':'ignored'}))
    assert driver._fixture_http(fixture_input(), transport=transport)['actor_id'] == ACTOR
    for raw in (b'{} '*10923, b'{"schema":', b'[]'):
        with pytest.raises(ValueError): driver._fixture_input(raw)


def setup_parent(monkeypatch, *, command=None):
    budget = driver.control.RecoveryBudget(time.monotonic())
    events = []
    def local(value):
        assert value is budget and value.end <= time.monotonic()+10
        events.append('local')
    def source(*args):
        assert 'TALLI_RF_RESTORE_OWNER_TOKEN' not in os.environ
        assert args[2]._recovery_budget is budget
        events.append('source')
        return {'Image':driver.IMAGE}, {}, {}
    def run(value, argv, **kwargs):
        events.append('child')
        assert value is budget and kwargs['end'] == budget.end
        assert kwargs['cap'] == 32768 and len(kwargs['data']) <= 32768
        data = driver._fixture_input(kwargs['data'])
        assert data['work_end'] == budget.end-2
        assert 'generated-service' not in repr(argv) and 'generated-anon' not in repr(argv)
        return fixture_reply(data)
    monkeypatch.setattr(driver.control, 'require_local_docker', local)
    monkeypatch.setattr(driver.identity, 'owned_identity_source', source)
    if command is not False: monkeypatch.setattr(driver.control, 'io_command', command or run)
    return budget, events


def owner_scope(budget):
    return driver.focused_owner_session('postgresql://private', 'http://127.0.0.1:54321',
        Path('/private/generated'), object(), budget, anon_key='generated-anon', service_key='generated-service')


@pytest.mark.parametrize('previous', [None, '', 'inherited-token'])
def test_owner_fixture_restores_budget_signals_before_recovery_and_environment_after(monkeypatch, previous):
    if previous is None: monkeypatch.delenv('TALLI_RF_RESTORE_OWNER_TOKEN', raising=False)
    else: monkeypatch.setenv('TALLI_RF_RESTORE_OWNER_TOKEN', previous)
    budget, events = setup_parent(monkeypatch)
    oldend, context = budget.end, budget.context
    handlers = {s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM)}
    with owner_scope(budget):
        events.append('M0')
        assert budget.end == oldend and budget.context is context
        assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
        assert all(signal.getsignal(s) is h for s,h in handlers.items())
        assert os.environ['TALLI_RF_RESTORE_OWNER_TOKEN'] != previous
        driver._fixture_token(os.environ['TALLI_RF_RESTORE_OWNER_TOKEN'], ACTOR, time.time()+210)
        budget.enter('actors')
    assert events == ['local','source','child','M0']
    assert budget.phase == 'actors' and budget.end <= budget.started+150
    assert os.environ.get('TALLI_RF_RESTORE_OWNER_TOKEN') == previous


@pytest.mark.parametrize('error', [ValueError('private-body'), KeyboardInterrupt(), SystemExit('private')])
@pytest.mark.parametrize('where', ['ownership','child','body'])
def test_owner_fixture_failure_identity_and_prior_environment(monkeypatch, error, where):
    budget, events = setup_parent(monkeypatch)
    oldend = budget.end
    monkeypatch.setenv('TALLI_RF_RESTORE_OWNER_TOKEN','old')
    def fail(*a, **kw): raise error
    if where=='ownership': monkeypatch.setattr(driver.identity,'owned_identity_source',fail)
    if where=='child': monkeypatch.setattr(driver.control,'io_command',fail)
    with pytest.raises(BaseException) as caught:
        with owner_scope(budget):
            assert where=='body'
            raise error
    assert caught.value is error and budget.end == oldend
    assert os.environ['TALLI_RF_RESTORE_OWNER_TOKEN']=='old'
    if where=='ownership': assert 'child' not in events


@pytest.mark.parametrize('scope_name', ['_connection_signals','io_deadline','budget_scope'])
@pytest.mark.parametrize('primary', [None, ValueError('body'), KeyboardInterrupt(), SystemExit('body')])
def test_owner_fixture_restoration_fault_keeps_first_primary_and_sticky_uncertainty(monkeypatch, scope_name, primary):
    secondary = RuntimeError('restore')
    budget, events = setup_parent(monkeypatch)
    oldend=budget.end
    if primary is not None:
        def fail(*a, **k): raise primary
        monkeypatch.setattr(driver.control,'io_command',fail)
    original = getattr(driver.control, scope_name)
    @contextmanager
    def broken(*a, **kw):
        try:
            with original(*a, **kw): yield
        finally: raise secondary
    monkeypatch.setattr(driver.control,scope_name,broken)
    with pytest.raises(BaseException) as caught:
        with owner_scope(budget): pytest.fail('restoration failure admitted recovery')
    assert caught.value is (primary if primary is not None else secondary)
    assert budget.context.owner.uncertain and budget.end==oldend
    assert 'TALLI_RF_RESTORE_OWNER_TOKEN' not in os.environ


@pytest.mark.parametrize('rf', [False,True])
def test_owner_fixture_refuses_earlier_alarm_without_touching_it_or_ownership(monkeypatch, rf):
    budget, events=setup_parent(monkeypatch)
    original=signal.getsignal(signal.SIGALRM)
    def alarm(*args): raise AssertionError('earlier alarm unexpectedly fired')
    if rf: alarm._rf_io_deadline=True
    signal.signal(signal.SIGALRM,alarm);signal.setitimer(signal.ITIMER_REAL,3,7)
    try:
        with pytest.raises(ValueError):
            with owner_scope(budget): pytest.fail('early alarm admitted')
        left,interval=signal.getitimer(signal.ITIMER_REAL)
        assert 0 < left <= 3 and interval==7 and signal.getsignal(signal.SIGALRM) is alarm
        assert events==[]
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,original)


def test_owner_fixture_preserves_later_alarm_and_interval(monkeypatch):
    budget, events=setup_parent(monkeypatch)
    old=signal.getsignal(signal.SIGALRM)
    def later(*args): raise AssertionError('later alarm fired')
    signal.signal(signal.SIGALRM,later);signal.setitimer(signal.ITIMER_REAL,30,7)
    try:
        with owner_scope(budget):
            left,interval=signal.getitimer(signal.ITIMER_REAL)
            assert 10 < left <= 30 and interval==7 and signal.getsignal(signal.SIGALRM) is later
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old)


@pytest.mark.parametrize('field,value', [('nonce','f'*32),('actor_id',SESSION),('schema','bad'),
    ('access_token',fixture_token(exp=1)),('extra','private')])
def test_owner_fixture_parent_revalidates_child_reply(monkeypatch,field,value):
    def command(budget,argv,**kw):
        return fixture_reply(json.loads(kw['data']),**{field:value})
    budget,_=setup_parent(monkeypatch,command=command)
    with pytest.raises(ValueError):
        with owner_scope(budget): pytest.fail('bad reply admitted')


def test_owner_fixture_insufficient_reap_headroom_refuses_child(monkeypatch):
    budget,events=setup_parent(monkeypatch)
    budget.end=time.monotonic()+1
    with pytest.raises(driver.control.RestoreUnavailable):
        with owner_scope(budget): pytest.fail('no reap reserve')
    assert events==['local','source']


def test_owner_fixture_fixed_launcher_and_closed_entry_mode(monkeypatch,capsys):
    argv=driver._fixture_argv()
    assert argv[:4]==[sys.executable,'-I','-B','-c']
    assert argv[-2:]==[str(Path(driver.__file__).resolve()),'--fixture-session']
    assert argv[4]==driver.FIXTURE_LAUNCHER
    called=[]
    monkeypatch.setattr(driver,'main',lambda:called.append('main') or 7)
    monkeypatch.setattr(driver,'_fixture_child_main',lambda:called.append('child') or 8)
    assert driver.entrypoint([])==7 and driver.entrypoint(['--fixture-session'])==8
    assert driver.entrypoint(['--fixture-session','extra'])==1 and called==['main','child']
    assert capsys.readouterr().err=='fixture_session_unavailable\n'


@pytest.mark.parametrize('first', [RuntimeError('inner-exit'), KeyboardInterrupt(), SystemExit('inner-exit')])
def test_owner_fixture_inner_exit_first_failure_survives_outer_exit(monkeypatch, first):
    budget, _ = setup_parent(monkeypatch)
    oldend = budget.end
    monkeypatch.setenv('TALLI_RF_RESTORE_OWNER_TOKEN', 'previous')
    second = RuntimeError('outer-exit')
    deadline, signals = driver.control.io_deadline, driver.control._connection_signals
    @contextmanager
    def inner(*args, **kwargs):
        with deadline(*args, **kwargs): yield
        raise first
    @contextmanager
    def outer(*args, **kwargs):
        try:
            with signals(*args, **kwargs): yield
        finally: raise second
    monkeypatch.setattr(driver.control, 'io_deadline', inner)
    monkeypatch.setattr(driver.control, '_connection_signals', outer)
    with pytest.raises(BaseException) as caught:
        with owner_scope(budget): pytest.fail('exit failure admitted M0')
    assert caught.value is first
    assert budget.context.owner.uncertain and budget.context.owner.primary is first
    assert budget.end == oldend and os.environ['TALLI_RF_RESTORE_OWNER_TOKEN'] == 'previous'


def journal_owner(budget, tmp_path, case):
    """Observe existing owned slots immediately; never replace global Popen/read."""
    path = Path(os.environ.get('RF_OWNER_TEST_PROCESS_LOG', str(tmp_path/'children.jsonl')))
    observed = {}
    def record(value):
        fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps({'case':case, **value}, sort_keys=True)+'\n')
            stream.flush()
    class JournalOwner(type(budget.context.owner)):
        def launch(self, *args, **kwargs):
            try: return super().launch(*args, **kwargs)
            finally:
                for slot in self.slots:
                    process=slot.process
                    if process is not None and process.pid not in observed:
                        observed[process.pid]={'process':process, 'waited':False}
                        record({'event':'registered','pid':process.pid})
        def reaped(self, process):
            super().reaped(process)
            observed[process.pid]['waited']=True
            record({'event':'waited','pid':process.pid,'returncode':process.returncode})
        def unwind(self, *args, **kwargs):
            held=[(slot,slot.process) for slot in self.slots if slot.process is not None]
            try: return super().unwind(*args, **kwargs)
            finally:
                for slot,process in held:
                    item=observed[process.pid]
                    if slot.waited and not item['waited']:
                        item['waited']=True
                        record({'event':'waited','pid':process.pid,'returncode':process.returncode})
    owner=JournalOwner();budget.context.owner=owner
    return owner,observed


GENERATED_CHILD = '''import json,sys,time,os,signal,base64
v=json.loads(sys.stdin.buffer.read())
def enc(x):return base64.urlsafe_b64encode(json.dumps(x).encode()).decode().rstrip('=')
t=enc({'alg':'HS256'})+'.'+enc({'sub':'11111111-1111-4111-8111-111111111111','session_id':'22222222-2222-4222-8222-222222222222','role':'authenticated','exp':int(time.time())+3600})+'.c2ln'
r=json.dumps({'schema':'rf1086-focused-owner-session-output-v1','nonce':v['nonce'],'actor_id':'11111111-1111-4111-8111-111111111111','access_token':t}).encode()
mode=sys.argv[1]
if mode=='hang':time.sleep(20)
if mode=='sigterm':os.kill(os.getppid(),signal.SIGTERM);time.sleep(20)
if mode=='stdout_cap':sys.stdout.buffer.write(b'x'*32769);sys.stdout.buffer.flush()
elif mode=='stderr_cap':sys.stderr.buffer.write(b'x'*65537);sys.stderr.buffer.flush()
elif mode=='truncated':sys.stdout.buffer.write(r[:20]);sys.stdout.buffer.flush()
else:sys.stdout.buffer.write(r);sys.stdout.buffer.flush()
if mode=='partial_hang':time.sleep(20)
if mode=='nonzero':raise SystemExit(7)
'''


@pytest.mark.parametrize('mode', ['success','hang','partial_hang','nonzero','stdout_cap','stderr_cap','truncated','sigterm'])
def test_owner_fixture_actual_owned_child_eof_exit_caps_cancel_and_reap(monkeypatch,tmp_path,mode):
    budget,events=setup_parent(monkeypatch,command=False)
    budget.end=time.monotonic()+3
    original_end=budget.end
    owner,children=journal_owner(budget,tmp_path,mode)
    monkeypatch.setattr(driver,'_fixture_argv',lambda:[sys.executable,'-I','-B','-c',GENERATED_CHILD,mode])
    handlers={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM)}
    primary=None
    started=time.monotonic()
    try:
        if mode=='success':
            with owner_scope(budget):
                events.append('M0')
                assert budget.end==original_end and all(c['waited'] for c in children.values())
        else:
            with pytest.raises(BaseException) as caught:
                with owner_scope(budget): pytest.fail('failed child admitted M0')
            primary=caught.value
            if mode=='sigterm':
                assert isinstance(primary,KeyboardInterrupt) and owner.primary is primary
            elif mode!='truncated': assert isinstance(primary,driver.control.RestoreUnavailable)
            else: assert isinstance(primary,ValueError)
    finally:
        # The production command has already unwound; this is an explicit test
        # safety net on the SAME original endpoint, including assertion failures.
        if any(s.process is not None for s in owner.slots):
            owner.unwind(original_end,primary=primary or sys.exception())
    assert len(children)==1 and all(c['waited'] and c['process'].returncode is not None for c in children.values())
    assert all(s.process is None for s in owner.slots) and not owner.uncertain
    assert time.monotonic()-started < 3.5
    assert all(signal.getsignal(s) is h for s,h in handlers.items())
    assert signal.getitimer(signal.ITIMER_REAL)[0]==0
    assert ('M0' in events)==(mode=='success')


def test_owner_fixture_actual_fixed_launcher_rejects_input_without_http(monkeypatch,tmp_path):
    budget=driver.control.RecoveryBudget(time.monotonic());budget.end=time.monotonic()+5
    owner,children=journal_owner(budget,tmp_path,'fixed-launcher-invalid-input')
    primary=None
    try:
        with pytest.raises(driver.control.RestoreUnavailable) as caught:
            driver.control.io_command(budget,driver._fixture_argv(),data=b'{}',cap=32768,end=budget.end)
        primary=caught.value
    finally:
        if any(s.process is not None for s in owner.slots): owner.unwind(budget.end,primary=primary or sys.exception())
    assert len(children)==1 and all(c['waited'] and c['process'].returncode==1 for c in children.values())
    assert all(s.process is None for s in owner.slots)


@pytest.mark.parametrize('where',['acquire','unwind'])
def test_owner_fixture_nested_owner_deferral_keeps_cancel_and_reaps(monkeypatch,tmp_path,where):
    budget,_=setup_parent(monkeypatch,command=False)
    budget.end=time.monotonic()+3;end=budget.end
    owner,children=journal_owner(budget,tmp_path,'deferred-'+where)
    monkeypatch.setattr(driver,'_fixture_argv',lambda:[sys.executable,'-I','-B','-c',GENERATED_CHILD,'hang'])
    original=owner.launch
    def launch(*a,**kw):
        with owner.deferred():
            process=original(*a,**kw)
            if where=='acquire': os.kill(os.getpid(),signal.SIGTERM)
            else:
                kill=process.kill
                def interrupted_kill():
                    os.kill(os.getpid(),signal.SIGTERM)
                    return kill()
                process.kill=interrupted_kill
            return process
    monkeypatch.setattr(owner,'launch',launch)
    primary=None
    try:
        with pytest.raises(BaseException) as caught:
            with owner_scope(budget): pytest.fail('deferred cancellation admitted recovery')
        primary=caught.value
        assert owner.cancelled and owner.primary is primary
        if where=='acquire': assert isinstance(primary,KeyboardInterrupt)
    finally:
        if any(s.process is not None for s in owner.slots):owner.unwind(end,primary=primary or sys.exception())
    assert len(children)==1 and all(c['waited'] for c in children.values())
    assert all(s.process is None for s in owner.slots) and not owner.uncertain


@pytest.mark.parametrize('previous',[signal.SIG_IGN,'callable'])
def test_owner_fixture_existing_signal_policy_and_restoration(monkeypatch,previous):
    budget,events=setup_parent(monkeypatch)
    old=signal.getsignal(signal.SIGTERM);seen=[]
    handler=(lambda *args:seen.append('deferred')) if previous=='callable' else previous
    command=driver.control.io_command
    def interrupted(*a,**kw):
        os.kill(os.getpid(),signal.SIGTERM)
        return command(*a,**kw)
    monkeypatch.setattr(driver.control,'io_command',interrupted)
    signal.signal(signal.SIGTERM,handler)
    try:
        with owner_scope(budget):assert signal.getsignal(signal.SIGTERM) is handler
        assert seen==(['deferred'] if previous=='callable' else [])
    finally:signal.signal(signal.SIGTERM,old)


@pytest.mark.parametrize('primary',[None,ValueError('first'),KeyboardInterrupt(),SystemExit('first')])
def test_owner_fixture_environment_restore_fault_never_masks_first(monkeypatch,primary):
    budget,_=setup_parent(monkeypatch)
    prior=dict(os.environ);prior['TALLI_RF_RESTORE_OWNER_TOKEN']='old-token'
    second=RuntimeError('restore-env')
    class Environment(dict):
        def __setitem__(self,key,value):
            if key=='TALLI_RF_RESTORE_OWNER_TOKEN' and value=='old-token':raise second
            return super().__setitem__(key,value)
    environment=Environment(prior)
    monkeypatch.setattr(driver.os,'environ',environment)
    with pytest.raises(BaseException) as caught:
        with owner_scope(budget):
            if primary is not None:raise primary
    assert caught.value is (primary if primary is not None else second)
    assert budget.context.owner.uncertain and budget.context.owner.primary is caught.value
    assert all(environment.get(k)==prior.get(k) for k in ('DATABASE_URL','SUPABASE_URL','TALLI_SUPABASE_WORKDIR'))


@pytest.mark.parametrize('failure',['local','source','image','keys'])
def test_owner_fixture_before_write_admission_failure_has_no_child(monkeypatch,failure):
    budget,events=setup_parent(monkeypatch)
    def refuse(*a,**kw):raise ValueError('owned-source-refused')
    if failure=='local':monkeypatch.setattr(driver.control,'require_local_docker',refuse)
    elif failure=='source':monkeypatch.setattr(driver.identity,'owned_identity_source',refuse)
    elif failure=='image':monkeypatch.setattr(driver.identity,'owned_identity_source',lambda *a:({'Image':'wrong'}, {}, {}))
    with pytest.raises(ValueError):
        with driver.focused_owner_session('postgresql://private','http://127.0.0.1:54321',Path('/private/generated'),object(),budget,
            anon_key='' if failure=='keys' else 'generated-anon',service_key='generated-service'):
            pytest.fail('unowned write admitted')
    assert 'child' not in events


def test_owner_fixture_child_drip_past_work_cutoff_rejects_before_next_request(monkeypatch):
    transport,calls=mock_auth()
    value=fixture_input();real=time.monotonic
    counter=0
    def clock():
        nonlocal counter
        counter+=1
        return value['work_end']+1 if counter>=5 else real()
    monkeypatch.setattr(driver.time,'monotonic',clock)
    with pytest.raises(ValueError):driver._fixture_http(value,transport=transport)
    assert sum(isinstance(c,dict) for c in calls)<=1 and calls[-1]=='transport_close'


@pytest.mark.parametrize('raw',[b'{"unknown":1e999}',b'{"unknown":[{"x":-1e999}]}'])
def test_owner_fixture_rejects_nonfinite_json_overflow_in_unknown_fields(raw):
    with pytest.raises(ValueError):driver._fixture_json(raw,65536)


@pytest.mark.parametrize('where',['ownership','reply'])
def test_owner_fixture_late_positive_scope_refuses_m0(monkeypatch,where):
    budget,events=setup_parent(monkeypatch)
    primary=driver.control.RestoreUnavailable('deadline')
    if where=='ownership':
        def expire(*args):raise primary
        monkeypatch.setattr(driver.identity,'owned_identity_source',expire)
    else:
        tokencheck=driver._fixture_token
        def expire(*args):
            tokencheck(*args)
            raise primary
        monkeypatch.setattr(driver,'_fixture_token',expire)
    end=budget.end
    with pytest.raises(driver.control.RestoreUnavailable) as caught:
        with owner_scope(budget):pytest.fail('late positive admitted')
    assert caught.value is primary and budget.end==end
    if where=='ownership':assert 'child' not in events


def test_owner_fixture_alarm_read_uses_timestamp_before_getitimer(monkeypatch):
    budget,events=setup_parent(monkeypatch)
    now=time.monotonic()
    times=iter([now,now,now+9])
    # If sampled after getitimer, the prior deadline would appear later than
    # the fixture cutoff. Only the conservative BEFORE sample refuses it.
    monkeypatch.setattr(driver.time,'monotonic',lambda:next(times))
    monkeypatch.setattr(driver.signal,'getitimer',lambda _: (2,0))
    with pytest.raises(ValueError):
        driver._fixture_setup('postgresql://private','http://127.0.0.1:54321',Path('/private/generated'),
            object(),budget,'generated-anon','generated-service')
    assert events==[]


def test_owner_fixture_success_child_output_only_after_transport_close(monkeypatch,capsys):
    import io
    transport,calls=mock_auth()
    original=driver._fixture_http
    monkeypatch.setattr(driver,'_fixture_http',lambda value:original(value,transport=transport))
    monkeypatch.setattr(driver.sys,'stdin',type('Input',(),{'buffer':io.BytesIO(driver.control.ledger.canonical(fixture_input()))})())
    raw=io.BytesIO()
    class Output:
        buffer=None
        def write(self,value):raise AssertionError('text output forbidden')
    class Sink:
        def write(self,value):
            assert calls[-1]=='transport_close'
            return raw.write(value)
        def flush(self):assert calls[-1]=='transport_close'
    output=Output();output.buffer=Sink()
    with monkeypatch.context() as m:
        m.setattr(driver.sys,'stdout',output)
        assert driver._fixture_child_main()==0
    value=driver._fixture_json(raw.getvalue(),32768)
    assert value['nonce']=='c'*32 and value['actor_id']==ACTOR
    assert capsys.readouterr()==('','')
