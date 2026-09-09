"""Atomic owner transition preserving the existing request-before-pilot lock order."""

from talli_backend.modules.authority_connections.public import (
    SystemUserOwner, SystemUserRequest, SystemUserRequestStatus,
    SystemUserStateTransaction, SystemUserStateUpdate,
)
from talli_backend.modules.billing.public import (
    AuthorityFailurePilotSuspension, SuspendProductionPilotForAuthorityFailureCommand,
    SystemUserRequestReference,
)


async def record_authority_state(
    authority: SystemUserStateTransaction,
    billing: AuthorityFailurePilotSuspension,
    owner: SystemUserOwner,
    update: SystemUserStateUpdate,
) -> SystemUserRequest:
    """Both ports share one open transaction; no external I/O may run here.

    The predecessor writer locked the request, suspended linked active pilots,
    then wrote the request. Any invalid transition or late authorization loss
    rolls the complete transaction back, preserving that exact ordering.
    """
    previous = await authority.lock_request(owner, update.request_id)
    if (previous.status == SystemUserRequestStatus.ACCEPTED
        and update.status == SystemUserRequestStatus.VERIFICATION_FAILED):
        await billing.suspend_for_authority_failure(
            SuspendProductionPilotForAuthorityFailureCommand(
                owner.company_id, previous.identity.owner_id,
                SystemUserRequestReference(previous.request_id),
            )
        )
    result = await authority.apply_state(owner, update)
    await authority.assert_current_owner(owner)
    return result


__all__ = ["record_authority_state"]
