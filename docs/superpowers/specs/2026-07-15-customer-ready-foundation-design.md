# Customer-ready foundation design

Status: approved through sequential founder HITL on 2026-07-15  
Decision owner: Kristian Elmer  
Legal beta operator: ELMER WELFIS, org.nr. 930 835 978  
Delivery branch: `codex/customer-ready-foundation`  

## Objective

Move Talli from a publicly reachable pre-production application to a truthful,
invite-only beta foundation with a non-forgeable sensitive-action boundary. This
slice also records the founder-approved product scope that governs the remaining
customer-ready build.

Production filing, live Vipps charging, and admission of paid customers remain
disabled. Enabling any of them requires a new explicit founder confirmation after
the corresponding evidence gates pass.

## Approved launch model

### Audience and availability

- The first release is an invite-only beta/waitlist, not a public production
  filing service.
- Signup interest may remain open, but the public site must state that production
  submissions and live payments are unavailable during beta.
- The beta is free. Paid access begins only after production filing and a live
  charge/refund flow are proven.
- Paid launch requires five separate private holding-company beta cases: one
  inactive company, one ordinary Norwegian investment case, one straightforward
  foreign-holding case, and two additional supported cases.
- Paid launch primarily targets income year 2026. Year-versioned 2025 support is
  retained for beta validation, late filings, and corrections.

### Supported company boundary

- Norwegian holding AS customers only for the initial paid launch.
- Exclude employees/payroll, VAT activity, foreign business activity beyond the
  supported shareholding facts, group accounts, audit-required entities, and
  complex securities.
- Support ordinary ownership in Norwegian and foreign limited companies when a
  structured questionnaire establishes a deterministic tax treatment.
- Block low-tax, NOKUS, hybrid, foreign-tax-credit, and otherwise uncertain
  cross-border cases.
- Support foreign transactions using the actual documented NOK settlement amount;
  preserve original currency/rate as evidence and do not estimate exchange rates.
- Prefer Skatteetaten-prefilled year-end share values. Missing unlisted-company
  values require documented user input; Talli does not estimate them.
- Support multiple NOK bank accounts. Foreign-currency bank accounts remain out of
  scope.
- Launch with CSV/manual document intake. Live bank feeds, OCR, BankID login, and
  third-party registry-assisted holding discovery are deferred.

### Opening investment positions

- Onboarding accepts one aggregate opening position per investment: share count
  and total book/tax cost, reconciled to prior records.
- Acquisition-lot history is required only before a disposal or when foreign-tax
  eligibility depends on ownership history.
- A sale remains blocked until the required history is complete. Talli never
  invents acquisition cost.

### Filing and corporate documents

- Paid launch must support RF-1086, company tax return, and annual accounts as one
  complete annual product.
- RF-1086 must cover ordinary holding-company purchases, sales, and dividends, not
  only incorporation/no-activity cases. Each scenario needs separate TT02 evidence.
- Company-tax launch supports only cases that require no additional attachments.
  Attachment-required cases are blocked and redirected.
- Include professionally reviewed annual-close documents: annual meeting minutes
  and annual-accounts approval. Optional/ad-hoc corporate documents stay disabled
  until separately reviewed or explicitly risk-accepted within their safe scope.
- The customer, not a Talli operator, reviews and approves the filing. Talli shows
  the exact output, evidence, and warnings; blocks unsupported/inconsistent cases;
  and never submits silently.
- Public copy must describe technical validation, not accountant, legal, or human
  professional assurance.
- A customer may invite an accountant/adviser with read-only and commenting access.
  Only a verified owner may approve, pay, or submit.

### Professional validation and founder override

- Before paid launch, seek a one-time Norwegian accountant review of accounting and
  tax mappings and a Norwegian lawyer review of corporate/legal templates.
- The founder may explicitly override either professional-review gate with a named,
  dated risk acceptance.
- An override cannot claim that professional review occurred and cannot enable an
  unreviewed template or uncertain tax case beyond the accepted scope.
- Authority approval, production credentials, tenant isolation, signed AAL2,
  restore evidence, and the final production confirmation are non-bypassable.

### Authentication, authority, and support access

- Use email/Google account login plus Supabase MFA. Do not add BankID login for the
  first launch.
- Use ID-porten/Altinn for authority confirmation and signing where the authority
  flow requires it.
- Demo exploration may be unverified. Creating a real company workspace, storing
  company records, or inviting users requires Altinn/ID-porten authority proof.
- Talli operators see status metadata only by default. Accounting details or
  documents require a time-limited customer-granted support session with a complete
  audit trail. Emergency break-glass access is separate and fully audited.
- Customer support is email-only at `post@talli.no`, with a target response within
  two business days and no advertised phone/on-call SLA.

### Billing and cancellation

- Vipps MobilePay is the first live payment provider.
- Founder cohort: first 100 companies at NOK 29/month plus NOK 299 per annual filing
  package. Founder pricing remains while the subscription stays continuously
  active; cancellation and later reactivation use the then-current standard price.
- Standard price: NOK 49/month plus NOK 499 per annual filing package.
- Advertised prices include VAT whenever VAT applies.
- One filing package covers RF-1086, company tax return, and annual accounts for one
  company/income year. Supported corrections for that year are included while the
  subscription remains active.
