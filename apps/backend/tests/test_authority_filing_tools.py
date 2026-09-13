"""No-provider execution of original evidence checkpoints and continuation branches."""
import asyncio
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from talli_backend.authority_tools import annual_accounts_test as annual
from talli_backend.authority_tools import company_tax_test as tax
from talli_backend.authority_tools import annual_accounts_transport as annual_http
from talli_backend.authority_tools import company_tax_transport as tax_http
from talli_backend.authority_tools._filing import ROOT, payload, read_evidence, write_evidence
from test_authority_filing_transports import ALTINN_TOKEN, TAX_TOKEN, ID, DATA, OTHER, ORG, annual_instance, instance, queue

VALIDATION = "<r><resultatAvValidering>validertOK</resultatAvValidering></r>"


def environment(tmp_path, kind):
    name = "ANNUAL_ACCOUNTS" if kind == "annual" else "COMPANY_TAX"
    fixture = "annual-accounts-simple-holding-2025.json" if kind == "annual" else "company-tax-no-activity-2025.json"
    return {f"TALLI_{name}_APPROVED_TEST_WRITE": "true", "TALLI_MASKINPORTEN_ENVIRONMENT": "test",
        "TALLI_MASKINPORTEN_SCOPE": annual.SCOPE if kind == "annual" else " ".join(tax.SCOPES),
        f"TALLI_{name}_CASE_PATH": str(ROOT / "tests/fixtures/authority" / fixture),
        f"TALLI_{name}_EVIDENCE_PATH": str(tmp_path / "evidence.json"),
        "TALLI_MASKINPORTEN_SYSTEM_USER_ORG": ORG, "TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF": "original-fixture-ref",
        "TALLI_ANNUAL_ACCOUNTS_CONTACT_EMAIL": "synthetic@example.test", "TALLI_ANNUAL_ACCOUNTS_APPROVAL_DATE": "2026-06-30",
        "TALLI_ANNUAL_ACCOUNTS_CONFIRMING_REPRESENTATIVE": "Synthetic Person",
        "TALLI_COMPANY_TAX_REHEARSAL_MODE": "prepare", "TALLI_SKATTE_XSD_DIR": str(tmp_path)}


async def no_sleep(_):
    pass


def execute(module, env, transport):
    calls = []
    async def factory(environment, evidence):
        # Intent must be durable before any token or filing provider operation.
        path = Path(environment[f"TALLI_{'ANNUAL_ACCOUNTS' if module is annual else 'COMPANY_TAX'}_EVIDENCE_PATH"])
        assert read_evidence(path)["companyOrgNumber"] == ORG
        calls.append(copy.deepcopy(evidence))
        return annual_http.AnnualAccountsTransport(ALTINN_TOKEN, transport=transport) if module is annual else tax_http.CompanyTaxTransport(TAX_TOKEN, ALTINN_TOKEN, transport=transport)
    kwargs = dict(client_factory=factory, validate=lambda *_: None)
    if module is tax: kwargs["sleep"] = no_sleep
    return asyncio.run(module.run(env, **kwargs)), calls


@pytest.mark.parametrize("module", [annual, tax])
def test_cli_refuses_without_approved_write_before_credentials_or_network(module):
    result = subprocess.run([sys.executable, "-m", module.__name__], cwd=ROOT,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT/"apps/backend/src")}, capture_output=True, text=True)
    assert result.returncode == 1 and not result.stdout
    error = json.loads(result.stderr)
    assert error["code"] == "local_configuration_or_payload_error" and "APPROVED_TEST_WRITE" in error["message"]


