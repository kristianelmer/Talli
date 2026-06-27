# Talli Privacy Policy Draft

Status: draft for founder/legal review  
Last updated: 2026-06-27  
Blocks: #72 remains open until human/legal signoff

## Controller

Talli is currently operated by Kristian Elmer (founder) as a natural person,
pre-incorporation. Kristian Elmer is the data controller for account and service
data. Once a Talli holding/operating AS is registered, the controller of record
will be migrated to that company and this policy updated with the company name
and organization number.

For business customers, the customer company is controller for its own company
accounting data, documents, and filing content (see `dpa-draft.md`).

## Data Talli Processes

Talli processes data needed to operate a holding-first accounting and filing app:

- account data: email, auth identifiers, session/security state;
- company data: organization number, company name, address, entity type, status;
- membership data: owner/reviewer/read-only roles, invitations, accepted access;
- accounting data: ledger entries, holding actions, bank CSV rows, opening balances;
- documents: accounting source documents, storage keys, metadata, signed download events;
- filing data: previews, validation issues, overrides, confirmations, submissions, receipts;
- billing data: plan, subscription state, filing-package state, refund eligibility;
- audit logs: security, role, document, ledger, billing, filing, and support-relevant events.

## Purpose

Data is processed to:

- provide secure company workspaces;
- maintain company accounting records and document archive;
- evaluate filing readiness;
- prepare, simulate, validate, and, where enabled, submit statutory filings;
- store authority feedback and receipts;
- manage billing and refunds;
- provide support and security monitoring;
- export company archives and handle cancellation/deletion requests.

## Access

Access is role-scoped:

- owner can manage company data, documents, filing, billing, reviewers, and export;
- reviewer can read authorized data and add review comments;
- read-only can read authorized data but cannot mutate company resources;
- non-members are denied by RLS and storage policies.

Support/operator access is read-only by default and follows a least-privilege model:
it is time-boxed, granted only on the user's request or for a documented incident, and
every access is recorded in the audit log. Standing or unaudited operator access to
company data is not permitted, and the access model is reviewed before production launch.

## Legal Basis for Processing

Talli processes personal data under the following GDPR article 6 bases:

- **Contract (art. 6(1)(b))** — account, company workspace, accounting, filing, and
  billing data processed to provide the service the user has signed up for.
- **Legal obligation (art. 6(1)(c))** — retention of accounting material and filing
  evidence required by Norwegian law (bokføringsloven § 13).
- **Legitimate interests (art. 6(1)(f))** — security monitoring, audit logging, fraud/
  abuse prevention, and service improvement, balanced against user rights.
- **Consent (art. 6(1)(a))** — any optional processing that is not covered above; consent
  can be withdrawn at any time.

The legal basis for each processing purpose must be confirmed by the legal/privacy
reviewer before publication.

## Processors and External Services

Named processors/services:

- Supabase (Postgres/Auth/Storage) for data, auth, RLS, and documents — EU region;
- Vercel for app hosting and runtime logs (US-incorporated; EEA data covered by SCCs);
- Vipps MobilePay for payment processing when paid billing is enabled — EEA;
- Resend for transactional/notification email (US-incorporated; covered by SCCs);
- Norwegian public authority systems when direct filing is enabled.

This list reflects the providers chosen at draft time and must be re-confirmed on
incorporation and before any provider change.

## Data Location and International Transfers

Personal and company data is stored in the EEA (Supabase EU region; Vipps
MobilePay operates within the EEA). Some processors are US-incorporated
(Vercel for hosting, Resend for email). Where data is processed by a
US-incorporated supplier, the transfer is covered by EU Standard Contractual
Clauses (SCCs) and/or the EU-US Data Privacy Framework as set out in that
supplier's data processing terms. Talli does not transfer data outside the EEA
except as described here.

## Retention

Accounting documentation, filing receipts, and audit trails may need retention
even after cancellation. Primary accounting material is retained for a minimum of
5 years after the end of the accounting year, per the Norwegian Bookkeeping Act
(bokføringsloven § 13). Deletion requests must be evaluated against accounting
documentation requirements and legal retention duties. See
`docs/legal/retention-delete-export-policy-draft.md`.

## User Rights

Users may request access, correction, export, restriction, or deletion where
applicable. Talli should provide company archive export before cancellation and
explain any data that cannot be deleted immediately because of statutory
retention obligations.

Users also have the right to lodge a complaint with the Norwegian Data Protection
Authority (Datatilsynet) if they believe their data is processed unlawfully.

## Required Human Review Before Publication

- [x] Controller identified — Kristian Elmer (natural person), pre-incorporation;
  re-confirm and migrate to the AS name + org number on incorporation.
- [x] Processor list confirmed — Supabase, Vercel, Vipps MobilePay, Resend.
- [x] Data transfer basis confirmed — EEA residency; US suppliers under SCCs/DPF.
- [x] Support/operator access model confirmed — read-only, time-boxed, request/incident-
  gated, fully audited; no standing operator access to company data.
- [ ] Legal/privacy reviewer approves final wording and per-purpose legal basis.
