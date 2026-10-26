"""Frozen read model for the future annual-compliance source store."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import json
import math
from types import MappingProxyType
from uuid import UUID

from talli_backend.shared.kernel import CompanyId, IncomeYear


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class LegacyAnnualDataView:
    source_id: str
    company_id: CompanyId
    income_year: IncomeYear
    answers: Mapping[str, object]
    confirmations: tuple[str, ...]
    no_activity_confirmed: bool
    annual_full_time_equivalents: int | float
    completed_at: str
    updated_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "answers", _freeze(self.answers))


def decode_annual_interview_history(items, company_id: CompanyId,
                                    income_year: IncomeYear) -> LegacyAnnualDataView | None:
    """Decode the existing exact-year history API without deciding readiness.

    Absence is distinct from malformed/unavailable history. Answer interpretation
    remains with the consuming capability and Annual's canonical policy.
    """
    if not isinstance(items, list):
        raise ValueError('Annual interview history is unavailable.')
    selected, identities, years = None, set(), set()
    expected = {'sourceId', 'companyId', 'incomeYear', 'answers', 'confirmations',
                'noActivityConfirmed', 'annualFullTimeEquivalents', 'completedAt', 'updatedAt'}
    for item in items:
        if (not isinstance(item, dict) or set(item) != expected
                or item['companyId'] != str(company_id)
                or type(item['incomeYear']) is not int
                or not 2000 <= item['incomeYear'] <= int(income_year)
                or type(item['sourceId']) is not str):
            raise ValueError('Annual interview history scope is invalid.')
        identity = str(UUID(item['sourceId']))
        if identity != item['sourceId'] or identity in identities or item['incomeYear'] in years:
            raise ValueError('Annual interview history is ambiguous.')
        identities.add(identity)
        years.add(item['incomeYear'])
        if (not isinstance(item['answers'], dict)
                or any(type(key) is not str for key in item['answers'])
                or not isinstance(item['confirmations'], list)
                or any(type(value) is not str for value in item['confirmations'])
                or type(item['noActivityConfirmed']) is not bool):
            raise ValueError('Annual interview facts are malformed.')
        json.dumps(item['answers'], allow_nan=False)
        equivalents = item['annualFullTimeEquivalents']
        if equivalents is not None and (type(equivalents) not in (int, float)
                or not math.isfinite(equivalents) or equivalents < 0):
            raise ValueError('Annual interview workforce fact is malformed.')
        for name in ('completedAt', 'updatedAt'):
            if type(item[name]) is not str or datetime.fromisoformat(item[name]).utcoffset() is None:
                raise ValueError('Annual interview time is malformed.')
        if item['incomeYear'] == int(income_year):
            selected = LegacyAnnualDataView(identity, company_id, income_year, item['answers'],
                tuple(item['confirmations']), item['noActivityConfirmed'],
                0 if equivalents is None else equivalents, item['completedAt'], item['updatedAt'])
    return selected


__all__ = ["LegacyAnnualDataView", "decode_annual_interview_history"]