@pytest.mark.parametrize("kind", ["annual", "tax"])
@pytest.mark.parametrize("fault", ["approval", "environment", "scope", "organization", "case"])
def test_invalid_gate_identity_or_case_never_opens_provider(tmp_path, kind, fault):
    module = annual if kind == "annual" else tax
    env = environment(tmp_path, kind)
    name = "ANNUAL_ACCOUNTS" if kind == "annual" else "COMPANY_TAX"
    if fault == "approval": env[f"TALLI_{name}_APPROVED_TEST_WRITE"] = "TRUE"
    if fault == "environment": env["TALLI_MASKINPORTEN_ENVIRONMENT"] = "production"
    if fault == "scope": env["TALLI_MASKINPORTEN_SCOPE"] += " other:scope"
    if fault == "organization": env["TALLI_MASKINPORTEN_SYSTEM_USER_ORG"] = "999999999"
    if fault == "case":
        case = json.loads(Path(env[f"TALLI_{name}_CASE_PATH"]).read_text())
        if kind == "annual": case["synthetic"] = False
        else: case["holdingActions"] = [{"kind": "share_purchase"}]
        path = tmp_path/"case.json"
        path.write_text(json.dumps(case))
        env[f"TALLI_{name}_CASE_PATH"] = str(path)
    async def unavailable(*_): pytest.fail("provider construction before gates")
    with pytest.raises(ValueError): asyncio.run(module.run(env, client_factory=unavailable))
    assert not (tmp_path/"evidence.json").exists()


def test_annual_prepare_resumes_original_instance_uploads_and_human_signing(tmp_path):
    env = environment(tmp_path, "annual")
    first, requests, _ = queue(annual_instance(), httpx.Response(201), httpx.Response(503, text="private-error"))
    with pytest.raises(annual_http.AnnualAccountsAuthorityError): execute(annual, env, first)
    evidence = read_evidence(tmp_path/"evidence.json")
    assert evidence["instance"]["id"] == ID and evidence["instance"]["mainFormUploaded"]
    assert not evidence["instance"]["companyAccountsUploaded"] and evidence["status"] == "failed_retryable"
    assert "private-error" not in json.dumps(evidence)
    second, requests, _ = queue(httpx.Response(201), [], {"currentTask": {"altinnTaskType": "signing"}}, annual_instance("signing"))
    result, _ = execute(annual, env, second)
    assert result["status"] == "locked_for_person_signing" and not result["signed"] and not result["submitted"]
    assert requests[0].url.path.endswith("/data/"+OTHER) and all(r.method != "POST" for r in requests)
    value = instance(None, [{"id": DATA, "dataType": "signature", "contentType": "application/json"},
        {"id": OTHER, "dataType": "ref-data-as-pdf", "contentType": "application/pdf", "size": 20}],
        process={"currentTask": None, "ended": "2026-07-14T10:37:41Z", "endEvent": "End"},
        status={"isArchived": True, "archived": "2026-07-14T10:37:41Z"})
    third, requests, _ = queue(value)
    result, _ = execute(annual, env, third)
    assert result["status"] == "submitted_and_archived" and result["submitted"]
    assert len(requests) == 1 and requests[0].method == "GET"
    final, requests, _ = queue()
    result, calls = execute(annual, env, final)
    assert result["submitted"] and not calls and not requests
    assert (tmp_path/"evidence.json").stat().st_mode & 0o777 == 0o600


def current_response(reference="SKI:755:1", party="1234567"):
    import base64
    encoded = base64.b64encode(f"<return><partsnummer>{party}</partsnummer></return>".encode()).decode()
    return httpx.Response(200, text=f"<r><skattemeldingdokument><id>{reference}</id><content>{encoded}</content></skattemeldingdokument></r>")


def prepared_tax_queue(*, existing=False):
    responses = [current_response(), httpx.Response(200, text=VALIDATION), {"id": ID},
        instance(data=[{"id": DATA, "dataType": tax_http.ENVELOPE}] if existing else [])]
    if not existing: responses.append({"id": DATA})
    responses += [instance(data=[{"id": DATA, "dataType": tax_http.ENVELOPE, "fileScanResult": "Clean"}]),
        {"jobbId": "original-job", "jobbStatus": "NY"}, {"jobbStatus": "FERDIG"}, httpx.Response(200, text=VALIDATION),
        instance("data"), {}, instance("confirmation")]
    return queue(*responses)


@pytest.mark.parametrize("kind", ["annual", "tax"])
@pytest.mark.parametrize("year", [2025.0, "2025.0", " 2.025e3 ", "+2025", "0x7e9"],
    ids=["json-decimal", "decimal-string", "exponent", "signed", "hexadecimal"])
