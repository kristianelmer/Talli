"""Backend-system technical operator records; filing owners still decide release."""
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from talli_backend.shared.kernel import ActorId, ErrorCategory, Timestamp, UserId


class LaunchSignoffKey(StrEnum):
    PUBLIC_COPY = 'launch_legal_name_public_copy'
    LEGAL_POLICY = 'legal_policy_pack'
    SECURITY_RESTORE = 'security_restore'
    BILLING_REFUND = 'billing_refund'
    RF1086 = 'rf1086_authority'
    ANNUAL_ACCOUNTS = 'annual_accounts_authority'
    TAX_RETURN = 'tax_return_authority'
    SUPPORT_ROLLBACK = 'support_rollback'
    FOUNDER_GO_LIVE = 'founder_production_go_live'


class LaunchSignoffStatus(StrEnum):
    APPROVED = 'approved'
    REJECTED = 'rejected'
    PENDING = 'pending'


class LaunchSignoffError(Exception):
    def __init__(self, code: str, category: ErrorCategory):
        self.code = code
        self.category = category
        super().__init__(code)


class LaunchSignoffAuthenticationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RecordLaunchSignoff:
    key: LaunchSignoffKey
    status: LaunchSignoffStatus
    reviewer: str
    reviewed_at: datetime
    evidence_link: str
    decision: str

    def normalized(self, now: datetime) -> 'RecordLaunchSignoff':
        if (not isinstance(self.key, LaunchSignoffKey) or not isinstance(self.status, LaunchSignoffStatus)
                or self.reviewed_at.tzinfo is None or self.reviewed_at > now
                or any(not isinstance(v, str) for v in (self.reviewer, self.evidence_link, self.decision))):
            raise LaunchSignoffError('launch_signoff_invalid', ErrorCategory.INVALID_INPUT)
        values = tuple(v.strip() for v in (self.reviewer, self.evidence_link, self.decision))
        if self.status is LaunchSignoffStatus.APPROVED and not all(values):
            raise LaunchSignoffError('launch_signoff_invalid', ErrorCategory.INVALID_INPUT)
        return RecordLaunchSignoff(self.key, self.status, values[0], self.reviewed_at, values[1], values[2])


@dataclass(frozen=True, slots=True)
class LaunchSignoffRecord:
    key: LaunchSignoffKey
    status: LaunchSignoffStatus
    reviewer: str
    reviewed_at: Timestamp
    evidence_link: str
    decision: str
    recorded_by: UserId
    updated_at: Timestamp


class LaunchSignoffSession(Protocol):
    actor_id: ActorId
    async def authorize_operator(self, *, admin: bool) -> None: ...
    async def list_signoffs(self) -> tuple[LaunchSignoffRecord, ...]: ...
    async def record_signoff(self, command: RecordLaunchSignoff) -> LaunchSignoffRecord: ...


class LaunchSignoffSessionFactory(Protocol):
    async def session(self, access_token: str) -> LaunchSignoffSession: ...


class LaunchSignoffWorkflow:
    def __init__(self, session: LaunchSignoffSession):
        self._session = session

    async def list_signoffs(self):
        await self._session.authorize_operator(admin=False)
        return await self._session.list_signoffs()

    async def record_signoff(self, command: RecordLaunchSignoff):
        await self._session.authorize_operator(admin=True)
        command = command.normalized(datetime.now(UTC))
        result = await self._session.record_signoff(command)
        if (result.key != command.key or result.status != command.status
            or result.reviewer != command.reviewer or result.evidence_link != command.evidence_link
            or result.decision != command.decision or result.reviewed_at.value != command.reviewed_at
            or result.recorded_by != self._session.actor_id.subject):
            raise LaunchSignoffError('launch_signoff_unavailable', ErrorCategory.DEPENDENCY_UNAVAILABLE)
        return result
