# Talli Terms of Service Draft

Status: draft for founder/legal review  
Last updated: 2026-06-27  
Blocks: #72 remains open until human/legal signoff

## Operator

Talli is currently operated by Kristian Elmer (founder) as a natural person,
pre-incorporation. On registration of a Talli AS, these terms will be updated to
name the company and its organization number as the operator/provider.

## Product Scope

Talli is a holding-first accounting and filing app for simple Norwegian holding
AS companies. Launch scope is the annual holding compliance loop:

- `aksjonærregisteroppgaven`
- `årsregnskap`
- `skattemelding for AS`

Talli is not a full accounting system for all AS companies. Launch scope excludes
VAT, payroll, invoicing, customer/supplier ledgers, foreign tax complexity,
advanced corporate actions, audit-obligation cases, and legal/tax advisory work.

## User Responsibility

The user remains responsible for:

- having authority to act for the company;
- entering complete and correct source data;
- reviewing filing previews before submission;
- resolving hard readiness blocks;
- deciding whether to invite an accountant or advisor;
- keeping exported archives when leaving Talli.

Talli can block unsupported cases, show warnings, generate deterministic filing
data, and store receipts where available. Talli does not guarantee that a filing
is accepted by authorities, avoids fees, or replaces professional judgment in
complex cases.

## Direct Filing Limits

Direct filing may be enabled per obligation only after authority access,
test-environment evidence, security review, billing gate, and production
credential gate pass.

Before a production gate passes, Talli may offer previews, simulations, archive
exports, validation feedback, and support-boundary guidance. These must not be
marketed as completed live authority filing.

## Billing and Refunds

Billing follows the founder pricing gate:

- monthly subscription covers use of the workspace;
- filing package may be charged only after readiness passes;
- unsupported cases must not be charged for a filing package;
- if Talli accepts a supported case and fails because of Talli filing logic or
  integration, the filing package is refund-eligible.

Refund eligibility does not cover user-provided incorrect data, missing authority
access, unsupported cases, missed deadlines outside Talli control, or authority
outages unless Talli has made a separate written commitment.

Payments, when paid billing is enabled, are processed by Vipps MobilePay.

## Support Boundary

Talli support can help users understand app state, readiness blockers, supported
workflows, export files, receipts, and known product limits.

Support must not provide bespoke legal advice, investment advice, tax planning,
or accountant approval for unsupported cases. Needs-accountant cases should be
blocked, escalated, or exported for external review.

## Limitation of Liability

To the maximum extent permitted by applicable law, and without limiting any mandatory
consumer rights, Talli is not liable for indirect or consequential loss, for losses
arising from user-provided incorrect data, missing authority access, unsupported cases,
or authority/third-party outages. Talli's liability for a supported case that fails
because of Talli filing logic or integration is addressed through the refund mechanism in
the Billing and Refunds section. Final liability and cap wording is subject to legal
review.

## Governing Law and Jurisdiction

These terms are intended to be governed by Norwegian law, with disputes subject to the
Norwegian courts, without prejudice to mandatory consumer-protection rules. The exact
governing-law and venue wording is to be confirmed by the legal reviewer before
publication.

## Changes to These Terms

Talli may update these terms. Material changes will be communicated to active users
(for example, by email via Resend or in-app notice) before they take effect, with a
reasonable opportunity to review. Continued use after the effective date of an update
constitutes acceptance of the updated terms.

## Termination

A user may stop using Talli and cancel at any time; export the company archive before
cancellation (see `retention-delete-export-policy-draft.md`). Talli may suspend or
terminate access for non-payment, misuse, security risk, or unsupported/abusive use,
with notice where practical, and subject to statutory retention of accounting material.

## Effective Date

These terms take effect on their published effective date. This draft is not yet
published and has no binding effect until founder/legal signoff and publication.

## Required Human Review Before Publication

- Founder approves commercial terms and refund wording.
- Legal reviewer approves liability, consumer/business customer, and jurisdiction wording.
- Security reviewer confirms terms align with data-processing and incident docs.
- Launch reviewer confirms no claim conflicts with `docs/launch/clearance-checklist.md`.