def test_case_number_integer_coercion_preserves_year_and_real_payload(tmp_path, kind, year):
    module = annual if kind == "annual" else tax
    env = environment(tmp_path, kind)
    name = "ANNUAL_ACCOUNTS" if kind == "annual" else "COMPANY_TAX"
    case = json.loads(Path(env[f"TALLI_{name}_CASE_PATH"]).read_text())
    case["company"]["incomeYear"] = year
    case_path = tmp_path/"case.json"
    case_path.write_text(json.dumps(case))
    env[f"TALLI_{name}_CASE_PATH"] = str(case_path)
    transport, requests, pending = prepared_tax_queue() if kind == "tax" else queue(
        annual_instance(), httpx.Response(201), httpx.Response(201), [],
        {"currentTask": {"altinnTaskType": "signing"}}, annual_instance("signing"))
    result, _ = execute(module, env, transport)
    assert not pending and requests and result["incomeYear"] == 2025
    assert type(read_evidence(tmp_path/"evidence.json")["incomeYear"]) is int


def test_tax_null_ledger_matches_original_empty_no_activity_payload(tmp_path):
    env = environment(tmp_path, "tax")
    case = json.loads(Path(env["TALLI_COMPANY_TAX_CASE_PATH"]).read_text())
    case["ledgerEntries"] = None
    path = tmp_path/"case.json"
    path.write_text(json.dumps(case))
    env["TALLI_COMPANY_TAX_CASE_PATH"] = str(path)
    transport, _, pending = prepared_tax_queue()
    assert execute(tax, env, transport)[0]["status"] == "awaiting_person_confirmation"
    assert not pending


@pytest.mark.parametrize("kind", ["annual", "tax"])
@pytest.mark.parametrize("year", [2025.5, "2025.5", "2_025", "Infinity"],
    ids=["fraction", "fraction-string", "python-only-separator", "nonfinite"])
def test_fractional_and_non_number_case_years_still_fail_before_provider(tmp_path, kind, year):
    env = environment(tmp_path, kind)
    module = annual if kind == "annual" else tax
    name = "ANNUAL_ACCOUNTS" if kind == "annual" else "COMPANY_TAX"
    case = json.loads(Path(env[f"TALLI_{name}_CASE_PATH"]).read_text())
    case["company"]["incomeYear"] = year
    path = tmp_path/"case.json"
    path.write_text(json.dumps(case))
    env[f"TALLI_{name}_CASE_PATH"] = str(path)
    async def unavailable(*_): pytest.fail("invalid year reached provider")
    with pytest.raises(ValueError): asyncio.run(module.run(env, client_factory=unavailable))
    assert not (tmp_path/"evidence.json").exists()


@pytest.mark.parametrize("kind", ["annual", "tax"])
@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_json_case_constants_fail_before_provider_or_evidence(tmp_path, kind, constant):
    module = annual if kind == "annual" else tax
    env = environment(tmp_path, kind)
    name = "ANNUAL_ACCOUNTS" if kind == "annual" else "COMPANY_TAX"
    case = Path(env[f"TALLI_{name}_CASE_PATH"]).read_text().rstrip()
    path = tmp_path/"case.json"
    path.write_text(case[:-1] + ', "ignored": {"nested": [' + constant + ']}}')
    env[f"TALLI_{name}_CASE_PATH"] = str(path)
    async def unavailable(*_): pytest.fail("invalid JSON case reached provider construction")
    with pytest.raises(ValueError):
        asyncio.run(module.run(env, client_factory=unavailable, validate=lambda *_: None))
    assert not (tmp_path/"evidence.json").exists()


