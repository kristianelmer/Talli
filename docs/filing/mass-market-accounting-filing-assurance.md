# Accounting and filing assurance for mass-market launch

Research date: 2026-08-26  
Question: What must Talli prove before an eligible holding company can use it as
its only accounting product and directly file RF-1086, the company tax return,
and annual accounts at unrestricted scale?

This note separates legal duties, filing-authority requirements, and prudent
launch evidence. It is official-source research, not legal or accounting advice.

## Answer

There is no single approval that makes Talli safe to sell as an accounting and
filing product. Mass-market launch needs all four of these gates:

1. **Accounting-system gate:** Talli must meet the bookkeeping, documentation,
   retention, period-closing, control-trail, balance-documentation, and SAF-T
   duties that apply when it is the company's only electronic accounting system.
2. **Supported-case gate:** Talli must accept only cases for which its ledger,
   accounting treatment, tax calculation, annual-account presentation, notes,
   and all three filings are complete. Unsupported facts must stop onboarding or
   filing, not become warnings that a normal owner is expected to understand.
3. **Authority gate:** Each filing path must have current production permission,
   customer authority, current-year schemas and rules, successful official test
   evidence, safe submission-state handling, and verified receipt/final-outcome
   retrieval.
4. **Launch-evidence gate:** Representative supported cases must reconcile from
   source document to ledger to all three filings, pass independent parallel-run
   checks, and complete controlled real-company production filings before
   unrestricted sales open.

Talli's existing TT02 work is valuable transport evidence, but it is not enough
for mass-market launch. It covers a supported no-activity shape for each filing,
while persisted structured company-tax feedback and final filing state remain
open, and the annual-accounts processing decision remains pending. It also does
not prove the wider supported case set, production operation, or statutory
accounting-system duties.

The clearest newly identified hard gap is **SAF-T**. Talli's earlier product
decision says SAF-T can wait until after launch. That is not a safe reading for
an electronic accounting system. Skatteetaten says the turnover exception does
not help a business that nevertheless keeps its booked data electronically, and
SAF-T 1.40 becomes the only valid format from 1 January 2027. Talli should treat
a validated SAF-T 1.40 export as a launch requirement, not future compatibility.

## 1. Mandatory duties for the company and its accounting system

These are legal/accounting duties. Authority API acceptance does not prove that
they have been met.

### Complete, real, accurate, traceable bookkeeping

