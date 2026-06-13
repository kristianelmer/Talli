# PRD: Talli Holding-First Filing Assistant

Status: `ready-for-agent`  
Product: Talli  
Audience: Product, engineering, compliance review, future implementation agents  
Source plan: consolidated Talli plan and ADRs

## Problem Statement

Owners of simple Norwegian holding companies need to complete annual statutory reporting, but broad accounting suites are priced and designed for wider operating-company workflows: invoicing, VAT, payroll, projects, supplier ledgers, customer ledgers, and bank-feed-heavy bookkeeping. A regular holding company often does not need that surface area.

The user problem is not merely "bookkeeping is annoying." The deeper problem is that annual holding compliance is high-consequence, deadline-driven, and fragmented across shareholder reporting, annual accounts, company tax return, documents, balances, shareholder events, dividends, loans, and authority submission. Existing broad products can solve the problem, but they make a simple holding AS pay for clutter and complexity it does not use.

Talli should give these owners a cheaper, narrower, more direct path: complete the annual holding compliance loop for a simple Norwegian holding AS, block unsupported cases clearly, and directly file supported obligations instead of only preparing numbers for manual filing elsewhere.

## Solution

Build Talli as a Norwegian-first filing assistant with a narrow ledger for simple Norwegian holding companies.

The product should maintain enough deterministic accounting data to support the annual holding compliance loop, while avoiding generic accounting-suite scope. The first user experience should be a guided owner workflow: onboard a company, capture holding actions, attach accounting documents, run filing readiness gates, review Norwegian filing previews, submit directly through supported authority flows, and store receipts and an exportable company archive.

The launch promise is:

**File the annual reports for a simple Norwegian holding AS directly from the app.**

The first direct filing scope is:

1. `aksjonærregisteroppgaven`
2. `årsregnskap`
3. `skattemelding for AS`

The first implementation target is the Python domain and filing engine, beginning with `aksjonærregisteroppgaven` filing simulation. The web SaaS product, billing, auth, document storage, and production authority submission should come after the filing core is proven with deterministic fixtures, official schemas, public-data validation, and official test-flow validation.

## User Stories

