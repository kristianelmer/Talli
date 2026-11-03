"""Bounded GitHub issue-comment transport; no application/runtime registration.

Comments are editable/deletable transport, never a complete durable journal.
Envelope signatures and admission belong to the arming protocol, not GitHub.
Only tests replace ``_request``/``bounded_rpc``; there is no endpoint override.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import re
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

import httpx

from talli_backend.adapters.hosted_recovery_capture import json_bytes, private_read, require
from talli_backend.adapters.hosted_recovery_diagnostics import SafeTransportFailure, safe_failure
from talli_backend.adapters.hosted_recovery_window import Deadline, bounded_rpc


ORIGIN = 'https://api.github.com'
PREFIX = 'TALLI_RECOVERY_PROTOCOL_V1\n'
WORKFLOW_PATH = '.github/workflows/talli-recovery-cleanup.yml'
JOB_NAME = 'Independent cleanup pilot'
MAX_RESPONSE = 2 * 1024**2
MAX_BODY = 16 * 1024
MAX_PAGES = 32
PAGE_SIZE = 100
MAX_MESSAGES = MAX_PAGES * PAGE_SIZE
_FIELDS = {'version', 'windowId', 'authoritySha256', 'configSha256', 'commit',
    'repository', 'workflowPath', 'runId', 'runAttempt', 'jobId', 'issueNumber',
    'cleanupAtUtc', 'armBeforeUtc', 'coordinatorPublicKey', 'mode'}


class MailboxRateLimited(SafeTransportFailure):
    """No automatic retry. Caller may stop/back off using this bounded delay."""
    def __init__(self, status, retry_after_seconds):
        super().__init__({'class': 'HttpStatusError', 'sqlState': None,
            'category': 'http_status_error', 'httpStatus': status})
        self.retry_after_seconds = retry_after_seconds


def _etag(value):
    require(value is None or isinstance(value, str) and 0 < len(value) <= 512 and
        all(32 <= ord(c) <= 126 for c in value), 'hosted_mailbox_etag_invalid')
    return value


def _positive(value):
    return type(value) is int and 0 < value < 2**63


def _binding(value, *, without_job=False):
    """Validate all routing inputs before credentials or a network child are used."""
    require(isinstance(value, dict) and set(value) == _FIELDS - ({'jobId'} if without_job else set()),
        'hosted_mailbox_binding_invalid')
    require(type(value['version']) is int and value['version'] == 1 and
        type(value['runAttempt']) is int and value['runAttempt'] == 1,
        'hosted_mailbox_binding_invalid')
    for field in ('runId', 'issueNumber', *(() if without_job else ('jobId',))):
        require(_positive(value[field]), 'hosted_mailbox_binding_invalid')
    repo = value['repository']
    require(isinstance(repo, str) and re.fullmatch(
        r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}', repo)
        and repo.split('/')[1] not in {'.', '..'}, 'hosted_mailbox_binding_invalid')
    require(value['workflowPath'] == WORKFLOW_PATH and
        value['mode'] in ('metadata-only', 'cleanup'), 'hosted_mailbox_binding_invalid')
    for field, length in (('authoritySha256', 64), ('configSha256', 64),
            ('coordinatorPublicKey', 64), ('commit', 40)):
        require(isinstance(value[field], str) and re.fullmatch('[0-9a-f]{%d}' % length, value[field]),
            'hosted_mailbox_binding_invalid')
    try:
        window = UUID(value['windowId'])
        require(str(window) == value['windowId'] and window.int != 0 and
            value['coordinatorPublicKey'] != '0' * 64, 'hosted_mailbox_binding_invalid')
        require(all(isinstance(value[field], str) and 'T' in value[field]
            for field in ('armBeforeUtc', 'cleanupAtUtc')), 'hosted_mailbox_binding_invalid')
        times = [datetime.fromisoformat(value[field]) for field in ('armBeforeUtc', 'cleanupAtUtc')]
        require(all(t.utcoffset() == timedelta(0) for t in times) and times[0] < times[1],
            'hosted_mailbox_binding_invalid')
    except (ValueError, TypeError, AttributeError):
        raise ValueError('hosted_mailbox_binding_invalid') from None
    return deepcopy(value)


def _seconds(value):
    require(type(value) in (float, int) and math.isfinite(value) and 0 < value <= 60,
        'hosted_mailbox_timeout_invalid')
    return float(value)


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise ValueError('hosted_mailbox_message_invalid') from None


def _path(binding, route, artifact_id=None):
    base = '/repos/' + binding['repository']
    paths = {'comments': base + '/issues/%d/comments' % binding['issueNumber'],
        'run': base + '/actions/runs/%d' % binding['runId'],
        'jobs': base + '/actions/runs/%d/attempts/1/jobs' % binding['runId']}
    if 'jobId' in binding:
        paths['job'] = base + '/actions/jobs/%d' % binding['jobId']
    if route == 'artifact':
        require(_positive(artifact_id), 'hosted_mailbox_artifact_invalid')
        paths['artifact'] = base + '/actions/artifacts/%d' % artifact_id
    else:
        require(artifact_id is None, 'hosted_mailbox_route_invalid')
    require(route in paths, 'hosted_mailbox_route_invalid')
    return paths[route]


def _next_page(response, path, page):
    """Never follow server-supplied URLs; validate then rebuild the next route."""
    require(len(response.headers.get('link', '')) <= 8192, 'hosted_mailbox_pagination_invalid')
    link = response.links.get('next')
    if link is None:
        return None
    try:
        url = urlsplit(link['url'])
        query = parse_qsl(url.query, strict_parsing=True)
        require(url.scheme == 'https' and url.netloc == 'api.github.com' and url.path == path
            and not url.fragment and len(query) == 2 and dict(query) == {
                'per_page': '100', 'page': str(page + 1)}, 'hosted_mailbox_pagination_invalid')
        require(page < MAX_PAGES, 'hosted_mailbox_history_bound')
    except (ValueError, KeyError, TypeError):
        raise ValueError('hosted_mailbox_pagination_invalid') from None
    return page + 1


def _job(value):
    require(isinstance(value, dict), 'hosted_mailbox_response_invalid')
    return {k: value.get(k) for k in ('id', 'run_id', 'head_sha', 'name', 'status', 'conclusion')}


def _request(pipe, credentials, binding, method, route, page, body, seconds, artifact_id=None, etag=None):
    """Disposable HTTPS child. Only bounded public metadata crosses the pipe."""
    try:
        binding = _binding(binding, without_job='jobId' not in binding)
        seconds = _seconds(seconds)
        _etag(etag)
        require(etag is None or method == 'GET', 'hosted_mailbox_etag_invalid')
        require(method == 'GET' or (method == 'POST' and route == 'comments'),
            'hosted_mailbox_method_invalid')
        path = _path(binding, route, artifact_id)
        paged = route in ('comments', 'jobs') and method == 'GET'
        require(type(page) is int and 1 <= page <= MAX_PAGES and (paged or page == 1),
            'hosted_mailbox_pagination_invalid')
        require((method == 'GET' and body is None) or (method == 'POST' and
            isinstance(body, str) and body.startswith(PREFIX) and len(body.encode()) <= MAX_BODY),
            'hosted_mailbox_message_invalid')
        values = json_bytes(private_read(credentials, 32768))
        token = values.get('githubToken')
        require(isinstance(token, str) and 20 <= len(token) <= 4096 and
            token.isascii() and all(33 <= ord(c) <= 126 for c in token),
            'hosted_mailbox_credentials_invalid')
        url = ORIGIN + path
        if paged:
            url += '?per_page=100&page=%d' % page
        with httpx.Client(timeout=httpx.Timeout(seconds), follow_redirects=False, trust_env=False) as client:
            with client.stream(method, url, headers={'Authorization': 'Bearer ' + token,
                    'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2026-03-10',
                    **({'If-None-Match': etag} if etag is not None else {})},
                    **({'json': {'body': body}} if method == 'POST' else {})) as response:
                if response.status_code == 304:
                    require(method == 'GET' and etag is not None, 'hosted_mailbox_cache_invalid')
                    result = {'notModified': True}
                    if paged and 'link' in response.headers:
                        result['nextPage'] = _next_page(response, path, page)
                    pipe.send_bytes(_canonical({'ok': True, 'value': result}))
                    return
                if response.status_code == 429 or (response.status_code == 403 and
                        ('retry-after' in response.headers or response.headers.get('x-ratelimit-remaining') == '0')):
                    delay = response.headers.get('retry-after', '')
                    seconds = min(3600, max(1, int(delay))) if re.fullmatch('[0-9]{1,6}', delay) else 60
                    pipe.send_bytes(_canonical({'ok': True, 'value': {'rateLimited': True,
                        'httpStatus': response.status_code, 'retryAfterSeconds': seconds}}))
                    return
                response.raise_for_status()
                require(response.status_code == (201 if method == 'POST' else 200),
                    'hosted_mailbox_http_unexpected')
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=16384):
                    require(len(raw) + len(chunk) <= MAX_RESPONSE, 'hosted_mailbox_response_bound')
                    raw.extend(chunk)
                value = json_bytes(bytes(raw))
                if method == 'POST':
                    require(isinstance(value, dict) and _positive(value.get('id')) and
                        value.get('body') == body, 'hosted_mailbox_publish_unverified')
                    result = None
                elif route == 'comments':
                    require(isinstance(value, list) and len(value) <= PAGE_SIZE,
                        'hosted_mailbox_response_invalid')
                    items = []
                    for item in value:
                        require(isinstance(item, dict) and _positive(item.get('id')) and
                            isinstance(item.get('body'), str), 'hosted_mailbox_response_invalid')
                        text = item['body']
                        if text.startswith(PREFIX):
                            require(len(text.encode()) <= MAX_BODY, 'hosted_mailbox_message_bound')
                            items.append({'id': item['id'], 'body': text})
                        else:
                            items.append({'id': item['id'], 'body': None})
                    result = {'items': items, 'nextPage': _next_page(response, path, page)}
                elif route == 'jobs':
                    require(isinstance(value, dict) and isinstance(value.get('jobs'), list) and
                        len(value['jobs']) <= PAGE_SIZE, 'hosted_mailbox_response_invalid')
                    result = {'items': [_job(v) for v in value['jobs']],
                        'nextPage': _next_page(response, path, page)}
                elif route == 'job':
                    result = _job(value)
                elif route == 'artifact':
                    require(isinstance(value, dict) and isinstance(value.get('workflow_run'), dict),
                        'hosted_mailbox_response_invalid')
                    result = {k: value.get(k) for k in ('id', 'name', 'digest', 'expired',
                        'expires_at', 'size_in_bytes')}
                    result['workflow_run'] = {k: value['workflow_run'].get(k) for k in ('id', 'head_sha')}
                else:
                    require(isinstance(value, dict) and isinstance(value.get('repository'), dict),
                        'hosted_mailbox_response_invalid')
                    result = {k: value.get(k) for k in ('id', 'path', 'head_sha', 'run_attempt',
                        'status', 'conclusion', 'event')}
                    result['repository'] = {'full_name': value['repository'].get('full_name')}
                etag = _etag(response.headers.get('etag')) if method == 'GET' else None
        frame = _canonical({'ok': True, 'value': {'data': result, 'etag': etag}})
        require(len(frame) <= MAX_RESPONSE, 'hosted_mailbox_response_bound')
        pipe.send_bytes(frame)
    except BaseException as error:
        try:
            pipe.send_bytes(_canonical({'ok': False, 'failure': safe_failure(error)}))
        except BaseException:
            pass  # A lost parent receives no result, never a raw child traceback.
    finally:
        try:
            pipe.close()
        except BaseException:
            pass


def _run_matches(run, binding, *, running=True):
    path = run.get('path')
    # The documented run path can carry @ref. Only the exact path followed by
    # one syntactically valid Git ref is accepted; head_sha is checked separately.
    if isinstance(path, str) and path.startswith(WORKFLOW_PATH + '@'):
        ref = path[len(WORKFLOW_PATH) + 1:]
        if (not ref or len(ref) > 255 or ref.startswith(('/', '.')) or ref.endswith(('/', '.'))
                or any(c in ref for c in ('..', '//', '@', '\\', '~', '^', ':', '?', '*', '[', ' '))
                or any(ord(c) < 33 or ord(c) > 126 for c in ref)
                or any(p.startswith('.') or p.endswith('.lock') for p in ref.split('/'))):
            return False
        path = WORKFLOW_PATH
    return (type(run.get('id')) is int and run['id'] == binding['runId'] and
        run.get('repository') == {'full_name': binding['repository']} and path == WORKFLOW_PATH and
        run.get('head_sha') == binding['commit'] and type(run.get('run_attempt')) is int and
        run['run_attempt'] == 1 and (run.get('status') == 'in_progress' and
            run.get('conclusion') is None or not running and run.get('status') == 'completed') and
        run.get('event') == 'workflow_dispatch')


def _job_matches(job, binding):
    return (type(job.get('id')) is int and job['id'] == binding['jobId'] and
        type(job.get('run_id')) is int and job['run_id'] == binding['runId'] and
        job.get('head_sha') == binding['commit'] and job.get('name') == JOB_NAME and
        job.get('status') == 'in_progress' and job.get('conclusion') is None)


def _call(binding, credentials, seconds, method, route, *, page=1, body=None,
        deadline=None, artifact_id=None, cache=None):
    try:
        outer = deadline if deadline is not None else Deadline(seconds)
        require(outer.open(), 'hosted_window_deadline_closed')
        seconds = min(seconds, outer.remaining())
        require(seconds > 0, 'hosted_window_deadline_closed')
        request_deadline = _RequestDeadline(outer, seconds)
        key = (_canonical(binding), route, page, artifact_id)
        cached = cache.get(key) if method == 'GET' and cache is not None else None
        conditional = cached
        if (cached is not None and route in ('comments', 'jobs') and
                len(cached[1]['items']) == PAGE_SIZE and cached[1]['nextPage'] is None):
            # The body of a full terminal page can remain identical when a new
            # page appears. Refresh its Link headers with an unconditional GET.
            conditional = None
        value = bounded_rpc(_request, (str(credentials), binding, method, route,
            page, body, seconds, artifact_id, conditional[0] if conditional is not None else None),
            deadline=request_deadline,
            max_bytes=MAX_RESPONSE)
        require(request_deadline.open(), 'hosted_window_deadline_closed')
        if value.get('rateLimited') is True:
            raise MailboxRateLimited(value['httpStatus'], value['retryAfterSeconds'])
        if value.get('notModified') is True:
            require(conditional is not None, 'hosted_mailbox_cache_invalid')
            data = deepcopy(cached[1])
            if 'nextPage' in value:
                data['nextPage'] = value['nextPage']
                cache[key] = (cached[0], deepcopy(data))
            return data
        data, etag = value['data'], value['etag']
        if cached is not None and cached[0] == etag:
            previous, current = cached[1], data
            if route in ('comments', 'jobs'):
                previous, current = previous['items'], current['items']
            require(_canonical(previous) == _canonical(current), 'hosted_mailbox_cache_changed')
        if method == 'GET' and cache is not None:
            if etag is None:
                cache.pop(key, None)
            else:
                cache[key] = (etag, deepcopy(data))
        return data
    except MailboxRateLimited:
        raise
    except Exception as error:
        raise SafeTransportFailure(safe_failure(error)) from None


class _RequestDeadline:
    """Keep the caller's absolute/clock budget and the individual call cap."""
    def __init__(self, outer, seconds):
        self.outer = outer
        self.limit = Deadline(seconds)

    def open(self):
        return self.outer.open() and self.limit.open()

    def remaining(self):
        return min(self.outer.remaining(), self.limit.remaining())


