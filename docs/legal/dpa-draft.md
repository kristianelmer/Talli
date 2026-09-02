# Talli Data Processing Agreement Draft

Status: founder/accountable-owner role and return/delete decisions approved; hosted appendix pending
Last updated: 2026-08-30
Blocks: #72 remains open until the production subprocessor/security appendix and final digest are recorded

This Data Processing Agreement (DPA) forms part of the Talli Business Terms
between the customer and ELMER WELFIS, org.nr. 930 835 978. It is intended to
cover the requirements of GDPR Article 28 where Talli processes personal data
on the customer's behalf. The founder/accountable-owner decision does not by
itself publish this draft or prove hosted compliance.

## 1. Parties, Roles, and Priority

The customer company is controller for personal data in its company,
shareholder, accounting-document, narrow-ledger, and filing content. Talli is
processor when ELMER WELFIS processes that content to provide the service on
documented instructions.

ELMER WELFIS acts as an independent controller for limited processing needed for
account and access administration, service security, support, optional public
measurement, billing, legal compliance, and its own business records. If this
DPA conflicts with the Business Terms about processor activity, this DPA
prevails.

## 2. Subject Matter, Nature, Purpose, and Duration

The subject matter is processing needed to provide the customer's Talli
workspace and supported accounting and reporting workflows. The nature and
purpose can include collecting, storing, organizing, calculating, displaying,
validating, exporting, and, only when separately enabled, transmitting data;
maintaining security and audit records; providing support; and returning or
deleting data.

Processing lasts while the Business Terms apply, during the approved read-only
and export period, and afterward only as needed to follow the customer's return
or deletion instruction, complete a verified backup rotation, or meet a legal
retention duty that applies directly to Talli.

## 3. Categories of Data Subjects and Personal Data

Categories of data subjects can include the customer's users, shareholders,
board members, employees, contact persons, transaction counterparties, and
other people identified in customer-controlled documents or filing material.

Categories of personal data can include identity and contact data; account,
authentication, access, ownership, and role data; transactions and accounting
documents; document contents; reporting and filing data; authority feedback and
receipts; billing data; and security and audit logs. The customer must not use
Talli for categories outside the supported service or provide special-category
data unless the service and parties have expressly approved that processing.

## 4. Documented Instructions

The processor processes personal data only on documented instructions from the
controller, including this DPA and the customer's authorized use of enabled
service functions, unless applicable law requires other processing. Where
permitted, the processor informs the controller before legally required
processing. It notifies the controller without undue delay if it believes an
instruction infringes applicable data-protection law.

The processor must not use customer accounting data for an unrelated purpose
without a separate legal basis and customer-facing disclosure.

## 5. Confidentiality

The processor ensures that people authorized to process customer personal data
are bound by confidentiality and receive access only as needed for their role.
Least-privilege, time-bounded, request- or incident-gated, and audited operator
access is the required model; the deployed implementation requires current
security-review evidence before publication.

## 6. Technical and Organizational Measures

The processor must implement technical and organizational measures appropriate
to the processing risk. The required control objectives include:

- authentication, authorization, and tenant isolation;
- private object storage and time-limited document access;
- encrypted transport and protected production secrets;
- auditable sensitive actions and security monitoring;
- secure development, deployment, incident handling, and least privilege; and
- backup, tested restoration, continuity, and deletion controls.

This list is a contractual control objective, not a certification or proof that
the current hosted environment has passed review. Before named-company
processing, the accountable owner must confirm exact Supabase and Vercel
systems, hosted tenant isolation, private storage, case- and time-limited support
access, database and document restore, logs, regions, external services,
transfers, privileged access, deletion, automatic cleanup, monitoring, and
incident handling. AI agents may collect and test evidence but do not provide an
independent professional certification.

## 7. Subprocessors

The customer gives general written authorization for subprocessors needed to
provide Talli. The processor must maintain an available current list, give
advance notice of intended additions or replacements so the customer can raise
a reasonable data-protection objection, and impose substantially equivalent
data-protection obligations on each subprocessor. The processor remains
responsible to the customer for subprocessor performance as required by law.

Potential production subprocessors and their purposes include database,
authentication and storage hosting; application hosting; payment processing
when enabled; transactional email; and Norwegian authority systems when filing
is enabled. Names, roles, processing locations, certifications, international
transfer paths, and transfer bases must be re-confirmed against current
production contracts and configuration before publication. This draft does not
assert an unverified location, certification, or transfer basis.

Any material provider or security change requires security re-confirmation
against the current hosted environment before customer processing continues.

## 8. International Transfers

The processor transfers personal data outside the EEA only on documented
instructions and when applicable data-protection requirements are met. Before
an actual transfer, it must verify and document a valid transfer mechanism and
any necessary supplementary measures, and make relevant information available
to the controller. No particular transfer basis is represented as verified by
this draft.

## 9. Assistance and Data-Subject Rights

Taking account of the nature of processing, the processor assists the
controller, where possible through appropriate technical and organizational
measures, with requests to exercise data-subject rights. A request received
directly about customer data is referred to the controller unless law requires
otherwise.

The processor also provides reasonable assistance, taking account of the
information available and the nature of processing, with security duties,
breach assessment and notification, data-protection impact assessments, and
prior consultation with supervisory authorities.

## 10. Personal Data Breach Notification

When the processor becomes aware of a personal-data breach affecting data
processed on the customer's behalf, it notifies the affected customer (controller) without undue delay.
As information becomes available, the notice
describes the incident, affected categories, likely consequences, measures and
contact point needed to support the controller's own obligations. The
controller decides whether it must notify authorities or data subjects.

## 11. Audit and Compliance

The processor makes available to the controller the information reasonably
necessary to demonstrate compliance with this DPA and GDPR Article 28, and
supports reasonable audits or inspections by the controller or its mandated
auditor. Audits should use available documentation and remote review first,
give reasonable notice, remain limited to the customer's processing, and
protect other customers, security, and confidentiality.

## 12. Deletion and Return

At the end of the approved read-only and export period, the processor returns or
deletes customer personal data and existing copies at the controller's
documented choice, unless a legal duty applies directly to Talli or the
controller gives a lawful documented retention instruction. The customer's own
bookkeeping duty is not a general reason for Talli to retain all customer data.
Lawfully retained data is isolated from ordinary processing and used only for
the retention purpose. Backups are deleted or overwritten under the applicable
production rotation after that rotation is verified.

The operational deletion sequence must distinguish account/auth data, company
workspace data, accounting documents, filing payloads and receipts, billing
records, and audit/security logs. It must remain aligned with
`retention-delete-export-policy-draft.md` and applicable accounting retention
requirements.

## 13. Duration and Termination

This DPA applies for as long as Talli processes personal data on the
controller's behalf. Its confidentiality, security, audit, and deletion duties
continue for retained personal data after the Business Terms end.

## Approval and Remaining Evidence

- Kristian Elmer approved the controller/processor boundary, return/delete
  position, transfer condition, and customer-facing obligations as founder and
  accountable owner on 2026-08-30.
- The accountable owner must confirm the technical and organizational measures
  and all published subprocessor facts against the current hosted environment.
- AI-assisted research informed the decision and is not professional legal or
  security certification.
- Production subprocessor locations, transfer bases, certifications, security
  appendix, and restore claims remain unapproved until evidenced and reviewed.
