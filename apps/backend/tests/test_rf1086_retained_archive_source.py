"""Complete retained query contracts; synthetic member access, no SQL proof."""
import asyncio
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
import json
from uuid import UUID

import pytest

from talli_backend.application.shareholder_register_filing_workflow import ShareholderRegisterFilingWorkflow
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.modules.shareholder_register_filing.preparation import Rf1086PreparationService
from talli_backend.shared.kernel import ActorId, ActorKind, UserId
from test_rf1086_archive_history import history_archive
from test_rf1086_archive_history_v6 import mixed_archive
from test_rf1086_archive_source import snapshot
from test_rf1086_archive_storage_v6 import approved_v6, forbid_fresh, query
from test_rf1086_retained_source_dispatch import retained_submission
from test_rf1086_year_source import ACTOR


def bomb(*args, **kwargs):
    raise AssertionError('Complete retained query must not call this port')


class Store:
    def __init__(self, result, *, actor=ACTOR, failure=None):
        self.result, self.actor_id, self.failure = result, actor, failure
        self.queries = []

    async def archive_source(self, requested):
        self.queries.append(requested)
        if self.failure is not None:
            raise self.failure
        return self.result

    workspace = source_snapshot = legacy_archive_source = bomb


def read(store, requested, *, outward=False):
    service = (ShareholderRegisterFilingWorkflow(store) if outward
        else Rf1086PreparationService(store, clock=bomb))
    return asyncio.run(service.retained_archive_source(requested))


def forbid_export(monkeypatch):
    from talli_backend.modules.shareholder_register_filing import archive_storage, archive_storage_v6
    for name in ('serialize_rf1086_archive', 'parse_rf1086_archive',
                 'serialize_rf1086_archive_v6', 'parse_rf1086_retained_archive'):
        monkeypatch.setattr(rf, name, bomb)
    for module in (archive_storage, archive_storage_v6):
        monkeypatch.setattr(module, 'serialize', bomb)
        monkeypatch.setattr(module, 'parse', bomb)


@pytest.mark.parametrize('kind', ['cash_issue', 'loss_covering_reduction'])
@pytest.mark.parametrize('amendments', [0, 1, 2])
@pytest.mark.parametrize('state', ['approved', 'accepted'])
def test_complete_capital_history_returns_exact_snapshot_without_fresh_or_export_ports(
        kind, amendments, state, monkeypatch):
    archive = retained_submission(kind, amendments, state)
    source = archive.source_history.year_sources[-1]
    assert len(archive.source_history.year_sources) == 2
    assert source.governance_projection.chain_count == 1
    assert source.governance_projection.chains[0].amendment_count == amendments
    assert len(archive.source_history.register_observations) == amendments + 1
    assert len(archive.withdrawal_capture_records) == amendments
    requested = query(archive)
    store = Store(archive)
    forbid_fresh(monkeypatch)
    forbid_export(monkeypatch)
    assert read(store, requested, outward=True) is archive
    assert store.queries == [requested]


@pytest.mark.parametrize('kind', ['no_activity', 'formation', 'dividend', 'mixed'])
def test_noncapital_and_mixed_history_are_not_filtered_to_approved_or_current_rows(kind, monkeypatch):
    archive, _ = mixed_archive(kind, 0, legacy=True, previews=True)
    store = Store(archive)
    forbid_fresh(monkeypatch)
    assert read(store, query(archive)) is archive
    assert len(store.queries) == 1
    assert len(archive.source_history.year_sources) == 2 and not archive.approvals


@pytest.mark.parametrize('approved', [False, True])
def test_complete_legacy_source_history_stays_available_without_rerender(approved, monkeypatch):
    archive, _ = history_archive(approved=approved)
    archive = replace(archive, overrides=(), withdrawal_capture_records=())
    store = Store(archive)
    forbid_fresh(monkeypatch)
    assert read(store, query(archive)) is archive
    assert all(type(source) is rf.Rf1086YearSourceSnapshot for source in archive.source_history.year_sources)


def test_member_query_preserves_original_actor_and_off_year_company_evidence(monkeypatch):
    archive = snapshot()
    numbers = {'float': 1.1, 'int': 1, 'decimal': Decimal('1.00')}
    archive = replace(archive, source_history=rf.Rf1086ArchiveSourceHistory(), overrides=(),
        withdrawal_capture_records=(), simulations=(replace(archive.simulations[0], submitted_payload=numbers),))
    member = ActorId(ActorKind.USER, UserId(str(UUID(int=99123))))
    requested = replace(query(archive), actor_id=member)
    store = Store(archive, actor=member)  # The fake store models permitted member access.
    assert archive.review_comments[0].created_by != str(member.subject)
    assert archive.review_comments[0].preview_id not in {row.id for row in archive.previews}
    forbid_fresh(monkeypatch)
    assert read(store, requested, outward=True) is archive
    assert store.queries == [requested]
    for name, value in numbers.items():
        assert type(archive.simulations[0].submitted_payload[name]) is type(value)
    assert str(archive.simulations[0].submitted_payload['decimal']) == '1.00'