@pytest.mark.parametrize("kind", ["annual", "tax"])
@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_json_evidence_constants_fail_before_provider_and_preserve_bytes(tmp_path, kind, constant):
    module = annual if kind == "annual" else tax
    env = environment(tmp_path, kind)
    transport, _, _ = prepared_tax_queue() if kind == "tax" else queue(
        annual_instance(), httpx.Response(201), httpx.Response(201), [],
        {"currentTask": {"altinnTaskType": "signing"}}, annual_instance("signing"))
    execute(module, env, transport)
    path = tmp_path/"evidence.json"
    saved = path.read_text().rstrip()
    path.write_text(saved[:-1] + ', "ignored": {"nested": [' + constant + ']}}')
    previous = path.read_bytes()
    async def unavailable(*_): pytest.fail("invalid JSON evidence reached provider construction")
    with pytest.raises(ValueError):
        asyncio.run(module.run(env, client_factory=unavailable, validate=lambda *_: None))
    assert path.read_bytes() == previous


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_local_payload_output_rejects_non_json_constants(monkeypatch, constant):
    def spawn(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0,
            '{"result":"validertOK","ignored":[' + constant + ']}', '')
    monkeypatch.setattr(subprocess, "run", spawn)
    with pytest.raises(ValueError):
        payload("annual_accounts", {"synthetic": True})


def test_json_string_values_and_valid_numeric_syntax_remain_accepted(tmp_path):
    path = tmp_path/"evidence.json"
    path.write_text('{"values":["NaN","Infinity","-Infinity"],"incomeYear":2025.0,"ignored":1e400}')
    result = read_evidence(path)
    assert result["values"] == ["NaN", "Infinity", "-Infinity"]
    assert result["incomeYear"] == 2025.0 and result["ignored"] == float("inf")


@pytest.mark.parametrize("year,accepted", [(2025.0, True), ("2025.0", False), (2025.5, False)])
def test_tax_resume_preserves_number_is_integer_without_string_coercion(tmp_path, year, accepted):
    env = environment(tmp_path, "tax")
    saved = {"environment": "test", "productionEnabled": False, "companyOrgNumber": ORG,
        "incomeYear": year, "instance": {"id": ID}, "status": "submitted_and_receipted"}
    path = tmp_path/"evidence.json"
    write_evidence(path, saved)
    previous = path.read_bytes()
    env["TALLI_COMPANY_TAX_REHEARSAL_MODE"] = "resume"
    async def unavailable(*_): pytest.fail("completed evidence reached provider")
    if accepted:
        assert asyncio.run(tax.run(env, client_factory=unavailable))["incomeYear"] == 2025
        assert type(read_evidence(path)["incomeYear"]) is int
    else:
        with pytest.raises(ValueError): asyncio.run(tax.run(env, client_factory=unavailable))
        assert path.read_bytes() == previous


def test_tax_private_key_fifo_is_rejected_without_blocking(tmp_path):
    fifo = tmp_path/"key-fifo"
    os.mkfifo(fifo, 0o600)
    script = ("from talli_backend.authority_tools._filing import check_private_key_file\n"
        "import sys\ntry:\n check_private_key_file({'TALLI_MASKINPORTEN_PRIVATE_KEY_PATH':sys.argv[1]})\n"
        "except ValueError as error:\n print(str(error))\nelse:\n raise SystemExit(1)\n")
    result = subprocess.run([sys.executable, "-c", script, str(fifo)], capture_output=True, text=True, timeout=2)
    assert result.returncode == 0 and "regular file" in result.stdout


