"""Accounts owns test-only rehearsal gates, durable checkpoints and resume decisions."""
from __future__ import annotations

import hashlib
import math
import re

from .numbers import number
from .public import AnnualAccountsAuthorityError, AnnualAccountsRehearsalConfiguration, AnnualAccountsRehearsalIO

SCOPE = "altinn:instances.read altinn:instances.write"


def _required(value, name):
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is required.")
    return value


def _organization(value):
    if not re.fullmatch(r"[0-9]{9}", value):
        raise ValueError("Invalid organization number.")
    return value


def _case_year(value):
    parsed = number(value)
    if not math.isfinite(parsed) or not parsed.is_integer():
        raise ValueError("Authority case income year is invalid.")
    return int(parsed)


def _sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _local_error():
    return {"code": "ANNUAL_ACCOUNTS_LOCAL_OR_RESPONSE_ERROR", "status": None, "correlationId": None,
            "retryable": False, "message": "Local configuration, payload or authority response is invalid."}


def _reconciliation_error():
    return AnnualAccountsAuthorityError(
        "An earlier authority operation may have completed. Reconcile the saved evidence before retrying.",
        code="ANNUAL_ACCOUNTS_RECONCILIATION_REQUIRED", retryable=False)


def _legacy_ambiguous(prior):
    if prior.get("operationJournalVersion") == 1:
        return False
    instance = prior.get("instance") or {}
    if not instance:
        return True
    return (not instance.get("locked") and instance.get("mainFormUploaded")
        and instance.get("companyAccountsUploaded")
        and prior.get("status") not in ("company_accounts_uploaded", "validation_failed"))


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


async def run(configuration: AnnualAccountsRehearsalConfiguration, io: AnnualAccountsRehearsalIO):
    if _required(configuration.approved_test_write, "TALLI_ANNUAL_ACCOUNTS_APPROVED_TEST_WRITE") != "true":
        raise ValueError("TALLI_ANNUAL_ACCOUNTS_APPROVED_TEST_WRITE must be exactly true.")
    if _required(configuration.authority_environment, "TALLI_MASKINPORTEN_ENVIRONMENT") != "test":
        raise ValueError("The annual-accounts authority rehearsal refuses every environment except test.")
    scope = _required(configuration.scope, "TALLI_MASKINPORTEN_SCOPE")
    if scope != SCOPE:
        raise ValueError("The annual-accounts authority rehearsal requires its exact read/write scopes.")
    with io.exclusive_evidence():
        return await _run_owned(configuration, io, scope)


