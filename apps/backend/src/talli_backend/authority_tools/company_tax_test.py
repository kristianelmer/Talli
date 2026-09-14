"""Thin local entry point for the Company Tax prepare/resume workflow."""
from __future__ import annotations

import asyncio
import json
import os
import sys

from ._filing import payload, validate_xml
from talli_backend.adapters.company_tax_authority import (
    CompanyTaxTransport, exchange_maskinporten_for_altinn_token,
)
from talli_backend.adapters.local_company_tax_rehearsal import LocalCompanyTaxRehearsal, local_rehearsal_summary
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxRehearsalConfiguration, CompanyTaxReturnAuthorityError, rehearse_company_tax_return,
)


async def _client(environment, evidence):
    from ._grant import CliGrantConfiguration, request_token
    token = await request_token(CliGrantConfiguration.from_environment(environment))
    try:
        exchanged = await exchange_maskinporten_for_altinn_token(token.access_token)
        return CompanyTaxTransport(token.access_token, exchanged)
    finally:
        token.discard()


async def run(environment=None, *, client_factory=_client, generate=payload, validate=validate_xml, sleep=asyncio.sleep):
    environment = os.environ if environment is None else environment
    configuration = CompanyTaxRehearsalConfiguration(
        approved_test_write=environment.get("TALLI_COMPANY_TAX_APPROVED_TEST_WRITE", ""),
        authority_environment=environment.get("TALLI_MASKINPORTEN_ENVIRONMENT", ""),
        mode=environment.get("TALLI_COMPANY_TAX_REHEARSAL_MODE", ""),
        scope=environment.get("TALLI_MASKINPORTEN_SCOPE", ""),
        system_user_org=environment.get("TALLI_MASKINPORTEN_SYSTEM_USER_ORG", ""),
        external_reference=environment.get("TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF", ""),
    )
    io = LocalCompanyTaxRehearsal(environment, client_factory=client_factory, generate=generate,
        validate=validate, real_client=client_factory is _client)
    return local_rehearsal_summary(await rehearse_company_tax_return(configuration, io, sleep=sleep))


def main():
    os.umask(0o077)
    try:
        print(json.dumps(asyncio.run(run()), ensure_ascii=False))
    except Exception as error:
        if isinstance(error, CompanyTaxReturnAuthorityError):
            result = {"ok": False, **error.evidence()}
        else:
            message = str(error) if isinstance(error, ValueError) and str(error).startswith("TALLI_") else "Local configuration or payload is invalid."
            result = {"ok": False, "code": "local_configuration_or_payload_error", "status": None, "message": message}
        print(json.dumps(result), file=sys.stderr)
        return 1
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
