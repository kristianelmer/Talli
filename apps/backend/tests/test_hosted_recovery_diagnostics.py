"""Real operator failure boundary: retain a concrete signal, never error text."""
import json
import errno
import socket
import threading

import psycopg
import pytest

from test_hosted_backup_recovery import operator, snapshot  # noqa: F401
from talli_backend.adapters.hosted_recovery_diagnostics import RecoveryTrace, boundary, safe_failure


def test_database_disconnect_preserves_safe_cause_and_last_boundary(snapshot, tmp_path, monkeypatch):
    instance, _ = operator(snapshot, tmp_path, monkeypatch)

    def disconnected(*args):
        raise psycopg.OperationalError(
            'SSL connection has been closed unexpectedly; password=DO_NOT_RETAIN row=PRIVATE_ROW')

    monkeypatch.setattr(instance, '_restore_database', disconnected)
    with pytest.raises(psycopg.OperationalError):
        instance.restore(expected_plan_sha256=instance.plan_sha)
    state = instance._state()
    assert state['phase'] == 'inspection_or_containment_required'
    assert state['lastFailure']['category'] == 'tls_connection_closed'
    trace = json.loads((instance.work / 'diagnostics.json').read_text())
    assert trace['failure']['category'] == 'tls_connection_closed'
    assert trace['failure']['boundary'] == 'restore.database'
    assert trace['failure']['atUtc'].endswith('+00:00')
    assert trace['failure']['elapsedMs'] >= 0
    wire = json.dumps(state) + json.dumps(trace)
    assert 'DO_NOT_RETAIN' not in wire and 'PRIVATE_ROW' not in wire
    assert 'SSL connection has been' not in wire


@pytest.mark.parametrize('error', [RuntimeError('password PRIVATE_ROW'),
    ValueError('hosted_password_secret'), psycopg.OperationalError('unrecognized PRIVATE_ROW'),
    type('PRIVATE_ROW', (Exception,), {})('password')])
def test_unknown_messages_and_dynamic_exception_names_never_escape(error):
    wire = json.dumps(safe_failure(error))
    assert 'PRIVATE_ROW' not in wire and 'password' not in wire and 'secret' not in wire


def test_bounded_cause_chain_keeps_reset_signal_without_text_or_cycles():
    outer = psycopg.OperationalError('PRIVATE_ROW')
    reset = ConnectionResetError(errno.ECONNRESET, 'PRIVATE_SECRET')
    outer.__cause__ = reset; reset.__cause__ = outer
    value = safe_failure(outer)
    assert value['causes'] == [{'class': 'OSError', 'sqlState': None, 'category': 'connection_reset'}]
    assert 'PRIVATE_' not in json.dumps(value)


def test_actual_libpq_peer_disconnect_is_classified_without_row_or_credential_text():
    server = socket.socket(); server.bind(('127.0.0.1', 0)); server.listen()
    port = server.getsockname()[1]
    def peer():
        connection, _ = server.accept()
        with connection:
            connection.recv(8192)  # Startup only: no PostgreSQL/SQL server.
        server.close()
    thread = threading.Thread(target=peer); thread.start()
    records = []; trace = RecoveryTrace(lambda value: records.append(json.loads(json.dumps(value))))
    try:
        with pytest.raises(psycopg.OperationalError):
            with trace.active(), boundary('database.connect'):
                psycopg.connect(host='127.0.0.1', port=port, dbname='postgres',
                    user='synthetic', password='PRIVATE_SECRET', sslmode='disable', connect_timeout=1)
    finally:
        thread.join(timeout=2); server.close()
    assert records[-1]['failure']['category'] == 'connection_closed'
    assert records[-1]['failure']['boundary'] == 'database.connect'
    assert 'PRIVATE_SECRET' not in json.dumps(records)


@pytest.mark.parametrize('code',['hosted_remote_ack_unavailable','hosted_arming_pending',
    'hosted_arming_preflight'])
def test_fixed_admission_codes_survive_safe_transport_envelope(code):
    from talli_backend.adapters.hosted_recovery_diagnostics import SafeTransportFailure
    value=safe_failure(ValueError(code))
    assert value['category']==code
    assert safe_failure(SafeTransportFailure(value))==value


def test_admission_code_prefix_never_copies_arbitrary_error_text():
    secret='fixture-private-value'
    for message in ['hosted_remote_ack_unavailable:'+secret,'hosted_arming_unknown_'+secret]:
        value=safe_failure(ValueError(message))
        assert value['category']=='unclassified' and secret not in json.dumps(value)
