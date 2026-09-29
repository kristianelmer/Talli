"""Exact-year RF consumer of the unchanged annual interview history contract."""
from datetime import datetime, timezone
import json
import math
from uuid import UUID

from talli_backend.application.annual_data_compatibility import LegacyAnnualDataView
from talli_backend.modules.shareholder_register_filing import public as rf


def annual_interview_for_year(items, query) -> LegacyAnnualDataView | None:
    """Validate scope and uniqueness before choosing this year's immutable view.

    A successfully enumerated history without this year means missing interview.
    Malformed/unavailable evidence never becomes that missing-source result.
    """
    try:
        if not isinstance(items, list):
            raise ValueError()
        selected = None
        years, identities = set(), set()
        for item in items:
            if (not isinstance(item, dict) or item.get('companyId') != str(query.company_id)
                    or type(item.get('incomeYear')) is not int
                    or not 2000 <= item['incomeYear'] <= int(query.income_year)
                    or type(item.get('sourceId')) is not str):
                raise ValueError()
            identity = str(UUID(item['sourceId']))
            if identity != item['sourceId'] or identity in identities or item['incomeYear'] in years:
                raise ValueError()
            identities.add(identity)
            years.add(item['incomeYear'])
            if item['incomeYear'] == int(query.income_year):
                selected = item
        if selected is None:
            return None
        expected = {'sourceId', 'companyId', 'incomeYear', 'answers', 'confirmations',
                    'noActivityConfirmed', 'annualFullTimeEquivalents', 'completedAt', 'updatedAt'}
        if set(selected) != expected:
            raise ValueError()
        answers, confirmations = selected['answers'], selected['confirmations']
        if (not isinstance(answers, dict) or any(type(key) is not str for key in answers)
                or not isinstance(confirmations, list)
                or any(type(value) is not str for value in confirmations)
                or type(selected['noActivityConfirmed']) is not bool):
            raise ValueError()
        # Preserve unknown JSON answers as evidence; validate the flags used by
        # the existing RF annual prerequisites without truthiness coercion.
        for key in ('bank_balance_confirmed', 'has_unpaid_items', 'authority_to_submit_confirmed'):
            if key in answers and type(answers[key]) is not bool:
                raise ValueError()
        json.dumps(answers, allow_nan=False)
        equivalents = selected['annualFullTimeEquivalents']
        if equivalents is not None and (type(equivalents) not in (int, float)
                or not math.isfinite(equivalents) or equivalents < 0):
            raise ValueError()
        times = []
        for key in ('completedAt', 'updatedAt'):
            if type(selected[key]) is not str:
                raise ValueError()
            value = datetime.fromisoformat(selected[key])
            if value.utcoffset() is None:
                raise ValueError()
            times.append(value.astimezone(timezone.utc).isoformat())
        return LegacyAnnualDataView(selected['sourceId'], query.company_id, query.income_year,
                                    answers, tuple(confirmations), selected['noActivityConfirmed'],
                                    0 if equivalents is None else equivalents, *times)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise rf.ShareholderRegisterFilingError.unavailable() from None
