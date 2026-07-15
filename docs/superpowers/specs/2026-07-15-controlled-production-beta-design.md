# Controlled production beta design

Status: approved by Kristian Elmer on 2026-07-15
Decision owner: Kristian Elmer
Legal beta operator: ELMER WELFIS, org.nr. 930 835 978
Delivery branch: `codex/controlled-production-beta`

## Objective

Let a small, named group of beta customers prepare, review, approve, and make
real statutory filings through Talli while keeping every production transport
deny-by-default. The pilot must test both Talli's deterministic filing output and
the complete authority journey, including delegation, signing where required,
official receipt, final outcome, correction, support, and rollback.

This is a production pilot with legal consequences, not a TT02 usability test.
Calling it beta does not reduce Talli's obligations as a supplier of a
sluttbrukersystem.

## Existing decisions carried forward

This design narrows and operationalizes the approved customer-ready foundation:

- Invite-only beta; the founder admits each customer.
- Customers use their own real company data only in production. TT02 continues
  to use synthetic Tenor data only.
- The customer reviews the exact output and explicitly authorizes every filing.
- Only a verified owner may approve or submit. Adviser access remains read-only
  and commenting-only.
- Unsupported or uncertain cases are blocked rather than estimated.
- Production filing is enabled independently for RF-1086, company tax, and
  annual accounts.
- Live payment is not required for the free production pilot and remains off.
- The public product remains truthful about the currently enabled filing types.
- The founder may bypass a professional-review recommendation only through the
  existing named risk-acceptance mechanism. Authority access, tenant isolation,
  signed AAL2, production credentials, and final authority gates remain
  non-bypassable.

## Approaches considered

### 1. Enable all three filing transports for all beta customers

This maximizes feedback speed but couples three different authority protocols,
signature journeys, and failure modes to one launch event. A defect or missing
receipt path in one obligation would expose every pilot customer. Rejected.

### 2. Let customers export files and complete all submissions elsewhere

This safely tests calculation and presentation, but it does not test Talli's
production authentication, transport, signing handoff, receipt, final-outcome,
or correction paths. It is also not a viable RF-1086 end state because
Skatteetaten requires filing through a sluttbrukersystem. Retained only as a
fallback where an authority explicitly supports manual completion.

### 3. Staged production pilot per obligation

Selected. Admit named companies to a pilot cohort, then activate one obligation
at a time behind its own entitlement, release gate, adapter flag, monitoring,
and kill switch. Start with the narrow supported RF-1086 path. Add company tax
and annual accounts only after their personal signing handoffs and final outcome
loops are proven.

## Product language

The beta UI may say that a filing is real only when all server-side production
gates for that company, income year, user, and obligation pass.

Use these states:

- `Forhåndsvisning`: generated output; nothing sent.
- `Klar til gjennomgang`: deterministic checks pass; owner review remains.
- `Godkjent av deg`: immutable payload snapshot approved; nothing sent yet.
- `Sender`: an idempotent authority operation is in progress.
- `Mottatt`: the authority acknowledged transport, but has not accepted content.
- `Venter på signering`: the authority requires the owner to sign/submit through
  ID-porten.
- `Til behandling`: the authority has the signed/submitted filing and final
  processing remains open.
- `Godkjent`: official final feedback classifies the filing as accepted.
- `Avvist` or `Må rettes`: official feedback requires correction.

Never equate a local approval, HTTP success, Altinn instance, dialog reference,
or receipt reference with final authority acceptance.

## Pilot entitlement model

Beta admission and production filing permission are separate concepts.

Add a server-managed production-pilot entitlement for one:

- company;
- verified owner user;
- income year;
- obligation;
- supported-case profile;
- activation and expiry interval.

An entitlement records its approving operator, evidence/signoff reference, and
status: `pending`, `active`, `suspended`, `completed`, or `revoked`. Only an
active admin operator may activate it. Customers cannot create, widen, or extend
their own entitlement.

An active entitlement never overrides:

- filing readiness or supported-case blockers;
- current owner membership and company identity;
- fresh signed AAL2/AMR;
- customer authority/delegation;
- production adapter capability;
- current obligation-specific launch signoffs;
- environment and credential checks;
- the global or obligation-specific kill switch.

## Immutable owner approval

Before the final action Talli renders a production review containing:

- company and organization number;
- income year and obligation;
- supported-case boundary and unresolved warnings;
- human-readable filing values;
- the exact authority documents available for inspection/download;
- payload hashes and the time the snapshot was created;
- a prominent statement that the action creates a real filing;
- the expected authority journey and correction consequences.

Approval requires fresh AAL2 and creates an immutable approval record bound to
the company, user, obligation, income year, payload hashes, adapter version, and
supported-case decision. Any data or adapter change invalidates the approval and
requires a new review.

The approval action and authority-send action remain distinct. This makes it
possible to prove exactly what the customer saw and authorized without implying
that approval alone completed a filing.

