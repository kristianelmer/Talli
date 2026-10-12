"""Separate historical read and CompanyAccess-authorized standalone download."""
from collections.abc import Iterator
from typing import Protocol

from talli_backend.application.shareholder_register_company_test_retention_stream import stream_company_test_retention
from talli_backend.modules.company_access.public import CompanyAccessService
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, CompanyId


class CompanyTestRetentionSession(rf.Rf1086CompanyTestRetentionPersistence, Protocol):
    @property
    def actor_id(self) -> ActorId: ...


class CompanyTestRetentionSessionFactory(Protocol):
    async def session(self, access_token: str) -> CompanyTestRetentionSession: ...


class ShareholderRegisterCompanyTestRetentionHttp:
    def __init__(self, sessions: CompanyTestRetentionSessionFactory, company_access: CompanyAccessService):
        self._sessions, self._company_access = sessions, company_access

    async def read(self, access_token: str, *, company_id: CompanyId) -> rf.Rf1086CompanyTestRetentionSnapshot:
        session = await self._sessions.session(access_token)
        snapshot = await session.read_company_test_retention(rf.Rf1086CompanyTestRetentionQuery(company_id, session.actor_id))
        rf.serialize_rf1086_company_test_retention(snapshot)
        if snapshot.company_id != company_id:
            raise rf.ShareholderRegisterFilingError.unavailable()
        return snapshot

    async def download(self, access_token: str, *, company_id: CompanyId) -> Iterator[bytes]:
        session = await self._sessions.session(access_token)

        async def authorize():
            scope = await self._company_access.authorize_archive_download_step_up(access_token, company_id=str(company_id))
            if str(scope.company_id) != str(company_id) or str(scope.subject_id) != str(session.actor_id.subject):
                raise rf.ShareholderRegisterFilingError.forbidden()

        await authorize()
        snapshot = await session.read_company_test_retention(rf.Rf1086CompanyTestRetentionQuery(company_id, session.actor_id))
        if snapshot.company_id != company_id:
            raise rf.ShareholderRegisterFilingError.unavailable()
        content = stream_company_test_retention(snapshot)
        try:
            first = next(content)  # Entire RF capture validates before HTTP headers.
            await authorize()     # Current Auth/member/MFA after acquisition and priming.
        except BaseException:
            content.close()
            raise

        def completed_frames():
            try:
                yield first
                yield from content
            finally:
                content.close()

        return completed_frames()
