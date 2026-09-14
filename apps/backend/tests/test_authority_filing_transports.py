"""Local characterization of the frozen tax/accounts request and evidence contracts."""
import asyncio
import base64
import json

import httpx
import pytest

from talli_backend.authority_tools import annual_accounts_transport as annual
from talli_backend.adapters import company_tax_authority as tax
from talli_backend.authority_tools._filing import MAX_RESPONSE_BYTES
from talli_backend.modules.company_tax_filing.public import (
    wait_for_company_tax_validation, wait_for_company_tax_feedback,
    wait_for_company_tax_clean_envelope,
)

ID = "50001234/10000000-0000-4000-8000-000000000001"
DATA = "20000000-0000-4000-8000-000000000002"
OTHER = "30000000-0000-4000-8000-000000000003"
SIGNATURE = "40000000-0000-4000-8000-000000000004"
ORG = "310279617"
TAX_TOKEN, ALTINN_TOKEN = "opaque-tax-test-token", "opaque-altinn-test-token"
XML = "<document>æ</document>"
IDENTITY = dict(income_year=2025, company_org_number=ORG)


def instance(task="data", data=None, **extra):
    return {"id": ID, "process": {"currentTask": {"altinnTaskType": task}, "ended": None},
            "status": {}, "data": data or [], **extra}


def annual_instance(task="data"):
    return instance(task, [{"id": DATA, "dataType": "Hovedskjema"}, {"id": OTHER, "dataType": "Underskjema"}])


def queue(*results):
    requests = []
    pending = list(results)
    def respond(request):
        requests.append(request)
        assert pending, f"Unexpected {request.method} {request.url.path}"
        result = pending.pop(0)
        return result if isinstance(result, httpx.Response) else httpx.Response(200, json=result)
    return httpx.MockTransport(respond), requests, pending


def run(call):
    return asyncio.run(call)


def test_annual_exact_create_upload_validate_lock_and_person_handoff():
    transport, requests, pending = queue(annual_instance(), httpx.Response(201), httpx.Response(201),
        [{"severity": "Warning", "code": "RR0002_GUIDANCE", "field": "approval", "message": "Check date."}],
        {"currentTask": {"altinnTaskType": "signing"}}, annual_instance("signing"))
    result = run(annual.prepare_annual_accounts_for_signing(annual.AnnualAccountsTransport(ALTINN_TOKEN, transport=transport),
        company_org_number=ORG, main_form_xml="<main/>", company_accounts_xml="<accounts/>"))
    assert not pending
    assert [(r.method, str(r.url)) for r in requests] == [
        ("POST", annual.BASE+"/instances/create"), ("PUT", annual.BASE+f"/instances/{ID}/data/{DATA}"),
        ("PUT", annual.BASE+f"/instances/{ID}/data/{OTHER}"), ("GET", annual.BASE+f"/instances/{ID}/validate"),
        ("PUT", annual.BASE+f"/instances/{ID}/process/next"), ("GET", annual.BASE+f"/instances/{ID}")]
    assert json.loads(requests[0].content) == {"instanceOwner": {"organisationNumber": ORG}}
    assert requests[1].content == b"<main/>" and requests[2].content == b"<accounts/>"
    assert json.loads(requests[4].content) == {"action": "confirm"}
    assert all(r.headers["authorization"] == "Bearer "+ALTINN_TOKEN for r in requests)
    assert result["processTask"] == "signing" and not result["signed"] and not result["submitted"]
    assert result["signingUrl"] == annual.BASE+f"/#/instance/{ID}"
    assert result["dataIds"] == {"mainForm": DATA, "companyAccounts": OTHER}


def test_annual_validation_error_never_locks():
    transport, requests, _ = queue(annual_instance(), httpx.Response(201), httpx.Response(201),
        [{"severity": "Error", "code": "RR0002_REQUIRED"}])
    with pytest.raises(annual.AnnualAccountsAuthorityError) as caught:
        run(annual.prepare_annual_accounts_for_signing(annual.AnnualAccountsTransport(ALTINN_TOKEN, transport=transport),
            company_org_number=ORG, main_form_xml="<main/>", company_accounts_xml="<accounts/>"))
    assert caught.value.validation_codes == ["RR0002_REQUIRED"]
    assert len(requests) == 4 and not any(r.url.path.endswith("/process/next") for r in requests)


