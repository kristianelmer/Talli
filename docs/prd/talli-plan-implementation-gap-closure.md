# PRD: Close Plan vs Implementation Gaps

Status: `ready-for-agent`  
Product: Talli  
Audience: Product, engineering, compliance review, future implementation agents  
Source plan: `PLAN.md`, ADRs, current implementation audit on 2026-06-14

## Problem Statement

Talli has a coherent plan: a Norwegian-first filing assistant with a narrow ledger for simple holding AS companies, direct owner-managed filing, strict support boundaries, low pricing, and no broad Fiken-style clutter.

The current implementation is a useful first engine, but it does not yet satisfy the full plan. It contains RF-1086 simulation, a narrow ledger prototype, holding-action builders, annual/tax preview simulations, archive export, a static Next.js SaaS shell, a submission-state model, and a billing-gate model. Those are foundations, not the complete product.

The user-facing risk is that the repository can look more complete than it is. Several issue slices are closed because they added anchors or prototypes, but the plan still requires real workflows: persistent SaaS state, official company lookup, document storage, bank CSV/reconciliation, production filing integration, annual accounts and tax return authority mappings, security controls, billing collection, and end-to-end owner UX.

This PRD identifies discrepancies between the current implementation and the plan, then defines the product and technical work needed to close them.

## Solution

Build a gap-closure milestone that turns the existing engine-first prototype into a plan-aligned MVP baseline.

The milestone should not expand Talli into a generic accounting suite. It should make the current narrow promise more real:

- A supported simple holding AS can be onboarded from official company identity.
- Owner data, ledger entries, documents, filings, reviewers, billing, and submissions are persisted per tenant.
- Holding actions are executable through product workflows, not only Python builders.
- Annual data flows from posted entries and approved structured records into filing readiness, previews, and archives.
- RF-1086 remains the first authority integration, but production filing cannot proceed through unverified code paths.
- `årsregnskap` and `skattemelding for AS` move from rough simulations toward authority-mapped filing engines.
- Billing, security, audit, archive, and support boundaries are enforced as product gates, not only documented intentions.

### Current Implementation Anchors

The audit found these plan-aligned foundations:

- Python 3.12/Pydantic domain engine exists.
- RF-1086/RF-1086-U XML generation exists for no activity, stiftelse, simple sale, and dividend fixtures.
- RF-1086 XSD validation exists through local official XSD files.
- RF-1086 readiness blocks unsupported share class and ownership mismatches.
- RF-1086 transaction-code registry records verified/provisional code status.
- Thin CLI exists for RF-1086 simulation, XSD validation, case validation, and public/synthetic validation.
- Narrow ledger supports draft, post, reverse, immutable posted entries, and basic audit events.
- Structured holding-action builders exist for opening balance, admin costs, dividend received, share purchase, share sale, dividend to owner, and shareholder loan.
- Year-end interview data model exists.
- Annual accounts and tax return preview simulations exist.
- Company archive JSON export exists.
- Static Next.js SaaS shell exists with company support-boundary demo, document metadata demo, reviewer comments, and readiness summary.
- Submission-state domain model exists with authority confirmation, preview confirmation, UUID idempotency, failure states, and receipt state.
- Billing-gate domain model exists with founder pricing, standard pricing, readiness charging gate, unsupported-case no-charge, and refund eligibility.

### Discrepancy Inventory

These are the current gaps between implementation and plan.

1. Direct filing is not implemented.
   - Plan requires owner-managed direct filing for `aksjonærregisteroppgaven`, `årsregnskap`, and `skattemelding for AS`.
   - Current state has RF-1086 XML simulation and a submission-state model, but no authority API client, auth flow, system-user flow, feedback retrieval, or official receipt storage.

2. RF-1086 production readiness is still blocked.
   - Plan requires direct filing once accurate.
   - Current code documents `K`, `S`, and `U` transaction code values as production blockers until confirmed by official docs, code list, or Skatteetaten test-environment acceptance.

