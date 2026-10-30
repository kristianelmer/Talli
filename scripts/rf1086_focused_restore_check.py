"""Observe real identity construction on a fresh, pinned-image fixture.

The caller body is empty: completing this diagnostic never proves RF business
recovery, reproduces an older archive, or replaces the full release rehearsal.
"""
import time

ENTRY_STARTED = time.monotonic()

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import base64
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import sys
import tomllib
from uuid import UUID, uuid4

import httpx

import rf1086_restore_control as control
import rf1086_identity_restore as identity
from rf1086_actual_replay_package import IMAGE


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "rf1086-focused-restore-check-v2"
FAILURE_SCHEMA = "rf1086-focused-post-construction-failure-v4"
CONSTRUCTION_PREFIX = "owned_identity_restore_construction "
CATALOG_PREFIX = "owned_identity_restore_catalog_diagnostic "
MAX_OUTPUT = 64 * 1024
SOURCE_PATHS = (
    "scripts/rf1086_focused_restore_check.py",
    "scripts/rf1086_identity_restore.py",
    "scripts/rf1086_restore_control.py",
    "scripts/rf1086_restore_metadata.py",
    "scripts/rf1086_catalog_difference.py",
    "scripts/rf1086_actual_replay_package.py",
    "scripts/test-corporate-reporting-owned-clone.py",
    "scripts/prepare-isolated-supabase-workdir.mjs",
    ".github/workflows/rf1086-focused-restore.yml",
)

FIXTURE_INPUT_SCHEMA = 'rf1086-focused-owner-session-input-v1'
FIXTURE_OUTPUT_SCHEMA = 'rf1086-focused-owner-session-output-v1'
FIXTURE_BYTES = 32768
FIXTURE_LAUNCHER = """import os,runpy,sys
if len(sys.argv)!=3 or sys.argv[2]!='--fixture-session': raise SystemExit(2)
p=sys.argv[1]
if not os.path.isabs(p) or os.path.realpath(p)!=p or os.path.basename(p)!='rf1086_focused_restore_check.py': raise SystemExit(2)
sys.path.insert(0,os.path.dirname(p))
sys.argv=[p,'--fixture-session']
runpy.run_path(p,run_name='__main__')
"""


def _fixture_json(raw, cap):
    need(type(raw) is bytes and 0 < len(raw) <= cap, 'fixture_binding')
    text = raw.decode('utf-8')
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            need(depth <= 16, 'fixture_binding')
        elif char in ']}':
            depth -= 1
    value = strict_json(text)
    need(type(value) is dict, 'fixture_binding')
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is float:
            need(math.isfinite(item), 'fixture_binding')
        elif type(item) is dict:
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
    return value


def _fixture_uuid(value):
    need(type(value) is str and len(value) == 36, 'fixture_binding')
    parsed = UUID(value)
    need(parsed.int != 0 and str(parsed) == value, 'fixture_binding')
    return value


def _fixture_api(value):
    need(type(value) is str and re.fullmatch(r'http://127\.0\.0\.1:([1-9][0-9]{0,4})/?', value), 'fixture_binding')
    need(1 <= int(value.rstrip('/').rsplit(':', 1)[1]) <= 65535, 'fixture_binding')
    return value.rstrip('/')


def _fixture_key(value):
    need(type(value) is str and 0 < len(value) <= 8192
         and re.fullmatch(r'[\x21-\x7e]+', value), 'fixture_binding')
    return value


