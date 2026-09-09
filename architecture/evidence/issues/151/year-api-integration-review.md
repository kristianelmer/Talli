# Year API integration review

Read-only independent review of the mutable follow-up to fixed base `3e8bf518`, on 2026-09-09. Scope: root's main routes, generator/generated transport, Ledger authenticated session/application/adapter by-year method, and the RF application archive delegation. I authored the RF public/preparation contract and earlier archive adaptation; those are excluded from independent certification. I also drafted the new RF persistence method, so its implementation is excluded. C's web verification and B's actual database proof are separate. No suites, database, provider or hosted operations were run in this review.

## Error-path finding — closed after narrow correction

`main.py:10052` builds `Rf1086SimulationWire` from retained nested JSON. A legal persisted `receipt_metadata = '{}'::jsonb` reaches this path and raises Pydantic `ValidationError` (required receipt fields are missing). The application/public immutable row does not claim that nested historical JSON is valid; this transport boundary performs that check. `shareholder_register_filing_call:4259–4279` does not map output validation errors. The resulting outer `unexpected_error_handler:4506–4514` emits `_problem_response:3737–3742`, whose only header is X-Request-ID. `RequestIdMiddleware:3711–3716` cannot add Cache-Control after `call_next` raises. Installed Starlette's `applications.py:80–100` puts ServerErrorMiddleware outside this user middleware, confirming that the fallback response bypasses the no-store assignment.

The new archive-source failure therefore returns a sanitized 500 without the required no-store policy. Map only this output validation to RF unavailable (503) inside the normal handled-error path, or set no-store on the bounded error response. Keep malformed selected-year evidence rejected; do not add a permissive JSON fallback. Add an actual HTTP case with malformed selected-year nested JSON and `raise_server_exceptions=False`, checking sanitized error plus no-store.

## Corrective review

The root correction catches only Pydantic `ValidationError` around construction of the new archive-source wire result and raises `ShareholderRegisterFilingError.unavailable()` without retaining the validation contents. This reaches the existing handled 503 mapping and returns through RequestIdMiddleware, preserving `Cache-Control: no-store` and the request ID. Existing route behavior and public nested payload validation are unchanged; malformed selected-year data still fails closed.

The new actual HTTP regression uses `raise_server_exceptions=False` with retained receipt JSON containing a synthetic private field. It asserts 503, no-store, original request ID and absence of both the field name and value. The red run in `/tmp/talli-151-archive-no-store-red.log` reproduced the prior 500. Root's combined RF/Ledger API run then completed with 130 passed in 24.50 seconds, recorded in `/tmp/talli-151-year-archive-api-green.log`; I inspected that final result without rerunning it. The finding is closed with source and actual HTTP regression evidence, and no further scoped finding.

## Reviewed without further findings

- Both new GET routes require valid company UUID and year 2000–2100 before opening a session. Actor identity comes from the verified session, never query parameters. RF application `archive_source` rechecks actor and calls only the public preparation factory. Reads add no new MFA, entitlement or readiness policy.
- Ledger adapter `list_opening_snapshots_for_year` passes company, exact year, bound subject, no cursor and limit1 directly to the five-argument database composition before row decoding. It retains the original four-argument all-year list. The actual composition forwards the year to both RF and Ledger owned source reads before joining/validation.
- Zero or one opening item is retained. Adapter and API reject other company/year, pagination and extra rows. Existing OpeningSnapshotPage validates cursor consistency, holder identity/scope/count, and share/bank money invariants. `_money` uses Decimal/string and `_money_wire` preserves exact monetary strings, including the focused fixture above 2^53.
- Both generated clients use the required scope, existing bearer/request options, runtime schema guards and `cache: no-store`. Existing nested simulation serializers retain their prior timestamp handling; no new payload conversion is introduced.
- Direct JSON comparison found all 134 preexisting OpenAPI paths and all existing schemas unchanged; only by-year opening and RF archive-source paths were added. Result: `/tmp/talli-151-year-api-contract-comparison.json`.

Reviewed focused test source includes by-year actor-before-database, wrong-scope/empty/paginated responses and exact money, plus archive company/year/missing-auth/cross-scope/duplicate response cases. Those source cases support intent; root owns execution results and this review does not attest them. Full database/browser/gates remain separate.

## Corrected source hashes

```json
{
  "apps/backend/src/talli_backend/main.py": "bb0c29e13ba4a27482a0def1b34ff1676567b260e361b9e65bdd274e19d2486c",
  "apps/backend/tests/test_shareholder_register_filing_api.py": "bee366f5da6a8d450c8cd753fc9c289ec8707a603a38579c7b7fa3cbd6f398f2",
  "apps/backend/src/talli_backend/application/ledger_session.py": "b0779d288f7a9801172cdca0644f35598f76445f8407bb0f133d0ba78312ca45",
  "apps/backend/src/talli_backend/application/ledger_workflow.py": "959c58a9937eaf47192d2cbc0bcdd43ced236d54557b8756f7c3592472ce1117",
  "apps/backend/src/talli_backend/application/shareholder_register_filing_workflow.py": "9319817c3408089e5e01badfbb6d98f9a325b0b3c128a6bf06628c45f9516077",
  "apps/backend/src/talli_backend/adapters/supabase_ledger.py": "9b38c9d5cd5e5bd8730d30b0e3140d31aa6cff16e36ccdb7f429ac689e24d9fa",
  "scripts/generate-api-client.mjs": "22db2155e7e9c7ea6752708ac79747bc29a929389285897768aa92fabf9a5e7f",
  "packages/talli-api-client/src/generated/client.ts": "ee70c653d820b07771a61bfae5d3063fa9efbd94f8abe566a5f6253f7f4555d5",
  "contracts/openapi/talli-v1.json": "2cfca140bee4fcf3d88c33c8d6527e16a18f7ca3e851b20a1b115194949cdbd9",
  "apps/web/features/ledger/transport.ts": "eef2e2062c8b8977b09045f7219120801b3c4cbaa2e27b8b6480085e039b5ef8"
}
```