3. `årsregnskap` is only a preview simulation.
   - Plan requires annual accounts filing to Brønnøysundregistrene.
   - Current implementation computes simple balance/result preview and simulated receipt only. It does not map RR-0002 or annual-account submission payloads, notes, attachments, approval artifacts, or Brønnøysund/Altinn delivery behavior.

4. `skattemelding for AS` is only a simplified preview simulation.
   - Plan requires company tax return direct filing.
   - Current implementation estimates a simplified tax basis from admin costs and `fritaksmetoden` add-back. It does not map Skatteetaten company tax return schemas, tax statement payloads, attachments, validation feedback, or official submission.

5. Official company onboarding is not implemented.
   - Plan requires organization-number-first setup with Brønnøysund fetch, AS verification, address/status import, locked filing identity, and authority guidance.
   - Current web shell validates only a 9-digit org number and provided entity type. There is no Brønnøysund integration or persistent company identity confirmation workflow.

6. Persistent multi-company SaaS data model is missing.
   - Plan requires multiple companies per user from day one with single-company-first UX.
   - Current Python models accept `company_id`, and the web demo has company-scoped arrays, but there is no database schema, tenant model, user-company membership, or migration.

7. Authentication and authorization are missing.
   - Plan requires secure app login, MFA, owner/admin/reviewer/read-only roles, tenant isolation, and explicit authority confirmation.
   - Current code has in-memory role checks in the web demo and a submission confirmation model, but no real auth, MFA, sessions, authorization middleware, or tenant isolation.

8. Document storage is metadata-only.
   - Plan requires in-app accounting document storage, signed access, retention, and archive export.
   - Current implementation stores document metadata and optional `storage_uri`, but no object storage integration, upload/download flow, signed URLs, retention enforcement, virus scanning, or secure deletion/export lifecycle.

9. Bank CSV import and reconciliation are missing.
   - Plan lists bank CSV import, manual transaction entry, and bank reconciliation as core holding actions.
   - Current code has manual holding-action builders and bank balance calculations, but no CSV parser, bank transaction model, matching workflow, reconciliation state, or unreconciled-warning acceptance.

10. Manual journal escape hatch is missing as a product workflow.
    - Plan allows manual journal entry only as an advanced escape hatch with warnings for filing-sensitive accounts.
    - Current ledger can create drafts programmatically, but no manual journal UI/API, no sensitive-account classifier, and no readiness escalation for unstructured entries.

11. Period locking is missing.
    - Plan requires accounting-system discipline: traceability, period locks, corrections instead of silent edits.
    - Current ledger makes posted entries immutable but has no accounting periods, locks, filing locks, or correction policy tied to filed periods.

12. Audit logging is too narrow.
    - Plan requires audit logs for security events, company identity changes, invitations, role changes, posting, corrections, readiness checks, overrides, submissions, and receipts.
    - Current audit events cover only ledger draft/post/reversal lifecycle.

13. Filing overrides are not implemented.
    - Plan allows limited audited filing-field overrides where source data cannot model an authority field.
    - Current code has no override model, explanation requirement, readiness report display, risk classification, or audit event for overrides.

14. Holding actions are not connected into an end-to-end annual workflow.
    - Plan expects owner-level wizards that generate deterministic entries and feed readiness gates.
    - Current holding actions are Python builders tested in isolation. They are not persisted, not surfaced in the web UI, not linked to documents/bank transactions, and not composed into a complete company-year state.

15. Investment register is incomplete.
    - Plan requires investment positions, cost basis, ownership percentage, dividend events, disposal events, and clear tax treatment.
    - Current implementation creates an `InvestmentPosition` in share purchase and updates it in share sale, but there is no durable register, position history, reconciliation to ledger, organization lookup, or securities-specific support boundary.

16. Dividend-to-owner corporate documents are placeholders.
    - Plan requires board proposal and general meeting templates.
    - Current result returns only template titles, not generated documents, content, approval flow, or archive linkage.

17. Tax settlement workflow is missing.
    - Plan requires estimated tax payable/refundable, payment/refund tracking, and prior-year tax settlement difference.
    - Current code estimates tax in preview but does not create tax settlement entries or track payments/refunds.