1. As a holding company owner, I want Talli to explain whether my company fits the simple holding AS path, so that I know whether I can safely use the product.
2. As a holding company owner, I want to enter my organization number first, so that company setup starts from official Norwegian company identity.
3. As a holding company owner, I want Talli to verify that the company is an AS, so that unsupported entity types are blocked early.
4. As a holding company owner, I want non-AS entities to be rejected clearly, so that I do not waste time setting up an unsupported company.
5. As a holding company owner, I want to confirm that I am authorized to file for the company, so that direct filing happens under proper owner control.
6. As a holding company owner, I want guidance on Altinn and authority access requirements, so that I understand what role or access I need before the filing deadline.
7. As a holding company owner, I want to start a new accounting year from opening balances, so that I can begin using Talli without full historical migration.
8. As a holding company owner, I want to upload prior annual accounts, so that Talli has reference material for opening balances and later validation.
9. As a holding company owner, I want to enter opening bank balance, investment balances, shareholder positions, loans, and equity, so that the annual loop can reconcile correctly.
10. As a holding company owner, I want Talli to support no-activity years, so that I can file required reports even when nothing happened.
11. As a holding company owner, I want Talli to support newly founded simple AS companies, so that stiftelse-year shareholder reporting can be handled.
12. As a holding company owner, I want Talli to block non-cash incorporation and other complex formation cases, so that the product does not pretend unsupported cases are safe.
13. As a holding company owner, I want a single-company-first workspace, so that the product feels focused on my company rather than an accountant practice dashboard.
14. As an owner with multiple companies, I want the account model to support more than one company, so that I can later manage several holdings without migration.
15. As a holding company owner, I want holding-action wizards instead of manual journal forms, so that I can record events in ordinary owner language.
16. As a holding company owner, I want to record opening balance as a guided action, so that the ledger starts from an explicit approved state.
17. As a holding company owner, I want to import bank transactions from CSV, so that I can capture simple bank activity without paying for a live bank feed.
18. As a holding company owner, I want to manually enter transactions, so that I can use Talli before automated bank integrations exist.
19. As a holding company owner, I want to reconcile bank balance, so that annual filings are based on a believable ledger.
20. As a holding company owner, I want to record bank fees, accounting fees, software costs, public fees, legal fees, and other admin costs, so that ordinary holding expenses are handled.
21. As a holding company owner, I want Talli to avoid unpaid supplier-ledger complexity at launch, so that the app stays simple.
22. As a holding company owner, I want to attach receipts and accounting documents, so that the company archive can support later review.
23. As a holding company owner, I want document requirements to be risk-based, so that important actions require documentation and small low-risk costs do not become tedious.
24. As a holding company owner, I want to record investments in Norwegian private companies, so that share ownership can feed accounting and tax reporting.
25. As a holding company owner, I want to record simple listed shares or funds manually, so that low-volume securities can be included without broker import complexity.
26. As a holding company owner, I want to record share purchases, so that cost basis, bank movement, documentation, and tax classification are captured together.
27. As a holding company owner, I want to record share sales, so that gain or loss and filing consequences are calculated from structured data.
28. As a holding company owner, I want Talli to classify whether a share event is clearly within `fritaksmetoden`, so that the tax treatment is transparent.
29. As a holding company owner, I want unclear share tax treatment to be escalated or blocked, so that I do not accidentally file a complex case as simple.
30. As a holding company owner, I want to record dividends received from Norwegian AS holdings, so that the 3% taxable add-back can be calculated where applicable.
31. As a holding company owner, I want dividend received workflows to require paying company, amount, dates, linked investment, bank match, and documentation, so that the filing data is defensible.
32. As a holding company owner, I want foreign withholding tax and unclear foreign dividend cases blocked or escalated, so that unsupported tax complexity is not hidden.
33. As a holding company owner, I want to declare and pay simple cash dividends to shareholders, so that shareholder reporting and annual accounts stay consistent.
34. As a holding company owner, I want Talli to check available equity and liquidity before owner dividends, so that obvious illegal or unsafe dividend cases are blocked.
35. As a holding company owner, I want shareholder dividend allocations calculated by share ownership, so that equal treatment within one share class is enforced.
36. As a holding company owner, I want board proposal and general meeting templates for simple dividends, so that required corporate documents can be produced from the same data.
37. As a holding company owner, I want unequal dividends, foreign shareholder withholding cases, and non-cash dividends blocked at launch, so that complex cases are not mishandled.
38. As a holding company owner, I want to record shareholder loans from owner to company, so that balances and documentation are tracked.
39. As a holding company owner, I want loans from company to personal shareholder treated as high-risk, so that potential dividend taxation is not missed.
40. As a holding company owner, I want shareholder loans to have documentation and review flags, so that the filing readiness gate can catch risk.
41. As a holding company owner, I want simple tax settlement entries, so that estimated tax payable, refunds, and prior-year differences are included in annual close.
42. As a holding company owner, I want advanced tax cases such as group contribution and tax credits outside launch scope, so that the first product remains reliable.
43. As a holding company owner, I want one ordinary share class supported first, so that shareholder reporting remains bounded.
44. As a holding company owner, I want multiple shareholders supported where they are Norwegian persons or Norwegian companies, so that simple multi-owner holdings can use Talli.
45. As a holding company owner, I want foreign shareholders, options, warrants, treasury shares, mergers, demergers, and capital reductions blocked at launch, so that I get a clear support boundary.
46. As a holding company owner, I want posted ledger entries to be immutable, so that accounting history is auditable.
47. As a holding company owner, I want corrections to be reversal or correction entries, so that changes after posting are traceable.
48. As a holding company owner, I want draft entries editable, so that I can fix mistakes before posting.
49. As a holding company owner, I want filing data to derive from posted entries and approved structured records, so that filings are not based on accidental drafts.
50. As a holding company owner, I want every important change recorded in an audit log, so that later review can explain who changed what and when.
51. As a holding company owner, I want a year-end interview instead of raw filing forms, so that I can answer business questions and let Talli map them to accounting and filing data.
52. As a holding company owner, I want the year-end interview to ask about shares, dividends, loans, costs, bank balance, unpaid items, and general meeting approval, so that the filing readiness gate covers the annual loop.
53. As a holding company owner, I want `aksjonærregisteroppgaven` to have its own readiness gate, so that shareholder reporting can be filed before full year-end accounting is complete.
54. As a holding company owner, I want annual accounts and company tax return to have their own readiness gates, so that each filing is judged by its own data requirements.
55. As a holding company owner, I want readiness gates to share annual data, so that inconsistencies across filings are caught.
56. As a holding company owner, I want hard readiness issues to block filing, so that unsupported or inconsistent filings cannot be submitted.
57. As a holding company owner, I want warnings to be explicit and accept-or-fix decisions to be recorded, so that I understand and own the remaining risk.
58. As a holding company owner, I want needs-accountant cases explained bluntly, so that I know whether to fix data, export the archive, or invite an accountant.
59. As a holding company owner, I want manual filing-field overrides to be limited and audited, so that source data remains the preferred correction point.
60. As a holding company owner, I want final Norwegian filing previews, so that I can review what will be submitted before approving direct filing.
61. As a holding company owner, I want to see official submission status and receipts after filing, so that I have proof of delivery.
62. As a holding company owner, I want simulated receipts during pre-production testing, so that the product can validate filing behavior before authority submission is enabled.
63. As a holding company owner, I want correction-after-filing limitations explained, so that I know when amendments require manual handling or accountant help.
64. As a holding company owner, I want deadline reminders for 31 January, 31 May, and 31 July, so that I do not miss the annual holding compliance loop.
65. As a holding company owner, I want overdue status and late-filing guidance, so that I can still act if I miss a deadline.
66. As a holding company owner, I want Talli not to guarantee against fines at launch, so that the product remains honest about its maturity.
67. As a holding company owner, I want all product language in Norwegian filing terms, so that the app feels aligned with Norwegian authorities.
68. As a holding company owner, I want plain explanations and no "AI accountant" claims, so that trust comes from transparent deterministic behavior.
69. As a holding company owner, I want AI suggestions to be reviewable before posting, so that AI cannot silently change my accounting records.
70. As a holding company owner, I want tax calculations, filing payloads, and ledger math to be deterministic, so that statutory filings are reproducible.
71. As a holding company owner, I want an archive export, so that I can leave Talli without losing accounting documents, filings, receipts, and ledger history.
72. As a holding company owner, I want archive export before cancellation deletion, so that data portability is not used as lock-in.
73. As a holding company owner, I want accounting documents retained according to Norwegian documentation expectations, so that later audit or review is possible.
74. As a holding company owner, I want optional accountant review, so that I can get help without making accountant approval mandatory.
75. As an invited accountant, I want read and comment access, so that I can review records and filing previews without taking over filing.
76. As an invited accountant, I want to mark comments and concerns, so that the owner sees advisory issues before filing.
77. As a holding company owner, I want accountant comments to be advisory unless tied to hard system validations, so that owner-managed direct filing remains possible.
78. As a founder customer, I want lower founder pricing, so that I am compensated for adopting a new product early.
79. As a founder customer, I want support boundaries to be clear, so that low pricing does not imply unlimited accounting consulting.
80. As a founder customer, I want refund rules if Talli cannot complete a supported filing, so that the risk of trying the product is reduced.
81. As a product operator, I want unsupported cases blocked early, so that support load does not destroy the low-price model.
82. As a product operator, I want direct filing scope to remain narrow, so that Talli does not become a broad Fiken clone by accident.
83. As a product operator, I want optional operating modules deferred, so that VAT, payroll, invoicing, and bank feeds do not clutter launch.
84. As a product operator, I want public-data validation before private customer validation, so that the product can progress without waiting for sensitive real-company data.
85. As a product operator, I want private validation later with a few real simple holding AS cases, so that official and public validation can be complemented before production scale.
86. As a developer, I want a Python domain and filing engine first, so that filing correctness is proven before UI polish.
87. As a developer, I want filing cases expressed as structured fixtures, so that examples can be regression-tested deterministically.
88. As a developer, I want official XSD validation for RF-1086 XML, so that generated filing payloads match the public schema.
89. As a developer, I want a thin CLI around the core engine, so that filing behavior can be exercised before a web app exists.
90. As a developer, I want readiness output available as JSON, so that a future UI can consume the same readiness gate.
91. As a developer, I want invalid cases to fail before generating filing artifacts, so that bad data cannot move toward submission.
92. As a developer, I want production authority API integration separated from filing simulation, so that payload generation can be hardened before submission state is introduced.
93. As a developer, I want idempotency keys stored per authority API call later, so that production retries are safe.
94. As a developer, I want authority feedback documents and receipts stored later, so that submission state remains auditable.
95. As a security reviewer, I want MFA, RBAC, tenant isolation, audit logs, encryption, backups, and restore tests before production direct filing, so that user and company data is handled responsibly.
96. As a compliance reviewer, I want source links, filing maps, and ADRs preserved, so that implementation choices can be traced back to official or product decisions.
97. As a future SaaS user, I want desktop-first filing review and mobile-readable status, so that detail-heavy work is comfortable and reminders remain accessible.
98. As a future SaaS user, I want document uploads stored securely, so that sensitive accounting documents are protected.
99. As a future SaaS user, I want billing tied to active companies and filing packages, so that pricing remains much lower than broad accounting suites.
100. As a future SaaS user, I want clear statements about what Talli is not, so that I do not mistake it for payroll, VAT, invoicing, legal advice, or investment advice.