def _fixture_token(token, actor, min_expiry):
    need(type(token) is str and 0 < len(token) <= 16384, 'fixture_binding')
    parts = token.split('.')
    need(len(parts) == 3 and all(re.fullmatch(r'[A-Za-z0-9_-]+', p) for p in parts), 'fixture_binding')
    decoded = []
    for part in parts:
        raw = base64.b64decode(part + '=' * (-len(part) % 4), altchars=b'-_', validate=True)
        need(raw and base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=') == part, 'fixture_binding')
        decoded.append(raw)
    claims = _fixture_json(decoded[1], 16384)
    need(claims.get('role') == 'authenticated' and _fixture_uuid(claims.get('sub')) == actor,
         'fixture_binding')
    _fixture_uuid(claims.get('session_id'))
    need(type(claims.get('exp')) is int and claims['exp'] > min_expiry, 'fixture_binding')
    return claims['exp']


def _fixture_cutoff(end):
    left = end - time.monotonic()
    need(left > 0, 'fixture_binding')
    return min(3, left)


def _fixture_input(raw):
    value = _fixture_json(raw, FIXTURE_BYTES)
    need(set(value) == {'schema', 'nonce', 'api_url', 'anon_key', 'service_key', 'work_end', 'min_expiry'}
         and value['schema'] == FIXTURE_INPUT_SCHEMA, 'fixture_binding')
    need(type(value['nonce']) is str and re.fullmatch(r'[a-f0-9]{32}', value['nonce']), 'fixture_binding')
    _fixture_api(value['api_url'])
    _fixture_key(value['anon_key']); _fixture_key(value['service_key'])
    for key in ('work_end', 'min_expiry'):
        need(type(value[key]) in (int, float) and math.isfinite(value[key]), 'fixture_binding')
    need(0 < value['work_end'] - time.monotonic() <= 10, 'fixture_binding')
    return value


def _fixture_http(value, *, transport=None):
    """Child-only private protocol; the parent owns termination of hung closes."""
    end = value['work_end']
    api = _fixture_api(value['api_url'])
    responses = []
    client = None
    primary = None
    try:
        _fixture_cutoff(end)
        if transport is None:
            transport = httpx.HTTPTransport(retries=0, trust_env=False, http2=False,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0))
        client = httpx.Client(transport=transport, trust_env=False, follow_redirects=False,
                             timeout=_fixture_cutoff(end))

        def request(method, path, apikey, bearer, body=None):
            headers = {'apikey': apikey, 'Authorization': 'Bearer ' + bearer,
                       'X-Supabase-Api-Version': '2024-01-01', 'Accept': 'application/json',
                       'Accept-Encoding': 'identity'}
            req = client.build_request(method, api + path, headers=headers, json=body,
                                       timeout=_fixture_cutoff(end))
            need('cookie' not in req.headers, 'fixture_binding')
            response = client.send(req, stream=True, follow_redirects=False)
            responses.append(response)
            _fixture_cutoff(end)
            need(response.status_code == 200 and 'set-cookie' not in response.headers
                 and response.headers.get('content-encoding', 'identity').lower() == 'identity', 'fixture_binding')
            media = response.headers.get('content-type', '').lower().replace(' ', '')
            need(media in ('application/json', 'application/json;charset=utf-8'), 'fixture_binding')
            length = response.headers.get('content-length')
            if length is not None:
                need(re.fullmatch(r'[0-9]{1,6}', length) and int(length) <= 65536, 'fixture_binding')
            raw = bytearray()
            for chunk in response.iter_raw(chunk_size=4096):
                _fixture_cutoff(end)
                need(len(raw) + len(chunk) <= 65536, 'fixture_binding')
                raw.extend(chunk)
            need(length is None or len(raw) == int(length), 'fixture_binding')
            _fixture_cutoff(end)
            try:
                result = _fixture_json(bytes(raw), 65536)
            finally:
                raw.clear()
            _fixture_cutoff(end)
            return result

        email = 'rf-focused-' + uuid4().hex + '@example.test'
        password = 'Aa1!' + secrets.token_urlsafe(32)
        created = request('POST', '/auth/v1/admin/users', value['service_key'], value['service_key'],
                          {'email': email, 'password': password, 'email_confirm': True})
        actor = _fixture_uuid(created.get('id'))
        need(created.get('role') == 'authenticated', 'fixture_binding')
        created.clear()
        signed = request('POST', '/auth/v1/token?grant_type=password', value['anon_key'], value['anon_key'],
                         {'email': email, 'password': password})
        need(type(signed.get('user')) is dict and signed['user'].get('id') == actor
             and signed.get('token_type') == 'bearer', 'fixture_binding')
        expiry = _fixture_token(signed.get('access_token'), actor, value['min_expiry'])
        need(type(signed.get('expires_in')) in (int, float) and math.isfinite(signed['expires_in'])
             and 0 < signed['expires_in'] <= 86400, 'fixture_binding')
        need('expires_at' not in signed or type(signed['expires_at']) is int
             and signed['expires_at'] == expiry, 'fixture_binding')
        token = signed['access_token']
        signed.clear()
        user = request('GET', '/auth/v1/user', value['anon_key'], token)
        need(user.get('id') == actor, 'fixture_binding')
        user.clear()
        result = {'schema': FIXTURE_OUTPUT_SCHEMA, 'nonce': value['nonce'],
                  'access_token': token, 'actor_id': actor}
    except BaseException as error:
        primary = error
        raise
    finally:
        errors = []
        for item in [*responses, client, transport]:
            if item is not None:
                try:
                    item.close()
                except BaseException as error:
                    errors.append(error)
        if errors:
            raise primary if primary is not None else errors[0]
    _fixture_cutoff(end)
    _fixture_token(result['access_token'], result['actor_id'], value['min_expiry'])
    return result


