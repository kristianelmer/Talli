"""Offline transport bounds, identity, failure secrecy and inactive template checks."""
from copy import deepcopy
import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import textwrap
import time
from types import SimpleNamespace

import httpx
import pytest

from talli_backend.adapters import hosted_recovery_mailbox as mailbox
from talli_backend.adapters.hosted_recovery_diagnostics import SafeTransportFailure, safe_failure
from talli_backend.adapters.hosted_recovery_window import Deadline, bounded_rpc


REAL_CLIENT = httpx.Client
TEMPLATE = Path(__file__).resolve().parents[3] / 'docs/security/workflows/talli-recovery-cleanup.yml'


def binding():
    return {'version': 1, 'windowId': 'bbfb254c-9bb0-4844-a14d-4e279bd5a724',
        'authoritySha256': 'a' * 64, 'configSha256': 'b' * 64, 'commit': 'c' * 40,
        'repository': 'owner/talli', 'workflowPath': mailbox.WORKFLOW_PATH,
        'runId': 123, 'runAttempt': 1, 'jobId': 456, 'issueNumber': 192,
        'cleanupAtUtc': '2099-11-03T12:00:00Z', 'armBeforeUtc': '2099-11-03T11:00:00Z',
        'coordinatorPublicKey': 'd' * 64, 'mode': 'metadata-only'}


def envelope(**payload):
    return {'version': 1, 'binding': binding(), 'kind': 'heartbeat',
        'nonce': 'dbf54d29-a95a-4b9b-bbfb-062c19499cf4',
        'issuedAtUtc': '2099-11-03T11:10:00Z', 'payload': payload, 'signature': 'e' * 128}


def comment(number=10, value=None):
    return {'id': number, 'body': mailbox.PREFIX + mailbox._canonical(value or envelope()).decode()}


def run():
    return {'id': 123, 'repository': {'full_name': 'owner/talli'},
        'path': mailbox.WORKFLOW_PATH, 'head_sha': 'c' * 40, 'run_attempt': 1,
        'status': 'in_progress', 'conclusion': None, 'event': 'workflow_dispatch'}


def job():
    return {'id': 456, 'run_id': 123, 'head_sha': 'c' * 40,
        'name': mailbox.JOB_NAME, 'status': 'in_progress', 'conclusion': None}


def artifact():
    return {'id': 789, 'name': 'recovery-arm-123-a1', 'digest': 'sha256:' + 'f' * 64,
        'expired': False, 'expires_at': '2099-11-04T12:00:00Z', 'size_in_bytes': 2048,
        'workflow_run': {'id': 123, 'head_sha': 'c' * 40}}


