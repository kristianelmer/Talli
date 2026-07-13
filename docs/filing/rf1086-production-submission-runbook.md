# RF-1086 Production Submission Runbook

Status: production blocked until human review and official validation
Last updated: 2026-07-13
Target filing: `aksjonærregisteroppgaven` / RF-1086

This runbook defines the path from local RF-1086 simulation to live submission. It is not permission to enable production filing. Live filing remains disabled until authority access, test-environment evidence, RF-1086 code decisions, billing, security, and human review gates are complete.

## Official Anchors

- Skatteetaten RF-1086 API docs: https://skatteetaten.github.io/api-dokumentasjon/api/innrapportering-aksjonaerregisteroppgave
- Published OpenAPI 1.0.0: https://api.swaggerhub.com/apis/skatteetaten/innrapportering-aksjonaerregister-api/1.0.0/swagger.json
- Skatteetaten RF-1086 page: https://www.skatteetaten.no/skjema/rf-1086-aksjonarregisteroppgaven/
- Skatteetaten end-user-system transition note: https://www.skatteetaten.no/bedrift-og-organisasjon/rapportering-og-bransjer/aksjonarregisteroppgaven/
- Skatteetaten setup guidance for re-established services: https://www.skatteetaten.no/samarbeidspartnere/reetablering-altinn/systemleverandor/oppkobling/
- Altinn system-user guide: https://docs.altinn.studio/en/authorization/guides/resource-owner/system-user/
- Dialogporten authentication: https://docs.altinn.studio/en/dialogporten/user-guides/authenticating/
- Dialogporten dialog details: https://docs.altinn.studio/en/dialogporten/user-guides/getting-dialog-details/
- RF-1086 phase 0 map: [aksjonaerregisteroppgaven-phase-0-map.md](./aksjonaerregisteroppgaven-phase-0-map.md)
- RF-1086 authority contract evidence: [rf1086-authority-api-contract.md](./rf1086-authority-api-contract.md)

## Required Authority Access

Before production filing can be enabled:

- Talli must be registered as a relevant end-user-system/system supplier where required.
- Talli must have Maskinporten client setup for the correct organization.
- Talli must have access to scope `skatteetaten:innrapporteringaksjonaerregisteroppgave`.
- Altinn/system-user flow must be tested for a supported company and delegated right/access package.
- Test submissions must use synthetic/test data where required by Skatteetaten/Altinn/Digdir guidance.
- Production credentials must be separated from local/dev credentials and explicitly enabled only after security sign-off.

## Submission Flow

The local integration seam in `holding_core.rf1086_submission` models the production path:

1. Build RF-1086 readiness from the deterministic case model.
2. Block if readiness has hard errors.
3. Block if billing/subscription/filing-package gate is not satisfied.
4. Block if required RF-1086 transaction code decisions still have `production_blocker=True`.
5. In production mode, require fresh MFA, human security review, and explicit production credentials gate.
6. Require owner authority confirmation and final preview confirmation.
7. Prepare API calls for:
   - `POST /{inntektsaar}/1086H` hovedskjema.
   - `POST /{inntektsaar}/{hovedskjemaid}/1086U` per underskjema.
   - `POST /{inntektsaar}/{hovedskjemaid}/bekreft?antall_underskjema={count}`.
   - `GET /{inntektsaar}/forsendelser/{forsendelseid}/dokumenter?page=0&size=50`.
   - Dialogporten `GET /api/v1/enduser/dialogs/{dialogid}` to discover
     authorized API attachments for the confirmed party and resource.
   - `GET /{inntektsaar}/forsendelser/{forsendelseid}/dokumenter/{dokumentid}`
     for each allowlisted provider artifact discovered from a URL that exactly
     matches the fixed authority host and confirmed shipment.
8. Store content-addressed submitted XML, immutable provider artifacts, and a
   separate manifest for each Dialogporten revision.

## Idempotency Policy

Skatteetaten requires an `idempotencyKey` UUID on the hovedskjema and underskjema XML POST operations. Repeated POSTs with the same body/key reuse the first response. Talli policy:

- Store endpoint, body hash, and idempotency key for each logical authority call.
- Reuse the same key only for the same endpoint and same body hash.
- Generate a new key if the endpoint or body changes.
- Never retry a changed body under an old key.
- Never create duplicate logical submissions for the same confirmed preview.
- Do not add an idempotency header to `bekreft` unless a later published contract requires it.

This is covered by `holding_core.submission.register_api_call` and RF-1086 submission tests.

The exact authority HTTP boundary is implemented in
`app/lib/rf1086-authority-client.ts` and covered by
`npm run test:rf1086:authority`. Crash-safe one-call orchestration is implemented
in `app/lib/rf1086-authority-orchestration.ts` and covered by
`npm run test:rf1086:orchestration`. It requires prepared, sent, and accepted
journal revisions and blocks replay of an uncertain `bekreft`. A reviewed
Supabase production journal adapter with service-role-only atomic writes is now
implemented and tested on a disposable real stack. Hosted migration deployment
and production worker/web wiring remain required before activation. The local TT02-only operator boundary is implemented by
`app/lib/maskinporten-system-user.ts`, `app/lib/rf1086-file-journal.ts`,
`app/lib/rf1086-tt02-runner.ts`, and `scripts/rf1086-tt02.ts`; see
`rf1086-tt02-submission-runbook.md`. TT02 feedback/receipt evidence is still
pending.

The Dialogporten/read-archive boundary is implemented in
`app/lib/dialogporten-client.ts` and
`app/lib/rf1086-authority-archive.ts`. It is covered by
`npm run test:rf1086:archive`. Production persistence and web wiring remain
disabled.

## Failure Handling

Retryable failures:

- Authentication/token expiry.
- Temporary authority outage.
- Network timeout before final authority state is known.

Blocked failures:

- Missing authorization.
- Readiness mismatch.
- Underskjema count mismatch.
- Unverified RF-1086 code values.
- Missing authority confirmation or final preview confirmation.
- Production security gate missing.

Every failure must preserve the submission state and be visible to the user/operator without silently resubmitting.

## Current RF-1086 Production Scope

As of 2026-06-16:

- `N` for stiftelse has evidence status `verified`; it is observed in Skatteetaten public API example and has no local RF-1086 code-value blocker.
- `K` for kjøp is excluded from live filing scope until official code-list evidence or Skatteetaten test-environment acceptance is recorded.
- `S` for salg is excluded from live filing scope until official code-list evidence or Skatteetaten test-environment acceptance is recorded.
- `U` for utbytte is excluded from live filing scope until official code-list evidence or Skatteetaten test-environment acceptance is recorded.

The public examples identify labels and reporting positions, but the public XSDs do not prove these exact code values. To avoid guessed production filing, Talli's RF-1086 live scope is limited to stiftelse/no-activity cases. Share-sale and dividend cases can still be simulated and exported, but production submission returns `RF1086_EVENT_UNSUPPORTED`.

User-facing blocker text must explain that production submission is unavailable for purchase/sale/dividend events until official RF-1086 code evidence or test-environment acceptance is recorded.

## Human Review Before Live Filing

Production credentials/live filing may be enabled only after a named reviewer signs off:

- Authority access and system-user flow tested.
- RF-1086 unsupported events remain excluded from live filing unless official code evidence is recorded.
- Test-environment submission and feedback retrieval completed with evidence.
- Security baseline and restore test completed.
- Launch claims reviewed.
- Support/refund policy confirmed.

Until then, Talli may generate previews, XML, validation reports, and simulated submission state only.
