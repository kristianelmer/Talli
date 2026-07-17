# Talli Business Terms Draft

Status: draft for founder/legal/security review
Last updated: 2026-07-17
Blocks: #72 remains open until the required human approvals are recorded

## Parties and Business-Customer Scope

These Talli Business Terms are the general agreement between the company that
explicitly accepts them (the customer) and ELMER WELFIS, org.nr. 930 835 978
(the supplier). They apply only to business customers. The person accepting
must be authorized to bind the named customer company.

The Data Processing Agreement is incorporated into these Business Terms when
the supplier processes personal data on the customer's behalf. If the two
documents conflict about that processing, the Data Processing Agreement
prevails.

## Product Scope, Plans, and Capabilities

Talli is a holding-first accounting and filing app for simple Norwegian holding
AS companies. Its supported scope can include the annual holding compliance
loop:

- `aksjonærregisteroppgaven`
- `årsregnskap`
- `skattemelding for AS`

Talli is not a full accounting system for all AS companies. Supported scope
excludes VAT, payroll, invoicing, customer/supplier ledgers, foreign tax
complexity, advanced corporate actions, audit-obligation cases, and legal/tax
advisory work unless the service explicitly says otherwise.

The customer's price and access follow the plan and capabilities shown in the service.
Beta, early access, and later general availability are service
states under this same agreement, not separate customer agreements. Acceptance
alone does not activate payment or production filing.

## Account, Company, and Authority

The customer must provide correct information, protect account credentials, and
ensure its users have appropriate authority. An authenticated representative
accepts the current versioned Business Terms and Data Processing Agreement for
the named company through an explicit electronic control during company
onboarding. A personal account, passive use, a footer link, or a pre-selected
control is not company acceptance.

The acceptance record identifies the customer and accepting user and preserves
the document versions and SHA-256 digests, authority-statement version,
acceptance method, and timestamp. A later version does not rewrite an earlier
acceptance record. Material changes will be notified, and new explicit
acceptance will be collected when required.

## Customer Responsibility

The customer remains responsible for:

- entering complete and correct source data;
- reviewing calculations, documents, and filing previews before submission;
- resolving hard readiness blocks;
- deciding whether to invite an accountant or advisor;
- maintaining required authority access and meeting deadlines; and
- keeping exported archives when leaving Talli.

Talli can block unsupported cases, show warnings, generate deterministic filing
data, and store receipts where available. Preparation, local approval, or a
transport receipt is not final authority acceptance. Talli does not guarantee
that a filing is accepted by authorities, avoids fees, or replaces professional
judgment in complex cases.

## Direct Filing Limits

Direct filing may be enabled per obligation only after authority access,
test-environment evidence, security review, billing gate, production credential
gate, exact entitlement, and all other release conditions pass. Agreement
acceptance does not grant a filing entitlement or bypass any gate.

Before a production gate passes, Talli may offer previews, simulations, archive
exports, validation feedback, and support-boundary guidance. These must not be
marketed as completed live authority filing.

## Billing and Refunds

The current price and payment state are shown in the customer's plan. A free
plan creates no payment obligation. Before paid service is activated, its price
and payment terms must be shown and the customer must complete the applicable
activation.

The following refund boundary remains subject to founder and legal review:

- a filing package may be charged only after readiness passes;
- unsupported cases must not be charged for a filing package; and
- if Talli accepts a supported case and fails because of Talli filing logic or
  integration, the filing package is refund-eligible.

Refund eligibility does not cover customer-provided incorrect data, missing
authority access, unsupported cases, missed deadlines outside Talli's control,
or authority outages unless the supplier makes a separate written commitment.
Payments, when paid billing is enabled, are processed by the displayed payment
provider. Provider details require production re-confirmation before publication.

## Support Boundary

Talli support can help customers understand app state, readiness blockers,
supported workflows, export files, receipts, and known product limits. Support
does not take over the customer's review, archive, deadline, or filing duties.

Support must not provide bespoke legal advice, investment advice, tax planning,
or accountant approval for unsupported cases. Needs-accountant cases should be
blocked, escalated, or exported for external review.

## Confidentiality and Customer Data

Each party must protect the other's confidential information and use it only to
perform this agreement or as required by law. The customer retains rights in
its data and documents and permits the supplier to process them only as needed
to provide and secure the service. Talli software, design, and branding remain
the supplier's or its licensors' property.

## Acceptable Use

The customer must not use Talli unlawfully, seek unauthorized access to the
service or another customer's data, disrupt the service, or circumvent its
security or release gates.

## Limitation of Liability

To the maximum extent permitted by applicable law, the supplier is not liable
for indirect or consequential loss, or for loss arising from customer-provided
incorrect data, missing customer review or authority access, use outside the
supported scope, or authority/third-party outages. Nothing limits liability
that cannot be excluded under mandatory law.

Liability for a supported case that fails because of Talli filing logic or
integration is addressed through the refund mechanism above. Final liability,
cap, remedy, and business-customer wording remain subject to legal review and
must not be treated as approved by this draft.

## Suspension, Termination, and Export

The customer may cancel the service. The supplier may suspend access where
needed for a security risk, unlawful use, non-payment, or material breach, and
may terminate for material breach after reasonable opportunity to cure where
appropriate.

Before access ends, the customer must export data and documents it must retain.
After termination, personal data is handled under the Data Processing
Agreement, applicable retention law, and available export and deletion
procedures in `retention-delete-export-policy-draft.md`.

## Changes to These Terms

The supplier may update these terms as the service or law changes. Material
changes will be communicated by email or in the service before they take
effect, with a reasonable opportunity to review. New explicit acceptance will
be obtained when required; continued use alone is not the sole evidence of
acceptance of a material change.

## Governing Law and Jurisdiction

These terms are intended to be governed by Norwegian law. Disputes should first
be addressed in good faith and may then be brought before the ordinary Norwegian
courts under applicable venue rules and mandatory law. Final governing-law and
venue wording remains subject to legal review.

## Effective Date

These terms take effect for a customer when the published version is validly
accepted for that customer's company. This draft is not published and has no
binding effect until the required founder/legal/security approvals and
publication are recorded.

## Required Human Review Before Publication

- Founder approves the commercial terms and refund wording.
- Legal reviewer approves the B2B scope, electronic acceptance, liability,
  remedies, governing law, jurisdiction, and incorporation of the DPA.
- Security reviewer confirms alignment with the final DPA, security measures,
  incident policy, and current hosted evidence.
- Launch reviewer confirms no claim conflicts with
  `docs/launch/clearance-checklist.md` or enables production filing.
