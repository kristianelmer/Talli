"""Real transactions fence delayed original requests; no provider authority."""
import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import json
from uuid import uuid4

import psycopg
import pytest

from test_annual_purchase_basis_runtime import DATABASE_URL, ROOT, admitted, insert, scoped, test_role_authority
from test_annual_checkout_runtime import setup, session, candidate, counts, observation
from talli_backend.adapters.postgres_annual_checkout import PostgresAnnualCheckoutSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.billing.annual_service import AnnualCheckoutService, checkout_fingerprint
from talli_backend.modules.billing.public import BillingError, BillingErrorCode, AnnualProviderStatus
from talli_backend.shared.kernel import ActorId, ActorKind, UserId, IdempotencyKey, IncomeYear

pytestmark = pytest.mark.billing_database
MIGRATION = '20260906221800_annual_checkout_withdrawals.sql'
TABLE = 'billing.annual_checkout_withdrawals'


def withdraw(setup, command=None, **options):
    value = command or setup[5]
    return session(setup, **options).withdraw_checkout_request(value, checkout_fingerprint(value))


def receipts(setup):
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        return connection.execute('select to_jsonb(w) from ' + TABLE + ' w where company_id=%s',
                                  (str(setup[2].company_id),)).fetchall()


class OldWriter(PostgresAnnualCheckoutSession):
    """Original claim algorithm: company/year lock, no Python withdrawal lookup."""
    async def _lock_original_key(self, *args):
        pass

    async def _reject_withdrawal(self, *args):
        pass


def receipt_fields(setup, command=None):
    value = command or setup[5]
    return dict(company_id=str(value.company_id),income_year=value.income_year.value,
                requested_by=str(value.actor_id.subject),idempotency_key=str(value.idempotency_key),
                request_fingerprint=checkout_fingerprint(value),offer_version=value.offer_version,
                terms_digest=value.terms_digest,purchase_accepted=value.purchase_accepted,
                recurring_consent=value.recurring_consent,consent_version=value.consent_version)


def test_concurrent_identical_withdrawals_replay_one_immutable_receipt(setup):
    async def run():
        return await asyncio.gather(*(withdraw(setup) for _ in range(12)))
    outcomes = asyncio.run(run())
    assert all(value == outcomes[0] for value in outcomes)
    assert outcomes[0].purchase_id is None and len(receipts(setup)) == 1
    assert counts(setup) == (0, 0)


def test_original_start_paused_in_sources_cannot_claim_after_withdrawal(setup):
    class Provider:
        provider = 'vipps-mt'
        account_reference = 'synthetic'
        production_enabled = False
        async def execute(self, intent):
            pytest.fail('withdrawn request reached provider')
        reconcile = execute
    service = AnnualCheckoutService(session(setup), Provider(), return_url='https://example.test', management_url='https://example.test')
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def sources():
            entered.set()
            await release.wait()
            return setup[4]
        task = asyncio.create_task(service.start_checkout(setup[5], sources))
        await entered.wait()
        result = await withdraw(setup)
        release.set()
        with pytest.raises(BillingError) as denied:
            await task
        assert denied.value.code == BillingErrorCode.CHECKOUT_REQUEST_WITHDRAWN
        return result
    assert asyncio.run(run()).withdrawal_id is not None
    assert counts(setup) == (0, 0) and len(receipts(setup)) == 1


@pytest.mark.parametrize('change', ['year','terms','recurring','offer','consent'])
def test_changed_original_request_races_cannot_produce_contradictory_success(setup, change):
    original = setup[5]
    changes = {'year':dict(income_year=IncomeYear(2025)), 'terms':dict(terms_digest='d'*64),
               'recurring':dict(recurring_consent=False), 'offer':dict(offer_version='obsolete'),
               'consent':dict(consent_version='obsolete')}
    changed = replace(original, **changes[change])
    async def run():
        return await asyncio.gather(session(setup).claim_checkout(candidate(setup), setup[4]),
                                    withdraw(setup, changed), return_exceptions=True)
    result = asyncio.run(run())
    assert sum(not isinstance(value, Exception) for value in result) == 1, result
    errors = [value for value in result if isinstance(value, Exception)]
    assert all(isinstance(value, BillingError) and value.code == BillingErrorCode.IDEMPOTENCY_KEY_REUSED for value in errors)
    assert (counts(setup),len(receipts(setup))) in [((1,1),0),((0,0),1)]


