# HoldingSwift Product Requirements Implementation Plan

Status: `phase-1-core-implemented; live-integrations-and-corporate-artifacts-gated`
Source: `docs/remarks/holdingswift_produktkrav.md`
Baseline audited: 2026-07-13

## Product decision

The HoldingSwift brief is the target product direction for Talli: a filing
assistant with a narrow ledger for simple, passive Norwegian holding AS
companies. It strengthens the existing holding-first positioning; it does not
turn Talli into a general accounting suite.

The existing Next.js, Supabase/PostgreSQL, and Python filing-engine architecture
remains the implementation baseline. The suggested FastAPI and BankID choices
in the brief are options, not a mandate to rewrite a working authenticated
application. A separate service is justified only when an authority adapter or
background job cannot safely live in the current boundaries.

## Non-negotiable boundaries

- No invoicing, VAT returns, payroll/a-melding, OTP, employer tax, inventory,
  logistics, time tracking, or project accounting.
- AI and OCR can create reviewable suggestions only. They cannot post ledger
  entries, approve corporate decisions, or submit filings.
- Unclear tax residence, non-EEA investments, derivatives, group
  contributions, multiple share classes, reorganisations, and other complex
  cases remain blocked or require accountant review.
- Posted entries and accepted filing evidence are immutable. Corrections use
  reversal/correction records with audit events.
- Every external callback, import, and authority write must be tenant-scoped,
  idempotent, auditable, and safe to retry.

## Authority corrections to the source brief

The product outcome is direct filing, but the implementation must follow each
authority's actual contract instead of assuming every interface is REST/JSON.

- RF-1086 uses XML documents validated against Skatteetaten XSDs. The official
  flow posts the main form, one or more subforms, and a confirmation, using the
  `skatteetaten:innrapporteringaksjonaerregisteroppgave` scope and idempotency
  UUIDs.
- The company tax return uses Skatteetaten's published schemas and validation
  feedback before submission. Maskinporten/system-user access does not replace
  any required owner review or signing step.
- Annual accounts use the Regnskapsregisteret/Altinn 3 instance flow. A system
  user can prepare the instance, but current official guidance requires a
  person authenticated through ID-porten to sign before submission.
- Production stays disabled until a successful test-environment run, feedback
  retrieval, receipt/archive evidence, and dated human approval are recorded
  for the specific obligation.

Primary references:

- Skatteetaten RF-1086 API:
  <https://skatteetaten.github.io/api-dokumentasjon/en/api/innrapportering-aksjonaerregisteroppgave>
- Skatteetaten test environments:
  <https://skatteetaten.github.io/api-dokumentasjon/en/test/testmiljo>
- Skatteetaten company tax return API:
  <https://skatteetaten.github.io/api-dokumentasjon/api/innrapportering-skattemelding>
- Regnskapsregisteret machine reporting:
  <https://brreg.github.io/docs/apidokumentasjon/regnskapsregisteret/maskinell-innrapportering/hvordan-sende-inn/>
- Altinn system integration setup:
  <https://docs.altinn.studio/en/altinn-studio/v8/guides/integration/sbs/setup/>

## Requirement-to-evidence matrix

