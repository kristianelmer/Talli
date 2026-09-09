"""Offline preflight, or one explicitly requested MT checkout observation pass."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from talli_backend.adapters import annual_billing_runtime as runtime
from talli_backend.modules.billing.public import AnnualCheckoutObservationOutcome


PASS_TIMEOUT_SECONDS = 45
REQUIRED_SETTINGS = (
    "TALLI_ANNUAL_CHECKOUT_RECONCILIATION_DATABASE_URL",
    "TALLI_VIPPS_MT_MERCHANT_SERIAL_NUMBER",
    "TALLI_VIPPS_MT_CLIENT_ID",
    "TALLI_VIPPS_MT_CLIENT_SECRET",
    "TALLI_VIPPS_MT_SUBSCRIPTION_KEY",
    "TALLI_VIPPS_MT_CONFIRMATION_ORIGINS",
)


class CommandError(Exception):
    """Fixed command diagnostics; never include configuration/provider values."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CommandError("invalid_arguments")


def preflight(environment):
    enabled = environment.get("TALLI_ANNUAL_CHECKOUT_RECONCILIATION_MODE", "off") != "off"
    report = {
        "action": "offline-preflight", "configuration_valid": True, "enabled": False,
        "database_calls": 0, "provider_calls": 0,
        "missing_names": [name for name in REQUIRED_SETTINGS if not environment.get(name)] if enabled else [],
    }
    try:
        configuration = runtime.AnnualCheckoutReconciliationConfiguration.from_environment(environment)
        report["enabled"] = configuration is not None
    except runtime.AnnualBillingRuntimeConfigurationError:
        report["configuration_valid"] = False
    return report


async def run_once(operations):
    async with asyncio.timeout(PASS_TIMEOUT_SECONDS):
        outcome = await operations.run_once()
    if not isinstance(outcome, AnnualCheckoutObservationOutcome):
        raise CommandError("invalid_worker_outcome")
    return {"action": "run-once", "outcome": outcome.value}


def main(argv=None, *, environment=None):
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("--run-once", action="store_true", help="Run one configured MT reconciliation pass, then exit.")
        args = parser.parse_args(argv)
        values = os.environ if environment is None else environment
        if not args.run_once:
            report = preflight(values)
        else:
            operations = runtime.compose_annual_checkout_reconciliation(values)
            if operations is None:
                raise CommandError("checkout_reconciliation_disabled")
            report = asyncio.run(run_once(operations))
        print(json.dumps(report, sort_keys=True))
        return 0
    except CommandError as error:
        code = error.args[0]
    except runtime.AnnualBillingRuntimeConfigurationError:
        code = "checkout_reconciliation_configuration_invalid"
    except Exception:
        # Database, timeout and provider errors may contain tenant/payment data
        # or credentials; do not print their messages, contexts or tracebacks.
        code = "checkout_reconciliation_unavailable"
    print(json.dumps({"error": code}), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
