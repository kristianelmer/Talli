"""The two owning ports preserve the characterized atomic effect ordering."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from talli_backend.application.authority_connections_state_workflow import record_authority_state
from talli_backend.modules.authority_connections.public import (
    AuthorityFailureCode, SystemUserIdentity, SystemUserOwner, SystemUserRequest,
    SystemUserRequestStatus as Status, SystemUserStateUpdate,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, UserId


def test_accepted_failure_preserves_request_lock_then_pilot_then_state_order():
    actor = ActorId(ActorKind.USER, UserId(str(uuid4())))
    owner = SystemUserOwner(CompanyId(str(uuid4())), actor, "930835978")
    identity = SystemUserIdentity(owner.company_id, actor.subject, owner.organization_number, "a" * 43)
    previous = SystemUserRequest(str(uuid4()), identity, Status.ACCEPTED)
    update = SystemUserStateUpdate(previous.request_id, identity, None, Status.VERIFICATION_FAILED,
                                   None, AuthorityFailureCode.NETWORK_ERROR)
    calls = []

    class Authority:
        async def lock_request(self, actual_owner, request_id):
            assert (actual_owner, request_id) == (owner, previous.request_id)
            calls.append("request_lock")
            return previous

        async def apply_state(self, actual_owner, actual_update):
            assert (actual_owner, actual_update) == (owner, update)
            calls.append("request_write")
            return replace(previous, status=Status.VERIFICATION_FAILED)

        async def assert_current_owner(self, actual_owner):
            assert actual_owner == owner
            calls.append("owner_recheck")

    class Billing:
        async def suspend_for_authority_failure(self, command):
            assert command.company_id == owner.company_id
            assert command.owner_id == actor.subject
            assert str(command.system_user_request_id) == previous.request_id
            calls.append("pilot_suspend")

    result = asyncio.run(record_authority_state(Authority(), Billing(), owner, update))
    assert result.status == Status.VERIFICATION_FAILED
    assert calls == ["request_lock", "pilot_suspend", "request_write", "owner_recheck"]


@pytest.mark.parametrize("prior,target", [
    (Status.CREATING,Status.VERIFICATION_FAILED),
    (Status.NEW,Status.VERIFICATION_FAILED),
    (Status.VERIFICATION_FAILED,Status.ACCEPTED),
    (Status.ACCEPTED,Status.ACCEPTED),
])
def test_only_existing_accepted_authorization_is_suspended(prior, target):
    actor = ActorId(ActorKind.USER, UserId(str(uuid4())))
    owner = SystemUserOwner(CompanyId(str(uuid4())), actor, "930835978")
    identity = SystemUserIdentity(owner.company_id, actor.subject, owner.organization_number, "a" * 43)
    previous = SystemUserRequest(str(uuid4()), identity, prior)
    update = SystemUserStateUpdate(previous.request_id, identity, None, target, None,
        AuthorityFailureCode.NETWORK_ERROR if target == Status.VERIFICATION_FAILED else None)

    class Authority:
        async def lock_request(self, *_): return previous
        async def apply_state(self, *_): return replace(previous, status=target)
        async def assert_current_owner(self, *_): pass

    class Billing:
        async def suspend_for_authority_failure(self, _):
            pytest.fail("unrelated state transition must not suspend or reactivate pilot authorization")

    assert asyncio.run(record_authority_state(Authority(),Billing(),owner,update)).status == target