def test_complete_empty_year_is_distinct_from_missing_capture():
    template = snapshot()
    empty = rf.Rf1086ArchiveSnapshot(template.company_id, template.income_year,
        source_history=rf.Rf1086ArchiveSourceHistory(), overrides=(), withdrawal_capture_records=())
    store = Store(empty)
    assert read(store, query(empty)) is empty
    assert store.queries == [query(empty)]


@pytest.mark.parametrize('blocked', [False, True])
def test_unapproved_preview_raw_text_is_not_replaced_by_canonical_approval_bytes(blocked, monkeypatch):
    archive, _ = mixed_archive(previews=True)
    row = archive.source_history.source_previews[0]
    preview = replace(row.preview, readiness_status='blocked', hovedskjema_xml=None, underskjema_xml=None) if blocked else row.preview
    raw = json.dumps(json.loads(rf.serialize_rf1086_source_preview(preview)), indent=2) + '\n'
    archive = replace(archive, source_history=replace(archive.source_history,
        source_previews=(replace(row, preview=preview, payload_text=raw,
            payload_sha256=sha256(raw.encode()).hexdigest()),)))
    forbid_fresh(monkeypatch)
    assert read(Store(archive), query(archive)) is archive
    assert archive.source_history.source_previews[0].payload_text == raw


@pytest.mark.parametrize('kind', ['empty', 'legacy', 'v3'])
@pytest.mark.parametrize('missing', [('source_history',), ('overrides',), ('withdrawal_capture_records',),
    ('source_history', 'withdrawal_capture_records'), ('source_history', 'overrides', 'withdrawal_capture_records')])
def test_every_live_result_requires_all_three_captured_sections(kind, missing):
    if kind == 'v3':
        archive = approved_v6()
    elif kind == 'legacy':
        archive = replace(snapshot(), source_history=rf.Rf1086ArchiveSourceHistory(), overrides=(), withdrawal_capture_records=())
    else:
        template = snapshot()
        archive = rf.Rf1086ArchiveSnapshot(template.company_id, template.income_year,
            source_history=rf.Rf1086ArchiveSourceHistory(), overrides=(), withdrawal_capture_records=())
    requested = query(archive)
    store = Store(replace(archive, **{name: None for name in missing}))
    with pytest.raises(rf.ShareholderRegisterFilingError) as caught:
        read(store, requested)
    assert caught.value.code is rf.ShareholderRegisterFilingErrorCode.DEPENDENCY_UNAVAILABLE
    assert store.queries == [requested]


@pytest.mark.parametrize('result', [None, {}, 'unexpected', 1, ()])
def test_invalid_return_shape_is_unavailable(result):
    store = Store(result)
    with pytest.raises(rf.ShareholderRegisterFilingError) as caught:
        read(store, query(snapshot()))
    assert caught.value.code is rf.ShareholderRegisterFilingErrorCode.DEPENDENCY_UNAVAILABLE
    assert len(store.queries) == 1


@pytest.mark.parametrize('failure', [rf.ShareholderRegisterFilingError.forbidden(),
    rf.ShareholderRegisterFilingError.not_found(), rf.ShareholderRegisterFilingError.unavailable(),
    RuntimeError('synthetic persistence failure'), asyncio.CancelledError()])
def test_persistence_failures_propagate_unchanged_outside_validation_boundary(failure):
    archive = approved_v6()
    store = Store(archive, failure=failure)
    with pytest.raises(type(failure)) as caught:
        read(store, query(archive), outward=True)
    assert caught.value is failure
    assert store.queries == [query(archive)]


def test_workflow_session_actor_mismatch_precedes_any_raw_read():
    archive = approved_v6()
    other = ActorId(ActorKind.USER, UserId(str(UUID(int=99124))))
    store = Store(archive)
    with pytest.raises(rf.Rf1086ProductionError, match='authentication_required'):
        read(store, replace(query(archive), actor_id=other), outward=True)
    assert store.queries == []


def test_old_archive_query_and_retained_parser_keep_unknown_legacy_coverage():
    archive = snapshot()
    store = Store(archive)
    assert asyncio.run(rf.create_rf1086_preparation_service(store).archive_source(query(archive))) is archive
    text = rf.serialize_rf1086_archive(archive, query=query(archive))
    restored = rf.parse_rf1086_retained_archive(text, query=query(archive))
    assert restored.source_history is restored.overrides is restored.withdrawal_capture_records is None
    with pytest.raises(rf.ShareholderRegisterFilingError):
        read(Store(restored), query(restored))
