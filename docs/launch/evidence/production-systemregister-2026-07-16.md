# Production Systemregister verification — 2026-07-16

Status: verified and operations gate closed; production filing remains disabled

This record captures the one-time supplier-side production registration for
Talli's RF-1086 Systembruker boundary. It is not a customer delegation, filing
approval, production filing, or founder go-live signoff.

## Fixed authority definition

- System ID: `930835978_talli`
- Vendor: `0192:930835978` (ELMER WELFIS)
- Production Maskinporten client ID:
  `4a42d9fe-9759-4d4e-a07a-84ebc80a5a1b`
- Production public-key ID: `93fea8a9-4435-4fdc-84fc-775803714c53`
- Right: `ske-innrapportering-aksjonaerregisteroppgave`
- Visible in Altinn: `true`
- Access packages: none
- Redirect URLs: none
- Canonical request SHA-256:
  `2c414ae29ef5bd58e8349ce5e41d5619db1367d08b09b145c0e4c1a9f4572703`

The operation used exactly
`altinn:authentication/systemregister.write` against
`https://platform.altinn.no/authentication/api/v1/systemregister/vendor`.
It did not include Systembruker `authorization_details` and had no `PUT` path.

## Observed execution

The production runtime first performed an idempotent `GET`. The missing system
was created by `POST`, which returned HTTP 200 with the internal system UUID as
a JSON string. Talli's initial parser expected a JSON object, failed closed, and
recorded:

- `failed · authority_response_invalid`
- HTTP 200
- Started `2026-07-16 08:32:52` Europe/Oslo
- Completed `2026-07-16 08:32:53` Europe/Oslo

Altinn's official setup guide documents that the create endpoint returns a JSON
string UUID. The parser was corrected test-first to accept only a UUID-shaped
JSON string and to verify the full system through the documented `GET` response.
It also normalizes Altinn's documented `allowedRedirectUrls` casing and omitted
vendor authority while continuing to compare the vendor ID, names,
descriptions, right, client ID, access packages, redirect list, and visibility.

The subsequent idempotent operation performed `GET` only and recorded:

- `succeeded · already_verified`
- HTTP 200
- Started `2026-07-16 08:38:01` Europe/Oslo
- Completed `2026-07-16 08:38:02` Europe/Oslo
- Exact system, client, and RF-1086 right match

Relevant official documentation:

- https://docs.altinn.studio/en/api/authentication/systemuserapi/systemregister/create/
- https://docs.altinn.studio/en/api/authentication/systemuserapi/systemregister/get/
- https://docs.altinn.studio/en/altinn-studio/v8/guides/integration/sbs/setup/

## Security and audit boundary

- The operation required the founder's authenticated production session, an
  active admin-operator grant, and a fresh signed Supabase TOTP/AAL2 claim.
- The operator enrolled and re-verified TOTP; no QR code, shared secret,
  Maskinporten assertion, access token, private key, or raw Altinn response was
  persisted in evidence or rendered in the UI.
- The database audit stores only actor ID, fixed operation, request hash,
  allowlisted result code, HTTP status, fixed public metadata, and timestamps.
- The managed Vercel private key remained write-only throughout.
- The production operations gate was set back to `false` immediately after the
  successful verification. The deployed operator page showed **Deaktivert** and
  a disabled execution button while retaining the redacted audit rows.

## Deployments

- `dpl_FRPUgMm3YMSViBDXu7dNbrkCWyGX`: fresh-MFA flow and valid production RSA
  PEM boundary; the successful create response exposed the documented response
  mismatch and was recorded fail-closed.
- `dpl_EFTAscAtm4s5q3ynpJ8WeFt6Uda1`: corrected response handling; existing
  definition verified with HTTP 200 and `already_verified`.
- `dpl_F2mAq32FbJn9m2gSZXfzrw5TxvaL`: production operations gate disabled and
  verified disabled at `https://talli.no/operator`.

Earlier diagnostic deployments stayed inside the same fixed operation and did
not broaden endpoints, rights, or filing capability.

## Production scopes observed on the client

- `skatteetaten:innrapporteringaksjonaerregisteroppgave`
- `altinn:correspondence.read`
- `altinn:events.subscribe`
- `altinn:instances.read`
- `digdir:dialogporten`
- `altinn:authentication/systemregister.write`
- `altinn:authentication/systemuser.request.read`
- `altinn:authentication/systemuser.request.write`

`altinn:instances.write` is still missing from the production Digdir scope
picker despite the approval email. This remains a separate follow-up and was not
treated as present.

## Closed boundaries and cost

- `TALLI_AUTHORITY_OPS_ENABLED=false` after the one-time verification.
- `TALLI_RF1086_PRODUCTION_ENABLED` was not changed and remains false.
- No customer production Systembruker was created or approved.
- No Skatteetaten filing, Altinn instance creation, signing, submission, inbox,
  or archive endpoint was called.
- No paid plan, certificate, API, add-on, or service was purchased. Altinn and
  Maskinporten charged NOK 0. Vercel used the existing Free plan's included
  build/runtime quota; no upgrade or overage prompt appeared.

## Remaining gate

Before a production RF-1086 pilot, a named real customer must approve the
customer-side Systembruker, the delegated read-only pre-flight must succeed, the
exact owner/company/year entitlement must be recorded, and the owner/reviewer
signoffs and filing production switch must be handled under the controlled
production runbook. This evidence alone does not authorize a filing.