@pytest.mark.parametrize('status', ['pending','paid','failed','refunded'])
def test_existing_original_purchase_is_returned_in_all_states_without_new_sale_checks(setup,status):
    store = session(setup)
    checkout = asyncio.run(store.claim_checkout(candidate(setup), setup[4])).checkout
    if status != 'pending':
        checkout = asyncio.run(store.settle_checkout(checkout, observation(
            checkout, status=AnnualProviderStatus.FAILED if status == 'failed' else AnnualProviderStatus.CONFIRMED,
            captured=0 if status == 'failed' else 149000, refunded=149000 if status == 'refunded' else 0,
        )))
    before = checkout
    result = asyncio.run(withdraw(setup,current=False))
    assert result.purchase_id == checkout.purchase_id and result.withdrawal_id is None
    assert asyncio.run(store.load_checkout(checkout.offer.company_id,checkout.purchase_id)) == before
    assert receipts(setup) == []
    with psycopg.connect(DATABASE_URL) as connection, pytest.raises(psycopg.errors.UniqueViolation):
        scoped(connection, setup[1].subject)
        insert(connection,TABLE,receipt_fields(setup))


def test_old_writer_cannot_bypass_withdrawal_or_leave_partial_purchase(setup):
    asyncio.run(withdraw(setup))
    with pytest.raises(BillingError) as denied:
        asyncio.run(session(setup,session_type=OldWriter).claim_checkout(candidate(setup),setup[4]))
    assert denied.value.code == BillingErrorCode.DEPENDENCY_UNAVAILABLE
    assert counts(setup) == (0,0)
    replacement = candidate(setup,key=IdempotencyKey(str(uuid4())))
    assert asyncio.run(session(setup).claim_checkout(replacement,setup[4])).newly_claimed
    with pytest.raises(BillingError) as denied:
        asyncio.run(session(setup).claim_checkout(candidate(setup),setup[4]))
    assert denied.value.code == BillingErrorCode.CHECKOUT_REQUEST_WITHDRAWN


def test_lost_ack_replays_commit_and_deferred_commit_failure_returns_no_receipt(setup):
    class LostAck(PostgresAnnualCheckoutSession):
        async def _transaction(self, work):
            await super()._transaction(work)
            raise BillingError.unavailable()
    with pytest.raises(BillingError):
        asyncio.run(withdraw(setup,session_type=LostAck))
    before = receipts(setup)
    assert len(before) == 1
    assert str(asyncio.run(withdraw(setup)).withdrawal_id) == before[0][0]['id']
    assert receipts(setup) == before
    another = replace(setup[5],idempotency_key=IdempotencyKey(str(uuid4())))
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute('set local role billing_store_owner')
        connection.execute('create constraint trigger fixture_withdrawal_commit_failure after insert on ' + TABLE +
                           ' deferrable initially deferred for each row execute function billing.guard_annual_evidence_v1()')
    try:
        with pytest.raises(BillingError) as error:
            asyncio.run(withdraw(setup,another))
        assert error.value.code == BillingErrorCode.DEPENDENCY_UNAVAILABLE
        assert receipts(setup) == before
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute('set local role billing_store_owner')
            connection.execute('drop trigger fixture_withdrawal_commit_failure on ' + TABLE)
    assert asyncio.run(withdraw(setup,another)).withdrawal_id is not None


@pytest.mark.parametrize('lock_kind',['key','year'])
@pytest.mark.parametrize('change',['revoked','expired'])
@pytest.mark.parametrize('replay',[False,True])
def test_adapter_reauthorizes_after_each_lock_for_new_and_replayed_withdrawals(setup,lock_kind,change,replay):
    if replay:
        asyncio.run(withdraw(setup))
    async def run():
        store = session(setup)
        if change == 'expired':
            claims = json.loads(store._verified.claims_json)
            claims['amr'][0]['timestamp'] = datetime.now(UTC).timestamp()-899.5
            store._verified = _VerifiedActor(store.actor_id,json.dumps(claims))
        key = (f'annual-checkout-key|{setup[5].idempotency_key}' if lock_kind == 'key'
               else f'annual-checkout|{setup[2].company_id}|2026')
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as holder:
            await holder.execute('select pg_advisory_xact_lock(hashtextextended(%s,192))',(key,))
            task = asyncio.create_task(store.withdraw_checkout_request(setup[5],checkout_fingerprint(setup[5])))
            async with await psycopg.AsyncConnection.connect(DATABASE_URL,autocommit=True) as observer:
                for _ in range(100):
                    row = await (await observer.execute("select count(*) from pg_stat_activity where %s = any(pg_blocking_pids(pid))",(holder.info.backend_pid,))).fetchone()
                    if row[0]: break
                    await asyncio.sleep(.01)
                else: pytest.fail('withdrawal never waited')
                if change == 'revoked':
                    await observer.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',
                                           (str(setup[2].company_id),str(setup[1].subject)))
                    await observer.commit()
                else:
                    await asyncio.sleep(.65)
            await holder.commit()
        with pytest.raises(BillingError) as denied:
            await task
        assert denied.value.code == (BillingErrorCode.FORBIDDEN if change == 'revoked' else BillingErrorCode.STEP_UP_REQUIRED)
    asyncio.run(run())
    assert counts(setup) == (0,0)


