"""An intentional migration predecessor cannot claim its future APIs are ready."""
import asyncio
from pathlib import Path
import runpy

import pytest
from fastapi.testclient import TestClient

from talli_backend import main
from talli_backend.adapters import dependency_readiness
from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsError
from talli_backend.modules.company_tax_filing.public import CompanyTaxError


ROOT = Path(__file__).resolve().parents[3]
predecessor_application = runpy.run_path(
    str(ROOT / "tests/fixtures/start_rf1086_predecessor_backend.py")
)["predecessor_application"]
FUTURE_ROLES = {"company_tax_filing_workflow_executor", "annual_accounts_filing_workflow_executor"}
DATABASE_SETTINGS = ("TALLI_LEDGER_DATABASE_URL", "TALLI_COMPANY_ACCESS_DATABASE_URL",
                     "TALLI_BANKING_DATABASE_URL", "TALLI_MARKETING_MEASUREMENT_DATABASE_URL")


def configure_precontract_probes(monkeypatch, *, failed=None):
    calls = []
    for setting in DATABASE_SETTINGS:
        monkeypatch.setenv(setting, setting)
    monkeypatch.setenv("TALLI_ANNUAL_BILLING_MODE", "off")

    async def database(dsn, roles):
        calls.append((dsn, roles))
        # The real aggregate's early workspace/onboarding phase deliberately
        # precedes the two executor binding contract migrations.
        return dsn != failed and not FUTURE_ROLES.intersection(roles)

    async def auth(origin, key):
        calls.append(("auth", ()))
        return failed != "auth"

    monkeypatch.setattr(dependency_readiness, "probe_database", database)
    monkeypatch.setattr(dependency_readiness, "probe_auth", auth)
    return calls


def test_predecessor_composition_checks_its_real_dependencies_without_future_contracts(monkeypatch):
    calls = configure_precontract_probes(monkeypatch)
    with TestClient(main.create_app()) as client:
        assert client.get("/health/ready").status_code == 503
    assert FUTURE_ROLES <= {role for _, roles in calls for role in roles}
    calls.clear()
    with TestClient(predecessor_application()) as client:
        assert client.get("/health/ready").json() == {"status": "ready"}
    assert {dsn for dsn, _ in calls} == {*DATABASE_SETTINGS, "auth"}
    assert not FUTURE_ROLES.intersection(role for _, roles in calls for role in roles)


@pytest.mark.parametrize("failed", [*DATABASE_SETTINGS, "auth"])
def test_predecessor_never_bypasses_a_required_probe(monkeypatch, failed):
    configure_precontract_probes(monkeypatch, failed=failed)
    with TestClient(predecessor_application()) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready"}
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/health/live").status_code == 200


def test_predecessor_future_adapters_cannot_use_unavailable_contracts(monkeypatch):
    selected = {}
    monkeypatch.setattr(main, "create_app", lambda **kwargs: selected.update(kwargs))
    predecessor_application()
    assert set(selected) == {"company_tax_session_factory", "annual_accounts_session_factory"}
    for name, error in (("company_tax_session_factory", CompanyTaxError),
                        ("annual_accounts_session_factory", AnnualAccountsError)):
        with pytest.raises(error):
            asyncio.run(selected[name].session("unused-fixture-token"))
