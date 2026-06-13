# Plan: Talli

Research date: 2026-06-12  
Planning status: consolidated after grilling session  
Scope: a low-cost, Norwegian-first filing assistant with a narrow ledger for simple Norwegian holding companies (`AS`).
Working brand: Talli (`talli.no` secured).

This is a product and engineering plan, not legal, tax, or accounting advice. Before production filing is enabled, filing models, validation rules, and authority payloads must be reviewed against official specifications and tested through official or equivalent validation flows.

## 1. Product Thesis

The product should not be a generic Fiken clone. Fiken is broad: bookkeeping, invoicing, purchases, VAT, payroll, bank integration, tax return, annual accounts, shareholder reporting, assets, debt, securities, API, accountant workflows, and more.

The opportunity is narrower:

**File the annual reports for a simple Norwegian holding AS directly from the app, for far less than Fiken, without exposing the user to operating-company clutter.**

The product category is a **filing assistant with a narrow ledger**:

- It has a real double-entry ledger.
- The ledger only supports the holding actions needed for annual holding compliance.
- It directly files the obligations it owns.
- It blocks, warns, or escalates unsupported cases.
- It does not try to be a full accounting system for every SME workflow.

## 2. Launch Promise

Public launch promise:

**“File the annual reports for a simple Norwegian holding AS directly from the app.”**

Included direct filings:

1. `Aksjonærregisteroppgaven`
2. `Årsregnskap`
3. `Skattemelding for AS`

Launch scope is only:

- Simple Norwegian holding AS.
- No VAT.
- No payroll, board fees, or employee benefits.
- No customer invoicing.
- No complex share events.
- No foreign or unclear tax cases.
- Owner-managed direct filing.

Unsupported cases are blocked or escalated with a plain explanation.

## 3. Target User and First Scenario

Primary user:

- Owner of a Norwegian holding AS.
- Wants to avoid paying for a broad accounting suite.
- Has limited accounting knowledge.
- Wants the app to handle the annual compliance loop.

First target scenario:

- One Norwegian holding AS.
- One bank account.
- Few yearly transactions.
- Investments in one or more companies or simple securities.
- Dividends received.
- Basic bank/accounting/admin costs.
- No VAT.
- No payroll.
- No customer invoicing.
- Owner files directly from the app.

Also support a no-activity year as a first-class path:

- Opening balances exist.
- No bank movements.
- No dividends.
- No share changes.
- No costs.
- Annual filing still required.

The app should verify opening/closing balances, confirm shareholder register unchanged, confirm no dividends/loans/share events, generate filings, and store the user's confirmations.

Secondary users later:

- Accountants managing many simple holding companies.
- Advisors reviewing filings.
- Owners with multiple companies.

The data model should support multiple companies per user from day one, but the first UX should be single-company-first.

## 4. Brand Posture

The working brand is **Talli**. The brand should be boring, official, and cheap. The product handles statutory filings, so trust matters more than personality.

Brand rules:

- Norwegian-first.
- Plain explanations.
- Clear prices.
- Clear deadlines.
- No "AI accountant" positioning.
- No playful compliance language.
- No broad accounting-suite claims.
- Visual tone closer to Altinn/Fiken simplicity than fintech flash.

Talli should explicitly say what it is not. Talli is not:

- A full accounting system.
- A replacement for an accountant in complex cases.
- Payroll software.
- VAT software at launch.
- Invoice software.
- Investment advice.
- Legal advice.
- Tax advice for foreign or complex structures.

Positioning line candidate:

**Talli: Årsrapportering for holdingselskap, uten regnskapssystemet du ikke trenger.**

## 5. Research Summary

### Norwegian AS Obligations