## Authority journeys

### RF-1086

RF-1086 is the first production-pilot candidate because Talli already has the
production transport implementation and accepted TT02 no-activity evidence.

After owner approval, the server uses the delegated Systembruker to:

1. post the hovedskjema with a persisted unique idempotency key;
2. post every underskjema with its own persisted unique key;
3. confirm the complete forsendelse;
4. poll and archive authority documents and feedback;
5. classify the official outcome without losing raw evidence.

The initial pilot supports only the exact no-activity/stiftelse scope evidenced
in TT02. Purchase, sale, dividend, foreign-shareholder, multiple-share-class,
and correction cases stay blocked until separate authority evidence and a scope
decision exist. This scope is intentionally narrower than the eventual paid
product.

### Company tax return

Talli may validate, create the Altinn instance, and upload the approved company
tax and business-specification documents with Systembruker. It must then stop at
the documented confirmation boundary and hand the owner to the Skatteetaten/
Altinn ID-porten journey. Server code must not perform the person's final
signature transition.

The production pilot is limited to the existing deterministic no-attachment
case boundary. Talli resumes read-only after return to retrieve the official
feedback and archive references. Production activation waits for implemented
adapter orchestration, explicit authority confirmation of the handoff, accepted
and rejected outcome fixtures, and a controlled pilot procedure.

### Annual accounts

Talli may create the Altinn instance, upload the main form, accounts data, and
supported attachments, and lock the immutable instance for signing. The owner
then signs and submits through ID-porten. Talli resumes read-only to retrieve the
Regnskapsregisteret decision.

The initial scope is a small, non-audit Norwegian holding AS using the exact
supported schema and attachment boundary. Activation waits for final TT02
outcome classification, tested return/resume behavior, and production adapter
orchestration.

## Submission journal and idempotency

Every production submission uses a durable append-only operation journal. Before
each external mutation Talli stores:

- stable submission and operation identifiers;
- obligation, company, income year, and approved payload hash;
- adapter version and production environment;
- endpoint operation name, not secrets or raw access tokens;
- idempotency key where supported;
- attempt number and timestamps;
- sanitized authority reference or sanitized failure class.

Retries resume from the journal. A browser retry, process restart, timeout, or
double click must not create a second filing. Unknown outcomes are quarantined
for read-only reconciliation; Talli does not retry a potentially completed
mutation until the authority state is checked.

## Outcomes, correction, and evidence

For every obligation Talli stores an immutable evidence package containing:

- the owner-approved human-readable snapshot;
- exact submitted payloads and SHA-256 hashes;
- authority submission/instance/dialog references;
- official receipts and feedback documents;
- normalized status transitions with original timestamps;
- user, operator, adapter, and release-SHA audit metadata.

Raw authority feedback is preserved privately. The UI shows a safe normalized
summary and gives access to the original receipt where appropriate.

The pilot must support an honest correction path before an obligation is widened
beyond the founder's hand-held cohort. Corrections create a new version linked to
the prior filing; they never overwrite the original approval or evidence.

## Security and privacy

- Production keys are separate from `~/talli-test.key` and TT02 material.
- Private keys live only in managed production secret storage and are never
  returned to the browser, database rows, logs, or evidence archives.
- Every sensitive server action re-verifies signed Supabase claims, fresh AAL2,
  owner membership, tenant identity, and entitlement.
- Production endpoints and tokens have no TT02 fallback.
- Logs contain correlation IDs and sanitized error classes, not payloads,
  organization numbers, personal identifiers, tokens, or private documents.
- The beta customer agreement and data-processing agreement explicitly cover
  real filing, customer responsibility for review, incident handling, support,
  and correction.
- The existing time-limited audited support-session boundary applies. Operators
  cannot inspect customer accounting data merely because the company is in the
  pilot.

## Monitoring, support, and rollback

Each obligation has an independently controlled kill switch. Disabling transport
must preserve customer drafts, approvals, journals, and authority evidence.

Alerts cover:

- repeated authentication or delegation failures;
- idempotency conflicts or duplicate-risk states;
- submissions stuck in `sender`, `venter på signering`, or `til behandling`;
- receipt/feedback retrieval failures;
- authority rejection or schema-error spikes;
- any attempt to use a test endpoint or test credential in production.

The first RF-1086 production submission is founder-assisted and observed from
approval through final feedback. Do not use a statutory filing as a connectivity
probe. A prepared rollback and alternative filing/support route must be recorded
before the customer presses Send.

## Rollout sequence

### Phase 0 — shared production-pilot foundation

- Add server-managed pilot entitlements and audit trail.
- Add immutable production approval snapshots.
- Generalize the durable submission journal and normalized outcome model.
- Add obligation-specific flags and kill switches.
- Finish hosted MFA, tenant-isolation, restore, legal/DPA, support, monitoring,
  and production-secret evidence.
- Keep every production adapter disabled.

### Phase 1 — RF-1086 controlled pilot