@pytest.mark.parametrize("existing", [False, True])
def test_tax_prepare_recovers_existing_envelope_then_human_confirmation_and_read_only_resume(tmp_path, existing):
    env = environment(tmp_path, "tax")
    env.pop("TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF")  # preserve original optional RAR external reference
    transport, requests, pending = prepared_tax_queue(existing=existing)
    result, _ = execute(tax, env, transport)
    assert not pending and result["status"] == "awaiting_person_confirmation"
    uploads = [r for r in requests if r.method == "POST" and "/data?" in str(r.url)]
    assert len(uploads) == (0 if existing else 1)
    assert sum(r.url.path.endswith("/process/next") for r in requests) == 1
    evidence = read_evidence(tmp_path/"evidence.json")
    assert evidence["instance"]["id"] == ID and evidence["instance"]["envelopeDataId"] == DATA
    assert evidence["instance"]["validationJobId"] == "original-job"
    assert "partyNumber" not in json.dumps(evidence) and "SKI:755:1" not in json.dumps(evidence)
    assert all(v not in json.dumps(evidence) for v in (TAX_TOKEN, ALTINN_TOKEN))
    transport, requests, _ = queue(instance("confirmation"))
    assert execute(tax, env, transport)[0]["status"] == "awaiting_person_confirmation"
    assert len(requests) == 1 and requests[0].method == "GET"
    env["TALLI_COMPANY_TAX_REHEARSAL_MODE"] = "resume"
    receipt = "<receipt>æ</receipt>"
    value = instance("feedback", [{"id": OTHER, "dataType": "tilbakemelding", "contentType": "application/xml",
        "fileScanResult": "Clean", "size": len(receipt.encode())}])
    transport, requests, _ = queue(value, httpx.Response(200, text=receipt, headers={"content-type": "application/xml"}), value)
    result, _ = execute(tax, env, transport)
    assert result["status"] == "submitted_and_receipted" and all(r.method == "GET" for r in requests)
    evidence = read_evidence(tmp_path/"evidence.json")
    assert "receiptXml" not in evidence["receipt"] and len(evidence["receipt"]["contentSha256"]) == 64
    transport, requests, _ = queue()
    assert execute(tax, env, transport)[0]["status"] == "submitted_and_receipted" and not requests


@pytest.mark.parametrize("fault", ["company", "year", "payload", "reference"])
def test_tax_prior_identity_payload_and_reference_conflicts_fail_before_instance_write(tmp_path, fault):
    env = environment(tmp_path, "tax")
    transport, _, _ = prepared_tax_queue()
    execute(tax, env, transport)
    path = tmp_path/"evidence.json"
    evidence = read_evidence(path)
    evidence["status"] = "failed_retryable"
    evidence["instance"]["confirmationPrepared"] = False
    if fault == "company": evidence["companyOrgNumber"] = "999999999"
    if fault == "year": evidence["incomeYear"] = 2024
    if fault == "payload": evidence["payloadHashes"]["skattemelding"] = "0"*64
    if fault == "reference": evidence["currentDocumentReferenceHash"] = "0"*64
    write_evidence(path, evidence)
    transport, requests, _ = queue(current_response())
    with pytest.raises(ValueError): execute(tax, env, transport)
    assert all(r.method == "GET" for r in requests)


def test_fixed_generator_child_environment_has_no_credential_or_node_injection(monkeypatch):
    captured = {}
    def spawn(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args[0], 0, '{"result":"validertOK"}', '')
    monkeypatch.setattr(subprocess, "run", spawn)
    monkeypatch.setenv("TALLI_MASKINPORTEN_PRIVATE_KEY_PATH", "/private/key")
    monkeypatch.setenv("NODE_OPTIONS", "--require /private/inject")
    assert payload("annual_accounts", {"synthetic": True}) == {"result": "validertOK"}
    assert set(captured["env"]) == {"PATH", "LANG"}
    assert "key" not in captured["input"] and "NODE_OPTIONS" not in captured["env"]


@pytest.mark.parametrize("kind", ["annual", "tax"])
@pytest.mark.parametrize("fault", ["malformed_json", "malformed_shape", "company", "year", "payload", "uuid"])
def test_existing_evidence_corruption_never_creates_another_instance(tmp_path, kind, fault):
    module = annual if kind == "annual" else tax
    env = environment(tmp_path, kind)
    path = tmp_path/"evidence.json"
    if kind == "tax":
        transport, _, _ = prepared_tax_queue()
    else:
        transport, _, _ = queue(annual_instance(), httpx.Response(201), httpx.Response(201), [],
            {"currentTask": {"altinnTaskType": "signing"}}, annual_instance("signing"))
    execute(module, env, transport)
    value = read_evidence(path)
    if fault == "malformed_json": path.write_text("{malformed")
    elif fault == "malformed_shape": path.write_text("[]")
    else:
        if fault == "company": value["companyOrgNumber"] = "999999999"
        if fault == "year": value["incomeYear"] = 2024
        if fault == "payload":
            value["payloadHashes"]["mainForm" if kind == "annual" else "skattemelding"] = "0"*64
            if kind == "tax":
                value["status"] = "failed_retryable"
                value["instance"]["confirmationPrepared"] = False
        if fault == "uuid": value["instance"]["id"] = "../other-instance"
        write_evidence(path, value)
    transport, requests, _ = queue(current_response())
    with pytest.raises(Exception): execute(module, env, transport)
    assert all(r.method == "GET" for r in requests)


