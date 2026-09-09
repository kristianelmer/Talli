"""Real RLS/HTTP support reads; setup source facts and authentication are synthetic."""

import asyncio
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from test_annual_purchase_basis_runtime import DATABASE_URL, admitted, insert, scoped, test_role_authority
from test_annual_checkout_runtime import setup, session, candidate, observation, counts
from test_annual_cancellation_runtime import purchase
from test_annual_refund_runtime import paid, command, source, store, refund_observation, state
from talli_backend.adapters.postgres_annual_support import PostgresAnnualSupportReadSession
from talli_backend.adapters.postgres_annual_cleanup import PostgresAnnualCleanupSession
from talli_backend.application.billing_session import BillingAuthenticationError
from talli_backend.main import create_app
from talli_backend.modules.billing.public import (
    AnnualOperationStatus, AnnualProviderStatus, AnnualPurchaseId, AnnualSupportCaseId, AnnualSupportQuery, BillingError,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IdempotencyKey, UserId

pytestmark = pytest.mark.billing_database
PATH = '/api/v1/billing/annual/support/purchases'


def support(setup, mode='opened'):
    actor = ActorId(ActorKind.USER, UserId(str(setup[0]['outsider'])))
    case_id = uuid4()
    now = datetime.now(UTC)
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection, 'public.support_operators', {
            'user_id': actor.subject.value, 'role': 'support' if mode == 'non_admin' else 'admin',
            'active': mode != 'inactive',
        })
        grant = {
            'case_id': case_id, 'company_id': setup[0]['company'], 'operator_user_id': actor.subject.value,
            'reason': 'customer_request', 'scopes': ['profile' if mode == 'wrong_scope' else 'billing'],
            'starts_at': now+timedelta(hours=1) if mode == 'future' else now-timedelta(hours=2),
            'expires_at': now+timedelta(hours=-1 if mode == 'expired' else 2), 'granted_by': actor.subject.value,
        }
        if mode == 'revoked':
            grant |= {'revoked_at': now, 'revoked_by': actor.subject.value, 'revocation_reason': 'case_closed'}
        insert(connection, 'public.support_access_grants', grant)
        if mode != 'unopened':
            insert(connection, 'public.support_case_openings', {
                'actor_id': actor.subject.value, 'operation_id': uuid4(), 'case_id': case_id,
                'company_id': setup[0]['company'],
            })
    return AnnualSupportQuery(setup[2].company_id, AnnualSupportCaseId(str(case_id)), actor)


def reads(setup, query, *, fresh=True):
    return PostgresAnnualSupportReadSession(session(setup, actor=query.actor_id, fresh=fresh, current=False))


def http(setup, query, *, fresh=True):
    class Factory:
        async def session(self, token):
            if token != 'local-verified-admin':
                raise BillingAuthenticationError()
            return SimpleNamespace(actor_id=query.actor_id, support_reads=reads(setup, query, fresh=fresh))
    return TestClient(create_app(annual_billing_session_factory=Factory(), annual_billing_provider=object()))


def get(api, query):
    return api.get(PATH, headers={'Authorization': 'Bearer local-verified-admin'}, params={
        'companyId': str(query.company_id), 'supportCaseId': str(query.support_case_id),
        **({'beforePurchaseId': str(query.before_purchase_id)} if query.before_purchase_id else {}),
    })


def fingerprint(setup):
    # Compare exact rows before/after GET, including case openings and audit data.
    tables = ['billing.annual_purchases', 'billing.annual_operations', 'billing.annual_refund_cases',
              'billing.annual_refund_requests', 'billing.annual_cancellation_requests',
              'public.support_case_openings', 'public.audit_events']
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        from psycopg import sql
        result = []
        for table in tables:
            if table.startswith('public.'):
                connection.execute('reset role')
            result.append(connection.execute(sql.SQL("select coalesce(jsonb_agg(to_jsonb(t)),'[]') from (select * from {} where company_id=%s order by 1) t")
                          .format(sql.Identifier(*table.split('.'))), (str(setup[2].company_id),)).fetchone()[0])
        return result


def test_authorized_empty_support_http_read_never_opens_case_or_creates_evidence(setup):
    query = support(setup)
    before = fingerprint(setup)
    api = http(setup, query)
    for _ in range(2):
        response = get(api, query)
        assert response.status_code == 200
        assert response.json()['purchases'] == [] and response.json()['nextPurchaseId'] is None
        assert response.headers['cache-control'] == 'no-store'
    assert fingerprint(setup) == before


@pytest.mark.parametrize('mode', ['non_admin', 'inactive', 'unopened', 'wrong_scope', 'expired', 'future', 'revoked', 'stale_mfa', 'wrong_case', 'wrong_company', 'wrong_operator', 'owner'])
def test_annual_support_requires_current_admin_open_case_and_mfa_even_when_empty(setup, mode):
    query = support(setup, mode)
    if mode == 'wrong_case':
        query = replace(query, support_case_id=AnnualSupportCaseId(str(uuid4())))
    elif mode == 'wrong_company':
        query = replace(query, company_id=CompanyId(str(uuid4())))
    elif mode in ('wrong_operator', 'owner'):
        query = replace(query, actor_id=setup[1])
        if mode == 'wrong_operator':
            with psycopg.connect(DATABASE_URL) as connection:
                insert(connection, 'public.support_operators', {'user_id': setup[1].subject.value, 'role': 'admin', 'active': True})
    response = get(http(setup, query, fresh=mode != 'stale_mfa'), query)
    assert response.status_code == 403
    if mode == 'stale_mfa':
        assert response.json()['code'] == 'BILLING_STEP_UP_REQUIRED'
    assert counts(setup) == (0, 0)