- Obtain Skatteetaten production scope and accept current SBS terms.
- Register the production system/client and obtain customer delegation.
- Activate only the TT02-evidenced no-activity/stiftelse case.
- Run one founder-assisted filing, retrieve final feedback, archive evidence,
  and rehearse rollback.
- Admit at most three named RF-1086 pilot companies after the first accepted run.

### Phase 2 — company-tax controlled pilot

- Complete the no-attachment production adapter and signing handoff.
- Prove accepted, rejected, return, resume, and correction behavior.
- Run one founder-assisted filing, then admit a small named cohort.

### Phase 3 — annual-accounts controlled pilot

- Complete outcome classification and production adapter orchestration.
- Prove signing handoff, accepted/rejected outcomes, return, and correction.
- Run one founder-assisted filing, then admit a small named cohort.

### Phase 4 — scope widening

- Add RF-1086 purchase, sale, and dividend cases only after separate TT02 and
  authority evidence.
- Add other supported company-tax or annual-account cases only as separate,
  reviewable scope decisions.
- Keep payment disabled until the independent live charge/refund gate passes.

## Test strategy

### Unit and contract tests

- Pilot entitlement cannot bypass any existing release gate.
- Approval hashes are deterministic and invalidated by any relevant change.
- Production state transitions reject illegal transitions and never infer
  acceptance from transport success.
- Journal retries are idempotent and quarantine unknown outcomes.
- Test credentials/endpoints cannot be selected in production.

### Database and security tests

- Customers cannot create or mutate pilot entitlements, signoffs, adapter flags,
  or normalized authority outcomes.
- Owner, adviser, outsider, and operator policies match the approved access model.
- Fresh AAL2 is required both in server code and sensitive database boundaries.
- Cross-tenant reads, approvals, sends, receipts, and archives fail.

### Authority adapter tests

- Exact official request/response fixtures for success, validation rejection,
  timeout, ambiguous outcome, signing return, final acceptance, and correction.
- TT02 rehearsals with synthetic data only.
- One monitored production pilot per obligation before cohort expansion.

### Browser tests

- Review → approve → send/handoff → return → receipt → final result.
- Double-click, refresh, session expiry, delegation loss, kill switch, and
  unsupported-case behavior.
- Production warnings, status language, receipt access, and support guidance on
  desktop and mobile Safari/Chrome.

## Release gates

An obligation can enter the production beta only when all of these are current
for the deployed SHA:

1. production API access, client, scope/resource, and Systembruker delegation;
2. current authority/SBS terms and customer agreements;
3. supported-case TT02 evidence with accepted and rejected outcomes;
4. production-only key, secret storage, rotation, and revocation evidence;
5. deployed tenant-isolation, AAL2, backup/restore, monitoring, and rollback;
6. implemented production adapter and tested kill switch;
7. immutable owner review/approval and idempotent journal;
8. receipt, final outcome, archive, and correction behavior;
9. named authority and security signoffs;
10. active company/user/year/obligation pilot entitlement;
11. explicit founder approval for that obligation's first production run.

The global `founder_production_go_live` signoff remains required. It does not
enable all obligations; each obligation still needs its own authority signoff,
adapter flag, and pilot entitlement.

## Success criteria

- A named owner can see exactly what will be filed and knowingly authorize it.
- Talli either blocks the case with a useful reason or completes the documented
  authority journey without a duplicate submission.
- Talli displays the official final outcome and preserves a complete evidence
  package.
- A transport can be disabled immediately without losing customer or authority
  state.
- No public or in-product claim exceeds the exact obligations and case profiles
  currently enabled.
- The first accepted production filing and one correction/rejection rehearsal
  are reviewed before exposure grows.

## Non-goals

- Public self-service production filing.
- Enabling all obligations with one feature flag.
- Automatic submission without an owner reviewing the exact output.
- Letting a beta disclaimer bypass a release, security, or authority gate.
- Paid beta, live Vipps charging, bank feeds, OCR, or BankID login.
- Supporting uncertain tax treatment, attachments outside the explicit boundary,
  audited/group accounts, payroll, VAT, or foreign business activity.

## Official references

- Skatteetaten SBS terms:
  <https://www.skatteetaten.no/samarbeidspartnere/sluttbrukersystemer/bruksvilkar/>
- RF-1086 reporting API:
  <https://skatteetaten.github.io/api-dokumentasjon/api/innrapportering-aksjonaerregisteroppgave>
- RF-1086 filing requirement:
  <https://www.skatteetaten.no/bedrift-og-organisasjon/rapportering-og-bransjer/aksjonarregisteroppgaven/>
- Company-tax filing guidance:
  <https://www.skatteetaten.no/bedrift-og-organisasjon/utenlandsk/skattemelding-og-skatteoppgjor/skattemelding-as/>
- Annual-accounts filing guidance:
  <https://www.brreg.no/innsending-av-arsregnskap/>