18. SAF-T compatibility is not designed.
    - Plan says SAF-T export is not required at launch, but ledger data must avoid painful redesign.
    - Current ledger has account strings and journal lines, but no structured chart of accounts metadata, voucher ids, journal ids, party records, period data, or SAF-T compatibility note.

19. Public-data validation is too narrow.
    - Plan requires public annual-account fixtures, public/synthetic holding-company validation, validation reports, and mismatch classification.
    - Current validation harness covers RF-1086 synthetic fixtures and limitations. It does not validate public annual-account totals, annual accounts previews, tax return mappings, or mismatch categories beyond pass/warning/blocked.

20. Private validation plan is not operationalized.
    - Plan recommends later comparison against 3-5 real simple holding cases.
    - Current repository only documents this; it has no anonymized validation protocol, fixture format, comparison checklist, or privacy handling.

21. Deadline reminders and late-filing guidance are missing.
    - Plan requires deadline reminders, overdue status, late filing guidance, and no fine guarantee.
    - Current code has no deadline model, notification scheduler, reminder UI, or overdue classification.

22. Optional accountant review is only a demo.
    - Plan requires optional review access, comments, checklist review, filing preview review, and owner control.
    - Current web shell implements in-memory reviewer comments and acknowledgement only. There is no persisted invitation flow, email, permissions, checklist model, filing-preview-specific review, or audit trail.

23. Billing collection is missing.
    - Plan requires founder cohort support, subscription, filing package, refund rules, and billing gate.
    - Current domain model can decide gates, but there is no payment provider, invoices, checkout, subscription lifecycle, founder cohort persistence, billing admin, or refund process.

24. Production security baseline is missing.
    - Plan requires MFA, RBAC, tenant isolation, encryption, backups, restore tests, signed URLs, GDPR processes, and data processing terms before production.
    - Current repository has no app auth/security implementation beyond local role demo and environment placeholders.

25. Web UI is not yet a usable product.
    - Plan requires Norwegian-first desktop filing UX with mobile-readable status and actual workflows.
    - Current Next.js app is a static dashboard over demo data. It does not call the Python engine, persist data, accept real owner inputs, upload files, execute holding actions, run real readiness gates, preview actual filings, or submit.

26. Product language is partially mixed.
    - Plan requires Norwegian-first user-facing workflows.
    - Current UI is mostly Norwegian but still exposes terms like `Readiness`, `Review`, `Owner workflow`, and internal status strings directly.

27. Authority research maps are incomplete beyond RF-1086.
    - Plan Phase 0 requires annual accounts public fields/RR-0002 requirements and `skattemelding for AS` API surface mapping.
    - Current docs deeply map RF-1086, but there are no equivalent maps for annual accounts or company tax return.

28. Backend/API boundary is missing.
    - Plan anticipates a backend API around the Python filing engine if needed.
    - Current Next.js shell and Python engine are separate. There is no service boundary, queue/job model, or deployment architecture connecting them.

29. Archive export is not productized.
    - Plan requires company archive export at any time and before cancellation.
    - Current archive export writes JSON from annual data. It is not exposed in UI/API, does not bundle actual documents, and is not tied to cancellation or retention policy.

30. Naming/trademark clearance is not done.
    - Plan notes `talli.no` is secured but trademark and company-name checks remain.
    - Current docs record this risk; no clearance workflow or launch checklist exists.

## User Stories