@pytest.mark.parametrize('lock_kind',['key','year'])
def test_direct_insert_never_waits_with_a_stale_mfa_statement_clock(setup,lock_kind):
    key = (f'annual-checkout-key|{setup[5].idempotency_key}' if lock_kind == 'key'
           else f'annual-checkout|{setup[2].company_id}|2026')
    with psycopg.connect(DATABASE_URL) as holder:
        holder.execute('select pg_advisory_xact_lock(hashtextextended(%s,192))',(key,))
        with psycopg.connect(DATABASE_URL) as contender, pytest.raises(psycopg.errors.LockNotAvailable):
            scoped(contender,setup[1].subject)
            contender.execute("set local statement_timeout='250ms'")
            insert(contender,TABLE,receipt_fields(setup))
    assert receipts(setup) == []
    assert asyncio.run(withdraw(setup)).withdrawal_id is not None


def test_rls_private_fields_mutation_and_unrelated_user_foreign_key_check(setup):
    result = asyncio.run(withdraw(setup))
    for role in ('anon','authenticated','service_role','billing_executor'):
        with psycopg.connect(DATABASE_URL) as connection:
            assert not connection.execute("select has_table_privilege(%s,%s,'SELECT')",(role,TABLE)).fetchone()[0]
            assert not connection.execute("select has_any_column_privilege(%s,%s,'INSERT')",(role,TABLE)).fetchone()[0]
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection,setup[1].subject)
        assert connection.execute('update '+TABLE+' set id=id where id=%s',(str(result.withdrawal_id),)).rowcount == 0
        for column in ('id','requested_at'):
            assert not connection.execute("select has_column_privilege(current_user,%s,%s,'INSERT')",(TABLE,column)).fetchone()[0]
    with psycopg.connect(DATABASE_URL) as connection, pytest.raises(psycopg.errors.InsufficientPrivilege):
        scoped(connection,setup[1].subject)
        connection.execute('delete from '+TABLE+' where id=%s',(str(result.withdrawal_id),))
    identity = uuid4()
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection,'auth.users',{'id':identity,'email':f'{identity}@example.test'})
        connection.execute('delete from auth.users where id=%s',(identity,))


def test_withdrawal_cannot_import_another_owners_acceptance_or_expose_another_tenant(setup,request):
    original = asyncio.run(withdraw(setup))
    identity = uuid4()
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection,'auth.users',{'id':identity,'email':f'{identity}@example.test'})
        insert(connection,'public.company_memberships',dict(company_id=str(setup[2].company_id),user_id=identity,
                                                          role='owner',accepted_at=datetime.now(UTC)))
    actor = ActorId(ActorKind.USER,UserId(str(identity)))
    with pytest.raises(BillingError) as denied:
        asyncio.run(withdraw(setup,actor=actor))
    assert denied.value.code == BillingErrorCode.FORBIDDEN
    with pytest.raises(BillingError) as conflict:
        asyncio.run(withdraw(setup,replace(setup[5],actor_id=actor),actor=actor))
    assert conflict.value.code == BillingErrorCode.IDEMPOTENCY_KEY_REUSED
    other = globals()['setup'].__wrapped__(admitted.__wrapped__(request))
    guessed = replace(other[5],idempotency_key=setup[5].idempotency_key)
    with pytest.raises(BillingError) as conflict:
        asyncio.run(withdraw(other,guessed))
    assert conflict.value.code == BillingErrorCode.IDEMPOTENCY_KEY_REUSED
    assert receipts(other) == [] and counts(other) == (0,0)
    with pytest.raises(BillingError) as stale:
        asyncio.run(withdraw(setup,fresh=False))
    assert stale.value.code == BillingErrorCode.STEP_UP_REQUIRED
    assert asyncio.run(withdraw(setup)) == original


def test_immutable_trigger_still_denies_a_mutation_if_a_policy_is_accidentally_broadened(setup):
    result = asyncio.run(withdraw(setup))
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute('set local role billing_store_owner')
        connection.execute('create policy fixture_withdrawal_update on '+TABLE+' for update to billing_store_owner using (true) with check (true)')
    try:
        with psycopg.connect(DATABASE_URL) as connection, pytest.raises(psycopg.errors.RaiseException,match='immutable'):
            scoped(connection,setup[1].subject)
            connection.execute('update '+TABLE+' set id=id where id=%s',(str(result.withdrawal_id),))
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute('set local role billing_store_owner')
            connection.execute('drop policy fixture_withdrawal_update on '+TABLE)


