"""Annual claims are proved in the same disposable database as admission."""

from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from test_annual_purchase_basis_runtime import (
    DATABASE_URL, ROOT, admitted, basis, insert, scoped, test_role_authority,
)
from talli_backend.modules.billing.annual_policy import ANNUAL_TERMS, annual_offer
from talli_backend.shared.kernel import CompanyId, IncomeYear


def purchase_values(seed, accepted_basis, **changes):
    offer = annual_offer(CompanyId(str(seed["company"])), IncomeYear(2026))
    identity = uuid4()
    return {
        "id": identity, "company_id": seed["company"], "income_year": 2026,
        "accepted_by": seed["owner"], "offer_version": offer.offer_version,
        "terms_digest": offer.terms_digest, "terms_text": ANNUAL_TERMS,
        "currency": offer.currency, "gross_minor": offer.gross_minor,
        "net_minor": offer.net_minor, "vat_minor": offer.vat_minor, "vat_basis_points": offer.vat_basis_points,
        "paid_through": offer.paid_through, "export_through": offer.export_through,
        "renewal_date": offer.renewal_date, "accepted_basis": Jsonb(accepted_basis),
        "recurring_consent": True, "consent_version": offer.offer_version,
        "provider": "vipps-mt", "provider_account": "123456",
        "agreement_external_reference": f"agreement-{identity}", "charge_reference": f"charge-{identity}",
    } | changes


def operation_values(seed, purchase, **changes):
    identity = uuid4()
    return {
        "id": identity, "purchase_id": purchase["id"], "company_id": seed["company"],
        "income_year": 2026, "created_by": seed["owner"], "idempotency_key": str(identity),
        "request_fingerprint": "c" * 64, "operation": "checkout", "amount_minor": 149000,
        "intent": Jsonb({"fixture": "original-immutable-intent"}),
    } | changes


def purchased(seed):
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, seed["owner"])
        purchase = purchase_values(seed, basis(connection, seed))
        insert(connection, "billing.annual_purchases", purchase)
        operation = operation_values(seed, purchase)
        insert(connection, "billing.annual_operations", operation)
    return purchase, operation


def test_purchase_and_intent_are_durable_and_scope_offer_and_keys_cannot_change(admitted):
    purchase, operation = purchased(admitted)
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        row = connection.execute("select status, captured_minor, terms_digest from billing.annual_purchases where id=%s", (purchase["id"],)).fetchone()
        assert row == ("pending", 0, purchase["terms_digest"])
        assert connection.execute("select intent from billing.annual_operations where id=%s", (operation["id"],)).fetchone()[0] == {"fixture": "original-immutable-intent"}
        with pytest.raises(psycopg.errors.RaiseException, match="annual_evidence_is_immutable"):
            connection.execute("update billing.annual_purchases set recurring_consent=false where id=%s", (purchase["id"],))
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        with pytest.raises(psycopg.errors.RaiseException, match="annual_evidence_is_immutable"):
            connection.execute("update billing.annual_operations set request_fingerprint=repeat('d',64) where id=%s", (operation["id"],))


@pytest.mark.parametrize("role", ["authenticated", "anon", "service_role"])
def test_browser_and_service_roles_cannot_read_annual_tables(admitted, role):
    purchased(admitted)
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"], role=role)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("select * from billing.annual_purchases")


def test_other_tenant_sees_no_rows_and_cannot_forge_the_locked_basis(admitted):
    purchased(admitted)
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["outsider"])
        assert connection.execute("select count(*) from billing.annual_purchases where company_id=%s", (admitted["company"],)).fetchone()[0] == 0
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        forged = basis(connection, admitted) | {"assessment_id": str(uuid4())}
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            insert(connection, "billing.annual_purchases", purchase_values(admitted, forged))


def test_a_second_checkout_cannot_enter_while_the_original_is_unresolved(admitted):
    with psycopg.connect(DATABASE_URL) as first, psycopg.connect(DATABASE_URL) as second:
        scoped(first, admitted["owner"])
        accepted = basis(first, admitted)
        purchase = purchase_values(admitted, accepted)
        insert(first, "billing.annual_purchases", purchase)
        insert(first, "billing.annual_operations", operation_values(admitted, purchase))
        scoped(second, admitted["owner"])
        second.execute("set local lock_timeout='250ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            insert(second, "billing.annual_purchases", purchase_values(admitted, accepted))
        second.rollback()
        first.commit()
        scoped(second, admitted["owner"])
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert(second, "billing.annual_purchases", purchase_values(admitted, accepted))


def refund_case(seed, purchase):
    case = {
        "id": uuid4(), "purchase_id": purchase["id"], "company_id": seed["company"], "income_year": 2026,
        "reason": "change_of_mind", "source_reference": str(uuid4()), "facts": Jsonb({"fixture": "verified-no-submission"}),
        "total_entitlement_minor": 149000, "initiate_by": datetime.now(UTC).date(), "created_by": seed["owner"],
    }
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, seed["owner"])
        insert(connection, "billing.annual_refund_cases", case)
    return case


