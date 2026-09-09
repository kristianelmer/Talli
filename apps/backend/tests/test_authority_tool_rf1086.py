"""Real RF command/transport with fake authority only; preserves saved evidence."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from test_authority_tool_grant import grant_environment
from talli_backend.authority_tools import rf1086_test as tool
from talli_backend.modules.shareholder_register_filing.public import Rf1086AuthorityError

ROOT = Path(__file__).resolve().parents[3]
MAIN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
DIALOG_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ARCHIVE_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
SECRET = "local-only-private-bearer"


@pytest.fixture
def rf_environment(grant_environment, tmp_path):
    case_path = tmp_path / "case.json"
    case = json.loads((ROOT / "tests/fixtures/rf1086/stiftelse.json").read_text())
    case_path.write_text(json.dumps(case))
    return grant_environment | {"PATH": os.environ.get("PATH", ""), "TALLI_PYTHON_BIN": sys.executable,
        "TALLI_RF1086_APPROVED_TEST_WRITE": "true", "TALLI_MASKINPORTEN_SCOPE": tool.RF1086_SCOPE,
        "TALLI_RF1086_CASE_PATH": str(case_path), "TALLI_RF1086_EVIDENCE_PATH": str(tmp_path / "proof/evidence.json"),
        "TALLI_MASKINPORTEN_SYSTEM_USER_ORG": case["company"]["org_number"]}


@pytest.fixture
def fake_xml(monkeypatch):
    calls = []
    main = "<?xml version=\"1.0\"?>\r\n<Skjema>Å</Skjema>\r\n"
    under = "<Skjema>ø</Skjema>\r\n"
    def generate(raw_case, output):
        calls.append(("generate", raw_case))
        (output / "1086H.xml").write_bytes(main.encode())
        (output / "1086U-founder.xml").write_bytes(under.encode())
    def validate(main_path, under_paths, environment):
        calls.append(("validate", main_path, tuple(under_paths)))
    monkeypatch.setattr(tool, "_generate_xml", generate)
    monkeypatch.setattr(tool, "_validate_xml", validate)
    return calls, main, under


def execute(environment, *, handler=None, sleeps=None):
    calls = []
    def respond(request):
        calls.append(request)
        if handler:
            result = handler(request)
            if result is not None:
                return result
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": SECRET, "expires_in": 119})
        if request.url.path.endswith("/1086H"):
            return httpx.Response(200, json={"hovedskjemaId": MAIN_ID})
        if request.url.path.endswith("/1086U"):
            return httpx.Response(200, json={})
        if request.url.path.endswith("/bekreft"):
            return httpx.Response(200, json={"oppgavegiversLeveranseReferanse": "original-receipt",
                "dialogId": DIALOG_ID, "forsendelseId": ARCHIVE_ID})
        if request.url.path.endswith("/dokumenter"):
            return httpx.Response(200, json={"dokumenter": ["<archive>å\r\n</archive>"], "totalItems": 1,
                                            "totalPages": 1, "currentPage": 0})
        pytest.fail("Unexpected method: " + request.method + " " + str(request.url))
    async def sleep(seconds):
        if sleeps is not None:
            sleeps.append(seconds)
    transport = httpx.MockTransport(respond)
    try:
        return asyncio.run(tool.run(environment, token_transport=transport, authority_transport=transport, sleep=sleep)), calls
    except Exception as error:
        error.test_calls = calls
        raise


def evidence(environment):
    return json.loads(Path(environment["TALLI_RF1086_EVIDENCE_PATH"]).read_text())


def test_four_exact_methods_preserve_xml_bytes_keys_and_embedded_archive_hash(rf_environment, fake_xml):
    summary, calls = execute(rf_environment)
    stored = evidence(rf_environment)
    assert [request.method for request in calls] == ["POST", "POST", "POST", "POST", "GET"]
    assert [request.url.path.split("/")[-1] for request in calls] == ["token", "1086H", "1086U", "bekreft", "dokumenter"]
    assert calls[1].content == fake_xml[1].encode() and calls[2].content == fake_xml[2].encode()
    assert calls[1].headers["idempotencykey"] == stored["idempotencyKeys"]["hovedskjema"]
    assert calls[2].headers["idempotencykey"] == stored["idempotencyKeys"]["underskjema"]["founder"]
    assert calls[3].headers["idempotencykey"] == stored["idempotencyKeys"]["bekreft"]
    assert calls[3].url.query == b"antall_underskjema=1"
    assert calls[4].url.query == b"page=0&size=50" and ARCHIVE_ID in str(calls[4].url)
    assert stored["payloadHashes"]["hovedskjema"] == hashlib.sha256(fake_xml[1].encode()).hexdigest()
    assert stored["archive"]["documentHashes"] == [hashlib.sha256("<archive>å\r\n</archive>".encode()).hexdigest()]
    assert summary == {"ok": True, "status": "accepted", "environment": "test", "companyOrgNumber": "314259521",
        "incomeYear": 2025, "hovedskjemaId": MAIN_ID, "receiptReference": "original-receipt", "dialogId": DIALOG_ID,
        "archiveReference": ARCHIVE_ID, "archivedDocumentCount": 1, "evidencePath": rf_environment["TALLI_RF1086_EVIDENCE_PATH"]}
    assert SECRET not in json.dumps(stored) + json.dumps(summary)
    assert Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"]).stat().st_mode & 0o077 == 0


def test_accepted_replay_reads_no_key_or_token_and_does_not_rewrite_evidence(rf_environment, fake_xml):
    original, _ = execute(rf_environment)
    path = Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"])
    previous = path.read_bytes()
    del rf_environment["TALLI_MASKINPORTEN_PRIVATE_KEY_PATH"]
    summary, calls = execute(rf_environment)
    assert summary == original and calls == [] and path.read_bytes() == previous


def test_retry_continues_original_durable_uuid_intent_and_skips_already_recorded_writes(rf_environment, fake_xml):
    def fail_subdocument(request):
        if request.url.path.endswith("/1086U"):
            return httpx.Response(503, json={"kode": "GLD_004", "melding": SECRET})
    with pytest.raises(Rf1086AuthorityError):
        execute(rf_environment, handler=fail_subdocument)
    previous = evidence(rf_environment)
    assert previous["status"] == "failed_retryable" and previous["hovedskjema"]["hovedskjemaId"] == MAIN_ID
    summary, calls = execute(rf_environment)
    current = evidence(rf_environment)
    assert [request.url.path.split("/")[-1] for request in calls] == ["token", "1086U", "bekreft", "dokumenter"]
    assert current["preparedAt"] == previous["preparedAt"] and current["idempotencyKeys"] == previous["idempotencyKeys"]
    assert summary["status"] == "accepted" and SECRET not in json.dumps(previous)


def test_confirmed_retry_only_lists_original_archive(rf_environment, fake_xml):
    def fail_archive(request):
        if request.url.path.endswith("/dokumenter"):
            return httpx.Response(503, json={"kode": "GLD_004"})
    with pytest.raises(Rf1086AuthorityError):
        execute(rf_environment, handler=fail_archive)
    previous = evidence(rf_environment)
    _, calls = execute(rf_environment)
    assert [request.url.path.split("/")[-1] for request in calls] == ["token", "dokumenter"]
    assert evidence(rf_environment)["confirmation"] == previous["confirmation"]


def test_malformed_saved_keys_are_never_replaced_with_new_provider_intent(rf_environment, fake_xml):
    def failed_main(request):
        if request.url.path.endswith("/1086H"):
            return httpx.Response(503, json={"kode": "GLD_004"})
    with pytest.raises(Rf1086AuthorityError):
        execute(rf_environment, handler=failed_main)
    saved = evidence(rf_environment)
    saved["idempotencyKeys"] = {}
    Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"]).write_text(json.dumps(saved))
    with pytest.raises(KeyError) as caught:
        execute(rf_environment)
    assert [request.url.path.split("/")[-1] for request in caught.value.test_calls] == ["token"]
    assert evidence(rf_environment)["idempotencyKeys"] == {}


@pytest.mark.parametrize("archive", ["empty", "eventual404"])
def test_five_archive_attempts_and_four_delays_preserve_polling(rf_environment, fake_xml, archive):
    count = 0
    def pending(request):
        nonlocal count
        if request.url.path.endswith("/dokumenter"):
            count += 1
            if archive == "eventual404":
                return httpx.Response(404, json={"kode": "GLD_021", "spesifisering": [{"kode": "GLD_1017"}]})
            return httpx.Response(200, json={"dokumenter": [], "totalItems": 0})
    sleeps = []
    with pytest.raises((ValueError, Rf1086AuthorityError)):
        execute(rf_environment, handler=pending, sleeps=sleeps)
    assert count == 5 and sleeps == [2, 2, 2, 2]
    assert evidence(rf_environment)["status"] == "failed_blocked"


def test_reference_archive_remains_blocked_without_new_document_get(rf_environment, fake_xml):
    def reference(request):
        if request.url.path.endswith("/dokumenter"):
            return httpx.Response(200, json={"dokumenter": [{"dokumentId": ARCHIVE_ID}]})
    with pytest.raises(AttributeError) as caught:
        execute(rf_environment, handler=reference)
    assert [r.method for r in caught.value.test_calls].count("GET") == 1
    assert evidence(rf_environment)["status"] == "failed_blocked"


@pytest.mark.parametrize("field,value", [
    ("TALLI_RF1086_APPROVED_TEST_WRITE", "false"), ("TALLI_RF1086_APPROVED_TEST_WRITE", "TRUE"),
    ("TALLI_MASKINPORTEN_ENVIRONMENT", "production"), ("TALLI_MASKINPORTEN_SCOPE", "other:scope"),
    ("TALLI_MASKINPORTEN_SYSTEM_USER_ORG", "123456789"),
])
def test_environment_write_scope_and_company_gates_precede_generation_and_network(rf_environment, fake_xml, field, value):
    with pytest.raises(ValueError) as caught:
        execute(rf_environment | {field: value})
    assert fake_xml[0] == [] and caught.value.test_calls == []


def test_unsupported_events_and_changed_payload_never_reuse_saved_intent(rf_environment, fake_xml):
    execute(rf_environment)
    saved = Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"]).read_bytes()
    case_path = Path(rf_environment["TALLI_RF1086_CASE_PATH"])
    case = json.loads(case_path.read_text())
    case["events"] = [{"type": "dividend"}]
    case_path.write_text(json.dumps(case))
    with pytest.raises(ValueError, match="limited"):
        execute(rf_environment)
    case["events"] = []
    case["company"]["income_year"] = 2024
    case_path.write_text(json.dumps(case))
    with pytest.raises(ValueError, match="different payload") as caught:
        execute(rf_environment)
    assert caught.value.test_calls == [] and Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"]).read_bytes() == saved


@pytest.mark.parametrize("reflected", [SECRET, "prefix-" + SECRET, "Bearer another-private-value",
                                        "-----BEGIN " "PRIVATE KEY-----private", "eyJabc.eyJdef.signature"])
def test_success_response_reflection_is_blocked_before_evidence_or_summary(rf_environment, fake_xml, reflected):
    def echo(request):
        if request.url.path.endswith("/bekreft"):
            return httpx.Response(200, json={"oppgavegiversLeveranseReferanse": reflected,
                                            "dialogId": DIALOG_ID, "forsendelseId": ARCHIVE_ID})
    with pytest.raises(Rf1086AuthorityError, match="RF1086_RESPONSE_SECRET"):
        execute(rf_environment, handler=echo)
    stored = evidence(rf_environment)
    assert stored["confirmation"] is None and reflected not in json.dumps(stored)


def test_actual_canonical_generation_preserves_source_xml_bytes(rf_environment, monkeypatch):
    monkeypatch.chdir(ROOT)
    summary, calls = execute(rf_environment)
    assert summary["status"] == "accepted"
    output = Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"]).parent / "xml"
    assert calls[1].content == (output / "1086H.xml").read_bytes()
    assert calls[2].content == (output / "1086U-founder.xml").read_bytes()
    assert evidence(rf_environment)["payloadHashes"]["hovedskjema"] == hashlib.sha256(calls[1].content).hexdigest()


@pytest.mark.parametrize("name", ["no_activity", "stiftelse", "stiftelse_two_founders"])
def test_tool_generates_exact_pinned_predecessor_fixture_bytes_before_mock_send(rf_environment, name):
    vectors = json.loads((Path(__file__).parent / "fixtures/rf1086_oracle/python-oracle.json").read_text())
    vector = next(row for row in vectors if row["name"] == name)
    Path(rf_environment["TALLI_RF1086_CASE_PATH"]).write_text(json.dumps(vector["input"]))
    rf_environment["TALLI_MASKINPORTEN_SYSTEM_USER_ORG"] = vector["input"]["company"]["org_number"]
    summary, calls = execute(rf_environment)
    assert summary["status"] == "accepted"
    assert calls[1].content == vector["output"]["hovedskjemaXml"].encode("utf-8")
    children = [request.content for request in calls if request.url.path.endswith("/1086U")]
    expected = vector["output"]["underskjemaXml"]
    assert children == [expected[key].encode("utf-8") for key in tool._shareholder_write_order(list(expected), rf_environment)]


def test_missing_local_xml_validator_stops_before_token_or_existing_evidence_mutation(rf_environment):
    path = Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"])
    path.parent.mkdir(parents=True)
    original = b'{"private":"existing journal remains unchanged"}\n'
    path.write_bytes(original)
    rf_environment["PATH"] = ""
    with pytest.raises(ValueError, match="Local RF-1086 command failed") as caught:
        execute(rf_environment)
    assert caught.value.test_calls == [] and path.read_bytes() == original


def test_invalid_generated_xml_cannot_reach_evidence_or_token(rf_environment, monkeypatch):
    def malformed(_case, output):
        (output / "1086H.xml").write_bytes(b"<wrong-schema/>")
        (output / "1086U-founder.xml").write_bytes(b"<wrong-schema/>")
    monkeypatch.setattr(tool, "_generate_xml", malformed)
    with pytest.raises(ValueError, match="Local RF-1086 command failed") as caught:
        execute(rf_environment)
    assert caught.value.test_calls == []
    assert not Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"]).exists()


def test_local_xml_validation_subprocess_never_receives_credentials(rf_environment, monkeypatch):
    seen = []
    actual_popen = tool.subprocess.Popen
    def launch(arguments, **kwargs):
        seen.append((arguments, kwargs))
        return actual_popen([sys.executable, "-c", "pass"], **kwargs)
    monkeypatch.setattr(tool.subprocess, "Popen", launch)
    tool._run_xml_command(["xmllint", "--noout", "--schema", "schema.xsd", "input.xml"], rf_environment | {"NODE_OPTIONS": "private"})
    assert seen[0][0] == ["xmllint", "--noout", "--schema", "schema.xsd", "input.xml"]
    assert set(seen[0][1]["env"]) <= {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}


@pytest.mark.parametrize("stream", ["stdout", "stderr", "combined"])
def test_xml_validator_is_killed_and_reaped_when_output_exceeds_eight_mib(rf_environment, tmp_path, monkeypatch, stream):
    marker = tmp_path / "should-not-be-reached"
    children = []
    actual_popen = tool.subprocess.Popen
    script = ("import os,sys;from pathlib import Path;block=b'x'*65536;"
              "[(os.write(1 if sys.argv[2]=='stdout' or (sys.argv[2]=='combined' and n<64) else 2,block)) for n in range(144)];"
              "Path(sys.argv[1]).write_text('generator continued past output cap')")
    def launch(_arguments, **kwargs):
        process = actual_popen([sys.executable, "-c", script, str(marker), stream], **kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(tool.subprocess, "Popen", launch)
    with pytest.raises(ValueError, match="Local RF-1086 command failed"):
        tool._run_xml_command(["xmllint"], rf_environment)
    assert not marker.exists() and len(children) == 1
    assert children[0].returncode is not None and children[0].returncode != 0
    with pytest.raises(ChildProcessError):
        os.waitpid(children[0].pid, os.WNOHANG)


def test_xml_validator_accepts_exact_eight_mib_and_reaps_normal_or_failed_exit(rf_environment, tmp_path, monkeypatch):
    marker = tmp_path / "completed"
    actual_popen = tool.subprocess.Popen
    children = []
    script = ("import os,sys;from pathlib import Path;block=b'x'*65536;"
              "[os.write(1,block) for _ in range(128)];Path(sys.argv[1]).write_text('finished')")
    def launch(_arguments, **kwargs):
        process = actual_popen([sys.executable, "-c", script, str(marker)], **kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(tool.subprocess, "Popen", launch)
    tool._run_xml_command(["xmllint"], rf_environment)
    assert marker.read_text() == "finished" and children[0].returncode == 0
    script = "import sys;sys.stderr.write('private-child-diagnostic');sys.exit(7)"
    with pytest.raises(ValueError) as caught:
        tool._run_xml_command(["xmllint"], rf_environment)
    assert children[1].returncode == 7 and "private" not in str(caught.value)


def test_embedded_lone_surrogate_document_uses_original_javascript_utf8_hash(rf_environment, fake_xml):
    document = "<archive>\ud800</archive>"
    def archive(request):
        if request.url.path.endswith("/dokumenter"):
            return httpx.Response(200, content=json.dumps({"dokumenter": [document]}).encode(),
                                  headers={"content-type": "application/json"})
    result, _ = execute(rf_environment, handler=archive)
    assert result["status"] == "accepted"
    assert evidence(rf_environment)["archive"]["documentHashes"] == [
        "364ce93a9ca6cf5f38f09521b8e5e3be95c1da9e884e266338b6ea0c8fbc1913"]


def test_saved_lone_surrogate_receipt_round_trips_without_changing_original_intent(rf_environment, fake_xml):
    receipt = "original-\ud800-receipt"
    def confirmation(request):
        if request.url.path.endswith("/bekreft"):
            return httpx.Response(200, content=json.dumps({"oppgavegiversLeveranseReferanse": receipt,
                "dialogId": DIALOG_ID, "forsendelseId": ARCHIVE_ID}).encode(), headers={"content-type": "application/json"})
    summary, _ = execute(rf_environment, handler=confirmation)
    saved = Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"]).read_bytes()
    assert summary["receiptReference"] == receipt
    assert b"\\ud800" in saved and json.loads(saved)["confirmation"]["oppgavegiversLeveranseReferanse"] == receipt
    repeated, calls = execute(rf_environment)
    assert repeated == summary and calls == []
    assert Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"]).read_bytes() == saved


def test_json_evidence_and_hashes_match_node_surrogate_and_unicode_encoding(tmp_path):
    value = json.loads('{"Å": ["\\ud800", "\\udfff", "\\ud83d\\ude00", "ø", "literal\\\\ud800"]}')
    serialized = json.dumps(value)
    original = subprocess.run(["node", "--input-type=module", "-e",
        "import{createHash}from'node:crypto';const v=JSON.parse(process.argv[1]);"
        "console.log(JSON.stringify({json:JSON.stringify(v,null,2)+'\\n',hashes:v['Å'].map(s=>createHash('sha256').update(s).digest('hex'))}));",
        serialized], capture_output=True, text=True, check=True)
    expected = json.loads(original.stdout)
    path = tmp_path / "evidence.json"
    tool._write_json(path, value)
    assert path.read_bytes() == expected["json"].encode()
    assert [tool._sha256(item) for item in value["Å"]] == expected["hashes"]


def test_atomic_evidence_ignores_legacy_predictable_symlink_and_cleans_failed_temporary(tmp_path, monkeypatch):
    path = tmp_path / "evidence.json"
    victim = tmp_path / "unrelated.txt"
    victim.write_text("unchanged")
    victim.chmod(0o644)
    legacy = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    legacy.symlink_to(victim)
    tool._write_json(path, {"status": "original"})
    assert victim.read_text() == "unchanged" and victim.stat().st_mode & 0o777 == 0o644
    assert path.stat().st_mode & 0o077 == 0
    previous = path.read_bytes()
    def fail_replace(_self, _target):
        raise OSError("simulated local rename failure")
    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError):
        tool._write_json(path, {"status": "new"})
    assert path.read_bytes() == previous and list(tmp_path.glob(".evidence.json.*.tmp")) == []


def test_mixed_case_astral_and_nonascii_order_matches_original_node_source(rf_environment):
    identifiers = ["z", "A", "a", "å", "æ", "ø", "é", "e", "𐀀", "\ue000", "2", "10", "01"]
    actual = tool._shareholder_write_order(identifiers, rf_environment | {"NODE_OPTIONS": "--invalid-private-option"})
    original = subprocess.run(["node", "-e",
        "const ids=JSON.parse(process.argv[1]);console.log(JSON.stringify({"
        "write:Object.entries(Object.fromEntries(ids.map(id=>[id,'xml']))).sort(([a],[b])=>a.localeCompare(b)).map(([id])=>id),"
        "defaults:ids.sort(),objectKeys:Object.keys(Object.fromEntries(ids.map(id=>[id,'xml'])))}));",
        json.dumps(identifiers)], env={"PATH": rf_environment["PATH"]}, capture_output=True, text=True, check=True)
    expected = json.loads(original.stdout)
    assert actual == expected["write"]
    defaults = sorted(identifiers, key=tool._utf16)
    assert defaults == expected["defaults"]
    assert list(dict(tool._object_items(dict.fromkeys(defaults, "xml")))) == expected["objectKeys"]


def test_ordering_subprocess_receives_only_identifiers_and_runtime_locale(rf_environment, monkeypatch):
    captured = []
    def run(arguments, **kwargs):
        captured.append((arguments, kwargs))
        return type("Result", (), {"returncode": 0, "stdout": '["a","A"]'})()
    monkeypatch.setattr(tool.subprocess, "run", run)
    assert tool._shareholder_write_order(["A", "a"], rf_environment | {
        "NODE_OPTIONS": "private", "LANG": "nb_NO.UTF-8", "LC_COLLATE": "nb_NO.UTF-8"}) == ["a", "A"]
    arguments, kwargs = captured[0]
    assert arguments[:2] == ["node", "-e"] and "localeCompare" in arguments[2]
    assert json.loads(kwargs["input"]) == ["A", "a"]
    assert set(kwargs["env"]) == {"PATH", "LANG", "LC_COLLATE"}
    assert kwargs["timeout"] == 30 and SECRET not in str(captured)


def test_original_harness_pagination_projection_does_not_gain_an_acceptance_gate(rf_environment, fake_xml):
    def mixed_page(request):
        if request.url.path.endswith("/dokumenter"):
            return httpx.Response(200, json={"dokumenter": ["<archive/>"], "totalItems": "1", "totalPages": "unknown"})
    summary, _ = execute(rf_environment, handler=mixed_page)
    assert summary["status"] == "accepted" and evidence(rf_environment)["archive"]["totalPages"] is None


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_rf_case_rejects_non_json_constants_before_generation_or_transport(rf_environment, fake_xml, constant):
    path = Path(rf_environment["TALLI_RF1086_CASE_PATH"])
    path.write_text(path.read_text().rstrip()[:-1] + ',"ignored":{"values":[' + constant + ']}}')
    with pytest.raises(ValueError) as caught:
        execute(rf_environment)
    assert caught.value.test_calls == [] and fake_xml[0] == []
    assert not Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"]).exists()


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_rf_prior_evidence_rejects_non_json_constants_without_rewrite_or_transport(rf_environment, fake_xml, constant):
    execute(rf_environment)
    path = Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"])
    path.write_text(path.read_text().rstrip()[:-1] + ',"ignored":{"values":[' + constant + ']}}')
    previous = path.read_bytes()
    with pytest.raises(ValueError) as caught:
        execute(rf_environment)
    assert caught.value.test_calls == [] and path.read_bytes() == previous


def test_rf_case_and_prior_evidence_keep_json_strings_named_like_nonfinite_constants(rf_environment, fake_xml):
    case_path = Path(rf_environment["TALLI_RF1086_CASE_PATH"])
    case = json.loads(case_path.read_text())
    case["ignored"] = ["NaN", "Infinity", "-Infinity"]
    case_path.write_text(json.dumps(case))
    original, _ = execute(rf_environment)
    evidence_path = Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"])
    stored = evidence(rf_environment)
    stored["ignored"] = ["NaN", "Infinity", "-Infinity"]
    evidence_path.write_text(json.dumps(stored))
    previous = evidence_path.read_bytes()
    replayed, calls = execute(rf_environment)
    assert replayed == original and calls == [] and evidence_path.read_bytes() == previous