## Implementation Decisions

- Build Talli as a holding-first product, not a generic Fiken clone. The advantage is narrower scope, clearer workflow, and lower price, not feature parity with broad accounting suites.
- The product category is a filing assistant with a narrow ledger. It needs a real double-entry ledger, but only for supported holding actions needed by simple holding-company compliance.
- The launch promise is direct filing for simple Norwegian holding AS annual reports, not preparation-only exports.
- The first production filing model is owner-managed direct filing. The owner or legal representative authenticates, reviews, confirms authority, submits, and receives stored receipt/status.
- Optional accountant review is allowed, but not mandatory for simple supported filings.
- The first filing-engine target is `aksjonærregisteroppgaven`, because it is holding-specific, bounded by shareholder/share-event data, has public examples, and has a public API/XSD surface.
- `Årsregnskap` and `skattemelding for AS` follow after the shareholder-register engine is proven.
- The implementation should begin with a Python domain and filing engine. A polished SaaS UI is deferred until filing correctness and support-boundary behavior are proven.
- The domain engine should expose stable concepts for company identity, share snapshots, shareholders, shareholder snapshots, holding actions, filing cases, readiness results, filing previews, generated payloads, and receipts.
- The current prototype type shape is a valid initial decision boundary: company, share snapshot, shareholders, shareholder snapshots, and typed events produce readiness output and RF-1086 documents.
- The filing readiness result should remain machine-readable with at least filing name, status, and issue list. A status of blocked means direct filing or filing artifact generation must not continue.
- Hard invariants should fail at domain validation time. Examples include shareholder totals not matching company share count, missing shareholder identifiers, dividend allocation totals not matching declared dividend, and event references to unknown shareholders.
- Readiness gates should handle support-boundary and filing-readiness issues. Examples include unsupported share class, shareholder register reconciliation, dividend allocation review, shareholder loan review, manual overrides, and missing authority confirmation.
- Filing simulations should build the intended filing data, validate known required fields, run readiness gates, show Norwegian previews, and store simulated receipts without submitting to authorities.
- Production direct filing should be implemented only after simulation, official test-flow validation, authority access, submission-state design, receipt storage, security hardening, and recovery procedures exist.
- Production `aksjonærregisteroppgaven` integration must respect the public API shape: submit hovedskjema, submit one underskjema per shareholder/share-class context, confirm submission, then retrieve documents or feedback where available.
- Production submission state must store idempotency keys per logical API call. Retrying the same body should reuse the same key; new calls need new UUIDs.
- The product should support one ordinary share class at launch. Multiple share classes are out of launch scope because RF-1086 requires separate reporting per share class and adds support complexity.
- Company setup should be organization-number-first and verify AS status. Non-AS entities should be hard-blocked.
- Launch onboarding should support new-year start and simple newly founded AS setup, not full mid-year migration.
- The narrow ledger should support opening balance, bank balance, share investments, simple securities, dividends received, admin costs, tax payable/refundable, share capital/equity, dividends to owners, shareholder/intercompany loans, and annual result allocation.
- The ledger should be compatible with later SAF-T export even if SAF-T is not required at public launch.
- Posted entries are immutable. Corrections happen through reversal or correction entries. Drafts can be edited or deleted before posting.
- Filing data derives only from posted entries plus approved structured records.
- All important state changes require audit logging, including company identity changes, user access changes, posting, corrections, readiness checks, overrides, submission confirmation, and receipts.
- Holding-action wizards are the primary posting UX. Manual journal entry exists only as an advanced escape hatch and may trigger readiness warnings or blocks when touching filing-sensitive accounts.
- Norwegian-first product language is a requirement for user-facing workflows and filing explanations. English can remain in internal engineering artifacts.
- AI may assist with coding, classification suggestions, extraction drafts, explanations, and missing-information summaries. AI must not own ledger math, tax calculations, validation rules, filing payload generation, audit logs, period locks, or submission state.
- Document storage is core from day one of the SaaS product. Required document types include bank statements, dividend documentation, share purchase/sale agreements, receipts, prior annual accounts, corporate documents, filing previews, and filing receipts.
- Company archive export is required for portability and cancellation. Data lock-in must not be part of the business model.
- Security requirements before production include MFA, RBAC, tenant isolation, encryption in transit and at rest, restore-tested backups, signed document URLs or equivalent, GDPR processes, data processing terms, and explicit authority submission confirmation.
- Pricing should start materially below broad accounting suites. The working hypothesis is low monthly subscription plus annual filing package, with founder pricing for early risk compensation.
- Unsupported-case behavior must be blunt and specific: state the reason, risk response, and next available action.
- The product should not add VAT, payroll, invoicing, live bank feeds, broker import, broad supplier/customer ledgers, or practice-management workflows into the default launch product.

