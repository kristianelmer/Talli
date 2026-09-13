"""Atomic, request-bound ports for Company Tax capture."""
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from talli_backend.modules.banking.public import TaxSettlementBankingPersistence
from talli_backend.modules.company_tax_filing.public import TaxSettlementPersistence, TaxSettlementArchivePersistence, CompanyTaxWorkspacePersistence
from talli_backend.modules.documents.public import DocumentBindingPersistence
from talli_backend.modules.ledger.public import LedgerPersistence
from talli_backend.shared.kernel import ActorId


class CompanyTaxTransaction(
    TaxSettlementPersistence, TaxSettlementArchivePersistence, CompanyTaxWorkspacePersistence, LedgerPersistence, TaxSettlementBankingPersistence,
    DocumentBindingPersistence, Protocol,
):
    @property
    def actor_id(self) -> ActorId: ...


class CompanyTaxSession(Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    def transaction(self) -> AbstractAsyncContextManager[CompanyTaxTransaction]: ...


class CompanyTaxSessionFactory(Protocol):
    async def session(self, access_token: str) -> CompanyTaxSession: ...
