"""Company Tax owns durable rehearsal intent and test-only prepare/resume decisions."""
from __future__ import annotations

import hashlib
import math
import re

from .numbers import number
from .public import CompanyTaxRehearsalConfiguration, CompanyTaxRehearsalIO, CompanyTaxReturnAuthorityError
from .authority_workflow import wait_for_clean_envelope, wait_for_feedback, wait_for_validation

SCOPES = ("skatteetaten:formueinntekt/skattemelding", "altinn:instances.read", "altinn:instances.write")

SCHEMAS = ("skattemeldingUpersonlig_v5_ekstern.xsd", "naeringsspesifikasjon_v6_ekstern.xsd", "skattemeldingognaeringsspesifikasjonrequest_v2_kompakt.xsd")


def _required(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is required.")
    return value


def _organization(value: str) -> str:
    if not re.fullmatch(r"[0-9]{9}", value):
        raise ValueError("Invalid organization number.")
    return value


def _case_year(value: object) -> int:
    try:
        parsed = number(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Authority case income year is invalid.") from None
    if not math.isfinite(parsed) or not parsed.is_integer():
        raise ValueError("Authority case income year is invalid.")
    return int(parsed)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _local_error():
    return {"code": "COMPANY_TAX_LOCAL_OR_RESPONSE_ERROR", "status": None, "correlationId": None,
            "retryable": False, "message": "Local configuration, payload or authority response is invalid."}


def safe_summary(evidence):
    return {"ok": evidence["status"] in ("awaiting_person_confirmation", "submitted_and_receipted"),
        "status": evidence["status"], "environment": evidence["environment"],
        "companyOrgNumber": evidence["companyOrgNumber"], "incomeYear": evidence["incomeYear"],
        "instanceId": (evidence.get("instance") or {}).get("id"),
        "validationResult": (evidence.get("authorityValidation") or {}).get("result"),
        "confirmationUrl": evidence.get("confirmationUrl"), "receiptReference": (evidence.get("receipt") or {}).get("reference"),
        "archiveReference": (evidence.get("submission") or {}).get("archiveReference"), "evidenceFile": evidence["evidenceFile"]}


async def run(configuration: CompanyTaxRehearsalConfiguration, io: CompanyTaxRehearsalIO, *, sleep):
    if _required(configuration.approved_test_write, "TALLI_COMPANY_TAX_APPROVED_TEST_WRITE") != "true":
        raise ValueError("TALLI_COMPANY_TAX_APPROVED_TEST_WRITE must be exactly true.")
    if _required(configuration.authority_environment, "TALLI_MASKINPORTEN_ENVIRONMENT") != "test":
        raise ValueError("The company-tax authority rehearsal refuses every environment except test.")
    mode = _required(configuration.mode, "TALLI_COMPANY_TAX_REHEARSAL_MODE")
    if mode not in ("prepare", "resume"):
        raise ValueError("TALLI_COMPANY_TAX_REHEARSAL_MODE must be prepare or resume.")
    scope = _required(configuration.scope, "TALLI_MASKINPORTEN_SCOPE")
    if set(filter(None, scope.split(" "))) != set(SCOPES):
        raise ValueError("The company-tax rehearsal requires exactly its three existing scopes.")
    io.select_evidence()
    system_org = _organization(_required(configuration.system_user_org, "TALLI_MASKINPORTEN_SYSTEM_USER_ORG"))
    external_ref = configuration.external_reference.strip() or None
    prior = io.load_evidence()
    case = None
    if mode == "prepare":
        case = io.load_case()
        company = case.get("company") or {}
        organization = _organization(str(company.get("orgNumber", "")))
        year = _case_year(company.get("incomeYear", float("nan")))
        if organization != system_org:
            raise ValueError("Company-tax case organization must equal the system-user organization.")
        if ((case.get("annualData") or {}).get("no_activity_confirmed") is not True
            or case.get("holdingActions") != []
            or any(not isinstance(v, dict) or v.get("entry_type") != "opening_balance"
                   for v in ([] if case.get("ledgerEntries") is None else case["ledgerEntries"]))):
            raise ValueError("Company-tax rehearsal is limited to the approved no-activity case.")
        if prior and (prior.get("environment") != "test" or prior.get("productionEnabled") is not False
            or prior.get("companyOrgNumber") != organization or prior.get("incomeYear") != year):
            raise ValueError("Existing evidence belongs to a different company or year; choose a new evidence path.")
        if prior and prior.get("status") == "submitted_and_receipted":
            prior.update(codeCommit=io.revision(), evidenceFile=io.evidence_filename())
            io.save_evidence(prior)
            return safe_summary(prior)
        evidence = prior or {"schemaVersion": 2, "status": "prepared", "environment": "test", "productionEnabled": False,
            "authority": "Skatteetaten company tax via Altinn TT02", "companyOrgNumber": organization,
            "companyName": str(company.get("name", "")), "incomeYear": year, "scope": scope,
            "systemUserResource": "app_skd_formueinntekt-skattemelding-v2", "systemUserExternalRef": external_ref,
            "caseFixture": io.case_filename(), "evidenceFile": io.evidence_filename(), "codeCommit": io.revision(),
            "payloadHashes": {}, "payloadFeedbackCodes": [], "localSchemaValidation": None,
            "preflightValidation": None, "authorityValidation": None, "instance": None,
            "confirmationUrl": None, "receipt": None, "submission": None, "secretsStored": False,
            "preparedAt": io.timestamp(), "error": None}
        if evidence.get("schemaVersion") == 1:
            evidence["preflightValidation"], evidence["authorityValidation"] = evidence.get("authorityValidation"), None
        evidence.update(schemaVersion=2, authority="Skatteetaten company tax via Altinn TT02", scope=scope,
            systemUserResource="app_skd_formueinntekt-skattemelding-v2", systemUserExternalRef=external_ref,
            evidenceFile=io.evidence_filename(), codeCommit=io.revision())
        evidence.pop("evidencePath", None)
        io.save_evidence(evidence)
    else:
        if not prior or prior.get("environment") != "test" or prior.get("productionEnabled") is not False:
            raise ValueError("Resume requires existing test-only company-tax evidence.")
        if prior.get("companyOrgNumber") != system_org:
            raise ValueError("Resume organization must equal the system-user organization.")
        if type(prior.get("incomeYear")) not in (int, float) or not (prior.get("instance") or {}).get("id"):
            raise ValueError("Resume evidence is missing year or instance id.")
        prior["incomeYear"] = _case_year(prior["incomeYear"])
        if prior.get("status") not in ("awaiting_person_confirmation", "submitted_and_receipted"):
            raise ValueError("Resume evidence is not awaiting person confirmation.")
        evidence = prior
        if evidence["status"] == "submitted_and_receipted":
            evidence.update(codeCommit=io.revision(), evidenceFile=io.evidence_filename())
            io.save_evidence(evidence)
            return safe_summary(evidence)
    io.prepare_credentials()
    try:
        client = await io.connect(evidence)
        if mode == "resume":
            receipt = await wait_for_feedback(client, instance_id=evidence["instance"]["id"], sleep=sleep)
            instance = await client.get_instance(instance_id=evidence["instance"]["id"])
            evidence["receipt"] = {"dataId": receipt["dataId"], "dataType": receipt["dataType"],
                "contentType": receipt["contentType"], "byteLength": receipt["sizeBytes"],
                "contentSha256": _sha256(receipt["receiptXml"]), "reference": receipt["reference"]}
            evidence["submission"] = {"submitted": True, "processTask": instance["processTask"],
                "processEndedAt": instance["processEndedAt"], "archived": instance["archived"],
                "archivedAt": instance["archivedAt"], "archiveReference": receipt["archiveReference"]}
            evidence.update(status="submitted_and_receipted", receiptRetrievedAt=io.timestamp(), error=None, codeCommit=io.revision())
            io.save_evidence(evidence)
            return safe_summary(evidence)
        if evidence["status"] == "awaiting_person_confirmation" or (evidence.get("instance") or {}).get("confirmationPrepared"):
            prepared = await client.advance_to_confirmation(instance_id=evidence["instance"]["id"])
            evidence["instance"].update(confirmationPrepared=True, processTask=prepared["processTask"])
            evidence.update(status="awaiting_person_confirmation", confirmationUrl=client.get_owner_confirmation_url(instance_id=evidence["instance"]["id"]), error=None)
            io.save_evidence(evidence)
            return safe_summary(evidence)
        identity = {"income_year": evidence["incomeYear"], "company_org_number": evidence["companyOrgNumber"]}
        current = await client.fetch_current(**identity)
        documents = io.generate("company_tax", {"companyOrgNumber": evidence["companyOrgNumber"],
            "companyPartyNumber": current["partyNumber"], "incomeYear": evidence["incomeYear"],
            "annualData": case.get("annualData"), "ledgerEntries": case.get("ledgerEntries") or [], "holdingActions": case.get("holdingActions") or []})
        envelope_input = {"skattemeldingXml": documents["skattemeldingXml"], "naeringsspesifikasjonXml": documents["naeringsspesifikasjonXml"],
            "companyOrgNumber": evidence["companyOrgNumber"], "incomeYear": evidence["incomeYear"], "createdBy": "Talli"}
        validation_envelope = io.generate("company_tax_validation_envelope", envelope_input)["envelopeXml"]
        io.validate_documents(documents, validation_envelope, SCHEMAS)
        corrected = {"skattemelding": _sha256(documents["skattemeldingXml"]), "naeringsspesifikasjon": _sha256(documents["naeringsspesifikasjonXml"]),
            "validationEnvelope": _sha256(validation_envelope)}
        changed = any((evidence.get("payloadHashes") or {}).get(k) != v for k, v in corrected.items())
        repairing = changed and evidence["status"] == "failed_blocked" and "UgyldigPartsnummer" in (evidence.get("authorityValidation") or {}).get("failureReasons", []) and (
            (evidence.get("instance") or {}).get("processTask") == "data" and (evidence.get("instance") or {}).get("envelopeUploaded") is True)
        if changed and evidence.get("instance") and not repairing:
            raise ValueError("Existing instance belongs to a different payload; choose a new evidence path.")
        if changed or (evidence.get("preflightValidation") or {}).get("result") != "validertOK":
            result = await client.validate_test(**identity, envelope_xml=validation_envelope)
            preflight = io.generate("company_tax_validation_summary", result)
            evidence["preflightValidation"] = preflight
            if preflight["result"] != "validertOK":
                evidence["status"] = "preflight_validation_failed"
                io.save_evidence(evidence)
                raise ValueError("Preflight validation did not accept the corrected payload.")
        envelope = io.generate("company_tax_envelope", envelope_input | {"currentDocumentReference": current["documentReference"]})["envelopeXml"]
        io.validate_documents(documents, envelope, SCHEMAS)
        envelope_hash = _sha256(envelope)
        old_hash = (evidence.get("payloadHashes") or {}).get("submissionEnvelope")
        envelope_changed = bool(old_hash) and old_hash != envelope_hash
        reference_hash = _sha256(current["documentReference"])
        if evidence.get("currentDocumentReferenceHash") and evidence["currentDocumentReferenceHash"] != reference_hash:
            raise ValueError("Current reference changed for an existing prepared instance.")
        evidence.update(payloadHashes=corrected | {"submissionEnvelope": envelope_hash},
            payloadFeedbackCodes=sorted(v["code"] for v in documents["feedback"]),
            localSchemaValidation={"status": "passed", "schemas": list(SCHEMAS)},
            currentDocumentReferenceHash=reference_hash, error=None)
        io.save_evidence(evidence)
        if repairing or envelope_changed:
            if not (evidence.get("instance") or {}).get("envelopeDataId"):
                raise ValueError("Existing instance is missing its envelope data id.")
            replaced = await client.replace_envelope(instance_id=evidence["instance"]["id"], data_id=evidence["instance"]["envelopeDataId"], envelope_xml=envelope)
            evidence["instance"].update(envelopeDataId=replaced["dataId"], fileScanResult=replaced["fileScanResult"],
                validationJobId=None, validationJobStatus=None, confirmationPrepared=False, processTask="data")
            evidence.update(authorityValidation=None, validationResponseBytes=None, validatedAt=None, status="envelope_uploaded")
            io.save_evidence(evidence)
        if not evidence.get("instance"):
            created = await client.create_instance(**identity)
            evidence["instance"] = {"id": created["id"], "envelopeUploaded": False, "envelopeDataId": None,
                "validationJobId": None, "confirmationPrepared": False, "processTask": "data"}
            evidence["status"] = "instance_created"
            io.save_evidence(evidence)
        instance = evidence["instance"]
        if not instance["envelopeUploaded"]:
            stored = await client.get_instance(instance_id=instance["id"])
            existing = [v for v in stored["data"] if v["dataType"] == "skattemeldingOgNaeringsspesifikasjon"]
            if len(existing) > 1:
                raise ValueError("Instance contains duplicate submission envelopes.")
            if existing:
                instance.update(envelopeUploaded=True, envelopeDataId=existing[0]["id"])
            else:
                uploaded = await client.upload_envelope(instance_id=instance["id"], envelope_xml=envelope)
                instance.update(envelopeUploaded=True, envelopeDataId=uploaded["dataId"])
            evidence["status"] = "envelope_uploaded"
            io.save_evidence(evidence)
        await wait_for_clean_envelope(client, instance["id"], sleep=sleep)
        instance["fileScanResult"], evidence["status"] = "Clean", "envelope_clean"
        io.save_evidence(evidence)
        if not instance.get("validationJobId"):
            job = await client.start_validation(**identity, instance_id=instance["id"])
            instance.update(validationJobId=job["jobId"], validationJobStatus=job["status"])
            evidence["status"] = "validation_started"
            io.save_evidence(evidence)
        result = await wait_for_validation(client, **identity, job_id=instance["validationJobId"], sleep=sleep)
        validation = io.generate("company_tax_validation_summary", result)
        evidence.update(authorityValidation=validation, validationResponseBytes=len(result["resultXml"].encode()), validatedAt=io.timestamp())
        if validation["result"] != "validertOK":
            evidence["status"] = "validation_failed"
            io.save_evidence(evidence)
            raise ValueError("Altinn validation did not accept the payload.")
        evidence["status"] = "validated"
        io.save_evidence(evidence)
        prepared = await client.advance_to_confirmation(instance_id=instance["id"])
        instance.update(confirmationPrepared=True, processTask=prepared["processTask"])
        evidence.update(status="awaiting_person_confirmation", confirmationUrl=client.get_owner_confirmation_url(instance_id=instance["id"]),
            confirmationPreparedAt=io.timestamp(), error=None)
        io.save_evidence(evidence)
        return safe_summary(evidence)
    except Exception as error:
        if evidence["status"] != "awaiting_person_confirmation":
            evidence["status"] = "failed_retryable" if isinstance(error, CompanyTaxReturnAuthorityError) and error.retryable else "failed_blocked"
        evidence["error"] = error.evidence() if isinstance(error, CompanyTaxReturnAuthorityError) else _local_error()
        io.save_evidence(evidence)
        raise
