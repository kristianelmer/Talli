# RF-1086 Authority API Contract Evidence

Status: authority client, durable journal, and guarded server-only worker implemented; hosted/live activation remains disabled
Verified: 2026-07-13
OpenAPI contract: `innrapportering-aksjonaerregister-api` `1.0.0`

This record pins Talli's RF-1086 authority boundary to the current published
Skatteetaten contract. It is implementation evidence, not permission to perform
a live filing.

## Primary Sources

- Skatteetaten service documentation:
  https://skatteetaten.github.io/api-dokumentasjon/api/innrapportering-aksjonaerregisteroppgave
- Published SwaggerHub registry entry:
  https://api.swaggerhub.com/apis/skatteetaten/innrapportering-aksjonaerregister-api/
- Published OpenAPI `1.0.0` JSON:
  https://api.swaggerhub.com/apis/skatteetaten/innrapportering-aksjonaerregister-api/1.0.0/swagger.json
- Altinn system-user token guide:
  https://docs.altinn.studio/en/authorization/guides/system-vendor/system-user/usetoken/
- Digdir Maskinporten token endpoint:
  https://docs.digdir.no/docs/Maskinporten/maskinporten_protocol_token.html
- Digdir system-user RAR contract:
  https://docs.digdir.no/docs/Maskinporten/maskinporten_func_systembruker.html
- Dialogporten authentication:
  https://docs.altinn.studio/en/dialogporten/user-guides/authenticating/
- Dialogporten dialog details:
  https://docs.altinn.studio/en/dialogporten/user-guides/getting-dialog-details/
- Dialogporten OpenAPI environments:
  https://docs.altinn.studio/en/dialogporten/reference/openapi/
- Supabase Row Level Security:
  https://supabase.com/docs/guides/database/postgres/row-level-security
- Supabase database functions and function privileges:
  https://supabase.com/docs/guides/database/functions
- Supabase Data API hardening and explicit grants:
  https://supabase.com/docs/guides/api/securing-your-api

The SwaggerHub registry reported `1.0.0` as the default, published version. The
OpenAPI document identifies itself as OpenAPI `3.0.3` and API version `1.0.0`.

## Fixed Environments

| Environment | Base URL |
| --- | --- |
| TT02/external test | `https://api-test.sits.no/api/aksjonaerregister/v1` |
| Production | `https://api.skatteetaten.no/api/aksjonaerregister/v1` |

The runtime client accepts only the symbolic environments `test` and
`production`; it does not accept a caller-controlled base URL. This prevents an
authority bearer token from being redirected to an arbitrary host.

## Authentication and Authorization

- Maskinporten scope:
  `skatteetaten:innrapporteringaksjonaerregisteroppgave`
- Altinn resource for a standard system user:
  `ske-innrapportering-aksjonaerregisteroppgave`
- Dialog and attachment discovery additionally requires
  `digdir:dialogporten` on a system-user-bound Maskinporten token.
- Authority API calls use the short-lived system-user Maskinporten token as a
  Bearer token.
- Token acquisition, signing-key access, and token refresh are intentionally not
  part of the web-facing API client. Tokens are injected in memory and are not
  logged or returned in errors.
- The worker accepts only the symbolic Maskinporten environment and therefore
  fixes production grants and token exchange to `https://maskinporten.no/`.
  It requests only the RF-1086 scope for the authority step.

## Operations

| Operation | Contract |
| --- | --- |
| Submit hovedskjema | `POST /{inntektsaar}/1086H`; XML body; `Accept: application/json`; `Content-Type: application/xml`; UUID `idempotencyKey` header |
| Submit underskjema | `POST /{inntektsaar}/{hovedskjemareferanse}/1086U`; XML body; the same content headers; a new UUID `idempotencyKey` for each logical underskjema call |
| Confirm submission | `POST /{inntektsaar}/{hovedskjemareferanse}/bekreft?antall_underskjema={count}` |
| List documents | `GET /{inntektsaar}/forsendelser/{forsendelseid}/dokumenter?page={page}&size={size}`; page is zero-based and size is `1..50` |
| Get one document | `GET /{inntektsaar}/forsendelser/{forsendelseId}/dokumenter/{dokumentId}`; accepted formats are JSON, XML, PDF, and CSV |

The list operation's `dokumenter` array contains the submitted XML documents;
it is not a list of feedback document ids. The confirmation response's
`dialogId` is resolved through Dialogporten
`GET /api/v1/enduser/dialogs/{dialogId}`. Authorized API attachment URLs in
that dialog identify provider documents. Talli validates those URLs against the
fixed Skatteetaten origin, year, and confirmed `forsendelseId`, extracts only
the UUID, and invokes the fixed provider client instead of following the URL.

The previous local preparation seam incorrectly appended a shareholder ID after
`1086U`, omitted the `antall_underskjema` query, and used the hovedskjema path for
document retrieval. Commit `5b4445f` corrects those paths and locks them with
tests.

