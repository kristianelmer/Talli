"""Frozen read model for the future annual-compliance source store."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

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


__all__ = ["LegacyAnnualDataView"]