def test_tax_exact_invalid_party_number_repair_reuses_envelope_and_restarts_validation(tmp_path):
    env = environment(tmp_path, "tax")
    transport, _, _ = prepared_tax_queue()
    execute(tax, env, transport)
    path = tmp_path/"evidence.json"
    value = read_evidence(path)
    value["status"] = "failed_blocked"
    value["authorityValidation"] = {"result": "validertMedFeil", "failureReasons": ["UgyldigPartsnummer"]}
    value["payloadHashes"]["skattemelding"] = "0"*64
    value["instance"].update(processTask="data", confirmationPrepared=False)
    write_evidence(path, value)
    transport, requests, pending = queue(current_response(), httpx.Response(200, text=VALIDATION),
        {"id": DATA, "fileScanResult": "Pending"},
        instance(data=[{"id": DATA, "dataType": tax_http.ENVELOPE, "fileScanResult": "Clean"}]),
        {"jobbId": "repaired-job", "jobbStatus": "NY"}, {"jobbStatus": "FERDIG"}, httpx.Response(200, text=VALIDATION),
        instance("data"), {}, instance("confirmation"))
    result, _ = execute(tax, env, transport)
    assert result["status"] == "awaiting_person_confirmation" and not pending
    assert requests[2].method == "PUT" and requests[2].url.path.endswith(f"/instances/{ID}/data/{DATA}")
    assert not any(r.method == "POST" and "/instances/" in r.url.path for r in requests)
    result = read_evidence(path)
    assert result["instance"]["validationJobId"] == "repaired-job" and result["instance"]["envelopeDataId"] == DATA


def test_evidence_atomic_write_does_not_follow_predictable_temporary_symlink(tmp_path):
    path, victim = tmp_path/"evidence.json", tmp_path/"unrelated.txt"
    victim.write_text("preserve")
    (tmp_path/f"evidence.json.{os.getpid()}.tmp").symlink_to(victim)
    write_evidence(path, {"status": "prepared"})
    assert victim.read_text() == "preserve" and read_evidence(path) == {"status": "prepared"}
    assert path.stat().st_mode & 0o777 == 0o600


def test_tax_key_file_failure_preserves_prepared_checkpoint(tmp_path):
    env = environment(tmp_path, "tax")
    env["TALLI_MASKINPORTEN_PRIVATE_KEY_PATH"] = str(tmp_path/"missing-key")
    with pytest.raises(ValueError, match="key file"):
        asyncio.run(tax.run(env))
    value = read_evidence(tmp_path/"evidence.json")
    assert value["status"] == "prepared" and value["error"] is None and value["instance"] is None


@pytest.mark.parametrize("module", [annual, tax])
def test_real_client_composition_discards_grant_wrapper_and_preserves_external_reference(monkeypatch, module):
    from talli_backend.authority_tools import _grant
    configuration = _grant.CliGrantConfiguration("test", "client", "key", "synthetic-private-key",
        annual.SCOPE if module is annual else " ".join(tax.SCOPES), ORG, "environment-ref")
    monkeypatch.setattr(_grant.CliGrantConfiguration, "from_environment", lambda _: configuration)
    observed = []
    class Token:
        access_token = TAX_TOKEN
        def discard(self): observed.append("discarded")
    async def request_token(config):
        observed.append(config.system_user_external_ref)
        return Token()
    async def exchange(token):
        assert token == TAX_TOKEN
        return ALTINN_TOKEN
    monkeypatch.setattr(_grant, "request_token", request_token)
    monkeypatch.setattr(module, "exchange_maskinporten_for_altinn_token", exchange)
    client = asyncio.run(module._client({}, {"systemUserExternalRef": "original-evidence-ref"}))
    assert isinstance(client, annual_http.AnnualAccountsTransport if module is annual else tax_http.CompanyTaxTransport)
    assert observed == ["original-evidence-ref" if module is annual else "environment-ref", "discarded"]
