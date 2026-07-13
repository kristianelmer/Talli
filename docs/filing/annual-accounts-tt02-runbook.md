# Annual Accounts TT02 Boundary Runbook

Status: local renderer, guarded orchestration, and private journal implemented;
live TT02 mutation is not yet authorized
Last updated: 2026-07-13
Target app: `brg/aarsregnskap-vanlig-202406`

This runbook covers Talli's test-only Altinn boundary for a simple holding AS.
It does not authorize creating a TT02 instance, changing Maskinporten scopes,
registering a new system right, or sending production annual accounts.

## Official Contract

- Brønnøysund's annual-accounts integration guide:
  https://brreg.github.io/docs/apidokumentasjon/regnskapsregisteret/maskinell-innrapportering/hvordan-sende-inn/
- Brønnøysund's official Postman examples:
  https://brreg.github.io/docs/apidokumentasjon/regnskapsregisteret/maskinell-innrapportering/eksempler-paa-registrering/API-eksempler-Postman.zip
- Digdir's system-user setup guide:
  https://docs.altinn.studio/nb/altinn-studio/v8/guides/integration/sbs/setup/
- Digdir's App API integration guide:
  https://docs.altinn.studio/nb/altinn-studio/v8/guides/integration/sbs/apis/
- Altinn validation API:
  https://docs.altinn.studio/en/api/apps/validation/

Pinned TT02 endpoints:

- Token exchange:
  `GET https://platform.tt02.altinn.no/authentication/api/v1/exchange/maskinporten`
- App base:
  `https://brg.apps.tt02.altinn.no/brg/aarsregnskap-vanlig-202406`

Required Maskinporten scopes:

- `altinn:instances.read`
- `altinn:instances.write`

Required Altinn system-register resource:

- `app_brg_aarsregnskap`

## Implemented Safety Boundary

`app/lib/annual-accounts-altinn-client.ts` is deliberately TT02-only:

- it has no production environment or base-URL option;
- it rejects attempted endpoint overrides;
- it exchanges the system-user Maskinporten token for an Altinn token once per
  client session;
- it refuses redirects, bounds streamed responses, and never includes provider
  bodies or bearer tokens in errors;
- it can create a draft, replace XML data elements, validate the stored draft,
  and lock a validated draft with `{"action":"confirm"}`;
- changing XML invalidates the local validation state;
- a draft cannot be locked unless its current local revision has passed
  validation;
- a successful lock must enter an Altinn `signing` task; and
- it exposes no `sign` or `submit` operation.

`app/lib/annual-accounts-orchestration.ts` and
`app/lib/annual-accounts-file-journal.ts` add the recovery boundary:

- every operation is persisted as `prepared` and then `sent` before transport;
- the checkpoint locks the operation, customer, year, and both XML hashes;
- draft and lock calls are never replayed automatically when their outcome is
  uncertain;
- fixed-data-ID XML replacements and validation reads may retry from the same
  stored identity;
- locking performs a fresh validation in the same client session immediately
  before the transition;
- checkpoint files are atomically replaced under a private `0700` directory,
  use `0600` files, reject symlinks, and enforce optimistic revisions; and
- the exact checkpoint schema permits only hashes, instance/data IDs, bounded
  validation codes, and process state. Tokens, assertions, XML, provider field
  paths, and provider values are rejected.

Brønnøysund requires a person authenticated through ID-porten to sign annual
accounts. Signing also submits the form. That action must remain a visible,
intentional owner step.

## Preconditions for a Live TT02 Rehearsal

All items must be evidenced before creating a draft:

1. An operator explicitly approves the permission changes.
2. The Maskinporten test client has both instance scopes.
3. Talli's system registration includes `app_brg_aarsregnskap`.
4. The selected synthetic company approves a separate annual-accounts system
   access request.
5. The approved person has the underlying right being delegated.
6. A complete RR-0002 XML pair for the supported schema has been generated and
   independently reviewed.
7. The XML renderer and crash-safe TT02 evidence journal tests pass.

The current client is a contract boundary, not an operator CLI. Do not perform a
live rehearsal by assembling ad-hoc HTTP calls around it.

## Intended Rehearsal Sequence

Once the preconditions are met, the guarded orchestration must:

1. persist a prepared checkpoint before any mutation;
2. obtain a system-user-bound Maskinporten token with the two instance scopes;
3. exchange it for an Altinn token;
4. create one empty TT02 instance for the approved synthetic company;
5. verify the returned owner, instance ID, current task, and data-element IDs;
6. replace `Hovedskjema` and `Underskjema` with the reviewed XML;
7. call instance validation and persist only bounded validation codes;
8. stop on every validation error;
9. lock the unchanged validated revision with the `confirm` action;
10. persist the resulting instance reference and signing-task state; and
11. hand the owner a direct Altinn link for personal ID-porten review/signing.

No automation may call the `sign` action. After the person signs, a separate
read-only verification step must prove the ended process and archive/receipt
data elements before authority-test evidence can be accepted.

## Abort Conditions

Stop without retrying the mutation when:

- the customer or system right does not match the approved request;
- the returned instance owner differs from the requested organization;
- a response is malformed, oversized, redirected, or has an unexpected content
  type;
- a data-element or instance ID is inconsistent;
- draft creation or locking has a `sent` checkpoint without an accepted
  response checkpoint;
- validation returns an error;
- XML changes after validation;
- `confirm` does not enter a signing task; or
- the post-signature archive/receipt cannot be tied to the same instance.

## Local Verification

Run:

```sh
npm run test:annual-accounts
npm run typecheck
```

The focused suite currently has 27 tests across the RR-0002 payload map, XML
renderer, Altinn client, crash-safe orchestration, and private file journal. It
uses injected clients/transports and creates no Altinn instance.
