# RF-1086 TT02 Submission Runbook

Status: system-user approval complete; synthetic preview review required before provider writes
Last updated: 2026-07-13
Environment: Skatteetaten test / Altinn TT02 only

This runbook is the controlled path for the first synthetic RF-1086 authority
submission. It cannot target production. It does not authorize production filing.

## Proven prerequisites

- Skatteetaten granted DM-8 test access to the vendor organization.
- The Maskinporten test client can obtain the RF-1086 scope.
- Altinn system `930835978_talli` includes
  `ske-innrapportering-aksjonaerregisteroppgave`.
- Test company `310279617` approved the standard system-user request.
- A system-user-bound Maskinporten token was issued for customer
  `0192:310279617`.

The Altinn page saying `Denne forespørselen er allerede godkjent` is a success
state. Do not create or approve another request.

## Official anchors

- Skatteetaten RF-1086 API:
  https://skatteetaten.github.io/api-dokumentasjon/api/innrapportering-aksjonaerregisteroppgave
- Published OpenAPI 1.0.0:
  https://api.swaggerhub.com/apis/skatteetaten/innrapportering-aksjonaerregister-api/1.0.0/swagger.json
- Altinn system-user token guide:
  https://docs.altinn.studio/en/authorization/guides/system-vendor/system-user/usetoken/
- Digdir JWT grant:
  https://docs.digdir.no/docs/Maskinporten/maskinporten_protocol_jwtgrant
- Digdir token endpoint:
  https://docs.digdir.no/docs/Maskinporten/maskinporten_protocol_token.html

Skatteetaten's test recipe says to use a real vendor organization for the
Maskinporten test client, a synthetic organization and role-holder from Tenor
for system-user approval, and only synthetic data for test submissions. Those
setup steps are complete.

## Safety properties

The local runner is `npm run rf1086:tt02`.

- The provider environment is hard-coded to `test`.
- Preview and key files must be regular, non-symlinked, private files.
- The journal directory must be `0700`; checkpoint files are `0600`.
- The token grant lasts 120 seconds and is never printed or journaled.
- Every XML document must contain only the approved customer organization and
  the selected income year.
- Each invocation sends at most one provider request.
- Main- and sub-form retries reuse the exact persisted idempotency key.
- The non-idempotent `bekreft` call requires `--confirm` and is never
  automatically replayed after an uncertain result.
- Preview-only inspection does not read the private key or request a token.

## Synthetic fixture under review

The initial 2025 no-activity integration fixture uses the source-backed company
capital structure from the synthetic organization dataset:

- company: `LOGISK ØDE TIGER AS`, organization `310279617`;
- share capital: NOK 1,000,000, fully paid;
- shares: 500 ordinary shares;
- nominal value: NOK 2,000 per share;
- no 2025 share changes, dividends, or other RF-1086 events;
- one synthetic role-holder is assigned all 500 shares solely for this TT02
  integration fixture.

The shareholder allocation is constructed synthetic test data. It is not
presented as ownership sourced from Brønnøysundregistrene or
Aksjonærregisteret. The final XML preview and this assumption must be reviewed
before any provider write.

## Operator sequence

Use absolute paths. Keep the private key outside the repository. Do not paste a
token into a command, file, terminal history, issue, or documentation.

1. Create a private journal directory and verify private file permissions:

   ```sh
   mkdir -m 700 <absolute-journal-directory>
   chmod 600 <absolute-preview-json> <absolute-private-key-pem>
   ```

2. Inspect without external writes:

   ```sh
   npm run rf1086:tt02 -- inspect \
     --preview <absolute-preview-json> \
     --journal <absolute-journal-directory> \
     --customer-org 310279617
   ```

   Review the company, income year, main-form hash, ordered sub-form hashes,
   and `nextOperation`. The output deliberately excludes XML and personal
   identifiers.

3. After the preview is explicitly accepted, send exactly one test step:

   ```sh
   npm run rf1086:tt02 -- step \
     --preview <absolute-preview-json> \
     --journal <absolute-journal-directory> \
     --customer-org 310279617 \
     --client-id 7166e743-978e-4a60-8a2d-0a5c00fe6ad0 \
     --key-id 2d275f93-10a2-4839-993e-b14da2b84ad8 \
     --private-key <absolute-private-key-pem> \
     --execute-test
   ```

4. Inspect again. Repeat step 3 only while `nextOperation` is a hovedskjema or
   underskjema operation.

5. When inspection reports `bekreft`, re-check all hashes and the journal. The
   final call additionally requires `--confirm`:

   ```sh
   npm run rf1086:tt02 -- step \
     --preview <absolute-preview-json> \
     --journal <absolute-journal-directory> \
     --customer-org 310279617 \
     --client-id 7166e743-978e-4a60-8a2d-0a5c00fe6ad0 \
     --key-id 2d275f93-10a2-4839-993e-b14da2b84ad8 \
     --private-key <absolute-private-key-pem> \
     --execute-test \
     --confirm
   ```

6. Record the returned main-form, dialog, and shipment references. Use the
   published document endpoints to retrieve feedback and receipt artifacts.
   Do not claim success until those artifacts are stored and reviewed.

## Stop conditions

Stop and reconcile without automatic replay if:

- the preview hash, company, year, or environment changes;
- the journal reports `failed_blocked` or `reconcile`;
- `bekreft` times out or returns an uncertain result;
- the provider response is malformed or uses an unexpected content type;
- the company or shareholder assumption is no longer accepted for the test.

