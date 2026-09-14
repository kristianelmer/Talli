"""RF test writes stop at uncertain outcomes; all transports are synthetic."""
import httpx
import pytest
from pathlib import Path
from test_authority_tool_grant import grant_environment
from test_authority_tool_rf1086 import rf_environment, fake_xml, execute, evidence
from talli_backend.modules.shareholder_register_filing.public import Rf1086AuthorityError


@pytest.mark.parametrize("stage", ["1086H", "1086U", "bekreft"])
def test_lost_post_response_blocks_replay_before_credentials(rf_environment, fake_xml, stage):
    def lose_response(request):
        if request.url.path.endswith("/" + stage):
            raise httpx.ReadTimeout("synthetic lost response", request=request)
    with pytest.raises(Rf1086AuthorityError):
        execute(rf_environment, handler=lose_response)
    path = Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"])
    saved = path.read_bytes()
    del rf_environment["TALLI_MASKINPORTEN_PRIVATE_KEY_PATH"]
    with pytest.raises(Rf1086AuthorityError, match="RECONCILIATION_REQUIRED") as caught:
        execute(rf_environment)
    assert caught.value.test_calls == [] and path.read_bytes() == saved


@pytest.mark.parametrize("stage", ["1086H", "1086U", "bekreft"])
def test_durable_pending_marker_matches_request_before_transport(rf_environment, fake_xml, stage):
    import hashlib
    def inspect(request):
        if request.url.path.endswith("/" + stage):
            marker = evidence(rf_environment)["pendingOperation"]
            assert marker["bodyHash"] == hashlib.sha256(request.content).hexdigest()
            assert marker["idempotencyKey"] == request.headers["idempotencykey"]
            assert marker["name"] == {"1086H": "hovedskjema", "1086U": "underskjema:founder", "bekreft": "bekreft"}[stage]
    execute(rf_environment, handler=inspect)
    assert evidence(rf_environment)["pendingOperation"] is None


@pytest.mark.parametrize("stage", ["hovedskjema_accepted", "underskjema_accepted", "confirmed"])
def test_response_checkpoint_failure_retains_pending_intent(rf_environment, fake_xml, monkeypatch, stage):
    from talli_backend.authority_tools import rf1086_test as tool
    original_write = tool._write_json
    def fail_checkpoint(path, value):
        if value["status"] == stage:
            raise OSError("synthetic checkpoint failure")
        original_write(path, value)
    monkeypatch.setattr(tool, "_write_json", fail_checkpoint)
    with pytest.raises(OSError):
        execute(rf_environment)
    saved = Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"]).read_bytes()
    assert evidence(rf_environment)["pendingOperation"] is not None
    with pytest.raises(Rf1086AuthorityError, match="RECONCILIATION_REQUIRED") as caught:
        execute(rf_environment)
    assert caught.value.test_calls == []
    assert Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"]).read_bytes() == saved


def _hold_post(environment, connection, stage):
    def hold(request):
        if request.url.path.endswith("/" + stage):
            connection.send("pending POST reached")
            connection.recv()
    execute(environment, handler=hold)


@pytest.mark.parametrize("stage", ["1086H", "1086U", "bekreft"])
def test_process_owner_blocks_alias_and_death_keeps_unknown_intent(rf_environment, fake_xml, tmp_path, stage):
    import multiprocessing
    context = multiprocessing.get_context("fork")
    parent, child = context.Pipe()
    process = context.Process(target=_hold_post, args=(rf_environment, child, stage))
    process.start()
    try:
        assert parent.poll(10), "child did not reach the synthetic POST"
        assert parent.recv() == "pending POST reached"
        path = Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"])
        saved = path.read_bytes()
        alias = tmp_path / "alias"
        alias.symlink_to(path.parent, target_is_directory=True)
        contender = rf_environment | {"TALLI_RF1086_EVIDENCE_PATH": str(alias / path.name)}
        with pytest.raises(Rf1086AuthorityError, match="REHEARSAL_IN_PROGRESS") as caught:
            execute(contender)
        assert caught.value.test_calls == [] and fake_xml[0] == []
        assert path.read_bytes() == saved
    finally:
        process.terminate()
        process.join(10)
        parent.close()
        child.close()
        if process.is_alive():
            process.kill()
            process.join(10)
    assert process.exitcode is not None
    with pytest.raises(Rf1086AuthorityError, match="RECONCILIATION_REQUIRED") as caught:
        execute(rf_environment)
    assert caught.value.test_calls == [] and path.read_bytes() == saved


