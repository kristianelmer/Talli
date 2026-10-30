"""Independent complete-query checks; fake access is not database enumeration proof."""
import asyncio
from dataclasses import replace
from datetime import timedelta, timezone
from hashlib import sha256
from itertools import combinations
import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from talli_backend.application import shareholder_register_filing_workflow as workflow
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.modules.shareholder_register_filing.preparation import Rf1086PreparationService
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId
from test_rf1086_archive_source import snapshot as legacy_snapshot
from test_rf1086_archive_history_v6 import mixed_archive
from test_rf1086_archive_storage_v6 import forbid_fresh
from test_rf1086_retained_source_dispatch import retained_submission
from test_rf1086_year_source import ACTOR

CAPTURES = ('source_history', 'overrides', 'withdrawal_capture_records')
OMISSIONS = tuple(group for size in (1, 2, 3) for group in combinations(CAPTURES, size))
MEMBER = ActorId(ActorKind.USER, UserId(str(UUID(int=44001))))


def complete(kind='empty'):
    if kind == 'v2':
        return mixed_archive('loss_covering_reduction', 2, legacy=True, previews=True)[0]
    original = legacy_snapshot()
    if kind == 'empty':
        original = rf.Rf1086ArchiveSnapshot(original.company_id, original.income_year)
    return replace(original, source_history=rf.Rf1086ArchiveSourceHistory(),
        overrides=(), withdrawal_capture_records=())


def requested(archive, actor=ACTOR):
    return rf.Rf1086ArchiveQuery(archive.company_id, archive.income_year, actor)


class OnlyRawRead:
    def __init__(self, result, *, actor=ACTOR, failure=None):
        self.result, self.actor_id, self.failure = result, actor, failure
        self.calls = []

    async def archive_source(self, query):
        self.calls.append(query)
        if self.failure is not None:
            raise self.failure
        return self.result

    def __getattr__(self, name):
        raise AssertionError('Unexpected archive query dependency: ' + name)


def bomb(*args, **kwargs):
    raise AssertionError('A retained query cannot use fresh, dispatch, codec or clock work')


def read(store, query):
    return asyncio.run(Rf1086PreparationService(store, clock=bomb).retained_archive_source(query))


def unavailable(archive, query=None):
    query = requested(archive) if query is None else query
    store = OnlyRawRead(archive)
    with pytest.raises(rf.ShareholderRegisterFilingError) as caught:
        read(store, query)
    assert caught.value.code == rf.ShareholderRegisterFilingErrorCode.DEPENDENCY_UNAVAILABLE
    assert store.calls == [query]
    return caught.value


@pytest.mark.parametrize('kind', ['empty', 'legacy', 'v2'])
@pytest.mark.parametrize('omitted', OMISSIONS)
def test_all_capture_sections_are_required_without_inferring_empty_history(kind, omitted):
    archive = complete(kind)
    unavailable(replace(archive, **{field: None for field in omitted}))


@pytest.mark.parametrize('kind', ['empty', 'legacy', 'v2'])
def test_complete_result_is_same_object_for_a_distinct_member_without_extra_ports(kind, monkeypatch):
    archive = complete(kind)
    query = requested(archive, MEMBER)
    store = OnlyRawRead(archive, actor=MEMBER)
    if kind == 'v2':
        source = archive.source_history.year_sources[-1]
        assert len(source.governance_projection.chains) == 1
        assert source.governance_projection.chains[0].amendment_count == 2
        assert len(archive.source_history.register_observations) == 3
        assert len(archive.withdrawal_capture_records) == 2
        assert source.confirmed_by != MEMBER
    elif kind == 'legacy':
        assert archive.review_comments[0].preview_id not in {row.id for row in archive.previews}
        assert archive.review_comments[0].created_by != str(MEMBER.subject)
    forbid_fresh(monkeypatch)
    for name in ('serialize_rf1086_archive', 'parse_rf1086_archive', 'serialize_rf1086_archive_v6',
                 'parse_rf1086_retained_archive', 'assess_rf1086_retained_source_dispatch',
                 'prepare_rf1086_retained_source_reconciliation'):
        monkeypatch.setattr(rf, name, bomb)
    result = asyncio.run(workflow.ShareholderRegisterFilingWorkflow(store).retained_archive_source(query))
    assert result is archive
    assert store.calls == [query]