1. As a holding company owner, I want Talli to fetch official company identity from my organization number, so that setup starts from trusted Brønnøysund data.
2. As a holding company owner, I want non-AS entities blocked before onboarding, so that I do not enter data into an unsupported product.
3. As a holding company owner, I want company filing identity fields locked after confirmation, so that filings do not drift from official records.
4. As a holding company owner, I want clear Altinn/authority access guidance during setup, so that I know whether I can file before deadlines.
5. As a holding company owner, I want a persistent company workspace, so that my data survives refreshes and sessions.
6. As a holding company owner with multiple AS companies, I want each company separated under my account, so that data cannot leak between companies.
7. As an owner, I want secure login with MFA for sensitive actions, so that company and filing data is protected.
8. As an owner, I want invited reviewers and read-only users to have scoped roles, so that helpers can access only what they need.
9. As an owner, I want all invitations and role changes audited, so that I can review who had access to company data.
10. As an owner, I want to upload bank statements and accounting documents, so that required evidence is stored with the company year.
11. As an owner, I want secure document download links, so that sensitive accounting documents are not public.
12. As an owner, I want document retention and archive export, so that I can meet documentation expectations and leave Talli without lock-in.
13. As an owner, I want to import bank CSV files, so that simple holding bank activity can be captured cheaply.
14. As an owner, I want bank transactions matched to holding actions, so that readiness can see which entries are reconciled.
15. As an owner, I want unreconciled bank items shown clearly, so that I can fix them or accept a warning where allowed.
16. As an owner, I want manual transaction entry for rare cases, so that I am not blocked by missing import support.
17. As an owner, I want manual journals marked as advanced and risky, so that filing-sensitive accounts are not changed casually.
18. As an owner, I want holding-action wizards in the UI, so that I can record events without writing debit/credit lines.
19. As an owner, I want opening balances entered through a guided flow, so that the first accounting year starts from reconciled data.
20. As an owner, I want admin costs, dividends received, share purchases, share sales, owner dividends, and shareholder loans saved as structured records, so that filing implications are traceable.
21. As an owner, I want every structured action linked to documents and bank transactions where required, so that the archive is defensible.
22. As an owner, I want an investment register, so that positions, cost basis, disposals, and dividends are tracked over time.
23. As an owner, I want investment balances reconciled to the ledger, so that annual accounts and tax return data match.
24. As an owner, I want clear `fritaksmetoden` treatment per investment and dividend, so that taxable add-back is transparent.
25. As an owner, I want unclear investment tax treatment blocked or escalated, so that the app does not pretend a complex tax case is simple.
26. As an owner, I want generated board and general meeting documents for simple dividends, so that corporate paperwork matches accounting entries.
27. As an owner, I want tax settlement entries, so that tax payable/refundable and payments are handled in the annual loop.
28. As an owner, I want posted periods locked after filing, so that submitted years are not silently changed.
29. As an owner, I want corrections posted as reversals or correction entries, so that accounting history remains auditable.
30. As an owner, I want filing-field overrides to require a reason and appear in readiness, so that exceptional manual fixes are visible.
31. As an owner, I want `aksjonærregisteroppgaven` readiness to block production when transaction codes are unverified, so that Talli does not submit guessed authority values.
32. As an owner, I want RF-1086 production filing through the authority flow once validated, so that Talli provides the direct-filing value promised.
33. As an owner, I want official RF-1086 feedback and receipts stored, so that I have proof of delivery.
34. As an owner, I want annual accounts mapped to the correct authority requirements, so that `årsregnskap` is not just a preview.
35. As an owner, I want company tax return mapped to the correct authority requirements, so that `skattemelding for AS` is not just a rough estimate.
36. As an owner, I want separate readiness gates for all three filings, so that each deadline can be handled independently.
37. As an owner, I want shared annual data across filings, so that inconsistencies are caught once and reflected everywhere.
38. As an owner, I want filing previews in Norwegian with authority terminology, so that I can review what will be submitted.
39. As an owner, I want deadline reminders for 31 January, 31 May, and 31 July, so that I do not miss statutory deadlines.
40. As an owner, I want overdue guidance without penalty guarantees, so that Talli stays honest about late filings.
41. As an owner, I want optional accountant review on filing previews, so that I can get help without giving up owner-managed filing.
42. As an accountant reviewer, I want persisted comments and checklist status, so that my review survives sessions and can be audited.
43. As an owner, I want advisory comments distinguishable from hard system blocks, so that I understand what I can acknowledge and what I must fix.
44. As a founder customer, I want founder pricing applied to my company account, so that early adoption risk is reflected in billing.
45. As a founder customer, I want filing packages charged only after readiness passes, so that I do not pay for unsupported work.
46. As a founder customer, I want refunds tracked when Talli fails a supported filing, so that the low-trust startup risk is reduced.
47. As a product operator, I want unsupported cases blocked early, so that low pricing is not destroyed by support-heavy customers.
48. As a product operator, I want support boundaries linked to billing gates, so that unsupported users are not charged for direct filing.
49. As a developer, I want a persistent schema for companies, users, roles, documents, ledger entries, structured actions, filings, submissions, and billing, so that the SaaS product has a real system of record.
50. As a developer, I want the web app to call the same deterministic engine used by CLI tests, so that UI behavior and engine behavior cannot diverge.
51. As a developer, I want API/service seams around onboarding, holding actions, readiness, previews, archive export, and submission, so that browser tests can cover real workflows.
52. As a developer, I want public-data validation expanded beyond RF-1086, so that annual accounts and tax return assumptions are challenged.
53. As a compliance reviewer, I want authority maps for annual accounts and company tax return, so that those engines have source-backed field decisions.
54. As a compliance reviewer, I want official test-environment acceptance recorded before production filing, so that production readiness is evidence-based.
55. As a security reviewer, I want tenant-isolation and role-authorization tests, so that one company cannot access another company's data.
56. As a security reviewer, I want backup and restore tests before launch, so that data loss recovery is proven.
57. As a security reviewer, I want signed document URLs and storage policies tested, so that document access is controlled.
58. As a future implementation agent, I want discrepancy status tracked in one PRD, so that closed prototype issues are not mistaken for launch completeness.
59. As a future implementation agent, I want each gap mapped to high-level modules and test seams, so that follow-up issues can be cut without redoing the audit.
60. As the founder, I want the repo to show exactly what remains before Talli can claim direct filing, so that product risk and build order are clear.

