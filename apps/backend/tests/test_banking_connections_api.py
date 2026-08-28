from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from talli_backend.main import create_app
from talli_backend.modules.banking.public import (
    BankAccount,
    BankAccountId,
    BankAccountStatus,
    BankConnection,
    BankConnectionList,
    BankConnectionId,
    BankConnectionStatus,
    BankConnectorId,
    BankConsentRedirect,
    BankProviderAccount,
    BankProviderConnection,
    BankProviderTransactionPage,
    BankSourceFileId,
    BankStatementImportResult,
    BankSyncAttemptId,
    BankSyncContext,
    BankSyncPageResult,
    BankSyncResult,
    PersistedBankFilePreview,
)
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    LocalDate,
    UserId,
)


ACTOR_ID = ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000002"))
COMPANY_ID = CompanyId("10000000-0000-0000-0000-000000000001")
CONNECTION_ID = BankConnectionId("30000000-0000-0000-0000-000000000003")
ACCOUNT_ID = BankAccountId("40000000-0000-0000-0000-000000000004")


class ProviderStub:
    connector_id = BankConnectorId("fixture-connector")

    async def begin_consent(self, request):
        return BankConsentRedirect("https://bank.example/consent", "opaque-state")

    async def complete_consent(self, request):
        return BankProviderConnection(
            connection_id=request.connection_id,
            connector_id=self.connector_id,
            adapter_connection_reference="provider-session",
            consent_expires_on=LocalDate(date(2027, 2, 24)),
            accounts=(
                BankProviderAccount(
                    adapter_account_reference="provider-account",
                    masked_account="•••• 1234",
                    currency="NOK",
                    account_kind="CACC",
                    display_name="Driftskonto",
                ),
            ),
        )

    async def fetch_transactions(self, request):
        return BankProviderTransactionPage((), None)

    async def revoke_consent(self, request):
        return None


class SessionStub:
    actor_id = ACTOR_ID

    def __init__(self) -> None:
        self.events: list[str] = []

    async def session(self, access_token):
        assert access_token == "session-token"
        return self

    async def begin_connection(self, command):
        self.events.append("begin")

    async def list_connections(self, **_request):
        return BankConnectionList((
            BankConnection(
                connection_id=CONNECTION_ID,
                company_id=COMPANY_ID,
                connector_id=BankConnectorId("fixture-connector"),
                status=BankConnectionStatus.CONSENT_PENDING,
                consent_expires_on=None,
                accounts=(),
                last_success_at=None,
                last_failure_code=None,
            ),
        ))

    async def get_connection_completion_replay(self, command):
        return None

    async def record_consent_redirect(self, command, redirect):
        self.events.append("redirect")
        return redirect

    async def fail_connection(self, command, *, error_code):
        self.events.append(f"failed:{error_code}")

    async def complete_connection(self, command, provider_connection):
        return BankConnection(
            connection_id=command.connection_id,
            company_id=command.company_id,
            connector_id=provider_connection.connector_id,
            status=BankConnectionStatus.ACTIVE,
            consent_expires_on=provider_connection.consent_expires_on,
            accounts=(
                BankAccount(
                    account_id=ACCOUNT_ID,
                    connection_id=command.connection_id,
                    masked_account="•••• 1234",
                    currency="NOK",
                    account_kind="CACC",
                    display_name="Driftskonto",
                    status=BankAccountStatus.ACTIVE,
                    earliest_covered_date=None,
                    latest_covered_date=None,
                    last_success_at=None,
                ),
            ),
            last_success_at=None,
            last_failure_code=None,
        )

    async def begin_revocation(self, command):
        self.events.append("revocation-began")
        return "provider-session"

    async def complete_revocation(self, command):
        self.events.append("revocation-completed")

    async def prepare_sync(self, command):
        return BankSyncContext(
            attempt_id=BankSyncAttemptId("50000000-0000-0000-0000-000000000005"),
            connector_id=BankConnectorId("fixture-connector"),
            adapter_connection_reference="provider-session",
            adapter_account_reference="provider-account",
            resume_cursor=None,
        )

    async def apply_sync_page(self, command, *, context, transactions, next_cursor):
        return BankSyncPageResult(0, 0, 0)

    async def complete_sync(self, command, *, context, pages, imported_count, updated_count, duplicate_count):
        return BankSyncResult(context.attempt_id, pages, 0, 0, 0, False)

    async def fail_sync(self, command, *, context, error_code):
        raise AssertionError(error_code)

    async def persist_file_preview(self, command, preview):
        self.events.append("preview")
        return PersistedBankFilePreview(command.source_file_id, preview, False)

    async def accept_file(self, command):
        self.events.append("accept")
        return BankStatementImportResult(1, 0, (), False)