@pytest.mark.parametrize('shape', ['history-dict', 'history-subclass', 'override-list',
                                  'withdrawal-list', 'float-year', 'foreign-company'])
def test_malformed_returned_capture_and_scope_shapes_fail_closed(shape):
    archive = complete()
    query = requested(archive)
    if shape == 'history-dict':
        object.__setattr__(archive, 'source_history', {})
    elif shape == 'history-subclass':
        class HistorySubclass(rf.Rf1086ArchiveSourceHistory):
            pass
        object.__setattr__(archive, 'source_history', HistorySubclass())
    elif shape == 'override-list':
        object.__setattr__(archive, 'overrides', [])
    elif shape == 'withdrawal-list':
        object.__setattr__(archive, 'withdrawal_capture_records', [])
    elif shape == 'float-year':
        object.__setattr__(archive, 'income_year', IncomeYear(float(archive.income_year.value)))
    else:
        object.__setattr__(archive, 'company_id', CompanyId(str(UUID(int=44002))))
    unavailable(archive, query)


@pytest.mark.parametrize('shape', ['untyped-result', 'untyped-query'])
def test_untyped_boundary_values_have_closed_unavailable(shape):
    archive = complete()
    query = requested(archive)
    if shape == 'untyped-result':
        archive = SimpleNamespace(**{name: getattr(archive, name) for name in
            ('company_id', 'income_year', *CAPTURES)})
    else:
        query = SimpleNamespace(company_id=query.company_id, income_year=query.income_year, actor_id=query.actor_id)
    unavailable(archive, query)


@pytest.mark.parametrize('attack', ['head-missing', 'head-wrong', 'duplicate-observation',
    'missing-observation', 'missing-source-capture', 'missing-withdrawal',
    'raw-source-corrupt', 'raw-observation-offset'])
def test_captured_history_is_validated_instead_of_only_checking_presence(attack):
    archive = complete('v2')
    history = archive.source_history
    if attack == 'head-missing':
        history = replace(history, year_source_head=None)
    elif attack == 'head-wrong':
        history = replace(history, year_source_head=replace(history.year_source_head, source_sha256='f' * 64))
    elif attack == 'duplicate-observation':
        history = replace(history, register_observations=(*history.register_observations, history.register_observations[0]))
    elif attack == 'missing-observation':
        history = replace(history, register_observations=history.register_observations[1:])
    elif attack == 'missing-source-capture':
        history = replace(history, source_capture_records=history.source_capture_records[1:])
    elif attack == 'missing-withdrawal':
        archive = replace(archive, withdrawal_capture_records=archive.withdrawal_capture_records[1:])
    elif attack == 'raw-source-corrupt':
        row = history.source_capture_records[-1]
        history = replace(history, source_capture_records=(*history.source_capture_records[:-1],
            replace(row, snapshot_text=row.snapshot_text + 'broken')))
    else:
        original = history.register_observations[-1]
        changed = replace(original, confirmed_at=original.confirmed_at.astimezone(timezone(timedelta(hours=3))))
        assert original.confirmed_at == changed.confirmed_at
        assert rf.serialize_rf1086_register_observation(original) != rf.serialize_rf1086_register_observation(changed)
        history = replace(history, observation_capture_records=tuple(
            replace(row, snapshot_text=rf.serialize_rf1086_register_observation(changed))
            if row.record_id == original.observation_id.value else row
            for row in history.observation_capture_records))
    unavailable(replace(archive, source_history=history))


