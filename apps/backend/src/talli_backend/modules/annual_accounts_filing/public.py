"""Immutable Annual Accounts calculation, rendering and readiness contracts."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class AnnualAccountsSource:
    """Ordered source facts supplied by a workflow; no authorization attestation."""
    income_year: int
    annual_data: Mapping[str, object] | None
    ledger_entries: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'annual_data', _freeze(self.annual_data))
        object.__setattr__(self, 'ledger_entries', _freeze(self.ledger_entries))


@dataclass(frozen=True, slots=True)
class AnnualAccountsCandidate:
    schema_type: str
    main_form_format_id: str
    main_form_format_version: str
    accounts_format_id: str
    accounts_format_version: str
    notes: Mapping[str, object]
    fields: tuple[Mapping[str, object], ...]
    feedback: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        for name in ('notes', 'fields', 'feedback'):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class AnnualAccountsRenderInput:
    candidate: AnnualAccountsCandidate
    organization_number: str
    company_name: str
    contact_email: str
    approval_date: str
    confirming_representative: str


@dataclass(frozen=True, slots=True)
class AnnualAccountsDocuments:
    main_form_xml: str
    company_accounts_xml: str


@dataclass(frozen=True, slots=True)
class AnnualAccountsReadinessIssue:
    level: str
    code: str
    message: str
    source: str
    accepted: bool = False


@dataclass(frozen=True, slots=True)
class AnnualAccountsCorporateReadiness:
    """Corporate Governance's blockers; enabling this does not manufacture close facts."""
    enabled: bool
    blockers: tuple[AnnualAccountsReadinessIssue, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'blockers', tuple(self.blockers))


def build_annual_accounts(source: AnnualAccountsSource) -> AnnualAccountsCandidate:
    from .calculation import build
    return build(source)


def render_annual_accounts(input: AnnualAccountsRenderInput) -> AnnualAccountsDocuments:
    from .rendering import render
    return render(input)


def assess_annual_accounts_readiness(
    source: AnnualAccountsSource, *, company_id: str,
    corporate: AnnualAccountsCorporateReadiness | None = None,
) -> tuple[AnnualAccountsReadinessIssue, ...]:
    """Accounts-specific issues only; Annual retains the common readiness gates."""
    from .readiness import assess
    return assess(source, company_id, corporate)


__all__ = [
    'AnnualAccountsSource', 'AnnualAccountsCandidate', 'AnnualAccountsRenderInput',
    'AnnualAccountsDocuments', 'AnnualAccountsReadinessIssue', 'AnnualAccountsCorporateReadiness',
    'build_annual_accounts', 'render_annual_accounts', 'assess_annual_accounts_readiness',
]
