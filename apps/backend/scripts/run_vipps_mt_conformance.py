"""Opt-in MT provider observations; never billing, source or worker authority."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import fields
from datetime import UTC, date, datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from uuid import UUID, uuid4, uuid5
import webbrowser
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from talli_backend.adapters.annual_billing_runtime import load_vipps_mt_configuration
from talli_backend.adapters.vipps_billing import VippsTestBillingProvider, vipps_operation_key
from talli_backend.modules.billing.public import (
    AnnualProviderIntent, AnnualProviderOperation, AnnualProviderStatus, BillingPaymentEventId,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear, Timestamp


EXPECTED_MSN = "535717"
ENV_NAMES = tuple("TALLI_VIPPS_MT_" + name for name in (
    "MERCHANT_SERIAL_NUMBER", "CLIENT_ID", "CLIENT_SECRET", "SUBSCRIPTION_KEY", "CONFIRMATION_ORIGINS",
))
STAGES = (
    "checkout", "renewal", "partial-refund", "remaining-refund", "full-refund",
    "cancel-renewal", "cancel-charge", "stop",
)
OPERATIONS = dict(zip(STAGES, (
    "checkout", "renewal", "refund", "refund", "refund", "renewal", "cancel_charge", "stop_agreement",
)))
LIMITS = {
    "evidence_scope": "provider-observations-only",
    "webhooks": "not-exercised", "billing_database": "not-exercised",
    "trusted_sources": "not-exercised", "automatic_workers": "not-exercised",
    "whole_issue_acceptance": "not-established",
}


class ConformanceError(Exception):
    """Only fixed, value-free diagnostic codes cross the command boundary."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ConformanceError("invalid_arguments")


def parser():
    result = Parser(description=__doc__)
    result.add_argument("--action", choices=("preflight", "execute", "reconcile", "repeat-execute"), default="preflight")
    result.add_argument("--allow-mt", action="store_true", help="Permit calls to the designated MT sales unit only.")
    result.add_argument("--state", type=Path, help="Private durable JSON state; keep it for every retry.")
    result.add_argument("--stage", choices=STAGES, default="checkout")
    result.add_argument("--return-url", help="HTTPS test return URL, without credentials, query or fragment.")
    result.add_argument("--management-url", help="HTTPS test subscription management URL.")
    result.add_argument("--due-date", help="YYYY-MM-DD, required when first scheduling either renewal stage.")
    result.add_argument("--open-confirmation", action="store_true", help="Open an allowlisted confirmation URL without logging or saving it.")
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def timestamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ConformanceError("invalid_state")
    return result


def intent_record(intent):
    result = {}
    for field in fields(intent):
        value = getattr(intent, field.name)
        if isinstance(value, Timestamp):
            value = value.value.isoformat()
        elif isinstance(value, IncomeYear):
            value = value.value
        elif isinstance(value, date):
            value = value.isoformat()
        elif isinstance(value, (CompanyId, BillingPaymentEventId)):
            value = str(value)
        result[field.name] = value
    return result


def read_intent(value):
    if set(value) != {field.name for field in fields(AnnualProviderIntent)}:
        raise ConformanceError("invalid_state")
    return AnnualProviderIntent(**(value | {
        "operation_id": BillingPaymentEventId(value["operation_id"]),
        "company_id": CompanyId(value["company_id"]),
        "income_year": IncomeYear(value["income_year"]),
        "operation": AnnualProviderOperation(value["operation"]),
        "created_at": Timestamp(timestamp(value["created_at"])),
        "due_date": date.fromisoformat(value["due_date"]) if value["due_date"] else None,
    }))


def test_url(value):
    target = urlsplit(value or "")
    if (target.scheme != "https" or not target.hostname or target.username or target.password
            or target.query or target.fragment or target.hostname == "api.vipps.no"):
        raise ConformanceError("invalid_test_url")
    return value


def latest(stage):
    return stage["attempts"][-1].get("observation") if stage["attempts"] else None


def require_observation(state, name, *, captured=None, refunded=None, statuses=("confirmed",)):
    stage = state["stages"].get(name)
    observation = latest(stage) if stage else None
    if (observation is None or observation["status"] not in statuses
            or (captured is not None and observation["captured_minor"] != captured)
            or (refunded is not None and observation["refunded_minor"] != refunded)):
        raise ConformanceError("stage_prerequisite_not_observed")
    return observation


def terminal_without_capture(state, stage):
    observation = latest(state["stages"][stage])
    return observation is not None and (
        observation["status"], observation["captured_minor"], observation["refunded_minor"]
    ) == ("failed", 0, 0)


