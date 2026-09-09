"""Real FastAPI/Supabase fixture with the shipped provider adapters sent to local mock HTTP.

This launcher is test-only. It refuses non-loopback databases, Supabase, and mock
addresses, and its process-wide socket guard denies all external connections.
Global production flags remain disabled. The explicitly injected RF fixture
permits historical recovery through the two fixed GETs and denies send effects.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import uvicorn


def loopback_url(value: str, schemes: tuple[str, ...]) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in schemes or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("authority_browser_fixture_requires_loopback")
    return value


def provider_mock_url(original: str, mock_origin: str, method: str = "GET") -> str:
    mock = urlsplit(loopback_url(mock_origin, ("http",)))
    if mock.username or mock.password or mock.path not in ("", "/") or mock.query or mock.fragment:
        raise ValueError("authority_browser_fixture_mock_origin_invalid")
    provider = urlsplit(original)
    if provider.username or provider.password or provider.fragment:
        raise ValueError("authority_browser_fixture_blocked_provider_request")
    if provider.scheme == "https" and provider.netloc == "maskinporten.no" and provider.path == "/token" and not provider.query:
        path = "/maskinporten/token"
    elif (provider.scheme == "https" and provider.netloc == "platform.altinn.no"
          and provider.path.startswith("/authentication/api/v1/systemuser/")):
        path = "/altinn" + provider.path + ("?" + provider.query if provider.query else "")
    elif (provider.scheme == "https" and provider.netloc == "api.skatteetaten.no" and method == "GET"
          and re.fullmatch(r"/api/aksjonaerregister/v1/[0-9]{4}/forsendelser/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/dokumenter(?:/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})?", provider.path)
          and (provider.query == "page=0&size=50" if provider.path.endswith("/dokumenter") else not provider.query)):
        path = "/skatte" + provider.path.removeprefix("/api/aksjonaerregister/v1") + ("?" + provider.query if provider.query else "")
    else:
        raise ValueError("authority_browser_fixture_blocked_provider_request")
    return mock_origin.rstrip("/") + path


def guard_socket(event: str, arguments: tuple[object, ...]) -> None:
    if event == "socket.getaddrinfo":
        if arguments[0] not in ("localhost", "127.0.0.1", "::1", None):
            raise PermissionError("authority_browser_fixture_blocked_external_dns")
    if event == "socket.connect":
        address = arguments[1]
        if not isinstance(address, tuple) or not ipaddress.ip_address(address[0]).is_loopback:
            raise PermissionError("authority_browser_fixture_blocked_external_connection")


def main() -> None:
    for key in ("DATABASE_URL", "TALLI_LEDGER_DATABASE_URL", "TALLI_COMPANY_ACCESS_DATABASE_URL"):
        loopback_url(os.environ[key], ("postgres", "postgresql"))
    loopback_url(os.environ["SUPABASE_URL"], ("http",))
    mock_origin = loopback_url(os.environ["TALLI_LOCAL_AUTHORITY_MOCK_BASE_URL"], ("http",))
    if os.environ.get("TALLI_AUTHORITY_OPS_ENABLED") == "true" or os.environ.get("TALLI_RF1086_PRODUCTION_ENABLED") == "true":
        raise SystemExit("authority_browser_fixture_production_activation_forbidden")
    nonce = os.environ["TALLI_READINESS_NONCE"]
    if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", nonce):
        raise SystemExit("invalid readiness nonce")
    sys.addaudithook(guard_socket)
    repository_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repository_root / "apps" / "backend" / "src"))
    from talli_backend.adapters.altinn_system_user import AltinnSystemUserAdapter
    from talli_backend.adapters.maskinporten import MaskinportenClient, MaskinportenConfiguration
    from talli_backend.main import create_app

    async def mock_transport(request: httpx.Request) -> httpx.Response:
        target = provider_mock_url(str(request.url), mock_origin, request.method)
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = await client.request(request.method, target, content=request.content,
                headers={key: value for key, value in request.headers.items() if key.lower() != "host"})
            return httpx.Response(response.status_code, headers=response.headers, content=response.content)

    transport = httpx.MockTransport(mock_transport)
    maskinporten = MaskinportenClient(MaskinportenConfiguration.production(os.environ), transport=transport)
    from talli_backend.adapters.brreg_company_registry import BrregCompanyRegistryAdapter
    from talli_backend.adapters.postgres_legacy_rf1086_authority import PostgresLegacyRf1086AuthorityAdapter
    from talli_backend.adapters.supabase_billing import SupabaseBillingAdapter
    from talli_backend.adapters.supabase_company_access import SupabaseCompanyAccessAdapter
    from talli_backend.adapters.supabase_documents import SupabaseDocumentsAdapter
    from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration
    from talli_backend.adapters.simulation_billing import SimulationBillingProvider
    from talli_backend.application.billing_workflow import BillingWorkflow
    from talli_backend.compatibility.rf1086_authority_workflow import LegacyRf1086Error
    from talli_backend.modules.company_access.public import CompanyAccessService
    billing = SupabaseBillingAdapter.from_environment()
    documents = SupabaseDocumentsAdapter.from_environment()
    async def billing_queries(access_token):
        return BillingWorkflow(await billing.session(access_token), SimulationBillingProvider())
    class RecoveryOnlyFactory:
        async def session(self, access_token):
            session = await rf.session(access_token)
            async def deny_mutation(*args, **kwargs):
                raise LegacyRf1086Error("send_unavailable")
            session.bind_mutation_authority = deny_mutation
            session.begin_production_filing = deny_mutation
            return session
    rf = PostgresLegacyRf1086AuthorityAdapter(
        LedgerSupabaseConfiguration(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"], os.environ["TALLI_LEDGER_DATABASE_URL"]),
        billing_queries_factory=billing_queries, documents_session_factory=documents,
        company_access_service=CompanyAccessService(SupabaseCompanyAccessAdapter.from_environment(), BrregCompanyRegistryAdapter.from_environment()),
        environment=dict(os.environ) | {"TALLI_RF1086_PRODUCTION_ENABLED": "true", "TALLI_PROD_RF1086_SCOPE": "skatteetaten:innrapporteringaksjonaerregisteroppgave"},
        maskinporten=maskinporten, rf_transport=transport,
    )
    application = create_app(legacy_rf1086_session_factory=RecoveryOnlyFactory(), documents_session_factory=documents,
        system_user_authority_provider=AltinnSystemUserAdapter(
        maskinporten, environment="production", transport=transport,
    ))

    @application.middleware("http")
    async def observed_transport(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(("/api/v1/authority-connections/", "/api/v1/legacy-rf1086/")):
            print(f"TALLI_AUTHORITY_HTTP:{request.method}:{request.url.path}:{response.status_code}", flush=True)
        return response

    port = int(os.environ["TALLI_BACKEND_PORT"])
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(2048)
    print(f"TALLI_BACKEND_BOUND:{nonce}", flush=True)
    configuration = uvicorn.Config(application, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    asyncio.run(uvicorn.Server(configuration).serve(sockets=[listener]))


if __name__ == "__main__":
    main()