## Implementation Decisions

- Treat this PRD as a bridge between the current prototype and the full plan. It does not supersede `PLAN.md`; it defines the next gap-closure milestone.
- Preserve the current strategic ADRs: holding-first, owner-managed direct filing, deterministic compliance core, Norwegian-first UI, multi-company data model with single-company-first UX, narrow ledger, domain engine before UI, Python engine first, and Talli as working brand.
- Keep RF-1086 as the first production filing target. Do not start production submission for cases requiring `K`, `S`, or `U` RF-1086 code values until those values are verified through official evidence or test-environment acceptance.
- Add authority research maps for `årsregnskap` and `skattemelding for AS` before treating those filing simulations as more than previews.
- Introduce a persistent system of record. The first schema should cover users, companies, company memberships, company identity confirmations, documents, bank transactions, ledger drafts/posts, structured holding actions, investment positions, annual data, filing readiness snapshots, filing previews, submissions, receipts, reviewers, review comments, billing accounts, and audit events.
- Keep the Python engine as the source of deterministic accounting and filing behavior. The web app should call service/API seams that wrap the Python engine or share generated engine outputs, rather than reimplementing filing rules in demo JavaScript.
- Use Supabase/Postgres as the likely first database because the project already has Supabase environment placeholders and user setup. Schema design must include tenant isolation from the start.
- Keep object storage separate from document metadata. Store document metadata in Postgres and document bytes in object storage with signed access.
- Model bank CSV import as a first-class source of bank transactions. Reconciliation should link bank transactions to posted entries or accepted warnings.
- Add period and filing locks before production filing. Filed periods cannot be edited directly; corrections must be new entries.
- Expand audit logs beyond the current ledger-only events. Audit should record security, role, company identity, document, bank import, structured action, posting, readiness, override, billing, submission, and receipt events.
- Convert holding-action builders into persisted workflows. Each action should produce structured business record, draft entry, document requirements, bank-match requirements, support-boundary status, and filing implications.
- Build an investment register with position history. Share purchases and sales should update durable positions and reconcile to ledger accounts.
- Generate actual corporate document artifacts for simple dividends, not only titles.
- Add tax settlement actions for estimated tax, payments/refunds, and prior-year differences.
- Create a filing override model with field target, old value, new value, reason, risk level, approver, audit event, and readiness impact.
- Build deadline status as data, not hardcoded UI text. Deadline rules should generate upcoming, due, overdue, and filed states.
- Connect billing gates to persisted billing accounts. Payment collection can be provider-backed later, but the domain state must not remain only in tests.
- Keep unsupported-case handling blunt and specific. Every blocker should state reason, risk response, and next action.
- Keep user-facing UI Norwegian-first. Replace mixed English UI labels in the product shell where they are visible to users.
- Do not add VAT, payroll, invoicing, broad supplier/customer ledgers, live bank feeds, broker imports, or accountant practice management while closing these gaps.

