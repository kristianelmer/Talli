"""Frozen #152 RR0002 TT02 transport. A person, never this tool, signs."""
from __future__ import annotations
import json

from ._filing import FixedTransport, FilingToolError, data_id, instance_id, iso, obj, opaque, org_number, xml

BASE = "https://brg.apps.tt02.altinn.no/brg/aarsregnskap-vanlig-202406"
PLATFORM = "https://platform.tt02.altinn.no"


class AnnualAccountsAuthorityError(FilingToolError):
    def evidence(self):
        return super().evidence() | {"validationCodes": self.validation_codes}


async def exchange_maskinporten_for_altinn_token(token, *, environment="test", transport=None, timeout_ms=20_000):
    if environment not in ("test", "production"):
        raise ValueError("Annual accounts authority environment must be test or production.")
    host = PLATFORM if environment == "test" else "https://platform.altinn.no"
    request = FixedTransport("ANNUAL_ACCOUNTS", AnnualAccountsAuthorityError, transport=transport, timeout_ms=timeout_ms)
    raw, _, _, _ = await request._request(host+"/authentication/api/v1/exchange/maskinporten", "GET", token, accept="text/plain")
    return opaque(raw)


class AnnualAccountsTransport(FixedTransport):
    def __init__(self, altinn_access_token, *, environment="test", transport=None, timeout_ms=20_000):
        if environment != "test":
            raise ValueError("Annual accounts production authority transport is disabled.")
        self._token = opaque(altinn_access_token)
        super().__init__("ANNUAL_ACCOUNTS", AnnualAccountsAuthorityError,
            transport=transport, timeout_ms=timeout_ms, secrets=(self._token,))

    def _url(self, value):
        return f"{BASE}/instances/{instance_id(value)}"

    def _task(self, value):
        task = obj(obj(obj(value).get("process")).get("currentTask"))
        return self.safe(task.get("altinnTaskType") or task.get("elementId"), "unknown")

    def _elements(self, value, kind):
        elements = obj(value).get("data")
        return [obj(v) for v in elements if self.safe(obj(v).get("dataType")) == kind] if isinstance(elements, list) else []

    async def create_instance(self, *, company_org_number):
        _, result, _, _ = await self._request(BASE+"/instances/create", "POST", self._token,
            content_type="application/json", body=json.dumps({"instanceOwner": {"organisationNumber": org_number(company_org_number)}}, separators=(",", ":")))
        identifier = instance_id(self.safe(obj(result).get("id")))
        identifiers = {}
        for key, kind in (("mainForm", "Hovedskjema"), ("companyAccounts", "Underskjema")):
            matches = [self.safe(v.get("id")) for v in self._elements(result, kind)]
            matches = [v for v in matches if v]
            if len(matches) != 1:
                raise AnnualAccountsAuthorityError("Altinn did not create exactly one main form and company-accounts element.",
                    code="ANNUAL_ACCOUNTS_DATA_ELEMENTS_MISSING")
            identifiers[key] = data_id(matches[0])
        return {"id": identifier, "dataIds": identifiers, "processTask": self._task(result)}

    async def _upload(self, *, instance_id, data_id: str, xml: str):
        from ._filing import data_id as checked_id, xml as checked_xml
        identifier = checked_id(data_id)
        await self._request(self._url(instance_id)+f"/data/{identifier}", "PUT", self._token,
            content_type="application/xml", body=checked_xml(xml))
        return {"dataId": identifier, "uploaded": True}

    async def upload_main_form(self, **values):
        return await self._upload(**values)

    async def upload_company_accounts(self, **values):
        return await self._upload(**values)

    async def validate_instance(self, *, instance_id):
        _, result, _, _ = await self._request(self._url(instance_id)+"/validate", "GET", self._token)
        issues = result if isinstance(result, list) else obj(result).get("validationIssues", [])
        if not isinstance(issues, list):
            issues = []
        issues = [{"severity": self.safe(obj(v).get("severity"), "Unknown"),
                   "code": self.safe(obj(v).get("code"), "ANNUAL_ACCOUNTS_VALIDATION_ISSUE"),
                   "field": self.safe(obj(v).get("field")), "message": self.safe(obj(v).get("message"))}
                  for v in issues]
        return {"hasErrors": any(v["severity"].lower() == "error" for v in issues), "issues": issues}

    async def lock_for_signing(self, *, instance_id):
        _, result, _, _ = await self._request(self._url(instance_id)+"/process/next", "PUT", self._token,
            content_type="application/json", body='{"action":"confirm"}')
        task = obj(obj(result).get("currentTask"))
        return {"processTask": self.safe(task.get("altinnTaskType") or task.get("elementId"), "unknown"), "locked": True}

    async def _instance(self, identifier):
        _, result, _, _ = await self._request(self._url(identifier), "GET", self._token)
        if instance_id(self.safe(obj(result).get("id"))) != identifier:
            raise AnnualAccountsAuthorityError("Altinn returned a different annual accounts instance id.",
                code="ANNUAL_ACCOUNTS_INSTANCE_MISMATCH")
        return obj(result)

    async def get_signing_handoff(self, *, instance_id):
        result = await self._instance(instance_id)
        return {"instanceId": instance_id, "processTask": self._task(result),
                "signingUrl": f"{BASE}/#/instance/{instance_id}", "signed": False, "submitted": False}

    async def get_submission_evidence(self, *, instance_id):
        result = await self._instance(instance_id)
        process, status = obj(result.get("process")), obj(result.get("status"))
        ended, event = iso(process.get("ended")), self.safe(process.get("endEvent")) or None
        completed = "currentTask" in process and process["currentTask"] is None and ended is not None and event is not None
        archived_at = iso(status.get("archived"))
        archived = status.get("isArchived") is True and archived_at is not None
        signatures = self._elements(result, "signature")
        signature = signatures[0] if len(signatures) == 1 else None
        signed = signature is not None and self.safe(signature.get("contentType")) == "application/json"
        signature_id = data_id(self.safe(signature.get("id"))) if signed else None
        receipts = self._elements(result, "ref-data-as-pdf")
        element = receipts[0] if len(receipts) == 1 else None
        receipt = None
        if element and self.safe(element.get("contentType")) == "application/pdf":
            identifier = data_id(self.safe(element.get("id")))
            try:
                size = float(element.get("size"))
            except (TypeError, ValueError):
                size = 0
            if isinstance(size, float) and size.is_integer() and size > 0:
                receipt = {"dataId": identifier, "dataType": "ref-data-as-pdf",
                        "filename": self.safe(element.get("filename"), "annual-accounts-receipt.pdf"),
                        "contentType": "application/pdf", "sizeBytes": int(size),
                        "reference": f"{PLATFORM}/storage/api/v1/instances/{instance_id}/data/{identifier}",
                        "downloadUrl": self._url(instance_id)+f"/data/{identifier}"}
        return {"instanceId": instance_id, "processCompleted": completed, "processEndedAt": ended,
            "endEvent": event, "signed": signed, "signatureDataId": signature_id,
            "submitted": completed and signed and archived and receipt is not None,
            "archived": archived, "archivedAt": archived_at,
            "archiveReference": f"{PLATFORM}/storage/api/v1/instances/{instance_id}" if archived else None,
            "receipt": receipt}


async def prepare_annual_accounts_for_signing(client, *, company_org_number, main_form_xml, company_accounts_xml):
    instance = await client.create_instance(company_org_number=company_org_number)
    await client.upload_main_form(instance_id=instance["id"], data_id=instance["dataIds"]["mainForm"], xml=main_form_xml)
    await client.upload_company_accounts(instance_id=instance["id"], data_id=instance["dataIds"]["companyAccounts"], xml=company_accounts_xml)
    validation = await client.validate_instance(instance_id=instance["id"])
    if validation["hasErrors"]:
        raise AnnualAccountsAuthorityError("Annual accounts validation must pass before locking.",
            code="ANNUAL_ACCOUNTS_VALIDATION_FAILED", validation_codes=sorted({v["code"] for v in validation["issues"] if v["severity"].lower() == "error"}))
    await client.lock_for_signing(instance_id=instance["id"])
    return await client.get_signing_handoff(instance_id=instance["id"]) | {"dataIds": instance["dataIds"], "validation": validation}