def _fixture_child_main():
    try:
        value = _fixture_input(sys.stdin.buffer.read(FIXTURE_BYTES + 1))
        result = _fixture_http(value)
        raw = control.ledger.canonical(result)
        need(len(raw) <= FIXTURE_BYTES, 'fixture_binding')
        _fixture_cutoff(value['work_end'])
        sys.stdout.buffer.write(raw)
        sys.stdout.buffer.flush()
        return 0
    except BaseException:
        sys.stderr.write('fixture_session_unavailable\n')
        return 1


def _fixture_argv():
    return [sys.executable, '-I', '-B', '-c', FIXTURE_LAUNCHER,
            str(Path(__file__).resolve(strict=True)), '--fixture-session']


def _fixture_uncertain(budget, error, primary):
    budget.context.owner._uncertain('fixture_restore', error, primary)
    raise primary if primary is not None else error


def _fixture_setup(database_url, api_url, workdir, boundary, budget, anon_key, service_key):
    original_end = budget.end
    original = (budget.phase, budget.started, budget.context, dict(budget.phase_elapsed))
    need(budget.phase == 'construction', 'fixture_binding')
    end = min(original_end, time.monotonic() + 10)
    read_started = time.monotonic()
    left, _ = signal.getitimer(signal.ITIMER_REAL)
    need(left == 0 or read_started + left > end, 'fixture_binding')
    primary = None
    raw = reply = value = None
    try:
        budget.end = end
        try:
            with control._connection_signals(budget):
                try:
                    with control.io_deadline(budget, end=end):
                        try:
                            api_url = _fixture_api(api_url)
                            _fixture_key(anon_key); _fixture_key(service_key)
                            control.require_local_docker(budget)
                            db, _, _ = identity.owned_identity_source(workdir, database_url,
                                                                    control.bounded_boundary(boundary, budget))
                            need(db.get('Image') == IMAGE, 'fixture_binding')
                            budget.remaining(reserve=2, end=end)
                            nonce = secrets.token_hex(16)
                            minimum = time.time() + max(0, budget.started + 180 - time.monotonic()) + 30
                            raw = control.ledger.canonical({'schema': FIXTURE_INPUT_SCHEMA, 'nonce': nonce,
                                'api_url': api_url, 'anon_key': anon_key, 'service_key': service_key,
                                'work_end': end - 2, 'min_expiry': minimum})
                            need(len(raw) <= FIXTURE_BYTES, 'fixture_binding')
                            reply = control.io_command(budget, _fixture_argv(), data=raw, cap=FIXTURE_BYTES, end=end)
                            value = _fixture_json(reply, FIXTURE_BYTES)
                            need(set(value) == {'schema', 'nonce', 'access_token', 'actor_id'}
                                 and value['schema'] == FIXTURE_OUTPUT_SCHEMA and value['nonce'] == nonce, 'fixture_binding')
                            actor = _fixture_uuid(value['actor_id'])
                            minimum = time.time() + max(0, budget.started + 180 - time.monotonic()) + 30
                            _fixture_token(value['access_token'], actor, minimum)
                            budget.remaining(end=end)
                            token = value['access_token']
                        except BaseException as error:
                            primary = error
                            raise
                except BaseException as error:
                    if primary is None:
                        primary = error
                        _fixture_uncertain(budget, error, primary)
                    if error is not primary:
                        _fixture_uncertain(budget, error, primary)
                    raise
        except BaseException as error:
            if primary is None or error is not primary:
                _fixture_uncertain(budget, error, primary)
            raise
    finally:
        pending = primary if primary is not None else sys.exception()
        raw = reply = value = None
        try:
            budget.end = original_end
            need((budget.phase, budget.started, budget.context, budget.phase_elapsed) == original,
                 'fixture_binding')
        except BaseException as error:
            _fixture_uncertain(budget, error, pending)
    budget.context.raise_if_fatal()
    return token


