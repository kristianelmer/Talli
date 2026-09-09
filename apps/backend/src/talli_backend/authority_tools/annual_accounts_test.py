"""Frozen #152 standalone RR0002 rehearsal; no provider call without explicit test gate."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import sys

from ._filing import (FilingToolError, _parse_json, case_income_year, git_commit, local_error, now, org_number, payload,
    read_evidence, required, sha256, validate_xml, write_evidence)
from .annual_accounts_transport import AnnualAccountsAuthorityError, AnnualAccountsTransport, exchange_maskinporten_for_altinn_token

SCOPE = "altinn:instances.read altinn:instances.write"


def safe_summary(evidence):
    submission = evidence.get("submission") or {}
    return {"ok": evidence["status"] in ("locked_for_person_signing", "submitted_and_archived"),
        "status": evidence["status"], "environment": evidence["environment"],
        "companyOrgNumber": evidence["companyOrgNumber"], "incomeYear": evidence["incomeYear"],
        "instanceId": (evidence.get("instance") or {}).get("id"),
        "validationIssueCodes": [v["code"] for v in (evidence.get("validation") or {}).get("issues", [])],
        "signingUrl": evidence.get("signingUrl"), "signed": evidence.get("signed") is True,
        "submitted": evidence.get("submitted") is True,
        "receiptReference": (submission.get("receipt") or {}).get("reference"),
        "archiveReference": submission.get("archiveReference"), "evidenceFile": evidence["evidenceFile"]}


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
    if required(environment, "TALLI_ANNUAL_ACCOUNTS_APPROVED_TEST_WRITE") != "true":
        raise ValueError("TALLI_ANNUAL_ACCOUNTS_APPROVED_TEST_WRITE must be exactly true.")
    if required(environment, "TALLI_MASKINPORTEN_ENVIRONMENT") != "test":
        raise ValueError("The annual-accounts authority rehearsal refuses every environment except test.")
    scope = required(environment, "TALLI_MASKINPORTEN_SCOPE")
    if scope != SCOPE:
        raise ValueError("The annual-accounts authority rehearsal requires its exact read/write scopes.")
    case_path = Path(required(environment, "TALLI_ANNUAL_ACCOUNTS_CASE_PATH")).resolve()
    evidence_path = Path(required(environment, "TALLI_ANNUAL_ACCOUNTS_EVIDENCE_PATH")).resolve()
    case = _parse_json(case_path.read_text())
    if case.get("synthetic") is not True or case.get("environment") != "test":
        raise ValueError("Annual-accounts rehearsal requires an explicitly synthetic test case.")
    company = case.get("company") or {}
    organization = org_number(str(company.get("orgNumber", "")))
    year = case_income_year(company.get("incomeYear", float("nan")))
    if organization != required(environment, "TALLI_MASKINPORTEN_SYSTEM_USER_ORG"):
        raise ValueError("Annual-accounts case organization must equal the system-user organization.")
    documents = generate("annual_accounts", {"incomeYear": year, "annualData": case.get("annualData"),
        "ledgerEntries": case.get("ledgerEntries") or [], "companyOrgNumber": organization,
        "companyName": str(company.get("name", "")), "contactEmail": required(environment, "TALLI_ANNUAL_ACCOUNTS_CONTACT_EMAIL"),
        "approvalDate": required(environment, "TALLI_ANNUAL_ACCOUNTS_APPROVAL_DATE"),
        "confirmingRepresentative": required(environment, "TALLI_ANNUAL_ACCOUNTS_CONFIRMING_REPRESENTATIVE")})
    validate({"hovedskjema.xml": documents["mainFormXml"], "selskapsregnskap.xml": documents["companyAccountsXml"]})
    hashes = {"mainForm": sha256(documents["mainFormXml"]), "companyAccounts": sha256(documents["companyAccountsXml"])}
    prior = read_evidence(evidence_path)
    if prior and (prior.get("environment") != "test" or prior.get("companyOrgNumber") != organization
        or prior.get("incomeYear") != year or any((prior.get("payloadHashes") or {}).get(k) != v for k, v in hashes.items())):
        raise ValueError("Existing annual-accounts evidence belongs to a different payload; choose a new evidence path.")
    if prior and prior.get("status") == "submitted_and_archived":
        prior.update(codeCommit=git_commit(), evidenceFile=evidence_path.name)
        prior.pop("evidencePath", None)
        write_evidence(evidence_path, prior)
        return safe_summary(prior)
    evidence = prior or {"schemaVersion": 1, "status": "prepared", "environment": "test", "productionEnabled": False,
        "authority": "Brønnøysundregistrene RR0002 via Altinn TT02", "companyOrgNumber": organization,
        "companyName": str(company.get("name", "")), "incomeYear": year, "scope": scope,
        "systemUserResource": "app_brg_aarsregnskap-vanlig-202406",
        "systemUserRequestId": environment.get("TALLI_ANNUAL_ACCOUNTS_SYSTEM_USER_REQUEST_ID", "").strip() or None,
        "systemUserExternalRef": required(environment, "TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF"),
        "caseFixture": case_path.name, "evidenceFile": evidence_path.name, "codeCommit": git_commit(),
        "payloadHashes": hashes, "payloadFeedbackCodes": sorted(v["code"] for v in documents["feedback"]),
        "localXmlValidation": {"status": "well_formed"}, "instance": None, "validation": None, "signingUrl": None,
        "signed": False, "submitted": False, "submission": None, "secretsStored": False, "preparedAt": now(), "error": None}
    evidence.update(codeCommit=git_commit(), evidenceFile=evidence_path.name)
    evidence.pop("evidencePath", None)
    write_evidence(evidence_path, evidence)
    client = await client_factory(environment, evidence)
    try:
        if evidence["status"] == "locked_for_person_signing":
            submission = await client.get_submission_evidence(instance_id=evidence["instance"]["id"])
            evidence.update(submission=submission, signed=submission["signed"], submitted=submission["submitted"],
                status="submitted_and_archived" if submission["submitted"] else "locked_for_person_signing",
                submittedAt=submission["processEndedAt"] if submission["submitted"] else None, error=None)
            write_evidence(evidence_path, evidence)
            return safe_summary(evidence)
        if not evidence["instance"]:
            created = await client.create_instance(company_org_number=organization)
            evidence["instance"] = {"id": created["id"], "dataIds": created["dataIds"],
                "createdProcessTask": created["processTask"], "mainFormUploaded": False, "companyAccountsUploaded": False, "locked": False}
            evidence["status"] = "instance_created"
            write_evidence(evidence_path, evidence)
        instance = evidence["instance"]
        if not instance["mainFormUploaded"]:
            await client.upload_main_form(instance_id=instance["id"], data_id=instance["dataIds"]["mainForm"], xml=documents["mainFormXml"])
            instance["mainFormUploaded"], evidence["status"] = True, "main_form_uploaded"
            write_evidence(evidence_path, evidence)
        if not instance["companyAccountsUploaded"]:
            await client.upload_company_accounts(instance_id=instance["id"], data_id=instance["dataIds"]["companyAccounts"], xml=documents["companyAccountsXml"])
            instance["companyAccountsUploaded"], evidence["status"] = True, "company_accounts_uploaded"
            write_evidence(evidence_path, evidence)
        validation = await client.validate_instance(instance_id=instance["id"])
        evidence.update(validation=validation, validatedAt=now())
        if validation["hasErrors"]:
            evidence["status"] = "validation_failed"
            write_evidence(evidence_path, evidence)
            raise ValueError("Altinn RR0002 validation failed.")
        evidence["status"] = "validated"
        write_evidence(evidence_path, evidence)
        if not instance["locked"]:
            locked = await client.lock_for_signing(instance_id=instance["id"])
            instance.update(locked=True, lockedProcessTask=locked["processTask"])
            evidence["status"] = "locked"
            write_evidence(evidence_path, evidence)
        handoff = await client.get_signing_handoff(instance_id=instance["id"])
        evidence.update(signingUrl=handoff["signingUrl"], signed=False, submitted=False,
            status="locked_for_person_signing", lockedAt=now(), error=None)
        write_evidence(evidence_path, evidence)
        return safe_summary(evidence)
    except Exception as error:
        if evidence["status"] != "validation_failed":
            evidence["status"] = "failed_retryable" if isinstance(error, AnnualAccountsAuthorityError) and error.retryable else "failed_blocked"
        evidence["error"] = error.evidence() if isinstance(error, AnnualAccountsAuthorityError) else local_error("ANNUAL_ACCOUNTS")
        write_evidence(evidence_path, evidence)
        raise


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