@pytest.mark.parametrize("field,value", [
    ("idempotencyKeys", None), ("idempotencyKeys", {}),
    ("pendingOperation", {}), ("pendingOperation", False),
    ("schemaVersion", 99), ("confirmation", {"forsendelseId": "incomplete"}),
])
def test_bad_saved_intent_never_mutates_or_connects(rf_environment, fake_xml, field, value):
    import json
    execute(rf_environment)
    path = Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"])
    prior = evidence(rf_environment)
    prior[field] = value
    path.write_text(json.dumps(prior))
    saved = path.read_bytes()
    with pytest.raises(Rf1086AuthorityError) as caught:
        execute(rf_environment)
    assert caught.value.test_calls == [] and path.read_bytes() == saved


@pytest.mark.parametrize("status", ["prepared", "hovedskjema_accepted", "failed_retryable", "failed_blocked"])
def test_legacy_unconfirmed_journal_cannot_prove_no_write(rf_environment, fake_xml, status):
    import json
    def fail(request):
        if request.url.path.endswith("/1086U"):
            raise httpx.ReadTimeout("synthetic timeout", request=request)
    with pytest.raises(Rf1086AuthorityError):
        execute(rf_environment, handler=fail)
    prior = evidence(rf_environment)
    prior["schemaVersion"] = 1
    prior["status"] = status
    prior.pop("pendingOperation")
    path = Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"])
    path.write_text(json.dumps(prior))
    saved = path.read_bytes()
    with pytest.raises(Rf1086AuthorityError, match="RECONCILIATION_REQUIRED") as caught:
        execute(rf_environment)
    assert caught.value.test_calls == [] and path.read_bytes() == saved


def test_legacy_confirmed_journal_recovers_through_get_only(rf_environment, fake_xml):
    import json
    def fail(request):
        if request.url.path.endswith("/dokumenter"):
            return httpx.Response(503, json={"kode": "GLD_004"})
    with pytest.raises(Rf1086AuthorityError):
        execute(rf_environment, handler=fail)
    prior = evidence(rf_environment)
    prior["schemaVersion"] = 1
    prior.pop("pendingOperation")
    Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"]).write_text(json.dumps(prior))
    _, calls = execute(rf_environment)
    assert [request.url.path.split("/")[-1] for request in calls] == ["token", "dokumenter"]


def test_storage_flush_failure_prevents_credentials_and_authority(rf_environment, fake_xml, monkeypatch):
    from talli_backend.authority_tools import rf1086_test as tool
    def fail(_descriptor):
        raise OSError("synthetic disk flush failure")
    monkeypatch.setattr(tool.os, "fsync", fail)
    with pytest.raises(OSError) as caught:
        execute(rf_environment)
    assert caught.value.test_calls == []
    assert not Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"]).exists()