class Pipe:
    def __init__(self):
        self.raw = None
        self.closed = False

    def send_bytes(self, raw):
        assert self.raw is None
        self.raw = raw

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def deny_real_http(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('unit test attempted non-mocked HTTP')
    monkeypatch.setattr(mailbox.httpx, 'Client', deny)


@pytest.fixture
def credentials(tmp_path):
    path = tmp_path / 'credentials.json'
    path.write_text(json.dumps({'githubToken': 'fake-github-token-not-a-real-credential',
        'managementToken': 'private-management-sentinel-never-send'}))
    path.chmod(0o600)
    return path


@pytest.fixture
def http(monkeypatch, credentials):
    calls, clients = [], []
    handler = lambda request: httpx.Response(200, json=[])

    def install(callback):
        nonlocal handler
        handler = callback

    def transport(request):
        calls.append(request)
        assert request.url.scheme == 'https' and request.url.host == 'api.github.com'
        assert request.headers['authorization'] == 'Bearer fake-github-token-not-a-real-credential'
        assert b'private-management-sentinel' not in request.content
        assert request.headers['x-github-api-version'] == '2026-03-10'
        return handler(request)

    def client(**kwargs):
        clients.append(kwargs)
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        assert isinstance(kwargs['timeout'], httpx.Timeout)
        return REAL_CLIENT(transport=httpx.MockTransport(transport), **kwargs)

    def rpc(target, args, *, deadline, max_bytes):
        assert target is mailbox._request and deadline.open()
        assert max_bytes == mailbox.MAX_RESPONSE
        pipe = Pipe()
        target(pipe, *args)
        assert pipe.closed and len(pipe.raw) <= max_bytes
        result = json.loads(pipe.raw)
        if not result['ok']:
            raise SafeTransportFailure(result['failure'])
        return result['value']

    monkeypatch.setattr(mailbox.httpx, 'Client', client)
    monkeypatch.setattr(mailbox, 'bounded_rpc', rpc)
    return install, calls, clients, mailbox.GitHubMailbox(binding(), credentials)


def test_publish_uses_only_exact_issue_post_and_canonical_envelope(http):
    install, calls, _, transport = http
    value = envelope(commandSeq=1)
    install(lambda r: httpx.Response(201, json={'id': 11, 'body': json.loads(r.content)['body']}))
    assert transport.publish(value) is None
    assert len(calls) == 1 and calls[0].method == 'POST'
    assert calls[0].url.path == '/repos/owner/talli/issues/192/comments'
    assert json.loads(calls[0].content) == {'body': mailbox.PREFIX + mailbox._canonical(value).decode()}


def test_reads_all_pages_deduplicates_and_history_does_not_consume_cursor(http):
    install, calls, _, transport = http
    rows = [comment(10), comment(20, envelope(commandSeq=2))]
    def handler(request):
        page = int(request.url.params['page'])
        return httpx.Response(200, json=[rows[page - 1]], headers=({'Link':
            '<https://api.github.com/repos/owner/talli/issues/192/comments?page=2&per_page=100>; rel="next"'}
            if page == 1 else {}))
    install(handler)
    assert transport.history() == [envelope(), envelope(commandSeq=2)]
    assert transport.read() == transport.history()
    assert transport.read() == []
    rows.append(comment(30, envelope(commandSeq=3)))
    install(lambda _: httpx.Response(200, json=rows))
    assert transport.read() == [envelope(commandSeq=3)]
    assert all(r.method == 'GET' and 'since' not in r.url.params for r in calls)


def test_unrelated_comments_and_other_binding_ignored(http):
    install, _, _, transport = http
    other = envelope()
    other['binding']['windowId'] = 'f8ce8481-a148-450c-bdab-0ed402ebc3ed'
    install(lambda _: httpx.Response(200, json=[{'id': 1, 'body': 'ordinary discussion'},
        comment(2, other), comment(3)]))
    assert transport.read() == [envelope()]


@pytest.mark.parametrize('rows', [
    [comment(10), comment(10)], [comment(20), comment(10)],
    [{'id': True, 'body': 'discussion'}],
    [{'id': 1, 'body': mailbox.PREFIX + '{"secret":"do-not-leak",broken'}],
    [{'id': 1, 'body': mailbox.PREFIX + '{"binding":{},"binding":{}}'}],
    [{'id': 1, 'body': mailbox.PREFIX + '{ "binding": {} }'}],
    [{'id': 1, 'body': mailbox.PREFIX + '[]'}],
    [{'id': 1, 'body': mailbox.PREFIX + 'x' * mailbox.MAX_BODY}],
])
def test_malformed_messages_fail_without_raw_text_or_cursor_advance(http, rows):
    install, _, _, transport = http
    install(lambda _: httpx.Response(200, json=rows))
    with pytest.raises((ValueError, SafeTransportFailure)) as caught:
        transport.read()
    assert 'do-not-leak' not in str(caught.value)
    assert transport._seen == {}


def test_modified_protocol_comment_is_not_silently_reaccepted(http):
    install, _, _, transport = http
    install(lambda _: httpx.Response(200, json=[comment()]))
    transport.read()
    install(lambda _: httpx.Response(200, json=[comment(value=envelope(changed=True))]))
    with pytest.raises(ValueError, match='hosted_mailbox_comment_changed'):
        transport.read()


@pytest.mark.parametrize('rows', [[], [{'id': 10, 'body': 'edited into ordinary discussion'}]])
def test_known_comment_deletion_or_conversion_to_unrelated_text_fails_closed(http, rows):
    install, _, _, transport = http
    install(lambda _: httpx.Response(200, json=[comment()]))
    transport.read()
    install(lambda _: httpx.Response(200, json=rows))
    with pytest.raises(ValueError, match='hosted_mailbox_comment_'):
        transport.read()


@pytest.mark.parametrize('next_url', [
    'http://api.github.com/repos/owner/talli/issues/192/comments?per_page=100&page=2',
    'https://evil.invalid/repos/owner/talli/issues/192/comments?per_page=100&page=2',
    'https://api.github.com@evil.invalid/repos/owner/talli/issues/192/comments?per_page=100&page=2',
    'https://api.github.com:443/repos/owner/talli/issues/192/comments?per_page=100&page=2',
    'https://api.github.com/repos/owner/talli/issues/193/comments?per_page=100&page=2',
    'https://api.github.com/repos/owner/talli/issues/192/comments?per_page=100&page=1',
    'https://api.github.com/repos/owner/talli/issues/192/comments?per_page=100&page=3',
    'https://api.github.com/repos/owner/talli/issues/192/comments?per_page=100&page=2&token=secret',
    'https://api.github.com/repos/owner/talli/issues/192/comments?per_page=100&page=2#fragment',
    'https://api.github.com/repos/owner/talli/issues/192/comments?per_page=100&page=2&page=2',
])
def test_untrusted_pagination_never_followed(http, next_url):
    install, calls, _, transport = http
    install(lambda _: httpx.Response(200, json=[comment()], headers={'Link': '<' + next_url + '>; rel="next"'}))
    with pytest.raises(SafeTransportFailure):
        transport.read()
    assert len(calls) == 1 and not transport._seen


def test_partial_scan_failure_keeps_cursor_unconsumed(http):
    install, _, _, transport = http
    def handler(request):
        if request.url.params['page'] == '2':
            return httpx.Response(403, text='secret-provider-body')
        return httpx.Response(200, json=[comment()], headers={'Link':
            '<https://api.github.com/repos/owner/talli/issues/192/comments?per_page=100&page=2>; rel="next"'})
    install(handler)
    with pytest.raises(SafeTransportFailure):
        transport.read()
    assert not transport._seen
    install(lambda _: httpx.Response(200, json=[comment()]))
    assert transport.read() == [envelope()]


def test_conditional_gets_revalidate_every_page_and_reuse_detached_cached_data(http):
    install, calls, _, transport = http
    def handler(request):
        page = int(request.url.params['page'])
        tag = '"page-%d"' % page
        if request.headers.get('if-none-match') == tag:
            return httpx.Response(304)
        return httpx.Response(200, json=[comment(page, envelope(commandSeq=page))], headers={
            'ETag': tag, **({'Link': '<https://api.github.com/repos/owner/talli/issues/192/comments?'
                'per_page=100&page=2>; rel="next"'} if page == 1 else {})})
    install(handler)
    first = transport.history()
    first[0]['payload']['commandSeq'] = 'caller changed detached result'
    assert transport.read() == [envelope(commandSeq=1), envelope(commandSeq=2)]
    assert transport.read() == []
    assert len(calls) == 6
    assert [r.headers.get('if-none-match') for r in calls] == [None, None,
        '"page-1"', '"page-2"', '"page-1"', '"page-2"']


def test_conditional_scan_still_follows_new_page_and_detects_etag_body_change(http):
    install, calls, _, transport = http
    install(lambda _: httpx.Response(200, json=[comment()], headers={'ETag': '"first"'}))
    assert transport.read() == [envelope()]
    def new_page(request):
        if request.url.params['page'] == '1':
            return httpx.Response(200, json=[comment()], headers={'ETag': '"changed"', 'Link':
                '<https://api.github.com/repos/owner/talli/issues/192/comments?per_page=100&page=2>; rel="next"'})
        return httpx.Response(200, json=[comment(20, envelope(commandSeq=2))], headers={'ETag': '"second"'})
    install(new_page)
    assert transport.read() == [envelope(commandSeq=2)]
    def changed_body(request):
        if request.url.params['page'] == '1':
            return httpx.Response(304)
        return httpx.Response(200, json=[comment(20, envelope(commandSeq=99))], headers={'ETag': '"second"'})
    install(changed_body)
    with pytest.raises(SafeTransportFailure):
        transport.read()
    assert len(transport._seen) == 2


def test_unsolicited_304_without_cache_fails_closed(http):
    install, calls, _, transport = http
    install(lambda _: httpx.Response(304))
    with pytest.raises(SafeTransportFailure):
        transport.history()
    assert len(calls) == 1


def test_full_terminal_cached_page_refreshes_links_to_discover_new_page(http):
    install, calls, _, transport = http
    rows = [comment(i + 1) for i in range(100)]
    install(lambda _: httpx.Response(200, json=rows, headers={'ETag': '"unchanged-body"'}))
    assert len(transport.read()) == 100
    def handler(request):
        if request.url.params['page'] == '1':
            assert 'if-none-match' not in request.headers
            return httpx.Response(200, json=rows, headers={'ETag': '"unchanged-body"', 'Link':
                '<https://api.github.com/repos/owner/talli/issues/192/comments?per_page=100&page=2>; rel="next"'})
        return httpx.Response(200, json=[comment(101, envelope(commandSeq=101))])
    install(handler)
    assert transport.read() == [envelope(commandSeq=101)]
    assert len(calls) == 3


def test_304_updated_pagination_headers_are_validated(http):
    install, calls, _, transport = http
    install(lambda _: httpx.Response(200, json=[comment()], headers={'ETag': '"first"'}))
    transport.read()
    install(lambda _: httpx.Response(304, headers={'Link':
        '<https://evil.invalid/comments?per_page=100&page=2>; rel="next"'}))
    with pytest.raises(SafeTransportFailure):
        transport.read()
    assert len(calls) == 2


@pytest.mark.parametrize('status, headers, delay', [
    (429, {'Retry-After': '123'}, 123), (429, {'Retry-After': '999999'}, 3600),
    (429, {'Retry-After': 'secret-value'}, 60), (403, {'X-RateLimit-Remaining': '0'}, 60),
    (403, {'Retry-After': '0'}, 1),
])
def test_rate_limit_is_safe_bounded_outcome_without_busy_retry(http, status, headers, delay):
    install, calls, _, transport = http
    install(lambda _: httpx.Response(status, text='SECRET-RATE-ERROR', headers=headers))
    with pytest.raises(mailbox.MailboxRateLimited) as caught:
        transport.publish(envelope())
    assert caught.value.retry_after_seconds == delay
    assert safe_failure(caught.value)['httpStatus'] == status
    assert 'SECRET' not in str(caught.value) + json.dumps(safe_failure(caught.value))
    assert len(calls) == 1 and not transport._seen


def test_exact_body_bound_and_oversize_publish(http):
    install, calls, _, transport = http
    value = envelope(text='')
    remaining = mailbox.MAX_BODY - len(mailbox.PREFIX.encode()) - len(mailbox._canonical(value))
    value['payload']['text'] = 'x' * remaining
    install(lambda r: httpx.Response(201, json={'id': 11, 'body': json.loads(r.content)['body']}))
    transport.publish(value)
    value['payload']['text'] += 'x'
    with pytest.raises(ValueError, match='hosted_mailbox_message_bound'):
        transport.publish(value)
    assert len(calls) == 1


def test_page_and_total_message_bounds_fail_closed(http):
    install, calls, _, transport = http
    def handler(request):
        page = int(request.url.params['page'])
        return httpx.Response(200, json=[comment(page * 100 + i) for i in range(100)],
            headers={'Link': '<https://api.github.com/repos/owner/talli/issues/192/comments?'
                'per_page=100&page=%d>; rel="next"' % (page + 1)})
    install(handler)
    with pytest.raises(SafeTransportFailure):
        transport.history()
    assert len(calls) == mailbox.MAX_PAGES
    assert not transport._seen


def test_exactly_3200_messages_on_32_pages_accepted(http):
    install, calls, _, transport = http
    def handler(request):
        page = int(request.url.params['page'])
        headers = {} if page == 32 else {'Link':
            '<https://api.github.com/repos/owner/talli/issues/192/comments?per_page=100&page=%d>; rel="next"' % (page + 1)}
        return httpx.Response(200, json=[comment(page * 100 + i) for i in range(100)], headers=headers)
    install(handler)
    assert len(transport.read()) == 3200
    assert len(calls) == 32


@pytest.mark.parametrize('status', [301, 302, 307, 401, 403, 404, 429, 500])
def test_http_failures_and_redirects_never_leak_or_retry_post(http, status, capsys):
    install, calls, _, transport = http
    install(lambda _: httpx.Response(status, text='RAW-RESPONSE-TOKEN', headers={'Location': 'https://evil.invalid/'}))
    with pytest.raises(SafeTransportFailure) as caught:
        transport.publish(envelope())
    assert len(calls) == 1
    assert 'RAW-RESPONSE-TOKEN' not in str(caught.value) + json.dumps(safe_failure(caught.value))
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('error', [RuntimeError('SECRET-RAW'),
    httpx.ReadTimeout('SECRET-RAW'), httpx.ConnectError('SECRET-RAW')])
def test_transport_exception_is_safe(http, error):
    install, _, _, transport = http
    def fail(_):
        raise error
    install(fail)
    with pytest.raises(SafeTransportFailure) as caught:
        transport.history()
    assert 'SECRET-RAW' not in str(caught.value) + json.dumps(safe_failure(caught.value))


def test_response_size_and_page_size_bounds(http):
    install, _, _, transport = http
    for response in (httpx.Response(200, content=b'X' * (mailbox.MAX_RESPONSE + 1)),
            httpx.Response(200, json=[comment(i + 1) for i in range(101)])):
        install(lambda _, response=response: response)
        with pytest.raises(SafeTransportFailure):
            transport.history()


@pytest.mark.parametrize('changes', [
    {'repository': '../talli'}, {'repository': 'owner/..'}, {'repository': 'owner/talli?x=y'},
    {'repository': 'owner/talli/issues/1'}, {'repository': 'owner%2fevil/talli'},
    {'issueNumber': True}, {'runId': 0}, {'jobId': '456'}, {'runAttempt': 2},
    {'workflowPath': '.github/workflows/other.yml'}, {'commit': 'c' * 39},
    {'windowId': '00000000-0000-0000-0000-000000000000'}, {'coordinatorPublicKey': '0' * 64},
    {'armBeforeUtc': '2099-11-03T11:00:00'}, {'extra': 'invalid'},
])
def test_binding_invalid_before_any_transport(credentials, changes):
    with pytest.raises(ValueError, match='hosted_mailbox_binding_invalid'):
        mailbox.GitHubMailbox({**binding(), **changes}, credentials)


@pytest.mark.parametrize('seconds', [0, -1, True, float('inf'), float('nan'), 61, '10'])
def test_invalid_call_bound(credentials, seconds):
    with pytest.raises(ValueError, match='hosted_mailbox_timeout_invalid'):
        mailbox.GitHubMailbox(binding(), credentials, seconds)


@pytest.mark.parametrize('kind', ['public', 'symlink', 'hardlink', 'missing', 'malformed'])
def test_credentials_private_file_and_no_raw_failures(http, credentials, tmp_path, kind):
    _, calls, _, transport = http
    if kind == 'public':
        credentials.chmod(0o644)
    elif kind == 'symlink':
        link = tmp_path / 'link.json'
        link.symlink_to(credentials)
        transport.credentials_path = str(link)
    elif kind == 'hardlink':
        os.link(credentials, tmp_path / 'alias.json')
    elif kind == 'missing':
        credentials.unlink()
    else:
        credentials.write_text('RAW-CREDENTIAL-SENTINEL')
    with pytest.raises(SafeTransportFailure) as caught:
        transport.read()
    assert not calls
    assert 'RAW-CREDENTIAL-SENTINEL' not in str(caught.value)


@pytest.mark.parametrize('route, method, page', [
    ('comments', 'DELETE', 1), ('run', 'POST', 1), ('https://evil.invalid', 'GET', 1),
    ('comments', 'GET', 0), ('comments', 'GET', 33), ('run', 'GET', 2),
])
def test_child_revalidates_method_route_page_before_credentials(credentials, route, method, page):
    pipe = Pipe()
    mailbox._request(pipe, str(credentials), binding(), method, route, page, None, 10)
    assert json.loads(pipe.raw)['ok'] is False and pipe.closed


@pytest.mark.parametrize('path', [mailbox.WORKFLOW_PATH,
    mailbox.WORKFLOW_PATH + '@main', mailbox.WORKFLOW_PATH + '@refs/heads/pilot',
    mailbox.WORKFLOW_PATH + '@' + 'c' * 40])
def test_verify_actual_run_and_job(http, path):
    install, calls, _, transport = http
    install(lambda r: httpx.Response(200, json={**run(), 'path': path} if '/runs/' in r.url.path else job()))
    assert transport.verify_job() is True
    assert [r.url.path for r in calls] == ['/repos/owner/talli/actions/runs/123',
        '/repos/owner/talli/actions/jobs/456']


def test_shared_identity_budget_expiring_after_run_prevents_job_request(credentials, monkeypatch):
    now, calls = [100.0], []
    outer = Deadline(1, wall=lambda: now[0], monotonic=lambda: now[0])

    def rpc(target, args, *, deadline, max_bytes):
        assert deadline.outer is outer and deadline.open()
        calls.append(args[3])
        assert args[6] == pytest.approx(1)
        now[0] += 1.01
        return {'data': run(), 'etag': None}

    monkeypatch.setattr(mailbox, 'bounded_rpc', rpc)
    with pytest.raises(SafeTransportFailure) as caught:
        mailbox.GitHubMailbox(binding(), credentials).verify_job(deadline=outer)
    assert safe_failure(caught.value)['category'] == 'hosted_window_deadline_closed'
    assert calls == ['run']


def test_one_caller_budget_covers_publish_pages_identity_and_history(credentials, monkeypatch):
    now, calls = [100.0], []
    outer = Deadline(3, wall=lambda: now[0], monotonic=lambda: now[0])

    def rpc(target, args, *, deadline, max_bytes):
        _, _, method, route, page, _, seconds, *_ = args
        assert deadline.outer is outer and deadline.open()
        assert 0 < deadline.remaining() <= seconds <= 1
        calls.append((method, route, page, seconds))
        if method == 'POST':
            data = None
        elif route == 'run':
            data = run()
        elif route == 'job':
            data = job()
        else:
            data = {'items': [comment(page)], 'nextPage': 2 if page == 1 else None}
        now[0] += .4
        return {'data': data, 'etag': None}

    monkeypatch.setattr(mailbox, 'bounded_rpc', rpc)
    transport = mailbox.GitHubMailbox(binding(), credentials, call_seconds=1)
    transport.publish(envelope(), deadline=outer)
    assert transport.read(deadline=outer) == [envelope(), envelope()]
    assert transport.verify_job(deadline=outer)
    assert transport.history(deadline=outer) == [envelope(), envelope()]
    assert [(m, r, p) for m, r, p, _ in calls] == [('POST', 'comments', 1),
        ('GET', 'comments', 1), ('GET', 'comments', 2), ('GET', 'run', 1),
        ('GET', 'job', 1), ('GET', 'comments', 1), ('GET', 'comments', 2)]
    assert calls[-1][3] == pytest.approx(.6)


@pytest.mark.parametrize('operation', ['publish', 'read', 'history', 'verify_job', '_scan'])
def test_expired_caller_deadline_starts_no_http_child(credentials, monkeypatch, operation):
    now = [100.0]
    outer = Deadline(1, wall=lambda: now[0], monotonic=lambda: now[0])
    now[0] += 2

    def unexpected(*args, **kwargs):
        pytest.fail('expired caller budget must not start a child')

    monkeypatch.setattr(mailbox, 'bounded_rpc', unexpected)
    transport = mailbox.GitHubMailbox(binding(), credentials)
    with pytest.raises(SafeTransportFailure):
        getattr(transport, operation)(*([envelope()] if operation == 'publish' else []), deadline=outer)


def test_long_outer_deadline_retains_individual_call_cap(credentials, monkeypatch):
    now, calls = [100.0], []
    clock_deadline = lambda seconds: Deadline(seconds, wall=lambda: now[0], monotonic=lambda: now[0])
    outer = clock_deadline(30)
    monkeypatch.setattr(mailbox, 'Deadline', clock_deadline)

    def rpc(target, args, *, deadline, max_bytes):
        assert deadline.outer is outer and deadline.remaining() == 1
        calls.append(args[3])
        now[0] += 1.01
        return {'data': run(), 'etag': None}

    monkeypatch.setattr(mailbox, 'bounded_rpc', rpc)
    with pytest.raises(SafeTransportFailure):
        mailbox.GitHubMailbox(binding(), credentials, call_seconds=1).verify_job(deadline=outer)
    assert outer.open() and calls == ['run']


@pytest.mark.parametrize('run_changes, job_changes', [
    ({'repository': {'full_name': 'evil/talli'}}, {}),
    ({'head_sha': 'a' * 40}, {}), ({'id': 124}, {}), ({'run_attempt': 2}, {}),
    ({'status': 'queued'}, {}), ({'status': 'requested'}, {}), ({'event': 'push'}, {}),
    ({'status': 'completed', 'conclusion': 'success'}, {}),
    ({'path': mailbox.WORKFLOW_PATH + '@refs/../evil'}, {}),
    ({'path': mailbox.WORKFLOW_PATH + '@main@other'}, {}),
    ({'path': mailbox.WORKFLOW_PATH + '@refs/heads/.hidden'}, {}),
    ({'path': mailbox.WORKFLOW_PATH + '@refs/heads/pilot.lock'}, {}),
    ({'path': '.github/workflows/talli-recovery-cleanup.yml/other@main'}, {}),
    ({'path': 'other/' + mailbox.WORKFLOW_PATH + '@main'}, {}),
    ({}, {'id': 789}), ({}, {'run_id': 124}), ({}, {'head_sha': 'a' * 40}),
    ({}, {'name': 'Some other job'}), ({}, {'status': 'queued'}),
    ({}, {'status': 'completed', 'conclusion': 'success'}),
])
def test_identity_status_and_workflow_mismatch_never_armed(http, run_changes, job_changes):
    install, _, _, transport = http
    install(lambda r: httpx.Response(200, json={**run(), **run_changes} if '/runs/' in r.url.path
        else {**job(), **job_changes}))
    assert transport.verify_job() is False


def test_numeric_job_resolution_paginated_and_directly_verified(http, credentials):
    install, calls, _, _ = http
    def handler(request):
        if request.url.path.endswith('/jobs'):
            page = int(request.url.params['page'])
            return httpx.Response(200, json={'jobs': [job()] if page == 2 else []}, headers={}
                if page == 2 else {'Link': '<https://api.github.com/repos/owner/talli/actions/runs/123/attempts/1/jobs?'
                    'per_page=100&page=2>; rel="next"'})
        return httpx.Response(200, json=job() if '/actions/jobs/' in request.url.path else run())
    install(handler)
    assert mailbox.resolve_job({k: v for k, v in binding().items() if k != 'jobId'},
        credentials_path=credentials) == 456
    assert calls[-1].url.path.endswith('/actions/jobs/456')
    assert all('/attempts/1/jobs' in r.url.path for r in calls if r.url.params)


@pytest.mark.parametrize('jobs', [[], [job(), job()], [{**job(), 'status': 'queued'}],
    [{**job(), 'id': True}], [{**job(), 'run_id': 999}]])
def test_numeric_job_resolution_rejects_missing_ambiguous_or_wrong_jobs(http, credentials, jobs):
    install, _, _, _ = http
    install(lambda r: httpx.Response(200, json={'jobs': jobs} if r.url.path.endswith('/jobs') else run()))
    with pytest.raises(ValueError, match='hosted_mailbox_job_unverified'):
        mailbox.resolve_job({k: v for k, v in binding().items() if k != 'jobId'}, credentials_path=credentials)


def test_artifact_metadata_bound_to_actual_run_and_digest(http):
    install, calls, _, transport = http
    install(lambda r: httpx.Response(200, json=artifact() if '/artifacts/' in r.url.path else run()))
    assert transport.artifact_metadata(789) == artifact()
    assert calls[-1].url.path == '/repos/owner/talli/actions/artifacts/789'


def test_completed_run_can_authenticate_old_archive_but_cannot_be_armed(http):
    install, _, _, transport = http
    def handler(request):
        value = artifact() if '/artifacts/' in request.url.path else job() if '/actions/jobs/' in request.url.path else {
            **run(), 'status': 'completed', 'conclusion': 'cancelled'}
        return httpx.Response(200, json=value)
    install(handler)
    assert transport.artifact_metadata(789) == artifact()
    assert transport.verify_job() is False


@pytest.mark.parametrize('changes', [
    {'id': 790}, {'name': 'recovery-arm-123-a2'}, {'expired': True},
    {'expires_at': '2000-01-01T00:00:00Z'}, {'expires_at': '2099-01-01T00:00:00'},
    {'digest': 'sha256:invalid'}, {'digest': None}, {'size_in_bytes': mailbox.MAX_RESPONSE + 1},
    {'workflow_run': {'id': 999, 'head_sha': 'c' * 40}},
    {'workflow_run': {'id': 123, 'head_sha': 'a' * 40}},
])
def test_artifact_metadata_rejects_foreign_stale_or_unbounded_archive(http, changes):
    install, _, _, transport = http
    install(lambda r: httpx.Response(200, json={**artifact(), **changes} if '/artifacts/' in r.url.path else run()))
    with pytest.raises(ValueError, match='hosted_mailbox_artifact_unverified'):
        transport.artifact_metadata(789)


def _large_reply(pipe, size):
    pipe.send_bytes(json.dumps({'ok': True, 'value': 'x' * size}).encode())
    pipe.close()


def test_real_shared_process_rpc_supports_bounded_github_frame_above_4k():
    assert len(bounded_rpc(_large_reply, (12000,), deadline=Deadline(5), max_bytes=mailbox.MAX_RESPONSE)) == 12000
    with pytest.raises(ValueError, match='hosted_window_provider_frame_invalid'):
        bounded_rpc(_large_reply, (12000,), deadline=Deadline(5))


def test_template_inactive_manual_only_exact_permissions_and_public_artifacts():
    source = TEMPLATE.read_text()
    assert '/.github/workflows/' not in str(TEMPLATE)
    assert '  workflow_dispatch:' in source
    assert not re.search(r'^  (push|pull_request|schedule|issue_comment|workflow_call):', source, re.M)
    assert 'environment: talli-recovery-cleanup-pilot' in source
    assert 'name: Independent cleanup pilot' in source
    assert 'github.run_attempt == 1' in source
    assert re.findall(r'^      (contents|actions|issues): (\w+)', source, re.M) == [
        ('contents', 'read'), ('actions', 'read'), ('issues', 'write')]
    assert re.findall(r'secrets\.([A-Z_]+)', source) == ['TALLI_RECOVERY_METADATA_TOKEN']
    assert 'persist-credentials: false' in source
    assert not re.search(r'\b(?:HOME|home|CODEX_HOME)=', source)
    assert re.findall(r'^          path: (.+)$', source, re.M) == [
        '${{ env.TALLI_RECOVERY_DIR }}/session/arm.json', '${{ env.TALLI_RECOVERY_DIR }}/session/result.json']
    assert source.index('Publish public arm while') < source.index('Await retained runtime completion')
    assert 'runtime-status.json' in source and 'child.wait(' in source and "'/stat'" in source
    assert 'pendingHistoryKnown' not in source or 'false' in source
    actions = re.findall(r'uses: (actions/[\w-]+)@([a-f0-9]{40})', source)
    assert actions == [('actions/checkout', '3d3c42e5aac5ba805825da76410c181273ba90b1'),
        ('actions/setup-python', '5fda3b95a4ea91299a34e894583c3862153e4b97'),
        ('actions/upload-artifact', '043fb46d1a93c77aae656e7c1c64a875d1fc6a0a'),
        ('actions/upload-artifact', '043fb46d1a93c77aae656e7c1c64a875d1fc6a0a')]


def test_template_embedded_python_compiles_and_never_interpolates_inputs_into_shell():
    source = TEMPLATE.read_text()
    scripts = re.findall(r"python -B - <<'PY'\n(.*?)          PY", source, re.S)
    assert len(scripts) == 5
    for script in scripts:
        assert '${{' not in script
        compile(textwrap.dedent(script), '<inactive-pilot-template>', 'exec')
    for name in ('config_b64', 'authority_b64', 'expected_config_sha256', 'expected_authority_sha256'):
        assert source.count('${{ inputs.' + name + ' }}') == 1
    assert "config['mode'] != 'metadata-only'" in scripts[0]
    assert 'resolve_job(' in scripts[1] and "'--job-id', str(job_id)" in scripts[1]


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='template runs on a Linux runner')
@pytest.mark.parametrize('cancel', [False, True])
def test_template_guardian_retains_reaps_and_forwards_cancellation(http, tmp_path, monkeypatch, cancel):
    install, _, _, _ = http
    install(lambda r: httpx.Response(200, json={'jobs': [job()]} if r.url.path.endswith('/jobs')
        else job() if '/actions/jobs/' in r.url.path else run()))
    scripts = [textwrap.dedent(s) for s in re.findall(
        r"python -B - <<'PY'\n(.*?)          PY", TEMPLATE.read_text(), re.S)]
    root = tmp_path
    (root / 'digests.json').write_text(json.dumps(['a' * 64, 'b' * 64]))
    (root / 'credentials.json').write_text(json.dumps({'githubToken': 'fake-github-token-not-a-real-credential'}))
    (root / 'credentials.json').chmod(0o600)
    monkeypatch.setenv('TALLI_RECOVERY_DIR', str(root))
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    fake_remote = SimpleNamespace(load_inputs=lambda *args: ({}, {}),
        binding_for=lambda *args, **kwargs: binding())
    monkeypatch.setitem(sys.modules, 'talli_backend.adapters.hosted_recovery_remote', fake_remote)
    real_read_text = Path.read_text

    def read_text(path, *args, **kwargs):
        # macOS local qualification only; Linux CI reads real process identity.
        if str(path).startswith('/proc/'):
            return '123 (test guardian) ' + ' '.join(str(i) for i in range(20))
        return real_read_text(path, *args, **kwargs)

    if not Path('/proc/self/stat').exists():
        monkeypatch.setattr(Path, 'read_text', read_text)
    actual_popen = subprocess.Popen
    child_code = '''
import json, signal, sys, time
from pathlib import Path
root = Path(sys.argv[1])
session = root / 'session'
session.mkdir(mode=0o700)
(session / 'arm.json').write_text('{"public":"arm"}')
def stop(signum, frame):
    (session / 'result.json').write_text('{"metadataOnly":true,"cancelled":true}')
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
until = time.monotonic() + 8
while not (root / 'release').exists() and time.monotonic() < until:
    time.sleep(.02)
(session / 'result.json').write_text('{"metadataOnly":true,"cancelled":false}')
'''

    def popen(argv, **kwargs):
        assert '--metadata-only' in argv and argv[-2:] == ['--job-id', '456']
        (root / 'runtime-argv.json').write_text(json.dumps(argv))
        return actual_popen([sys.executable, '-B', '-c', child_code, str(root)], **kwargs)

    monkeypatch.setattr(subprocess, 'Popen', popen)
    namespace = {}
    pid = None
    try:
        exec(compile(scripts[1], '<pilot-start>', 'exec'), namespace)
        pid = json.loads((root / 'owner.json').read_text())['pid']
        assert (root / 'session/arm.json').is_file()
        assert not (root / 'runtime-status.json').exists()
        os.kill(pid, 0)  # Arm artifact would be uploaded at this boundary.
        if cancel:
            exec(compile(scripts[3], '<pilot-stop>', 'exec'), {})
        else:
            (root / 'release').touch()
        until = time.monotonic() + 5
        while not (root / 'runtime-status.json').exists() and time.monotonic() < until:
            time.sleep(.02)
        assert json.loads((root / 'runtime-status.json').read_text()) == {'returncode': 0}
        assert json.loads((root / 'session/result.json').read_text())['cancelled'] is cancel
        waited, status = os.waitpid(pid, 0)
        assert waited == pid and os.waitstatus_to_exitcode(status) == 0
        pid = None
    finally:
        (root / 'release').touch()
        if pid is not None:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)