| Requirement | Implementation evidence | Remaining gate / next acceptance test |
| --- | --- | --- |
| Passive holding AS scope | ADR-0001, ADR-0006, onboarding support boundary | Keep exclusions enforced in onboarding, actions, readiness, and marketing copy. |
| 5–25 bank transactions | CSV import, duplicate hash, persisted bank transactions, reconciliation, deterministic suggestion engine, atomic acceptance RPC, and disabled provider-neutral consent/sync port | A live aggregator requires provider, security, consent, retention, and data-processing decisions plus sandbox evidence. |
| Known transaction rules | Versioned rules `2026-07-13.1` produce 7770/1920, 6700/1920, and 1920/8050 drafts; ambiguous text/direction fails closed; an owner must accept atomically | Run the same acceptance suite against the deployed Supabase project before release. |
| PDF evidence | Private Supabase storage, tenant-scoped upload/download, PDF signature/MIME/name and 10 MB validation, quarantined extraction contract, and review-only field normaliser | Persist provider job transitions after vendor approval; OCR provider remains disabled until approved. |
| Acquisition-cost register | Persisted investment positions plus immutable acquisition lots and sale allocations; atomic writes reconcile lot totals to position and ledger | Existing positions marked `needs_reconstruction` require an owner-reviewed opening-lot workflow before sale. |
| `fritaksmetoden` | 3% dividend add-back and supported-treatment gates | Keep qualifying dividends/gains separate; add explicit unsupported/taxable treatment boundaries rather than guessing non-EEA treatment. |
| FIFO disposal | Deterministic FIFO is implemented in Python, TypeScript, and PostgreSQL with stable lot ordering, exact residual cost, atomic locks, action/ledger/audit consistency, and retry idempotency | Run deployed Supabase concurrency and tenant-isolation tests with project credentials. |
| Board/GM documents | Dividend checks and placeholder text records | Generate actual versioned PDF content from reviewed facts; store hash, template version, approval state, and signature state. |
| Owner dividend | Free-equity and liquidity checks exist | Reconcile the brief's proposed accounts with the approved chart/accounting policy before changing postings; generate the GM decision from the same immutable facts. |
| RF-1086 | XSD-backed generator, readiness gate, Maskinporten system-user client, idempotent Skatteetaten transport/journal, accepted TT02 no-activity submission, archive retrieval, and machine-checked evidence | Record the evidence in the deployed runtime gate, complete production credential/security/restore review, and obtain dated `rf1086_authority` approval before enabling. |
| Company tax return | Deterministic payload/XML, three official 2025 XSD checks, test-only Skatteetaten/Altinn transport client, TT02 `validertOK` evidence, and the two Altinn instance scopes; reconciliation handles supported admin costs, interest, exempt dividends/gains, non-deductible losses, and 3% inclusion | Connect the transport to persisted filing state, complete TT02 instance/upload plus personal signing handoff and receipt/archive, and obtain dated approval. |
| Annual accounts | Deterministic result/balance field model, corrected financial income/cost treatment, test-only Altinn create/upload/validate/lock/person-signing-handoff client, required Altinn instance scopes, and fail-closed production gate | Complete the RR0002 XML renderer, add `app_brg_aarsregnskap` to a TT02 system user, validate the complete payload and hybrid signing flow in TT02, implement receipt polling, and record dated approval. |
| Low-cost architecture | Next.js 16, Supabase/PostgreSQL, Python core | Add background jobs only for consent refresh, extraction, and authority polling; measure before adding another service. |
| BankID login | Existing Supabase authentication | New authentication flow and vendor contract require a separate security/identity decision; do not add implicitly. |
| NOK 990 example price | Existing founder/standard subscription plus filing package | Commercial decision required. Do not silently replace the approved billing model. |

## Delivery order

### 1. FIFO investment lots

Introduce immutable acquisition lots and explicit sale allocations. Existing
positions without trustworthy lot history are not silently converted: they are
marked `needs_lot_reconstruction` and blocked from FIFO sale until the owner
reconstructs opening lots. A purchase creates a lot; a sale consumes oldest
available lots by acquisition date and stable creation order.

Acceptance:

- two lots with different unit costs produce the expected FIFO cost basis;
- a partial lot remains with the exact residual quantity and cost;
- retrying the same action cannot consume a lot twice;
- oversale, negative values, future lot dates, missing lots, and cross-company
  lot references are rejected;
- position quantity/cost equals the sum of remaining lots after every write;
- ledger lines, action payload, movement record, and audit record use the same
  computed allocation.

### 2. Deterministic transaction suggestions

Add a pure rule engine that normalizes Norwegian text and uses amount direction
to return a suggestion, confidence reason, rule version, and balanced draft
lines. Suggestions are never accepted automatically.

Acceptance:

