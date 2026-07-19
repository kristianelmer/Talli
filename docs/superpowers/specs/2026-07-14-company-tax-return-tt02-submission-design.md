# Company Tax Return TT02 Submission Evidence Design

Status: approved product path; implementation test-only and production-disabled

## Goal

Complete the existing company-tax-return TT02 integration through an owner-managed
Altinn submission and official feedback receipt without enabling production or
allowing a system user to perform the owner's final confirmation.

## Authoritative contract

The pinned Skatteetaten `skattemeldingen` source at tag `v1.62.47` is the
authority for the 2025 integration:

- <https://github.com/Skatteetaten/skattemeldingen/blob/v1.62.47/docs/api-v2/README.md#altinn3-api>
- <https://github.com/Skatteetaten/skattemeldingen/blob/v1.62.47/docs/api-asynk/README.md>
- <https://docs.altinn.studio/en/api/apps/process/>
- <https://docs.altinn.studio/en/api/apps/data-elements/>

The contract requires both Skatteetaten and Altinn operations: retrieve the
current return, create an Altinn instance, upload the combined envelope, run
asynchronous validation, move the instance to `Bekreftelse`, let a person
complete the final confirmation/submission, and retrieve the later
`tilbakemelding` data element. The Altinn instance remains the archive record.

## Boundaries

- Every network call is restricted to TT02/test endpoints. Constructing the
  client for production continues to throw.
- The supported case is a simple Norwegian AS with no attachment, auditor, or
  unsupported tax treatment requirement.
- Submission requires the current Skatteetaten document reference. A missing
  current draft blocks the run; Talli does not invent a reference.
- The system-user phase may advance the process exactly once from the initial
  data task to the owner confirmation task. It must not invoke the second
  `process/next` that submits the return.
- The resume phase is read-only. It may inspect the instance and download the
  official `tilbakemelding`, but it performs no process transition.
- Raw access tokens, private keys, source XML, current-return XML, calculated
  response documents, receipt XML, and personal identifiers are never written
  to repository evidence.
- Production filing and production authority capability remain disabled after
  successful TT02 evidence.

## Client interfaces

Extend `app/lib/company-tax-return-authority-client.ts` with the following
test-only operations:

1. `getInstance({ instanceId })` parses process state, archive status, and
   sanitized data-element metadata.
2. `advanceToConfirmation({ instanceId })` reads the instance, advances only
   when the current task is the initial data task, then verifies that the
   resulting task is confirmation. Calling it again in confirmation is
   idempotent and performs no write.
3. `getOwnerConfirmationUrl({ instanceId })` returns Skatteetaten's documented
   TT02 viewer URL for the exact instance.
4. `getFeedbackReceipt({ instanceId })` finds exactly one clean
   `tilbakemelding` data element, downloads it as XML, and returns only the XML
   to the in-memory caller plus stable metadata. Missing/pending receipt is a
   retryable typed error; duplicates, rejected scan state, or non-XML content
   are blocking errors.
5. `waitForCompanyTaxReturnFeedback(...)` performs bounded read-only polling
   and returns the receipt when available.

Process parsing must be conservative. Unknown/missing tasks, a completed
instance without feedback, and any task other than initial data or confirmation
at preparation time fail closed with sanitized typed errors.

## Rehearsal phases

Extend `scripts/company-tax-return-authority-test.mjs` behind two explicit
operator approvals:

- `prepare`: require test credentials, the combined Skatteetaten and Altinn
  scopes, a company-bound supported fixture, and a writable sanitized evidence
  path. Fetch the current draft, render the reference-bound envelope, validate
  all three pinned XSDs, create/upload the instance, wait for a clean file scan,
  run async validation, require `validertOK`, and advance once to confirmation.
  Persist `awaiting_person_confirmation` evidence with instance/data/job IDs,
  payload hashes, validation summary, viewer URL, and no secrets.
- `resume`: require the existing evidence file and matching company/instance.
  Mint fresh test tokens, perform only read operations, wait for the official
  receipt, hash it, and atomically update evidence to
  `submitted_and_receipted`. Record process/archive metadata and the receipt
  data ID/reference/content hash/byte length without storing receipt XML.

Retries must reuse the exact instance recorded in evidence. A prepare run must
not create another instance when compatible awaiting-person evidence already
exists. Conflicting company, year, payload hash, or instance evidence is a hard
idempotency error.

## Evidence and runtime gate

The sanitized repository evidence is machine checked and maps to a dedicated
company-bound runtime importer. Import status remains `pending` until a final
accepted authority outcome is explicit in the receipt/evidence. Import never
writes `authority_permissions`, launch signoffs, production flags, or adapter
configuration.

The first implementation slice stops after client, rehearsal, evidence tests,
and documentation. Runtime persistence is a separate atomic slice so evidence
validation can be reviewed independently from database mutation.

## Verification

- Tests prove the first transition is made once and the final transition is
  never made by the system-user client or rehearsal.
- Tests prove resume mode performs only GET requests.
- Tests cover clean receipt retrieval, pending/retry, duplicate receipt,
  rejected scan, wrong content type, wrong task, idempotent confirmation, and
  production refusal.
- Existing validation tests and the full launch rehearsal remain green.
- The real TT02 run uses the pinned 2025 schemas and synthetic company data.
- Production remains disabled in capability tests and evidence.

## Completion criteria

This slice is complete when the test-only code and tests are committed and a
real TT02 instance reaches owner confirmation. Full company-tax authority
evidence additionally requires the owner to perform the personal confirmation,
the resume phase to retrieve a clean official feedback receipt, safe runtime
import, and dated production approval. None of those later gates may be
inferred from a prepared instance.
