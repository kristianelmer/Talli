"""Full-year source previews retain evidence identity and canonical filing bytes."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
from uuid import UUID
from xml.etree import ElementTree as ET

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_year_source import basis, prepare, NOW


class CapturingStore:
    def __init__(self):
        self.prepared = None

    async def capture_source_preview(self, command, prepared):
        self.prepared = prepared
        source, rendered = prepared.source, prepared.rendered
        preview = rf.Rf1086SourcePreview(
            preview_id=rf.PreviewId(str(UUID(int=90))), source_id=source.source_id,
            company_id=source.company_id, income_year=source.income_year,
            source_sha256=source.source_sha256, case_sha256=source.case_sha256,
            readiness_status=rendered.status, readiness_issues=rendered.issues,
            preview_text=rendered.preview, hovedskjema_xml=rendered.hovedskjema_xml,
            underskjema_xml=rendered.underskjema_xml)
        rf.assert_rf1086_source_preview_matches(preview, source)
        return preview


def preview_source(source):
    store = CapturingStore()
    preview = asyncio.run(rf.create_rf1086_preparation_service(store).generate_source_preview(
        rf.GenerateRf1086SourcePreview(source.company_id, source.income_year, source)))
    return preview, store


@pytest.mark.parametrize('kind', ['no_activity', 'dividend', 'cash_issue'])
def test_full_case_preview_uses_canonical_xml_and_explicit_paid_in(kind):
    source = prepare(*basis(kind))
    preview, store = preview_source(source)
    expected = rf.render_rf1086_preview(source.command.case)
    assert preview.hovedskjema_xml == expected.hovedskjema_xml
    assert preview.underskjema_xml == expected.underskjema_xml
    assert preview.readiness_status == 'ready'
    assert 'Skattemessig innbetalt kapital' in preview.preview_text
    assert 'Overkurs 1. januar: 2000.00 kr' in preview.preview_text
    assert store.prepared.source == source


def test_dividend_and_cash_issue_events_are_in_source_xml():
    dividend, _ = preview_source(prepare(*basis('dividend')))
    issue, _ = preview_source(prepare(*basis('cash_issue')))
    assert Decimal(ET.fromstring(dividend.underskjema_xml['owner']).find('.//*[@orid="29169"]').text) == 1000
    assert ET.fromstring(issue.underskjema_xml['owner']).find('.//*[@orid="17745"]').text == "N"


def test_same_filing_bytes_keep_distinct_corrected_evidence_identity():
    command, context = basis()
    old = prepare(command, context)
    correction = replace(command, supersedes_source_id=old.source_id,
        supersedes_source_sha256=old.source_sha256, correction_reason='Corrected evidence attribution')
    current = prepare(correction, context, previous=old,
        source_id=rf.Rf1086YearSourceId(str(UUID(int=91))), confirmed_at=NOW + timedelta(days=1))
    before, _ = preview_source(old)
    after, _ = preview_source(current)
    assert before.hovedskjema_xml == after.hovedskjema_xml
    assert before.source_sha256 != after.source_sha256
    assert before.case_sha256 == after.case_sha256
    with pytest.raises(rf.Rf1086YearSourceError, match='source_preview_mismatch'):
        rf.assert_rf1086_source_preview_matches(before, current)


@pytest.mark.parametrize('field,value', [
    ('source_sha256', 'a' * 64), ('case_sha256', 'b' * 64),
    ('preview_text', 'Changed review'), ('hovedskjema_xml', '<changed/>'),
    ('underskjema_xml', {}), ('readiness_status', 'blocked'),
    ('readiness_issues', (rf.Rf1086ReadinessIssue('warning', 'changed', 'Changed'),)),
    ('rendering_profile', 'unknown'),
])
def test_preview_must_match_exact_source_and_full_render(field, value):
    source = prepare(*basis('dividend'))
    preview, _ = preview_source(source)
    with pytest.raises(rf.Rf1086YearSourceError, match='source_preview_mismatch'):
        rf.assert_rf1086_source_preview_matches(replace(preview, **{field: value}), source)


def test_invalid_source_is_rejected_before_persistence():
    source = prepare(*basis())
    store = CapturingStore()
    altered = replace(source, source_sha256='f' * 64)
    with pytest.raises(rf.Rf1086YearSourceError, match='source_preview_invalid'):
        asyncio.run(rf.create_rf1086_preparation_service(store).generate_source_preview(
            rf.GenerateRf1086SourcePreview(source.company_id, source.income_year, altered)))
    assert store.prepared is None


def test_codec_preserves_original_immutable_render():
    source = prepare(*basis('dividend'))
    preview, _ = preview_source(source)
    serialized = rf.serialize_rf1086_source_preview(preview)
    decoded = rf.parse_rf1086_source_preview(serialized)
    assert decoded == preview
    assert rf.serialize_rf1086_source_preview(decoded) == serialized
    with pytest.raises(TypeError):
        decoded.underskjema_xml['owner'] = 'changed'


@pytest.mark.parametrize('change', ['xml', 'hash', 'version', 'extra', 'duplicates', 'nonfinite', 'not_preview'])
def test_codec_rejects_altered_or_malformed_stored_payload(change):
    preview, _ = preview_source(prepare(*basis()))
    raw = json.loads(rf.serialize_rf1086_source_preview(preview))
    if change == 'xml': raw['preview']['hovedskjema_xml'] = 'changed'
    if change == 'hash': raw['sha256'] = 'f' * 64
    if change == 'version': raw['codec'] = 'unknown'
    if change == 'extra': raw['extra'] = None
    if change == 'nonfinite': raw['preview'] = float('nan')
    if change == 'not_preview': raw['preview'] = None
    value = json.dumps(raw)
    if change == 'duplicates': value = value[:-1] + ', "sha256": "' + 'f' * 64 + '"}'
    with pytest.raises(rf.Rf1086YearSourceError, match='source_preview_storage_invalid'):
        rf.parse_rf1086_source_preview(value)


def test_paid_in_review_preserves_sub_cent_precision_independent_of_rounding():
    from decimal import localcontext, ROUND_DOWN, ROUND_UP
    command, context = basis()
    case = replace(command.case, share_snapshot=replace(command.case.share_snapshot,
        previous_paid_in_premium=Decimal('2000.005'), current_paid_in_premium=Decimal('2000.005')))
    command = replace(command, case=case, paid_in=replace(command.paid_in,
        opening_premium=Decimal('2000.005'), closing_premium=Decimal('2000.005')))
    source = prepare(command, context)
    previews = []
    for rounding in (ROUND_DOWN, ROUND_UP):
        with localcontext() as decimal_context:
            decimal_context.rounding = rounding
            previews.append(preview_source(source)[0])
    assert previews[0] == previews[1]
    assert 'Overkurs 1. januar: 2000.005 kr' in previews[0].preview_text


def test_historical_blocked_preview_codec_retains_absent_xml():
    preview, _ = preview_source(prepare(*basis()))
    blocked = replace(preview, readiness_status='blocked', hovedskjema_xml=None, underskjema_xml=None)
    assert rf.parse_rf1086_source_preview(rf.serialize_rf1086_source_preview(blocked)) == blocked


def test_registered_capital_review_is_exact_and_independent_of_rounding():
    from decimal import localcontext, ROUND_DOWN, ROUND_UP
    command, context = basis()
    capital = Decimal('30000.005')
    nominal = Decimal('300.00005')
    case = replace(command.case, share_snapshot=replace(command.case.share_snapshot,
        previous_share_capital=capital, current_share_capital=capital,
        previous_nominal_value=nominal, current_nominal_value=nominal,
        previous_paid_in_share_capital=capital, current_paid_in_share_capital=capital))
    command = replace(command, case=case, paid_in=replace(command.paid_in,
        opening_capital=capital, closing_capital=capital))
    source = prepare(command, context)
    previews = []
    for rounding in (ROUND_DOWN, ROUND_UP):
        with localcontext() as decimal_context:
            decimal_context.rounding = rounding
            previews.append(preview_source(source)[0])
    assert previews[0] == previews[1]
    assert '- Aksjekapital 1. januar: 30000.005 kr' in previews[0].preview_text


def retained_v2_preview_row():
    """Hand-built retained row; this does not invoke or enable a v2 writer."""
    from hashlib import sha256
    from test_rf1086_year_source_v2 import prepare
    source = prepare()
    rendered = rf.render_rf1086_preview(source.command.case)
    preview = rf.Rf1086SourcePreview(preview_id=rf.PreviewId(str(UUID(int=990))),
        source_id=source.source_id, company_id=source.company_id, income_year=source.income_year,
        source_sha256=source.source_sha256, case_sha256=source.case_sha256,
        readiness_status=rendered.status, readiness_issues=rendered.issues,
        preview_text='Retained renderer wording\n' + rendered.preview,
        hovedskjema_xml=rendered.hovedskjema_xml, underskjema_xml=rendered.underskjema_xml)
    encoded = rf.serialize_rf1086_source_preview(preview)
    row = dict(id=preview.preview_id.value, company_id=source.company_id.value,
        income_year=source.income_year.value, source_id=source.source_id.value,
        source_sha256=source.source_sha256, case_sha256=source.case_sha256,
        profile=preview.rendering_profile, payload_text=encoded,
        payload_sha256=sha256(encoded.encode()).hexdigest(),
        source_snapshot_text=rf.serialize_rf1086_year_source_v2(source))
    return source, preview, row


def test_retained_v2_preview_returns_exact_original_renderer_bytes_without_rerender(monkeypatch):
    from talli_backend.adapters.postgres_shareholder_register_filing import PostgresShareholderRegisterFilingSession
    source, preview, row = retained_v2_preview_row()
    def forbidden(*args, **kwargs):
        raise AssertionError('A historical preview must not invoke the current renderer')
    monkeypatch.setattr(rf, 'render_rf1086_preview', forbidden)
    monkeypatch.setattr(rf, 'assert_rf1086_source_preview_matches', forbidden)
    result = PostgresShareholderRegisterFilingSession._source_preview(row)
    assert result == preview
    assert rf.serialize_rf1086_source_preview(result) == row['payload_text']
    assert result.source_sha256 == source.source_sha256
    assert result.preview_text.startswith('Retained renderer wording\n')


@pytest.mark.parametrize('change', ['preview_id', 'company', 'year', 'source_id', 'source_hash',
    'case_hash', 'profile', 'payload_hash', 'payload_bytes', 'malformed_source',
    'unknown_codec', 'cross_codec', 'duplicate_codec', 'source_integrity', 'source_binding'])
def test_retained_v2_preview_rejects_malformed_or_cross_bound_rows(change):
    from talli_backend.adapters.postgres_shareholder_register_filing import PostgresShareholderRegisterFilingSession
    source, preview, row = retained_v2_preview_row()
    if change == 'preview_id': row['id'] = str(UUID(int=991))
    if change == 'company': row['company_id'] = str(UUID(int=992))
    if change == 'year': row['income_year'] -= 1
    if change == 'source_id': row['source_id'] = str(UUID(int=993))
    if change == 'source_hash': row['source_sha256'] = 'f' * 64
    if change == 'case_hash': row['case_sha256'] = 'f' * 64
    if change == 'profile': row['profile'] = 'unknown'
    if change == 'payload_hash': row['payload_sha256'] = 'f' * 64
    if change == 'payload_bytes': row['payload_text'] += ' '
    if change == 'malformed_source': row['source_snapshot_text'] = '{'
    if change == 'unknown_codec':
        raw = json.loads(row['source_snapshot_text'])
        raw['codec'] = 'rf1086-year-source-v3'
        row['source_snapshot_text'] = json.dumps(raw)
    if change == 'cross_codec':
        row['source_snapshot_text'] = row['source_snapshot_text'].replace(
            'rf1086-year-source-v2', 'rf1086-year-source-v1', 1)
    if change == 'duplicate_codec':
        row['source_snapshot_text'] = row['source_snapshot_text'][:-1] + ',"codec":"rf1086-year-source-v2"}'
    if change == 'source_integrity':
        row['source_snapshot_text'] = row['source_snapshot_text'].replace(source.source_sha256, 'f' * 64)
    if change == 'source_binding':
        from test_rf1086_year_source_v2 import prepare, v2_basis
        other = prepare(*v2_basis(), source_id=rf.Rf1086YearSourceId(str(UUID(int=994))))
        row['source_snapshot_text'] = rf.serialize_rf1086_year_source_v2(other)
    with pytest.raises(rf.Rf1086YearSourceError, match='storage_invalid'):
        PostgresShareholderRegisterFilingSession._source_preview(row)


def test_retained_v2_support_does_not_enable_new_preview_generation():
    from test_rf1086_year_source_v2 import prepare
    source = prepare()
    store = CapturingStore()
    with pytest.raises(rf.Rf1086YearSourceError):
        asyncio.run(rf.create_rf1086_preparation_service(store).generate_source_preview(
            rf.GenerateRf1086SourcePreview(source.company_id, source.income_year, source)))
    assert store.prepared is None