@pytest.mark.parametrize("missing", ["signature", "receipt", "archived", "ended", "event", "currentTask"])
def test_annual_submission_requires_all_original_evidence(missing):
    value = instance(None, [{"id": DATA, "dataType": "signature", "contentType": "application/json"},
        {"id": OTHER, "dataType": "ref-data-as-pdf", "contentType": "application/pdf", "size": 19}],
        process={"currentTask": None, "ended": "2026-07-14T10:37:41.935543Z", "endEvent": "EndEvent_1"},
        status={"isArchived": True, "archived": "2026-07-14T10:37:41.935543Z"})
    transport, requests, _ = queue(value)
    result = run(annual.AnnualAccountsTransport(ALTINN_TOKEN, transport=transport).get_submission_evidence(instance_id=ID))
    assert result["submitted"] and result["receipt"]["sizeBytes"] == 19
    if missing in ("signature", "receipt"):
        value["data"].pop(0 if missing == "signature" else 1)
    elif missing == "archived": value["status"]["isArchived"] = False
    elif missing == "currentTask": value["process"]["currentTask"] = {"altinnTaskType": "signing"}
    else: value["process"].pop("endEvent" if missing == "event" else "ended")
    transport, _, _ = queue(value)
    assert not run(annual.AnnualAccountsTransport(ALTINN_TOKEN, transport=transport).get_submission_evidence(instance_id=ID))["submitted"]
    assert len(requests) == 1  # no receipt/signature downloads


@pytest.mark.parametrize("module,client", [(annual, annual.AnnualAccountsTransport), (tax, tax.CompanyTaxTransport)])
def test_exchange_exact_get_and_production_client_refusal(module, client):
    transport, requests, _ = queue(httpx.Response(200, text=ALTINN_TOKEN))
    assert run(module.exchange_maskinporten_for_altinn_token(TAX_TOKEN, transport=transport)) == ALTINN_TOKEN
    assert requests[0].method == "GET" and str(requests[0].url) == "https://platform.tt02.altinn.no/authentication/api/v1/exchange/maskinporten"
    assert requests[0].headers["authorization"] == "Bearer "+TAX_TOKEN
    with pytest.raises(ValueError, match="production authority transport"):
        client(TAX_TOKEN, environment="production", transport=transport)


@pytest.mark.parametrize("module", [annual, tax])
def test_response_text_strips_one_utf8_bom_before_json_and_token_parsing(module):
    response = annual_instance() if module is annual else {"id": ID}
    transport, _, _ = queue(httpx.Response(200, content=b"\xef\xbb\xbf"+json.dumps(response).encode()))
    client = annual.AnnualAccountsTransport(ALTINN_TOKEN, transport=transport) if module is annual else tax.CompanyTaxTransport(TAX_TOKEN, ALTINN_TOKEN, transport=transport)
    arguments = {"company_org_number": ORG} if module is annual else IDENTITY
    assert run(client.create_instance(**arguments))["id"] == ID
    transport, _, _ = queue(httpx.Response(200, content=b"\xef\xbb\xbf"+ALTINN_TOKEN.encode()))
    assert run(module.exchange_maskinporten_for_altinn_token(TAX_TOKEN, transport=transport)) == ALTINN_TOKEN


@pytest.mark.parametrize("module", [annual, tax])
@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_json_response_constants_do_not_admit_instance_or_continue_writes(module, constant):
    value = annual_instance() if module is annual else {"id": ID}
    body = json.dumps(value)[:-1] + ', "ignored": {"nested": [' + constant + ']}}'
    transport, requests, pending = queue(httpx.Response(200, text=body))
    client = annual.AnnualAccountsTransport(ALTINN_TOKEN, transport=transport) if module is annual else tax.CompanyTaxTransport(TAX_TOKEN, ALTINN_TOKEN, transport=transport)
    async def create_then_upload():
        if module is annual:
            created = await client.create_instance(company_org_number=ORG)
            await client.upload_main_form(instance_id=created["id"], data_id=DATA, xml=XML)
        else:
            created = await client.create_instance(**IDENTITY)
            await client.upload_envelope(instance_id=created["id"], envelope_xml=XML)
    # The predecessor JSON.parse failure becomes an empty object, whose id
    # cannot be admitted. No later upload may consume the apparent instance.
    with pytest.raises(ValueError, match="instance id"):
        run(create_then_upload())
    assert len(requests) == 1 and not pending


