"""Bounded operator diagnostics. Raw exceptions, SQL and transport values never leave memory."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import errno
import re
import time

import httpx
import psycopg


_current = ContextVar('hosted_recovery_trace', default=None)
_SIGNALS = (
    ('tls_certificate_rejected', ('certificate verify failed', 'certificate verification failed')),
    ('tls_connection_closed', ('ssl connection has been closed unexpectedly', 'ssl syscall error')),
    ('connection_closed', ('server closed the connection unexpectedly', 'connection is closed')),
    ('connection_timeout', ('connection timeout expired', 'timeout expired', 'connection timed out')),
    ('connection_refused', ('connection refused',)),
    ('dns_failure', ('could not translate host name', 'name or service not known', 'nodename nor servname')),
    ('credential_rejected', ('password authentication failed', 'password has expired')),
    ('network_unreachable', ('network is unreachable', 'no route to host')),
    ('connection_reset', ('connection reset by peer',)),
    ('broken_pipe', ('broken pipe',)),
)


def _single_failure(error):
    """Categorize driver signals, not a redacted copy of arbitrary error text.

    Patterns are diagnostic hints only: they never authorize retry or prove a
    database rollback. Unknown text deliberately remains unclassified.
    """
    result = {'class': 'Other', 'sqlState': None, 'category': 'unclassified'}
    if isinstance(error, psycopg.Error):
        result['class'] = 'OperationalError' if isinstance(error, psycopg.OperationalError) else 'DatabaseError'
        state = error.sqlstate
        if isinstance(state, str) and re.fullmatch('[0-9A-Z]{5}', state):
            result['sqlState'] = state
        # Inspect a bounded prefix in memory. Do not retain any substring/hash of
        # the message: it can contain SQL values, DSNs or low-entropy passwords.
        message = str(error)[:8192].lower()
        for category, patterns in _SIGNALS:
            if any(pattern in message for pattern in patterns):
                result['category'] = category
                break
    elif isinstance(error, httpx.TimeoutException):
        result.update({'class': 'HttpTimeout', 'category': 'http_timeout'})
    elif isinstance(error, httpx.TransportError):
        result.update({'class': 'HttpTransportError', 'category': 'http_transport_failure'})
    elif isinstance(error, OSError):
        result.update({'class': 'OSError', 'category': {
            errno.ETIMEDOUT: 'connection_timeout', errno.ECONNRESET: 'connection_reset',
            errno.ECONNREFUSED: 'connection_refused', errno.EPIPE: 'broken_pipe',
            errno.ENETUNREACH: 'network_unreachable', errno.EHOSTUNREACH: 'network_unreachable',
        }.get(error.errno, 'os_failure')})
    elif isinstance(error, (KeyboardInterrupt, SystemExit)):
        result.update({'class': 'Interrupted', 'category': 'interrupted'})
    elif isinstance(error, ValueError):
        result['class'] = 'ValueError'
        if str(error) in {'hosted_window_worker_deadline', 'hosted_window_provider_call_deadline',
                'hosted_window_provider_call_outcome_unknown', 'hosted_window_guardian_signal',
                'hosted_window_deadline_closed'}:
            result['category'] = str(error)
    return result


def safe_failure(error):
    result = _single_failure(error)
    causes, seen = [], {id(error)}
    current = error
    for _ in range(3):
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
        if current is None or id(current) in seen:
            break
        seen.add(id(current)); causes.append(_single_failure(current))
    if causes:
        result['causes'] = causes
    return result


class RecoveryTrace:
    def __init__(self, write):
        self.write = write
        self.started = time.monotonic_ns()
        self.body = {'version': 1, 'clock': 'same-process-monotonic-ns', 'events': [],
            'failure': None, 'databaseOutcomeInferred': False}

    def event(self, boundary, status):
        # All callers use code-owned labels, not table, object or actor names.
        if not re.fullmatch('[a-z][a-z.]{0,63}', boundary):
            raise ValueError('hosted_diagnostic_boundary_invalid')
        event = {'boundary': boundary, 'status': status,
            'atUtc': datetime.now(timezone.utc).isoformat(),
            'elapsedMs': max(0, (time.monotonic_ns() - self.started) // 1_000_000)}
        self.body['events'] = (self.body['events'] + [event])[-32:]
        self.write(self.body)
        return event

    @contextmanager
    def step(self, boundary):
        self.event(boundary, 'started')
        try:
            yield
        except BaseException as error:
            event = self.event(boundary, 'failed')
            if self.body['failure'] is None:
                self.body['failure'] = {**safe_failure(error), **event}
                self.write(self.body)
            raise
        else:
            self.event(boundary, 'completed')

    @contextmanager
    def active(self):
        token = _current.set(self)
        try:
            with self.step('restore'):
                yield
        finally:
            _current.reset(token)


@contextmanager
def boundary(label):
    trace = _current.get()
    if trace is None:
        yield
    else:
        with trace.step(label):
            yield


def traced(label):
    def decorate(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            with boundary(label):
                return function(*args, **kwargs)
        return invoke
    return decorate
