# Production Systemregister Operations Design

Status: approved design
Date: 2026-07-16
Scope: production Maskinporten verification and RF-1086 Systemregister registration

## Context

Altinn granted ELMER WELFIS the required Systembruker and inbox scopes in test and
production. Seven of those scopes are now attached to the existing production
Maskinporten client `4a42d9fe-9759-4d4e-a07a-84ebc80a5a1b`.
`altinn:instances.write` is granted according to the Altinn service-desk email but
is not yet visible in Digdir's production scope picker.

The production Maskinporten private key is a Vercel Sensitive Environment Variable.
Vercel intentionally makes sensitive values write-only, so the key cannot be pulled
back for a local token or Systemregister operation. The operation must execute inside
Talli's production runtime without weakening that credential boundary.

## Decision

Add a narrowly scoped, founder-only authority-operations surface to Talli's existing
operator area. It will execute fixed production operations inside Vercel, record a
redacted audit trail, and never return or persist a Maskinporten assertion, access
token, or private key.

The first supported operation is `register_rf1086_system`. It verifies the
`altinn:authentication/systemregister.write` token, then creates or verifies the
production Systemregister definition for Talli's RF-1086 flow.

## Alternatives considered

### Rotate to a locally held production key

This would make local scripts easy to run, but it creates another persistent
credential and unnecessarily replaces a working key. Rejected because it weakens the
existing managed-secret boundary.

### Deploy and remove a disposable one-off endpoint

This keeps the key in Vercel but requires two deployments, has weaker auditability,
and creates a greater chance that an unreviewed endpoint is left behind. Rejected in
favor of a reusable but disabled-by-default operations surface.

## Trust boundaries and threats

- The browser session is untrusted until Supabase validates it server-side.
- A normal owner or support operator must not execute authority operations.
- A stolen but non-MFA session must not execute an authority operation.
- Request input must not select arbitrary scopes, endpoints, system IDs, rights, or
  redirect URLs.
- Altinn and Maskinporten responses are untrusted external input and must be bounded,
  parsed defensively, and reduced to safe result codes.
- Logs, HTTP responses, database rows, and exceptions must not contain assertions,
  access tokens, private keys, or raw authority response bodies.
- Repeated requests must be idempotent and must not silently overwrite an existing
  Systemregister definition.

## Operator authorization

The operation is available only when all of these conditions hold:

1. `TALLI_AUTHORITY_OPS_ENABLED` is the exact string `true`; missing, empty, or any
   other value fails closed.
2. Supabase validates the signed-in user.
3. `support_operators` contains an active `admin` grant for that user.
4. The signed session proves AAL2 with a fresh MFA authentication time, using the same
   trusted-claims boundary as other sensitive Talli actions.
5. The submitted form contains the exact operation name and an exact human
   confirmation phrase displayed by the operator UI.

The operation is exposed as an operator-only server action from `/operator`. This
keeps it same-origin, benefits from the framework's server-action CSRF protections,
and avoids a general public JSON API.

## Fixed production definition

No field in the Systemregister payload comes from browser input. The server builds the
definition from constants plus the configured production client ID:

- system ID: `930835978_talli`
- vendor ID: `0192:930835978`
- localized name: `Talli`
- localized descriptions: the existing RF-1086 own-system descriptions used in TT02
- right: `ske-innrapportering-aksjonaerregisteroppgave`
- access packages: none
- client ID: the configured production Maskinporten client ID
- allowed redirect URLs: none for the initial operation
- visibility: `true`

This is a standard own-system model. It is not an agent/client-system registration.

## Execution flow

1. Create an `authority_operations` row with status `started`, the actor ID, a stable
   operation name, and a SHA-256 hash of the canonical fixed payload.
2. Load the production client ID, key ID, and private PEM from Vercel environment
   variables. Reject missing, malformed, test, or TT02-looking values.
3. Mint a production Maskinporten token for exactly
   `altinn:authentication/systemregister.write`, without Systembruker
   `authorization_details`.
4. `GET https://platform.altinn.no/authentication/api/v1/systemregister/vendor/930835978_talli`.
5. If the response is 404, `POST` the fixed definition to
   `https://platform.altinn.no/authentication/api/v1/systemregister/vendor`.
6. If the response is 200, canonicalize and compare the security-relevant fields.
   Return `already_verified` only when they match exactly.
7. If an existing definition differs, stop with `definition_conflict`. Never issue an
   automatic `PUT`, because Altinn's PUT replaces the complete definition.
8. Update the audit row to `succeeded`, `failed`, or `conflict`, recording only the
   HTTP status and an allowlisted result code.

Network calls use HTTPS-only constant endpoints, no redirects, a 15-second timeout,
and bounded response parsing.

## Audit model

Add a global `authority_operations` table because company-scoped `audit_events`
cannot accurately represent a supplier-level system registration.

Stored fields:

- operation ID
- operation name from a database check constraint
- actor user ID
- status (`started`, `succeeded`, `failed`, `conflict`)
- request hash
- allowlisted result code
- authority HTTP status, when available
- redacted metadata limited to system ID, client ID, and right identifier
- created and completed timestamps

RLS permits active admin operators to read rows. Browser roles cannot insert or update
rows directly; only the server-side service-role client records operation state.

## UI and error handling

The operator page shows:

- whether authority operations are enabled;
- the immutable target system ID, production client ID suffix, and RF-1086 right;
- the required confirmation phrase;
- a submit button available only to active admin operators; and
- recent redacted operation results.

User-facing failures use safe codes such as `authority_ops_disabled`,
`operator_mfa_required`, `maskinporten_scope_rejected`, `definition_conflict`, and
`authority_unavailable`. Raw upstream bodies and stack traces are never rendered.

## Verification

Tests must be written before implementation and cover:

- the exact fixed definition and canonical request hash;
- rejection of missing, malformed, or test credentials;
- rejection when the feature flag, admin grant, AAL2 freshness, operation name, or
  confirmation phrase is absent;
- token construction without Systembruker authorization details;
- 404 then POST creation;
- 200 exact-match verification without POST or PUT;
- mismatched existing definition returning `definition_conflict` without PUT;
- redaction of access tokens, assertions, private keys, and raw upstream bodies;
- migration grants and RLS; and
- the operator UI remaining hidden from non-admin operators.

Before deployment, run targeted tests, full typecheck/build, security tests, and a
secret scan. After deployment, temporarily enable the operation, execute it once,
verify the redacted audit result, then disable the operation again. A read-only GET
must confirm the registered production definition.

## Cost boundary

No paid integration, certificate, or provider plan is required for this operation.
Deployment and execution use the project's current Vercel free plan and consume only
included build/runtime quota. If Vercel presents an upgrade, overage, paid add-on, or
other charge, stop and obtain explicit founder approval before continuing.

## Out of scope

- enabling `TALLI_RF1086_PRODUCTION_ENABLED`;
- creating a customer production Systembruker request;
- granting a production-pilot entitlement;
- sending an RF-1086 filing;
- attaching `altinn:instances.write` before Digdir exposes it in the picker; and
- registering Skattemelding or annual-accounts rights.