def client(session: SessionStub) -> TestClient:
    return TestClient(
        create_app(
            banking_session_factory=session,
            banking_providers={"fixture-connector": ProviderStub()},
        )
    )


def headers(key: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer session-token",
        "Idempotency-Key": key,
        "X-Request-ID": "banking-route-test",
    }


def test_callback_and_sync_routes_resolve_provider_from_canonical_connection() -> None:
    session = SessionStub()
    api = client(session)
    listed = api.get(
        "/api/v1/banking/connections",
        headers={"Authorization": "Bearer session-token"},
        params={"companyId": str(COMPANY_ID)},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["connectorId"] == "fixture-connector"
    started = api.post(
        "/api/v1/banking/connections",
        headers=headers("banking-start-route-0001"),
        json={
            "companyId": str(COMPANY_ID),
            "incomeYear": 2026,
            "connectionId": str(CONNECTION_ID),
            "connectorId": "fixture-connector",
            "bankKey": "DNB",
            "returnUrl": "https://app.talli.no/bank/callback",
        },
    )
    assert started.status_code == 200, started.text
    assert started.json()["redirectUrl"] == "https://bank.example/consent"
    completed = api.get(
        f"/api/v1/banking/connections/{CONNECTION_ID}/callback",
        headers={"Authorization": "Bearer session-token"},
        params={
            "companyId": str(COMPANY_ID),
            "incomeYear": 2026,
            "code": "opaque-code",
            "state": "opaque-state",
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["accounts"][0]["maskedAccount"] == "•••• 1234"
    synced = api.post(
        f"/api/v1/banking/connections/{CONNECTION_ID}/accounts/{ACCOUNT_ID}/syncs",
        headers=headers("banking-sync-route-0001"),
        json={
            "companyId": str(COMPANY_ID),
            "incomeYear": 2026,
            "connectorId": "browser-forged-connector",
            "dateFrom": "2026-01-01",
            "dateTo": "2026-12-31",
            "mode": "ON_DEMAND",
        },
    )
    assert synced.status_code == 200, synced.text
    assert synced.json()["pageCount"] == 1
    revoked = api.post(
        f"/api/v1/banking/connections/{CONNECTION_ID}/revoke",
        headers=headers("banking-revoke-route-0001"),
        json={
            "companyId": str(COMPANY_ID),
            "incomeYear": 2026,
            "connectorId": "browser-forged-connector",
        },
    )
    assert revoked.status_code == 204, revoked.text
    assert session.events == [
        "begin",
        "redirect",
        "revocation-began",
        "revocation-completed",
    ]


def test_file_routes_require_preview_before_explicit_acceptance() -> None:
    session = SessionStub()
    api = client(session)
    source_file_id = BankSourceFileId("60000000-0000-0000-0000-000000000006")
    previewed = api.post(
        "/api/v1/banking/source-files/previews",
        headers=headers("banking-preview-route-0001"),
        json={
            "companyId": str(COMPANY_ID),
            "incomeYear": 2026,
            "sourceFileId": str(source_file_id),
            "accountId": str(ACCOUNT_ID),
            "dataFormat": "CSV",
            "filename": "statement.csv",
            "content": "date,text,amount\n2026-01-02,Annual fee,-89\n",
            "columnMapping": {
                "bookingDate": "date",
                "valueDate": None,
                "text": "text",
                "amount": "amount",
                "balance": None,
                "reference": None,
                "state": None,
            },
        },
    )
    assert previewed.status_code == 200, previewed.text
    accepted = api.post(
        f"/api/v1/banking/source-files/{source_file_id}/acceptance",
        headers=headers("banking-accept-file-route-0001"),
        json={
            "companyId": str(COMPANY_ID),
            "incomeYear": 2026,
            "documentSha256": previewed.json()["documentSha256"],
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["importedCount"] == 1
    assert session.events == ["preview", "accept"]