@contextmanager
def focused_owner_session(database_url, api_url, workdir, boundary, budget, *, anon_key, service_key):
    changes = {'DATABASE_URL': database_url, 'SUPABASE_URL': api_url,
               'TALLI_SUPABASE_WORKDIR': str(workdir), 'TALLI_RF_RESTORE_OWNER_TOKEN': None}
    previous = {key: os.environ.get(key) for key in changes}
    primary = None
    token = None
    try:
        for key, value in changes.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        try:
            with control.budget_scope(budget):
                try:
                    token = _fixture_setup(database_url, api_url, workdir, boundary, budget, anon_key, service_key)
                except BaseException as error:
                    primary = error
                    raise
        except BaseException as error:
            if primary is None or error is not primary:
                _fixture_uncertain(budget, error, primary)
            raise
        os.environ['TALLI_RF_RESTORE_OWNER_TOKEN'] = token
        yield
    except BaseException as error:
        primary = error
        raise
    finally:
        errors = []
        for key, value in previous.items():
            try:
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            except BaseException as error:
                errors.append(error)
        token = anon_key = service_key = None
        if errors:
            for error in errors:
                budget.context.owner._uncertain('fixture_environment', error, primary)
            raise primary if primary is not None else errors[0]


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            need(key not in value, "producer_output")
            value[key] = item
        return value

    def invalid(_):
        raise ValueError("producer_output")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


class PrivateOutput:
    """Keep bounded producer text in memory; never echo unknown output."""
    def __init__(self):
        self.parts = []
        self.bytes = 0

    def write(self, value):
        need(type(value) is str, "producer_output")
        size = len(value.encode("utf-8"))
        need(self.bytes + size <= MAX_OUTPUT, "producer_output")
        self.bytes += size
        self.parts.append(value)
        return len(value)

    def flush(self):
        pass

    def records(self, prefix):
        result = []
        for line in "".join(self.parts).splitlines():
            if line.startswith(prefix):
                raw = line[len(prefix):].encode("utf-8")
                need(len(raw) <= 24 * 1024, "producer_output")
                value = strict_json(raw)
                need(control.ledger.canonical(value) == raw, "producer_output")
                result.append((value, hashlib.sha256(raw).hexdigest()))
        return result

    def clear(self):
        self.parts.clear()
        self.bytes = 0


@contextmanager
def local_environment(database_url, api_url, workdir):
    changes = {"DATABASE_URL": database_url, "SUPABASE_URL": api_url,
               "TALLI_SUPABASE_WORKDIR": str(workdir)}
    previous = {key: os.environ.get(key) for key in changes}
    os.environ.update(changes)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def source_bindings():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in SOURCE_PATHS}


def failure_details(error, budget, *, construction=None):
    try:
        with control.io_deadline(budget, end=min(budget.end, time.monotonic() + 0.250)):
            endpoint = startup = None
            if type(error) is control.EndpointAdmissionFailure:
                service, predicate = error.service, error.predicate
                if (type(service) is str and service in control.ENDPOINT_ADMISSION_SERVICES
                        and type(predicate) is str and predicate in control.ENDPOINT_ADMISSION_PREDICATES):
                    endpoint = {"service": service, "predicate": predicate}
                fields = BaseException.__dict__['__dict__'].__get__(error, type(error))
                if endpoint == {'service':'auth','predicate':'running'} and fields.get('auth_startup') is not None:
                    try:
                        need(type(construction) is dict and construction['status'] == 'constructed'
                             and construction['cleanupComplete'] is True
                             and construction['identitySourcePostcheck'] is True
                             and construction['fingerprints']['source'] is not None
                             and construction['fingerprints']['source'] == construction['fingerprints']['target'],
                             'producer_output')
                        delivery = construction['delivery']; original = delivery['original']; writer = delivery['writer']
                        need(type(original) is dict and set(original) == {'bytes','sha256'}
                             and type(original['bytes']) is int and 0 < original['bytes'] <= control.MAX_SCRIPT
                             and original == construction['bindings']['script']
                             and writer['stdoutEnd'] == writer['stderrEnd'] == 'eof'
                             and type(writer['exitCode']) is int and writer['exitCode'] == 0
                             and writer['reap'] == 'waited', 'producer_output')
                        control._diagnostic_hash(original['sha256'])
                        need(type(construction['identities']) is dict, 'producer_output')
                        candidate = control.validate_auth_startup(fields['auth_startup'], identities=construction['identities'])
                        # Canonical roundtrip copies only the already validated finite fields.
                        startup = strict_json(control.ledger.canonical(candidate))
                    except Exception:
                        budget.context.raise_if_fatal()
                        startup = None
            return {"location": control._diagnostic_location(error, budget),
                    "endpointAdmission": endpoint, "authStartup": startup}
    except Exception:
        budget.context.raise_if_fatal()
        return {"location": None, "endpointAdmission": None, "authStartup": None}


