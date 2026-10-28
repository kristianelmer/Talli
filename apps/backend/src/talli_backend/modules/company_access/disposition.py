"""Company-wide authorization for finite, independently reviewed disposition.

Facts must come from verified owner/operator sessions and owning capability reads;
these models are not HTTP requests or authority derived from caller-supplied JWTs.
"""
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class _Immutable(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class DispositionSession(_Immutable):
    subject: UUID
    session_id: UUID
    role: Literal["owner", "reviewer"]
    company_id: UUID
    mfa_at: AwareDatetime
    revoked: bool = False


class DispositionRecord(_Immutable):
    owner: str = Field(min_length=1, max_length=80)
    record_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    generation: str = Field(min_length=1, max_length=128)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["erase", "retain"]
    retention_until: AwareDatetime
    hold_basis: str | None = Field(default=None, min_length=1, max_length=500)
    hold_until: AwareDatetime | None = None


class DispositionExport(_Immutable):
    income_year: int = Field(ge=2000, le=2100)
    receipt_id: UUID
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    complete: bool


class CompanyDispositionPlan(_Immutable):
    operation_id: UUID
    company_id: UUID
    choice: Literal["return", "delete"] | None
    years: tuple[int, ...]
    generation: str = Field(min_length=1, max_length=128)
    records: tuple[DispositionRecord, ...] = Field(min_length=1, max_length=10000)
    inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    support_case_id: UUID

    def inventory_digest(self) -> str:
        # Policy and adapters agree on exact immutable selectors, not DB OIDs.
        return sha256(self.model_dump_json(include={"company_id", "years", "generation", "records"}).encode()).hexdigest()


class DispositionAuthorizationFacts(_Immutable):
    company_id: UUID
    all_company_years: tuple[int, ...]
    current_generation: str
    current_inventory_sha256: str
    paid_access_expires_at: AwareDatetime | None
    read_export_until: AwareDatetime | None
    exports: tuple[DispositionExport, ...]
    owner: DispositionSession
    reviewer: DispositionSession
    support_case_id: UUID
    review_plan_sha256: str
    inventory_complete: bool


class AuthorizedCompanyDisposition(_Immutable):
    plan: CompanyDispositionPlan
    facts: DispositionAuthorizationFacts
    policy_version: Literal["company-disposition-v1"] = "company-disposition-v1"
    authorized_at: AwareDatetime
    owner_subject: UUID
    reviewer_subject: UUID
    authorization_sha256: str


def authorize_company_disposition(plan: CompanyDispositionPlan, facts: DispositionAuthorizationFacts,
                                  *, now: datetime) -> AuthorizedCompanyDisposition:
    """No selected-year cancellation marker or blanket accounting hold grants erase authority."""
    def require(value: bool, reason: str) -> None:
        if not value:
            raise ValueError(reason)
    require(now.tzinfo is not None and now.utcoffset() is not None, "disposition_clock_invalid")
    require(plan.choice == "delete", "disposition_customer_choice_required")
    require(plan.company_id == facts.company_id, "disposition_company_mismatch")
    require(bool(plan.years) and plan.years == tuple(sorted(set(plan.years)))
            and plan.years == facts.all_company_years, "disposition_company_years_incomplete")
    require(facts.inventory_complete and plan.inventory_digest() == plan.inventory_sha256
            == facts.current_inventory_sha256 and plan.generation == facts.current_generation,
            "disposition_inventory_changed")
    require(len({(r.owner, r.record_id) for r in plan.records}) == len(plan.records)
            and all(r.income_year in plan.years for r in plan.records), "disposition_inventory_invalid")
    require(facts.paid_access_expires_at is not None and facts.read_export_until is not None,
            "disposition_billing_expiry_unavailable")
    require(facts.read_export_until >= facts.paid_access_expires_at + timedelta(days=90)
            and now >= facts.read_export_until, "disposition_read_export_period_active")
    require(len(facts.exports) == len(plan.years)
            and tuple(sorted(e.income_year for e in facts.exports)) == plan.years
            and all(e.complete and e.inventory_sha256 == plan.inventory_sha256 for e in facts.exports),
            "disposition_complete_export_required")
    for session, role in ((facts.owner, "owner"), (facts.reviewer, "reviewer")):
        require(session.company_id == plan.company_id and session.role == role and not session.revoked
                and timedelta(0) <= now - session.mfa_at <= timedelta(minutes=5), "disposition_fresh_session_required")
    require(facts.owner.subject != facts.reviewer.subject and facts.owner.session_id != facts.reviewer.session_id, "disposition_independent_review_required")
    require(facts.support_case_id == plan.support_case_id
            and facts.review_plan_sha256 == sha256(plan.model_dump_json().encode()).hexdigest(),
            "disposition_review_changed")
    for record in plan.records:
        require((record.hold_basis is None) == (record.hold_until is None), "disposition_unbounded_hold")
        require(record.hold_basis is None or bool(record.hold_basis.strip()), "disposition_hold_basis_required")
        if record.action == "erase":
            require(record.retention_until <= now and (record.hold_until is None or record.hold_until <= now),
                    "disposition_active_retention_or_hold")
        else:
            require(record.retention_until > now or (record.hold_until is not None and record.hold_until > now),
                    "disposition_retention_basis_required")
    body = facts.model_dump_json().encode() + now.isoformat().encode()
    return AuthorizedCompanyDisposition(plan=plan, facts=facts, authorized_at=now, owner_subject=facts.owner.subject,
        reviewer_subject=facts.reviewer.subject, authorization_sha256=sha256(body).hexdigest())
