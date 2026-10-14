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
    return {'schema':'rf1086-auth-startup-tail-v1','evidence':'source-pattern-compatible-only',
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
    assert failure['schema']=='rf1086-focused-post-construction-failure-v3'
    assert failure['authStartup']==primary.auth_startup and failure['authStartup'] is not primary.auth_startup
    assert failure['authStartup']['classification']['reportedSQLSTATE']=='28P01'
    assert failure['constructionSha256']==result['constructionReceiptSha256']
    assert result['identityOutcome']=='unavailable' and not result['identityContextEntered']
    primary.auth_startup['state']['status']='private-mutated'
    assert failure['authStartup']['state']['status']=='exited' and capsys.readouterr()==('','')


@pytest.mark.parametrize('fault',['source','target','same-auth','missing','extra','schema','evidence',
    'state-status','state-exit-bool','state-oom','tail-count-bool','tail-empty-hash','tail-overflow',
    'tail-fatal-count','stage','code','code-simple','extra-nested','hash-uppercase'])
def test_auth_startup_export_rejects_forged_finite_fields_preserving_endpoint(monkeypatch,fault):
    primary=driver.control.EndpointAdmissionFailure('auth','running');value=auth_startup_value()
    if fault=='source':value['sourceIdentitySha256']='a'*64
    elif fault=='target':value['targetIdentitySha256']='b'*64
    elif fault=='same-auth':value['authIdentitySha256']=value['targetIdentitySha256']
    elif fault=='missing':del value['state']
    elif fault=='extra':value['private']='canary'
    elif fault=='schema':value['schema']='private'
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
def test_auth_startup_export_cancellation_preserves_token_and_clears_private(monkeypatch,error):
    primary=driver.control.EndpointAdmissionFailure('auth','running');primary.auth_startup=auth_startup_value()
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
    assert diagnostic['schema'] == 'rf1086-focused-post-construction-failure-v3'
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
    assert diagnostic['schema'] == 'rf1086-focused-post-construction-failure-v3'
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
                return b'{"DB_URL":"postgresql://private","API_URL":"http://127.0.0.1:54321","SECRET_KEY":"must-never-escape"}'
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
