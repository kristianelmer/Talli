# Talli's legal duties for an unrestricted paid launch

Status: research note for issue 169  
Researched: 2026-08-26  
Scope: Norwegian B2B launch to holding companies; official Norwegian and EEA
sources only

This note is planning research, not legal advice. It separates duties that follow
from current rules from safer choices Talli can make. The final answer depends on
the seller, bank and payment providers, hosting locations, cookies, marketing
channels, and the exact support Talli gives customers.

## Short answer

Talli can launch as a B2B software service without first becoming an AS or buying
a general professional-insurance policy. It cannot safely open paid self-service
sales until it has done all of the following:

1. confirm the legal seller and show the seller correctly across the website,
   order flow, agreement, invoices, privacy notice, and provider contracts;
2. keep Talli on the software side of the line, rather than accepting accounting
   engagements for customers;
3. use a licensed route for live bank data, unless Talli itself obtains the
   required account-information licence and insurance;
4. support the bookkeeping rules that apply to an electronic accounting system,
   including SAF-T export, auditability, backup, retention, readable export, and
   lawful storage location;
5. publish and capture valid B2B terms, an Article 28 data-processing agreement,
   a correct privacy notice, and clear yearly billing and cancellation terms;
6. map every production data flow and vendor, sign the required processor terms,
   assess international transfers, and operate privacy and security controls;
7. block non-essential cookies until valid consent, and keep electronic marketing
   within Norway's opt-in rules;
8. prove public claims, meet private-sector web-accessibility requirements, and
   have a working support and incident route; and
9. register for VAT when the threshold is crossed, issue valid sales documents,
   and be ready for the B2B e-invoice rule that starts in 2027.

The highest-value narrow legal check is not a broad review of every document. It
is a written answer on whether Talli's exact automated bookkeeping, filing, and
support model stays outside regulated `regnskapsføring for andre`, followed by a
check of the chosen bank-feed contract and retention model. Free written guidance
from Finanstilsynet and Skatteetaten should be tried before paying a lawyer.

## Mandatory launch duties

### 1. Legal seller, public identity, VAT, and invoices

**Mandatory**

