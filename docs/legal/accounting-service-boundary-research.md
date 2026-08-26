# Talli's accounting-service boundary

Status: research note for issue #182  
Research date: 2026-08-26  
Scope: current Norwegian law and official Norwegian sources only

## Short answer

Talli can remain an ordinary software provider if the customer company, acting
through its owner or another authorized representative, supplies the facts,
reviews the result and remains the person who decides what is booked and filed.
Programmed rules may classify transactions, create entries, validate the ledger,
prepare mandatory reports and transmit them through official APIs. Official
preparatory works expressly place programmed preparation—including machine
learning—outside regulated accounting when people at the supplier do not decide
how the customer's real transactions should be booked and the supplier does not
take responsibility for the accounting result. The Ministry later retained the
same scope and described ordinary system deliveries as outside the law.
([NOU 2018: 9, chapter 3.1.2](https://www.regjeringen.no/no/dokumenter/nou-2018-9/id2602796/?ch=4),
[Prop. 130 L (2021–2022), chapter 3.1](https://www.regjeringen.no/no/dokumenter/prop.-130-l-20212022/id2919163/?ch=3))

The boundary changes when a Talli employee, contractor or human operator uses a
customer's actual records to make the accounting decision, correct or approve
the result, prepare a mandatory report, or otherwise accept responsibility for
its legal correctness. That is the substance of `regnskapsføring for andre`, not
ordinary software support. If done as part of Talli's commercial business, it
may only be performed by an approved accounting enterprise.
([Regnskapsførerloven §§ 1-1, 1-2 and 2-1](https://lovdata.no/dokument/NL/lov/2022-12-16-90))

The published sources resolve the core software-versus-human-work distinction.
They do not specifically classify Talli's full combination of automated posting,
owner-controlled direct filing, customer-record access during support and
pre-launch parallel-run validation. Before an unrestricted paid launch, Talli
should therefore obtain one narrow written determination from Finanstilsynet on
the exact facts listed under “Clarification still needed.” The Act expressly
allows Finanstilsynet to decide in doubtful cases whether the Act applies.
([Regnskapsførerloven § 1-1](https://lovdata.no/dokument/NL/lov/2022-12-16-90))

## Product facts used for this classification

This note assumes the product model currently recorded in the repository:

- Talli is paid self-service software for a simple Norwegian holding AS.
- Deterministic software imports transactions, applies programmed rules, creates
  proposed or final ledger entries, runs validations and prepares the annual
  reports supported by the product.
- The customer owner or legal representative provides the source facts, reviews
  the entries and filing preview, resolves warnings, authenticates, confirms and
  submits. Talli does not sign as an accountant or claim accountant approval.
- Talli offers general help pages and support email. Support explains the
  software and its supported boundary; it does not take over the customer's
  accounting, review, deadline or filing duties.
- Any support access to customer records is least-privilege, read-only by
  default, time-limited, requested or incident-gated and logged.
- An operational agent may help run Talli's own business, but is not embedded as
  a customer-facing accountant and is not allowed to make customer accounting
  decisions.

If any of these facts changes, the classification must be repeated.

## Plain classification by issue category

| Issue category | Allowed | Conditional | Outside the unlicensed boundary |
| --- | --- | --- | --- |
| Self-service software | Programmed import, posting, validation, reporting and customer-controlled filing. | Automatic handling of real transactions and reports must retain customer control, no supplier-person judgment and no Talli result responsibility; obtain the narrow Finanstilsynet determination below. | Talli people perform the customer's bookkeeping/reporting duties or approve the result. |
| Onboarding | Teach the app and configure future programmed rules. | Customer-specific setup is safe only before Talli staff process actual transactions, opening balances or reports. | Staff enter, classify, correct or approve real customer accounting data. |
| Help content | General product instructions, examples, field definitions and links to official guidance. | Examples must stay general and leave the real-case choice to the customer. | Content sold or delivered as an answer/approval for a named customer's actual accounting case. |
| Support email | Explain app state, technical errors, programmed rules and product limits. | Staff may see limited records to reproduce a technical fault but must not assess accounting correctness. | Recommend or choose the account, tax treatment, value, period or filing answer for a real item; reconcile, correct or approve the result. |
| Validation work | Automated checks and synthetic/public test cases. | Parallel-run real customer data only as product testing, without record changes, assurance or customer reliance, pending Finanstilsynet confirmation. | Human quality assurance of the customer's books/reports, correction work or a statement that the result is correct. |
| Filing assistance | Software prepares output; the customer reviews, authenticates, confirms/signs and commands submission with own-business authority. | Backend transport after customer approval, and exact treatment of each report, should be confirmed in writing. | Talli staff prepare, alter, approve or submit as the customer's accountant/service provider. |
| Operational agent | Work on Talli's own code, operations and technical ticket triage. | Customer-data access only for technical telemetry or deterministic repair under the same support controls. | Customer-specific accounting judgment, ledger/report edits, substantive warning clearance or accountant-like approval. |
| Customer records | Automated processing under the product and tightly controlled read-only technical support access. | Access must be necessary, customer-authorized, time-limited, least-privilege and logged; the customer makes accounting changes. | Talli staff use the records to perform, correct, reconcile or approve the customer's statutory accounting work. |

## The legal test

The current Act applies to the right to perform accounting commercially for
others. “Accounting” means performing the client's duties under the Bookkeeping
Act and Accounting Act and preparing mandatory accounting reports under
Bookkeeping Act section 3. Only an approved accounting enterprise may perform
that work commercially for others.
([Regnskapsførerloven §§ 1-1, 1-2 and 2-1](https://lovdata.no/dokument/NL/lov/2022-12-16-90))

The official sources give four practical tests:

1. **System or service?** Developing and setting up accounting software is
   outside the Act. Using it as a service provider to handle a customer's actual
   transactions is inside when the provider's people make the accounting
   decisions. Customer-specific programmed setup remains outside if the provider
   does not also use the system to register the customer's real transactions.
2. **Programmed or human judgment?** Programmed preparation of bookkeeping and
   mandatory reports is outside, including automated or machine-learning rules.
   A person at the supplier deciding how an actual transaction or document is
   booked is inside.
3. **Who owns the result?** A central fact is whether the provider accepts
   responsibility toward the customer for the booked transactions and mandatory
   reports meeting legal requirements. Professional and technical knowledge may
   be sold without authorization if the provider does not accept that result
   responsibility. A contract label alone cannot safely change what the service
   actually does.
4. **Commercial work for another?** Work for the provider's own business and
   work an employee performs for their employer is outside. Commercial external
   accounting is inside. Truly unpaid, occasional help is outside the commercial
   criterion, but a structured validation programme run to develop a paid
   product has a commercial purpose and should not rely on the “friend service”
   exception without a specific ruling.

The first three tests come directly from the detailed system boundary in
[NOU 2018: 9, chapter 3.1.2](https://www.regjeringen.no/no/dokumenter/nou-2018-9/id2602796/?ch=4).
The Ministry confirmed that system deliveries are outside, handling concrete
transactions is accounting, and the law remains technologically neutral in
[Prop. 130 L (2021–2022), chapter 3.1](https://www.regjeringen.no/no/dokumenter/prop.-130-l-20212022/id2919163/?ch=3).
The same NOU explains that “commercially” requires an economic aim, some scope
and duration, and business organization; genuinely unpaid voluntary help and
sporadic favors fall outside.

Finanstilsynet's current public boundary guidance is consistent with this
reading: work integrated into the customer's accounting system, mandatory
accounting reporting and fulfillment of bookkeeping-documentation duties can
require approval, while narrowly separated non-bookkeeping work may not. A
normal customer relationship is not the statutory exemption for collaborating
enterprises.
([Finanstilsynet: who needs approval as an accounting enterprise](https://www.finanstilsynet.no/tillatelser/regnskapsselskap/hvem-ma-ha-godkjenning-som-regnskapsforetak/))

The customer cannot transfer its own statutory responsibility away merely by
using an accountant. The official preparatory works state that the bookkeeping
and accounting entity remains fully responsible even when work is delegated.
That means an owner confirmation is important to Talli's operating model, but
it does not make customer-specific human accounting work unregulated.
([NOU 2018: 9, chapter 3.1.2](https://www.regjeringen.no/no/dokumenter/nou-2018-9/id2602796/?ch=4))

## Allowed: ordinary software activity

These activities fit the official description of a system delivery, provided
the assumptions above remain true:

| Talli activity | Why it stays outside regulated external accounting |
| --- | --- |
| Build and operate the ledger, filing engine, eligibility rules and bank/API integrations | Development and operation of accounting software is a system delivery. |
| Configure programmed posting rules for the supported holding-company profile or for one customer | Even customer-specific setup is outside when Talli does not also have a person register or decide the customer's actual transactions. |
| Automatically import bank transactions and documents | Receipt by software is not the deciding fact; the boundary changes if Talli's people assess the actual items. |
| Automatically propose or post entries using fixed, disclosed rules | Official preparatory works expressly allow programmed preparation. The customer must be able to review/correct and remain responsible. |
| Automatically validate completeness, balances, supported-case rules and report schemas | Programmed checks are part of the software. Do not describe them as human/accountant approval. |
| Automatically create a draft or filing-ready tax return, annual accounts or shareholder register statement | Programmed preparation is outside on the published system boundary. Human preparation of the customer's actual report is different. |
| Give general help pages, examples, field definitions and product instructions | General education and software guidance do not perform one named customer's statutory duties. |
| Answer technical support questions about login, integrations, app state, exports, receipts and known software errors | This explains or repairs the system without deciding what the customer's accounting should say. |
| Fix a code defect and rerun deterministic processing for all affected customers | The change is to the software rule. A human must not silently choose or edit an individual customer's accounting result. |
| Let the customer's authorized representative review, authenticate, sign and submit through Talli | Official reporting systems are expressly designed for end-user-system delivery. For example, all AS tax returns must be delivered through an accounting/year-end system, and shareholder register statements must use an end-user system from June 2026. ([Skatteetaten: tax return for companies](https://www.skatteetaten.no/bedrift-og-organisasjon/utenlandsk/skattemelding-og-skatteoppgjor/skattemelding-as/), [Skatteetaten: shareholder register statement](https://www.skatteetaten.no/bedrift-og-organisasjon/rapportering-og-bransjer/aksjonarregisteroppgaven/)) |
| Run an operational agent on Talli's own code, infrastructure, sales administration or support triage | Work on Talli's own business is not accounting for another. The agent must not decide or approve customer accounting. |

These are legal-boundary conclusions from official sources, not proof that each
feature meets separate tax, filing, privacy, security or financial-services
rules.

### Altinn setup that matches the owner-run model

Altinn distinguishes a system user for the user's **own business** from a system
user for a **client system**. The first is for software reporting only for the
user company's own organization number. The second is for an accountant,
consultant or other service provider reporting for other companies, and uses
client relationships or delegated client authority. The customer must approve
the requested own-business authority in Altinn. Altinn also says that when
personal responsibility is required, the person must use normal Altinn login.
([Altinn: system-user guidance](https://docs.altinn.studio/nb/authorization/guides/system-vendor/system-user/),
[Altinn: about system access](https://info.altinn.no/hjelp/systemtilgang/om-systemtilgang/))

Talli's target design should therefore use a separate customer-approved
own-business system user for each customer AS, restricted to that AS. Talli
should not use the client-system route, a registered-accountant relationship or
a Talli-wide client credential for owner-managed filing. This technical setup
supports the facts that the customer uses software for its own reporting and
controls the authority. It is not, by itself, a legal exemption: the actual
service and human conduct still decide whether Talli performs accounting for the
customer.

## Conditional: keep strict guardrails

| Activity | Allowed only when | Stop condition |
| --- | --- | --- |
| Email support explains a readiness error using a customer's screen or records | Support describes what the app detected, points to official/general guidance and asks the customer to choose or supply facts. | Support tells the customer which account, tax treatment, amount or filing answer is correct for that real case. |
| Read-only support access to customer records | Access is necessary to diagnose a technical fault, customer-authorized, time-limited and logged; the operator does not assess the accounting result. | The operator reviews documents or entries for correctness, reconciles balances, chooses treatment or clears an accounting warning. |
| Correct non-accounting technical data after a support request | The change is limited to integration state, duplicated transport data or other technical metadata and leaves an audit trail. The customer makes every correction to booked information or report fields. | Talli staff enter or change an actual ledger entry, opening balance, accounting document or mandatory-report value, even if the customer asked for the change. |
| Explain a programmed classification | Support explains the rule and alternatives and the customer makes the final factual/accounting choice. | Support applies professional judgment to the customer's document and directs the outcome. |
| Automated filing transport | The customer sees the exact report, authenticates, confirms/signs where required and commands the transmission using company authority; Talli does not change it after approval. | Talli human staff prepare, alter, approve or submit the report on the customer's behalf, or accept responsibility for its correctness. |
| Altinn system access | Each customer AS approves and controls an own-business system user limited to its organization; personal signing remains with its authorized person where required. | Talli uses a client-system setup to act across customer organizations, asks for accountant/service-provider authority, or lets its personnel file as the customer's representative. |
| Automated exception handling | Code applies pre-approved deterministic rules, or the case is blocked for the customer/accountant. | A Talli operator resolves an exception by deciding the customer's accounting treatment. |
| Customer-specific onboarding | Support teaches the customer to use Talli or configures future programmed rules without processing real transactions. | Support enters, classifies or approves the customer's opening balances, source documents or real transactions. |
| Pre-launch parallel-run validation with real customer records | Talli tests software outputs for product-development purposes, keeps the customer's existing filed/accountant result as the reference, gives no accounting assurance, and does not alter or submit customer records. | Talli tells the customer that its review establishes the correct books/report, corrects the customer's records, or lets the customer rely on Talli's human comparison for filing. This grey area still needs Finanstilsynet confirmation. |
| Operational agent sees a support case | It only classifies/routes the ticket, retrieves technical telemetry or applies a deterministic product fix under the same access controls. | It chooses a customer-specific accounting treatment, clears a substantive validation issue, edits the ledger/report or communicates accountant-like approval. |
| Product promises and refunds | Talli warrants that its software operates as described and refunds for software/integration failure, while the customer remains responsible for facts, review and filing decisions. | Marketing, terms or support promise that Talli takes care of the customer's statutory duties, guarantees the accounting result or provides accountant approval. |

Where the stop condition occurs, a “the customer clicked approve” checkbox or a
terms disclaimer is not a reliable cure. The official test looks at who actually
makes the decision and who accepts responsibility for the result.
([NOU 2018: 9, chapter 3.1.2](https://www.regjeringen.no/no/dokumenter/nou-2018-9/id2602796/?ch=4))

## Outside Talli's unlicensed self-service boundary

Treat the following as regulated external accounting and do not offer it unless
Talli changes to an approved accounting-enterprise model or uses a properly
approved separate provider:

- receiving a customer's real transaction or document and having a Talli person
  decide its account, timing, tax treatment or other bookkeeping treatment;
- entering or correcting real ledger entries or opening balances for the
  customer rather than requiring the customer to make the entry through the
  software;
- reconciling or quality-checking a customer's ledger and representing that it
  is correct or legally compliant;
- resolving customer-specific accounting exceptions or clearing substantive
  readiness warnings after examining the records;
- preparing, completing or approving the customer's annual accounts, company tax
  return or other mandatory accounting report through human work;
- taking over the customer's duty to maintain books, keep them current, prepare
  specifications or produce mandatory reports;
- acting under filing authority as the customer's accountant, or having staff
  change/approve/submit the customer's report rather than supplying automated
  transport controlled by the customer;
- selling “human review,” “accountant approval,” “we make sure your accounts are
  correct,” “we do your year-end” or a similar result commitment; and
- letting an operational agent or contractor do any of the same work on Talli's
  behalf. Outsourcing the action does not change what Talli has undertaken to
  deliver.

The covered duties include booking transactions, preparing supporting and
balance documentation, producing specifications, annual accounts and mandatory
accounting reporting. These examples are listed in the official discussion of
the statutory scope.
([NOU 2018: 9, chapter 3.1.2](https://www.regjeringen.no/no/dokumenter/nou-2018-9/id2602796/?ch=4))

## What changes if Talli crosses the boundary

Talli could not lawfully continue that work as an ordinary unapproved SaaS
seller. At minimum:

- the work could only be performed by a `regnskapsforetak` approved by
  Finanstilsynet; a company applicant must have registered purpose to account for
  others, sufficient liquidity, and fit owners, board members and management;
- each engagement needs a written engagement agreement specifying its work and
  period, necessary authority, and a named state-authorized accountant who is
  responsible for the engagement;
- the enterprise needs suitable capacity and competence, documented quality
  management and controls, confidentiality, engagement documentation and
  compliant performance under good accounting practice;
- the anti-money-laundering framework applies, including a named AML officer,
  documented customer identification, ongoing monitoring, risk assessment,
  routines and staff training; and
- the activity becomes subject to Finanstilsynet supervision. Intentional or
  negligent breach of the authorization rule can be punished by a fine or up to
  one year in prison; approved enterprises and authorized accountants can also
  face withdrawal, suspension and administrative penalties for covered
  breaches.

Sources: [Regnskapsførerloven chapters 2, 4, 5 and 6](https://lovdata.no/dokument/NL/lov/2022-12-16-90),
[Finanstilsynet: approval as an accounting company](https://www.finanstilsynet.no/tillatelser/regnskapsselskap/godkjenning-som-regnskapsforerselskap/),
[Finanstilsynet: duties after approval](https://www.finanstilsynet.no/tillatelser/regnskapsselskap/hvilke-krav-gjelder-etter-at-regnskapsforetaket-har-fatt-godkjenning/),
and [Finanstilsynet: who needs personal authorization](https://www.finanstilsynet.no/tillatelser/regnskapsforer/hvem-ma-ha-godkjennelse-som-regnskapsforer/).

This is a major operating-model change, not a wording fix. The cheaper launch
path is to keep Talli and its support inside the software boundary and refer
customer-specific accounting judgment to an independent approved accountant.

## Clarification still needed

The official sources are clear enough to design the default self-service model
and support policy. A broad paid legal opinion is not needed to learn the basic
boundary. A narrow written determination from Finanstilsynet is still justified
because the Act gives Finanstilsynet the decision in doubtful cases and the
published material does not apply the rule to this exact end-to-end design.

The request should provide a diagram and a plain factual description, not a
marketing summary, and ask Finanstilsynet to determine these exact points:

> Does Talli's described paid, owner-operated service remain a system delivery
> outside `regnskapsføring for andre` when programmed rules process real data,
> post entries, prepare and transmit mandatory reports, no Talli person makes or
> approves a customer accounting decision, each customer controls an Altinn
> own-business system user, and the customer reviews, confirms/signs and retains
> responsibility for every result—and exactly which listed support or validation
> actions would change that answer?

1. Does a paid end-user system remain outside `regnskapsføring for andre` when
   deterministic rules automatically import actual bank transactions, generate
   ledger entries and prepare mandatory reports, while no supplier person takes
   a position on an individual transaction and the customer reviews and owns the
   result?
2. Does software-only API transmission remain a system delivery when the
   customer's authorized representative reviews the exact report, authenticates,
   confirms/signs and commands submission, but Talli's backend performs the
   machine-to-machine call through an Altinn own-business system user created and
   approved by the customer company?
3. At what exact point does customer-record support become regulated—for
   example, explaining a validation message, stating which user-selectable rule
   produced it, viewing the underlying document, recommending a specific account
   or tax treatment, entering a correction, or clearing the block?
4. May Talli staff compare automated output with an already prepared/filed
   reference during a free commercial pre-launch validation programme if the
   comparison is only product testing, no customer record is changed or filed,
   and the customer receives no assurance? Which result-sharing or reliance
   would turn that work into a regnskapsoppdrag?
5. Does the answer differ among the three supported reports—annual accounts,
   company tax return and shareholder register statement—especially where the
   last is third-party reporting under Skatteforvaltningsloven section 7-7?
6. Is it sufficient that Talli's terms, product controls, support scripts, access
   controls and marketing consistently leave factual choices, review and result
   responsibility with the customer, or does any part of the product promise
   imply that Talli accepts responsibility for legal correctness despite those
   controls?

The request should attach the proposed support decision tree and representative
screens for automatic posting, error handling, final review and filing. It
should ask for a written determination under the last paragraph of
[Regnskapsførerloven § 1-1](https://lovdata.no/dokument/NL/lov/2022-12-16-90),
not general informal product feedback. No customer data is needed; synthetic
examples are enough.

Until that answer exists, the safe launch rule is simple: automate; let the
customer decide and submit; explain the product; block unclear cases; never let
Talli staff or agents decide, correct or approve a customer's accounting.

## Official sources

- [Regnskapsførerloven (current consolidated Act)](https://lovdata.no/dokument/NL/lov/2022-12-16-90)
- [Prop. 130 L (2021–2022), chapter 3: scope of the Act](https://www.regjeringen.no/no/dokumenter/prop.-130-l-20212022/id2919163/?ch=3)
- [NOU 2018: 9, chapter 3: system delivery, automation and human responsibility](https://www.regjeringen.no/no/dokumenter/nou-2018-9/id2602796/?ch=4)
- [Finanstilsynet: accounting companies](https://www.finanstilsynet.no/tillatelser/regnskapsselskap/)
- [Finanstilsynet: who needs approval as an accounting enterprise](https://www.finanstilsynet.no/tillatelser/regnskapsselskap/hvem-ma-ha-godkjenning-som-regnskapsforetak/)
- [Finanstilsynet: approval as an accounting company](https://www.finanstilsynet.no/tillatelser/regnskapsselskap/godkjenning-som-regnskapsforerselskap/)
- [Finanstilsynet: duties after approval](https://www.finanstilsynet.no/tillatelser/regnskapsselskap/hvilke-krav-gjelder-etter-at-regnskapsforetaket-har-fatt-godkjenning/)
- [Finanstilsynet: who needs personal authorization](https://www.finanstilsynet.no/tillatelser/regnskapsforer/hvem-ma-ha-godkjennelse-som-regnskapsforer/)
- [Skatteetaten: company tax return through an accounting/year-end system](https://www.skatteetaten.no/bedrift-og-organisasjon/utenlandsk/skattemelding-og-skatteoppgjor/skattemelding-as/)
- [Skatteetaten: shareholder register statement through an end-user system](https://www.skatteetaten.no/bedrift-og-organisasjon/rapportering-og-bransjer/aksjonarregisteroppgaven/)
- [Skatteetaten: Skatteforvaltningsloven section 7-7 and shareholder reporting](https://www.skatteetaten.no/rettskilder/type/handboker/skatteforvaltningshandboken/skatteforvaltningshandboken-2024/kapittel-7-opplysningsplikt-for-tredjeparter/ID-7-7.001/ID-7-7.003/)
- [Altinn: system user for own business versus client system](https://docs.altinn.studio/nb/authorization/guides/system-vendor/system-user/)
- [Altinn: about system access](https://info.altinn.no/hjelp/systemtilgang/om-systemtilgang/)
