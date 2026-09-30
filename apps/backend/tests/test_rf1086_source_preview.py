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
