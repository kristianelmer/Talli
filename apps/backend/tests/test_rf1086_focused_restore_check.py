"""Focused diagnostics cannot turn a rejected or incomplete restore into proof."""
from contextlib import contextmanager, nullcontext
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("focused_restore_driver", ROOT / "scripts/rf1086_focused_restore_check.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def receipt(*, success=False, clean=True, source_post=True, reason="postcondition"):
    before = dict.fromkeys(("roles", "catalog", "auth", "companyMemberships"), "a" * 64)
    return {
        "schema": driver.control.SCHEMA,
        "status": "constructed" if success else "unavailable",
        "reason": None if success else reason,
        "configurationSha256": "c" * 64,
        "code": None, "bindings": None, "identities": None, "counts": None,
        "hooks": None, "mutations": None, "delivery": None, "observers": None,
        "fingerprints": {"source": before, "target": dict(before) if success else before | {"catalog": "b" * 64}},
        "cleanupComplete": clean, "identitySourcePostcheck": source_post,
        "businessComplete": success, "outerBusinessPostchecks": None,
        "phaseElapsedSeconds": {},
    }


def install_context(monkeypatch, value, *, error=None, yield_context=False, repeats=1, extra=""):
    @contextmanager
    def restore(*args, **kwargs):
        try:
            if yield_context:
                yield object()
            elif error is not None:
                raise error
            else:
                raise ValueError("private rejection details")
        finally:
            for _ in range(repeats):
                print(driver.CONSTRUCTION_PREFIX + driver.control.ledger.canonical(value).decode("ascii"), file=sys.stderr)
            if extra:
                print(extra, file=sys.stderr)
    monkeypatch.setattr(driver.identity, "restored_identity", restore)


def observe():
    return driver.run_context("postgresql://private", "http://127.0.0.1:54321", Path("/private/fixture"), object(), object())


def test_rejected_catalog_is_a_diagnostic_result_not_recovery_success(monkeypatch, capsys):
    value = receipt()
    install_context(monkeypatch, value, extra="private row contents that must not be echoed")
    result = observe()
    assert result["identityOutcome"] == "catalog_postcondition_rejected"
    assert not result["identityContextEntered"] and not result["identityContextCompleted"]
    assert result["constructionReceiptSha256"] == hashlib.sha256(driver.control.ledger.canonical(value)).hexdigest()
    assert capsys.readouterr() == ("", "")
    assert "private row contents" not in json.dumps(result)


def test_empty_caller_completion_is_only_identity_context_completion(monkeypatch):
    install_context(monkeypatch, receipt(success=True), yield_context=True)
    result = observe()
    assert result["identityOutcome"] == "identity_context_completed"
    assert result["identityContextEntered"] and result["identityContextCompleted"]
    # The outer envelope always qualifies the no-op caller as business-unverified.
    assert "businessVerified" not in result


@pytest.mark.parametrize("changes", [{"clean": False}, {"source_post": False}, {"reason": "cleanup_uncertain"}, {"reason": "deadline"}])
def test_incomplete_cleanup_source_check_or_different_failure_stays_unavailable(monkeypatch, changes):
    install_context(monkeypatch, receipt(**changes))
    assert observe()["identityOutcome"] == "unavailable"


def test_matching_hashes_without_completed_context_are_not_success(monkeypatch):
    install_context(monkeypatch, receipt(success=True))
    assert observe()["identityOutcome"] == "unavailable"


def test_repeated_receipt_rejects_ambiguous_result(monkeypatch):
    install_context(monkeypatch, receipt(), repeats=2)
    with pytest.raises(ValueError, match="^producer_output$"):
        observe()


def test_diagnostic_must_bind_the_same_construction_receipt(monkeypatch):
    diagnostic = {"schema": driver.control.CATALOG_DIAGNOSTIC_SCHEMA, "status": "unavailable",
                  "reason": "input", "constructionSha256": "0" * 64,
                  "source": None, "target": None, "difference": None}
    install_context(monkeypatch, receipt(), extra=driver.CATALOG_PREFIX + driver.control.ledger.canonical(diagnostic).decode("ascii"))
    with pytest.raises(ValueError):
        observe()


def test_bound_unavailable_diagnostic_remains_explicit(monkeypatch):
    value = receipt()
    diagnostic = {"schema": driver.control.CATALOG_DIAGNOSTIC_SCHEMA, "status": "unavailable",
                  "reason": "input", "constructionSha256": hashlib.sha256(driver.control.ledger.canonical(value)).hexdigest(),
                  "source": None, "target": None, "difference": None}
    install_context(monkeypatch, value, extra=driver.CATALOG_PREFIX + driver.control.ledger.canonical(diagnostic).decode("ascii"))
    assert observe()["catalogDiagnostic"] == diagnostic


def test_preparation_refusal_retains_only_existing_closed_diagnostic(monkeypatch):
    diagnostic = {"schema": driver.control.DIAGNOSTIC_SCHEMA, "step": "unclassified",
                  "component": "unknown", "reason": "internal",
                  "inputs": dict.fromkeys(("source", "archive", "roles", "scriptBytes", "script", "archiveRows")),
                  "ledger": None, "lexicalLimit": None, "location": None}
    value = receipt(reason="metadata_profile")
    value["fingerprints"]["target"] = None
    install_context(monkeypatch, value, extra=driver.control.DIAGNOSTIC_PREFIX + driver.control.ledger.canonical(diagnostic).decode("ascii"))
    result = observe()
    assert result["identityOutcome"] == "unavailable"
    assert result["preTargetDiagnostic"] == diagnostic


def test_preparation_diagnostic_extra_private_fields_reject(monkeypatch):
    install_context(monkeypatch, receipt(), extra=driver.control.DIAGNOSTIC_PREFIX + '{"private":"must-not-escape"}')
    with pytest.raises(ValueError):
        observe()


def test_unknown_top_level_receipt_fields_never_escape(monkeypatch):
    install_context(monkeypatch, receipt() | {"privateValue": "sensitive"})
    with pytest.raises(ValueError, match="^producer_output$"):
        observe()


@pytest.mark.parametrize("payload", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'])
def test_ambiguous_nonfinite_producer_json_rejects(payload):
    with pytest.raises(ValueError):
        driver.strict_json(payload)


def test_private_output_cap_fails_without_retaining_overflow():
    private = driver.PrivateOutput()
    private.write("x" * driver.MAX_OUTPUT)
    with pytest.raises(ValueError, match="^producer_output$"):
        private.write("sensitive overflow")
    assert private.bytes == driver.MAX_OUTPUT and len(private.parts) == 1
    private.clear()
    assert private.parts == [] and private.bytes == 0


def test_noncanonical_carrier_is_not_admitted():
    private = driver.PrivateOutput()
    private.write(driver.CONSTRUCTION_PREFIX + '{ "schema" : "x" }\n')
    with pytest.raises(ValueError, match="^producer_output$"):
        private.records(driver.CONSTRUCTION_PREFIX)


def test_cancellation_identity_environment_and_private_capture_are_preserved(monkeypatch):
    primary = KeyboardInterrupt()
    install_context(monkeypatch, receipt(), error=primary)
    monkeypatch.setenv("DATABASE_URL", "original-private")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    cleared = []
    original = driver.PrivateOutput.clear
    def clear(self):
        original(self)
        cleared.append(self.bytes == 0 and self.parts == [])
    monkeypatch.setattr(driver.PrivateOutput, "clear", clear)
    with pytest.raises(KeyboardInterrupt) as caught:
        observe()
    assert caught.value is primary
    assert os.environ["DATABASE_URL"] == "original-private"
    assert "SUPABASE_URL" not in os.environ and cleared == [True]


@pytest.mark.parametrize("error", [ValueError("secret SQL"), RuntimeError("private password")])
def test_main_projects_only_closed_failure_reason(monkeypatch, capsys, error):
    def fail():
        raise error
    monkeypatch.setattr(driver, "check", fail)
    assert driver.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"schema": driver.SCHEMA, "status": "unavailable", "reason": "focused_restore_unavailable"}
    assert str(error) not in captured.err


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit("private cancellation message")])
def test_main_cancellation_is_finite_failure(monkeypatch, capsys, error):
    def fail():
        raise error
    monkeypatch.setattr(driver, "check", fail)
    assert driver.main() == 130
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {"schema": driver.SCHEMA, "status": "unavailable", "reason": "cancelled"}
    assert "private" not in captured.err and captured.out == ""


