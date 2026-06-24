# Talli Privacy Policy Draft

Status: draft for founder/legal review  
Last updated: 2026-06-24  
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

Support/operator access must be limited to operational need, audited, and
reviewed before production launch.

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

## Required Human Review Before Publication

- [x] Controller identified — Kristian Elmer (natural person), pre-incorporation;
  re-confirm and migrate to the AS name + org number on incorporation.
- [x] Processor list confirmed — Supabase, Vercel, Vipps MobilePay, Resend.
- [x] Data transfer basis confirmed — EEA residency; US suppliers under SCCs/DPF.
- [ ] Confirm support/operator access model.
- [ ] Legal/privacy reviewer approves final wording.