## Testing Decisions

- Tests should verify external behavior rather than implementation details. The main question is whether a supported filing case produces the expected readiness result, preview, generated payload, validation behavior, and refusal behavior.
- The highest current seam is structured filing fixtures through the Python domain/filing engine and thin CLI. This seam should remain the primary regression layer until a web API exists.
- RF-1086 XML generated by the engine should be validated against official local XSD copies. This is a stronger behavioral test than asserting internal builder steps.
- Golden fixtures should cover no-activity year, stiftelse/new company, two-founder formation, simple share sale, and simple dividend.
- Negative fixtures should verify that invalid ownership or allocation data fails before filing artifacts are generated.
- Readiness command behavior should be tested in both human-readable and JSON form, because the future UI should consume the same readiness contract.
- CLI simulation should be tested as an end-to-end seam for the pre-SaaS engine: fixture input, readiness gate, XML output, preview text, and schema validation.
- Future API tests should exercise company onboarding, holding-action posting, readiness calculation, filing preview generation, and archive export through public service boundaries rather than database internals.
- Future browser tests should cover the owner journey: create company, enter opening balances, record holding actions, attach documents, run year-end interview, review readiness, preview filing, confirm authority, and view receipt.
- Future production filing tests must use official test environments and synthetic authority-approved test data, not real customer or public-company data where test-environment rules prohibit it.
- Public-data validation should be used before private real-company validation. It can validate plausibility, public annual-account totals, known examples, and shareholder structures where available.
- Public-data validation cannot prove voucher completeness, exact bank classification, detailed tax internals, or parity with Fiken/accountant software. This limitation should remain visible in validation reports.
- Private validation should later use a small set of simple real holding AS cases and compare against Fiken-generated, accountant-prepared, or previously submitted filings where available.
- Submission-state tests should later verify idempotency behavior, retry safety, authority validation feedback handling, receipt storage, and no duplicate logical submissions.
- Security tests before production should cover tenant isolation, role authorization, audit-log creation, document access controls, backup restore, and MFA-required sensitive actions.