def test_pending_and_unknown_refunds_reserve_money_and_never_exceed_capture(admitted):
    purchase, checkout = purchased(admitted)
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        connection.execute("update billing.annual_purchases set captured_minor=149000,captured_at=now(),status='paid' where id=%s", (purchase["id"],))
        connection.execute("update billing.annual_operations set status='confirmed' where id=%s", (checkout["id"],))
    case = refund_case(admitted, purchase)
    refund = operation_values(admitted, purchase, operation="refund", amount_minor=37250, refund_case_id=case["id"])
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        insert(connection, "billing.annual_operations", refund)
        connection.execute("update billing.annual_operations set status='unknown' where id=%s", (refund["id"],))
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        with pytest.raises(psycopg.errors.RaiseException, match="annual_refund_not_available"):
            insert(connection, "billing.annual_operations", operation_values(admitted, purchase,
                operation="refund", amount_minor=149000, refund_case_id=case["id"]))
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        # Exact replay bypasses a new reservation and inserts nothing.
        connection.execute("""insert into billing.annual_operations
          (id,purchase_id,company_id,income_year,created_by,created_at,idempotency_key,request_fingerprint,operation,amount_minor,intent,refund_case_id)
          select id,purchase_id,company_id,income_year,created_by,created_at,idempotency_key,request_fingerprint,operation,amount_minor,intent,refund_case_id
          from billing.annual_operations where id=%s on conflict (idempotency_key) do nothing""", (refund["id"],))
        connection.execute("update billing.annual_purchases set refunded_minor=37250,renewal_canceled_at=now() where id=%s", (purchase["id"],))
        connection.execute("update billing.annual_operations set status='confirmed' where id=%s", (refund["id"],))
        insert(connection, "billing.annual_operations", operation_values(admitted, purchase,
            operation="refund", amount_minor=111750, refund_case_id=case["id"]))
        assert connection.execute("select captured_minor,refunded_minor,status,renewal_canceled_at is not null from billing.annual_purchases where id=%s", (purchase["id"],)).fetchone() == (149000, 37250, "paid", True)


def test_customer_cannot_attribute_a_talli_failure_to_themselves(admitted):
    purchase, _ = purchased(admitted)
    case = refund_case(admitted, purchase)
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            insert(connection, "billing.annual_refund_cases", case | {"id": uuid4(), "source_reference": str(uuid4()), "reason": "talli_delivery_failure"})


@pytest.mark.parametrize("mixed", [False, True])
def test_annual_rollback_and_recutover_preserve_unresolved_intents_and_acceptance(admitted, mixed):
    purchase, operation = purchased(admitted)
    def evidence():
        with psycopg.connect(DATABASE_URL) as connection:
            scoped(connection, admitted["owner"])
            return connection.execute("select to_jsonb(p),to_jsonb(o) from billing.annual_purchases p join billing.annual_operations o on o.purchase_id=p.id where p.id=%s", (purchase["id"],)).fetchone()
    before = evidence()
    migration = "20260905083150_annual_billing_purchase_ledger.sql"
    for _ in range(2):
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            connection.execute((ROOT / "supabase" / "rollback" / "20260905115700_legacy_billing_acquisition_retirement.sql").read_text())
            connection.execute((ROOT / "supabase" / "rollback" / "20260905103149_annual_agreement_cleanup.sql").read_text())
            connection.execute((ROOT / "supabase" / "rollback" / "20260905100130_annual_renewal_cancellation.sql").read_text())
            connection.execute((ROOT / "supabase" / "rollback" / migration).read_text())
            assert connection.execute("select to_regclass('billing.annual_purchases')").fetchone()[0] is None
            predecessors = [
                "20260905080550_annual_billing_purchase_basis.sql",
                "20260905061339_billing_provider_reconciliation.sql",
                "20260905010000_billing_capability.sql",
            ] if mixed else []
            for predecessor in predecessors:
                connection.execute((ROOT / "supabase" / "rollback" / predecessor).read_text())
            if mixed:
                assert connection.execute("select to_regnamespace('billing')").fetchone()[0] is None
            for predecessor in reversed(predecessors):
                connection.execute((ROOT / "supabase" / "migrations" / predecessor).read_text())
            connection.execute((ROOT / "supabase" / "migrations" / migration).read_text())
            connection.execute((ROOT / "supabase" / "migrations" / "20260905100130_annual_renewal_cancellation.sql").read_text())
            connection.execute((ROOT / "supabase" / "migrations" / "20260905103149_annual_agreement_cleanup.sql").read_text())
            connection.execute((ROOT / "supabase" / "migrations" / "20260905115700_legacy_billing_acquisition_retirement.sql").read_text())
        # The migration returns borrowed authority, so reacquire the test role.
        with psycopg.connect(DATABASE_URL) as connection:
            principal = connection.execute("select current_user").fetchone()[0]
            connection.execute(psycopg.sql.SQL("grant billing_store_owner to {}").format(psycopg.sql.Identifier(principal)))
        assert evidence() == before


