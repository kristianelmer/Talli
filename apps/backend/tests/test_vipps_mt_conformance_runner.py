"""Run the actual standalone MT adapter through local transport only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_vipps_mt_conformance.py"
spec = importlib.util.spec_from_file_location("vipps_mt_conformance_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
ENV = {
    "TALLI_VIPPS_MT_MERCHANT_SERIAL_NUMBER": "535717",
    "TALLI_VIPPS_MT_CLIENT_ID": "fixture-client-private",
    "TALLI_VIPPS_MT_CLIENT_SECRET": "fixture-secret-private",
    "TALLI_VIPPS_MT_SUBSCRIPTION_KEY": "fixture-subscription-private",
    "TALLI_VIPPS_MT_CONFIRMATION_ORIGINS": "https://apitest.vipps.no",
}


class Merchant:
    def __init__(self):
        self.calls = []
        self.effects = []
        self.agreement = None
        self.charges = {}
        self.keys = {}
        self.lose_create_response = False

    def capture(self, reference):
        charge = self.charges[reference]
        charge["status"] = "CHARGED"
        charge["summary"]["captured"] = charge["amount"]
        charge["history"] = [{"event": "CAPTURE", "amount": charge["amount"], "success": True,
                              "occurred": NOW.isoformat(), "idempotencyKey": "test-capture"}]

    def approve(self):
        self.agreement["status"] = "ACTIVE"
        self.capture(next(iter(self.charges)))

    def charge(self, body, kind):
        reference = body["orderId"]
        self.charges[reference] = {
            "id": reference, "agreementId": self.agreement["id"], "externalId": body["externalId"],
            "amount": body["amount"], "currency": "NOK", "transactionType": "DIRECT_CAPTURE",
            "type": kind, "status": "PENDING", "summary": {"captured": 0, "refunded": 0, "cancelled": 0},
            "history": [],
        }
        return reference

    def __call__(self, request):
        self.calls.append(request)
        assert request.url.host == "apitest.vipps.no"
        assert request.headers["Merchant-Serial-Number"] == "535717"
        if request.url.path == "/accesstoken/get":
            return httpx.Response(200, json={"access_token": "fixture-access-token-private"})
        assert request.headers["Authorization"] == "Bearer fixture-access-token-private"
        path = request.url.path
        if request.method == "GET":
            if path == "/recurring/v3/agreements":
                rows = [self.agreement] if self.agreement and self.agreement["status"] == request.url.params["status"] else []
                return httpx.Response(200, json=rows)
            if "/charges/" in path:
                return httpx.Response(200, json=self.charges[path.rsplit("/", 1)[1]])
            return httpx.Response(200, json=self.agreement)
        key = request.headers["Idempotency-Key"]
        body = json.loads(request.content) if request.content else None
        identity = request.method, path, body
        if key in self.keys:
            saved, status, content = self.keys[key]
            assert identity == saved, "Provider key must bind the exact immutable request"
            return httpx.Response(status, json=content) if content else httpx.Response(status)
        if path == "/recurring/v3/agreements":
            self.agreement = {name: body[name] for name in (
                "externalId", "pricing", "interval", "productName", "merchantRedirectUrl", "merchantAgreementUrl",
            )}
            self.agreement.update(id="agr_" + uuid4().hex, countryCode="NO", status="PENDING",
                                  vippsConfirmationUrl="https://apitest.vipps.no/register?token=private-confirmation")
            reference = self.charge(body["initialCharge"], "INITIAL")
            status, content = 201, {"agreementId": self.agreement["id"], "chargeId": reference,
                                    "vippsConfirmationUrl": self.agreement["vippsConfirmationUrl"]}
        elif request.method == "POST" and path.endswith("/charges"):
            status, content = 201, {"chargeId": self.charge(body, "RECURRING")}
        elif path.endswith("/refund"):
            charge = self.charges[path.split("/")[-2]]
            assert charge["summary"]["refunded"] + body["amount"] <= charge["summary"]["captured"]
            charge["summary"]["refunded"] += body["amount"]
            charge["status"] = "REFUNDED" if charge["summary"]["refunded"] == charge["amount"] else "PARTIALLY_REFUNDED"
            charge["history"].append({"event": "REFUND", "amount": body["amount"], "success": True,
                                      "occurred": NOW.isoformat(), "idempotencyKey": key})
            status, content = 204, None
        elif request.method == "DELETE":
            self.charges[path.rsplit("/", 1)[1]]["status"] = "CANCELLED"
            status, content = 202, None
        elif request.method == "PATCH":
            self.agreement["status"] = "STOPPED"
            status, content = 204, None
        else:
            raise AssertionError("Unexpected provider request")
        self.effects.append(identity)
        self.keys[key] = identity, status, content
        if path == "/recurring/v3/agreements" and self.lose_create_response:
            raise httpx.ReadTimeout("fixture-secret-private lost response")
        return httpx.Response(status, json=content) if content else httpx.Response(status)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "revision", lambda: "a" * 40)
    merchant = Merchant()
    state = tmp_path / "state.json"

    def run(stage="checkout", action="execute", *extra, environment=ENV, opener=lambda _: False):
        args = runner.parser().parse_args([
            "--state", str(state), "--stage", stage, "--action", action, "--allow-mt",
            "--return-url", "https://talli.example/return", "--management-url", "https://talli.example/manage", *extra,
        ])
        return runner.run(args, environment, transport=httpx.MockTransport(merchant), now=lambda: NOW, open_browser=opener)

    return run, merchant, state


def approved(harness):
    run, merchant, _ = harness
    assert run()["observation"]["status"] == "pending"
    merchant.approve()
    assert run()["observation"]["status"] == "confirmed"


def test_default_preflight_is_value_free_offline_and_creates_no_state(tmp_path, capsys):
    state = tmp_path / "never-created.json"

    def forbidden(request):
        pytest.fail("Preflight must not request a token or contact MT")

    assert runner.main(["--state", str(state)], environment=ENV, transport=httpx.MockTransport(forbidden)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["configuration_valid"] and report["provider_calls"] == 0
    assert not state.exists() and not list(tmp_path.iterdir())
    assert runner.main([], environment={}) == 0
    missing = json.loads(capsys.readouterr().out)
    assert missing["missing_names"] == list(runner.ENV_NAMES)


@pytest.mark.parametrize("arguments,environment", [
    (["--action", "execute"], ENV),
    (["--action", "execute", "--allow-mt"], ENV | {"TALLI_VIPPS_MT_MERCHANT_SERIAL_NUMBER": "123456"}),
    (["--action", "execute", "--allow-mt"], ENV | {"TALLI_VIPPS_MT_CLIENT_SECRET": ""}),
    (["--action", "reconcile", "--allow-mt"], ENV),
])
def test_missing_authority_or_configuration_never_calls_provider(tmp_path, capsys, arguments, environment):
    def forbidden(request):
        pytest.fail("Rejected configuration must never reach transport")

    assert runner.main(arguments + ["--state", str(tmp_path / "state.json")], environment=environment,
                       transport=httpx.MockTransport(forbidden)) == 2
    output = capsys.readouterr()
    assert not output.out
    assert "private" not in output.err and "Traceback" not in output.err
    assert not (tmp_path / "state.json").exists()


def test_lost_response_and_concurrent_execute_reconcile_original_intent(harness):
    run, merchant, state = harness
    merchant.lose_create_response = True
    first = run()
    assert first["observation"]["status"] == "unknown"
    original = json.loads(state.read_text())["stages"]["checkout"]["intent"]
    with pytest.raises(runner.ConformanceError, match="ambiguous_mutation_cannot_be_repeated"):
        run(action="repeat-execute")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert all(result["action"] == "reconcile" for result in results)
    assert len(merchant.effects) == 1
    assert json.loads(state.read_text())["stages"]["checkout"]["intent"] == original
    merchant.approve()
    assert run(action="reconcile")["observation"]["status"] == "confirmed"


def test_two_simultaneous_initial_commands_create_one_agreement(harness):
    run, merchant, state = harness
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert {result["action"] for result in results} == {"execute", "reconcile"}
    assert len(merchant.effects) == 1
    assert len(json.loads(state.read_text())["stages"]["checkout"]["attempts"]) == 2


def test_all_stages_preserve_refund_amounts_and_provider_keys(harness):
    run, merchant, state = harness
    approved(harness)
    initial = next(iter(merchant.charges))
    assert run(action="repeat-execute")["observation"]["status"] == "pending"
    assert len(merchant.charges) == 1
    assert run()["observation"]["status"] == "confirmed"
    renewal = run("renewal", "execute", "--due-date", "2026-09-08")
    renewal_reference = renewal["observation"]["charge_reference"]
    merchant.capture(renewal_reference)
    assert run("renewal")["observation"]["status"] == "confirmed"
    assert run("partial-refund")["observation"]["refunded_minor"] == 37250
    before = len(merchant.effects)
    replay = run("partial-refund", "repeat-execute")
    assert replay["observation"]["refunded_minor"] == 37250 and len(merchant.effects) == before
    assert run("remaining-refund")["observation"]["refunded_minor"] == 149000
    assert run("full-refund")["observation"]["refunded_minor"] == 149000
    cancelable = run("cancel-renewal", "execute", "--due-date", "2026-09-09")
    cancel_reference = cancelable["observation"]["charge_reference"]
    assert cancel_reference != renewal_reference
    assert run("cancel-charge")["observation"]["status"] == "confirmed"
    stop = run("stop")
    assert stop["observation"]["status"] == "confirmed"
    assert merchant.charges[initial]["summary"]["refunded"] == 149000
    assert merchant.charges[renewal_reference]["summary"]["refunded"] == 149000
    assert merchant.charges[cancel_reference]["summary"]["captured"] == 0
    saved = json.loads(state.read_text())
    assert set(saved["stages"]) == set(runner.STAGES)
    assert len({stage["operation_key"] for stage in saved["stages"].values()}) == 8
    assert stop["limits"]["whole_issue_acceptance"] == "not-established"
    assert state.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("stage,extra", [
    ("partial-refund", ()), ("remaining-refund", ()), ("full-refund", ()),
    ("cancel-charge", ()), ("stop", ()),
    ("renewal", ("--due-date", "2026-09-07")), ("renewal", ()),
])
def test_unobserved_prerequisites_never_dispatch_new_mutation(harness, stage, extra):
    run, merchant, _ = harness
    run()
    calls = len(merchant.calls)
    with pytest.raises(runner.ConformanceError):
        run(stage, "execute", *extra)
    assert len(merchant.calls) == calls


def test_stop_cannot_silently_cancel_unresolved_renewal(harness):
    run, merchant, _ = harness
    approved(harness)
    run("renewal", "execute", "--due-date", "2026-09-08")
    calls = len(merchant.calls)
    with pytest.raises(runner.ConformanceError, match="stage_prerequisite_not_observed"):
        run("stop")
    assert len(merchant.calls) == calls


@pytest.mark.parametrize("scheduled", ["renewal", "cancel-renewal"])
@pytest.mark.parametrize("extra", [(), ("--due-date", "2026-09-07")])
def test_approved_checkout_still_requires_future_renewal_due_date(harness, scheduled, extra):
    run, merchant, _ = harness
    approved(harness)
    calls = len(merchant.calls)
    with pytest.raises(runner.ConformanceError, match="future_due_date_required"):
        run(scheduled, "execute", *extra)
    assert len(merchant.calls) == calls


@pytest.mark.parametrize("scheduled", ["renewal", "cancel-renewal"])
@pytest.mark.parametrize("terminal", ["FAILED", "CANCELLED"])
def test_stop_preserves_terminal_uncaptured_renewal_failure_without_refund(harness, scheduled, terminal):
    run, merchant, state = harness
    approved(harness)
    result = run(scheduled, "execute", "--due-date", "2026-09-08")
    reference = result["observation"]["charge_reference"]
    merchant.charges[reference]["status"] = terminal
    assert run(scheduled, "reconcile")["observation"]["status"] == "failed"
    before = json.loads(state.read_text())["stages"][scheduled]
    assert run("stop")["observation"]["status"] == "confirmed"
    assert json.loads(state.read_text())["stages"][scheduled] == before
    assert not any(effect[1].endswith("/refund") or effect[0] == "DELETE" for effect in merchant.effects)


def test_stop_can_clean_up_active_agreement_after_initial_charge_failed(harness):
    run, merchant, _ = harness
    run()
    merchant.agreement["status"] = "ACTIVE"
    merchant.charges[next(iter(merchant.charges))]["status"] = "FAILED"
    assert run(action="reconcile")["observation"]["status"] == "failed"
    assert run("stop")["observation"]["status"] == "confirmed"


def test_failed_renewal_with_captured_money_cannot_skip_refund_cleanup(harness):
    run, merchant, _ = harness
    approved(harness)
    result = run("renewal", "execute", "--due-date", "2026-09-08")
    reference = result["observation"]["charge_reference"]
    merchant.capture(reference)
    merchant.charges[reference]["status"] = "FAILED"
    assert run("renewal", "reconcile")["observation"]["status"] == "failed"
    calls = len(merchant.calls)
    with pytest.raises(runner.ConformanceError, match="stage_prerequisite_not_observed"):
        run("stop")
    assert len(merchant.calls) == calls


def test_changed_due_date_and_tampered_state_fail_before_network(harness):
    run, merchant, state = harness
    approved(harness)
    run("renewal", "execute", "--due-date", "2026-09-08")
    calls = len(merchant.calls)
    with pytest.raises(runner.ConformanceError, match="immutable_intent_conflict"):
        run("renewal", "execute", "--due-date", "2026-09-09")
    saved = json.loads(state.read_text())
    saved["stages"]["renewal"]["intent"]["operation_id"] = str(uuid4())
    state.write_text(json.dumps(saved))
    with pytest.raises(runner.ConformanceError, match="invalid_state"):
        run("renewal")
    assert len(merchant.calls) == calls


def test_interrupted_evidence_write_recovers_without_second_mutation(harness, monkeypatch):
    run, merchant, state = harness
    original = runner.save_state
    saves = []

    def lose_result(path, value):
        saves.append(True)
        if len(saves) == 2:
            raise OSError("fixture-secret-private")
        original(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(runner, "save_state", lose_result)
        with pytest.raises(OSError):
            run()
    attempt = json.loads(state.read_text())["stages"]["checkout"]["attempts"][0]
    assert "observation" not in attempt
    assert run()["action"] == "reconcile" and len(merchant.effects) == 1


def test_durable_marker_failure_precedes_any_provider_request(harness, monkeypatch):
    run, merchant, _ = harness

    def fail(path, state):
        raise OSError("fixture-secret-private")

    monkeypatch.setattr(runner, "save_state", fail)
    with pytest.raises(OSError):
        run()
    assert not merchant.calls


def test_confirmation_can_open_without_logging_or_saving_capability(harness):
    run, _, state = harness
    opened = []
    result = run("checkout", "execute", "--open-confirmation", opener=lambda url: opened.append(url) or True)
    assert result["confirmation_opened"] and "token=" in opened[0]
    evidence = state.read_text() + json.dumps(result)
    assert "private" not in evidence and "token=" not in evidence
    assert "client_secret" not in evidence and "subscription_key" not in evidence