## Testing Decisions

- Use the highest available seams. Engine behavior should be tested through structured fixtures, CLI/service calls, and generated filing outputs. Web behavior should be tested through user workflows once persistence/API seams exist.
- Keep the current Python unit and CLI tests for RF-1086, ledger, holding actions, annual simulations, submission state, and billing gates.
- Add database-backed integration tests for tenant isolation, company membership, document metadata, structured actions, ledger posting, audit events, and filing readiness snapshots.
- Add service/API tests for company onboarding, Brønnøysund lookup handling, holding-action creation, bank CSV import, reconciliation, document upload metadata, filing preview generation, archive export, and submission preparation.
- Add browser tests for the owner journey: create company, confirm support boundary, enter opening balance, import bank CSV, record holding actions, attach documents, run readiness, review preview, confirm authority, pass billing gate, and view receipt or production blocker.
- Add negative browser/API tests for unsupported entity type, missing authority, unsupported share class, unverified RF-1086 code values, company-to-personal-shareholder loan, missing required documents, unreconciled bank transactions, and cross-tenant access attempts.
- Expand validation fixtures beyond RF-1086. Add annual accounts and tax return fixtures only after source-backed authority maps exist.
- Add public-data validation reports for annual accounts and tax return once the mappings are known. Reports must keep limitations visible.
- Add official test-environment acceptance tests or runbooks before enabling production direct filing.
- Add security tests for MFA-required sensitive actions, role checks, tenant isolation, signed document URLs, audit creation, backup restore, and archive export.
- Add billing tests that prove unsupported cases are not charged, readiness-blocked filings cannot buy a filing package, founder cohort limits are enforced, and supported filing failures become refund-eligible.
- Add deadline tests that cover upcoming, due, overdue, filed, and late-filed states for all three annual obligations.
- Do not write brittle tests against private helper implementation details when a higher-level workflow can prove the requirement.

## Out of Scope

- Changing the product strategy into a generic Fiken clone.
- Adding VAT, payroll, invoicing, customer ledger, supplier ledger, projects, time tracking, inventory, or broad operating-company workflows.
- Building live bank feeds before CSV import and manual reconciliation are proven.
- Building broker imports or high-volume trading support.
- Supporting foreign shareholder withholding tax, unclear foreign investments, multiple share classes, treasury shares, options, warrants, mergers, demergers, liquidation, complex capital reductions, or inheritance/gift cases.
- Supporting company incorporation before an organization number exists.
- Supporting direct amended filings or automatic re-submission as part of this gap-closure milestone.
- Providing legal, tax, investment, or custom accounting advice.
- Offering a penalty/fine guarantee.
- Building an accountant practice dashboard or accountant billing.
- Implementing optional modules that make the launch UI cluttered for simple holding companies.

## Further Notes

- The highest-risk discrepancy is the gap between the public launch promise and current production filing capability. Direct filing is the commercial value, but it must remain blocked until authority integration, verified filing values, security, and receipt storage are real.
- The strongest current implementation area is RF-1086 simulation. The weakest areas relative to the plan are persistence, official authority integration, document storage, auth/security, bank reconciliation, and real annual accounts/tax return mappings.
- The current closed issues should be interpreted as prototype anchors unless they were explicitly completed end-to-end. Future issues should name whether they are adding a domain anchor, persistent workflow, browser workflow, official integration, or production hardening.
- The next implementation breakdown should create smaller issues from this PRD in roughly this order: persistence and tenant model, onboarding/company identity, document storage, bank CSV/reconciliation, structured action persistence, engine/API integration, annual filing authority maps, RF-1086 production validation, billing collection, security hardening, and production filing runbooks.
- `talli.no` is secured, but trademark and company-name clearance still need a launch checklist before public use.
