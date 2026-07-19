# Talli Privacy Policy Draft

Status: draft for founder/legal/security review
Last updated: 2026-07-17
Blocks: #72 remains open until the required human approvals are recorded

## Controller

ELMER WELFIS, org.nr. 930 835 978 is the controller for account administration,
service security, legal compliance, and its own business records. This role
boundary and the final purpose-by-purpose legal bases require legal/privacy
review before publication.

For business customers, the customer company is expected to be controller for
personal data in its own company, shareholder, accounting-document, and filing
content. ELMER WELFIS/Talli is expected to act as processor when it handles that
data on the customer's documented instructions under `dpa-draft.md`. The final
controller/processor allocation remains subject to legal review.

## Data Talli Processes

Talli processes data needed to operate a holding-first accounting and filing app:

- account data: email, auth identifiers, session/security state;
- company data: organization number, company name, address, entity type, status;
- membership data: owner/reviewer/read-only roles, invitations, accepted access;
- accounting data: ledger entries, holding actions, bank CSV rows, opening balances;
- documents: accounting source documents, storage keys, metadata, signed download events;
- filing data: previews, validation issues, overrides, confirmations, submissions, receipts;
- billing data: plan, subscription state, filing-package state, refund eligibility;
- audit logs: security, role, document, ledger, billing, filing, and support-relevant events;
- authority feedback and receipts when the relevant filing capability is enabled.

## Purpose

Data may be processed to:

- provide company workspaces and account access;
- maintain company accounting records and document archives;
- evaluate filing readiness;
- prepare, simulate, validate, and, only where separately enabled, submit filings;
- store authority feedback and receipts;
- manage billing and refunds when billing is enabled;
- provide support and security operations; and
- export company archives and handle cancellation/deletion requests.

Agreement acceptance does not enable billing or production filing and does not
prove that any hosted security or filing gate has passed.

## Access and Security Control Objectives

The intended access model is role-scoped: owners manage authorized company
resources; reviewers and read-only members receive limited access; non-members
are denied. The intended support/operator model is least-privilege, read-only by default,
time-bounded, request- or incident-gated, and audited.

These are required control objectives, not a claim that the current hosted
environment has been approved. Tenant isolation, private storage, operator
access, encryption, audit logging, backup, and restore must be verified against
the current production environment before being stated as implemented facts or
before named-company processing begins.

## Legal Basis for Processing

The intended GDPR article 6 bases, subject to final purpose-by-purpose review,
are:

- **Contract (art. 6(1)(b))** for processing needed to provide requested account
  and service functions;
- **Legal obligation (art. 6(1)(c))** for records that applicable law requires
  ELMER WELFIS to retain;
- **Legitimate interests (art. 6(1)(f))** for proportionate security, fraud and
  abuse prevention, service integrity, and business administration; and
- **Consent (art. 6(1)(a))** for optional processing that specifically relies on
  consent, which may be withdrawn.

The legal/privacy reviewer must confirm the correct controller, purpose, basis,
necessity, balancing, notice, and retention for each activity before publication.

## Processors and External Services

Talli may use external services for database, authentication, storage, hosting,
optional identity login, payments, transactional email, and Norwegian authority
connections. Provider identity, controller/processor role, data categories,
processing location, contract terms, certifications, and production configuration
must be verified against current production contracts and configuration before
publication. A draft-time provider choice is not a verified production fact.

## Data Location and International Transfers

No particular storage region, residency, certification, international-transfer
path, or transfer mechanism is represented as verified by this draft. Before an
actual restricted transfer, Talli must verify and document the processing
locations, a valid legal transfer mechanism, any required transfer assessment,
and necessary supplementary measures. Relevant current information must be made
available to affected customers before the transfer begins.

## Retention

Accounting documentation, filing receipts, billing records, and audit trails may
need retention after cancellation. Retention must be mapped to the applicable
controller, purpose, and legal duty. User-requested deletion must not silently
remove material that law requires the responsible controller to retain. See
`docs/legal/retention-delete-export-policy-draft.md`; exact periods and role
allocation remain subject to legal review.

## User Rights

Users may request access, correction, export, restriction, objection, or deletion
where applicable. Talli should provide company archive export before cancellation
and explain any data that cannot be deleted immediately because of a verified
legal retention duty.

Users may lodge a complaint with the Norwegian Data Protection Authority
(Datatilsynet) if they believe personal data is processed unlawfully.

## Required Human Review Before Publication

- Legal/privacy reviewer approves the controller/processor boundary, each
  purpose and legal basis, retention, rights, and transfer wording.
- Founder confirms the actual provider list and customer-facing commitments.
- Security reviewer confirms access and security statements against current
  hosted tenant-isolation, private-storage, backup, restore, and audit evidence.
- Provider regions, transfer bases, certifications, and hosted controls remain
  pending until current production verification is recorded.
