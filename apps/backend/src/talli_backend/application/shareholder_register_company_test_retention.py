"""Read RF company test history under the current authenticated member."""
from talli_backend.modules.shareholder_register_filing import public as rf


class ShareholderRegisterCompanyTestRetention:
    def __init__(self, sessions):
        self._sessions = sessions

    async def read(self, access_token, *, company_id):
        session = await self._sessions.session(access_token)
        return await session.read_company_test_retention(
            rf.Rf1086CompanyTestRetentionQuery(company_id, session.actor_id))
