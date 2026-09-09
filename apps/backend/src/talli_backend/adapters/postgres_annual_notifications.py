"""Actorless delivery receipt storage; no financial-table or provider authority."""

from asyncio import timeout

import psycopg
from psycopg.rows import dict_row

from talli_backend.modules.billing.public import (
    AnnualNotificationAccount, AnnualNotificationPersistence, AnnualNotificationReceipt,
    AnnualNotificationReceiptId, AnnualNotificationUnavailable, AnnualProviderNotification,
    billing_persistence_adapter,
)
from talli_backend.shared.kernel import Timestamp


@billing_persistence_adapter(AnnualNotificationPersistence)
class PostgresAnnualNotificationInbox:
    def __init__(self, database_url: str, account: AnnualNotificationAccount):
        self._database_url = database_url
        self._account = account

    @property
    def account(self) -> AnnualNotificationAccount:
        return self._account

    async def record_notification(self, notification: AnnualProviderNotification) -> AnnualNotificationReceipt:
        if not self._database_url or notification.account != self.account:
            raise AnnualNotificationUnavailable()
        try:
            async with (
                timeout(6),
                await psycopg.AsyncConnection.connect(
                    self._database_url, connect_timeout=3, row_factory=dict_row,
                    options="-c statement_timeout=3000 -c lock_timeout=1000",
                ) as connection,
                connection.transaction(),
            ):
                await connection.execute("set local role annual_notification_executor")
                await connection.execute(
                    "select set_config('talli.notification_provider', %s, true), "
                    "set_config('talli.notification_account', %s, true)",
                    (self.account.provider, self.account.reference),
                )
                row = await (await connection.execute(
                    """insert into annual_notification_inbox.receipts
                    (provider, provider_account, receipt_digest, agreement_reference,
                     charge_reference, event_type, occurred_at)
                    values (%s, %s, %s, %s, %s, %s, %s)
                    on conflict (provider, provider_account, receipt_digest) do nothing
                    returning *""",
                    (self.account.provider, self.account.reference, notification.receipt_digest,
                     notification.agreement_reference, notification.charge_reference,
                     notification.event_type, notification.occurred_at.value),
                )).fetchone()
                if row is None:
                    # A distinct statement sees the concurrent winner after the
                    # unique-key wait; a same-statement CTE can miss that commit.
                    row = await (await connection.execute(
                        """select * from annual_notification_inbox.receipts
                        where provider=%s and provider_account=%s and receipt_digest=%s""",
                        (self.account.provider, self.account.reference, notification.receipt_digest),
                    )).fetchone()
                if row is None:
                    raise AnnualNotificationUnavailable()
                stored = AnnualProviderNotification(
                    account=AnnualNotificationAccount(row['provider'], row['provider_account']),
                    receipt_digest=row['receipt_digest'], agreement_reference=row['agreement_reference'],
                    charge_reference=row['charge_reference'], event_type=row['event_type'],
                    occurred_at=Timestamp(row['occurred_at']),
                )
                if stored != notification:
                    raise AnnualNotificationUnavailable()
                receipt = AnnualNotificationReceipt(
                    AnnualNotificationReceiptId(str(row['id'])), Timestamp(row['received_at']), stored,
                )
            # Both transaction and connection contexts have completed commit.
            return receipt
        except (TimeoutError, psycopg.Error, ValueError, KeyError, TypeError):
            raise AnnualNotificationUnavailable() from None
