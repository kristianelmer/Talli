"""Immutable Annual Accounts calculation, rendering and readiness contracts."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


def _freeze(value):
    # Ignored JSON metadata may be deeply nested. Copy without Python call-stack
    # recursion, while retaining input order and rejecting non-JSON cycles.
    result = [None]
    active = set()
    pending = [('visit', value, result, 0)]
    while pending:
        operation, item, parent, key = pending.pop()
        if operation == 'finish':
            original, copied = item
            parent[key] = MappingProxyType(copied) if isinstance(copied, dict) else tuple(copied)
            active.remove(id(original))
        elif isinstance(item, (Mapping, list, tuple)):
            if id(item) in active:
                raise ValueError('Annual Accounts source facts must not contain cycles.')
            active.add(id(item))
            entries = list(item.items()) if isinstance(item, Mapping) else list(enumerate(item))
            copied = {child_key: None for child_key, _ in entries} if isinstance(item, Mapping) else [None] * len(item)
            pending.append(('finish', (item, copied), parent, key))
            pending.extend(('visit', child, copied, child_key) for child_key, child in reversed(entries))
        else:
            parent[key] = item
    return result[0]


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


@dataclass(frozen=True, slots=True)
class AnnualAccountsOfflineSource:
    """Existing public-data Annual totals; deliberately distinct from live Ledger input.

    Annual's offline model retains common aggregation and common readiness policy.
    This contract owns only the Accounts projection of those immutable facts.
    """
    company_id: str
    income_year: int
    bank_balance: float
    investment_balance: float
    admin_costs: float
    financial_income: float
    financial_costs: float
    shareholder_loan_payable: float
    share_capital: float
    retained_earnings: float
    result_before_tax: float
    general_meeting_approved: bool
    common_issues: tuple[Mapping[str, object], ...] = ()
    confirmations: tuple[str, ...] = ()
    annual_full_time_equivalents: float | None = 0
    audit_required: bool = False
    small_enterprise: bool = True
    annual_report_required: bool = False
    cash_flow_statement_required: bool = False
    sustainability_reporting_required: bool = False
    fiscal_year_is_calendar_year: bool = True
    prior_year_figures_confirmed: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, 'common_issues', _freeze(self.common_issues))
        object.__setattr__(self, 'confirmations', tuple(self.confirmations))


@dataclass(frozen=True, slots=True)
class AnnualAccountsOfflineSimulation:
    filing: str
    preview: str
    readiness: Mapping[str, object]
    simulated_receipt_id: str | None
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'readiness', _freeze(self.readiness))
        object.__setattr__(self, 'payload', _freeze(self.payload))


def build_annual_accounts_offline_payload(source: AnnualAccountsOfflineSource) -> Mapping[str, object]:
    from .offline import build_payload
    return _freeze(build_payload(source))


def assess_annual_accounts_offline(source: AnnualAccountsOfflineSource) -> Mapping[str, object]:
    from .offline import assess
    return _freeze(assess(source))


def simulate_annual_accounts_offline(source: AnnualAccountsOfflineSource) -> AnnualAccountsOfflineSimulation:
    from .offline import simulate
    return simulate(source)


@dataclass(frozen=True, slots=True)
class AnnualAccountsEvidenceInput:
    """Untrusted TT02 document plus caller identity supplied by the workflow.

    The workflow supplies its clock and authenticates the actor. This pure
    projection performs neither authorization nor authority classification.
    """
    company_id: str
    expected_organization_number: str
    evidence: object
    recorded_by: str
    recorded_at: str
    evidence_url: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, 'evidence', _freeze(self.evidence))


@dataclass(frozen=True, slots=True)
class AnnualAccountsEvidenceProjection:
    company_id: str
    obligation: str
    environment: str
    status: str
    test_reference: str
    feedback_summary: str
    receipt_reference: str
    archive_reference: str
    evidence_url: str | None
    payload_hash: str
    recorded_by: str
    recorded_at: str


def import_annual_accounts_evidence(input: AnnualAccountsEvidenceInput) -> AnnualAccountsEvidenceProjection:
    from .evidence import project
    return project(input)


__all__ = [
    'AnnualAccountsSource', 'AnnualAccountsCandidate', 'AnnualAccountsRenderInput',
    'AnnualAccountsDocuments', 'AnnualAccountsReadinessIssue', 'AnnualAccountsCorporateReadiness',
    'build_annual_accounts', 'render_annual_accounts', 'assess_annual_accounts_readiness',
    'AnnualAccountsOfflineSource', 'AnnualAccountsOfflineSimulation',
    'build_annual_accounts_offline_payload', 'assess_annual_accounts_offline', 'simulate_annual_accounts_offline',
    'AnnualAccountsEvidenceInput', 'AnnualAccountsEvidenceProjection', 'import_annual_accounts_evidence',
]
