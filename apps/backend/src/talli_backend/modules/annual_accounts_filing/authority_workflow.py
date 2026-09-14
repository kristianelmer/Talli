"""Accounts preparation order and validation failure before human-signing handoff."""
from .public import AnnualAccountsAuthorityError


async def prepare(client, *, company_org_number, main_form_xml, company_accounts_xml):
    instance = await client.create_instance(company_org_number=company_org_number)
    await client.upload_main_form(instance_id=instance["id"], data_id=instance["dataIds"]["mainForm"], xml=main_form_xml)
    await client.upload_company_accounts(instance_id=instance["id"], data_id=instance["dataIds"]["companyAccounts"], xml=company_accounts_xml)
    validation = await client.validate_instance(instance_id=instance["id"])
    if validation["hasErrors"]:
        raise AnnualAccountsAuthorityError("Annual accounts validation must pass before locking.",
            code="ANNUAL_ACCOUNTS_VALIDATION_FAILED", validation_codes=sorted({v["code"] for v in validation["issues"] if v["severity"].lower() == "error"}))
    await client.lock_for_signing(instance_id=instance["id"])
    return await client.get_signing_handoff(instance_id=instance["id"]) | {"dataIds": instance["dataIds"], "validation": validation}