def run_context(database_url, api_url, workdir, boundary, budget):
    private = PrivateOutput()
    entered = completed = False
    failure = None
    try:
        with local_environment(database_url, api_url, workdir):
            with redirect_stdout(private), redirect_stderr(private):
                try:
                    with identity.restored_identity(database_url, workdir, boundary, budget=budget):
                        entered = True
                        # Deliberately no filing, browser, or business assertions.
                    completed = True
                except Exception as error:
                    failure = error
        records = private.records(CONSTRUCTION_PREFIX)
        diagnostics = private.records(CATALOG_PREFIX)
        preparation = private.records(control.DIAGNOSTIC_PREFIX)
        need(len(records) == 1 and len(diagnostics) <= 1 and len(preparation) <= 1, "producer_output")
        receipt, receipt_hash = records[0]
        need(type(receipt) is dict and receipt.get("schema") == control.SCHEMA,
             "producer_output")
        need(set(receipt) == set("schema status reason configurationSha256 code bindings identities counts hooks mutations delivery observers fingerprints cleanupComplete identitySourcePostcheck businessComplete outerBusinessPostchecks phaseElapsedSeconds".split()), "producer_output")
        need(receipt["status"] in ("constructed", "unavailable")
             and (receipt["reason"] is None or receipt["reason"] in control.REASONS), "producer_output")
        need(type(receipt["cleanupComplete"]) is bool
             and type(receipt["identitySourcePostcheck"]) is bool, "producer_output")
        fingerprints = receipt["fingerprints"]
        need(type(fingerprints) is dict and set(fingerprints) == {"source", "target"},
             "producer_output")
        for value in fingerprints.values():
            need(value is None or (type(value) is dict
                 and set(value) == {"roles", "catalog", "auth", "companyMemberships"}
                 and all(type(x) is str and re.fullmatch("[a-f0-9]{64}", x)
                         for x in value.values())), "producer_output")
        clean = receipt["cleanupComplete"] and receipt["identitySourcePostcheck"]
        matching = fingerprints["source"] is not None and fingerprints["source"] == fingerprints["target"]
        catalog_mismatch = (fingerprints["source"] is not None
                            and fingerprints["target"] is not None
                            and fingerprints["source"]["catalog"] != fingerprints["target"]["catalog"])
        outcome = "unavailable"
        if completed and entered and failure is None and clean and matching and receipt["status"] == "constructed":
            outcome = "identity_context_completed"
        elif not entered and failure is not None and clean and catalog_mismatch and receipt["reason"] == "postcondition":
            outcome = "catalog_postcondition_rejected"
        diagnostic = diagnostics[0][0] if diagnostics else None
        # A closed producer schema and its exact construction commitment are
        # validated again by the manifest-bound, offline evidence reader.
        if diagnostic is not None:
            need(catalog_mismatch and type(diagnostic) is dict, "producer_output")
            control.validate_catalog_postcondition(
                diagnostic, construction_raw=control.ledger.canonical(receipt).decode("ascii"))
        pre_target = preparation[0][0] if preparation else None
        if pre_target is not None:
            control.validate_pre_target_diagnostic(pre_target)
        post_failure = None
        if (failure is not None and not entered and not completed and clean and matching
                and receipt["status"] == "constructed"):
            post_failure = {"schema": FAILURE_SCHEMA, "constructionSha256": receipt_hash,
                            **failure_details(failure, budget, construction=receipt)}
        return {"identityOutcome": outcome, "identityContextEntered": entered,
                "identityContextCompleted": completed, "construction": receipt,
                "constructionReceiptSha256": receipt_hash,
                "catalogDiagnostic": diagnostic, "preTargetDiagnostic": pre_target,
                "postConstructionFailure": post_failure}
    finally:
        private.clear()


