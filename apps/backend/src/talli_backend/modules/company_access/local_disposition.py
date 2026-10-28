"""Versioned Documents-only local approval; never whole-company authority.

The native controller resolves these observations. This is not an HTTP request,
nor a replacement for the company-wide completeness/export policy.
"""
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .disposition import CompanyDispositionPlan, DispositionSession


class LocalDocumentsFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    scope: Literal['local-documents-only'] = 'local-documents-only'
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_generations: tuple[tuple[int, int], ...]
    paid_expires_at: AwareDatetime
    recorded_export_until: AwareDatetime
    export_until: AwareDatetime
    documents_export_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    owner: DispositionSession
    reviewer: DispositionSession
    review_plan_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    support_case_id: UUID


class AuthorizedLocalDocumentsDisposition(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)
    policy_version: Literal['local-documents-disposition-v1'] = 'local-documents-disposition-v1'
    plan: CompanyDispositionPlan
    facts: LocalDocumentsFacts
    authorized_at: AwareDatetime
    owner_subject: UUID
    reviewer_subject: UUID
    authorization_sha256: str


def authorize_local_documents_disposition(plan: CompanyDispositionPlan, facts: LocalDocumentsFacts,
                                         *, now: datetime) -> AuthorizedLocalDocumentsDisposition:
    """Revalidatable local journal policy, consuming controller observations only."""
    def require(value, reason):
        if not value:
            raise ValueError(reason)
    require(now.tzinfo is not None, 'local_disposition_clock')
    require(plan.choice == 'delete' and plan.inventory_digest() == plan.inventory_sha256,
            'local_disposition_plan')
    require(all(r.owner == 'documents' for r in plan.records)
            and len({r.record_id for r in plan.records}) == len(plan.records)
            and plan.years == tuple(sorted({r.income_year for r in plan.records})),
            'local_disposition_scope')
    require(facts.export_until == max(facts.recorded_export_until, facts.paid_expires_at + timedelta(days=90))
            and now >= facts.export_until, 'local_disposition_export_period_active')
    require(facts.review_plan_sha256 == sha256(plan.model_dump_json().encode()).hexdigest()
            and facts.support_case_id == plan.support_case_id, 'local_disposition_review_changed')
    for session, role in ((facts.owner, 'owner'), (facts.reviewer, 'reviewer')):
        require(session.company_id == plan.company_id and session.role == role and not session.revoked
                and timedelta(0) <= now-session.mfa_at <= timedelta(minutes=5), 'local_disposition_fresh_session')
    require(facts.owner.subject != facts.reviewer.subject and facts.owner.session_id != facts.reviewer.session_id,
            'local_disposition_independent_review')
    require(bool(facts.source_generations) and facts.source_generations == tuple(sorted(set(facts.source_generations)))
            and all(y in dict(facts.source_generations) for y in plan.years), 'local_disposition_generation')
    for record in plan.records:
        require(record.hold_basis is None and record.hold_until is None, 'local_disposition_legal_source_unavailable')
        require((record.action == 'erase' and record.retention_until <= now)
                or (record.action == 'retain' and record.retention_until > now), 'local_disposition_retention')
    commitment = sha256((facts.model_dump_json()+now.isoformat()).encode()).hexdigest()
    return AuthorizedLocalDocumentsDisposition(plan=plan, facts=facts, authorized_at=now,
        owner_subject=facts.owner.subject, reviewer_subject=facts.reviewer.subject, authorization_sha256=commitment)
