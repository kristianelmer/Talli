"""Opt-in merchant-test composition; configuration grants no filing readiness."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
import re
from urllib.parse import urlsplit

import psycopg
from psycopg.conninfo import conninfo_to_dict

from talli_backend.adapters.postgres_annual_notifications import PostgresAnnualNotificationInbox
from talli_backend.adapters.vipps_billing import VippsTestBillingProvider, VippsTestConfiguration
from talli_backend.adapters.vipps_webhook import VippsWebhookAuthentication
from talli_backend.application.annual_notifications import AnnualNotificationIntake
from talli_backend.modules.billing.public import AnnualBillingProvider, BillingError


ANNUAL_NOTIFICATION_PATH = "/api/v1/billing/annual/provider-notifications"
VIPPS_MT_MERCHANT_SERIAL_NUMBER = "535717"


class AnnualBillingRuntimeConfigurationError(ValueError):
    """Expose the setting name, never a configured value or parser diagnostic."""

    def __init__(self, setting: str):
        super().__init__(f"Invalid annual billing runtime setting: {setting}")


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    if (not isinstance(value, str) or not value or len(value) > 8192
            or value != value.strip() or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise AnnualBillingRuntimeConfigurationError(name)
    return value


def _https_url(value: str, setting: str, *, path: str) -> None:
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname and parsed.username is None
                 and parsed.password is None and parsed.path == path and not parsed.query
                 and not parsed.fragment and parsed.port in (None, 443)
                 and not any(character.isspace() for character in value)
                 and not any(character in value for character in "\\?#")
                 and re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", parsed.hostname)
                 and all(label and len(label) <= 63 and not label.startswith("-")
                         and not label.endswith("-") for label in parsed.hostname.split(".")))
    except ValueError:
        valid = False
    if not valid:
        raise AnnualBillingRuntimeConfigurationError(setting)


def load_vipps_mt_configuration(environment: Mapping[str, str]) -> VippsTestConfiguration:
    """Parse the designated MT account without enabling HTTP intake or readiness."""
    merchant = _required(environment, "TALLI_VIPPS_MT_MERCHANT_SERIAL_NUMBER")
    if merchant != VIPPS_MT_MERCHANT_SERIAL_NUMBER:
        raise AnnualBillingRuntimeConfigurationError("TALLI_VIPPS_MT_MERCHANT_SERIAL_NUMBER")
    origins_setting = "TALLI_VIPPS_MT_CONFIRMATION_ORIGINS"
    origins = tuple(part.strip() for part in _required(environment, origins_setting).split(","))
    if len(origins) > 10 or len(set(origins)) != len(origins):
        raise AnnualBillingRuntimeConfigurationError(origins_setting)
    for origin in origins:
        _https_url(origin, origins_setting, path="")
    try:
        return VippsTestConfiguration(
            merchant,
            _required(environment, "TALLI_VIPPS_MT_CLIENT_ID"),
            _required(environment, "TALLI_VIPPS_MT_CLIENT_SECRET"),
            _required(environment, "TALLI_VIPPS_MT_SUBSCRIPTION_KEY"),
            origins,
        )
    except BillingError:
        raise AnnualBillingRuntimeConfigurationError(origins_setting) from None


@dataclass(frozen=True, slots=True)
class AnnualBillingRuntimeConfiguration:
    vipps: VippsTestConfiguration
    webhook: VippsWebhookAuthentication
    notification_database_url: str = field(repr=False)

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str],
    ) -> "AnnualBillingRuntimeConfiguration | None":
        mode = environment.get("TALLI_ANNUAL_BILLING_MODE", "off")
        if mode == "off":
            return None
        if mode != "vipps-mt":
            raise AnnualBillingRuntimeConfigurationError("TALLI_ANNUAL_BILLING_MODE")
        vipps = load_vipps_mt_configuration(environment)
        callback_setting = "TALLI_VIPPS_MT_WEBHOOK_CALLBACK_URL"
        callback = _required(environment, callback_setting)
        _https_url(callback, callback_setting, path=ANNUAL_NOTIFICATION_PATH)
        secret_setting = "TALLI_VIPPS_MT_WEBHOOK_SECRET"
        secret = _required(environment, secret_setting)
        if len(secret) > 1024:
            raise AnnualBillingRuntimeConfigurationError(secret_setting)
        webhook = VippsWebhookAuthentication(vipps.merchant_serial_number, callback, secret)
        database_setting = "TALLI_ANNUAL_NOTIFICATION_DATABASE_URL"
        database_url = _required(environment, database_setting)
        try:
            parsed = urlsplit(database_url)
            details = conninfo_to_dict(database_url)
            valid = (parsed.scheme in {"postgres", "postgresql"} and parsed.hostname
                     and not parsed.fragment and parsed.port != 0
                     and all(details.get(key) for key in ("host", "user", "dbname")))
        except (ValueError, psycopg.Error):
            valid = False
        if not valid:
            raise AnnualBillingRuntimeConfigurationError(database_setting) from None
        return cls(vipps, webhook, database_url)


@dataclass(frozen=True, slots=True)
class AnnualBillingRuntime:
    provider: AnnualBillingProvider | None = None
    notification_intake: AnnualNotificationIntake | None = None


def compose_annual_billing_runtime(
    environment: Mapping[str, str] | None = None,
) -> AnnualBillingRuntime:
    """Validate all enabled settings before constructing any adapter; no I/O."""
    configuration = AnnualBillingRuntimeConfiguration.from_environment(
        os.environ if environment is None else environment,
    )
    if configuration is None:
        return AnnualBillingRuntime()
    provider = VippsTestBillingProvider(configuration.vipps)
    inbox = PostgresAnnualNotificationInbox(
        configuration.notification_database_url, configuration.webhook.account,
    )
    return AnnualBillingRuntime(
        provider, AnnualNotificationIntake(configuration.webhook, inbox),
    )