@pytest.fixture
def bound_driver(monkeypatch, tmp_path):
    workdir = tmp_path / "talli-supabase-local.generated"
    (workdir / "supabase").mkdir(parents=True)
    (workdir / "supabase/config.toml").write_text('project_id = "tallig123"\n')
    for key, value in {"TALLI_FOCUSED_WORKDIR": str(workdir), "GITHUB_RUN_ID": "123",
                       "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "focused-restore", "GITHUB_SHA": "a" * 40}.items():
        monkeypatch.setenv(key, value)
    state = {"head": "a" * 40, "image": driver.IMAGE, "version": "17.6", "contexts": 0, "commands": []}
    class Budget:
        def __init__(self, started):
            self.end = started + 115
        def enter(self, phase):
            state["phase"] = phase
        def command(self, args, **kwargs):
            state["commands"].append(args)
            if args[:2] == ["git", "rev-parse"]:
                return state["head"].encode() + b"\n"
            if args[0] == "npm":
                return b'{"DB_URL":"postgresql://private","API_URL":"http://127.0.0.1:54321","SECRET_KEY":"must-never-escape"}'
            if args[1] == "inspect":
                return state["image"].encode() + b"\n"
            if "psql" in args:
                return state["version"].encode() + b"\n"
            return b"pg_dump (PostgreSQL) 17.6\n"
    def context(*args):
        state["contexts"] += 1
        return {"identityOutcome": "catalog_postcondition_rejected", "identityContextEntered": False,
                "identityContextCompleted": False, "construction": receipt(),
                "constructionReceiptSha256": "c" * 64, "catalogDiagnostic": None, "preTargetDiagnostic": None}
    monkeypatch.setattr(driver.control, "RecoveryBudget", Budget)
    monkeypatch.setattr(driver.control, "io_deadline", lambda *a, **k: nullcontext())
    monkeypatch.setattr(driver, "source_bindings", lambda: {"fixture": "b" * 64})
    monkeypatch.setattr(driver, "run_context", context)
    return state


def test_outer_report_never_promotes_diagnostic_to_business_or_historical_proof(bound_driver, capsys):
    assert driver.check(time.monotonic()) == 1
    value = json.loads(capsys.readouterr().out)
    assert value["identityOutcome"] == "catalog_postcondition_rejected"
    assert value["businessVerified"] is False and value["originalArchiveReplayed"] is False
    assert value["originalFailureCauseKnown"] is False
    assert value["diagnosticComplete"] is False
    assert value["scope"] == "generated_same_image_production_identity_context"
    assert "must-never-escape" not in json.dumps(value)
    assert bound_driver["contexts"] == 1 and bound_driver["phase"] == "output"


@pytest.mark.parametrize("key,bad,reason", [("head", "b" * 40, "candidate_binding"),
                                           ("image", "sha256:" + "0" * 64, "image_binding"),
                                           ("version", "17.11", "version_binding")])
def test_wrong_candidate_image_or_version_never_enters_recovery(bound_driver, key, bad, reason):
    bound_driver[key] = bad
    with pytest.raises(ValueError, match=f"^{reason}$"):
        driver.check(time.monotonic())
    assert bound_driver["contexts"] == 0
