# Legal and Operational Policy Drafts

Status: founder/accountable-owner decisions approved; hosted facts and final release evidence pending
Last updated: 2026-08-30

Files:

- `terms-of-service-draft.md`
- `privacy-policy-draft.md`
- `dpa-draft.md`
- `retention-delete-export-policy-draft.md`
- `incident-response-policy-draft.md`
- `marketing-measurement-decision-draft.md`
- `founder-legal-security-decision-2026-08-30.md`

These drafts convert approved founder decisions into reviewable policy text.
Kristian Elmer approved the business and privacy position on 2026-08-30 as
founder and accountable owner. The review used AI-assisted legal and security
research; it is not professional legal advice or an independent human
certification. Issue #72 remains open until deployed provider/security facts,
final document digests, and the remaining liability decision are recorded.

## Current Agreement Model

ELMER WELFIS, org.nr. 930 835 978 is the current supplier. Talli uses one set of
general B2B Business Terms and one incorporated Data Processing Agreement for
beta, early-access, and generally available customers. Beta is a plan and
capability state, not a separate agreement. Pricing, payment, features, and
production-filing availability follow the plan and capabilities shown in the
service and their separate release gates.

An authenticated representative explicitly accepts the current Business Terms
and DPA for a Brønnøysund-resolved named company during company onboarding. The
representative must affirm authority to bind that company. Account signup,
passive use, footer links, or pre-selected controls do not constitute company
acceptance.

Every material new agreement version requires explicit authorized re-acceptance
and new immutable evidence before it binds the customer. Passive or continued
use cannot serve as acceptance evidence, alone or in combination with another
signal. The owner workspace therefore remains unavailable for an existing
company until one of its accepted owners explicitly accepts the pinned current
versions and digests. That acceptance is appended; historical evidence is not
updated or backfilled.

The append-only acceptance evidence records the customer legal name and
organization number, accepting user, immutable Business Terms and DPA versions
and SHA-256 digests, authority-statement version, acceptance method, and
timestamp. Later document publication must not rewrite historical acceptance.
Existing customer records must not be fabricated or silently backfilled.

The Privacy Notice is disclosed separately; it is not presented as a contract
the company must accept.

## Decisions Preserved in the Draft Pack

- The customer controls personal data in its company, shareholder,
  accounting-document, narrow-ledger, and filing content. ELMER WELFIS/Talli
  acts as processor for that content on documented instructions.
- ELMER WELFIS is controller for limited account, access, security, support,
  billing, optional public-measurement, and own legal-record processing.
- Archive export precedes cancellation. The customer is responsible for its
  exported copy, while lawful retention and deletion remain governed by the
  retention policy and final legal review.
- The intended support/operator access model is least-privilege, read-only by
  default, time-bounded, request- or incident-gated, and audited.
- Processor breach notification is without undue delay so the controller can
  assess its own notification duties.
- The annual NOK 1,490 company-year, narrow Talli-logic/connection refund, and
  safe-exit decisions from #177 replace the former monthly/filing-package model.
  Renewal, cancellation, charging, provider, and settlement details remain
  disabled and undecided.
- Liability-cap language remains an explicit founder decision item; no amount is
  inferred by this review.

Earlier provider-region and international-transfer notes are not production
facts. Subprocessor identity, role, location, certification, contract,
international transfer path, and transfer basis must be re-confirmed against
the current deployed service before publication. The drafts must not be read as
asserting unverified residency, SCC, DPF, certification, or security claims.

## Remaining Approval and Release Gates

Before the legal pack is released for a named company:

- Founder approval covers the recorded commercial, role, consent, retention,
  DPO, acceptance, governing-law, and jurisdiction decisions.
- The final liability cap still needs a founder decision.
- The accountable owner must confirm the technical and organizational measures,
  support/operator access model, subprocessor facts, and security appendix
  against current hosted evidence. AI agents may collect and test evidence but
  must not be named as independent human professionals.

Valid electronic acceptance does not by itself clear named-company beta entry.
That gate also requires approved, current evidence for hosted tenant isolation,
private storage, and restore in the deployed environment. Neither agreement
acceptance nor this draft pack enables billing, grants filing entitlement,
approves production credentials, or authorizes a production filing.

## Signoff Record Boundary

- Implementation: `app/lib/launch-signoff.ts`
- Test: `npm run test:launch-signoff`
- Required key: `legal_policy_pack`
- Closure rule: final terms, privacy policy, DPA, retention/delete/export
  policy, and incident policy must be approved with reviewer, review date,
  evidence link, and decision. Draft text and automated tests are not approval.