class GitHubMailbox:
    """Full bounded rescans avoid page-offset/updated-time cursor omissions.

    ``read`` advances an in-memory ID/body cursor only after a complete scan.
    ``history`` does not advance it. Neither proves an undeleted complete tail;
    recovery from this transport alone must set pendingHistoryKnown=false.
    A lost POST is never retried here; the protocol must reconcile its nonce.
    Optional caller deadlines cover the entire operation, including every page
    and both identity reads; individual requests also retain call_seconds caps.
    """
    def __init__(self, binding, credentials_path, call_seconds=10):
        self.binding = _binding(binding)
        self.credentials_path = str(credentials_path)
        self.call_seconds = _seconds(call_seconds)
        self._seen = {}
        self._cache = {}

    def _call(self, method, route, **kwargs):
        return _call(self.binding, self.credentials_path, self.call_seconds, method, route,
            cache=self._cache, **kwargs)

    def publish(self, envelope, *, deadline=None):
        require(isinstance(envelope, dict) and envelope.get('binding') == self.binding,
            'hosted_mailbox_message_invalid')
        body = PREFIX + _canonical(envelope).decode()
        require(len(body.encode()) <= MAX_BODY, 'hosted_mailbox_message_bound')
        self._call('POST', 'comments', body=body, deadline=deadline)

    def _scan(self, *, deadline=None):
        deadline = deadline if deadline is not None else Deadline(self.call_seconds)
        messages, last_id = {}, 0
        for page in range(1, MAX_PAGES + 1):
            result = self._call('GET', 'comments', page=page, deadline=deadline)
            for item in result['items']:
                require(_positive(item['id']) and item['id'] > last_id,
                    'hosted_mailbox_cursor_invalid')
                last_id = item['id']
                require(item['id'] not in self._seen or self._seen[item['id']] == item['body'],
                    'hosted_mailbox_comment_changed')
                if item['body'] is None:
                    continue
                body = item['body']
                try:
                    raw = body[len(PREFIX):].encode()
                    value = json_bytes(raw)
                    require(isinstance(value, dict) and _canonical(value) == raw,
                        'hosted_mailbox_message_invalid')
                except (ValueError, TypeError, RecursionError, UnicodeError):
                    raise ValueError('hosted_mailbox_message_invalid') from None
                # Other windows on the same issue are unrelated to this mailbox.
                if value.get('binding') != self.binding:
                    continue
                messages[item['id']] = (body, value)
            if result['nextPage'] is None:
                require(self._seen.keys() <= messages.keys(), 'hosted_mailbox_comment_missing')
                return messages
            require(result['nextPage'] == page + 1, 'hosted_mailbox_cursor_invalid')
        raise ValueError('hosted_mailbox_history_bound')

    def read(self, *, deadline=None):
        messages = self._scan(deadline=deadline)
        result = [value for key, (_, value) in messages.items() if key not in self._seen]
        require(len(self._seen.keys() | messages.keys()) <= MAX_MESSAGES, 'hosted_mailbox_history_bound')
        self._seen.update({key: body for key, (body, _) in messages.items()})
        return result

    def history(self, *, deadline=None):
        return [value for _, value in self._scan(deadline=deadline).values()]

    def verify_job(self, *, deadline=None):
        deadline = deadline if deadline is not None else Deadline(self.call_seconds)
        run = self._call('GET', 'run', deadline=deadline)
        job = self._call('GET', 'job', deadline=deadline)
        return _run_matches(run, self.binding) and _job_matches(job, self.binding)

    def artifact_metadata(self, artifact_id):
        """Public bootstrap metadata, never download/follow archive redirects."""
        require(_positive(artifact_id), 'hosted_mailbox_artifact_invalid')
        deadline = Deadline(self.call_seconds)
        # Closed jobs can still authenticate old arm archives for cleanup-only
        # recovery. This never makes verify_job() admit a closed/queued job.
        require(_run_matches(self._call('GET', 'run', deadline=deadline), self.binding, running=False),
            'hosted_mailbox_run_unverified')
        value = self._call('GET', 'artifact', artifact_id=artifact_id, deadline=deadline)
        try:
            expires = datetime.fromisoformat(value['expires_at'])
            require(expires.utcoffset() == timedelta(0) and expires > datetime.now(timezone.utc),
                'hosted_mailbox_artifact_unverified')
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ValueError('hosted_mailbox_artifact_unverified') from None
        require(type(value.get('id')) is int and value['id'] == artifact_id and
            value.get('name') == 'recovery-arm-%d-a1' % self.binding['runId'] and
            value.get('expired') is False and _positive(value.get('size_in_bytes')) and
            value['size_in_bytes'] <= MAX_RESPONSE and isinstance(value.get('digest'), str) and
            re.fullmatch('sha256:[0-9a-f]{64}', value['digest']) and
            isinstance(value.get('workflow_run'), dict) and
            type(value['workflow_run'].get('id')) is int and
            value['workflow_run'] == {'id': self.binding['runId'], 'head_sha': self.binding['commit']},
            'hosted_mailbox_artifact_unverified')
        return value