- Cancellation stops renewal. Full access continues through the paid-through date,
  followed by 30 days of read-only archive/receipt access.
- After that window, unnecessary profile data is deleted or pseudonymized while the
  encrypted accounting archive, filing receipts, and billing evidence enter a
  five-year read-only retention hold, subject to final legal review.

### Privacy, notifications, and portability

- Store and process accounting records/documents primarily in the EU/EEA.
- Do not send raw customer data to AI/OCR services without separate approval and
  disclosure. Necessary non-EEA processing requires documented safeguards.
- Do not use advertising trackers or cross-site analytics. Product analytics are
  first-party/privacy-minimized and exclude accounting figures, documents,
  organisation numbers, and personal identifiers.
- Send operational deadline and submission-status messages by default. Customers
  may disable non-critical reminders, but not security, payment, or filing-result
  notices. Marketing consent remains separate.
- A completed-year/account-closure archive contains human-readable PDFs, CSV ledger
  data, original documents, filing XML, authority feedback/receipts, and a
  machine-readable integrity manifest.

## Security threat model

### Assets

- Customer accounting records and private evidence objects.
- Authority credentials, filing permissions, and submitted payloads.
- Billing state and refunds.
- Corporate approvals and immutable audit evidence.
- Operator-only launch decisions.

### Trust boundaries and abuse cases

1. A browser-authenticated customer can write exposed `public` tables through the
   Data API. They must not be able to manufacture MFA, human security approval, or
   production-credential state.
2. A stale or AAL1 session must not execute a sensitive mutation even if a legacy
   `step_up_events` row exists.
3. A user must not reuse another user's signed claims or a future/expired MFA
   timestamp.
4. Operator launch signoffs must remain writable only by active admin operators.
5. A code deployment must not imply that production filing, payment, or paid access
   is enabled.

## Trusted AAL2 architecture

### Alternatives considered

1. Keep `step_up_events` and permit only a server/service-role writer. This removes
   direct customer writes but duplicates Supabase Auth state and risks stale or
   incorrectly minted records.
2. Use verified Supabase JWT claims for user presence and existing operator-only
   `launch_signoffs` for human/environment gates. This is the selected design.
3. Build a separate authentication/authorization service. This creates unnecessary
   key, session, deployment, and operational complexity for the current product.

### Selected boundary

- Verify server-side claims with `supabase.auth.getClaims()`.
- Require `sub` to match the authenticated user, `aal` to equal `aal2`, and the most
  recent MFA method in signed `amr` to be no older than 15 minutes or in the future.
- Database-sensitive RPCs use `auth.jwt()` with the same AAL2 and AMR-age rules.
- Revoke `authenticated` access to `step_up_events` and remove its customer policies.
  Retain the legacy table only as inaccessible historical data until a later
  migration safely removes it.
- Remove `security_review_approved` and `production_credentials_enabled` from the
  user step-up context. Security/restore, billing/refund, support/rollback, legal,
  authority, and final founder decisions are operator-only launch signoffs.
- Add a `founder_production_go_live` signoff. It starts missing/pending and may be
  approved only after the founder gives the final explicit confirmation requested
  in this design.
- Production adapter environment flags remain deny-by-default and are independent
  from deployment.

## Public beta posture

- The public homepage says “invite-only beta” and does not promise completed
  authority delivery, human review, accountant replacement, or live payment.
- Calls to action collect beta interest or allow invited users to sign in; they do
  not imply immediate production access.
- Legal pages identify ELMER WELFIS with org.nr. 930 835 978 and use the same support
  address. Placeholder legal entities and contact addresses are removed.
- Canonical launch-copy validation scans the rendered public-page source, not only a
  detached copy object.

## Error handling

- Invalid/missing claims fail closed with a stable user-safe error code and a prompt
  to complete MFA; raw JWTs and claims are never logged.
- Claims lookup failures are audited as blocked sensitive actions without exposing
  provider details.
- Missing/stale/rejected launch signoffs produce machine-readable release-gate
  reasons.
- Beta copy and runtime capability state remain conservative when configuration is
  absent or ambiguous.

## Test design

- Unit tests prove that AAL1, mismatched subject, missing AMR, stale AMR, and future
  AMR fail; fresh signed-claim-shaped input passes.
- App integration tests prove no `step_up_events` query is used and allowed/blocked
  audit events still persist.
- Migration tests prove authenticated select/insert grants and policies are revoked
  and corporate RPCs check signed AAL2/AMR claims.
- Live local Supabase tests prove a customer cannot insert a forged step-up row.
- Release-gate tests prove `security_restore` freshness and
  `founder_production_go_live` are required even when authority adapters are marked
  enabled.
- Launch-copy tests scan the public route/copy source for invite-only beta language,
  the legal operator, no human-review claim, and no live-payment/submission claim.
- Full launch rehearsal, production build, dependency audit, and whitespace checks
  remain mandatory before merge.

## Rollout and non-goals

- This slice does not enable production filing, Vipps, paid customers, bank feeds,
  OCR, BankID, or optional corporate-document templates.
- Apply the migration in a hosted staging target and exercise real TOTP enrollment,
  challenge, recovery, and the sensitive-action paths before production promotion.
- Merge and deploy code with all live flags off. A later, separately evidenced
  release records the final founder signoff and changes only the approved feature
  flags.

