"""DB-free regression for the browser's actual provider/discovery/reconciliation path."""

import asyncio
import json
import os
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "apps/backend/src"), str(ROOT / "apps/backend/tests")]
from talli_backend.adapters.maskinporten import MaskinportenClient, MaskinportenConfiguration
from talli_backend.modules.shareholder_register_filing.public import (
    Rf1086ReconciliationInput,
    reconcile_journaled_rf1086_production,
)
from test_postgres_shareholder_register_filing import session, VALID
from test_shareholder_register_filing_production import FeedbackJournal

launcher = os.environ.get("TALLI_FIXTURE_LAUNCHER", "start_authority_connections_backend.py")
assert launcher in (
    "start_authority_connections_backend.py",
    "start_shareholder_register_filing_backend.py",
)
fixture = runpy.run_path(str(ROOT / "tests/fixtures" / launcher))
origin = fixture["loopback_url"](os.environ["TALLI_LOCAL_AUTHORITY_MOCK_BASE_URL"], ("http",))
sys.addaudithook(fixture["guard_socket"])


async def main():
    async def forward(request):
        target = fixture["provider_mock_url"](str(request.url), origin, request.method)
        async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
            response = await client.request(
                request.method, target, content=request.content,
                headers={key: value for key, value in request.headers.items() if key.lower() != "host"},
            )
            return httpx.Response(response.status_code, headers=response.headers, content=response.content)

    transport = httpx.MockTransport(forward)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ).decode()
    environment = VALID | {"TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM": key}
    store = session(environment)
    store._maskinporten = MaskinportenClient(
        MaskinportenConfiguration.production(environment), transport=transport,
    )
    store._rf_transport = transport
    org = os.environ["TALLI_FIXTURE_ORG"]
    submission = os.environ["TALLI_FIXTURE_SUBMISSION"]
    dialog = os.environ["TALLI_FIXTURE_DIALOG"]
    binding = await store.bind_read_only_authority(
        SimpleNamespace(org_number=org), SimpleNamespace(external_ref="A" * 43),
    )
    journal = FeedbackJournal("processing")
    try:
        result = await reconcile_journaled_rf1086_production(
            journal, binding.authority,
            Rf1086ReconciliationInput(
                "local-submission", "local-company", 2025, submission,
                "<submitted-main/>", {"holder": "<submitted-under/>"}, org, dialog,
            ),
            discovery=binding.feedback_discovery, initial_poll=False,
        )
        assert result.state == "accepted", result.state
        assert len(journal.events) == 1 and journal.events[0].state == "accepted"
        assert len(journal.artifacts) == 2
        print(json.dumps({"state": result.state, "artifacts": len(journal.artifacts)}))
    finally:
        binding.discard()


asyncio.run(main())
