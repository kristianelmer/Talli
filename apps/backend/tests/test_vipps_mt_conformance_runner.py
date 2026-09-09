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
        self.other_agreements = []
        self.charges = {}
        self.keys = {}
        self.lose_create_response = False
        self.lose_refund_response = False
        self.rate_limit = False

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
            if self.rate_limit:
                return httpx.Response(429)
            return httpx.Response(200, json={"access_token": "fixture-access-token-private"})
        assert request.headers["Authorization"] == "Bearer fixture-access-token-private"
        path = request.url.path
        if request.method == "GET":
            if path == "/recurring/v3/agreements":
                agreements = ([self.agreement] if self.agreement else []) + self.other_agreements
                rows = [row for row in agreements if row["status"] == request.url.params["status"]]
                return httpx.Response(200, json=rows)
            if "/charges/" in path:
                return httpx.Response(200, json=self.charges[path.rsplit("/", 1)[1]])
            return httpx.Response(200, json=self.agreement)
        key = request.headers["Idempotency-Key"]
        body = json.loads(request.content) if request.content else None
        identity = request.method, path, body
        # Real MT agreement creation did not deduplicate an exact same-key replay.
        if key in self.keys and path != "/recurring/v3/agreements":
            saved, status, content = self.keys[key]
            assert identity == saved, "Provider key must bind the exact immutable request"
            return httpx.Response(status, json=content) if content else httpx.Response(status)
        if path == "/recurring/v3/agreements":
            if self.agreement is not None:
                self.other_agreements.append(self.agreement)
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
        if path.endswith("/refund") and self.lose_refund_response:
            raise httpx.ReadTimeout("fixture-secret-private lost refund response")
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
    with pytest.raises(runner.ConformanceError, match="checkout_mutation_cannot_be_repeated"):
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


@pytest.mark.parametrize("confirmed", [False, True])
def test_checkout_raw_replay_is_rejected_before_state_or_network(harness, confirmed):
    run, merchant, state = harness
    if confirmed:
        approved(harness)
    else:
        run()
    before, calls = state.read_text(), len(merchant.calls)
    with pytest.raises(runner.ConformanceError, match="checkout_mutation_cannot_be_repeated"):
        run(action="repeat-execute")
    assert state.read_text() == before and len(merchant.calls) == calls
    assert run()["action"] == "reconcile" and len(merchant.effects) == 1


def test_original_checkout_agreement_survives_unknown_and_rate_limit_with_duplicate_search_matches(harness):
    run, merchant, state = harness
    approved(harness)
    original_agreement = merchant.agreement["id"]
    merchant.other_agreements.append(merchant.agreement | {"id": "agr_duplicate", "status": "PENDING"})
    saved = json.loads(state.read_text())
    checkout = saved["stages"]["checkout"]
    immutable = checkout["intent"], checkout["intent_sha256"], checkout["operation_key"]
    checkout["attempts"].append(checkout["attempts"][-1] | {
        "observation": checkout["attempts"][-1]["observation"] | {
            "status": "unknown", "agreement_reference": None, "captured_minor": 0,
        },
    })
    state.write_text(json.dumps(saved))
    merchant.rate_limit = True
    limited = run()
    assert limited["observation"]["status"] == "unknown"
    assert limited["observation"]["agreement_reference"] == original_agreement
    merchant.rate_limit = False
    calls = len(merchant.calls)
    recovered = run()
    assert recovered["observation"]["status"] == "confirmed"
    assert recovered["observation"]["agreement_reference"] == original_agreement
    assert all(request.url.path != "/recurring/v3/agreements" for request in merchant.calls[calls:])
    assert len(merchant.effects) == 1
    checkout = json.loads(state.read_text())["stages"]["checkout"]
    assert (checkout["intent"], checkout["intent_sha256"], checkout["operation_key"]) == immutable
    assert checkout["intent"]["agreement_reference"] is None


def test_conflicting_checkout_agreement_evidence_is_rejected_without_selecting_a_match(harness):
    run, merchant, state = harness
    approved(harness)
    saved = json.loads(state.read_text())
    saved["stages"]["checkout"]["attempts"][-1]["observation"]["agreement_reference"] = "agr_conflicting"
    state.write_text(json.dumps(saved))
    before, calls = state.read_text(), len(merchant.calls)
    for stage in ("checkout", "partial-refund", "initial-full-refund"):
        with pytest.raises(runner.ConformanceError, match="conflicting_checkout_agreement_references"):
            run(stage)
    assert state.read_text() == before and len(merchant.calls) == calls