def test_new_journal_uses_only_current_canonical_shareholder_extent(rf_environment):
    import json
    execute(rf_environment)
    path = Path(rf_environment["TALLI_RF1086_CASE_PATH"])
    case = json.loads(path.read_text())
    case = json.loads(json.dumps(case).replace('"founder"', '"current-founder"'))
    path.write_text(json.dumps(case))
    next_environment = rf_environment | {
        "TALLI_RF1086_EVIDENCE_PATH": str(Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"]).with_name("second.json"))}
    _, calls = execute(next_environment)
    assert set(evidence(next_environment)["underskjema"]) == {"current-founder"}
    assert sum(request.url.path.endswith("/1086U") for request in calls) == 1


def test_rejected_payload_keeps_all_retained_xml_unchanged(rf_environment):
    import json
    execute(rf_environment)
    path = Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"])
    before = {item: item.read_bytes() for item in path.parent.rglob("*.xml") if item.is_file()}
    case_path = Path(rf_environment["TALLI_RF1086_CASE_PATH"])
    case = json.loads(case_path.read_text())
    case["company"]["name"] = "CHANGED SYNTHETIC COMPANY AS"
    case_path.write_text(json.dumps(case))
    with pytest.raises(ValueError, match="different payload") as caught:
        execute(rf_environment)
    assert caught.value.test_calls == []
    assert {item: item.read_bytes() for item in path.parent.rglob("*.xml") if item.is_file()} == before


@pytest.mark.parametrize("mutation", ["missing", "wrong_reference", "missing_hash", "wrong_method", "wrong_endpoint"])
def test_accepted_replay_requires_bound_archive_evidence(rf_environment, fake_xml, mutation):
    import json
    execute(rf_environment)
    prior = evidence(rf_environment)
    if mutation == "missing":
        prior["archive"] = None
    elif mutation == "wrong_reference":
        prior["archive"]["lookupReferenceId"] = "different"
    elif mutation == "missing_hash":
        prior["archive"]["documentHashes"] = []
    elif mutation == "wrong_method":
        prior["archive"]["call"]["method"] = "POST"
    else:
        prior["archive"]["call"]["endpoint"] = "https://example.invalid/archive"
    path = Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"])
    path.write_text(json.dumps(prior))
    saved = path.read_bytes()
    with pytest.raises(Rf1086AuthorityError, match="SAVED_INTENT_INVALID") as caught:
        execute(rf_environment)
    assert caught.value.test_calls == [] and path.read_bytes() == saved


@pytest.mark.parametrize("checkpoint", ["hovedskjema", "underskjema", "confirmation"])
def test_saved_endpoint_mismatch_blocks_reuse(rf_environment, fake_xml, checkpoint):
    import json
    execute(rf_environment)
    prior = evidence(rf_environment)
    target = prior[checkpoint]
    if checkpoint == "underskjema":
        target = target["founder"]
    target["call"]["endpoint"] = "https://example.invalid/different-operation"
    path = Path(rf_environment["TALLI_RF1086_EVIDENCE_PATH"])
    path.write_text(json.dumps(prior))
    saved = path.read_bytes()
    with pytest.raises(Rf1086AuthorityError, match="SAVED_INTENT_INVALID") as caught:
        execute(rf_environment)
    assert caught.value.test_calls == [] and path.read_bytes() == saved


def test_failed_token_keeps_prepared_keys_for_safe_retry(rf_environment, fake_xml):
    def unavailable(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(503, json={"error": "temporarily_unavailable"})
    with pytest.raises(Exception) as caught:
        execute(rf_environment, handler=unavailable)
    assert [request.url.path.split("/")[-1] for request in caught.value.test_calls] == ["token"]
    saved = evidence(rf_environment)
    assert saved["status"] == "prepared" and saved["pendingOperation"] is None
    execute(rf_environment)
    assert evidence(rf_environment)["idempotencyKeys"] == saved["idempotencyKeys"]


@pytest.mark.parametrize("stage", ["1086H", "1086U", "bekreft"])
def test_malformed_success_response_never_authorizes_replay(rf_environment, fake_xml, stage):
    def malformed(request):
        if request.url.path.endswith("/" + stage):
            return httpx.Response(200, content=b'{"incomplete":', headers={"content-type": "application/json"})
    with pytest.raises(Rf1086AuthorityError):
        execute(rf_environment, handler=malformed)
    saved = evidence(rf_environment)
    assert saved["status"] == "unknown" and saved["pendingOperation"] is not None
    with pytest.raises(Rf1086AuthorityError, match="RECONCILIATION_REQUIRED") as caught:
        execute(rf_environment)
    assert caught.value.test_calls == [] and evidence(rf_environment) == saved


def test_partial_archive_never_mints_success_and_recovers_without_post(rf_environment, fake_xml):
    def partial(request):
        if request.url.path.endswith("/dokumenter"):
            return httpx.Response(200, json={"dokumenter": ["<first/>"], "totalItems": 2,
                                            "totalPages": 2, "currentPage": 0})
    with pytest.raises(Rf1086AuthorityError, match="ARCHIVE_INCOMPLETE"):
        execute(rf_environment, handler=partial)
    saved = evidence(rf_environment)
    assert saved["status"] == "failed_blocked" and saved["archive"] is None
    _, calls = execute(rf_environment)
    assert [request.url.path.split("/")[-1] for request in calls] == ["token", "dokumenter"]
    assert evidence(rf_environment)["idempotencyKeys"] == saved["idempotencyKeys"]
