"""Installed writer/inventory/package parity; synthetic claims, no live Auth proof."""
from io import BytesIO

import pytest

from talli_backend.application import shareholder_register_company_test_retention_bundle as bundle
from talli_backend.application import shareholder_register_company_test_retention_stream as stream
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_company_test_retention_database import (
    retained, admitted, backend_url, rf_fixture_admin_access, read, write, oracle,
)

pytestmark = pytest.mark.authority_database


def test_actual_complete_zero_bundle_preserves_verified_empty_inventory(retained):
    source = read(retained)
    assert source.record_count == 0
    parsed = bundle.verify_company_test_retention_bundle(BytesIO(bundle.pack_company_test_retention(source)),
        company_id=source.company_id)
    rf.assert_company_test_retention_source_capture_matches(parsed, source)
    assert parsed.records == oracle(retained) == ()


@pytest.mark.parametrize('status', ['accepted', 'rejected', 'blocked', 'pending'])
def test_actual_writer_originals_have_identical_bundle_and_completed_stream_capture(retained, status):
    write(retained, status=status, test_reference='Owned ø '+status,
        feedback_summary='Original\nfeedback', payload_hash='OPAQUE:stored/hash', receipt_reference=None)
    source = read(retained)
    assert source.records == oracle(retained)
    raw = bundle.pack_company_test_retention(source)
    parsed = bundle.verify_company_test_retention_bundle(BytesIO(raw), company_id=source.company_id)
    rf.assert_company_test_retention_source_capture_matches(parsed, source)
    completed = stream.verify_company_test_retention_stream(
        BytesIO(b''.join(stream.stream_company_test_retention(source))), company_id=source.company_id)
    assert bundle.pack_company_test_retention(completed) == raw
    assert read(retained).records == source.records


def test_actual_append_after_saved_capture_is_not_hidden_by_self_consistent_package(retained):
    write(retained)
    source = read(retained)
    raw = bundle.pack_company_test_retention(source)
    write(retained, status='rejected')
    current = read(retained)
    parsed = bundle.verify_company_test_retention_bundle(BytesIO(raw), company_id=source.company_id)
    rf.assert_company_test_retention_source_capture_matches(parsed, source)
    assert current.records == oracle(retained) and current.record_count == 2
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.assert_company_test_retention_target_inventory_matches(parsed, current)
    assert bundle.pack_company_test_retention(source) == raw