def recommit(archive, manifest, review=None):
    line = archive.source_approval_lineage[0]
    if review is not None:
        text = json.dumps(review, sort_keys=True, ensure_ascii=False)
        manifest['review']['sha256'] = sha256(text.encode()).hexdigest()
        line = replace(line, review_text=text, review_sha256=manifest['review']['sha256'])
    text = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    digest = sha256(text.encode()).hexdigest()
    return replace(archive,
        approvals=(replace(archive.approvals[0], manifest=manifest, manifest_hash=digest),),
        source_approval_lineage=(replace(line, manifest_text=text, manifest_sha256=digest),),
        source_submission_claims=tuple(replace(row, manifest_sha256=digest) for row in archive.source_submission_claims))


@pytest.mark.parametrize('attack', ['source-commitment', 'document-commitment', 'review-release',
                                  'annual-proof', 'claim-payload', 'journal-body'])
def test_checksums_and_complete_sections_cannot_replace_retained_semantic_proof(attack):
    archive = retained_submission('cash_issue', 2, 'accepted')
    manifest = json.loads(archive.source_approval_lineage[0].manifest_text)
    if attack == 'source-commitment':
        manifest['source']['sha256'] = 'f' * 64
        archive = recommit(archive, manifest)
    elif attack == 'document-commitment':
        manifest['documentHashes'][0]['sha256'] = 'f' * 64
        archive = recommit(archive, manifest)
    elif attack == 'review-release':
        review = json.loads(archive.source_approval_lineage[0].review_text)
        review['technicalReleaseReady'] = False
        archive = recommit(archive, manifest, review)
    elif attack == 'annual-proof':
        binding = manifest['annualReadiness']
        binding['proofText'] = 'not a retained typed annual proof'
        binding['proofTextSha256'] = sha256(binding['proofText'].encode()).hexdigest()
        archive = recommit(archive, manifest)
    elif attack == 'claim-payload':
        archive = replace(archive, source_submission_claims=(replace(
            archive.source_submission_claims[0], payload_sha256='f' * 64),))
    else:
        event = archive.production_events[0]
        archive = replace(archive, production_events=(replace(event, body_hash='f' * 64), *archive.production_events[1:]))
    unavailable(archive)


@pytest.mark.parametrize('failure', [rf.ShareholderRegisterFilingError.forbidden(),
    rf.ShareholderRegisterFilingError.not_found(), rf.ShareholderRegisterFilingError.unavailable(),
    ValueError('raw persistence decode failure'), RuntimeError('raw dependency failed'), asyncio.CancelledError()])
def test_raw_read_error_and_cancellation_escape_unchanged_without_retry(failure):
    archive = complete()
    store = OnlyRawRead(archive, failure=failure)
    query = requested(archive)
    with pytest.raises(type(failure)) as caught:
        read(store, query)
    assert caught.value is failure
    assert store.calls == [query]


def test_wrong_workflow_actor_is_rejected_before_service_construction_or_read(monkeypatch):
    archive = complete()
    store = OnlyRawRead(archive)
    monkeypatch.setattr(workflow, 'create_rf1086_preparation_service', bomb)
    with pytest.raises(rf.Rf1086ProductionError, match='authentication_required'):
        asyncio.run(workflow.ShareholderRegisterFilingWorkflow(store).retained_archive_source(requested(archive, MEMBER)))
    assert store.calls == []


@pytest.mark.parametrize('method', ['archive_source', 'legacy_archive_source'])
def test_existing_query_preserves_unknown_capture_coverage(method):
    archive = legacy_snapshot()
    assert all(getattr(archive, field) is None for field in CAPTURES)
    class OldReadStore(OnlyRawRead):
        async def legacy_archive_source(self, query):
            self.calls.append(query)
            return self.result
    store = OldReadStore(archive)
    query = requested(archive)
    assert asyncio.run(getattr(Rf1086PreparationService(store, clock=bomb), method)(query)) is archive
    assert store.calls == [query]


def test_existing_legacy_codec_roundtrip_preserves_unknown_and_new_query_rejects_it():
    archive = legacy_snapshot()
    query = requested(archive)
    text = rf.serialize_rf1086_archive(archive, query=query)
    parsed = rf.parse_rf1086_retained_archive(text, query=query)
    assert all(getattr(parsed, field) is None for field in CAPTURES)
    assert rf.serialize_rf1086_archive(parsed, query=query) == text
    unavailable(parsed, query)
