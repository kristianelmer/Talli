# Talli Data Processing Agreement Draft

Status: draft for founder/legal review  
Last updated: 2026-06-24  
Blocks: #72 remains open until human/legal signoff

## Parties and Roles

For business customers, the customer company is expected to be controller for
company accounting data, documents, and filing content. Talli is expected to be
processor for hosting, processing, validating, and submitting data according to
customer instructions.

Talli is currently operated by Kristian Elmer (founder) as a natural person,
pre-incorporation, acting as processor. On registration of a Talli AS, the
processor of record will migrate to that company and this agreement updated with
the company name and organization number.

This role model must be reviewed before production launch.

## Processing Instructions

Talli may process customer data to:

- maintain accounting workspace and archive;
- store source documents;
- run deterministic filing validation and readiness gates;
- generate filing previews and payloads;
- submit filings when production gates are enabled and user confirms;
- store authority feedback/receipts;
- provide support, billing, security monitoring, export, and cancellation flows.

Talli must not use customer accounting data for unrelated purposes without a
separate legal basis and customer-facing disclosure.

## Security Measures

Minimum controls:

- Supabase Auth and RLS for tenant isolation;
- private object storage and short-lived signed URLs for documents;
- MFA/step-up for sensitive actions;
- audit events for sensitive actions, invites, document access, posting, overrides,
  billing, submissions, feedback, receipts, exports, and deletion;
- production secrets outside repo/client env;
- backup/restore test before production filing;
- least-privilege support/operator access.

## Subprocessors

| Subprocessor | Purpose | Location / transfer basis |
| --- | --- | --- |
| Supabase | Database, auth, RLS, document storage | EU region (EEA) |
| Vercel | App hosting and runtime logs | US-incorporated; EEA data under SCCs/DPF |
| Vipps MobilePay | Payment processing (when paid billing enabled) | EEA |
| Resend | Transactional/notification email | US-incorporated; under SCCs/DPF |
| Norwegian public authority systems | Filing and access flows (Maskinporten/Altinn/Skatteetaten) | Norway (EEA) |

Subprocessor changes require advance notice to customers. The list above must be
re-confirmed on incorporation and before any provider change.

## Deletion and Return

On cancellation, Talli should provide archive export before deletion. Some data
may remain under accounting-document retention or audit obligations. Deletion
process must distinguish:

- account/auth data;
- company workspace data;
- accounting documents;
- filing payloads and receipts;
- billing records;
- audit/security logs.

## Required Human Review Before Publication

- [ ] Legal reviewer confirms controller/processor role (incl. pre-incorporation operator).
- [x] Processor/subprocessor table completed — Supabase, Vercel, Vipps MobilePay, Resend, authority systems.
- [ ] Security reviewer confirms technical measures are true in production.
- [ ] Founder approves customer-facing deletion/return obligations.