def test_response_text_xml_bom_and_invalid_utf8_keep_original_decoded_receipt_bytes():
    # Response.text removes the initial BOM and substitutes malformed UTF-8.
    receipt = "<receipt>\ufffd</receipt>"
    body = b"\xef\xbb\xbf<receipt>\xff</receipt>"
    element = {"id": DATA, "dataType": "tilbakemelding", "contentType": "application/xml",
        "size": len(receipt.encode()), "fileScanResult": "Clean"}
    transport, _, _ = queue(instance("feedback", [element]),
        httpx.Response(200, content=body, headers={"content-type": "application/xml"}))
    result = run(tax.CompanyTaxTransport(TAX_TOKEN, ALTINN_TOKEN, transport=transport).get_feedback_receipt(instance_id=ID))
    assert result["receiptXml"] == receipt and result["sizeBytes"] == len(receipt.encode())
    transport, _, _ = queue(httpx.Response(200, content=b"\xef\xbb\xbf<validation/>"))
    assert run(tax.CompanyTaxTransport(TAX_TOKEN, transport=transport).validate_test(
        **IDENTITY, envelope_xml=XML))["resultXml"] == "<validation/>"


def test_tax_current_validation_create_upload_scan_and_job_sequence():
    current_xml = "<response><skattemeldingdokument><id>SKI:755:1</id><content>"+base64.b64encode(b"<return><partsnummer>1234567</partsnummer></return>").decode()+"</content></skattemeldingdokument></response>"
    transport, requests, pending = queue(httpx.Response(200, text=current_xml), httpx.Response(200, text="<validation/>"),
        {"id": ID}, {"id": DATA, "fileScanResult": "Pending"},
        instance(data=[{"id": DATA, "dataType": tax.ENVELOPE, "fileScanResult": "Clean"}]),
        {"jobbId": "job-1", "jobbStatus": "NY"}, {"jobbStatus": "FERDIG", "forrigeStatus": "KJOERER"}, httpx.Response(200, text="<result/>"))
    client = tax.CompanyTaxTransport(TAX_TOKEN, ALTINN_TOKEN, transport=transport)
    async def sequence():
        current = await client.fetch_current(**IDENTITY)
        assert current["documentReference"] == "SKI:755:1" and current["partyNumber"] == "1234567"
        await client.validate_test(**IDENTITY, envelope_xml=XML)
        assert (await client.create_instance(**IDENTITY))["id"] == ID
        await client.upload_envelope(instance_id=ID, envelope_xml=XML)
        assert (await client.get_envelope_scan(instance_id=ID))["fileScanResult"] == "Clean"
        assert (await client.start_validation(**IDENTITY, instance_id=ID))["jobId"] == "job-1"
        return await wait_for_company_tax_validation(client, **IDENTITY, job_id="job-1", sleep=asyncio.sleep)
    assert run(sequence()) == {"resultXml": "<result/>"} and not pending
    assert [(r.method, str(r.url)) for r in requests] == [
        ("GET", tax.TAX_BASE+f"/2025/{ORG}"), ("POST", tax.TAX_BASE+f"/validertest/2025/{ORG}"),
        ("POST", tax.BASE+"/instances/"), ("POST", tax.BASE+f"/instances/{ID}/data?dataType={tax.ENVELOPE}"),
        ("GET", tax.BASE+f"/instances/{ID}"), ("POST", tax.TAX_BASE+f"/jobb/altinn/2025/{ORG}/start"),
        ("GET", tax.TAX_BASE+f"/jobb/altinn/2025/{ORG}/job-1/status"),
        ("GET", tax.TAX_BASE+f"/jobb/altinn/2025/{ORG}/job-1/resultat")]
    assert json.loads(requests[2].content) == {"instanceOwner": {"organisationNumber": ORG}, "appId": tax.APP_ID, "dataValues": {"inntektsaar": 2025}}
    assert requests[3].content == XML.encode() and requests[3].headers["content-type"] == "text/xml"
    assert requests[3].headers["content-disposition"] == "attachment; filename=skattemeldingOgNaeringsspesifikasjon.xml"
    assert json.loads(requests[5].content) == {"appId": tax.APP_ID, "instansId": ID}
    assert [r.headers["authorization"] for r in requests] == ["Bearer "+v for v in (TAX_TOKEN, TAX_TOKEN, ALTINN_TOKEN, ALTINN_TOKEN, ALTINN_TOKEN, TAX_TOKEN, TAX_TOKEN, TAX_TOKEN)]


