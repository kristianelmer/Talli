"""Unconfigured persistence fails with the bounded public transport category."""

import asyncio
import json
from uuid import uuid4

import pytest
import psycopg

from talli_backend.adapters.postgres_authority_connections import PostgresAuthorityConnectionsSession, _operation_database_error
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.authority_connections.public import AuthorityConnectionsError, AuthorityOperationError
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, ErrorCategory, UserId


def store():
    actor=ActorId(ActorKind.USER,UserId(str(uuid4())))
    return PostgresAuthorityConnectionsSession("",_VerifiedActor(actor,json.dumps({"sub":str(actor.subject),"role":"authenticated"})))


def test_missing_owner_database_is_sanitized_unavailable():
    session=store()
    with pytest.raises(AuthorityConnectionsError) as failure:
        asyncio.run(session.authorize_owner(CompanyId(str(uuid4())),session.actor_id,require_fresh_mfa=True))
    assert failure.value.code=="authority_connections_unavailable"
    assert failure.value.category==ErrorCategory.DEPENDENCY_UNAVAILABLE


def test_missing_operator_database_is_sanitized_unavailable():
    session=store()
    with pytest.raises(AuthorityOperationError) as failure:
        asyncio.run(session.authorize_operator(session.actor_id,require_fresh_mfa=True))
    assert failure.value.code=="authority_audit_unavailable"
    assert failure.value.category==ErrorCategory.DEPENDENCY_UNAVAILABLE


@pytest.mark.parametrize("message,category",[
    ("admin_operator_required",ErrorCategory.FORBIDDEN),
    ("authority_step_up_required",ErrorCategory.PRECONDITION_FAILED),
    ("authority_operation_invalid",ErrorCategory.INVALID_INPUT),
])
def test_database_failures_keep_authorization_and_input_transport_categories(message,category):
    failure=_operation_database_error(psycopg.errors.RaiseException(message))
    assert failure.code==message and failure.category==category


def test_session_actor_mismatch_is_forbidden_before_database_access():
    session=store()
    other=ActorId(ActorKind.USER,UserId(str(uuid4())))
    with pytest.raises(AuthorityOperationError) as failure:
        asyncio.run(session.authorize_operator(other,require_fresh_mfa=True))
    assert failure.value.code=="admin_operator_required"
    assert failure.value.category==ErrorCategory.FORBIDDEN
