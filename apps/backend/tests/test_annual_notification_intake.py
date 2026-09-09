"""Real HTTP/authentication composition with a synthetic durable receipt seam."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

from test_vipps_webhook import NOW, SECRET, encoded, signed as fixture_signed
from talli_backend.adapters.vipps_webhook import VippsWebhookAuthentication
from talli_backend.application.annual_notifications import AnnualNotificationIntake
from talli_backend.main import create_app
from talli_backend.modules.billing.public import (
    AnnualNotificationAccount, AnnualNotificationReceipt, AnnualNotificationReceiptId,
    AnnualNotificationUnavailable, AnnualProviderNotification,
)
from talli_backend.shared.kernel import Timestamp


PATH = '/api/v1/billing/annual/provider-notifications'
AUTH = VippsWebhookAuthentication('123456', 'https://talli.example' + PATH, SECRET)


def signed(body, **options):
    return fixture_signed(body, **({'path': PATH} | options))


class Receipts:
    account = AUTH.account

    def __init__(self):
        self.saved = {}
        self.calls = 0
        self.mode = 'ok'

    async def record_notification(self, notification):
        self.calls += 1
        if self.mode == 'commit-failed':
            raise AnnualNotificationUnavailable()
        receipt = self.saved.setdefault(notification.receipt_digest, AnnualNotificationReceipt(
            AnnualNotificationReceiptId(str(uuid4())), Timestamp(datetime.now(UTC)), notification,
        ))
        if self.mode == 'lost-ack':
            raise AnnualNotificationUnavailable()
        if self.mode == 'wrong-evidence':
            return replace(receipt, notification=replace(notification, agreement_reference='wrong'))
        return receipt


def fixture(store=None):
    store = store or Receipts()
    return TestClient(create_app(annual_notification_intake=AnnualNotificationIntake(AUTH, store))), store


def deliver(api, body=None, **options):
    body = encoded() if body is None else body
    return api.post(PATH, content=body, headers=signed(body, at=datetime.now(UTC)), **options)


def test_disabled_boundary_is_stable_and_never_accepts_an_owner_token():
    api = TestClient(create_app())
    assert api.post(PATH, content=encoded(), headers={'Authorization': 'Bearer owner'}).status_code == 503
    operation = api.app.openapi()['paths'][PATH]['post']
    assert operation['security'] == [{'annualNotificationHmac': []}]
    assert operation['operationId'] == 'billingReceiveAnnualProviderNotification'
    assert all('application/problem+json' in operation['responses'][str(status)]['content']
               for status in (400, 401, 408, 413, 503))
    assert api.get(PATH).status_code == 405


def test_signed_delivery_returns_only_committed_ack_and_exact_retry_receipt():
    api, store = fixture()
    first = deliver(api)
    assert first.status_code == 200 and first.json() == {'status': 'received'}
    assert first.headers['cache-control'] == 'no-store'
    assert 'x-request-id' in first.headers
    original = list(store.saved.values())
    assert deliver(api).json() == first.json()
    assert store.calls == 2 and list(store.saved.values()) == original
    assert not any(value in first.text for value in (SECRET, '123456', 'agr_local', '149000'))


@pytest.mark.parametrize('change', ['missing', 'bearer', 'signature', 'date', 'hash', 'duplicate', 'merchant', 'target', 'json-duplicate'])
def test_authentication_rejections_precede_any_persistence(change):
    api, store = fixture()
    body = encoded(msn='999999') if change == 'merchant' else encoded()
    if change == 'json-duplicate':
        body = body[:-1] + b',"msn":"123456"}'
    headers = signed(body, at=datetime.now(UTC), path='/wrong' if change == 'target' else PATH)
    if change == 'missing':
        headers = {}
    elif change == 'bearer':
        headers['Authorization'] = 'Bearer owner'
    elif change == 'signature':
        headers['Authorization'] += 'wrong'
    elif change == 'date':
        headers = signed(body, at=datetime.now(UTC) - timedelta(days=9))
    elif change == 'hash':
        body += b' '
    elif change == 'duplicate':
        headers = list(headers.items()) + [('authorization', headers['Authorization'])]
    response = api.post(PATH, content=body, headers=headers)
    assert response.status_code == 401, response.text
    assert store.calls == 0 and store.saved == {}
    assert SECRET not in response.text and '123456' not in response.text


def test_oversized_stream_and_empty_body_never_reach_persistence():
    api, store = fixture()
    assert api.post(PATH, content=iter([b'x' * 32768, b'x' * 32768, b'x']), headers={'Content-Length': '1'}).status_code == 413
    assert deliver(api, b'').status_code == 401
    assert store.calls == 0


def test_stream_stops_at_limit_without_consuming_tail_and_accepts_exact_limit():
    store = Receipts()
    app = create_app(annual_notification_intake=AnnualNotificationIntake(AUTH, store))
    chunks_read = []
    async def chunks():
        for size in (32768, 32768, 1, 999999):
            chunks_read.append(size)
            yield b'x' * size
    async def receive():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as api:
            response = await api.post(PATH, content=chunks())
            assert response.status_code == 413
    asyncio.run(receive())
    assert chunks_read == [32768, 32768, 1] and store.calls == 0
    body = encoded() + b' ' * (65536 - len(encoded()))
    api, _ = fixture(store)
    assert deliver(api, body).status_code == 200


def test_slow_incomplete_delivery_times_out_before_authentication_or_storage():
    store = Receipts()
    app = create_app(annual_notification_intake=AnnualNotificationIntake(AUTH, store))
    async def chunks():
        yield b'{'
        await asyncio.sleep(10)
        yield b'}'
    async def receive():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as api:
            response = await api.post(PATH, content=chunks())
            assert response.status_code == 408
    asyncio.run(receive())
    assert store.calls == 0


@pytest.mark.parametrize('mode', ['commit-failed', 'lost-ack', 'wrong-evidence'])
def test_no_ack_until_receipt_confirmed_and_lost_ack_replays_existing_receipt(mode):
    api, store = fixture()
    store.mode = mode
    assert deliver(api).status_code == 503
    saved = list(store.saved.values())
    store.mode = 'ok'
    assert deliver(api).status_code == 200
    assert len(store.saved) == 1
    if mode != 'commit-failed':
        assert list(store.saved.values()) == saved


def test_provider_and_account_must_match_before_any_intake():
    store = Receipts()
    store.account = AnnualNotificationAccount('vipps-mt', '999999')
    with pytest.raises(AnnualNotificationUnavailable):
        AnnualNotificationIntake(AUTH, store)
    assert store.calls == 0


@pytest.mark.parametrize('field,value', [
    ('agreement_reference', ''), ('agreement_reference', 'a' * 101), ('agreement_reference', '../escape'),
    ('charge_reference', 'æ'), ('event_type', 'bad event'), ('receipt_digest', 'f' * 63),
    ('receipt_digest', 'G' * 64), ('occurred_at', NOW), ('account', '123456'),
])
def test_notification_contract_rejects_unbounded_or_untyped_hints(field, value):
    original = AUTH.authenticate(encoded(), signed(encoded()), at=NOW)
    with pytest.raises(ValueError):
        replace(original, **{field: value})


def test_account_change_or_forged_digest_from_auth_adapter_never_reaches_store():
    store = Receipts()
    original = AUTH.authenticate(encoded(), signed(encoded()), at=NOW)
    for value in (replace(original, receipt_digest='a' * 64),
                  replace(original, account=AnnualNotificationAccount('other-test', '123456'))):
        class Authentication:
            account = AUTH.account
            def authenticate(self, *args, **kwargs):
                return value
        with pytest.raises(AnnualNotificationUnavailable):
            asyncio.run(AnnualNotificationIntake(Authentication(), store).receive(encoded(), {}, at=NOW))
    assert store.calls == 0


def test_reserialized_json_is_a_separate_delivery_not_business_effect_idempotency():
    api, store = fixture()
    assert deliver(api).status_code == 200
    assert deliver(api, encoded() + b'\n').status_code == 200
    assert len(store.saved) == 2
