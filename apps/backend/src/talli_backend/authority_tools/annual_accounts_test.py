"""Thin local entry point for the owned Annual Accounts test rehearsal."""
from __future__ import annotations
import asyncio
import json
import os
import sys

from ._filing import payload, validate_xml
from talli_backend.adapters.annual_accounts_authority import (
    AnnualAccountsTransport, exchange_maskinporten_for_altinn_token,
)
from talli_backend.adapters.local_annual_accounts_rehearsal import (
    LocalAnnualAccountsRehearsal, local_annual_accounts_summary,
)
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsAuthorityError, AnnualAccountsRehearsalConfiguration, rehearse_annual_accounts,
)


async def _client(environment, evidence):
    from dataclasses import replace
    from ._grant import CliGrantConfiguration, request_token
    configuration = replace(CliGrantConfiguration.from_environment(environment),
        system_user_external_ref=evidence["systemUserExternalRef"])
    token = await request_token(configuration)
    try:
        exchanged = await exchange_maskinporten_for_altinn_token(token.access_token)
    finally:
        token.discard()
    return AnnualAccountsTransport(exchanged)


async def run(environment=None, *, client_factory=_client, generate=payload, validate=validate_xml):
    environment = os.environ if environment is None else environment
    configuration = AnnualAccountsRehearsalConfiguration(
        approved_test_write=environment.get("TALLI_ANNUAL_ACCOUNTS_APPROVED_TEST_WRITE", ""),
        authority_environment=environment.get("TALLI_MASKINPORTEN_ENVIRONMENT", ""),
        scope=environment.get("TALLI_MASKINPORTEN_SCOPE", ""),
        system_user_org=environment.get("TALLI_MASKINPORTEN_SYSTEM_USER_ORG", ""),
        external_reference=environment.get("TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF", ""),
        system_user_request_id=environment.get("TALLI_ANNUAL_ACCOUNTS_SYSTEM_USER_REQUEST_ID", ""),
        contact_email=environment.get("TALLI_ANNUAL_ACCOUNTS_CONTACT_EMAIL", ""),
        approval_date=environment.get("TALLI_ANNUAL_ACCOUNTS_APPROVAL_DATE", ""),
        confirming_representative=environment.get("TALLI_ANNUAL_ACCOUNTS_CONFIRMING_REPRESENTATIVE", ""),
    )
    io = LocalAnnualAccountsRehearsal(environment, client_factory=client_factory,
        generate=generate, validate=validate)
    return local_annual_accounts_summary(await rehearse_annual_accounts(configuration, io))


def main():
    os.umask(0o077)
    try:
        print(json.dumps(asyncio.run(run()), ensure_ascii=False))
    except Exception as error:
        if isinstance(error, AnnualAccountsAuthorityError):
            result = {"ok": False, **error.evidence()}
        else:
            message = str(error) if isinstance(error, ValueError) and str(error).startswith("TALLI_") else "Local configuration or payload is invalid."
            result = {"ok": False, "code": "local_configuration_or_payload_error", "status": None, "message": message}
        print(json.dumps(result), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
