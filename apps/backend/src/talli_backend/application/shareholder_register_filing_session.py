"""Verified session, owned persistence and disposable provider bindings for RF."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import AsyncContextManager, Protocol

from talli_backend.application.shareholder_register_source_admission import Rf1086SourceAdmissionTransaction

from talli_backend.modules.billing.public import BillingQueries
from talli_backend.modules.company_access.public import CompanyAccessRecord
from talli_backend.modules.shareholder_register_filing.public import (
    ProductionOperationJournal, Rf1086Approval, Rf1086Connection, Rf1086PreparationPersistence,
    Rf1086MutationAuthority, Rf1086Preview, Rf1086ProductionJournal,
    Rf1086ReadOnlyAuthority, Rf1086FeedbackDiscovery, Rf1086Submission,
    Rf1086YearSourcePersistence, Rf1086RegisterObservationPersistence, Rf1086SourcePreviewPreparation, Rf1086SourceQuery,
)
from talli_backend.shared.kernel import ActorId


class ShareholderRegisterFilingAuthenticationError(Exception):
    """The bearer could not be bound to a verified current session."""


@dataclass(frozen=True, slots=True)
class Rf1086MutationBinding:
    authority: Rf1086MutationAuthority
    read_only_authority: Rf1086ReadOnlyAuthority
    discard: Callable[[], None] = field(repr=False)
    feedback_discovery: Rf1086FeedbackDiscovery


@dataclass(frozen=True, slots=True)
class Rf1086ReadOnlyBinding:
    authority: Rf1086ReadOnlyAuthority
    discard: Callable[[], None] = field(repr=False)
    feedback_discovery: Rf1086FeedbackDiscovery


class AuthenticatedShareholderRegisterFilingSession(Rf1086PreparationPersistence, Rf1086YearSourcePersistence,
        Rf1086RegisterObservationPersistence, Rf1086SourcePreviewPreparation, Protocol):
    @property
    def actor_id(self) -> ActorId: ...
    @property
    def billing(self) -> BillingQueries: ...
    def source_admission(self, query: Rf1086SourceQuery) -> AsyncContextManager[Rf1086SourceAdmissionTransaction]: ...
    def require_configuration(self) -> None: ...
    async def read_approval(self, approval_id: str) -> Rf1086Approval | None: ...
    async def read_preview(self, preview_id: str) -> Rf1086Preview | None: ...
    async def read_submission(self, submission_id: str) -> Rf1086Submission | None: ...
    async def company_record(self, company_id: str) -> CompanyAccessRecord | None: ...
    async def read_connection(self, request_id: str, company_id: str) -> Rf1086Connection | None: ...
    async def require_fresh_production_owner(self, company_id: str) -> None: ...
    async def bind_mutation_authority(self, company: CompanyAccessRecord, connection: Rf1086Connection) -> Rf1086MutationBinding: ...
    async def bind_read_only_authority(self, company: CompanyAccessRecord, connection: Rf1086Connection) -> Rf1086ReadOnlyBinding: ...
    async def begin_production_filing(self, approval_id: str) -> str: ...
    def operation_journal(self, submission_id: str) -> ProductionOperationJournal: ...
    async def claim_feedback_lease(self, submission_id: str, lease_id: str) -> bool: ...
    async def read_claimed_reference(self, submission_id: str, lease_id: str) -> str: ...
    async def read_claimed_dialog_id(self, submission_id: str, lease_id: str) -> str: ...
    async def release_feedback_lease(self, submission_id: str, lease_id: str) -> None: ...
    def feedback_journal(self, *, submission_id: str, company_id: str, income_year: int,
                         forsendelse_id: str, lease_id: str) -> Rf1086ProductionJournal: ...


class ShareholderRegisterFilingSessionFactory(Protocol):
    async def session(self, access_token: str) -> AuthenticatedShareholderRegisterFilingSession: ...


__all__ = ["AuthenticatedShareholderRegisterFilingSession", "ShareholderRegisterFilingAuthenticationError", "ShareholderRegisterFilingSessionFactory", "Rf1086MutationBinding", "Rf1086ReadOnlyBinding"]