def test_fully_refunded_purchase_preserves_history_and_allows_repurchase(admitted):
    purchase, _ = purchased(admitted)
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        connection.execute("update billing.annual_purchases set captured_minor=149000,refunded_minor=149000,captured_at=now(),status='refunded' where id=%s", (purchase["id"],))
        replacement = purchase_values(admitted, basis(connection, admitted))
        insert(connection, "billing.annual_purchases", replacement)
        assert connection.execute("select count(*) from billing.annual_purchases where company_id=%s", (admitted["company"],)).fetchone()[0] == 2


def test_concurrent_full_refund_retry_waits_then_replays_same_operation(admitted):
    from concurrent.futures import ThreadPoolExecutor
    from time import monotonic, sleep

    purchase, _ = purchased(admitted)
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        connection.execute("update billing.annual_purchases set captured_minor=149000,captured_at=now(),status='paid' where id=%s", (purchase["id"],))
    case = refund_case(admitted, purchase)
    refund = operation_values(admitted, purchase, operation="refund", refund_case_id=case["id"])
    with psycopg.connect(DATABASE_URL) as first, psycopg.connect(DATABASE_URL) as second:
        scoped(first, admitted["owner"])
        insert(first, "billing.annual_operations", refund)
        scoped(second, admitted["owner"])
        pid = second.info.backend_pid
        def replay():
            query = psycopg.sql.SQL("insert into billing.annual_operations ({}) values ({}) on conflict (idempotency_key) do nothing").format(
                psycopg.sql.SQL(',').join(map(psycopg.sql.Identifier, refund)),
                psycopg.sql.SQL(',').join(psycopg.sql.Placeholder() for _ in refund),
            )
            return second.execute(query, tuple(refund.values())).rowcount
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(replay)
            try:
                deadline = monotonic() + 5
                with psycopg.connect(DATABASE_URL, autocommit=True) as observer:
                    while monotonic() < deadline:
                        if observer.execute("select wait_event_type from pg_stat_activity where pid=%s", (pid,)).fetchone() == ('Lock',):
                            break
                        sleep(.01)
                    else:
                        pytest.fail('Concurrent retry did not reach the purchase lock')
                first.commit()
                assert future.result(timeout=5) == 0
            finally:
                first.rollback()
        assert second.execute("select count(*) from billing.annual_operations where purchase_id=%s and operation='refund'", (purchase["id"],)).fetchone()[0] == 1


@pytest.mark.parametrize("mode", ["opened", "no_case", "unopened", "wrong_company", "wrong_scope", "expired", "revoked", "stale_mfa"])
def test_operator_requires_open_same_company_billing_case(admitted, mode):
    from datetime import timedelta

    purchase, _ = purchased(admitted)
    actor, case_id = admitted["outsider"], uuid4()
    now = datetime.now(UTC)
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection, "public.support_operators", {"user_id": actor, "role": "admin", "active": True})
        insert(connection, "public.support_access_grants", {
            "case_id": case_id, "company_id": admitted["company"], "operator_user_id": actor,
            "reason": "customer_request", "scopes": ["profile" if mode == "wrong_scope" else "billing"],
            "starts_at": now - timedelta(hours=2), "expires_at": now + timedelta(hours=-1 if mode == "expired" else 1),
            "granted_by": actor,
        } | ({"revoked_at": now, "revoked_by": actor, "revocation_reason": "case_closed"} if mode == "revoked" else {}))
        if mode != "unopened":
            insert(connection, "public.support_case_openings", {
                "actor_id": actor, "operation_id": uuid4(), "case_id": case_id,
                "company_id": admitted["company"],
            })
    if mode == "wrong_company":
        # A real second company keeps the grant FK valid while mismatching the purchase.
        with psycopg.connect(DATABASE_URL) as connection:
            other = uuid4()
            insert(connection, "public.companies", {
                "id": other, "org_number": str(100000000 + other.int % 899999999),
                "name": "Other Case Holding AS", "entity_type": "AS", "address": "Testveien 2",
                "postal_code": "0150", "city": "Oslo", "status_text": "aktiv", "source": "test",
                "created_by": admitted["owner"],
            })
            connection.execute("update public.support_access_grants set company_id=%s where case_id=%s", (other, case_id))
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, actor, fresh=mode != "stale_mfa")
        if mode != "no_case":
            connection.execute("select set_config('talli.support_case_id',%s,true)", (str(case_id),))
        allowed = mode == "opened"
        assert connection.execute("select count(*) from billing.annual_purchases where id=%s", (purchase["id"],)).fetchone()[0] == int(allowed)
        assert connection.execute("update billing.annual_purchases set renewal_canceled_at=now() where id=%s", (purchase["id"],)).rowcount == int(allowed)
        values = {
            "id": uuid4(), "purchase_id": purchase["id"], "company_id": admitted["company"], "income_year": 2026,
            "reason": "talli_delivery_failure", "source_reference": str(uuid4()), "facts": Jsonb({"fixture": "incident"}),
            "total_entitlement_minor": 149000, "initiate_by": now.date(), "created_by": actor,
        }
        if allowed:
            insert(connection, "billing.annual_refund_cases", values)
        else:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                insert(connection, "billing.annual_refund_cases", values)