The published OpenAPI requires `idempotencyKey` on the two XML POST operations.
Skatteetaten's service page says a repeated POST with the same body and UUID
returns the first response. Talli therefore permits a UUID retry only for the
identical URL and body and rejects reuse for a different logical call. The
published `bekreft` operation does not define an idempotency header.

## Validated Responses

- Hovedskjema must return HTTP 200 JSON with UUID `hovedskjemaId`.
- Underskjema must return HTTP 200; the contract defines no response body.
- Bekreft must return the leveranse reference plus UUID `dialogId` and
  `forsendelseId` before Talli can treat the authority submission as confirmed.
- Document-page responses must contain bounded integer pagination values and no
  more than 50 string documents.
- A single document must match the requested allowlisted content type.

Non-200 responses are mapped to a bounded error code, status, retryability, and
optional correlation ID. Provider messages are not exposed because they can
contain submitted data or accidentally echo credentials. Responses are streamed
under a size cap, requests have a bounded timeout, redirects are rejected, and
malformed JSON/UUID/content types fail closed.

## Executable Evidence

- Client: `app/lib/rf1086-authority-client.ts`
- Contract/security tests: `tests/rf1086_authority_client.test.mjs`
- Crash-safe orchestration: `app/lib/rf1086-authority-orchestration.ts`
- Orchestration tests: `tests/rf1086_authority_orchestration.test.mjs`
- Durable Supabase journal: `app/lib/rf1086-supabase-journal.ts`
- Journal migration:
  `supabase/migrations/20260713192808_persist_rf1086_authority_checkpoints.sql`
- Journal tests: `tests/rf1086_supabase_journal.test.mjs` and the disposable
  local Supabase workspace rehearsal
- Fresh production-state loader: `app/lib/rf1086-production-state.ts`
- Guarded production runner/service: `app/lib/rf1086-production-runner.ts` and
  `app/lib/rf1086-production-service.ts`
- Short-lived production lease: `app/lib/rf1086-production-lease.ts`
- Lease migration and gate-source triggers:
  `supabase/migrations/20260713201500_guard_rf1086_production_lease.sql`
- Production release tests: `tests/rf1086_production_runner.test.mjs` and
  `tests/rf1086_production_state.test.mjs`, plus
  `tests/rf1086_production_lease.test.mjs`
- Command: `npm run test:rf1086:authority`
- Command: `npm run test:rf1086:orchestration`
- Dialog/immutable archive:
  `app/lib/dialogporten-client.ts` and
  `app/lib/rf1086-authority-archive.ts`
- Command: `npm run test:rf1086:archive`
- Launch rehearsal includes the authority-client contract tests.

The tests prove exact test/production URLs, headers, operation paths, strict
response parsing, bounded responses, no bearer-token disclosure, invalid-input
rejection before transport, safe UUID retries, write-before-send journal order,
crash recovery, environment/payload locking, and persisted-checkpoint tamper
rejection. A durable `sent` state prevents automatic `bekreft` replay when its
outcome could be unknown. The database journal enforces exact bounded JSON,
payload/preview binding on every read, service-role-only atomic mutation,
optimistic revisions with immediate HTTP 409 conflicts, accepted-membership RLS,
and no browser-role insert, update, or delete grant. The isolated real-stack test
also proves outsider denial, the owner/control/journal client split, and that a
fresh hard review comment and blocking override disable release even when an
older readiness snapshot remains ready. The production-service tests prove
pre-token and pre-transport audit ordering, a second fresh release-state load
after token issuance, exact RF scope selection, one provider call per
invocation, and bearer-token absence from results, audits, and checkpoints. A
service-only 120-second lease now spans token issuance through the one provider
operation. Its migration-tested triggers seal every release-gate source,
concurrent acquisition returns a conflict, successful and failed operations
attempt release, and automatic expiry limits the effect of a crashed worker.

Archive tests additionally prove exact Dialogporten hosts, strict party and
resource binding, bounded/token-free responses, consistent provider pagination,
cross-host/cross-shipment URL rejection before retrieval, private atomic files,
immutable document identities, and revisioned manifests.

## Remaining Before First TT02 Provider Write

1. Record explicit acceptance of the synthetic assumption: one synthetic
   shareholder owns all 500 shares and there are no 2025 transactions.
2. Run one guarded TT02 step. The current offline inspection is clean and reports
   `nextOperation: hovedskjema`; no provider write or journal checkpoint exists.
3. Inspect after every call and progress only through the remaining XML steps.
   When the journal reports `bekreft`, obtain a separate explicit confirmation.
4. With separate permission-change approval, attach `digdir:dialogporten` to the
   test client, verify it can be issued on the system-user token, and record the
   provider-observed feedback timing.
5. Retrieve feedback/receipt artifacts through the revisioned archive, store
   immutable references and hashes, and record an accepted
   `authority_test_run`.
6. Separately apply the reviewed journal migration to a confirmed hosted staging
   project before exercising the server-only production worker. Keep every web
   route and the production filing release gate disabled until filing, security,
   restore, billing, and named-reviewer gates pass.