@pytest.mark.parametrize('mode, changed_digest', [('metadata-only', False), ('cleanup', False),
    ('metadata-only', True)])
def test_template_decoder_enforces_mode_digests_and_private_files(tmp_path, monkeypatch, mode, changed_digest):
    from datetime import datetime, timedelta, timezone
    config = {'mode': mode, 'commit': 'c' * 40, 'repository': 'owner/talli',
        'cleanupAtUtc': (datetime.now(timezone.utc) + timedelta(seconds=240)).isoformat()}
    authority = {'mode': mode}
    raw = json.dumps(config).encode()
    authority_raw = json.dumps(authority).encode()
    output = tmp_path / 'environment'
    output.touch()
    env = {'CONFIG_B64': base64.b64encode(raw).decode(),
        'AUTHORITY_B64': base64.b64encode(authority_raw).decode(),
        'EXPECTED_CONFIG_SHA256': '0' * 64 if changed_digest else sha256(raw).hexdigest(),
        'EXPECTED_AUTHORITY_SHA256': sha256(authority_raw).hexdigest(),
        'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'c' * 40, 'GITHUB_REPOSITORY': 'owner/talli',
        'METADATA_TOKEN': 'fake-provider-metadata-credential', 'MAILBOX_TOKEN': 'fake-github-credential',
        'RUNNER_TEMP': str(tmp_path), 'GITHUB_ENV': str(output)}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setitem(sys.modules, 'talli_backend.adapters.hosted_recovery_remote',
        SimpleNamespace(load_inputs=lambda *args: (config, authority)))
    script = textwrap.dedent(re.findall(r"python -B - <<'PY'\n(.*?)          PY", TEMPLATE.read_text(), re.S)[0])
    previous_umask = os.umask(0o077)
    try:
        if mode == 'cleanup' or changed_digest:
            with pytest.raises(SystemExit, match='hosted_pilot_prepare_failed'):
                exec(compile(script, '<pilot-decode>', 'exec'), {})
            assert output.read_text() == ''
            assert not list(tmp_path.glob('talli-recovery-*'))
        else:
            exec(compile(script, '<pilot-decode>', 'exec'), {})
            root = Path(output.read_text().strip().split('=', 1)[1])
            assert not root.stat().st_mode & 0o077
            assert (root / 'config.json').read_bytes() == raw
            assert json.loads((root / 'credentials.json').read_text()) == {
                'managementToken': 'fake-provider-metadata-credential', 'githubToken': 'fake-github-credential'}
            assert all(not p.stat().st_mode & 0o077 for p in root.iterdir())
    finally:
        os.umask(previous_umask)
