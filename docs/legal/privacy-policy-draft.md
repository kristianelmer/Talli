# Talli Privacy Policy Draft

Status: founder/accountable-owner position approved; hosted facts and release digest pending
Last updated: 2026-08-30
Blocks: #72 remains open until hosted facts, final digests, and remaining pack decisions are recorded

## Controller

ELMER WELFIS, org.nr. 930 835 978, is the controller for limited processing used
for account and access administration, service security, support, optional
public measurement, billing, legal compliance, and its own business records.
Privacy contact: `post@talli.no`. Registered address: Fjøsangerveien 32D, 5053
Bergen, Norway.

For business customers, the customer company is controller for personal data in
its company, shareholder, accounting-document, narrow-ledger, and filing
content. ELMER WELFIS/Talli acts as processor when it handles that content on the
customer's documented instructions under `dpa-draft.md`.

## Data Talli Processes

Talli processes data needed to operate a holding-first accounting and filing app:

- account data: email, auth identifiers, session/security state;
- company data: organization number, company name, address, entity type, status;
- membership data: owner/reviewer/read-only roles, invitations, accepted access;
- accounting data: ledger entries, holding actions, bank CSV rows, opening balances;
- documents: accounting source documents, storage keys, metadata, signed download events;
- filing data: previews, validation issues, overrides, confirmations, submissions, receipts;
- billing data: company-year subscription, renewal choice, payment state, and
  refund eligibility;
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

The GDPR article 6 bases for ELMER WELFIS's own controller processing are:

- **Legitimate interests (art. 6(1)(f))** for proportionate account and access
  administration for a business customer, service security, fraud and abuse
  prevention, service integrity, support, and ordinary business administration;
- **Legal obligation (art. 6(1)(c))** for records that applicable law requires
  ELMER WELFIS to retain;
- **Consent (art. 6(1)(a))** for the optional public company-check and onboarding
  measurement described below. Consent may be withdrawn at any time.

For customer-controlled content, the customer determines its legal basis and
documents its instructions in the DPA. Talli must not silently reuse that
content for its own purpose.

Talli does not sell customer data. Talli does not use company, accounting,
bank, document, or filing data for advertising.

## Optional Public Measurement

If a visitor chooses `Tillat bruksmåling`, ELMER WELFIS uses voluntary
measurement only to see where the public company check and onboarding succeed or
stop. Talli processes a consent version, random session and event IDs, fixed
event, step, source and reason codes, and timestamps. This information is
pseudonymous personal data; Talli does not call it anonymous.

The measurement does not include a name, email, organization number, free text,
page address, accounting data, bank data, document information, account,
company, purchase, company-year, support, refund, or filing link. Nothing
optional is stored or sent before consent. Refusal has equal prominence and does
not reduce the service. The random session lasts no more than 30 minutes. Raw
events and minimized consent proof are deleted no later than 90 days after
receipt. The withdrawal tombstone lasts no more than 30 minutes.

A visitor can withdraw consent in the same interface. New collection stops at
once and Talli requests deletion of the raw session, with a safe retry if the
first request cannot be confirmed. Withdrawal does not affect processing that
was lawful before withdrawal. Provider logs and backups follow their verified
published periods and cannot be described until those facts are confirmed.

## Invited-Pilot Observation

An invited pilot uses the normal Talli product. A separate passive observer may
write a limited validation record after the normal product result. It must not
change, retry, hide, replace, or otherwise affect that result. Participants
receive the exact pilot information and agreement before observation starts.

Raw pilot observations are deleted no later than 90 days after receipt. The
separate protected participant register is deleted 12 months after validation
ends, unless a documented incident or legal requirement needs longer storage.
Access is limited to named validation reviewers. Full public launch requires
the observer to be off and every pilot permission to be expired or removed.

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

Customer-controlled content is returned or deleted at the customer's documented
choice after the agreed access/export period, unless a legal duty applies
directly to Talli or the customer instructs a lawful retention period. The
customer's bookkeeping duty is not a general right for Talli to retain unrelated
copies. Talli keeps its own billing and legal records only for their applicable
legal period. See `docs/legal/retention-delete-export-policy-draft.md`.

## Data Protection Officer Assessment

ELMER WELFIS does not appoint a formal data protection officer at launch. Talli
is not a public authority, does not conduct large-scale systematic monitoring,
and does not make large-scale processing of sensitive or criminal data a core
activity. The accountable owner reviews and records this assessment each year
and after a material product or scale change.

## User Rights

Users may request access, correction, export, restriction, objection, or deletion
where applicable. Talli should provide company archive export before cancellation
and explain any data that cannot be deleted immediately because of a verified
legal retention duty.

Users may lodge a complaint with the Norwegian Data Protection Authority
(Datatilsynet) if they believe personal data is processed unlawfully.

## Approval and Remaining Evidence

- Kristian Elmer approved the role, basis, measurement, retention, and DPO
  decisions as founder and accountable owner on 2026-08-30. AI-assisted research
  informed the decision and is not professional legal advice.
- The accountable owner must confirm the actual provider list and hosted access
  and security statements against current tenant-isolation, private-storage,
  backup, restore, logging, purge, and audit evidence.
- Provider regions, transfer bases, certifications, and hosted controls remain
  pending until current production verification is recorded.