- The seller must be a real registered undertaking. Talli's current draft seller,
  ELMER WELFIS (org. no. 930 835 978), is currently an active Norwegian sole
  proprietorship in the Enhetsregister, is not in the Foretaksregister, and is not
  VAT-registered. That is a permitted seller form; an AS is not a launch
  prerequisite. Recheck the live register immediately before launch because the
  seller may change. [Brønnøysund Register Centre live entity
  record](https://data.brreg.no/enhetsregisteret/api/enheter/930835978)
- The website must make the seller's registered name, address, email/direct
  contact details, organisation number, relevant register, VAT status, and any
  required authorisation easy to find. Website and business documents must show
  the registered name and organisation number. [E-commerce Act sections
  8–12](https://lovdata.no/NL/lov/2003-05-23-35), [Foretaksregister Act section
  7-2](https://lovdata.no/nav/lov/2025-06-20-106/kap7), [Altinn's current company
  information guidance](https://info.altinn.no/starte-og-drive/drive-bedrift/juridiske-og-regulatoriske-krav/krav-til-informasjon-om-foretaket-pa-nettsider-og-forretningsdokumenter)
- Norwegian taxable turnover above NOK 50,000 in a rolling 12-month period triggers
  VAT registration. Software is normally subject to the 25 percent standard rate.
  Talli must not add output VAT before registration, and must add `MVA` after the
  organisation number on sales documents after registration. [Altinn VAT
  guidance](https://info.altinn.no/starte-og-drive/skatt-og-avgift/avgift/merverdiavgift),
  [Skatteetaten rates](https://www.skatteetaten.no/satser/merverdiavgift/)
- Each yearly payment needs valid sales documentation with a machine-assigned
  number, seller and buyer identity, description, delivery date/period, price,
  VAT where applicable, total, and payment deadline. A payment-provider receipt
  is not enough unless it contains the legally required sales-document fields.
  [Altinn invoice requirements](https://info.altinn.no/starte-og-drive/regnskap-og-revisjon/regnskap/faktura-salgsdokumentasjon/)
- From 1 January 2027, the new B2B e-invoice rules start. The announced transition
  requires sellers to send structured e-invoices to bookkeeping customers that
  are registered to receive them; detailed format and exceptions must be checked
  again at launch. This is a duty of Talli's own billing operation, even though
  customer invoicing is outside the Talli product. [Finance Ministry commencement
  notice](https://www.regjeringen.no/no/aktuelt/nye-lovregler-om-e-fakturering-i-naringslivet-og-enkelte-andre-lovendringer-pa-finansmarkedsomradet-settes-i-kraft/id3166726/),
  [2026 amendment act](https://lovdata.no/dokument/NL/lov/2026-06-19-39/KAPITTEL_1)

**Depends on a decision**

- If a new Talli AS replaces ELMER WELFIS, the new company must become the seller,
  controller/processor, merchant of record, authority-contract party, and vendor
  customer. Terms, privacy notice, DPA, invoices, and acceptance records cannot
  silently keep naming the old seller.
- Decide whether the annual subscription renews automatically or requires a new
  purchase each year. The checkout and terms must state the renewal date, notice,
  cancellation deadline, price-change process, and what happens to filing access
  and data when the paid period ends.

### 2. Stay a software provider, not an unlicensed accounting firm

**Mandatory**

- A business that accepts assignments to keep accounts for others generally needs
  Finanstilsynet approval; an accounting company needs an authorised responsible
  accountant and the duties that follow from the Accounting Services Act.
  [Finanstilsynet: who needs approval](https://www.finanstilsynet.no/tillatelser/regnskapsforer/hvem-ma-ha-godkjennelse-som-regnskapsforer/),
  [approval for accounting companies](https://www.finanstilsynet.no/tillatelser/regnskapsselskap/godkjenning-som-regnskapsforerselskap/)
- Talli's owner-managed model should therefore remain a customer-operated software
  service: the customer supplies facts, reviews outputs, resolves warnings, and
  personally authorises/submits filings. Talli support may explain how the app
  works, but must not accept responsibility for keeping, correcting, approving, or
  filing a customer's accounts as an outsourced service.

**Unresolved boundary requiring a narrow answer**

Official sources state the rule for `regnskapsføring for andre`, but do not draw a
precise line for Talli's combination of deterministic automatic postings, annual
filing, and email support. Before unrestricted launch, obtain a written
classification from Finanstilsynet or a narrowly scoped Norwegian lawyer. Give
them the actual user journey and support scripts, not a generic description of
"accounting software." If the answer says Talli accepts accounting engagements,
launch requires approval and the related professional, quality, engagement,
recordkeeping, and anti-money-laundering duties; wording alone cannot avoid that.

### 3. Use licensed bank and payment routes

**Mandatory if the feature is used**

- Talli's required live read-only bank sync is potentially the regulated payment
  service `kontoinformasjonstjeneste`. A company providing that service needs
  authorisation as an `opplysningsfullmektig`; payment initiation and handling
  other people's funds are also regulated. [Finanstilsynet account-information
  licence guidance](https://www.finanstilsynet.no/tillatelser/opplysningsfullmektig/),
  [payment-services guidance](https://www.finanstilsynet.no/tillatelser/betalingsforetak/)
- The simplest route is normally to contract with a provider that already has the
  required EEA/Norwegian permission and to keep consent, account access, and token
  handling inside that provider's authorised model. Before committing, verify the
  provider in Finanstilsynet's register and get written confirmation whether Talli
  is merely a technical customer, an agent, or itself providing the regulated
  service. The provider must also pass the privacy, security, location, exit, and
  subprocessor checks below.
- If Talli itself provides account-information service, it needs authorisation and
  professional-liability insurance or an equivalent guarantee. Do not build on
  that route without a separate decision. [Financial Undertakings Act sections
  2-3 and 2-10a](https://lovdata.no/lov/2015-04-10-17/kap2)
- Taking payment for Talli's own subscription through a licensed payment provider
  does not by itself make Talli a payment institution. Talli must not hold customer
  funds, initiate payments from customer accounts, or store raw card credentials.

### 4. B2B contract and electronic checkout

**Mandatory**

- Make the customer a named company, not the owner as a consumer: resolve the
  organisation number, invoice the company, require an authenticated representative
  to state that they may bind it, and retain evidence of the accepted document
  versions. If Talli sells to a person outside their business, consumer withdrawal
  and digital-service protections apply. The Withdrawal Act itself is limited to
  consumer sales. [Withdrawal Act section 1](https://lovdata.no/nav/lov/2014-06-20-27/kap1)
- Before order, show the technical steps, supported language, whether the agreement
  is archived and accessible, and how the buyer can find and correct errors. Make
  the terms storable and reproducible, and send an electronic order confirmation
  without undue delay. Some of these rules can be varied in a B2B contract, but
  keeping them is the safer self-service design. [E-commerce Act sections
  11–12](https://lovdata.no/dokument/LTI/lov/2003-05-23-35)
- The terms must match the product actually sold: one annual company subscription,
  all three supported filings included, no filing-package fee, supported and
  unsupported cases, user review/authority duties, payment and renewal, cancellation,
  suspension, failure/refund handling, support limits, export/deletion, confidentiality,
  IP, liability, governing law, and dispute route.
- B2B customers do not have a general statutory 14-day withdrawal right. Refund,
  early cancellation, and renewal outcomes therefore need clear contract terms and
  ordinary breach remedies. A seriously unreasonable B2B term may still be changed
  or set aside under Contracts Act section 36. [Contracts Act section
  36](https://lovdata.no/nav/lov/1918-05-31-4/%C2%A736)

**Best practice**

- Use an unchecked explicit acceptance control, show links beside it, store the
  immutable terms/DPA version and digest, and email a durable copy. Re-acceptance is
  prudent for material adverse changes. A privacy notice is disclosed, not
  "accepted" as a contract.
- A fair remedy for Talli-caused inability to complete a supported filing should be
  explicit. The exact refund and liability cap are commercial choices; a short
  legal check is justified after those choices are made, not before.

### 5. Privacy roles, notices, DPAs, and vendors

**Mandatory**

- Roles follow facts, not labels. The customer is likely controller for shareholder,
  bank, transaction, accounting-document, and filing data used on its instructions;
  Talli is likely processor for that work. Talli is a separate controller for its
  own seller records such as account administration, security, billing, legal
  compliance, and direct marketing. Each purpose and data flow must be classified.
- A binding Article 28 DPA is required with every customer for processor work. It
  must describe subject, duration, nature, purpose, data, people, instructions,
  confidentiality, security, subprocessors, help with rights and breaches, return
  or deletion, and audits. Talli also needs processor terms with each production
  vendor that handles personal data. [Datatilsynet Article 28
  guidance](https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/hvordan-lage-en-databehandleravtale/hva-ma-en-databehandleravtale-inneholde/)
- If relying on general subprocessor authorisation, tell customers before additions
  or replacements and allow a real objection process. Maintain a current list with
  provider, purpose, role, location, and transfer route.
- Publish a plain privacy notice when data is collected. It must identify the
  controller and contact route; each purpose, data type, legal basis, recipient,
  transfer, retention rule, and right; complaint route; and any automated decision
  that legally affects an individual. [Datatilsynet information
  requirements](https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/informasjon-og-apenhet/hva-skal-virksomheten-gi-informasjon-om/)
- Map a legal basis per controller purpose before collection. The current privacy
  draft should not automatically use GDPR Article 6(1)(b) for user accounts: the
  company, not necessarily its employee/owner, is the contract party, while that
  basis requires a contract with the individual concerned. Legitimate interest may
  fit necessary B2B contact, account, security, and service-administration uses, but
  it needs a documented necessity and balancing test. Talli's own statutory invoice
  retention can use legal obligation. [Datatilsynet contract-basis
  guidance](https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/om-behandlingsgrunnlag/nodvendig-for-a-oppfylle-en-avtale/),
  [all legal bases](https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/om-behandlingsgrunnlag/)
- Keep controller and processor records of processing. The under-250-person exception
  is narrow and does not remove this practical duty for Talli's ongoing processing.
  [Datatilsynet Article 30 guidance](https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/protokoll-over-behandlingsaktiviteter/)
- For any access or transfer outside the EEA, document the country, transfer basis,
  transfer assessment, and necessary additional safeguards. A vendor's EU region
  does not prove that support, telemetry, or subprocessors stay in the EEA.
  [Datatilsynet transfer guidance](https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/overforing-av-personopplysninger-ut-av-eos/sarlig-om-standard-personvernbestemmelser-som-overforingsgrunnlag/)
- Create a rights process that authenticates the requester and normally answers
  within one month. GDPR portability covers an individual's qualifying personal
  data, not the company's complete ledger. The company archive is therefore a
  separate contractual/bookkeeping requirement. [Datatilsynet portability
  guidance](https://www.datatilsynet.no/rettigheter-og-plikter/den-registrertes-rettigheter/rett-til-dataportabilitet/)
- Document a DPIA screening before launch. A full DPIA is mandatory if the final
  scale and data flows are likely to create high risk. Given bank transactions,
  ownership data, filings, broad availability, and several integrations, completing
  a full DPIA is prudent even if the screening concludes it is not strictly required.
  [Datatilsynet DPIA threshold](https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/vurdering-av-personvernkonsekvenser/nar-ma-man-gjennomfore-en-vurdering-av-personvernkonsekvenser/)

**Not automatically required**

- Talli does not need a general GDPR registration or a data-protection officer merely
  because it launches. Reassess and document the DPO question if core activities
  become large-scale regular monitoring or large-scale special-category processing.
  [Datatilsynet DPO threshold](https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/personvernombud/hvem-ma-ha-personvernombud/)

### 6. Cookies and analytics

**Mandatory**

- Since 1 January 2025, storing or reading information on a user's device requires
  GDPR-quality consent unless it is strictly necessary to transmit communication
  or deliver the service the user explicitly requested. This covers cookies and
  similar storage/tracking technology, not just advertising cookies. [Electronic
  Communications Act section 3-15](https://lovdata.no/nav/lov/2024-12-13-76/kap3),
  [Nkom guidance](https://nkom.no/internett/informasjonskapsler-cookies)
- Audit the public site and logged-in app before launch. Block analytics, pixels,
  session replay, ad conversion tools, and non-essential third-party embeds until
  the user actively consents. Refusal must be as easy as acceptance, choices must
  be granular, and withdrawal must be easy. Keep only genuinely necessary auth,
  security, load-balancing, and user-requested preference storage without consent,
  and explain it.
- Server-side aggregate measurement that neither stores nor reads the user's device
  can avoid the cookie rule, but any personal data in logs or analytics still needs
  a GDPR purpose, legal basis, minimisation, security, retention period, and notice.

**Simplest launch choice**

Run with necessary storage and minimal first-party server metrics only. Add optional
analytics after a tested consent implementation. This is a product choice, not a
legal requirement to avoid analytics.

### 7. Bookkeeping, SAF-T, retention, storage, and export

**Mandatory because Talli replaces the customer's accounting system**

- The customer remains the `bokføringspliktig` party. Records 1–4 in Bookkeeping
  Act section 13, including annual reporting, ledger/specifications, source evidence,
  deleted-entry evidence, audit trail, and balance support, normally have a five-year
  retention period after year-end. They must remain ordered, protected from loss,
  destruction, and change, readable, printable, and available for public control.
  [Bookkeeping Act section 13](https://lovdata.no/nav/lov/2004-11-19-73/%C2%A713)
- Talli must preserve traceability and corrections rather than silently changing
  closed entries. Period closing must prevent deletion or alteration, and the system
  description and backups must meet Bookkeeping Regulation chapter 7. [Bookkeeping
  Act sections 6–10](https://lovdata.no/dokument/NL/lov/2004-11-19-73/%C2%A76),
  [Bookkeeping Regulation chapter 7](https://lovdata.no/nav/forskrift/2004-12-01-1558/KAPITTEL_7)
- **SAF-T cannot wait until after launch.** All bookkeeping entities using an
  electronic accounting system must be able to reproduce the electronic ledger in
  the standard format when the Tax Administration requests it. System suppliers
  must make that possible. Version 1.40 becomes the only valid schema from 1 January
  2027; earlier 2026 periods may still require version 1.30. [Skatteetaten SAF-T
  scope](https://www.skatteetaten.no/bedrift-og-organisasjon/starte-og-drive/rutiner-regnskap-og-kassasystem/saf-t-regnskap/sporsmal-og-svar---standardformat-regnskap/),
  [current schema schedule](https://www.skatteetaten.no/bedrift-og-organisasjon/starte-og-drive/rutiner-regnskap-og-kassasystem/saf-t-regnskap/dokumentasjon/),
  [Bookkeeping Regulation chapter 7, including section
  7-8](https://lovdata.no/nav/forskrift/2004-12-01-1558/KAPITTEL_7)
- Electronic accounting material may be stored in another EEA state, the UK, or
  Switzerland only under the current conditions: it must remain readable/printable
  from Norway, follow Norwegian retention time, and the bookkeeping customer must
  give the tax office written information about what is abroad, where, and how the
  authorities can access it. A Norway-hosted primary record avoids that customer
  notification burden. [Bookkeeping Regulation section
  7-5](https://lovdata.no/nav/forskrift/2004-12-01-1558/KAPITTEL_7)
- If the customer has entrusted bookkeeping and storage to Talli, Talli must assist
  control authorities with access to the system and records. [Skatteetaten on
  Bookkeeping Act section 14](https://www.skatteetaten.no/nn/rettskjelder/type/uttalelser/prinsipputtalelser/bistand-og-informasjon-til-kontrollmyndighet/)
- At contract end, the DPA requires return or deletion at the customer's choice
  unless law requires Talli itself to retain a copy. The customer's bookkeeping
  duty does not automatically give Talli a legal basis to keep the whole workspace
  against that instruction. The offboarding path must first provide a complete,
  verified company archive and SAF-T file, then apply the chosen return/deletion
  and documented backup-expiry path. Talli may separately retain its own invoices,
  acceptance evidence, disputes, and security records for their own justified
  periods.

**Important correction to current repo documents**

- `PLAN.md` and the launch PRD say SAF-T is not required at public launch. That
  conflicts with Bookkeeping Regulation section 7-8 and current Skatteetaten
  guidance for electronic accounting systems.
- The retention draft treats five-year retention of the customer's whole workspace
  by Talli as the default. It must instead distinguish the customer's statutory
  retention duty, Talli's processor instructions, any direct assistance duty, and
  Talli's own controller records. Resolve this before final cancellation copy is
  approved.

### 8. Security and incident notification

**Mandatory outcomes**

- GDPR Articles 25 and 32 require privacy by design/default and technical and
  organisational security appropriate to risk. Talli needs a documented processing
  inventory, security risk assessment, owners, access rules, confidentiality,
  tenant isolation, private document storage, strong authentication for sensitive
  work, encryption in transit, secret management, patching, monitoring, tested
  backup/restore, deletion controls, and regular control testing. The exact measures
  are risk-based, but the obligation to assess, implement, and prove them is not
  optional. [Datatilsynet security and internal-control
  guidance](https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/informasjonssikkerhet-internkontroll/etablere-internkontroll/iverksette-styringssystem-for-informasjonssikkerhet/),
  [privacy by design](https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/innebygd-personvern-og-personvern-som-standard/)
- Every personal-data breach must be logged and assessed. For processing where
  Talli is controller, notify Datatilsynet without undue delay and where feasible
  within 72 hours unless the breach is unlikely to create risk; notify affected
  people without undue delay when high risk applies. For customer-controlled data,
  Talli as processor notifies the customer without undue delay and supports its
  decision. [GDPR Articles 33–34](https://eur-lex.europa.eu/legal-content/EN/TXT/?qid=1590424137028&uri=CELEX%3A32016R0679),
  [Datatilsynet breach guidance](https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/avvik/hvilke-brudd-skal-meldes-til-datatilsynet/)
- The support email must have a tested urgent security route; an ordinary inbox that
  may sit unread near a filing deadline is not an adequate incident process.

**Conditional classification**

The Digital Security Act applies to online marketplaces, search engines, and
services that provide a scalable, flexible pool of shared computing resources.
Talli appears to consume cloud services rather than sell general cloud resources,
so it is not obviously in that class. Record that screening and ask NSM for free
clarification if Talli's service model changes. If it is classed as a cloud service,
extra security-risk and significant-incident notification duties apply.
[Digital Security Act sections 9–11](https://lovdata.no/lov/2023-12-20-108/%C2%A79)

### 9. Electronic marketing and public claims

**Mandatory**

- Electronic marketing to a natural person requires prior consent, including a
  named person's business email or direct message. The existing-customer exception
  is narrow: Talli must have received the address during a sale, market only its own
  similar services, and offer a simple free opt-out both when collected and in each
  message. [Marketing Control Act section 15](https://lovdata.no/nav/lov/2009-01-09-2/%C2%A715)
- Marketing email must clearly identify Talli as the sender and as marketing.
  Discounts, free offers, and their conditions must be clear. [E-commerce Act
  section 9](https://lovdata.no/NL/lov/2003-05-23-35)
- Public B2B claims must not be false, misleading, or missing guidance needed for a
  fair choice, and advertising must be identifiable. [Marketing Control Act
  sections 25–28](https://lovdata.no/lov/2009-01-09-2/%C2%A729)
- Before publication, evidence must support claims such as 80 percent market
  coverage, replaces other accounting software, direct filing, live bank sync,
  security, supported joining date, included filings, and price. Never imply
  approval, affiliation, guaranteed authority acceptance, guaranteed correctness,
  or accountant/legal review unless it is true and current.

The separate research ticket on lawful recruitment channels should govern the
free pre-launch validation group. No agent should send outreach until that work
resolves the channel, recipient, consent, opt-out, and data-source rules.

### 10. Accessibility and support

**Mandatory**

- Norwegian public and private undertakings must make user-facing main ICT
  solutions universally designed unless doing so would be a disproportionate
  burden. The public site, self-service checkout/onboarding, and customer web app
  are main solutions. [Equality and Anti-Discrimination Act section
  18](https://lovdata.no/nav/lov/2017-06-16-51/kap3)
- Private-sector web solutions currently have 35 WCAG success criteria in the
  Norwegian rules. Talli needs a documented manual and automated accessibility
  check of the complete sales, onboarding, accounting, and filing paths before
  launch. A formal accessibility statement is a public-sector requirement, but a
  short contact route and known-issues statement are sensible for Talli.
  [Uu-tilsynet requirements](https://www.uutilsynet.no/wcag-standarden/wcag-standarden/86)
- The website must provide an email and other information that permits direct and
  effective contact. The planned Norwegian help pages and contact email can satisfy
  the ordinary support model, provided ownership, response handling, security
  escalation, complaints, billing errors, filing uncertainty, and data-rights
  requests are defined. [E-commerce Act section
  8](https://lovdata.no/nav/lov/2003-05-23-35/%C2%A78)

**Best practice**

- Publish realistic response targets rather than an SLA Talli cannot meet. Keep
  support away from bespoke accounting, tax, legal, or investment advice. Record
  any operator access to a customer's data, keep it least-privileged and time-bound,
  and do not send personal or accounting data through ordinary email when a secure
  route is needed.

## Registration and insurance summary

| Item | Launch answer |
| --- | --- |
| Norwegian seller registration | Mandatory. ELMER WELFIS is currently registered in Enhetsregisteret; recheck and update if seller changes. |
| Foretaksregister | Not generally required merely to sell ordinary SaaS through the current sole proprietorship; required if the entity form or regulated activity says so. |
| VAT register | Mandatory after taxable turnover exceeds NOK 50,000 in 12 months; pre-registration may be possible where official conditions are met. |
| Finanstilsynet accounting approval | Mandatory only if Talli accepts `regnskapsføring for andre`; exact boundary needs a written answer before launch. |
| Bank account-information permission | Mandatory if Talli itself provides the service; use and verify a licensed provider if Talli will not be licensed. |
| Payment-institution permission | Not required merely to receive Talli's own price through a licensed processor; triggered if Talli provides regulated payment services. |
| Datatilsynet registration/DPO | No general launch registration. DPO only if Article 37 thresholds are met; document the assessment. |
| General professional or cyber insurance | No general mandatory policy identified for ordinary B2B SaaS. Both are prudent commercial risk choices. |
| Account-information liability insurance | Mandatory if Talli itself is licensed as an account-information provider. |
| Employee injury insurance | Mandatory if the seller has employees, not merely because the product launches. [Altinn guidance](https://info.altinn.no/starte-og-drive/arbeidsforhold/ansettelse/obligatoriske-og-frivillige-forsikringer) |

## What official-source research can settle

The following can be completed without paid counsel:

- seller/VAT/invoice fields and live register evidence;
- checkout disclosures, order confirmation, versioned acceptance evidence;
- data inventory, controller/processor record, purposes and draft legal bases;
- DPA completeness checklist and production subprocessor/transfer register;
- cookie scan and consent implementation;
- privacy rights, breach, retention, deletion, and export runbooks;
- bookkeeping integrity, storage-location, SAF-T, backup, and authority-access tests;
- public-claim evidence and accessibility testing; and
- support ownership and incident rehearsal.

## Where narrow paid review may be justified

Use official agencies first. If they will not give a usable answer, seek a fixed,
narrow quote and obtain Kristian's explicit cost approval before commissioning it.
The useful questions are:

1. Does the exact owner-operated workflow plus support boundary constitute
   `regnskapsføring for andre`?
2. Does the chosen bank provider's contract and technical flow keep Talli outside
   the licensed account-information service, and who is controller/processor?
3. Does the final cancellation model correctly reconcile Article 28 return/deletion,
   the customer's Bookkeeping Act duties, Talli's control-authority assistance, and
   the selected storage countries?
4. Are the chosen B2B annual renewal, refund, warranty, liability cap, and dispute
   terms enforceable for this product?

A broad open-ended review is not required to start. Review the finished documents
and concrete flows, not placeholders.

## Required changes to the existing draft pack

Before publication, the current files in `docs/legal/` need at least these updates:

- replace monthly/filing-package billing and refund language with one annual
  subscription including the annual holding compliance loop;
- make legal review optional and evidence-driven rather than an unconditional
  blanket gate, while preserving narrow escalation for unresolved regulated lines;
- correct the account-user legal-basis assumption for a B2B company contract;
- verify the final seller, merchant, bank provider, payment provider, email service,
  host, database/storage, analytics, countries, and transfer mechanisms;
- replace blanket five-year retention of the whole customer workspace with a
  role/data-class matrix and customer return/delete choice;
- add SAF-T 1.40 launch capability, with a 2026 compatibility decision if needed;
- add the 2027 seller e-invoice requirement; and
- make mass-market claims conditional on live filing, bank, security, accessibility,
  and market-coverage evidence.

## Launch evidence checklist

The legal launch gate is complete when the repository can point to:

- current seller and VAT registry evidence;
- rendered seller information, price/VAT, terms, DPA, privacy and cookie notices;
- a complete test acceptance and annual billing/cancellation record;
- written accounting-service and bank-licensing boundary decisions;
- vendor/DPA/subprocessor/transfer register matching production configuration;
- records of processing, legal-basis matrix, DPIA screening, and rights runbook;
- cookie/storage scan showing optional tools blocked before consent;
- SAF-T golden export validated against the current Skatteetaten schema, complete
  company archive, retention/deletion test, backup/restore evidence, and storage
  country evidence;
- security risk assessment and incident/breach rehearsal;
- documented evidence for every public launch claim;
- full private-sector WCAG check of the public and signed-in paths; and
- working Norwegian help pages, support inbox ownership, and urgent escalation.

## Regulatory watch items

- Recheck the detailed 2027 e-invoice regulation and exceptions at launch.
- Recheck whether Norway's Digital Services Act implementation has entered into
  force. As of the current official Nkom material, implementation was still in
  progress; Talli is not an online platform, and private accounting-document
  storage appears ancillary, but the final Norwegian law should be screened.
  [Nkom DSA status](https://nkom.no/internett/internettbaserte-plattformer/digital-services-act-dsa)
- Recheck Finanstilsynet, Skatteetaten, Datatilsynet, Nkom, and Uu-tilsynet guidance
  immediately before launch because the launch has no fixed public date.