def test_unbound_checkout_with_multiple_search_matches_stays_unknown(harness):
    run, merchant, _ = harness
    merchant.lose_create_response = True
    assert run()["observation"]["agreement_reference"] is None
    merchant.other_agreements.append(merchant.agreement | {"id": "agr_duplicate"})
    result = run()
    assert result["action"] == "reconcile"
    assert result["observation"]["status"] == "unknown"
    assert result["observation"]["agreement_reference"] is None
    assert len(merchant.effects) == 1


def test_all_stages_preserve_refund_amounts_and_provider_keys(harness):
    run, merchant, state = harness
    approved(harness)
    initial = next(iter(merchant.charges))
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
    assert set(saved["stages"]) == set(runner.STAGES) - {"initial-full-refund"}
    assert len({stage["operation_key"] for stage in saved["stages"].values()}) == 8
    assert stop["limits"]["whole_issue_acceptance"] == "not-established"
    assert state.stat().st_mode & 0o777 == 0o600


def test_initial_full_refund_is_one_original_charge_refund_and_preserves_recurring_scenario(harness):
    run, merchant, state = harness
    approved(harness)
    initial = next(iter(merchant.charges))
    result = run("initial-full-refund")
    assert result["observation"]["status"] == "confirmed"
    assert result["observation"]["captured_minor"] == result["observation"]["refunded_minor"] == 149000
    saved = json.loads(state.read_text())
    intent = saved["stages"]["initial-full-refund"]["intent"]
    assert intent["charge_reference"] == initial == saved["stages"]["checkout"]["intent"]["charge_reference"]
    assert intent["amount_minor"] == intent["original_charge_minor"] == 149000
    assert intent["original_charge_is_renewal"] is False and intent["due_date"] is None
    effects = list(merchant.effects)
    assert effects[-1][1].endswith(f"/{initial}/refund") and effects[-1][2]["amount"] == 149000
    # Refreshing the checkout after its refund must not invalidate the saved refund intent.
    assert run("checkout")["observation"]["refunded_minor"] == 149000
    for action in ("execute", "reconcile", "repeat-execute"):
        repeat = run("initial-full-refund", action)
        assert repeat["action"] == ("reconcile" if action == "execute" else action)
        assert repeat["operation_key"] == result["operation_key"]
        assert repeat["observation"]["refunded_minor"] == 149000
        assert merchant.effects == effects
    calls = len(merchant.calls)
    with pytest.raises(runner.ConformanceError, match="stage_prerequisite_not_observed"):
        run("full-refund")
    assert len(merchant.calls) == calls
    recurring = run("renewal", "execute", "--due-date", "2026-09-08")["observation"]["charge_reference"]
    merchant.capture(recurring)
    run("renewal", "reconcile")
    assert run("full-refund")["observation"]["refunded_minor"] == 149000
    saved = json.loads(state.read_text())
    assert saved["schema_version"] == 1
    assert saved["stages"]["full-refund"]["intent"]["charge_reference"] == recurring != initial
    assert saved["stages"]["full-refund"]["intent"]["original_charge_is_renewal"] is True


@pytest.mark.parametrize("chosen,blocked", [
    ("initial-full-refund", "partial-refund"), ("initial-full-refund", "remaining-refund"),
    ("partial-refund", "initial-full-refund"), ("remaining-refund", "initial-full-refund"),
])
@pytest.mark.parametrize("outcome", ["confirmed", "unknown", "interrupted"])
def test_initial_refund_path_is_reserved_even_without_a_confirmed_result(harness, chosen, blocked, outcome):
    run, merchant, state = harness
    approved(harness)
    if chosen == "remaining-refund":
        run("partial-refund")
    run(chosen)
    saved = json.loads(state.read_text())
    attempt = saved["stages"][chosen]["attempts"][-1]
    if outcome == "interrupted":
        del attempt["observation"]
        del attempt["finished_at"]
    else:
        attempt["observation"]["status"] = outcome
    state.write_text(json.dumps(saved))
    before, calls = state.read_text(), len(merchant.calls)
    for action in ("execute", "reconcile", "repeat-execute"):
        with pytest.raises(runner.ConformanceError, match="initial_refund_path_conflict"):
            run(blocked, action)
    assert len(merchant.calls) == calls and state.read_text() == before