def test_tax_replaces_original_data_element_and_keeps_xml_bytes():
    transport, requests, _ = queue({"id": DATA, "fileScanResult": "Pending"})
    assert run(tax.CompanyTaxTransport(TAX_TOKEN, ALTINN_TOKEN, transport=transport).replace_envelope(
        instance_id=ID, data_id=DATA, envelope_xml=XML))["dataId"] == DATA
    assert requests[0].method == "PUT" and str(requests[0].url) == tax.BASE+f"/instances/{ID}/data/{DATA}"
    assert requests[0].content == XML.encode()


@pytest.mark.parametrize("task,expected,writes", [("data", None, 1), ("confirmation", None, 0), ("feedback", "COMPANY_TAX_CONFIRMATION_TASK_INVALID", 0)])
def test_tax_owner_confirmation_read_before_write_and_readback(task, expected, writes):
    responses = [instance(task)] + ([{}, instance("confirmation")] if writes else [])
    transport, requests, _ = queue(*responses)
    client = tax.CompanyTaxTransport(TAX_TOKEN, ALTINN_TOKEN, transport=transport)
    if expected:
        with pytest.raises(tax.CompanyTaxReturnAuthorityError, match="initial data"):
            run(client.advance_to_confirmation(instance_id=ID))
    else:
        result = run(client.advance_to_confirmation(instance_id=ID))
        assert result == {"instanceId": ID, "processTask": "confirmation", "transitioned": bool(writes)}
    assert sum(r.method == "PUT" for r in requests) == writes
    assert client.get_owner_confirmation_url(instance_id=ID) == f"https://skatt-test.sits.no/web/skattemelding-visning/altinn?appId={tax.APP_ID}&instansId={ID}"


def test_tax_feedback_exact_one_clean_xml_receipt_read_only():
    element = {"id": DATA, "dataType": "tilbakemelding", "contentType": "text/xml", "size": len(XML.encode()), "fileScanResult": "Clean"}
    transport, requests, _ = queue(instance("feedback", [element]), httpx.Response(200, text=XML, headers={"content-type": "text/xml; charset=utf-8"}))
    result = run(tax.CompanyTaxTransport(TAX_TOKEN, ALTINN_TOKEN, transport=transport).get_feedback_receipt(instance_id=ID))
    assert result["receiptXml"] == XML and result["sizeBytes"] == len(XML.encode())
    assert result["reference"] == f"{tax.PLATFORM}/storage/api/v1/instances/{ID}/data/{DATA}"
    assert [r.method for r in requests] == ["GET", "GET"]


@pytest.mark.parametrize("fault,code", [("missing", "PENDING"), ("duplicate", "DUPLICATE"), ("pending", "PENDING"),
    ("scan", "SCAN_REJECTED"), ("type", "CONTENT_TYPE_INVALID"), ("size", "SIZE_INVALID"),
    ("response_type", "CONTENT_TYPE_INVALID"), ("response_size", "SIZE_MISMATCH")])
