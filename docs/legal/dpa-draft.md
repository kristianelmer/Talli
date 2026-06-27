# Talli Data Processing Agreement Draft

Status: draft for founder/legal review  
Last updated: 2026-06-27  
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

## Personal Data Breach Notification

Where Talli (as processor) becomes aware of a personal-data breach affecting customer
data, Talli notifies the affected customer (controller) without undue delay and provides
the information the controller needs to meet its own GDPR art. 33/34 obligations: the
nature of the breach, the data classes and companies affected, likely consequences, and
the containment/remediation taken. Talli's internal handling follows
`incident-response-policy-draft.md`.

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

## Audit and Compliance

Talli makes available to the controller the information reasonably necessary to
demonstrate compliance with this agreement, and supports audits or inspections of
processing activities conducted by the controller or a mandated auditor, subject to
reasonable notice, confidentiality, and protection of other customers' data.

## Duration and Termination

This agreement applies for as long as Talli processes personal data on the controller's
behalf. On termination, Talli returns or deletes customer personal data per the Deletion
and Return section above, except where retention is required by law (for example,
accounting-document retention under bokføringsloven § 13).

## Required Human Review Before Publication

- [ ] Legal reviewer confirms controller/processor role (incl. pre-incorporation operator).
- [x] Processor/subprocessor table completed — Supabase, Vercel, Vipps MobilePay, Resend, authority systems.
- [ ] Security reviewer confirms technical measures are true in production.
- [x] Founder approves customer-facing deletion/return obligations — archive export before
  deletion; customer is responsible for the exported copy; statutory accounting material
  retained for the bokføringsloven § 13 minimum before final deletion.