def test_lost_initial_full_refund_response_reconciles_without_replaying(harness):
    run, merchant, _ = harness
    approved(harness)
    merchant.lose_refund_response = True
    result = run("initial-full-refund")
    assert result["observation"]["status"] == "unknown"
    calls, effects = len(merchant.calls), list(merchant.effects)
    with pytest.raises(runner.ConformanceError, match="ambiguous_mutation_cannot_be_repeated"):
        run("initial-full-refund", "repeat-execute")
    with pytest.raises(runner.ConformanceError, match="initial_refund_path_conflict"):
        run("partial-refund")
    assert len(merchant.calls) == calls
    recovered = run("initial-full-refund")
    assert recovered["action"] == "reconcile" and recovered["observation"]["status"] == "confirmed"
    assert recovered["operation_key"] == result["operation_key"] and merchant.effects == effects


def test_interrupted_initial_full_refund_result_keeps_path_reserved(harness, monkeypatch):
    run, merchant, state = harness
    approved(harness)
    save, saves = runner.save_state, []

    def lose_result(path, value):
        saves.append(True)
        if len(saves) == 2:
            raise OSError("fixture lost result write")
        save(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(runner, "save_state", lose_result)
        with pytest.raises(OSError):
            run("initial-full-refund")
    attempt = json.loads(state.read_text())["stages"]["initial-full-refund"]["attempts"][-1]
    assert "observation" not in attempt
    calls, effects = len(merchant.calls), list(merchant.effects)
    with pytest.raises(runner.ConformanceError, match="initial_refund_path_conflict"):
        run("remaining-refund")
    with pytest.raises(runner.ConformanceError, match="ambiguous_mutation_cannot_be_repeated"):
        run("initial-full-refund", "repeat-execute")
    assert len(merchant.calls) == calls
    assert run("initial-full-refund")["observation"]["status"] == "confirmed"
    assert merchant.effects == effects


def test_pending_initial_full_refund_cannot_be_blindly_repeated(harness):
    run, merchant, state = harness
    approved(harness)
    run("initial-full-refund")
    saved = json.loads(state.read_text())
    saved["stages"]["initial-full-refund"]["attempts"][-1]["observation"]["status"] = "pending"
    state.write_text(json.dumps(saved))
    calls, effects = len(merchant.calls), list(merchant.effects)
    with pytest.raises(runner.ConformanceError, match="ambiguous_mutation_cannot_be_repeated"):
        run("initial-full-refund", "repeat-execute")
    assert len(merchant.calls) == calls
    assert run("initial-full-refund")["action"] == "reconcile" and merchant.effects == effects


@pytest.mark.parametrize("field,value", [
    ("captured_minor", 148999), ("refunded_minor", 1), ("amount_minor", 148999),
    ("charge_reference", "another-initial-charge"),
])
def test_initial_full_refund_requires_exact_original_capture(harness, field, value):
    run, merchant, state = harness
    approved(harness)
    saved = json.loads(state.read_text())
    saved["stages"]["checkout"]["attempts"][-1]["observation"][field] = value
    state.write_text(json.dumps(saved))
    calls = len(merchant.calls)
    with pytest.raises(runner.ConformanceError):
        run("initial-full-refund")
    assert len(merchant.calls) == calls


@pytest.mark.parametrize("field,value", [
    ("charge_reference", "another-initial-charge"), ("original_charge_is_renewal", True),
    ("amount_minor", 37250), ("original_charge_minor", 298000),
])
def test_saved_initial_full_refund_must_preserve_its_original_charge_intent(harness, field, value):
    run, merchant, state = harness
    approved(harness)
    run("initial-full-refund")
    saved = json.loads(state.read_text())
    stage = saved["stages"]["initial-full-refund"]
    stage["intent"][field] = value
    stage["intent_sha256"] = runner.digest(stage["intent"])
    stage["operation_key"] = runner.vipps_operation_key(
        runner.load_vipps_mt_configuration(ENV), runner.read_intent(stage["intent"]))
    state.write_text(json.dumps(saved))
    calls = len(merchant.calls)
    with pytest.raises(runner.ConformanceError, match="invalid_initial_charge"):
        run("initial-full-refund")
    assert len(merchant.calls) == calls


@pytest.mark.parametrize("stage,extra", [
    ("partial-refund", ()), ("remaining-refund", ()), ("full-refund", ()), ("initial-full-refund", ()),
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