def test_tax_feedback_failure_characterization(fault, code):
    element = {"id": DATA, "dataType": "tilbakemelding", "contentType": "application/xml", "size": len(XML.encode()), "fileScanResult": "Clean"}
    elements = [element]
    if fault == "missing": elements = []
    if fault == "duplicate": elements.append(dict(element, id=OTHER))
    if fault in ("pending", "scan"): element["fileScanResult"] = "Pending" if fault == "pending" else "Rejected"
    if fault == "type": element["contentType"] = "application/pdf"
    if fault == "size": element["size"] = 0
    response = httpx.Response(200, text=XML+"extra" if fault == "response_size" else XML,
        headers={"content-type": "application/pdf" if fault == "response_type" else "application/xml"})
    transport, _, _ = queue(instance("feedback", elements), response)
    with pytest.raises(tax.CompanyTaxReturnAuthorityError) as caught:
        run(tax.CompanyTaxTransport(TAX_TOKEN, ALTINN_TOKEN, transport=transport).get_feedback_receipt(instance_id=ID))
    assert caught.value.code == "COMPANY_TAX_FEEDBACK_"+code


@pytest.mark.parametrize("status,code", [("AVBRUTT", "AVBRUTT"), ("FEILET", "FEILET"), ("other", "STATUS_UNKNOWN"), ("KJOERER", "TIMEOUT")])
def test_tax_validation_polling_failures_are_bounded(status, code):
    transport, requests, _ = queue({"jobbStatus": status})
    with pytest.raises(tax.CompanyTaxReturnAuthorityError) as caught:
        run(wait_for_company_tax_validation(tax.CompanyTaxTransport(TAX_TOKEN, transport=transport), **IDENTITY, job_id="job", attempts=1, sleep=asyncio.sleep))
    assert caught.value.code == "COMPANY_TAX_VALIDATION_"+code and len(requests) == 1


@pytest.mark.parametrize("module", [annual, tax])
@pytest.mark.parametrize("fault", ["redirect", "large", "network", "remote_secret"])
def test_transport_response_guards_and_secret_reflection(module, fault):
    secret = "private-response-secret"
    def respond(request):
        if fault == "network": raise httpx.ConnectError(secret, request=request)
        if fault == "redirect": return httpx.Response(302, headers={"location": "https://evil.invalid/"})
        if fault == "large": return httpx.Response(200, content=b"x"*(MAX_RESPONSE_BYTES+1))
        return httpx.Response(429, json={"title": secret, "code": TAX_TOKEN, "traceId": ALTINN_TOKEN,
            "error_description": "-----BEGIN " "PRIVATE KEY----- secret -----END PRIVATE KEY-----"})
    transport = httpx.MockTransport(respond)
    with pytest.raises(Exception) as caught:
        run(module.exchange_maskinporten_for_altinn_token(TAX_TOKEN, transport=transport))
    rendered = json.dumps(caught.value.evidence())
    assert all(value not in rendered for value in (secret, TAX_TOKEN, ALTINN_TOKEN, "PRIVATE KEY", "evil.invalid"))
    assert caught.value.code.endswith({"redirect": "REDIRECT_REFUSED", "large": "RESPONSE_TOO_LARGE", "network": "NETWORK_ERROR", "remote_secret": "HTTP_429"}[fault])


@pytest.mark.parametrize("factory", [annual.AnnualAccountsTransport, tax.CompanyTaxTransport])
def test_transport_preserves_actual_20_second_default_and_timeout_limits(factory):
    assert factory(TAX_TOKEN)._timeout == 20
    for value in (0, 999, 120001, 1.5, True):
        with pytest.raises(ValueError): factory(TAX_TOKEN, timeout_ms=value)
    assert factory(TAX_TOKEN, timeout_ms=1000)._timeout == 1


@pytest.mark.parametrize("kind", ["annual", "tax"])
def test_success_response_cannot_smuggle_token_into_evidence(kind):
    if kind == "annual":
        transport, _, _ = queue([{"severity": "Error", "code": ALTINN_TOKEN, "message": ALTINN_TOKEN}])
        call = annual.AnnualAccountsTransport(ALTINN_TOKEN, transport=transport).validate_instance(instance_id=ID)
    else:
        transport, _, _ = queue(httpx.Response(200, text=f"<r><avvikstype>{TAX_TOKEN}</avvikstype></r>"))
        call = tax.CompanyTaxTransport(TAX_TOKEN, transport=transport).validate_test(**IDENTITY, envelope_xml=XML)
    with pytest.raises(Exception) as caught: run(call)
    assert caught.value.code.endswith("RESPONSE_INVALID")
    assert TAX_TOKEN not in str(caught.value) and ALTINN_TOKEN not in str(caught.value)


