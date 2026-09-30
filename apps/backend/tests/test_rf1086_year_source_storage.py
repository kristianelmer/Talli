from dataclasses import replace
from decimal import Decimal
import json
import re
import pytest
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_year_source import basis, prepare

@pytest.mark.parametrize('kind', ['no_activity','dividend','cash_issue'])
def test_storage_roundtrip_preserves_every_source_digest_and_exact_decimal(kind):
    command, context = basis(kind)
    source = prepare(command, context)
    encoded = rf.serialize_rf1086_year_source(source)
    decoded = rf.parse_rf1086_year_source(encoded)
    assert rf.rf1086_year_source_digest(decoded) == rf.rf1086_year_source_digest(source)
    assert rf.serialize_rf1086_year_source(decoded) == encoded
    assert decoded.command.paid_in.opening_premium == Decimal('2000')

@pytest.mark.parametrize('mutation', ['unknown_record','changed_hash','missing_field','duplicate_field','nan','malformed_decimal','executable'])
def test_storage_rejects_unknown_altered_or_ambiguous_records(mutation):
    command, context = basis(); raw=rf.serialize_rf1086_year_source(prepare(command,context))
    if mutation=='unknown_record': raw=raw.replace('Rf1086YearSourceSnapshot','ForeignRecord')
    elif mutation=='changed_hash': raw=raw.replace('"source_sha256":"','"source_sha256":"f',1)
    elif mutation=='missing_field':
        value=json.loads(raw);del value['snapshot']['fields']['command'];raw=json.dumps(value)
    elif mutation=='duplicate_field':raw=raw.replace('"codec":','"codec":"invalid","codec":',1)
    elif mutation=='nan':raw=re.sub(r'"decimal":"[^"]+"', '"decimal":"NaN"', raw, count=1)
    elif mutation=='malformed_decimal':raw=re.sub(r'"decimal":"[^"]+"', '"decimal":"invalid decimal"', raw, count=1)
    elif mutation=='executable':raw='{"codec":"rf1086-year-source-v1","snapshot":{"record":"eval","fields":{}}}'
    with pytest.raises(rf.Rf1086YearSourceError,match='storage_invalid'):rf.parse_rf1086_year_source(raw)


def test_storage_roundtrip_does_not_round_fractional_decimal_evidence():
    command,context=basis()
    shares=replace(command.case.share_snapshot,previous_paid_in_premium=Decimal('2000.123456'),current_paid_in_premium=Decimal('2000.123456'))
    command=replace(command,case=replace(command.case,share_snapshot=shares),paid_in=replace(command.paid_in,opening_premium=Decimal('2000.123456'),closing_premium=Decimal('2000.123456')))
    source=prepare(command,context)
    loaded=rf.parse_rf1086_year_source(rf.serialize_rf1086_year_source(source))
    assert loaded.command.case.share_snapshot.previous_paid_in_premium==Decimal('2000.123456')
    assert loaded.source_sha256==source.source_sha256