Every AS is subject to accounting and bookkeeping duties. The bookkeeping
system must be orderly and capable of producing mandatory reports and
specifications. Transactions must be complete, real, accurate, current,
documented, and linked by a two-way control trail from source documentation to
specifications and statutory reporting. Accounting material must be protected
against unauthorized change, deletion, and loss. See
[bokføringsloven §§ 2 and 4](https://lovdata.no/dokument/NL/lov/2004-11-19-73/%C2%A74)
and [Altinn's bookkeeping overview](https://info.altinn.no/starte-og-drive/regnskap-og-revisjon/regnskap/bokforingsplikt).

For Talli this means, at minimum:

- every bank transaction and every supported holding action is either posted,
  explicitly excluded with a reason, or left as a visible reconciliation item;
- every posting has a stable voucher/document reference and can be traced both
  ways between the document, ledger, calculation, and filing fields;
- posted data used in a closed reporting period cannot be silently edited;
- user-visible specifications can be reproduced for the retained period; and
- system documentation explains the data model, control trail, calculations,
  period closing, corrections, and export/recovery paths well enough for a
  control authority to inspect them.

Bookkeeping must be up to date according to the nature and volume of the
business and, as a main rule, no less often than every four months. It must be
current before statutory reporting. See
[bokføringsloven § 7](https://lovdata.no/dokument/NL/lov/2004-11-19-73/%C2%A77).

### Documents and balance support

Booked information must be supported by correct and complete documentation.
When annual accounts and the business specification are prepared, all material
balance-sheet positions must be documented. For a holding company this includes
bank and loan statements from financial institutions, statements for registered
financial instruments, and the method and assumptions behind valuations,
impairments, and provisions. See
[bokføringsloven §§ 10-11](https://lovdata.no/dokument/NL/lov/2004-11-19-73/%C2%A710)
and
[bokføringsforskriften §§ 6-2 to 6-4](https://lovdata.no/dokument/SF/forskrift/2004-12-01-1558/KAPITTEL_6).

A live bank feed is useful transaction capture, but it is not by itself the
required year-end support. Talli must also retain or obtain the relevant bank,
loan, securities, dividend, share transaction, and valuation documents.

### Closing and corrections

After the applicable reporting deadline has passed, booked information must not
be changed or deleted. Corrections must be new, documented postings that fully
reverse the original posting; deletions must remain visible in documentation or
specifications. See
[bokføringsloven § 9](https://lovdata.no/dokument/NL/lov/2004-11-19-73/%C2%A79).

If electronic booked data is retained instead of finished periodic
specifications, accounting periods must be closed with reliable protection
against later change or deletion, and the closing mechanism must be documented
and retained for five years. See
[bokføringsforskriften § 7-6](https://lovdata.no/dokument/SF/forskrift/2004-12-01-1558/%C2%A77-6).

Therefore Talli needs separate states for draft, posted, closed, corrected, and
reversed records. An audit-log entry alone is not a substitute for a legally
valid reversal/correction entry.

### Retention, backup, readability, access, and exit

Primary accounting material — annual reports and other statutory reporting,
specifications or the booked data needed to reproduce them, source documents,
control-trail material, and balance documentation — is generally retained for
five years after year-end. Important secondary material is generally retained
for three years and six months. Electronic booked data must remain
electronically available for three years and six months. See
[bokføringsloven §§ 13 and 13 b](https://lovdata.no/dokument/NL/lov/2004-11-19-73/%C2%A713)
and [Altinn's current retention guide](https://info.altinn.no/starte-og-drive/regnskap-og-revisjon/regnskap/oppbevaring-av-regnskapsmateriale/).

Electronic material needs a separate backup and must remain readable throughout
the retention period. If a company delegates bookkeeping or retention, the
company remains responsible; the service provider also has a duty to assist
control authorities with access to the accounting system and material. See
[bokføringsforskriften §§ 7-1 and 7-2](https://lovdata.no/dokument/SF/forskrift/2004-12-01-1558/KAPITTEL_7)
and
[bokføringsloven § 14](https://lovdata.no/dokument/NL/lov/2004-11-19-73/%C2%A714).

The April 2025 Norwegian bookkeeping standard on safeguarding accounting
material adds an important cloud-service point: when storage is outsourced, the
company must ensure by agreement that access is not restricted during the
retention period, and the risk assessment and safeguards should be documented.
See
[NBS 1, current edition](https://www.regnskapsstiftelsen.no/bokforing/bokforingsstandarder/nbs-1-sikring-av-regnskapsmateriale/).

Talli's cancellation path must therefore do more than create a convenient JSON
download. It must prove that the customer can obtain a complete, readable
archive containing the statutory specifications or reproducible booked data,
source/support documents, balance documentation, period and correction history,
filing previews/payload references, official receipts and decisions, and the
system/control-trail description. Deleting Talli's only retained copy before
the duty has been safely transferred would leave the company exposed.

### SAF-T is a launch duty, not a later option

Skatteetaten says electronically available booked data must be reproducible in
the prescribed SAF-T format and supplied when requested in a control. The
under-NOK-5-million turnover exception does not apply where the company
nevertheless has its booked information electronically available. That is the
normal case when Talli is the company's electronic accounting system. See
[Skatteetaten's SAF-T overview](https://www.skatteetaten.no/bedrift-og-organisasjon/starte-og-drive/rutiner-regnskap-og-kassasystem/saf-t-regnskap/)
and
[bokføringsforskriften §§ 7-7 and 7-8](https://lovdata.no/dokument/SF/forskrift/2004-12-01-1558/%C2%A77-8).

Skatteetaten's current format page says SAF-T Financial 1.40 may be used now and
becomes the only valid version from 1 January 2027; versions 1.20 and 1.30 may
only be used for earlier periods as specified there. See
[current SAF-T documentation](https://www.skatteetaten.no/bedrift-og-organisasjon/starte-og-drive/rutiner-regnskap-og-kassasystem/saf-t-regnskap/dokumentasjon/).

Launch evidence should include a SAF-T 1.40 file for every supported golden
case, official-XSD validation, account/code mapping checks, opening and closing
balances, voucher/document references, debit-credit reconciliation, and a
round-trip/control report that ties the export back to Talli's ledger and
mandatory specifications.

### 2027 and 2030 changes must be tracked

Norway enacted new bookkeeping changes in June 2026. The provisions changing
definitions, sales/purchase documentation, balance documentation, and retention
enter into force on 1 January 2027; mandatory use of an electronic accounting
system enters into force on 1 January 2030. Government guidance describes an
e-invoice sending duty from 2027 and electronic-system/e-invoice receipt duties
from 2030, subject to implementing rules and exceptions. See the
[commencement decision](https://lovdata.no/dokument/LTI/forskrift/2026-06-19-1154),
the [enacted amendment text](https://www.regjeringen.no/no/dokumenter/prop.-44-l-20252026/id3152698/?ch=11),
and the
[Finance Ministry summary](https://www.regjeringen.no/id3153196/).

Talli should maintain a dated law-and-specification watch. Before launch it must
either support any provisions already in force for its customers or record a
source-backed reason that a provision does not apply. By 2030, a product sold as
the only accounting system will need a clear way to receive and process the
electronic purchase documents its holding-company customers receive.

## 2. Annual accounts and company responsibility

An AS must prepare annual accounts for each year. The accounts include income
statement, balance sheet, and notes; small enterprises may omit a cash-flow
statement and annual report, but the exact small-enterprise and audit boundary
must be checked. Annual accounts follow the Accounting Act and good accounting
practice, including the current
[NRS 8 for small enterprises](https://www.regnskapsstiftelsen.no/regnskap/regnskapsstandarder/nrs-8-god-regnskapsskikk-for-sma-foretak/).
See also
[regnskapsloven §§ 3-1 to 3-5](https://lovdata.no/dokument/NL/lov/1998-07-17-56/KAPITTEL_3)
and [Altinn's annual-accounts guide](https://info.altinn.no/starte-og-drive/regnskap-og-revisjon/regnskap/arsregnskap/).

All board members and the general manager, if any, sign the annual accounts.
The ordinary general meeting must be held within six months after year-end and
approves the annual accounts. See
[regnskapsloven § 3-5](https://lovdata.no/dokument/NL/lov/1998-07-17-56/%C2%A73-5)
and
[aksjeloven § 5-5](https://lovdata.no/dokument/NL/lov/1997-06-13-44/%C2%A75-5).

Complete annual accounts are sent within one month after adoption. For a
calendar-year company, 31 July is the last date to avoid a late fee. The board
remains responsible even if a software supplier, accountant, or auditor is
expected to send them. See
[Brønnøysundregistrene's submission page](https://www.brreg.no/innsending-av-arsregnskap/).

This means Talli must show the owner exactly what is being approved, capture the
real corporate approvals and dates rather than infer them, and block submission
when small-enterprise status, audit status, notes, attachments, signatures, or
general-meeting approval are unresolved.

## 3. Tax-return responsibility

The company must give correct and complete information, act carefully and
loyally, and notify the tax authorities about errors. Delegating work to a
system supplier does not transfer that responsibility. See
[skatteforvaltningsloven §§ 8-1 and 8-2](https://lovdata.no/dokument/NL/lov/2016-05-27-14/KAPITTEL_8)
and
[Skatteetaten's current explanation of the duty](https://www.skatteetaten.no/rettskilder/type/handboker/skatteforvaltningshandboken/gjeldende/kapittel-8-opplysningsplikt-for-skattepliktige-trekkpliktige-mv/ID-8-1.001/ID-8-1.003/).

An AS must retrieve and submit its tax return and business specification through
an accounting or year-end system, even with no turnover. The ordinary deadline
is 31 May. Imported/pre-filled data must be checked and corrected before
submission. See
[Skatteetaten's company tax-return page](https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/selskap/).

A company can normally change the previous three income years by submitting a
new complete set for that year in the same format used for that year. See the
same company page and
[skatteforvaltningsloven § 9-4](https://lovdata.no/dokument/NL/lov/2016-05-27-14/%C2%A79-4).

Talli therefore needs an owner review that exposes imported facts, Talli's
classifications and calculations, unresolved warnings, and the complete filing
preview. A generic disclaimer does not replace this control.

## 4. RF-1086 responsibility

Every ordinary Norwegian AS must file RF-1086 annually unless a stated
exception applies. The deadline is 31 January. Since June 2026, the filing and
all change reports for earlier years must go through an end-user system, not the
old Altinn form or paper route. A rejected filing is not a completed filing and
can prevent correct pre-filling for shareholders. See
[Skatteetaten's current RF-1086 page](https://www.skatteetaten.no/skjema/rf-1086-aksjonarregisteroppgaven/).

Talli must reconcile opening and closing share capital, share count, each
shareholder's movement, dividends, and relevant corporate actions before
submission. It should not infer a clean shareholder history merely because the
ledger balances.

## 5. Mandatory filing-authority requirements

These requirements govern technical access and filing conformance. They do not
certify the accounting treatment behind an accepted payload.

### Requirements shared across Skatteetaten services

Talli needs a Norwegian organization number, Maskinporten onboarding, explicit
access to each API, customer authority through the current Altinn/Systembruker
model, correctly scoped production clients and keys, and valid customer and
data-processing agreements. Skatteetaten's supplier terms require service-
specific conformance, integration testing with synthetic data, documented
security/privacy controls, access control, customer support, incident and
contingency handling, and monitoring of authority changes and service status.
Skatteetaten may ask for test documentation. See
[Skatteetaten's API onboarding overview](https://skatteetaten.github.io/api-dokumentasjon/),
[Systembruker guidance](https://skatteetaten.github.io/api-dokumentasjon/om/systembruker),
and
[supplier terms](https://www.skatteetaten.no/samarbeidspartnere/sluttbrukersystemer/bruksvilkar/).

Production permission is service-specific. A successful TT02 run is evidence
for an application or release decision; it is not itself production approval.

### RF-1086

The current API requires the Maskinporten scope
`skatteetaten:innrapporteringaksjonaerregisteroppgave`, Skatteetaten access,
Systembruker authority, the required Altinn resource/access package, and the
documented main-form, sub-form, confirm, document, and prefill operations. Main
and sub forms must validate against the authority XSDs and follow the current
filling guidance. See the
[official RF-1086 API documentation](https://skatteetaten.github.io/api-dokumentasjon/api/innrapportering-aksjonaerregisteroppgave)
([current source snapshot](https://github.com/Skatteetaten/api-dokumentasjon/blob/a4cfe533fd542ff70c684846621ed729c0f2f17e/docs/api/innrapportering-aksjonaerregisteroppgave.md)).

Every new POST requires a new UUID idempotency key. A retry of the same logical
call must reuse the same key and identical body to receive the same response.
Feedback must be retrieved and classified; transport acceptance alone is not
evidence that RF-1086 was approved. Skatteetaten publishes control outcomes and
sends correction instructions when a filing fails controls. See
[the control-outcome notice](https://www.skatteetaten.no/samarbeidspartnere/sluttbrukersystemer/sbs-nyheter/oversikt-over-kontrollutslag-fra-aksjonarregisteret/).

### Company tax return

Talli must use Skatteetaten's current system-supplier repository for the exact
income year: information models, XSDs, code lists, calculations, controls,
texts, test guidance, validation API, and Altinn 3 submission flow. See
[Skatteetaten/skattemeldingen](https://github.com/Skatteetaten/skattemeldingen)
and the
[current tagged source at the research date](https://github.com/Skatteetaten/skattemeldingen/tree/d2c0b7e18d378f845129f4459648d968c543a248)
(`v1.62.81`).

The flow must fetch the current document where required, use the correct
document reference, validate against the current draft rather than the looser
pre-draft test endpoint, upload the complete current-year envelope to the
correct Altinn instance, hand final review/submission to an authorized person,
and retrieve the delayed official feedback and archive. The current official
guide describes the instance lifecycle and warns that feedback can take time.
See the
[official API/Altinn 3 guide](https://github.com/Skatteetaten/skattemeldingen/blob/d2c0b7e18d378f845129f4459648d968c543a248/docs/api-v2/README.md).

Talli's 2025 evidence is pinned to `v1.62.47`, while the official repository had
advanced to `v1.62.81` by this research date. This does not automatically mean
the 2025 payload is wrong, but it creates a mandatory source-drift review: diff
the relevant year, calculation, mapping, code-list, control, and API changes;
record applicability; then rerun affected tests before launch.

### Annual accounts

Annual-account system submission uses the current versioned Altinn app and its
schemas. A Systembruker can create, fill, upload, and lock a filing, but a person
using ID-porten must sign. Signing is the final step and automatically submits.
See
[Brønnøysundregistrene's system-submission guide](https://brreg.github.io/docs/apidokumentasjon/regnskapsregisteret/maskinell-innrapportering/hvordan-sende-inn/).

Brønnøysundregistrene expects system suppliers to test with synthetic TT02 data,
summarize what was tested and all remaining defects before production, and be
able to provide the test documentation on request. See
[the official test and production guide](https://brreg.github.io/docs/apidokumentasjon/regnskapsregisteret/maskinell-innrapportering/test-og-produksjon/).

Receipt/archival state is not the final processing decision. The company gets a
decision in Altinn. If rejected, the decision says what must be fixed. See
[Brønnøysundregistrene's feedback guide](https://www.brreg.no/innsending-av-arsregnskap/tilbakemelding-pa-arsregnskap/).

An accepted and registered annual account generally cannot simply be changed.
A replacement is ordinarily possible only within five months after the filing
deadline; later correction is narrow and needs an accounting explanation, a
new general-meeting approval, and a new auditor report where relevant. See
[the official correction guide](https://www.brreg.no/innsending-av-arsregnskap/korrigering-av-tidligere-innsendt-arsregnskap/).

## 6. Required supported-case controls

"Simple holding AS" is Talli's product boundary, not a legal exemption. The
normal owner should never need to know that an apparently simple fact changes
the accounting or filing treatment.

Before purchase and again before every filing, Talli should fail closed unless
all of these are resolved:

- the entity is an active Norwegian AS and the user has the required authority;
- accounting year, formation/closure status, prior submissions, and correction
  status are known;
- small-enterprise, audit, annual-report, group-account, and consolidation
  status are known;
- all bank accounts and transactions reconcile to source data and the year-end
  balance is supported by the financial institution;
- all shareholdings and securities reconcile by quantity, cost, book value, tax
  value, ownership category, events, dividends, sales, gains/losses,
  impairments, and year-end statements;
- share capital, share classes, shareholders, shareholder movements, dividends,
  and corporate approvals reconcile between the share register, ledger,
  RF-1086, annual accounts, and tax return;
- tax classifications are explicit, including whether the exemption method and
  three-percent inclusion apply, and foreign or withholding-tax facts are absent
  or fully supported;
- loans, intercompany balances, shareholder balances, group contributions,
  related-party matters, and unusual distributions are absent or covered by a
  tested supported rule;
- no payroll, VAT, customer invoicing, regulated activity, or other workflow is
  present unless Talli has deliberately added and assured it;
- opening balances and current-year history for mid-year joiners reconcile to
  prior annual accounts, tax data, bank data, securities data, and supporting
  documents; and
- all required notes, attachments, approvals, warnings, and authority feedback
  are complete.

Unknown, contradictory, manually overridden, or unclassified facts must block
the affected filing. A warning is suitable only where the rule permits the
owner to make a real informed choice and Talli records that choice.

## 7. Recommended evidence before unrestricted launch

The following evidence is not a statutory checklist. It is the minimum prudent
proof for Talli's public claim that eligible companies need no other accounting
product.

### A. Source and rule evidence

- A dated requirements matrix from every supported ledger/tax/accounting rule to
  the exact official law, NRS/NBS paragraph, authority field, schema, code list,
  calculation version, and implemented test.
- Immutable copies or hashes of every authority schema and version used, with
  an annual and emergency source-drift process.
- A product boundary register showing each fact as supported, blocked, or
  warning, with the source and test for that response.
- A documented accounting-system description covering control trail, period
  closing, corrections, retention, backup, restore, SAF-T, and exit.

### B. Deterministic accounting and calculation evidence

- Golden cases for every supported transaction combination, not only one case
  per feature in isolation.
- Negative cases proving unsupported and internally inconsistent companies stop
  before posting or filing.
- Double-entry, period, opening/closing balance, rounding, and year-over-year
  invariants.
- A field-level calculation trace from source facts and posted entries through
  annual accounts, RF-1086, tax return, and authority payloads.
- Cross-filing reconciliations for share capital, equity, dividends, ownership,
  investments, gains/losses, tax basis, result, tax, and opening/closing values.
- Current official XSD validation, authority validation, and expected feedback
  checks for every golden filing case.

### C. Real-company validation evidence

- A representative free pre-launch group covering the supported patterns and
  meaningful year-end combinations.
- For every company: documented consent/authority, complete source-document and
  opening-balance reconciliation, and a parallel run against the company's
  previously accepted filing, accountant-prepared result, or established
  accounting/year-end product.
- Every difference classified as Talli defect, source-data defect, permitted
  accounting choice, or unresolved. Unresolved material differences block
  launch.
- Controlled production completion for each filing path, including the final
  authority outcome rather than just upload/receipt. The number and mix should
  be decided from the supported-case risk matrix; no official source provides a
  magic sample size.

### D. Submission and recovery evidence

- A durable journal recording logical filing ID, exact payload hash, schema/rule
  version, user approval, authority instance/transmission IDs, idempotency keys,
  every state transition, feedback, receipt, final decision, and correction.
- RF-1086 retries reuse the same idempotency key and identical body for the same
  call; a changed body is a new, explicit operation.
- For Altinn instance flows, a timeout or network failure enters `unknown`, then
  Talli reads and reconciles the existing instance/process/data/receipt before
  creating or advancing anything. Blind retry or a second instance is blocked.
- Drills for rejection, delayed feedback, expired authority, partial upload,
  duplicate click, user abandonment before signature, authority outage,
  correction, and rollback/kill switch.
- A filing is shown as complete only after the filing-specific final authority
  outcome is stored. `uploaded`, `signed`, `receipt available`, `in archive`, and
  `approved/registered` remain separate states.

### E. Accounting archive and continuity evidence

- SAF-T 1.40 conformance and reconciliation evidence.
- A complete company archive restored and reviewed from a clean environment.
- Proof that source/support documents, bookkeeping specifications, balance
  support, corrections, system documentation, filings, receipts, and decisions
  remain readable for the required period.
- Cancellation, provider failure, and customer export drills demonstrating that
  access is not lost when the subscription ends.

## 8. What Talli has proved and what remains

The repository already contains strong foundations:

- deterministic filing code and official-schema validation for a narrow subset;
- a no-activity TT02 RF-1086 run through confirm and archive;
- a no-activity TT02 company-tax run through validation, personal signing,
  feedback retrieval, and archive; and
- a TT02 annual-accounts run through schema validation, personal signing,
  receipt, and archive.

See the existing
[RF-1086 evidence](./evidence/rf1086-tt02-2026-07-14.md),
[company-tax evidence](./evidence/company-tax-tt02-2026-07-14.md), and
[annual-accounts evidence](./evidence/annual-accounts-tt02-2026-07-14.md).

Before mass-market launch, the evidence still needs to close at least these
gaps:

1. Implement and validate SAF-T 1.40 and replace the "SAF-T later" assumption.
2. Complete current-source drift review, including the tax-specification change
   from Talli's tested `v1.62.47` snapshot to the applicable current version.
3. Persist and classify the company-tax authority feedback/final filing state,
   and capture the final annual-accounts processing decision.
4. Finish and test annual-account notes and attachment boundaries for every
   supported profile.
5. Expand official test evidence from no-activity to every supported filing
   archetype and combination identified by the risk matrix.
6. Obtain the required production permissions and customer authority; implement
   production adapters without weakening the owner review/signature boundary.
7. Prove durable submission journals, unknown-outcome recovery, correction, and
   final authority outcomes in the deployed runtime.
8. Prove the statutory accounting archive, backup/restore, period closing,
   control trail, and customer exit path.
9. Reconcile representative real companies and finish controlled production
   runs before opening unrestricted sales.

## 9. Internal research versus a narrow accountant review

Most assurance work can and should be completed internally from official
sources:

- legal and authority requirement matrices;
- current-year schemas, code lists, calculations, validation, and access flows;
- bookkeeping mechanics, control trail, period closing, SAF-T, retention,
  correction, archive, and recovery;
- deterministic calculations with explicit official rules;
- supported-case blocks and cross-filing reconciliations; and
- real-case parallel runs and difference reports.

Use free authority support first for access, schema, field, validation, receipt,
and processing-status questions. Those are questions for Skatteetaten,
Brønnøysundregistrene, Altinn, or Digdir, not an accountant.

No official source found in this research imposes a blanket accountant review
on a small AS that validly has no audit requirement. A paid review is therefore
not an automatic launch gate. It becomes justified only if internal research
leaves a material accounting judgment unresolved or the parallel runs disagree.

If that trigger occurs, buy a narrow review rather than broad consulting. The
best review package would contain Talli's proposed entries, calculations,
cross-filing output, source citations, and exact questions for representative
cases involving:

- classification, measurement, impairment, and disposal of shares/securities;
- dividend timing, the exemption method, the three-percent inclusion, and
  deductible/non-deductible costs or losses;
- shareholder/intercompany loans, distributions, and group contributions;
- opening balances and prior-period errors for mid-year onboarding; and
- annual-account presentation and notes for Talli's actual supported profiles.

The review should return written answers tied to exact cases and sources. It
should not be described as authority certification, and no review should be
purchased without separate cost approval.

## Launch decision

**Do not open unrestricted sales yet on accounting/filing assurance alone.**
The route is clear, but the required proof is not complete. Existing TT02
evidence should be retained as the foundation. The next hard gates are SAF-T
1.40, current-source reconciliation, final feedback/decision handling,
supported-case coverage, statutory archive/closing controls, and representative
real-company production validation.