def resolve_job(binding_without_job, jobname=JOB_NAME, *, credentials_path, call_seconds=10):
    """Bootstrap before the actual job ID can enter the signed binding."""
    binding = _binding(binding_without_job, without_job=True)
    seconds = _seconds(call_seconds)
    require(jobname == JOB_NAME, 'hosted_mailbox_job_unverified')
    deadline, matches = Deadline(seconds), []
    run = _call(binding, credentials_path, seconds, 'GET', 'run', deadline=deadline)
    require(_run_matches(run, binding), 'hosted_mailbox_run_unverified')
    for page in range(1, MAX_PAGES + 1):
        result = _call(binding, credentials_path, seconds, 'GET', 'jobs', page=page, deadline=deadline)
        matches.extend(j for j in result['items'] if j.get('name') == jobname)
        if result['nextPage'] is None:
            break
        require(page < MAX_PAGES and result['nextPage'] == page + 1, 'hosted_mailbox_history_bound')
    require(len(matches) == 1 and _positive(matches[0].get('id')), 'hosted_mailbox_job_unverified')
    resolved = {**binding, 'jobId': matches[0]['id']}
    require(_job_matches(matches[0], resolved), 'hosted_mailbox_job_unverified')
    job = _call(resolved, credentials_path, seconds, 'GET', 'job', deadline=deadline)
    require(_job_matches(job, resolved), 'hosted_mailbox_job_unverified')
    return resolved['jobId']
