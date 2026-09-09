"""Frozen #153 prepare/resume rehearsal with original local intent and person confirmation."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import sys

from ._filing import _parse_json, case_income_year, check_private_key_file, git_commit, local_error, now, org_number, payload, read_evidence, required, sha256, validate_xml, write_evidence
from .company_tax_transport import (CompanyTaxReturnAuthorityError, CompanyTaxTransport,
    exchange_maskinporten_for_altinn_token, wait_for_clean_envelope, wait_for_feedback, wait_for_validation)

SCOPES = ("skatteetaten:formueinntekt/skattemelding", "altinn:instances.read", "altinn:instances.write")
SCHEMAS = ("skattemeldingUpersonlig_v5_ekstern.xsd", "naeringsspesifikasjon_v6_ekstern.xsd", "skattemeldingognaeringsspesifikasjonrequest_v2_kompakt.xsd")


def safe_summary(evidence):
    return {"ok": evidence["status"] in ("awaiting_person_confirmation", "submitted_and_receipted"),
        "status": evidence["status"], "environment": evidence["environment"],
        "companyOrgNumber": evidence["companyOrgNumber"], "incomeYear": evidence["incomeYear"],
        "instanceId": (evidence.get("instance") or {}).get("id"),
        "validationResult": (evidence.get("authorityValidation") or {}).get("result"),
        "confirmationUrl": evidence.get("confirmationUrl"), "receiptReference": (evidence.get("receipt") or {}).get("reference"),
        "archiveReference": (evidence.get("submission") or {}).get("archiveReference"), "evidenceFile": evidence["evidenceFile"]}


async def _client(environment, evidence):
    from ._grant import CliGrantConfiguration, request_token
    token = await request_token(CliGrantConfiguration.from_environment(environment))
    try:
        exchanged = await exchange_maskinporten_for_altinn_token(token.access_token)
        return CompanyTaxTransport(token.access_token, exchanged)
    finally:
        token.discard()


def _validate(documents, envelope, directory, validate):
    names = ("skattemelding.xml", "naeringsspesifikasjon.xml", "envelope.xml")
    validate(dict(zip(names, (documents["skattemeldingXml"], documents["naeringsspesifikasjonXml"], envelope))),
        dict(zip(names, (directory / name for name in SCHEMAS))))


async def run(environment=None, *, client_factory=_client, generate=payload, validate=validate_xml, sleep=asyncio.sleep):
    environment = os.environ if environment is None else environment
    if required(environment, "TALLI_COMPANY_TAX_APPROVED_TEST_WRITE") != "true":
        raise ValueError("TALLI_COMPANY_TAX_APPROVED_TEST_WRITE must be exactly true.")
    if required(environment, "TALLI_MASKINPORTEN_ENVIRONMENT") != "test":
        raise ValueError("The company-tax authority rehearsal refuses every environment except test.")
    mode = required(environment, "TALLI_COMPANY_TAX_REHEARSAL_MODE")
    if mode not in ("prepare", "resume"):
        raise ValueError("TALLI_COMPANY_TAX_REHEARSAL_MODE must be prepare or resume.")
    scope = required(environment, "TALLI_MASKINPORTEN_SCOPE")
    if set(filter(None, scope.split(" "))) != set(SCOPES):
        raise ValueError("The company-tax rehearsal requires exactly its three existing scopes.")
    evidence_path = Path(required(environment, "TALLI_COMPANY_TAX_EVIDENCE_PATH")).resolve()
    system_org = org_number(required(environment, "TALLI_MASKINPORTEN_SYSTEM_USER_ORG"))
    external_ref = environment.get("TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF", "").strip() or None
    prior = read_evidence(evidence_path)
    case, xsd = None, None
    if mode == "prepare":
        case_path = Path(required(environment, "TALLI_COMPANY_TAX_CASE_PATH")).resolve()
        xsd = Path(required(environment, "TALLI_SKATTE_XSD_DIR")).resolve()
        case = _parse_json(case_path.read_text())
        company = case.get("company") or {}
        organization = org_number(str(company.get("orgNumber", "")))
        year = case_income_year(company.get("incomeYear", float("nan")))
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
            prior.update(codeCommit=git_commit(), evidenceFile=evidence_path.name)
            write_evidence(evidence_path, prior)
            return safe_summary(prior)
        evidence = prior or {"schemaVersion": 2, "status": "prepared", "environment": "test", "productionEnabled": False,
            "authority": "Skatteetaten company tax via Altinn TT02", "companyOrgNumber": organization,
            "companyName": str(company.get("name", "")), "incomeYear": year, "scope": scope,
            "systemUserResource": "app_skd_formueinntekt-skattemelding-v2", "systemUserExternalRef": external_ref,
            "caseFixture": case_path.name, "evidenceFile": evidence_path.name, "codeCommit": git_commit(),
            "payloadHashes": {}, "payloadFeedbackCodes": [], "localSchemaValidation": None,
            "preflightValidation": None, "authorityValidation": None, "instance": None,
            "confirmationUrl": None, "receipt": None, "submission": None, "secretsStored": False,
            "preparedAt": now(), "error": None}
        if evidence.get("schemaVersion") == 1:
            evidence["preflightValidation"], evidence["authorityValidation"] = evidence.get("authorityValidation"), None
        evidence.update(schemaVersion=2, authority="Skatteetaten company tax via Altinn TT02", scope=scope,
            systemUserResource="app_skd_formueinntekt-skattemelding-v2", systemUserExternalRef=external_ref,
            evidenceFile=evidence_path.name, codeCommit=git_commit())
        evidence.pop("evidencePath", None)
        write_evidence(evidence_path, evidence)
    else:
        if not prior or prior.get("environment") != "test" or prior.get("productionEnabled") is not False:
            raise ValueError("Resume requires existing test-only company-tax evidence.")
        if prior.get("companyOrgNumber") != system_org:
            raise ValueError("Resume organization must equal the system-user organization.")
        if type(prior.get("incomeYear")) not in (int, float) or not (prior.get("instance") or {}).get("id"):
            raise ValueError("Resume evidence is missing year or instance id.")
        prior["incomeYear"] = case_income_year(prior["incomeYear"])
        if prior.get("status") not in ("awaiting_person_confirmation", "submitted_and_receipted"):
            raise ValueError("Resume evidence is not awaiting person confirmation.")
        evidence = prior
        if evidence["status"] == "submitted_and_receipted":
            evidence.update(codeCommit=git_commit(), evidenceFile=evidence_path.name)
            write_evidence(evidence_path, evidence)
            return safe_summary(evidence)
    if client_factory is _client:
        check_private_key_file(environment)
    try:
        client = await client_factory(environment, evidence)
        if mode == "resume":
            receipt = await wait_for_feedback(client, instance_id=evidence["instance"]["id"], sleep=sleep)
            instance = await client.get_instance(instance_id=evidence["instance"]["id"])
            evidence["receipt"] = {"dataId": receipt["dataId"], "dataType": receipt["dataType"],
                "contentType": receipt["contentType"], "byteLength": receipt["sizeBytes"],
                "contentSha256": sha256(receipt["receiptXml"]), "reference": receipt["reference"]}
            evidence["submission"] = {"submitted": True, "processTask": instance["processTask"],
                "processEndedAt": instance["processEndedAt"], "archived": instance["archived"],
                "archivedAt": instance["archivedAt"], "archiveReference": receipt["archiveReference"]}
            evidence.update(status="submitted_and_receipted", receiptRetrievedAt=now(), error=None, codeCommit=git_commit())
            write_evidence(evidence_path, evidence)
            return safe_summary(evidence)
        if evidence["status"] == "awaiting_person_confirmation" or (evidence.get("instance") or {}).get("confirmationPrepared"):
            prepared = await client.advance_to_confirmation(instance_id=evidence["instance"]["id"])
            evidence["instance"].update(confirmationPrepared=True, processTask=prepared["processTask"])
            evidence.update(status="awaiting_person_confirmation", confirmationUrl=client.get_owner_confirmation_url(instance_id=evidence["instance"]["id"]), error=None)
            write_evidence(evidence_path, evidence)
            return safe_summary(evidence)
        identity = {"income_year": evidence["incomeYear"], "company_org_number": evidence["companyOrgNumber"]}
        current = await client.fetch_current(**identity)
        documents = generate("company_tax", {"companyOrgNumber": evidence["companyOrgNumber"],
            "companyPartyNumber": current["partyNumber"], "incomeYear": evidence["incomeYear"],
            "annualData": case.get("annualData"), "ledgerEntries": case.get("ledgerEntries") or [], "holdingActions": case.get("holdingActions") or []})
        envelope_input = {"skattemeldingXml": documents["skattemeldingXml"], "naeringsspesifikasjonXml": documents["naeringsspesifikasjonXml"],
            "companyOrgNumber": evidence["companyOrgNumber"], "incomeYear": evidence["incomeYear"], "createdBy": "Talli"}
        validation_envelope = generate("company_tax_validation_envelope", envelope_input)["envelopeXml"]
        _validate(documents, validation_envelope, xsd, validate)
        corrected = {"skattemelding": sha256(documents["skattemeldingXml"]), "naeringsspesifikasjon": sha256(documents["naeringsspesifikasjonXml"]),
            "validationEnvelope": sha256(validation_envelope)}
        changed = any((evidence.get("payloadHashes") or {}).get(k) != v for k, v in corrected.items())
        repairing = changed and evidence["status"] == "failed_blocked" and "UgyldigPartsnummer" in (evidence.get("authorityValidation") or {}).get("failureReasons", []) and (
            (evidence.get("instance") or {}).get("processTask") == "data" and (evidence.get("instance") or {}).get("envelopeUploaded") is True)
        if changed and evidence.get("instance") and not repairing:
            raise ValueError("Existing instance belongs to a different payload; choose a new evidence path.")
        if changed or (evidence.get("preflightValidation") or {}).get("result") != "validertOK":
            result = await client.validate_test(**identity, envelope_xml=validation_envelope)
            preflight = generate("company_tax_validation_summary", result)
            evidence["preflightValidation"] = preflight
            if preflight["result"] != "validertOK":
                evidence["status"] = "preflight_validation_failed"
                write_evidence(evidence_path, evidence)
                raise ValueError("Preflight validation did not accept the corrected payload.")
        envelope = generate("company_tax_envelope", envelope_input | {"currentDocumentReference": current["documentReference"]})["envelopeXml"]
        _validate(documents, envelope, xsd, validate)
        envelope_hash = sha256(envelope)
        old_hash = (evidence.get("payloadHashes") or {}).get("submissionEnvelope")
        envelope_changed = bool(old_hash) and old_hash != envelope_hash
        reference_hash = sha256(current["documentReference"])
        if evidence.get("currentDocumentReferenceHash") and evidence["currentDocumentReferenceHash"] != reference_hash:
            raise ValueError("Current reference changed for an existing prepared instance.")
        evidence.update(payloadHashes=corrected | {"submissionEnvelope": envelope_hash},
            payloadFeedbackCodes=sorted(v["code"] for v in documents["feedback"]),
            localSchemaValidation={"status": "passed", "schemas": list(SCHEMAS)},
            currentDocumentReferenceHash=reference_hash, error=None)
        write_evidence(evidence_path, evidence)
        if repairing or envelope_changed:
            if not (evidence.get("instance") or {}).get("envelopeDataId"):
                raise ValueError("Existing instance is missing its envelope data id.")
            replaced = await client.replace_envelope(instance_id=evidence["instance"]["id"], data_id=evidence["instance"]["envelopeDataId"], envelope_xml=envelope)
            evidence["instance"].update(envelopeDataId=replaced["dataId"], fileScanResult=replaced["fileScanResult"],
                validationJobId=None, validationJobStatus=None, confirmationPrepared=False, processTask="data")
            evidence.update(authorityValidation=None, validationResponseBytes=None, validatedAt=None, status="envelope_uploaded")
            write_evidence(evidence_path, evidence)
        if not evidence.get("instance"):
            created = await client.create_instance(**identity)
            evidence["instance"] = {"id": created["id"], "envelopeUploaded": False, "envelopeDataId": None,
                "validationJobId": None, "confirmationPrepared": False, "processTask": "data"}
            evidence["status"] = "instance_created"
            write_evidence(evidence_path, evidence)
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
            write_evidence(evidence_path, evidence)
        await wait_for_clean_envelope(client, instance["id"], sleep=sleep)
        instance["fileScanResult"], evidence["status"] = "Clean", "envelope_clean"
        write_evidence(evidence_path, evidence)
        if not instance.get("validationJobId"):
            job = await client.start_validation(**identity, instance_id=instance["id"])
            instance.update(validationJobId=job["jobId"], validationJobStatus=job["status"])
            evidence["status"] = "validation_started"
            write_evidence(evidence_path, evidence)
        result = await wait_for_validation(client, **identity, job_id=instance["validationJobId"], sleep=sleep)
        validation = generate("company_tax_validation_summary", result)
        evidence.update(authorityValidation=validation, validationResponseBytes=len(result["resultXml"].encode()), validatedAt=now())
        if validation["result"] != "validertOK":
            evidence["status"] = "validation_failed"
            write_evidence(evidence_path, evidence)
            raise ValueError("Altinn validation did not accept the payload.")
        evidence["status"] = "validated"
        write_evidence(evidence_path, evidence)
        prepared = await client.advance_to_confirmation(instance_id=instance["id"])
        instance.update(confirmationPrepared=True, processTask=prepared["processTask"])
        evidence.update(status="awaiting_person_confirmation", confirmationUrl=client.get_owner_confirmation_url(instance_id=instance["id"]),
            confirmationPreparedAt=now(), error=None)
        write_evidence(evidence_path, evidence)
        return safe_summary(evidence)
    except Exception as error:
        if evidence["status"] != "awaiting_person_confirmation":
            evidence["status"] = "failed_retryable" if isinstance(error, CompanyTaxReturnAuthorityError) and error.retryable else "failed_blocked"
        evidence["error"] = error.evidence() if isinstance(error, CompanyTaxReturnAuthorityError) else local_error("COMPANY_TAX")
        write_evidence(evidence_path, evidence)
        raise


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
