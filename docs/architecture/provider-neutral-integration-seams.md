# Provider-Neutral Bank and Document Integration Seams

Status: provider contracts implemented; live adapters disabled
Last updated: 2026-07-13

## Decision

Talli exposes narrow ports for Open Banking consent/synchronisation and PDF
field extraction without selecting a vendor. The default adapters fail closed.
No real bank consent, transaction, document, credential, or callback data may
be sent to a third party until the corresponding external decision is approved.

Implementations:

- `app/lib/bank-provider.ts`
- `app/lib/document-extraction.ts`
- `tests/provider_ports.test.mjs`

## Bank boundary

The bank port supports only three operations: begin consent, synchronise from a
per-connection cursor, and verify a signed webhook. A future implementation
must preserve:

- explicit company scope on every operation;
- a provider connection reference rather than access/refresh tokens in public
  application tables;
- consent expiry and revocation state;
- stable transaction references and cursor-based retry;
- a hashed, unique webhook receipt key before any event is processed;
- signature verification over the original webhook bytes;
- redacted diagnostics with no bearer tokens or credential values.

The provider port does not post accounting entries. Imported transactions flow
through the existing duplicate hash and reconciliation process; deterministic
suggestions still require explicit owner acceptance.

## Document extraction boundary

Only a tenant-scoped PDF with a SHA-256 digest can enter the extraction port.
It begins in `quarantined` state. A future malware scan must move it to
`ready_for_extraction`; extraction may not bypass that transition.

Provider output is untrusted data. The current normaliser accepts only amount,
date, and the supported counter accounts `6700` or `7790`, caps evidence text,
marks every field untrusted, and always returns `review_required`. It cannot
create a ledger entry or mark its own output accepted.

The ordinary upload path independently enforces PDF signature, PDF MIME/name,
and a 10 MB size limit before private storage.

## Approval gates for a live adapter

Before changing either adapter mode from `disabled`:

1. Approve the vendor, commercial terms, processing region, retention policy,
   sub-processors, incident terms, and data-processing agreement.
2. Complete security review for token storage, key rotation, callback
   verification, replay handling, tenant isolation, log redaction, deletion,
   and provider outage behaviour.
3. Add provider-specific contract tests and test-environment evidence.
4. Add persisted connection/job state with RLS, immutable event receipts, and
   atomic idempotent transitions.
5. Record dated human approval and a rollback/disable procedure.

Until then, attempting either external operation raises a typed disabled error;
this is the expected production behaviour.
