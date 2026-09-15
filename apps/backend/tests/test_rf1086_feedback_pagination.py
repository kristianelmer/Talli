"""Complete RF archive snapshots must precede a terminal feedback decision."""
import asyncio
from dataclasses import replace

import pytest
from test_shareholder_register_filing_production import (
    FeedbackJournal, ReadOnlyArchive, RECONCILIATION, MAIN_XML, DOCUMENT,
    page, feedback,
)
from talli_backend.modules.shareholder_register_filing import feedback as module
from talli_backend.modules.shareholder_register_filing.public import (
    Rf1086AuthorityError, Rf1086DocumentReference, reconcile_journaled_rf1086_production,
)


def fixture(last=None):
    children = {str(n): f'<U>synthetic shareholder {n}</U>' for n in range(50)}
    submitted = [MAIN_XML, *children.values()]
    pages = [page(submitted[:50], total_items=52, total_pages=2),
             page([submitted[50], feedback() if last is None else last], total_items=52, total_pages=2, current_page=1)]
    return replace(RECONCILIATION, underskjema_xml=children), pages


def run(input, authority, journal=None):
    journal = FeedbackJournal('processing') if journal is None else journal
    return asyncio.run(reconcile_journaled_rf1086_production(journal, authority, input)), journal


def test_feedback_on_second_page_is_read_before_final_decision():
    input, pages = fixture()
    authority = ReadOnlyArchive(pages)
    result, journal = run(input, authority)
    assert result.state == 'accepted' and result.artifact_count == 1
    assert [args['page'] for kind, args in authority.calls if kind == 'list'] == [0, 1]
    assert all(args['reference_id'] == input.forsendelse_id for _, args in authority.calls)
    assert len(journal.events) == 1 and journal.events[0].state == 'accepted'


def test_conflicting_feedback_on_later_page_prevents_first_page_acceptance():
    input, pages = fixture(feedback(status='avvist'))
    pages[0] = replace(pages[0], documents=(*pages[0].documents[:49], feedback()))
    result, journal = run(input, ReadOnlyArchive(pages))
    assert result.state == 'action_required' and result.safe_error_code == 'RF1086_FEEDBACK_CONFLICT'
    assert len(journal.artifacts) == 2 and all(event.state != 'accepted' for event in journal.events)


@pytest.mark.parametrize('change', [
    {'current_page': 0}, {'total_items': 53}, {'total_pages': 3},
    {'documents': ()}, {'document_shape_valid': False},
])
def test_inconsistent_second_page_stops_before_any_artifact_write(change):
    input, pages = fixture()
    pages[0] = replace(pages[0], documents=(*pages[0].documents[:49], feedback()))
    pages[1] = replace(pages[1], **change)
    result, journal = run(input, ReadOnlyArchive(pages))
    assert result.state == 'action_required' and result.safe_error_code == 'RF1086_ARCHIVE_SHAPE_INVALID'
    assert journal.artifacts == {} and all(event.state != 'accepted' for event in journal.events)


def test_repeated_document_across_pages_cannot_hide_an_unread_document():
    input, pages = fixture()
    pages[1] = replace(pages[1], documents=(MAIN_XML, feedback()))
    result, journal = run(input, ReadOnlyArchive(pages))
    assert result.state == 'action_required' and journal.artifacts == {}


def test_later_page_network_failure_never_uses_earlier_success_feedback():
    input, pages = fixture()
    pages[0] = replace(pages[0], documents=(*pages[0].documents[:49], feedback()))
    pages[1] = Rf1086AuthorityError('RF1086_NETWORK_ERROR', retryable=True)
    result, journal = run(input, ReadOnlyArchive(pages))
    assert result.state == 'unknown' and journal.artifacts == {}


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, True, 1.5])
def test_invalid_extent_stops_after_one_read(value):
    input, pages = fixture()
    authority = ReadOnlyArchive([replace(pages[0], total_pages=value)])
    result, journal = run(input, authority)
    assert result.state == 'action_required' and len(authority.calls) == 1 and journal.artifacts == {}


def test_empty_single_page_remains_processing():
    result, _ = run(RECONCILIATION, ReadOnlyArchive([page(total_pages=1)]))
    assert result.state == 'processing'


def test_declared_scan_above_capacity_stops_before_more_provider_reads():
    input, pages = fixture()
    authority = ReadOnlyArchive([replace(pages[0], total_items=5050, total_pages=101)])
    result, journal = run(input, authority)
    assert result.safe_error_code == 'RF1086_ARCHIVE_SCAN_LIMIT' and result.state == 'action_required'
    assert len(authority.calls) == 1 and journal.artifacts == {}


def test_inline_byte_budget_stops_before_fetching_next_page(monkeypatch):
    input, pages = fixture()
    monkeypatch.setattr(module, 'RF1086_MAX_ARCHIVE_SCAN_BYTES', 100)
    authority = ReadOnlyArchive(pages)
    result, journal = run(input, authority)
    assert result.safe_error_code == 'RF1086_ARCHIVE_SCAN_LIMIT'
    assert len(authority.calls) == 1 and journal.artifacts == {}


def test_slow_archive_scan_stops_without_terminal_success(monkeypatch):
    class Slow(ReadOnlyArchive):
        async def list_documents(self, **arguments):
            await asyncio.sleep(1)
            raise AssertionError('deadline did not cancel the read')
    monkeypatch.setattr(module, 'RF1086_ARCHIVE_SCAN_TIMEOUT_SECONDS', 0.001)
    result, journal = run(RECONCILIATION, Slow())
    assert result.state == 'unknown' and result.safe_error_code == 'RF1086_ARCHIVE_SCAN_TIMEOUT'
    assert journal.artifacts == {} and journal.events[0].state == 'unknown'


def test_referenced_document_budget_stops_before_persistence(monkeypatch):
    from talli_backend.modules.shareholder_register_filing.public import Rf1086AuthorityDocument
    monkeypatch.setattr(module, 'RF1086_MAX_ARCHIVE_SCAN_BYTES', 100)
    authority = ReadOnlyArchive([page([Rf1086DocumentReference(DOCUMENT)])], {
        DOCUMENT: Rf1086AuthorityDocument(DOCUMENT, 'application/xml', feedback().encode())})
    result, journal = run(RECONCILIATION, authority)
    assert result.safe_error_code == 'RF1086_ARCHIVE_SCAN_LIMIT' and result.state == 'action_required'
    assert [kind for kind, _ in authority.calls] == ['list', 'get'] and journal.artifacts == {}