def test_old_year_first_writer_fails_promptly_while_new_withdrawal_can_commit(setup):
    async def run():
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as old:
            await old.execute('set local role billing_store_owner')
            verified = session(setup)._verified
            await old.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",
                              (str(setup[1].subject),verified.claims_json))
            await old.execute('select pg_advisory_xact_lock(hashtextextended(%s,192))',
                              (f'annual-checkout|{setup[2].company_id}|2026',))
            task = asyncio.create_task(withdraw(setup))
            async with await psycopg.AsyncConnection.connect(DATABASE_URL,autocommit=True) as observer:
                for _ in range(70):
                    row = await (await observer.execute('select count(*) from pg_stat_activity where %s=any(pg_blocking_pids(pid))',
                                                       (old.info.backend_pid,))).fetchone()
                    if row[0]: break
                    await asyncio.sleep(.01)
                else: pytest.fail('new withdrawal did not reach year lock')
            await old.execute("set local statement_timeout='250ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                await old.execute("""insert into billing.annual_operations
                    (id,purchase_id,company_id,income_year,created_by,idempotency_key,request_fingerprint,operation,amount_minor,intent)
                    values (%s,%s,%s,2026,%s,%s,%s,'checkout',149000,'{}'::jsonb)""",
                    (str(uuid4()),str(uuid4()),str(setup[2].company_id),str(setup[1].subject),
                     str(setup[5].idempotency_key),checkout_fingerprint(setup[5])))
            await old.rollback()
        return await task
    assert asyncio.run(run()).withdrawal_id is not None
    assert counts(setup) == (0,0) and len(receipts(setup)) == 1


def test_withdrawal_and_function_identity_survive_full_rollback_recutover_twice(setup):
    result = asyncio.run(withdraw(setup))
    original = receipts(setup)
    predecessors = ['20260905145000_annual_refund_agreement_cleanup.sql',
                    '20260905141500_annual_refund_requests.sql','20260905115700_legacy_billing_acquisition_retirement.sql',
                    '20260905103149_annual_agreement_cleanup.sql','20260905100130_annual_renewal_cancellation.sql',
                    '20260905083150_annual_billing_purchase_ledger.sql','20260905080550_annual_billing_purchase_basis.sql',
                    '20260905061339_billing_provider_reconciliation.sql','20260905010000_billing_capability.sql']
    def denied_old_claim():
        with pytest.raises(BillingError):
            asyncio.run(session(setup,session_type=OldWriter).claim_checkout(
                candidate(setup,key=IdempotencyKey(str(uuid4()))),setup[4]))
    with psycopg.connect(DATABASE_URL) as connection:
        oid = connection.execute("select 'billing.guard_annual_checkout_request_v1()'::regprocedure::oid").fetchone()[0]
    for _ in range(2):
        with psycopg.connect(DATABASE_URL,autocommit=True) as connection:
            before_role = connection.execute("select pg_has_role(current_user,'billing_store_owner','SET')").fetchone()[0]
            connection.execute((ROOT/'supabase'/'rollback'/'20260907153938_annual_checkout_observation.sql').read_text())
            connection.execute((ROOT/'supabase'/'rollback'/MIGRATION).read_text())
            assert connection.execute("select pg_has_role(current_user,'billing_store_owner','SET')").fetchone()[0] == before_role
            assert connection.execute("select 'billing_annual_retired.guard_annual_checkout_request_v1()'::regprocedure::oid").fetchone()[0] == oid
            assert connection.execute("select tgfoid from pg_trigger where tgrelid='billing.annual_operations'::regclass and tgname='annual_checkout_request_fence'").fetchone()[0] == oid
            denied_old_claim()
            for name in predecessors:
                connection.execute((ROOT/'supabase'/'rollback'/name).read_text())
            assert connection.execute("select to_regnamespace('billing')").fetchone()[0] is None
            for name in reversed(predecessors):
                connection.execute((ROOT/'supabase'/'migrations'/name).read_text())
            principal = connection.execute('select current_user').fetchone()[0]
            connection.execute(psycopg.sql.SQL('grant billing_store_owner to {}').format(psycopg.sql.Identifier(principal)))
            denied_old_claim()
            connection.execute((ROOT/'supabase'/'migrations'/MIGRATION).read_text())
            connection.execute((ROOT/'supabase'/'migrations'/'20260907153938_annual_checkout_observation.sql').read_text())
            assert connection.execute("select 'billing.guard_annual_checkout_request_v1()'::regprocedure::oid").fetchone()[0] == oid
        assert receipts(setup) == original
        assert asyncio.run(withdraw(setup)) == result
        assert counts(setup) == (0,0)