@pytest.mark.parametrize("fault", ["reference", "content", "party"])
def test_tax_current_document_identity_must_be_usable(fault):
    encoded = base64.b64encode(b"<return><partsnummer>1234567</partsnummer></return>").decode()
    reference = "SKI:755:1"
    if fault == "reference": reference = ""
    if fault == "content": encoded = "invalid$"
    if fault == "party": encoded = base64.b64encode(b"<return><partsnummer>invalid</partsnummer></return>").decode()
    transport, _, _ = queue(httpx.Response(200, text=f"<r><skattemeldingdokument><id>{reference}</id><content>{encoded}</content></skattemeldingdokument></r>"))
    with pytest.raises(tax.CompanyTaxReturnAuthorityError) as caught:
        run(tax.CompanyTaxTransport(TAX_TOKEN, transport=transport).fetch_current(**IDENTITY))
    assert caught.value.code == {"reference": "COMPANY_TAX_CURRENT_REFERENCE_MISSING", "content": "COMPANY_TAX_CURRENT_CONTENT_INVALID", "party": "COMPANY_TAX_CURRENT_PARTY_NUMBER_MISSING"}[fault]


@pytest.mark.parametrize("module,method", [(annual, "get_signing_handoff"), (annual, "get_submission_evidence"), (tax, "get_instance")])
def test_readback_rejects_other_instance(module, method):
    transport, _, _ = queue(instance(id="50001234/99999999-0000-4000-8000-000000000001"))
    client = annual.AnnualAccountsTransport(ALTINN_TOKEN, transport=transport) if module is annual else tax.CompanyTaxTransport(TAX_TOKEN, ALTINN_TOKEN, transport=transport)
    with pytest.raises(Exception) as caught: run(getattr(client, method)(instance_id=ID))
    assert caught.value.code.endswith("INSTANCE_MISMATCH")


@pytest.mark.parametrize("fault", ["instance", "data", "organization", "year", "xml", "token"])
def test_invalid_inputs_never_reach_tax_transport(fault):
    transport, requests, _ = queue()
    client = tax.CompanyTaxTransport(TAX_TOKEN, ALTINN_TOKEN, transport=transport)
    with pytest.raises(Exception):
        if fault == "instance": run(client.get_instance(instance_id="https://evil.invalid/"))
        elif fault == "data": run(client.replace_envelope(instance_id=ID, data_id="../other", envelope_xml=XML))
        elif fault == "organization": run(client.fetch_current(income_year=2025, company_org_number="not-an-org"))
        elif fault == "year": run(client.fetch_current(income_year=1999, company_org_number=ORG))
        elif fault == "xml": run(client.upload_envelope(instance_id=ID, envelope_xml=""))
        else: run(tax.CompanyTaxTransport(TAX_TOKEN, transport=transport).create_instance(**IDENTITY))
    assert not requests


def test_tax_scan_and_feedback_polling_are_read_only_and_preserve_intervals():
    transport, requests, _ = queue(instance(data=[{"id": DATA, "dataType": tax.ENVELOPE, "fileScanResult": "Pending"}]),
        instance(data=[{"id": DATA, "dataType": tax.ENVELOPE, "fileScanResult": "Clean"}]))
    sleeps = []
    async def sleep(seconds): sleeps.append(seconds)
    client = tax.CompanyTaxTransport(TAX_TOKEN, ALTINN_TOKEN, transport=transport)
    assert run(wait_for_company_tax_clean_envelope(client, ID, sleep=sleep))["fileScanResult"] == "Clean"
    assert sleeps == [2] and [r.method for r in requests] == ["GET", "GET"]
    transport, requests, _ = queue(instance("confirmation"), instance("confirmation"))
    with pytest.raises(tax.CompanyTaxReturnAuthorityError) as caught:
        run(wait_for_company_tax_feedback(tax.CompanyTaxTransport(TAX_TOKEN, ALTINN_TOKEN, transport=transport), instance_id=ID, attempts=2, sleep=sleep))
    assert caught.value.code == "COMPANY_TAX_FEEDBACK_TIMEOUT" and len(requests) == 2
