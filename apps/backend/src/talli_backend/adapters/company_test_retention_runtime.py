"""Opt-in history composition; configuration does not attest an owned target."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import ipaddress
import os
from urllib.parse import urlsplit

import psycopg
from psycopg.conninfo import conninfo_to_dict

from talli_backend.adapters.postgres_shareholder_register_filing import PostgresCompanyTestRetentionSessionFactory
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration


class CompanyTestRetentionRuntimeConfigurationError(ValueError):
    """Expose a setting name, never its value or a parser diagnostic."""

    def __init__(self, setting: str):
        super().__init__(f"Invalid company test retention runtime setting: {setting}")


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    if (not isinstance(value, str) or not value or len(value) > 8192
            or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise CompanyTestRetentionRuntimeConfigurationError(name)
    return value


def _auth_origin(environment: Mapping[str, str]) -> str:
    setting = "SUPABASE_URL"
    value = _required(environment, setting)
    try:
        parsed = urlsplit(value)
        loopback = parsed.hostname == "localhost"
        if parsed.hostname and not loopback:
            try:
                loopback = ipaddress.ip_address(parsed.hostname).is_loopback
            except ValueError:
                pass
        valid = (parsed.scheme in {"https", "http"} and parsed.hostname
                 and (parsed.scheme == "https" or loopback)
                 and parsed.username is None and parsed.password is None
                 and parsed.path in {"", "/"} and parsed.port != 0
                 and not any(c.isspace() or c in "\\?#" for c in value))
    except (ValueError, UnicodeError):
        valid = False
    if not valid:
        raise CompanyTestRetentionRuntimeConfigurationError(setting) from None
    return f"{parsed.scheme}://{parsed.netloc}"


def _database_url(environment: Mapping[str, str]) -> str:
    setting = "TALLI_COMPANY_TEST_RETENTION_DATABASE_URL"
    value = _required(environment, setting)
    try:
        parsed = urlsplit(value)
        details = conninfo_to_dict(value)
        valid = (parsed.scheme in {"postgres", "postgresql"} and parsed.hostname
                 and "#" not in value and parsed.port != 0
                 and all(details.get(key) for key in ("host", "user", "dbname")))
    except (ValueError, UnicodeError, psycopg.Error):
        valid = False
    if not valid:
        raise CompanyTestRetentionRuntimeConfigurationError(setting) from None
    return value


@dataclass(frozen=True, slots=True)
class CompanyTestRetentionRuntimeConfiguration:
    auth_url: str
    anon_key: str = field(repr=False)
    database_url: str = field(repr=False)

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str],
    ) -> "CompanyTestRetentionRuntimeConfiguration | None":
        mode = environment.get("TALLI_COMPANY_TEST_RETENTION_MODE", "off")
        if mode == "off":
            return None
        if mode != "postgres":
            raise CompanyTestRetentionRuntimeConfigurationError("TALLI_COMPANY_TEST_RETENTION_MODE")
        origin = _auth_origin(environment)
        key = _required(environment, "SUPABASE_ANON_KEY")
        if not key.isascii() or any(c.isspace() for c in key):
            raise CompanyTestRetentionRuntimeConfigurationError("SUPABASE_ANON_KEY")
        database_url = _database_url(environment)
        return cls(origin, key, database_url)


def compose_company_test_retention_runtime(
    environment: Mapping[str, str] | None = None,
) -> PostgresCompanyTestRetentionSessionFactory | None:
    """Validate all enabled settings before constructing the existing reader; no I/O."""
    config = CompanyTestRetentionRuntimeConfiguration.from_environment(
        os.environ if environment is None else environment,
    )
    if config is None:
        return None
    return PostgresCompanyTestRetentionSessionFactory(
        LedgerSupabaseConfiguration(config.auth_url, config.anon_key, config.database_url),
    )
