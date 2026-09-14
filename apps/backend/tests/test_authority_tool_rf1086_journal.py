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