- bank/annual fee, supported system subscription, and interest fixtures map to
  the accounts in the brief;
- ambiguous text returns no suggestion;
- an incoming interest rule cannot match an outgoing payment;
- persisted acceptance records the rule version and owner identity.

### 3. Provider-neutral external seams

Define bank-consent/sync and document-extraction ports with disabled production
adapters, redacted observability, replay-safe webhooks, explicit consent expiry,
and per-company cursors. Select and contract with providers before sending real
customer or document data.

### 4. Corporate document artifacts

Generate deterministic, versioned PDFs for the supported annual approval and
owner-dividend cases. The generated record must include input hash, template
version, authorising decision, and signature status; signed files are immutable.

### 5. Authority adapters and release gates

Implement each obligation independently behind its own test-evidence and human
approval gate. A successful HTTP response is not a filing receipt. Persist the
request journal, authority identifiers, validation feedback, status history,
documents, and final receipt.

### 6. Production verification

Run tenant-isolation tests, authorization tests, secret scans, dependency audit,
backup/restore rehearsal, archive/cancellation tests, supported-case filing
rehearsals, accessibility/browser checks, and the full build. Claims of direct
filing remain disabled until the external authority evidence and legal/security
sign-offs are complete.

## Threat model for the new work

- **Assets:** company identity, bank transactions, accounting documents,
  investment lots, filings, tokens, receipts, signatures, and audit history.
- **Trust boundaries:** browser/server actions, Supabase RLS, object storage,
  bank/OCR callbacks, Maskinporten/Altinn/Skatteetaten, and operator access.
- **Primary risks:** cross-tenant reads/writes, replayed callbacks, duplicate
  postings, stale consent, prompt/document injection, malicious PDFs, secret or
  token disclosure, concurrent sale oversubscription, incorrect lot migration,
  and misleading submission state.
- **Controls:** server-side membership checks plus RLS, database transactions and
  unique idempotency keys, immutable lots/receipts, content-type and size limits,
  malware quarantine, extraction-as-untrusted-data, least-privilege scopes,
  redacted logs, encrypted secrets, explicit step-up/review, and fail-closed
  production gates.

## External decisions that cannot be inferred

These decisions do not block deterministic local work, but they block the
corresponding live integration:

1. Open Banking aggregator, commercial terms, consent model, and DPA.
2. OCR/document extraction provider, processing region, retention, and DPA.
3. Whether BankID is required in addition to the existing authentication path.
4. Final account-policy approval for owner dividends and taxable/non-EEA cases.
5. Final commercial model (current subscription/filing package versus the NOK
   990 example).
6. Dated authority test evidence and human production approval for all three
   filing obligations.

## Verification evidence (2026-07-13)

- `TALLI_SKATTE_XSD_DIR=<official-skattemeldingen-repository>/src/resources/xsd npm run test:launch-rehearsal` passed, including validation of both generated company-tax-return documents with official Skatteetaten XSDs.
- `uv run python -m unittest discover -s tests -p 'test_*.py'` passed 61 tests.
- `npm run typecheck`, `npm run build`, and `npm audit --omit=dev` passed; the audit reported zero known production dependency vulnerabilities.
- Migrations `0001`, `0002`, and `0003` applied to a fresh PostgreSQL 17 database with Supabase auth/storage stubs.
- The clean-database runtime rehearsal purchased 100 shares for NOK 10,000 and 100 for NOK 30,000, then sold 150 for NOK 30,000. FIFO allocated NOK 25,000 cost, recorded NOK 5,000 gain with `fritaksmetoden`, and retained 50 shares/NOK 15,000. Retrying the sale was idempotent.
- The same database rehearsal accepted a `system_subscription` suggestion once as the owner, produced 6700/1920 lines, linked the bank transaction, retained rule version `2026-07-13.1`, and returned idempotently on retry.
- The full authenticated Supabase integration suite remains unexecuted in this environment because project URL, keys, and database URL were not supplied. This is a release gate, not evidence of a pass.