def test_support_reports_maximum_liability_and_unknown_original_effect_without_duplicate_debt(setup, paid):
    first = command(setup, paid)
    resolution = asyncio.run(store(setup, source(paid, first)).claim_refund(first)).resolution
    asyncio.run(store(setup).settle_refund(resolution, refund_observation(resolution, AnnualProviderStatus.UNKNOWN)))
    second = command(setup, paid)
    deferred = asyncio.run(store(setup, source(paid, second)).claim_refund(second)).resolution
    assert deferred.operation is None
    query = support(setup)
    before = fingerprint(setup)
    response = get(http(setup, query), query)
    assert response.status_code == 200
    value = response.json()['purchases'][0]
    assert value['refundCaseCount'] == value['refundRequestCount'] == 2
    assert value['recordedRefundMinor'] == value['remainingRefundMinor'] == 149000
    assert value['refundOperations']['unknown'] == 1 and value['refundedMinor'] == 0
    assert value['refundInitiateBy'] == min(resolution.decision.initiate_by, deferred.decision.initiate_by).isoformat()
    assert value['cleanupStatus'] is None and value['renewalCanceledAt'] is not None
    assert not {'facts', 'sourceReference', 'provider', 'providerAccount', 'intent', 'observation', 'acceptedBasis'} & value.keys()
    assert fingerprint(setup) == before


def test_support_does_not_lose_failed_refund_or_confirm_cleanup_from_local_stop(setup, paid):
    request = command(setup, paid)
    result = asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution
    asyncio.run(store(setup).settle_refund(result, refund_observation(result, AnnualProviderStatus.FAILED)))
    query = support(setup)
    before = asyncio.run(reads(setup, query).read_support_purchases(query)).purchases[0]
    assert before.refund_operations.failed == 1 and before.remaining_refund_minor == 149000
    assert before.cleanup_status is None and before.renewal_canceled_at is not None
    cleanup = asyncio.run(PostgresAnnualCleanupSession(session(setup)).claim_agreement_cleanup(query.company_id, paid.purchase_id))
    assert cleanup is not None
    after = asyncio.run(reads(setup, query).read_support_purchases(query)).purchases[0]
    assert after.cleanup_status is AnnualOperationStatus.CREATED
    assert after.refunded_minor == 0 and after.remaining_refund_minor == 149000


def test_support_read_and_refund_settlement_observe_one_consistent_snapshot(setup, paid):
    request = command(setup, paid)
    resolution = asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution
    query = support(setup)

    async def concurrent():
        return await asyncio.gather(reads(setup, query).read_support_purchases(query),
                                    store(setup).settle_refund(resolution, refund_observation(resolution)))

    page, _ = asyncio.run(concurrent())
    value = page.purchases[0]
    assert (value.refunded_minor, value.remaining_refund_minor, value.refund_operations.created, value.refund_operations.confirmed) in (
        (0, 149000, 1, 0), (149000, 0, 0, 1),
    )
    final = asyncio.run(reads(setup, query).read_support_purchases(query)).purchases[0]
    assert final.refunded_minor == 149000 and final.remaining_refund_minor == 0 and final.refund_initiate_by is None


def test_revoked_case_cannot_replay_previously_visible_purchase(setup, paid):
    query = support(setup)
    api = http(setup, query)
    assert get(api, query).status_code == 200
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute('update public.support_access_grants set revoked_at=%s,revoked_by=%s,revocation_reason=%s where case_id=%s',
                           (datetime.now(UTC), str(query.actor_id.subject), 'case_closed', str(query.support_case_id)))
    assert get(api, query).status_code == 403


def test_support_cursor_is_company_scoped_and_stable_on_tied_history(setup, purchase, request):
    async def history():
        current = purchase
        ids = []
        for index in range(52):
            ids.append(current.purchase_id)
            await session(setup).settle_checkout(current, observation(current, status=AnnualProviderStatus.FAILED))
            if index < 51:
                proposed = candidate(setup, key=IdempotencyKey(str(uuid4())))
                proposed = replace(proposed, intent=replace(proposed.intent, created_at=purchase.intent.created_at))
                current = (await session(setup).claim_checkout(proposed, setup[4])).checkout
        return ids
    ids = asyncio.run(history())
    query = support(setup)
    first = asyncio.run(reads(setup, query).read_support_purchases(query))
    second = asyncio.run(reads(setup, query).read_support_purchases(replace(query, before_purchase_id=first.next_purchase_id)))
    assert len(first.purchases) == 50 and len(second.purchases) == 2 and second.next_purchase_id is None
    assert [row.purchase_id for row in (*first.purchases, *second.purchases)] == sorted(ids, key=str, reverse=True)
    other = globals()['setup'].__wrapped__(admitted.__wrapped__(request))
    foreign = asyncio.run(session(other).claim_checkout(candidate(other), other[4])).checkout
    for cursor in (foreign.purchase_id, AnnualPurchaseId(str(uuid4()))):
        response = get(http(setup, query), replace(query, before_purchase_id=cursor))
        assert response.status_code == 404

