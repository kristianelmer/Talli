"""Fixed TT02 HTTP adapter for the Company Tax authority port."""
from __future__ import annotations
import base64
import json
import re

from talli_backend.authority_tools._filing import FixedTransport, data_id, instance_id, income_year, iso, obj, opaque, org_number, valid, xml

APP_ID = "skd/formueinntekt-skattemelding-v2"
BASE = f"https://skd.apps.tt02.altinn.no/{APP_ID}"
PLATFORM = "https://platform.tt02.altinn.no"
TAX_BASE = "https://api-test.sits.no/api/skattemelding/v2"
ENVELOPE = "skattemeldingOgNaeringsspesifikasjon"


from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxAuthority, CompanyTaxReturnAuthorityError, company_tax_authority_adapter,
)


def _element(content, name):
    qualified = rf"(?:[A-Za-z_][\w.-]*:)?{name}"
    match = re.search(rf"<{qualified}\b[^>]*>([\s\S]*?)</{qualified}>", content)
    return match.group(1) if match else ""


async def exchange_maskinporten_for_altinn_token(token, *, environment="test", transport=None, timeout_ms=20_000):
    if environment not in ("test", "production"):
        raise ValueError("Company tax authority environment must be test or production.")
    host = PLATFORM if environment == "test" else "https://platform.altinn.no"
    request = FixedTransport("COMPANY_TAX", CompanyTaxReturnAuthorityError, transport=transport, timeout_ms=timeout_ms)
    raw, _, _, _ = await request._request(host+"/authentication/api/v1/exchange/maskinporten", "GET", token, accept="text/plain")
    return opaque(raw)


