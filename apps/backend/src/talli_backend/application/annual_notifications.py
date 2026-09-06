"""Commit authenticated delivery evidence without creating business authority."""

from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256

from talli_backend.modules.billing.public import (
    AnnualNotificationAuthentication, AnnualNotificationPersistence,
    AnnualNotificationReceipt, AnnualNotificationUnavailable,
)


class AnnualNotificationIntake:
    def __init__(
        self, authentication: AnnualNotificationAuthentication,
        receipts: AnnualNotificationPersistence,
    ):
        if authentication.account != receipts.account:
            raise AnnualNotificationUnavailable()
        self._authentication = authentication
        self._receipts = receipts

    async def receive(
        self, body: bytes, headers: Mapping[str, str], *, at: datetime,
    ) -> AnnualNotificationReceipt:
        notification = self._authentication.authenticate(body, headers, at=at)
        if (notification.account != self._authentication.account
                or notification.account != self._receipts.account
                or notification.receipt_digest != sha256(body).hexdigest()):
            raise AnnualNotificationUnavailable()
        receipt = await self._receipts.record_notification(notification)
        if receipt.notification != notification:
            raise AnnualNotificationUnavailable()
        return receipt