def check(started=ENTRY_STARTED):
    budget = control.RecoveryBudget(started)
    run, attempt, job = (os.environ[name] for name in
                         ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB"))
    need(re.fullmatch(r"[1-9][0-9]{0,19}", run)
         and re.fullmatch(r"[1-9][0-9]{0,5}", attempt)
         and job == "focused-restore", "run_binding")
    candidate = os.environ["GITHUB_SHA"]
    need(re.fullmatch(r"[a-f0-9]{40}", candidate), "candidate_binding")
    head = budget.command(["git", "rev-parse", "HEAD"], cap=4096,
                          end=min(budget.end, time.monotonic() + 5)).decode("ascii").strip()
    need(head == candidate, "candidate_binding")
    workdir = Path(os.environ["TALLI_FOCUSED_WORKDIR"]).resolve(strict=True)
    need(workdir.name.startswith("talli-supabase-local."), "workdir_binding")
    config = tomllib.loads((workdir / "supabase/config.toml").read_text())
    project = config["project_id"]
    need(type(project) is str and re.fullmatch(r"tallig[0-9]+", project), "workdir_binding")
    status = strict_json(budget.command(
        ["npm", "exec", "--", "supabase", "status", "--workdir", str(workdir), "--output", "json"],
        cap=64 * 1024, end=min(budget.end, time.monotonic() + 12)))
    need(type(status) is dict, "fixture_binding")
    database_url, api_url = status.get("DB_URL"), status.get("API_URL")
    anon_key, service_key = status.get('ANON_KEY'), status.get('SERVICE_ROLE_KEY')
    need(all(type(v) is str and 0 < len(v) <= 4096 for v in (database_url, api_url)), "fixture_binding")
    del status
    container = "supabase_db_" + project
    actual_image = budget.command(["docker", "inspect", "--format", "{{.Image}}", container],
                                  cap=4096, end=min(budget.end, time.monotonic() + 8)).decode("ascii").strip()
    need(actual_image == IMAGE, "image_binding")
    server = budget.command(["docker", "exec", container, "psql", "-XAt", "-U", "postgres",
                             "-d", "postgres", "-c", "SHOW server_version"], cap=4096)
    dump = budget.command(["docker", "exec", container, "pg_dump", "--version"], cap=4096)
    need(re.fullmatch(rb"17\.6(?: \([^\r\n]{1,128}\))?\s*", server)
         and re.fullmatch(rb"pg_dump \(PostgreSQL\) 17\.6\s*", dump), "version_binding")
    spec = importlib.util.spec_from_file_location("focused_owned_boundary", ROOT / "scripts/test-corporate-reporting-owned-clone.py")
    boundary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boundary)
    try:
        with focused_owner_session(database_url, api_url, workdir, boundary, budget,
                                   anon_key=anon_key, service_key=service_key):
            result = run_context(database_url, api_url, workdir, boundary, budget)
    finally:
        anon_key = service_key = None
    budget.enter("output")
    with control.io_deadline(budget):
        diagnostic_complete = (result["identityOutcome"] == "identity_context_completed"
                               or (result["identityOutcome"] == "catalog_postcondition_rejected"
                                   and result["catalogDiagnostic"] is not None
                                   and result["catalogDiagnostic"]["status"] == "observed"))
        result.update(schema=SCHEMA, candidate=candidate, run=run, attempt=attempt, job=job,
                      image=IMAGE, serverVersion="17.6", sources=source_bindings(),
                      scope="generated_same_image_production_identity_context",
                      businessVerified=False, originalArchiveReplayed=False,
                      originalFailureCauseKnown=False,
                      diagnosticComplete=diagnostic_complete,
                      elapsedSeconds=round(time.monotonic() - started, 3))
        raw = control.ledger.canonical(result)
        need(len(raw) <= MAX_OUTPUT, "producer_output")
        print(raw.decode("ascii"), flush=True)
    return 0 if diagnostic_complete else 1


def main():
    try:
        return check()
    except (KeyboardInterrupt, SystemExit):
        print(json.dumps({"schema": SCHEMA, "status": "unavailable", "reason": "cancelled"}, sort_keys=True), file=sys.stderr)
        return 130
    except Exception as error:
        allowed = {"run_binding", "candidate_binding", "workdir_binding", "fixture_binding",
                   "image_binding", "version_binding", "producer_output"}
        reason = str(error) if type(error) is ValueError and str(error) in allowed else "focused_restore_unavailable"
        print(json.dumps({"schema": SCHEMA, "status": "unavailable", "reason": reason}, sort_keys=True), file=sys.stderr)
        return 1


def entrypoint(args):
    if args == ['--fixture-session']:
        return _fixture_child_main()
    if not args:
        return main()
    print('fixture_session_unavailable', file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(entrypoint(sys.argv[1:]))