def new_intent(state, stage, due, at):
    context = state["context"]
    operation_id = str(uuid5(UUID(context["run_id"]), stage))
    checkout_id = str(uuid5(UUID(context["run_id"]), "checkout"))
    agreement = None
    charge = "talli-mt-" + checkout_id
    renewal = stage in {"renewal", "cancel-renewal", "cancel-charge", "full-refund"}
    amount = {"checkout": 149000, "renewal": 149000, "cancel-renewal": 149000,
              "partial-refund": 37250, "remaining-refund": 111750, "full-refund": 149000,
              "cancel-charge": 0, "stop": 0}[stage]
    due_date = None
    if stage != "checkout":
        if stage == "stop" and "checkout" in state["stages"] and terminal_without_capture(state, "checkout"):
            original = latest(state["stages"]["checkout"])
        else:
            original = require_observation(state, "checkout", captured=149000)
        agreement = original["agreement_reference"]
        if "stop" in state["stages"]:
            raise ConformanceError("agreement_stop_already_started")
    if stage in {"renewal", "cancel-renewal"}:
        due_date = date.fromisoformat(due) if due else None
        if due_date is None or due_date < at.astimezone(ZoneInfo("Europe/Oslo")).date() + timedelta(days=1):
            raise ConformanceError("future_due_date_required")
        charge = "talli-mt-" + operation_id
    elif stage == "partial-refund":
        require_observation(state, "checkout", captured=149000, refunded=0)
    elif stage == "remaining-refund":
        require_observation(state, "partial-refund", captured=149000, refunded=37250)
    elif stage == "full-refund":
        require_observation(state, "renewal", captured=149000, refunded=0)
        charge = state["stages"]["renewal"]["intent"]["charge_reference"]
    elif stage == "cancel-charge":
        require_observation(state, "cancel-renewal", captured=0, refunded=0, statuses=("pending",))
        charge = state["stages"]["cancel-renewal"]["intent"]["charge_reference"]
    elif stage == "stop":
        # Do not make the stop fixture silently cancel either unresolved renewal.
        for scheduled, resolved in (("renewal", "full-refund"), ("cancel-renewal", "cancel-charge")):
            if scheduled in state["stages"] and not terminal_without_capture(state, scheduled):
                require_observation(state, resolved)
    return AnnualProviderIntent(
        operation_id=BillingPaymentEventId(operation_id), company_id=CompanyId(context["company_id"]),
        income_year=IncomeYear(context["income_year"]), operation=AnnualProviderOperation(OPERATIONS[stage]),
        amount_minor=amount, created_at=Timestamp(at),
        agreement_external_reference="talli-mt-" + context["run_id"], charge_reference=charge,
        return_url=context["return_url"], management_url=context["management_url"],
        agreement_reference=agreement, due_date=due_date, recurring_consent=True,
        original_charge_is_renewal=renewal,
    )


def load_state(path, configuration):
    if path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise ConformanceError("invalid_state")
    state = json.loads(path.read_text())
    if set(state) != {"schema_version", "context", "context_sha256", "stages"} or state["schema_version"] != 1:
        raise ConformanceError("invalid_state")
    context = state["context"]
    if (set(context) != {"run_id", "company_id", "income_year", "merchant_serial_number", "return_url", "management_url"}
            or context["merchant_serial_number"] != EXPECTED_MSN or digest(context) != state["context_sha256"]
            or context["company_id"] != str(uuid5(UUID(context["run_id"]), "synthetic-company"))
            or set(state["stages"]) - set(STAGES)):
        raise ConformanceError("invalid_state")
    test_url(context["return_url"])
    test_url(context["management_url"])
    for name, stage in state["stages"].items():
        if set(stage) != {"intent", "intent_sha256", "operation_key", "attempts"}:
            raise ConformanceError("invalid_state")
        intent = read_intent(stage["intent"])
        if (digest(stage["intent"]) != stage["intent_sha256"]
                or stage["operation_key"] != vipps_operation_key(configuration, intent)
                or str(intent.operation_id) != str(uuid5(UUID(context["run_id"]), name))
                or intent.operation.value != OPERATIONS[name]
                or str(intent.company_id) != context["company_id"]
                or intent.return_url != context["return_url"] or intent.management_url != context["management_url"]
                or intent.agreement_external_reference != "talli-mt-" + context["run_id"]
                or not isinstance(stage["attempts"], list) or not stage["attempts"]):
            raise ConformanceError("invalid_state")
    return state


def save_state(path, state):
    descriptor, temporary = tempfile.mkstemp(prefix=".vipps-mt-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(state, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def observation_record(value, intent):
    if (value.provider != "vipps-mt" or value.operation != intent.operation
            or value.amount_minor != intent.amount_minor or value.charge_reference != intent.charge_reference
            or (value.agreement_reference is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value.agreement_reference))
            or not 0 <= value.refunded_minor <= value.captured_minor <= intent.original_charge_minor):
        raise ConformanceError("invalid_provider_observation")
    return {
        "status": value.status.value, "agreement_reference": value.agreement_reference,
        "charge_reference": value.charge_reference, "amount_minor": value.amount_minor,
        "captured_minor": value.captured_minor, "refunded_minor": value.refunded_minor,
        "captured_at": value.captured_at.value.isoformat() if value.captured_at else None,
        "confirmation_available": value.checkout_url is not None,
    }