## Out of Scope

- Building a generic Fiken clone.
- Invoicing and customer ledger.
- VAT registration, VAT deduction, and `mva-melding`.
- Payroll, board fees, employee benefits, and `a-melding`.
- Projects, time tracking, inventory, and broad SME workflows.
- Live bank feeds at launch.
- Broker imports and high-volume trading support.
- Foreign shareholder withholding tax at launch.
- Foreign investments where `fritaksmetoden` classification is unclear.
- Multiple share classes at launch.
- Treasury shares, options, warrants, mergers, demergers, liquidation, complex capital reductions, and inheritance/gift edge cases.
- Non-cash dividends and unequal dividends within the same share class.
- Loans from company to personal shareholder as a self-service simple path.
- Group contribution and advanced tax loss workflows at launch.
- Full mid-year migration.
- Company incorporation/registration before the organization number exists.
- Public API at launch.
- Accountant practice dashboard at launch.
- Direct amended filings, prior-year correction workflows, or automatic re-submission at launch.
- Fine or penalty guarantees at launch.
- Legal, tax, accounting, or investment advice beyond deterministic product explanations and support-boundary guidance.

## Further Notes

- Talli is the working brand and `talli.no` is secured. Domain ownership is not trademark clearance; trademark and company-name checks remain required before public launch.
- The current repository already contains a Phase 1 RF-1086 simulation prototype with Python/Pydantic models, readiness checks, CLI commands, fixtures, and official XSD validation.
- Current prototype support includes RF-1086/RF-1086-U generation for no activity, stiftelse, simple share sale, and simple dividend fixtures.
- The current prototype blocks invalid cases before generated filing artifacts are written.
- Production API calls are not implemented.
- RF-1086 event code values for some transaction types remain provisional until verified against Skatteetaten rettledning, code-list behavior, or official test-flow feedback.
- Before production filing, the filing models, validation rules, authority payloads, and submission state must be reviewed against current official specifications and validated through official or equivalent test flows.
- Infrastructure can start cheap, but compliance, support, security, authority integration, validation, and trust are the real costs.
- Founder pricing should compensate early adopters for product maturity risk, not permanently anchor the product below sustainable support cost.