@company_tax_authority_adapter(CompanyTaxAuthority)
class CompanyTaxTransport(FixedTransport):
    def __init__(self, tax_access_token, altinn_access_token=None, *, environment="test", transport=None, timeout_ms=20_000):
        if environment != "test":
            raise ValueError("Company tax production authority transport is disabled.")
        self._tax = opaque(tax_access_token)
        self._altinn = opaque(altinn_access_token) if altinn_access_token is not None else None
        super().__init__("COMPANY_TAX", CompanyTaxReturnAuthorityError, transport=transport,
            timeout_ms=timeout_ms, secrets=(self._tax, self._altinn))

    def _altinn_token(self):
        if not self._altinn:
            raise CompanyTaxReturnAuthorityError("Altinn access token is required for instance operations.", code="COMPANY_TAX_ALTINN_TOKEN_REQUIRED")
        return self._altinn

    def _url(self, identifier):
        return BASE+"/instances/"+instance_id(identifier)

    def _case(self, year, org):
        return f"{income_year(year)}/{org_number(org)}"

    def _job(self, identifier):
        return valid(identifier, r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", "validation job id")

    async def fetch_current(self, *, income_year, company_org_number):
        raw, _, _, _ = await self._request(TAX_BASE+"/"+self._case(income_year, company_org_number), "GET", self._tax, accept="application/xml")
        document = _element(xml(raw), "skattemeldingdokument")
        reference = _element(document, "id").strip()
        if not reference or len(reference) > 4000 or "<" in reference:
            raise CompanyTaxReturnAuthorityError("Current return has no usable document reference.", code="COMPANY_TAX_CURRENT_REFERENCE_MISSING")
        encoded = re.sub(r"\s+", "", _element(document, "content"))
        if not encoded or len(encoded) % 4 or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", encoded):
            raise CompanyTaxReturnAuthorityError("Current return content is invalid.", code="COMPANY_TAX_CURRENT_CONTENT_INVALID")
        decoded = base64.b64decode(encoded).decode("utf-8", errors="replace")
        party = _element(decoded, "partsnummer").strip()
        if not re.fullmatch(r"[0-9]{1,19}", party):
            raise CompanyTaxReturnAuthorityError("Current return has no usable party number.", code="COMPANY_TAX_CURRENT_PARTY_NUMBER_MISSING")
        return {"rawXml": raw, "documentReference": reference, "partyNumber": party}

    async def validate_test(self, *, income_year, company_org_number, envelope_xml):
        raw, _, _, _ = await self._request(TAX_BASE+"/validertest/"+self._case(income_year, company_org_number),
            "POST", self._tax, accept="application/xml", content_type="application/xml", body=xml(envelope_xml))
        return {"resultXml": xml(raw)}

    async def create_instance(self, *, income_year, company_org_number):
        self._case(income_year, company_org_number)
        _, result, _, _ = await self._request(BASE+"/instances/", "POST", self._altinn_token(),
            content_type="application/json", body=json.dumps({"instanceOwner": {"organisationNumber": company_org_number},
                "appId": APP_ID, "dataValues": {"inntektsaar": income_year}}, separators=(",", ":")))
        return {"id": instance_id(self.safe(obj(result).get("id")))}

    async def upload_envelope(self, *, instance_id, envelope_xml):
        _, result, _, _ = await self._request(self._url(instance_id)+f"/data?dataType={ENVELOPE}", "POST", self._altinn_token(),
            content_type="text/xml", body=xml(envelope_xml), headers={"content-disposition": "attachment; filename=skattemeldingOgNaeringsspesifikasjon.xml"})
        return {"dataId": data_id(self.safe(obj(result).get("id"))), "fileScanResult": self.safe(obj(result).get("fileScanResult"), "Unknown")}

    async def replace_envelope(self, *, instance_id, data_id: str, envelope_xml):
        from talli_backend.authority_tools._filing import data_id as checked_id
        _, result, _, _ = await self._request(self._url(instance_id)+"/data/"+checked_id(data_id), "PUT", self._altinn_token(),
            content_type="text/xml", body=xml(envelope_xml), headers={"content-disposition": "attachment; filename=skattemeldingOgNaeringsspesifikasjon.xml"})
        return {"dataId": checked_id(self.safe(obj(result).get("id"))), "fileScanResult": self.safe(obj(result).get("fileScanResult"), "Unknown")}

    async def get_envelope_scan(self, *, instance_id):
        _, result, _, _ = await self._request(self._url(instance_id), "GET", self._altinn_token())
        elements = obj(result).get("data", [])
        element = next((obj(v) for v in elements if self.safe(obj(v).get("dataType")) == ENVELOPE), None) if isinstance(elements, list) else None
        if element is None:
            raise CompanyTaxReturnAuthorityError("Instance has no company tax envelope.", code="COMPANY_TAX_ENVELOPE_MISSING", retryable=True)
        scan = self.safe(element.get("fileScanResult"), "Unknown")
        if scan not in ("Pending", "Clean"):
            raise CompanyTaxReturnAuthorityError("Company tax envelope was rejected during scanning.", code="COMPANY_TAX_ENVELOPE_SCAN_REJECTED")
        return {"dataId": self.safe(element.get("id")), "fileScanResult": scan}

    async def get_instance(self, *, instance_id: str):
        from talli_backend.authority_tools._filing import instance_id as checked_id
        _, result, _, _ = await self._request(self._url(instance_id), "GET", self._altinn_token())
        result = obj(result)
        if checked_id(self.safe(result.get("id"))) != instance_id:
            raise CompanyTaxReturnAuthorityError("Altinn returned a different company tax instance id.", code="COMPANY_TAX_INSTANCE_MISMATCH")
        process, status = obj(result.get("process")), obj(result.get("status"))
        task = obj(process.get("currentTask"))
        archived_at = iso(status.get("archived"))
        elements = result.get("data", [])
        data = []
        for raw in elements if isinstance(elements, list) else []:
            element = obj(raw)
            try:
                size = float(element.get("size", float("nan")))
            except (TypeError, ValueError):
                size = float("nan")
            data.append({"id": data_id(self.safe(element.get("id"))), "dataType": self.safe(element.get("dataType")),
                "contentType": self.safe(element.get("contentType")) or None,
                "filename": self.safe(element.get("filename")) or None,
                "sizeBytes": int(size) if size.is_integer() and size >= 0 else None,
                "fileScanResult": self.safe(element.get("fileScanResult")) or None})
        return {"instanceId": instance_id, "processTask": self.safe(task.get("altinnTaskType") or task.get("elementId")) or None,
            "processEndedAt": iso(process.get("ended")), "archived": status.get("isArchived") is True and archived_at is not None,
            "archivedAt": archived_at, "data": data}

    async def advance_to_confirmation(self, *, instance_id):
        current = await self.get_instance(instance_id=instance_id)
        if current["processTask"] == "confirmation":
            return {"instanceId": instance_id, "processTask": "confirmation", "transitioned": False}
        if current["processTask"] != "data":
            raise CompanyTaxReturnAuthorityError("Instance is not in the initial data task.", code="COMPANY_TAX_CONFIRMATION_TASK_INVALID")
        await self._request(self._url(instance_id)+"/process/next", "PUT", self._altinn_token(), content_type="application/json")
        prepared = await self.get_instance(instance_id=instance_id)
        if prepared["processTask"] != "confirmation":
            raise CompanyTaxReturnAuthorityError("Instance did not enter owner confirmation.", code="COMPANY_TAX_CONFIRMATION_NOT_REACHED", retryable=True)
        return {"instanceId": instance_id, "processTask": "confirmation", "transitioned": True}

    def get_owner_confirmation_url(self, *, instance_id: str):
        from talli_backend.authority_tools._filing import instance_id as checked_id
        return f"https://skatt-test.sits.no/web/skattemelding-visning/altinn?appId={APP_ID}&instansId={checked_id(instance_id)}"

    async def get_feedback_receipt(self, *, instance_id):
        instance = await self.get_instance(instance_id=instance_id)
        elements = [v for v in instance["data"] if v["dataType"] == "tilbakemelding"]
        if not elements:
            raise CompanyTaxReturnAuthorityError("Feedback is not available yet.", code="COMPANY_TAX_FEEDBACK_PENDING", retryable=True)
        if len(elements) != 1:
            raise CompanyTaxReturnAuthorityError("Instance contains duplicate feedback.", code="COMPANY_TAX_FEEDBACK_DUPLICATE")
        element = elements[0]
        scan = element["fileScanResult"]
        if scan == "Pending":
            raise CompanyTaxReturnAuthorityError("Feedback is being scanned.", code="COMPANY_TAX_FEEDBACK_PENDING", retryable=True)
        if scan != "Clean":
            raise CompanyTaxReturnAuthorityError("Feedback scan rejected.", code="COMPANY_TAX_FEEDBACK_SCAN_REJECTED")
        if element["contentType"] not in ("application/xml", "text/xml"):
            raise CompanyTaxReturnAuthorityError("Feedback is not XML.", code="COMPANY_TAX_FEEDBACK_CONTENT_TYPE_INVALID")
        if not element["sizeBytes"] or element["sizeBytes"] < 1:
            raise CompanyTaxReturnAuthorityError("Invalid feedback size.", code="COMPANY_TAX_FEEDBACK_SIZE_INVALID")
        raw, _, _, headers = await self._request(self._url(instance_id)+"/data/"+element["id"], "GET", self._altinn_token(), accept="application/xml, text/xml")
        content_type = self.safe(headers.get("content-type")).lower().split(";", 1)[0]
        if content_type not in ("application/xml", "text/xml"):
            raise CompanyTaxReturnAuthorityError("Downloaded feedback is not XML.", code="COMPANY_TAX_FEEDBACK_CONTENT_TYPE_INVALID")
        receipt = xml(raw)
        size = len(receipt.encode("utf-8"))
        if size != element["sizeBytes"]:
            raise CompanyTaxReturnAuthorityError("Feedback size does not match metadata.", code="COMPANY_TAX_FEEDBACK_SIZE_MISMATCH")
        return {"instanceId": instance_id, "dataId": element["id"], "dataType": "tilbakemelding",
            "contentType": content_type, "sizeBytes": size, "receiptXml": receipt,
            "reference": f"{PLATFORM}/storage/api/v1/instances/{instance_id}/data/{element['id']}",
            "archived": instance["archived"], "archivedAt": instance["archivedAt"],
            "archiveReference": f"{PLATFORM}/storage/api/v1/instances/{instance_id}"}

    async def start_validation(self, *, income_year, company_org_number, instance_id: str):
        from talli_backend.authority_tools._filing import instance_id as checked_id
        _, result, _, _ = await self._request(TAX_BASE+"/jobb/altinn/"+self._case(income_year, company_org_number)+"/start",
            "POST", self._tax, content_type="application/json", body=json.dumps({"appId": APP_ID, "instansId": checked_id(instance_id)}, separators=(",", ":")))
        return {"jobId": self._job(self.safe(obj(result).get("jobbId"))), "status": self.safe(obj(result).get("jobbStatus"))}

    async def get_validation_status(self, *, income_year, company_org_number, job_id):
        _, result, _, _ = await self._request(TAX_BASE+"/jobb/altinn/"+self._case(income_year, company_org_number)+"/"+self._job(job_id)+"/status", "GET", self._tax)
        return {"status": self.safe(obj(result).get("jobbStatus")), "previousStatus": self.safe(obj(result).get("forrigeStatus")) or None}

    async def get_validation_result(self, *, income_year, company_org_number, job_id):
        raw, _, status, _ = await self._request(TAX_BASE+"/jobb/altinn/"+self._case(income_year, company_org_number)+"/"+self._job(job_id)+"/resultat", "GET", self._tax, accept="application/xml")
        if status == 204 or not raw.strip():
            raise CompanyTaxReturnAuthorityError("Validation result is not ready.", code="COMPANY_TAX_VALIDATION_PENDING", retryable=True)
        return {"resultXml": xml(raw)}