async def _run_owned(configuration, io, scope):
    case = io.load_case()
    if case.get("synthetic") is not True or case.get("environment") != "test":
        raise ValueError("Annual-accounts rehearsal requires an explicitly synthetic test case.")
    company = case.get("company") or {}
    organization = _organization(str(company.get("orgNumber", "")))
    year = _case_year(company.get("incomeYear", float("nan")))
    if organization != _required(configuration.system_user_org, "TALLI_MASKINPORTEN_SYSTEM_USER_ORG"):
        raise ValueError("Annual-accounts case organization must equal the system-user organization.")
    documents = io.generate("annual_accounts", {"incomeYear": year, "annualData": case.get("annualData"),
        "ledgerEntries": case.get("ledgerEntries") or [], "companyOrgNumber": organization,
        "companyName": str(company.get("name", "")), "contactEmail": _required(configuration.contact_email, "TALLI_ANNUAL_ACCOUNTS_CONTACT_EMAIL"),
        "approvalDate": _required(configuration.approval_date, "TALLI_ANNUAL_ACCOUNTS_APPROVAL_DATE"),
        "confirmingRepresentative": _required(configuration.confirming_representative, "TALLI_ANNUAL_ACCOUNTS_CONFIRMING_REPRESENTATIVE")})
    io.validate_documents({"hovedskjema.xml": documents["mainFormXml"], "selskapsregnskap.xml": documents["companyAccountsXml"]})
    hashes = {"mainForm": _sha256(documents["mainFormXml"]), "companyAccounts": _sha256(documents["companyAccountsXml"])}
    prior = io.load_evidence()
    if prior and (prior.get("environment") != "test" or prior.get("companyOrgNumber") != organization
        or prior.get("incomeYear") != year or any((prior.get("payloadHashes") or {}).get(k) != v for k, v in hashes.items())):
        raise ValueError("Existing annual-accounts evidence belongs to a different payload; choose a new evidence path.")
    if prior and ("pendingAuthorityOperation" in prior or prior.get("status") == "reconciliation_required"):
        raise _reconciliation_error()
    if prior and prior.get("status") != "submitted_and_archived" and _legacy_ambiguous(prior):
        raise _reconciliation_error()
    if prior and prior.get("status") == "submitted_and_archived":
        prior.update(codeCommit=io.revision(), evidenceFile=io.evidence_filename())
        prior.pop("evidencePath", None)
        io.save_evidence(prior)
        return safe_summary(prior)
    evidence = prior or {"schemaVersion": 1, "status": "prepared", "environment": "test", "productionEnabled": False,
        "authority": "Brønnøysundregistrene RR0002 via Altinn TT02", "companyOrgNumber": organization,
        "companyName": str(company.get("name", "")), "incomeYear": year, "scope": scope,
        "systemUserResource": "app_brg_aarsregnskap-vanlig-202406",
        "systemUserRequestId": configuration.system_user_request_id.strip() or None,
        "systemUserExternalRef": _required(configuration.external_reference, "TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF"),
        "caseFixture": io.case_filename(), "evidenceFile": io.evidence_filename(), "codeCommit": io.revision(),
        "payloadHashes": hashes, "payloadFeedbackCodes": sorted(v["code"] for v in documents["feedback"]),
        "localXmlValidation": {"status": "well_formed"}, "instance": None, "validation": None, "signingUrl": None,
        "signed": False, "submitted": False, "submission": None, "secretsStored": False, "preparedAt": io.timestamp(), "error": None}
    evidence.setdefault("operationJournalVersion", 1)
    evidence.update(codeCommit=io.revision(), evidenceFile=io.evidence_filename())
    evidence.pop("evidencePath", None)
    io.save_evidence(evidence)
    client = await io.connect(evidence)
    pending_operation = None
    try:
        if evidence["status"] == "locked_for_person_signing" or (evidence.get("instance") or {}).get("locked") is True:
            submission = await client.get_submission_evidence(instance_id=evidence["instance"]["id"])
            if not submission["submitted"] and not evidence.get("signingUrl"):
                handoff = await client.get_signing_handoff(instance_id=evidence["instance"]["id"])
                evidence["signingUrl"] = handoff["signingUrl"]
            evidence.update(submission=submission, signed=submission["signed"], submitted=submission["submitted"],
                status="submitted_and_archived" if submission["submitted"] else "locked_for_person_signing",
                submittedAt=submission["processEndedAt"] if submission["submitted"] else None, error=None)
            io.save_evidence(evidence)
            return safe_summary(evidence)
        if not evidence["instance"]:
            pending_operation = {"operation": "create_instance", "instanceId": None, "startedAt": io.timestamp()}
            evidence["pendingAuthorityOperation"] = pending_operation
            io.save_evidence(evidence)
            created = await client.create_instance(company_org_number=organization)
            evidence["instance"] = {"id": created["id"], "dataIds": created["dataIds"],
                "createdProcessTask": created["processTask"], "mainFormUploaded": False, "companyAccountsUploaded": False, "locked": False}
            evidence["status"] = "instance_created"
            evidence.pop("pendingAuthorityOperation")
            io.save_evidence(evidence)
            pending_operation = None
        instance = evidence["instance"]
        if not instance["mainFormUploaded"]:
            await client.upload_main_form(instance_id=instance["id"], data_id=instance["dataIds"]["mainForm"], xml=documents["mainFormXml"])
            instance["mainFormUploaded"], evidence["status"] = True, "main_form_uploaded"
            io.save_evidence(evidence)
        if not instance["companyAccountsUploaded"]:
            await client.upload_company_accounts(instance_id=instance["id"], data_id=instance["dataIds"]["companyAccounts"], xml=documents["companyAccountsXml"])
            instance["companyAccountsUploaded"], evidence["status"] = True, "company_accounts_uploaded"
            io.save_evidence(evidence)
        validation = await client.validate_instance(instance_id=instance["id"])
        evidence.update(validation=validation, validatedAt=io.timestamp())
        if validation["hasErrors"]:
            evidence["status"] = "validation_failed"
            io.save_evidence(evidence)
            raise ValueError("Altinn RR0002 validation failed.")
        evidence["status"] = "validated"
        io.save_evidence(evidence)
        if not instance["locked"]:
            pending_operation = {"operation": "lock_for_signing", "instanceId": instance["id"], "startedAt": io.timestamp()}
            evidence["pendingAuthorityOperation"] = pending_operation
            io.save_evidence(evidence)
            locked = await client.lock_for_signing(instance_id=instance["id"])
            instance.update(locked=True, lockedProcessTask=locked["processTask"])
            evidence["status"] = "locked"
            evidence.pop("pendingAuthorityOperation")
            io.save_evidence(evidence)
            pending_operation = None
        handoff = await client.get_signing_handoff(instance_id=instance["id"])
        evidence.update(signingUrl=handoff["signingUrl"], signed=False, submitted=False,
            status="locked_for_person_signing", lockedAt=io.timestamp(), error=None)
        io.save_evidence(evidence)
        return safe_summary(evidence)
    except Exception as error:
        if pending_operation is not None:
            pending_operation["failure"] = error.evidence() if isinstance(error, AnnualAccountsAuthorityError) else _local_error()
            evidence.update(pendingAuthorityOperation=pending_operation, status="reconciliation_required",
                error=_reconciliation_error().evidence())
            io.save_evidence(evidence)
            raise _reconciliation_error() from None
        if evidence["status"] != "validation_failed":
            evidence["status"] = "failed_retryable" if isinstance(error, AnnualAccountsAuthorityError) and error.retryable else "failed_blocked"
        evidence["error"] = error.evidence() if isinstance(error, AnnualAccountsAuthorityError) else _local_error()
        io.save_evidence(evidence)
        raise
