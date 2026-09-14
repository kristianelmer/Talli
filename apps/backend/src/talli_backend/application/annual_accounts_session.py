"""Request-bound Accounts persistence; the public port owns its row projections."""
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsEvidencePersistence, AnnualAccountsWorkspacePersistence, AnnualAccountsPreparationPersistence
from talli_backend.shared.kernel import ActorId


class AnnualAccountsTransaction(AnnualAccountsEvidencePersistence, AnnualAccountsWorkspacePersistence, AnnualAccountsPreparationPersistence, Protocol):
    @property
    def actor_id(self) -> ActorId: ...


class AnnualAccountsSession(Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    def transaction(self, *, snapshot: bool = False) -> AbstractAsyncContextManager[AnnualAccountsTransaction]: ...


class AnnualAccountsSessionFactory(Protocol):
    async def session(self, access_token: str) -> AnnualAccountsSession: ...
