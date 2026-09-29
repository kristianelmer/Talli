"""Complete, exact-year RF opening evidence; no no-activity rendering assumption."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
import re
from uuid import UUID

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear


@dataclass(frozen=True, slots=True)
class Rf1086AnnualOpeningInputs:
    company_id: CompanyId
    income_year: IncomeYear
    opening_sources: tuple[rf.Rf1086OpeningSource, ...]


def annual_opening_inputs(openings, shareholders, query: rf.Rf1086SourceQuery) -> Rf1086AnnualOpeningInputs:
    """Commit complete owner rows, including lock/creation times and attribution.

    These are onboarding opening snapshots, not a claim that the full-year
    statutory case has no events or starts with these same capital amounts.
    The SQL owner reader also enforces migration-quarantine integrity.
    """
    try:
        if type(openings) is not list or type(shareholders) is not list or len(openings) > 1:
            raise ValueError()
        if not openings:
            if shareholders:
                raise ValueError()
            return Rf1086AnnualOpeningInputs(query.company_id, query.income_year, ())
        opening = openings[0]
        identity = _uuid(opening['id'])
        if (CompanyId(_uuid(opening['company_id'])) != query.company_id
                or type(opening['income_year']) is not int or opening['income_year'] != int(query.income_year)
                or type(opening['share_count']) is not int or opening['share_count'] <= 0
                or not 1 <= len(shareholders) <= 100):
            raise ValueError()
        _uuid(opening['created_by'])
        _timestamp(opening['locked_at'])
        _timestamp(opening['created_at'])
        capital, nominal = opening['share_capital'], opening['nominal_value']
        if (not isinstance(capital, Decimal) or not capital.is_finite() or capital < 0
                or not isinstance(nominal, Decimal) or not nominal.is_finite() or nominal <= 0):
            raise ValueError()
        with localcontext() as context:
            context.prec = max(28, len(nominal.as_tuple().digits) + len(str(opening['share_count'])) + 2)
            if capital != nominal * opening['share_count']:
                raise ValueError()
        identities = set()
        total = 0
        for holder in shareholders:
            holder_id = _uuid(holder['id'])
            if (holder_id in identities or _uuid(holder['setup_id']) != identity
                    or CompanyId(_uuid(holder['company_id'])) != query.company_id
                    or type(holder['share_count']) is not int or holder['share_count'] < 0
                    or type(holder['name']) is not str or not holder['name'].strip()
                    or len(holder['name']) > 255):
                raise ValueError()
            identities.add(holder_id)
            _uuid(holder['created_by'])
            _timestamp(holder['created_at'])
            kind = holder['shareholder_kind']
            field, width = {'norwegian_person': ('national_id', 11), 'norwegian_company': ('org_number', 9)}[kind]
            if type(holder[field]) is not str or not re.fullmatch(r'[0-9]{' + str(width) + '}', holder[field]):
                raise ValueError()
            total += holder['share_count']
        if total != opening['share_count']:
            raise ValueError()
        content = {'schema_version': 'rf1086-annual-opening-input-v1',
                   'opening': _canonical_row(opening),
                   'shareholders': [_canonical_row(row) for row in sorted(shareholders, key=lambda row: _uuid(row['id']))]}
        source = rf.Rf1086OpeningSource(query.company_id, rf.OpeningSnapshotId(identity), query.income_year,
                                       rf.rf1086_year_source_digest(content), len(shareholders))
        return Rf1086AnnualOpeningInputs(query.company_id, query.income_year, (source,))
    except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError):
        raise rf.ShareholderRegisterFilingError.unavailable() from None


def _uuid(value):
    if not isinstance(value, (UUID, str)):
        raise ValueError()
    return str(UUID(str(value)))


def _timestamp(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError()


def _canonical_row(row):
    return {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}
