# Annual Accounts TT02 Boundary Runbook

Status: local renderer, guarded orchestration, private journal, immutable
post-signature verifier, and read-only Dialogporten evidence verifier implemented;
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
- Dialogporten instance lookup:
  https://docs.altinn.studio/en/dialogporten/user-guides/looking-up-dialogs/
- Dialogporten dialog details:
  https://docs.altinn.studio/en/dialogporten/user-guides/getting-dialog-details/

Pinned TT02 endpoints:

- Token exchange:
  `GET https://platform.tt02.altinn.no/authentication/api/v1/exchange/maskinporten`
- App base:
  `https://brg.apps.tt02.altinn.no/brg/aarsregnskap-vanlig-202406`

Required Maskinporten scopes:

- `altinn:instances.read`
- `altinn:instances.write`

The post-signature verifier requests only `altinn:instances.read`.

The separate Dialogporten verifier requests only `digdir:dialogporten`. It does
not combine that read scope with either instance scope.

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

`npm run annual-accounts:tt02` is the guarded operator entrypoint:

- `inspect` is offline and needs neither a signing key nor `--execute-test`;
- `step` requires a private exact-schema input file, private journal directory,
  `--execute-test`, the approved customer/year, and the test client credentials;
- one invocation advances at most one persisted operation;
- only `altinn:instances.read` and `altinn:instances.write` are requested;
- the lock transition additionally requires `--lock`; and
- stdout contains hashes and checkpoint metadata, never XML, contact data,
  bearer material, assertions, or private-key content.

`verify-signed` is a separate externally read-only action. It refuses to run
unless the exact journaled instance is already at `awaiting-person-signature`,
requests only `altinn:instances.read`, and then requires:

- the same instance owner, UUID, organization number, and two XML data-element
  IDs recorded before signing;
- an ended Altinn process with no current task; and
- exactly one `signature` data element with `application/json` content type.

The bounded result is written idempotently as a private immutable
`<operation-id>.signed.json` record in the journal directory. Unknown fields,
provider bodies, tokens, assertions, XML, symlinks, conflicting rewrites, and
permissive directories/files are rejected. This proves signed-instance
completion; it does not invent an Altinn inbox, archive, or receipt reference.

`verify-dialog` is another externally read-only action. It refuses to request a
token unless the immutable signed-instance record matches the exact operation,
company, year, and both XML hashes. It then:

- requests only `digdir:dialogporten`;
- resolves the exact Altinn instance reference through Dialogporten's lookup
  endpoint;
- retrieves that one dialog with a second `GET`;
- requires the same party, `app_brg_aarsregnskap` resource, `brg` owner,
  completed status, and a dialog update no earlier than instance completion;
  and
- stores only bounded IDs, timestamps, linkage hash, and transmission/attachment
  counts in private immutable `<operation-id>.dialog.json` evidence.

Titles, authorization evidence, attachment names and URLs, provider fields,
tokens, assertions, and form content are discarded or rejected. This establishes
the completed dialog for the signed instance; it does not fetch or claim the
content of a provider receipt or decision attachment.

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

To run the optional post-completion Dialogporten verification, the same client
must additionally have `digdir:dialogporten`. Adding that scope is a separate
permission change and is not authorized by this runbook.

Do not perform a live rehearsal by assembling ad-hoc HTTP calls around the
client or by running the guarded command before every precondition is evidenced.

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

No automation may call the `sign` action. After the person signs, run the
separate read-only verification step:

```sh
npm run annual-accounts:tt02 -- verify-signed \
  --input <absolute-private-input-json> \
  --journal <absolute-private-journal-directory> \
  --customer-org <approved-synthetic-org-number> \
  --income-year 2025 \
  --client-id <test-client-id> \
  --key-id <test-key-id> \
  --private-key <absolute-private-key-pem> \
  --execute-test
```

This must prove the ended process and signature artifact before signed-instance
evidence can be accepted. If the separate Dialogporten scope has been explicitly
approved and attached, resolve and persist the exact completed dialog with:

```sh
npm run annual-accounts:tt02 -- verify-dialog \
  --input <absolute-private-input-json> \
  --journal <absolute-private-journal-directory> \
  --customer-org <approved-synthetic-org-number> \
  --income-year 2025 \
  --client-id <test-client-id> \
  --key-id <test-key-id> \
  --private-key <absolute-private-key-pem> \
  --execute-test
```

This performs two provider `GET` requests and writes bounded dialog evidence.
Official receipt/decision attachment content remains a separate evidence
requirement.

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
- the post-signature ended process or signature artifact cannot be tied to the
  same instance; or
- Dialogporten resolves another instance, party, resource, or owner, reports an
  unfinished dialog, or has a completion timestamp inconsistent with the signed
  instance.

## Local Verification

Run:

```sh
npm run test:annual-accounts
npm run typecheck
```

The focused suite currently has 56 tests across the RR-0002 payload map, XML
renderer, Altinn client, crash-safe orchestration, private file journal,
post-signature verifier, exact-instance Dialogporten lookup, immutable signed and
dialog evidence stores, TT02 runner, and CLI guard. It uses injected
clients/transports and creates no Altinn instance.
