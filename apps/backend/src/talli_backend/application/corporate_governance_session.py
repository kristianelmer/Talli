"""Request-scoped authentication and transaction ports for governance workflows."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol
from talli_backend.application.corporate_register_evidence import VerifiedCorporateRegisterEvidence

from talli_backend.application.annual_data_compatibility import LegacyAnnualDataView
from talli_backend.application.new_year_opening import (
    OpeningSnapshotCursor,
    OpeningSnapshotPage,
)
from talli_backend.modules.banking.public import BankTransactionClaimPersistence
from talli_backend.modules.corporate_governance.public import (
    CorporateGovernancePersistence,
    PersistedCompanyFacts,
)
from talli_backend.modules.ledger.public import LedgerPersistence
from talli_backend.shared.kernel import ActorId, CompanyId, CorrelationId, IncomeYear


class CorporateGovernanceAuthenticationError(Exception):
    """The caller could not be bound to a verified governance session."""


class CorporateGovernanceWorkflowTransaction(
    CorporateGovernancePersistence,
    LedgerPersistence,
    BankTransactionClaimPersistence,
    Protocol,
):
    @property
    def actor_id(self) -> ActorId: ...

    async def assert_register_evidence(self, evidence: VerifiedCorporateRegisterEvidence) -> None: ...

    async def list_opening_snapshots(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: OpeningSnapshotCursor | None,
        limit: int,
    ) -> OpeningSnapshotPage: ...

    async def list_annual_data_compatibility(
        self,
        *,
        company_id: CompanyId,
        income_year: IncomeYear,
    ) -> tuple[LegacyAnnualDataView, ...]: ...

    async def read_company_facts(
        self,
        company_id: CompanyId,
    ) -> PersistedCompanyFacts: ...


class AuthenticatedCorporateGovernanceSession(Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    def transaction(
        self,
        *, guarded_company_id: CompanyId | None = None,
    ) -> AbstractAsyncContextManager[CorporateGovernanceWorkflowTransaction]: ...


class CorporateGovernanceSessionFactory(Protocol):
    async def session(
        self,
        access_token: str,
    ) -> AuthenticatedCorporateGovernanceSession: ...


__all__ = [
    "AuthenticatedCorporateGovernanceSession",
    "CorporateGovernanceAuthenticationError",
    "CorporateGovernanceSessionFactory",
    "CorporateGovernanceWorkflowTransaction",
]