def revision():
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                            capture_output=True, text=True, check=False)
    if not re.fullmatch(r"[a-f0-9]{40}\n?", result.stdout):
        return "unknown"
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root,
                            capture_output=True, text=True, check=False)
    return result.stdout.strip() + ("-dirty" if status.returncode or status.stdout else "")


def run(args, environment, *, transport=None, now=None, open_browser=webbrowser.open):
    clock = now or (lambda: datetime.now(UTC))
    missing = [name for name in ENV_NAMES if not environment.get(name)]
    if args.action == "preflight":
        configured = False
        if not missing:
            try:
                configured = load_vipps_mt_configuration(environment).merchant_serial_number == EXPECTED_MSN
            except Exception:
                pass
        return {"action": "offline-preflight", "provider_calls": 0, "expected_msn": EXPECTED_MSN,
                "configuration_valid": configured, "missing_names": missing, "limits": LIMITS}
    if not args.allow_mt:
        raise ConformanceError("explicit_mt_opt_in_required")
    if args.state is None:
        raise ConformanceError("durable_state_required")
    configuration = load_vipps_mt_configuration(environment)
    if configuration.merchant_serial_number != EXPECTED_MSN:
        raise ConformanceError("designated_test_sales_unit_required")
    provider = VippsTestBillingProvider(configuration, transport=transport, now=clock)
    path = args.state.expanduser().absolute()
    with locked(path):
        if path.exists():
            state = load_state(path, configuration)
            for supplied, key in ((args.return_url, "return_url"), (args.management_url, "management_url")):
                if supplied is not None and supplied != state["context"][key]:
                    raise ConformanceError("immutable_run_context_conflict")
        else:
            if args.action != "execute" or args.stage != "checkout":
                raise ConformanceError("checkout_must_start_run")
            run_id = uuid4()
            context = {"run_id": str(run_id), "company_id": str(uuid5(run_id, "synthetic-company")),
                       "income_year": clock().year, "merchant_serial_number": EXPECTED_MSN,
                       "return_url": test_url(args.return_url), "management_url": test_url(args.management_url)}
            state = {"schema_version": 1, "context": context, "context_sha256": digest(context), "stages": {}}
        stage = state["stages"].get(args.stage)
        action = args.action
        if stage is None:
            if action != "execute":
                raise ConformanceError("stage_not_started")
            intent = new_intent(state, args.stage, args.due_date, clock())
            record = intent_record(intent)
            stage = {"intent": record, "intent_sha256": digest(record),
                     "operation_key": vipps_operation_key(configuration, intent), "attempts": []}
            state["stages"][args.stage] = stage
        else:
            intent = read_intent(stage["intent"])
            if args.due_date is not None and args.due_date != stage["intent"]["due_date"]:
                raise ConformanceError("immutable_intent_conflict")
            if action == "execute":
                action = "reconcile"
            if action == "repeat-execute":
                previous = stage["attempts"][-1].get("observation")
                if previous is None or previous["status"] not in {"pending", "confirmed"}:
                    raise ConformanceError("ambiguous_mutation_cannot_be_repeated")
        attempt = {"action": action, "started_at": clock().isoformat(), "source_revision": revision()}
        stage["attempts"].append(attempt)
        # This durable marker precedes every network call, including token acquisition.
        # A crash or lost response makes the next ordinary execute reconcile only.
        save_state(path, state)
        operation = provider.reconcile if action == "reconcile" else provider.execute
        observation = asyncio.run(operation(intent))
        attempt["observation"] = observation_record(observation, intent)
        attempt["finished_at"] = clock().isoformat()
        save_state(path, state)
        opened = False
        if args.open_confirmation and observation.checkout_url:
            opened = bool(open_browser(observation.checkout_url))
        return {"action": action, "stage": args.stage, "run_id": state["context"]["run_id"],
                "merchant_serial_number": EXPECTED_MSN, "source_revision": attempt["source_revision"],
                "intent_sha256": stage["intent_sha256"], "operation_key": stage["operation_key"],
                "attempt_count": len(stage["attempts"]), "observation": attempt["observation"],
                "confirmation_opened": opened, "limits": LIMITS}


def main(argv=None, *, environment=None, transport=None, now=None, open_browser=webbrowser.open):
    try:
        args = parser().parse_args(argv)
        report = run(args, os.environ if environment is None else environment,
                     transport=transport, now=now, open_browser=open_browser)
        print(json.dumps(report, sort_keys=True))
        return 0
    except ConformanceError as error:
        print(json.dumps({"error": error.args[0], "limits": LIMITS}), file=sys.stderr)
    except Exception:
        # Configuration, filesystem and provider diagnostics may contain secrets.
        print(json.dumps({"error": "conformance_unavailable", "limits": LIMITS}), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
