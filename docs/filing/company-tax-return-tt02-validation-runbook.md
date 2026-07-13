# Company Tax Return TT02 Validation Runbook

Status: guarded calculation/read rehearsal only; no submission capability

Last updated: 2026-07-13

This runbook exercises Skatteetaten's company-tax-return API v2 in TT02 without
creating an Altinn instance or submitting a tax return. Both supported actions
require a private, crash-safe evidence journal.

## Preconditions

- Use synthetic data only.
- The Maskinporten test client must have
  `skatteetaten:formueinntekt/skattemelding`.
- The selected synthetic company must have an accepted Altinn system-user
  request for `app_skd_formueinntekt-skattemelding-v2`.
- For current-draft inspection, Tenor/source-system evidence must show that the
  company has an actual 2025 Skatteetaten company-tax-return draft. BRREG-only
  data is not sufficient.
- The client-bound RSA private key must be a regular, non-symlinked file with
  private permissions. Never put it in the repository or command output.
- Use only the pinned 2025 contract fixture and schemas recorded in
  `company-tax-return-schema-evidence-register.md`.

## Create the Private Journal

Create the journal outside the repository:

```bash
mkdir -m 700 <private-journal-directory>
```

Every command writes a new UUID-named checkpoint with mode `0600`. A checkpoint
is written as `prepared` before Maskinporten or Skatteetaten is called, then
atomically replaced by either `completed` or `failed` at revision 2.

The journal stores only:

- customer, year, operation, timestamps, and request hash;
- validation result, hashes of provider reasons, and feedback codes;
- calculated-document hashes, types, and byte lengths; or
- current-document ID hashes, content hashes, byte lengths, and locked-field
  counts.

It rejects unknown fields and therefore cannot retain bearer tokens, signed
assertions, authority XML, provider field values, or free-text provider
diagnostics.

## Inspect the Current 2025 Draft

Run only after the synthetic company is known to have a 2025 tax-return draft:

```bash
npm run company-tax-return:tt02 -- inspect-current \
  --customer-org <synthetic-org-number> \
  --income-year 2025 \
  --client-id <maskinporten-client-uuid> \
  --key-id <maskinporten-key-uuid> \
  --private-key <private-key.pem> \
  --journal <private-journal-directory> \
  --execute-test
```

This performs one read-only GET. Terminal output includes document references
needed for a later controlled validation step, but the journal stores only
their SHA-256 hashes.

## Run the No-Activity Contract Calculation

This calls only the `validertest` calculation endpoint:

```bash
npm run company-tax-return:tt02 -- calculate-no-activity \
  --tax-return tests/fixtures/company_tax_return/2025-no-activity-current-tax-return.xml \
  --customer-org <synthetic-org-number> \
  --income-year 2025 \
  --client-id <maskinporten-client-uuid> \
  --key-id <maskinporten-key-uuid> \
  --private-key <private-key.pem> \
  --journal <private-journal-directory> \
  --execute-test
```

The runner hard-checks that the result remains `calculationOnly=true` and
`validForSubmission=false`. It cannot call the filing-validation endpoint,
create an Altinn instance, upload documents, sign, or submit.

## Recovery Rules

- `prepared`, revision 1: the outcome may be unknown. Inspect the operator
  terminal and provider state before starting a new operation. Do not edit or
  delete the checkpoint to force a retry.
- `failed`, revision 2: use the stable failure code and external status pages to
  decide whether a new operation is appropriate. A new operation receives a new
  UUID; the earlier evidence remains immutable.
- `completed`, revision 2: compare the returned operation UUID and hashes with
  the checkpoint. Do not treat `validertOK` from `validertest` as submission
  approval.
- A stale `.lock` file requires operator reconciliation. The journal deliberately
  fails closed instead of guessing that no process is active.
- If the provider call completes but the revision-2 save fails, treat the result
  as completed-but-unpersisted and reconcile it manually. The runner will not
  overwrite revision 1 with a misleading provider-failure state.

## Stop Conditions

Stop and keep production filing disabled if:

- the company/year/namespace differs from the approved 2025 target;
- the system-user customer differs from the XML party;
- current-draft inspection returns 403 or no tax-return document;
- the provider reports missing tax-return source data;
- any checkpoint is invalid, permissive, symlinked, conflicting, or oversized;
- validation produces an unsupported field, warning, or tax treatment;
- no named authority reviewer has approved the resulting evidence.

The separate Altinn3 submission/signing/receipt adapter remains unimplemented
and must not be inferred from a passing calculation-only rehearsal.