Private limited companies are subject to accounting obligations and must submit annual accounts every year. Commercial activity normally also triggers bookkeeping obligations and documentation retention requirements. Sources: [Altinn: Private limited companies](https://info.altinn.no/en/start-and-run-business/planning-starting/choosing-legal-structure/private-limited-companies/) and [Altinn: Accounting system](https://info.altinn.no/en/start-and-run-business/accounts-and-auditing/accounting/accounting-system/).

Accounting systems must be systematic, transparent, and able to produce required reports. Practical implications:

- Traceable ledger.
- Voucher/source-document trail.
- Period locking.
- Correction entries instead of silent edits.
- Required reports and exports.

Primary accounting documentation generally must be retained for 5 years, and secondary documentation for 3.5 years. Balance documentation must also be retained for 5 years. Sources: [Altinn: Voucher requirements](https://info.altinn.no/en/start-and-run-business/accounts-and-auditing/accounting/requirements-concerning-vouchers/) and [Altinn: Balance documentation](https://info.altinn.no/en/start-and-run-business/accounts-and-auditing/accounting/documentation-of-the-balance-reconciliation/).

### Annual Filing Loop

The first direct-filing scope is the annual holding compliance loop:

- 31 January: `aksjonærregisteroppgaven`.
- 31 May: `skattemelding for AS`.
- 31 July: `årsregnskap` to Brønnøysundregistrene.

Sources:

- [Skatteetaten: Aksjonærregisteroppgaven](https://www.skatteetaten.no/skjema/rf-1086-aksjonarregisteroppgaven/)
- [Skatteetaten: Skattemelding for selskap](https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/selskap/)
- [Brønnøysundregistrene: Innsending av årsregnskap](https://www.brreg.no/innsending-av-arsregnskap/)
- [Altinn: Annual accounts RR-0002](https://info.altinn.no/en/forms-overview/bronnoysund-register-centre/annual-accounts/)

VAT and a-melding are module-specific filings, not part of the first regular-holding-company promise. Sources: [Skatteetaten: Mva-melding](https://www.skatteetaten.no/bedrift-og-organisasjon/avgifter/mva/mva-melding/), [Altinn: A-melding](https://info.altinn.no/en/start-and-run-business/working-conditions/pay/a-melding/).

### Holding-Company Tax

The core holding-company tax workflow is `fritaksmetoden`. Skatteetaten explains that private limited companies are not taxed on qualifying share gains, and only 3% of dividends received is taxable income. Sources: [Skatteetaten: Tax exemption method](https://www.skatteetaten.no/en/business-and-organisation/tax-for-businesses/tax-return/deductions/shares-and-securities/the-tax-exemption-method/) and [Skatteetaten: Fritaksmetoden](https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/fradrag/aksjer/fritaksmetoden/).

For qualifying dividends, Skatteetaten notes that 3% is income-recognized, corresponding to 0.66% tax at a 22% corporate tax rate: [Skatteetaten: Aksjer i næring](https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/fradrag/aksjer/aksjer-i-naring-selskapets-aksjer/).

Shareholder loans are a major risk area. Loans, credit, or security from an AS to a personal shareholder or related party can be taxed as dividends. Sources: [Skatteetaten: Skattepliktig lån til personlig aksjonær](https://www.skatteetaten.no/person/skatt/hjelp-til-riktig-skatt/aksjer-og-verdipapirer/om/lan-til-personlig-aksjonar/) and [Skatteetaten: Beskatning av aksjonærlån](https://www.skatteetaten.no/bedrift-og-organisasjon/starte-og-drive/rutiner-regnskap-og-kassasystem/lonn-lan-og-utbytte/lan-til-aksjonar/skattepliktig-lan-til-personlig-aksjonar/sporsmal-og-svar---lan-fra-selskap/).

### Fiken Benchmark

Fiken’s public pricing and product surface provide the baseline:

- Base accounting: NOK 209/month excl. VAT.
- Bank connection: NOK 59/month.
- API: NOK 99/month.
- Payroll: from NOK 79/month plus NOK 39/month per extra employee.
- AS tax return: NOK 1,490/year, with annual accounts and shareholder register statement included.

Sources: [Fiken pricing](https://fiken.no/priser), [Fiken integrations](https://fiken.no/integrasjoner), [Fiken API docs](https://api.fiken.no/api/v2/docs/), [Fiken accountant course outline](https://kurs.fiken.no/courses/Fikens-sertifiseringskurs-for-regnskapsforere).

The competitive advantage is not “same as Fiken, cheaper.” It is:

**Less scope, clearer holding-company workflow, much lower price.**

## 6. Product Scope

### Core Holding Actions

The first product should support these holding actions:

1. Opening balance / new-year start.
2. Manual transaction entry.
3. Bank CSV import.
4. Bank reconciliation.
5. Buy shares or make capital contribution.
6. Sell shares or realize gain/loss.
7. Receive dividend.
8. Declare/pay dividend to owner.
9. Record shareholder or intercompany loan.
10. Book bank/accounting/admin costs.
11. Prepare and file annual holding compliance loop.

### Company Identity

Company setup should be organization-number-first:

- User enters Norwegian organization number.
- App fetches company name, organization form, address, and status from Brønnøysund where available.
- App verifies the company is an `AS`.
- Non-AS entities are blocked for launch, including ENK, NUF, DA, ASA, and stiftelser.
- User confirms they are authorized to file for the company.
- Company identity fields used in filings are locked or require explicit confirmation if edited.

Launch onboarding should support new-year start only, not mid-year migration.

Required onboarding data for an existing company:

- Accounting year start date.
- Opening bank balance.
- Opening investment balances.
- Share capital and shareholder register opening position.
- Loans to/from owner or related companies.
- Prior year annual accounts upload.
- Prior year closing balance / opening balance confirmation.

Mid-year onboarding is deferred because it increases reconciliation complexity and reduces filing confidence.

Launch should also support simple newly founded AS setup:

- Cash share capital.
- One share class.
- Norwegian shareholders.
- Simple founding/share setup.

Unsupported first:

- Non-cash contribution.
- Multiple share classes.
- Foreign founder.
- Complex formation costs.

Talli should start after incorporation. Launch requires an existing organization number and does not support creating/registering a new AS. Company formation can be a partner/referral workflow later.

Onboarding should include Altinn/authority permission guidance:

- Explain which role/access the user likely needs to submit for the AS.
- Help the user verify they can submit for the company.
- Show clear authorization failure messages.
- Explain the next step in Altinn when authorization fails.

Talli should not promise to solve ownership, role, or authorization disputes.

### Narrow Ledger Surface

The narrow ledger supports only the accounts/posting flows needed for:

- Opening balance.
- Bank balance.
- Share investments.
- Simple listed securities.
- Dividends received.
- Admin/accounting/bank costs.
- Tax payable/refundable.
- Share capital/equity.
- Dividends declared to owners.
- Shareholder/intercompany loans.
- Annual result allocation.

Not first product:

- General supplier ledger.
- General customer ledger.
- Invoice receivables.
- Trade payables.
- Inventory.
- Projects.
- Time tracking.
- Payroll.

SAF-T export is not required at public launch, but the ledger data model must be compatible with adding SAF-T later. Store enough structured account, voucher, journal, party, and period data to avoid a painful redesign.

Posting immutability:

- Draft entries can be edited/deleted.
- Posted entries are immutable.
- Corrections are new reversal/correction entries.
- Filing data derives only from posted entries plus approved structured records.
- Audit log records all state changes.

### Cost Workflow

Launch supports paid admin costs only:

- Bank fee.
- Accounting fee.
- Software/subscription fee.
- Brønnøysund/public fee.
- Legal/advisory fee.
- Other admin cost.

Required input:

- Date.
- Amount.
- Supplier/payee text.
- Category.
- Document optional/required depending amount and filing readiness policy.
- Paid from bank.

Unsupported first:

- Unpaid supplier invoices.
- Accounts payable.
- Partial payments.
- Foreign currency bills.
- VAT deduction.

### Investment Register

Supported:

- Private company shares.
- Simple listed shares/funds manually maintained.
- Cost basis.
- Ownership percentage.
- Dividend events.
- Disposal events.
- Clear tax treatment classification.

Not supported first:

- Broker import.
- High-volume trading.
- Derivatives.
- FX-heavy portfolios.
- Daily market values.
- Tax optimization.

### Dividend Received Workflow

Launch supports dividends received from Norwegian AS holdings where `fritaksmetoden` qualification is clear.

Required input:

- Paying company organization number/name.
- Date declared.
- Date paid.
- Gross dividend.
- Linked investment.
- Bank transaction match.
- Documentation upload.

App calculates:

- Accounting entry.
- 3% taxable add-back where applicable.
- Estimated tax effect.
- Tax-return mapping.

Unsupported first:

- Foreign withholding tax.
- Unclear EEA/non-EEA qualification.
- Fund distributions with complex tax treatment.
- Dividend receivable not yet paid.

### Dividend to Owner Workflow

Launch supports simple cash dividend from the holding AS to shareholders.

Required input and checks:

- Available equity / distributable amount check.
- Proposed dividend amount.
- Shareholder allocation by share ownership.
- Board proposal template.
- General meeting resolution template.
- Payment date.
- Bank transaction match.
- Shareholder register effect.
- Annual accounts and tax mapping.

Unsupported first:

- Non-cash dividend.
- Unequal dividend across the same share class.
- Foreign shareholder withholding cases.
- Dividend where available-equity or liquidity checks fail.
- Complex extraordinary dividend cases until safely modelled.

Sources to preserve in implementation research: Altinn states that the ordinary general meeting approves annual accounts and decides dividends based on the board's proposal, and Altinn/Brønnøysund describe the general meeting as the company body that approves annual accounts and dividends. Altinn also notes that dividend must be considered against prudent equity and liquidity requirements.

### Share Purchase Workflow

Launch supports simple purchase of shares by the holding company.

Required input:

- Investment company organization number/name where available.
- Acquisition date.
- Number of shares or ownership percentage.
- Purchase amount / cost basis.
- Payment date.
- Bank transaction match.
- Purchase agreement or documentation upload.
- Tax classification: clearly within `fritaksmetoden`, clearly outside, or needs-accountant.

Unsupported first:

- Earn-outs.
- Seller credits.
- Multi-currency purchases.
- Step acquisitions with control/accounting complexity.
- Non-cash consideration.
- Complex fund/security tax classification.

### Share Sale Workflow

Launch supports simple sale of shares by the holding company.

Required input:

- Linked investment.
- Sale date.
- Number of shares or percentage sold.
- Sale proceeds.
- Cost basis allocation.
- Bank transaction match.
- Sale agreement or documentation upload.
- Gain/loss calculation.
- Tax treatment under `fritaksmetoden` if clear.

Unsupported first:

- Partial disposals with unclear cost basis.
- Multi-currency sales.
- Deferred settlement.
- Non-cash consideration.
- Loss treatment where `fritaksmetoden` classification is unclear.

### Shareholder Loan Workflow

Launch should treat shareholder loans as high-risk.

Supported first:

- Loans from shareholder to company.
- Loans from company to corporate shareholder only if simple and documented.
- Balance tracking.
- Interest optional only if modelled conservatively.
- Documentation upload.

Needs-accountant or blocked first:

- Loans from company to personal shareholder.
- Related-party security/guarantees.
- Old loans with unclear tax history.
- Loan forgiveness.
- Unclear market interest or repayment terms.

Reason: Skatteetaten states that loans, credit, or security from a company to a personal shareholder or related party can be taxed as dividends.

### Tax Settlement Workflow

Launch should support simple corporate tax settlement entries needed for annual close:

- Estimated tax payable/refundable.
- Payment/refund tracking.
- Prior-year tax settlement difference.

Unsupported first:

- Advanced tax loss carry-forward workflows.
- Group contribution.
- Corrections to multiple prior years.
- Tax credits or deductions outside simple holding-company scope.

### Shareholder Structure

Launch-supported shareholder structure:

- One share class.
- Norwegian personal shareholder.
- Norwegian corporate shareholder.
- One or more shareholders.
- Simple share transfer.
- Simple capital increase.
- Dividend to shareholders.

Unsupported first:

- Foreign shareholders.
- Multiple share classes.
- Treasury shares.
- Options/warrants.
- Mergers/demergers.
- Complex capital reductions.
- Inheritance/gift edge cases.

### Documents

In-app accounting document storage is core from day one.

Minimum document types:

- Bank statements.
- Dividend documentation.
- Share purchase/sale agreements.
- Accounting/admin cost receipts.
- Prior annual accounts.
- General meeting/board documents.
- Filing previews.
- Filing receipts.

Retention and portability:

- Store accounting documents and filing receipts for at least 5 years.
- Allow company archive export at any time.
- On cancellation, allow archive download before deletion.
- Do not rely on data lock-in as part of the business model.
- No public API at launch; archive export is the portability mechanism.

### Templated Corporate Documents

Generate templates for:

- Annual general meeting protocol approving annual accounts.
- Simple dividend decision/resolution.
- Documentation checklist.

Do not support first:

- Legal advice.
- Articles of association changes.
- Mergers/demergers.
- Complex capital changes.

## 7. UX Principles

### Norwegian First

User-facing product language should be Norwegian-first. Use authority/accounting terminology such as:

- `aksjonærregisteroppgave`
- `skattemelding`
- `årsregnskap`
- `fritaksmetoden`
- `aksjonærlån`

English can remain in code and internal engineering documentation.

### Year-End Interview

Annual filing should feel like a guided year-end interview, not raw accounting forms.

Ask owner-level questions:

- Did the company own shares at year end?
- Did it buy or sell shares?
- Did it receive dividends?
- Did it declare dividends to owners?
- Did it have loans to or from owners or related companies?
- Did it pay any costs?
- Is the bank balance correct?
- Are there unpaid invoices or bills?
- Has the general meeting approved the annual accounts?

The app maps answers to ledger, shareholder register, tax return, and annual accounts data.

Filing UX should be desktop-first and mobile-readable. Filing review, documents, ledgers, and final submission are detail-heavy and should be optimized for desktop. Mobile should support reminders, status checks, and simple review, but not be the primary filing surface.

### Holding-Action Wizards

Primary posting UX should be holding-action wizards, not manual journals.

- User answers questions in ordinary owner language.
- App generates deterministic debit/credit entries.
- App explains the result.
- User reviews and approves before posting.

Manual journal entry exists only as an advanced escape hatch.

### Structured vs Unstructured Entries

- Structured entry: generated by a holding-action wizard with known intent and deterministic filing implications.
- Unstructured entry: manual journal whose business intent is not fully known by the app.

Unstructured entries touching tax-sensitive or filing-sensitive accounts trigger warnings, escalation, or blocking during filing readiness.

## 8. Direct Filing Model

### Owner-Managed Direct Filing

The first filing model is owner-managed direct filing:

- Owner/legal representative authenticates.
- App prepares filing data.
- User reviews final preview.
- User confirms authority to submit.
- App submits through relevant authority flow.
- Official receipt/status is stored.

Authentication split:

- App login can use secure email/password plus MFA or passwordless email plus MFA.
- BankID is not required for ordinary app login at launch.
- Authority authentication/authorization happens when filing through the relevant public-sector flow.

Accountant review is optional, not mandatory, for simple holding AS filings.

Launch should support simple accountant invite:

- Read/review access.
- Comments/checklist review.
- Filing preview review.
- No bulk client dashboard.
- No accountant billing.
- No accountant-mediated filing as the first model.

Owner control policy:

- Hard readiness issues block filing.
- Accountant comments are advisory unless tied to a hard readiness issue.
- User can acknowledge unresolved accountant comments and file.
- If an accountant marks "do not file", show escalation warning, but owner can still file unless system validations fail.

### Filing Readiness Gate

The annual loop should allow separate filing with shared annual data. Deadlines differ, especially because `aksjonærregisteroppgaven` comes before tax return and annual accounts. Each filing should have its own readiness gate, while sharing company/year data and showing consistency warnings across filings.

`Aksjonærregisteroppgaven` may be filed before full year-end accounting is complete because it is shareholder-event driven. Minimum readiness:

- Company identity verified.
- Shareholders complete.
- Share capital/share count reconciles.
- Share events complete.
- Dividends declared during year recorded.
- Shareholder loan flags reviewed.
- User confirms no missing share events.

It should not require full bank reconciliation or completed annual accounts, but it should show consistency warnings if later year-end data may affect shareholder reporting.

Every direct filing must pass its filing readiness gate:

- Ledger balanced.
- Bank reconciled or explicitly marked unreconciled with warning accepted.
- Required vouchers attached or missing-voucher warning accepted.
- Investments reconcile to balance sheet.
- Shareholder register reconciles to share capital.
- Dividend tax treatment reviewed.
- Shareholder loans reviewed.
- User confirms authority to submit for the company.
- User sees final filing preview.
- Submission receipt is stored after filing.

Manual filing-field overrides should be limited and audited:

- Prefer fixing source data over editing filing output.
- Allow override only where an authority field cannot yet be modelled from source data.
- Require explanation for every override.
- Show override in filing readiness report.
- Trigger warning/escalation depending on risk.
- Store override in audit log.

Corrections after filing:

- Launch stores filed data, preview, and receipt.
- Launch supports archive export.
- Launch explains that amendments/corrections require manual handling or accountant help.
- Launch does not support direct amended filings, prior-year correction workflows, or automatic re-submission.

Late filing:

- Launch supports deadline reminders.
- Launch shows overdue status.
- Launch gives "file as soon as possible" guidance.
- Launch warns that fees/penalties may apply.
- Launch stores filing receipt.
- Launch does not calculate fines, appeal penalties, or guarantee against late fees.

### Needs-Accountant Cases

The app must separate the simple self-service path from needs-accountant cases.

Examples:

- VAT registered company.
- Payroll, board fees, or employee benefits.
- Foreign shareholders.
- Foreign investments where `fritaksmetoden` classification is unclear.
- Shareholder loans from company to personal shareholder.
- Group contributions.
- Mergers, demergers, liquidation, or capital reduction.
- Multiple share classes or complex share transactions.
- Audit obligation.
- Negative equity or going-concern issue.
- Missing bank reconciliation.
- Manual override of tax treatment.

Risk responses:

1. **Hard block**: direct filing refused until resolved.
2. **Escalation required**: user must invite accountant or enable advanced review.
3. **Explicit warning**: user can continue after accepting risk.

Unsupported-case messages should be blunt and specific:

1. State the exact reason the company or event is outside the simple holding AS path.
2. State whether the issue is a hard block, escalation requirement, or warning.
3. Explain the next available action: fix data, export archive, invite accountant, or disable unsupported module.
4. Avoid vague error language such as "something went wrong."

## 9. Filing Implementation Sequence

### Technical Milestones

Direct filing should be implemented in two technical stages:

1. **Filing simulation**
   - Build intended filing data model.
   - Validate known required fields.
   - Run filing readiness gate.
   - Show Norwegian filing preview.
   - Store simulated receipt.
   - No authority submission.

2. **Production direct filing**
   - Connect real authority APIs/flows.
   - Submit.
   - Handle validation feedback.
   - Store official receipt/status.

Filing simulation is acceptable only where enough public information exists to model filings accurately. It is not a substitute for official API/test-flow validation.

### Authority Integration Build Order

Build-risk order:

1. `Aksjonærregisteroppgaven`
2. `Årsregnskap`
3. `Skattemelding for AS`

This is not the calendar order. It is the implementation-risk order.

### First Filing Engine Target

The first concrete filing-engine target is `aksjonærregisteroppgaven`.

Reason:

- Most holding-specific.
- Bounded shareholder/share-event model.
- Public Skatteetaten examples exist.
- Commercially important because AS companies move toward end-user-system delivery.

Done for first `aksjonærregisteroppgaven` simulation:

- One shareholder, no changes.
- New company / stiftelse.
- Share sale between two shareholders.
- Dividend declared/paid.
- Capital increase.
- Shareholder loan flag where relevant to reporting.
- Opening and closing share ownership reconcile.
- Filing preview generated in Norwegian.
- Golden tests based on Skatteetaten examples pass.
- No API submission yet.

## 10. Validation Strategy

### Public-Data Validation First

Use public-data validation before private real cases:

- Public annual accounts.
- Public shareholder information where available.
- Skatteetaten examples.
- Authority docs.
- Synthetic golden cases.

This is fast, cheap, and avoids the friction of collecting private data too early.

Public data can validate output plausibility, annual-account totals, shareholder structures where available, and known example handling.

Public data cannot fully validate:

- Bank transaction classification.
- Voucher completeness.
- Exact ledger postings.
- Detailed tax return internals.
- Same-payload parity with Fiken/accountant software.

### Private Validation Later

Recommended later step:

- 3-5 real simple holding AS cases.
- Compare against Fiken-generated, accountant-prepared, or previously submitted filings where available.

This private validation route can be revisited when the product reaches that stage.

## 11. AI Boundary

AI may reduce build cost and assist users, but it must not be the source of accounting truth.

Allowed AI uses:

- Coding assistance.
- Bank text classification suggestions.
- Suggested account mappings.
- Voucher/receipt extraction drafts.
- Plain-language explanations of deterministic calculations.
- Missing-information summaries.
- Help and onboarding.

Deterministic code must own:

- Double-entry ledger math.
- Tax calculations.
- `Fritaksmetoden` calculations.
- Validation rules.
- Filing payload generation.
- Audit logs.
- Period locks.
- Submission state and receipts.

Any AI suggestion that affects accounting records must be reviewable before posting. No AI-generated filing payload should be submitted without deterministic validation.

## 12. Technical Plan

### First Implementation Target

Implementation should start with the domain/filing engine, not a polished UI.

Use:

- Python 3.12+
- Pydantic for domain and filing schemas.
- Pytest for golden cases and public-data validation.
- Ruff and mypy for quality.
- Reusable Python library with thin CLI.
- FastAPI later if an API boundary is needed.
- Web UI stack deferred until the filing core is proven.

Initial shape:

- `holding_core/`: domain models, narrow ledger, holding actions, filing readiness, deterministic rules.
- `holding_cli/`: thin commands that exercise the library.
- `tests/fixtures/`: golden cases, public-data cases, official examples.

CLI commands later:

- `simulate-aksjonaerregister`
- `simulate-arsregnskap`
- `simulate-skattemelding`
- `validate-case`

### Later Web Architecture

Defer until the filing engine is proven.

Likely direction:

- Web UI with Norwegian-first workflows.
- Backend API around Python filing engine.
- PostgreSQL as system of record.
- Object storage for accounting documents.
- Background jobs for imports, exports, filing, validation, reminders.

Data model should support multiple companies per user from day one, while UI remains single-company-first.

Launch role model:

- Owner/admin: edit, invite users, file, manage billing.
- Reviewer/accountant: view, comment, review filing preview.
- Read-only: view/export.

No complex permissions matrix at launch.

### Security and Trust Requirements

Required before production:

- MFA.
- Role-based access control.
- Tenant isolation.
- Audit logs.
- Encryption in transit and at rest.
- Restore-tested backups.
- Signed URLs or equivalent for documents.
- GDPR processes and data processing terms.
- Explicit confirmation before every authority submission.

Audit log requirements:

- Record login/security events relevant to company access.
- Record company identity changes.
- Record user invitations and role changes.
- Record draft-to-posted transitions.
- Record corrections/reversals.
- Record filing readiness checks.
- Record filing-field overrides.
- Record filing submission confirmation and receipt.

Backup and recovery requirements:

- Automated database backups.
- Object/document backup strategy.
- Restore test before production launch.
- Company archive export independent of cancellation.
- Clear data deletion process after retention/export window.

## 13. Pricing and Go-To-Market

### Fiken Cost Benchmark

Approximate comparable Fiken annual cost from public pricing:

- Base: NOK 209/month = NOK 2,508/year excl. VAT.
- AS tax/annual/shareholder package: NOK 1,490/year.
- Comparable annual total before bank/API/payroll/etc.: about NOK 3,998/year excl. VAT.

### Pricing Hypothesis

Standard target pricing:

- NOK 49/month.
- NOK 499/year filing package.

Founder pricing:

- NOK 29/month.
- NOK 299/year filing package.
- Lifetime for first 100 companies.

Launch beta:

- NOK 0/month until first filing season, or first company free.

Founder pricing is compensation for early adoption risk, not the permanent value of statutory filing.

Billing defaults:

- Charge monthly subscription for active companies.
- Charge annual filing package when the user enters production filing flow or at filing completion; final timing can be decided during billing implementation.
- Do not charge for blocked unsupported cases beyond normal subscription unless the user used paid support/review.
- If Talli cannot complete a supported filing, refund the filing package.

### Trust Model

At launch, build trust through:

- Transparent readiness checks.
- Plain-language filing previews.
- Official receipt storage.
- Optional accountant review.
- Direct support for founder users during first filing season.
- Refund if the app cannot complete a supported filing.

Do not offer a fine/penalty guarantee at launch. That should wait until the product has filing history, insurance, and mature support.

Founder support should be included but tightly scoped.

Included:

- Onboarding help.
- Filing readiness issues.
- Product bugs.
- Authority submission errors.

Excluded:

- Custom tax advice.
- Complex accounting review.
- Investment advice.
- Legal advice.
- Bookkeeping cleanup from previous years.

## 14. Costs

### Development Cost Ranges

Very rough estimates:

| Stage | Scope | Estimated cost |
| --- | --- | ---: |
| Filing-domain prototype | Python engine, RF-1086 simulation, fixtures | NOK 100k-350k |
| MVP beta | Narrow ledger, documents, annual interview, simulations | NOK 600k-1.5m |
| Direct filing hardening | Authority integration, validation, receipts, security | NOK 1.5m-4.0m |
| Web SaaS product | Auth, storage, billing, UX, support tooling | NOK 1.0m-3.0m |
| Optional modules | VAT, payroll, bank feed, Fiken import | NOK 0.5m-5.0m+ each depending scope |

### Operating Costs

Early filing engine/prototype:

- Near zero infrastructure.
- Developer machine/GitHub only.

Early SaaS:

- Hosting/database/storage: low at first, but not zero once documents and user data are stored.
- Email and logging.
- Error monitoring.
- Backups.
- Domain and basic security tooling.

Later costs:

- Open banking provider if live bank feeds are added.
- Authority integration maintenance.
- Professional review/advisor costs.
- Support.
- Insurance.
- Security review.

Infrastructure can start cheap. Compliance, support, and trust are the real costs.

## 15. Risks

### Compliance Risk

Wrong filing or tax treatment can harm users.

Mitigations:

- Simple holding AS scope.
- Filing readiness gate.
- Needs-accountant escalation.
- Deterministic rules.
- Public-data validation.
- Official test-flow validation.
- Optional accountant review.

### Scope Creep

Adding VAT, payroll, invoicing, projects, bank feeds, OCR, and broad accounting workflows too early destroys the wedge.

Mitigation:

- Keep optional operating modules disabled by default.
- Keep launch promise narrow.
- Treat unsupported cases explicitly.

### Trust Risk

Users may not trust a new company with statutory filing.

Mitigation:

- Founder pricing.
- Direct support.
- Transparent previews.
- Receipts.
- Refund policy.
- Clear boundaries.

### API and Authority Risk

Authority APIs, access models, schemas, and requirements may change.

Mitigation:

- Simulation before production.
- Provider abstractions.
- Official docs and test flows.
- Versioned filing models.

### Liability Risk

Owner-managed direct filing creates responsibility questions.

Mitigation:

- Explicit authority confirmation.
- Clear terms.
- No penalty guarantee at launch.
- Optional accountant review.
- Block unsupported cases.

### Public-Data Validation Limits

Public data is not full end-to-end proof.

Mitigation:

- Use it first, but recognize its limits.
- Add private validation later if needed.
- Official test-flow validation before production filing.

### Support Load Risk

Low pricing can be destroyed by support-heavy customers.

Mitigations:

- Strict simple holding AS scope.
- Founder support boundaries.
- Unsupported-case blocks.
- Self-serve explanations.
- Refund filing package instead of providing unlimited consulting.

### Naming and Trademark Risk

`talli.no` is secured, but domain ownership is not trademark clearance.

Mitigations:

- Run Norwegian trademark search before launch.
- Check Brønnøysund company-name conflicts.
- Avoid claims that imply affiliation with Fiken, Altinn, Skatteetaten, or Brønnøysund.

## 16. Build Phases

### Phase 0: Final Research and Filing Spec Mapping

Deliverables:

- Map RF-1086 public API docs and examples.
- Map annual accounts public fields and RR-0002 requirements.
- Map `skattemelding for AS` API surface.
- Identify hard blockers for simulation accuracy.

RF-1086 mapping artifact:

- [Aksjonærregisteroppgaven Phase 0 Map](./docs/filing/aksjonaerregisteroppgaven-phase-0-map.md)
- Local official XSD copies:
  - [Hovedskjema XSD](./docs/filing/aksjonaerregisteroppgaveHovedskjema.xsd)
  - [Underskjema XSD](./docs/filing/aksjonaerregisteroppgaveUnderskjema.xsd)

### Phase 1: Python Filing Engine Prototype

Deliverables:

- `holding_core` library.
- Narrow ledger model.
- Shareholder/share-event model.
- Holding actions.
- Filing readiness gate.
- `aksjonærregisteroppgaven` simulation.
- Golden tests from Skatteetaten examples.
- Thin CLI.

Initial RF-1086 prototype status:

- `holding_core` Pydantic models created.
- `holding_cli` thin CLI created.
- RF-1086/RF-1086-U XML generation created for no-activity, stiftelse, simple share sale, and simple dividend fixtures.
- CLI readiness command created: `validate-case --case <fixture> [--json]`.
- Public/synthetic validation harness command created: `validate-public-data --case <fixture> [--json]`.
- `simulate-aksjonaerregister` now runs the filing readiness gate before writing XML.
- Invalid cases fail cleanly before filing artifacts are generated.
- Unsupported launch cases such as non-ordinary share classes block before XML generation.
- Official XSD validation runs locally with `xmllint`.
- Production API calls are not implemented.
- Event code values for kjøp/salg/utbytte remain provisional until rettledning/code-list verification.

Initial narrow-ledger prototype status:

- Draft, posted, reversal, and audit-event lifecycle created.
- Posted entries are immutable and are the filing-source entries.
- Opening balance / new-year start structured action created.
- Paid admin cost structured action created for launch-supported cost categories.
- Dividend received structured action created with `fritaksmetoden` 3% taxable add-back metadata.
- Share purchase structured action created with investment position and cost basis.
- Share sale structured action created with position reduction and gain/loss calculation.
- Dividend to owner structured action created with allocation, equity, liquidity, and document checks.
- Shareholder loan structured action created with high-risk personal-shareholder loan block.
- VAT deduction, unpaid supplier flows, and other operating-company cost complexity remain out of scope.

### Phase 2: Public-Data Validation Harness

Deliverables:

- Public annual-account fixtures.
- Synthetic holding-company fixtures.
- Validation reports.
- Mismatch classification.

Initial validation harness status:

- RF-1086 public/synthetic harness runs supported and blocked fixture cases.
- Reports classify pass, warning, and blocked outcomes.
- Reports include public-data limitations so validation confidence is not overstated.

Initial annual simulation status:

- Year-end interview answer model created.
- Shared annual data model created from posted narrow-ledger entries, documents, and confirmations.
- Filing-specific readiness gates created for `årsregnskap` and `skattemelding for AS`.
- `årsregnskap` simulation preview and simulated receipt created for simple holding AS.
- `skattemelding for AS` simulation preview includes simplified `fritaksmetoden` 3% add-back and estimated tax.
- Company archive export created with ledger entries, document index, filing previews, readiness reports, receipts, and missing-document markers.

### Phase 3: Annual Holding Compliance Simulation

Deliverables:

- `årsregnskap` simulation.
- `skattemelding for AS` simulation.
- Year-end interview model.
- Norwegian filing previews.
- Simulated receipts.

### Phase 4: SaaS MVP

Deliverables:

- Norwegian-first web UI.
- Auth.
- Company setup.
- New-year start.
- Manual entry and bank CSV import.
- Document storage.
- Filing readiness dashboard.
- Company archive export.

Initial SaaS shell status:

- Placeholder Next.js app replaced with a Norwegian-first owner-managed workflow dashboard.
- Company setup support-boundary status created for supported AS and blocked non-AS cases.
- Filing readiness summary shown from shared workspace data.
- Document metadata/status workflow created with company-scoped owner access checks.
- Optional accountant/reviewer invite, comment, and owner acknowledgement workflow created.
- Hard review/system blocks cannot be acknowledged away by owner.
- Web logic tests and Next production build pass locally.

### Phase 5: Production Direct Filing

Deliverables:

- Authority authentication/submission.
- Official validation feedback.
- Receipt storage.
- Billing.
- Founder cohort support process.
- Security review.

## 17. Key Decisions Recorded

See ADRs:

- [ADR 0001: Position as Holding-First, Not a Fiken Clone](./docs/adr/0001-position-as-holding-first-not-fiken-clone.md)
- [ADR 0002: Owner-Managed Direct Filing First](./docs/adr/0002-owner-managed-direct-filing-first.md)
- [ADR 0003: Deterministic Compliance Core With AI Assistance](./docs/adr/0003-deterministic-compliance-core-with-ai-assistance.md)
- [ADR 0004: Norwegian-First Product Language](./docs/adr/0004-norwegian-first-product-language.md)
- [ADR 0005: Multi-Company Model, Single-Company UX First](./docs/adr/0005-multi-company-model-single-company-ux-first.md)
- [ADR 0006: Filing Assistant With Narrow Ledger](./docs/adr/0006-filing-assistant-with-narrow-ledger.md)
- [ADR 0007: Domain and Filing Engine Before UI](./docs/adr/0007-domain-filing-engine-before-ui.md)
- [ADR 0008: Python Domain and Filing Engine First](./docs/adr/0008-python-domain-filing-engine-first.md)
- [ADR 0009: Use Talli as Working Brand](./docs/adr/0009-use-talli-as-working-brand.md)

## 18. Source Index

- [Altinn: Accounting system](https://info.altinn.no/en/start-and-run-business/accounts-and-auditing/accounting/accounting-system/)
- [Altinn: Private limited companies](https://info.altinn.no/en/start-and-run-business/planning-starting/choosing-legal-structure/private-limited-companies/)
- [Altinn: Reporting obligations](https://info.altinn.no/en/start-and-run-business/planning-starting/before-start-up/your-reporting-obligations/)
- [Altinn: Reporting and paying VAT](https://info.altinn.no/starte-og-drive/skatt-og-avgift/avgift/rapportering-og-betaling-av-mva/)
- [Altinn: A-melding](https://info.altinn.no/en/start-and-run-business/working-conditions/pay/a-melding/)
- [Altinn: Voucher requirements](https://info.altinn.no/en/start-and-run-business/accounts-and-auditing/accounting/requirements-concerning-vouchers/)
- [Altinn: Annual accounts RR-0002](https://info.altinn.no/en/forms-overview/bronnoysund-register-centre/annual-accounts/)
- [Skatteetaten: Annual accounts](https://www.skatteetaten.no/en/business-and-organisation/start-and-run/best-practices-accounting-and-cash-register-systems/annual-accounts/)
- [Skatteetaten: Skattemelding for selskap](https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/selskap/)
- [Skatteetaten: Mva-melding](https://www.skatteetaten.no/bedrift-og-organisasjon/avgifter/mva/mva-melding/)
- [Skatteetaten: VAT return API](https://skatteetaten.github.io/mva-meldingen/english/api/)
- [Skatteetaten: SAF-T Financial](https://www.skatteetaten.no/en/business-and-organisation/start-and-run/best-practices-accounting-and-cash-register-systems/saf-t-financial/)
- [Skatteetaten: Fritaksmetoden](https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/fradrag/aksjer/fritaksmetoden/)
- [Skatteetaten: Tax exemption method](https://www.skatteetaten.no/en/business-and-organisation/tax-for-businesses/tax-return/deductions/shares-and-securities/the-tax-exemption-method/)
- [Skatteetaten: Aksjer i næring](https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/fradrag/aksjer/aksjer-i-naring-selskapets-aksjer/)
- [Skatteetaten: Aksjonærregisteroppgaven](https://www.skatteetaten.no/skjema/rf-1086-aksjonarregisteroppgaven/)
- [Skatteetaten: Aksjonærregisteroppgaven API](https://skatteetaten.github.io/api-dokumentasjon/api/innrapportering-aksjonaerregisteroppgave)
- [Skatteetaten: Skattemelding upersonlig API](https://skatteetaten.github.io/api-dokumentasjon/api/skattemeldingupersonlig)
- [Skatteetaten: Shareholder loans](https://www.skatteetaten.no/person/skatt/hjelp-til-riktig-skatt/aksjer-og-verdipapirer/om/lan-til-personlig-aksjonar/)
- [Brønnøysundregistrene: Annual accounts submission](https://www.brreg.no/innsending-av-arsregnskap/)
- [Brønnøysundregistrene: Open data](https://www.brreg.no/en/use-of-data-from-the-bronnoysund-register-centre/open-data/)
- [Fiken: Pricing](https://fiken.no/priser)
- [Fiken: Integrations](https://fiken.no/integrasjoner)
- [Fiken: API documentation](https://api.fiken.no/api/v2/docs/)
- [Fiken: Accountant course outline](https://kurs.fiken.no/courses/Fikens-sertifiseringskurs-for-regnskapsforere)
- [Tink: Open banking platform](https://tink.com/)
- [Enable Banking: Open banking API](https://enablebanking.com/)
