# Live read-only bank connections for Norwegian holding companies

Status: official-source research complete; no provider selected or activated

Research date: 2026-08-26

Scope: automatic read-only transaction capture for Norwegian business payment
accounts used by a simple holding AS

## Decision summary

Talli should launch through a **licensed account-information provider using the
provider's AISP permission**, not apply to become an account-information service
provider itself and not integrate separately with every bank.

The first commercial check should compare:

1. **Neonomics** as the primary candidate. It is supervised in Norway, is
   explicitly licensed for account-information services, documents a separate
   business/corporate-account scope, and focuses on Nordic coverage.
2. **Enable Banking** as the strongest challenger. It explicitly documents
   Norwegian business-bank flows, including the different Nordea Business and
   Nordea Corporate systems, and supports production use under its own AISP
   authorisation.

**Mastercard Open Banking (Aiia)** and **Tink Business Transactions** are credible
fallback bidders, but their public material does not prove the exact current
Norwegian business-account coverage Talli needs. Tink also places Business
Transactions in its enterprise-only, custom-priced tier. They should stay on the
shortlist only if they provide a current bank-by-bank capability export and a
competitive quote.

This research does **not** authorise a purchase or signup. Every production route
requires commercial terms, and no candidate publishes enough information to
calculate Talli's total cost. Before any activation, Kristian must approve the
provider, exact price, recurrence or usage basis, and the cheaper fallback.

The implementation should keep Talli's provider-neutral port, poll conservatively,
store canonical transaction data with source provenance, and retain bank-file
import as a required recovery and historical-backfill path. A bank connection is
not proof of a complete accounting year.

## What “live” can honestly mean

PSD2 account information is an automatic bank feed, not a guaranteed event stream.
An AISP may fetch when the user actively asks and, when the user is absent, normally
no more than four times in 24 hours unless the bank and AISP agree a higher rate
with the user's consent. Initial access requires strong customer authentication;
the current exemption requires it again after 180 days for balance and recent
transaction access. Sources: [EU regulatory technical standards, Article
36(5)](https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=CELEX%3A32018R0389)
and [the 180-day amendment, Article
10a](https://eur-lex.europa.eu/eli/reg_del/2022/2360/oj/eng).

For Talli's low-volume holding-company use case, one scheduled refresh each night,
an owner-triggered “sync now,” and an extra refresh during annual close should be
enough. This is an implementation recommendation, not a provider guarantee.
Marketing should call the feature **automatic bank sync** or **connected bank
feed**, not “real-time,” unless the eventual contract and production evidence
support that stronger claim.

## Regulatory routes

### Recommended: operate through a licensed provider

Norwegian law treats obtaining payment-account information on an account holder's
behalf as a regulated account-information service. Finanstilsynet says a business
offering only that service needs permission as an *opplysningsfullmektig*, while an
authorised EEA provider may operate cross-border after the home regulator has
notified Norway. Sources: [Finanstilsynet on payment-service
permissions](https://www.finanstilsynet.no/tillatelser/betalingsforetak/),
[Finanstilsynet on an
opplysningsfullmektig](https://www.finanstilsynet.no/tillatelser/opplysningsfullmektig/),
and [Finanstilsynet on EEA cross-border payment
services](https://www.finanstilsynet.no/forbrukerinformasjon/betalingstjenester-og-betalingssystemer/).

The shortlisted providers offer a model in which their regulated entity is the
AISP and Talli is the integrating application. Tink says its ready-made
authentication flows require no PSD2 licence; Enable Banking says its default
production infrastructure relies on Enable Banking's authorisation; Mastercard
describes a licence-free Open Banking product distinct from its own-licence
Enterprise product; and Neonomics describes its Account Data API as a licensed
AISP service. Sources: [Tink platform
overview](https://www.tink.com/), [Enable Banking application
registration](https://enablebanking.com/docs/api/control-panel/), [Mastercard on
Aiia licensing](https://www.mastercard.com/de/de/business/open-finance/help-articles/do-i-need-a-license-to-use-aiia-enterprise.html),
and [Neonomics Account Data
API](https://www.neonomics.io/enterprise/account-data-api).

This reduces Talli's regulatory and bank-integration burden, but does not remove
Talli's own duties. Talli still needs an accurate service description, customer
terms and privacy notice, access control, data minimisation and retention rules,
incident handling, vendor governance, and a checked controller/processor split in
the DPA.

### Rejected for launch: Talli becomes regulated directly

Applying directly is possible but disproportionate for launch. Finanstilsynet
requires a Norwegian application including governance and suitability material, a
three-year organisation and operations plan, internal controls, security and
incident arrangements, and liability insurance or an equivalent guarantee. Its
published normal processing time is three months **after** a complete application
and fee, not three months from starting the work. The current application fee is
NOK 30,000; supervision and insurance create additional recurring costs.
Licensed account-information providers must also file half-year reports, complaint
reports, risk/vulnerability reporting, and outsourcing or ICT-service notices.
Sources: [Finanstilsynet application
requirements](https://www.finanstilsynet.no/tillatelser/opplysningsfullmektig/),
[current application
fee](https://prod.finanstilsynet.no/tillatelser/fellessider/gebyr-ved-soknad-om-konsesjon-for-betalingsforetak-og-e-pengeforetak/),
[insurance requirements in the financial-institutions
regulations](https://lovdata.no/dokument/SF/forskrift/2016-12-09-1502/delIV),
and [Finanstilsynet reporting
requirements](https://www.finanstilsynet.no/rapportering/opplysningsfullmektig/).

Direct licensing would then leave Talli to obtain PSD2 certificates, onboard and
maintain each bank interface, normalize different APIs, monitor changes, and run a
regulated operational programme. DNB and SpareBank 1 both make the boundary
concrete: production is for a registered AISP with an eIDAS/QWAC certificate,
while their sandboxes use synthetic data. Sources: [DNB Account Information
Service](https://developer.dnb.no/documentation/psd2-accounts/%40default/2.95.0)
and [SpareBank 1 PSD2 documentation](https://psd2.soa.sparebank1.no/developer/docs/documentation/).

This route should be reconsidered only after Talli has enough customers and
provider spend that the recurring savings can fund dedicated regulatory,
security, certificate, bank-connectivity, and incident work.

### Rejected for mass-market launch: one bank at a time

Direct bank APIs prove that corporate account data exists, but one-bank
integration does not meet the mass-market goal. DNB exposes Norwegian retail and
corporate accounts, balances and transactions; Nordea maintains separate APIs for
SME-oriented Nordea Business and larger-company Corporate Netbank; and SpareBank 1
has a distinct corporate-context flow. Sources: [DNB Account Information
Service](https://developer.dnb.no/documentation/psd2-accounts/%40default/2.95.0),
[Nordea business account information](https://developer.nordeaopenbanking.com/products/business-accounts-information),
and [SpareBank 1 corporate
context](https://psd2.soa.sparebank1.no/developer/docs/documentation/).

A premium bilateral bank API could later improve one high-volume bank, but it
cannot replace an aggregator at launch without leaving customers from other banks
unsupported.

## Provider comparison

| Route | Evidence for Norway and business accounts | Test and production path | Public cost evidence | Main risk | Research verdict |
| --- | --- | --- | --- | --- | --- |
| **Neonomics Account Data API** | Finanstilsynet's register shows Neonomics AS as a Norwegian payment institution licensed for account-information services. Its API has a `business-accounts` scope, and its public product material claims close to 100% Nordic retail-bank coverage while warning that functionality varies by bank and account type. | Public sandbox documentation exists; production keys follow due diligence and a commercial agreement. | Priced on successful calls with no charge for inactive users; no rate is published. | Coverage percentages are marketing-level and do not prove each corporate account type, history window, or SLA. | **Primary candidate.** Best regulatory/local-market fit; verify with a bank-by-bank matrix and real holding-company tests. |
| **Enable Banking API** | Its Norway guide covers DNB, SpareBank 1, Nordea, Handelsbanken and Danske Bank, and explicitly separates Nordea Business, Nordea Corporate and regional SpareBank 1 flows. API metadata distinguishes `business` from `personal` users. | Mock and selected bank sandboxes are documented. Public use needs contract and KYB; restricted production before contract is only for one's own linked accounts and cannot be used commercially. | Volume-based by accounts/payments with a monthly minimum; exact amount requires a quote. | Unknown minimum cost; exact default-service DPA, retention, SLA, and bank/account coverage need contract review. | **Strong challenger.** Especially useful as an independent check on Neonomics coverage and historical-data behavior. |
| **Mastercard Open Banking / Aiia** | Mastercard's licensed entity offers a licence-free route. Aiia's published Norway business-account list includes DNB, Danske Bank and many savings banks, but the public list does not establish current support for all of Nordea, SpareBank 1 and Handelsbanken business systems. | Sample/sandbox material exists; production onboarding and pricing are not publicly specified. | No usable public price. | Public coverage artifact is insufficient for Talli's required banks; likely enterprise contracting. | **Fallback bidder.** Continue only if Mastercard supplies current Norwegian business coverage and a competitive quote. |
| **Tink Business Transactions** | Tink is an active Swedish payment institution licensed for account-information services. Business Transactions supplies accounts, balances and transaction data, but Tink's public page does not expose a bank-by-bank Norwegian business matrix. | Simulated-data setup is public; production requires verification and a commercial relationship. | Business Transactions is enterprise-only with custom pricing; guaranteed response/resolution times are enterprise features. | Price and Norway business coverage are opaque; product may be too enterprise-shaped for Talli's launch economics. | **Fallback bidder.** Use only if it can prove coverage and beat the two leading candidates on total cost and SLA. |

Sources for the table:

- [Neonomics in Finanstilsynet's register](https://www.finanstilsynet.no/virksomhetsregisteret/detalj/?id=199328),
  [Neonomics business-account API](https://docs.neonomics.io/reference/getallaccounts),
  [Neonomics production and market FAQ](https://www.neonomics.io/customers-frequently-asked-questions),
  and [Neonomics pricing model](https://www.neonomics.io/enterprise/account-data-api).
- [Enable Banking Norway guide](https://enablebanking.com/docs/markets/no/),
  [API capability metadata](https://enablebanking.com/docs/tppapi/latest),
  [sandbox documentation](https://enablebanking.com/docs/api/sandbox/),
  [production restrictions](https://enablebanking.com/terms/), and [commercial
  pricing/onboarding FAQ](https://enablebanking.com/docs/faq/).
- [Mastercard licence model](https://www.mastercard.com/de/de/business/open-finance/help-articles/do-i-need-a-license-to-use-aiia-enterprise.html),
  [Aiia Norway business-bank list](https://cdn.nordicapigateway.com/public/List-of-supported-banks.pdf),
  and [Aiia consent terms](https://cdn.aiia.eu/public/aiia-terms-of-use.pdf).
- [Tink regulatory register](https://www.fi.se/sv/vara-register/foretagsregistret/details?id=145258),
  [Tink Business Transactions](https://tink.com/products/business-transactions/),
  and [Tink pricing](https://www.tink.com/pricing/).

## Coverage and data acceptance gates

A provider's bank count is not launch evidence. Talli needs a dated capability
matrix for the **business** user context and the actual payment-account types used
by holding companies. At minimum, the contract/bake-off must cover:

- DNB corporate, SpareBank 1 regional banks, Nordea Business, Handelsbanken and
  the current Norwegian successor/coverage situation for Danske Bank customers;
- ordinary NOK operating/current accounts, and any common placement/savings
  account from which external payments can be made;
- owner/representative authentication, delegated corporate access, account
  selection, balances, booked transactions and pending-transaction behavior;
- initial history available immediately after consent, ongoing history after the
  initial window, pagination, stable identifiers, corrections/reversals,
  transaction text/remittance fields, booking/value dates, and explicit gaps;
- consent expiry/revocation, reconnect behavior, bank/API incidents and provider
  incident notification.

DNB's own documentation shows why account type matters: it exposes corporate
operating, investment, currency and certain placement accounts, while some account
types are not available over PSD2. It also requires the corporate user's DNB
TX-ident. [DNB Account Information
Service](https://developer.dnb.no/documentation/psd2-accounts/%40default/2.95.0).

The provider must return all available historical transactions immediately after
consent. Enable Banking documents that many banks expose a year or more only for a
short period after authorisation, then limit later reads to roughly 90 days; actual
history varies by bank and account type. Therefore Talli must never defer the first
backfill job, and it must record the earliest successfully covered date and flag a
gap instead of pretending the year is complete. [Enable Banking historical-data
FAQ](https://enablebanking.com/docs/faq/).

## Consent, privacy and security boundary

PSD2 requires explicit user permission, access only to designated payment accounts
and related transactions, no request for sensitive payment data, and no use or
storage beyond the account-information service the user requested. [PSD2 Article
67](https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=CELEX%3A32015L2366).

The “explicit consent” wording in PSD2 is not automatically GDPR consent. The EDPB
says the normal GDPR basis for data needed to perform the requested payment service
is contractual necessity, and also addresses transaction data about “silent
parties” such as counterparties. Talli must document its own legal bases and
minimise both account-holder and counterparty data rather than copying a vendor's
consent text. [EDPB Guidelines 06/2020, final
version](https://www.edpb.europa.eu/sites/default/files/files/file1/edpb_guidelines_202006_psd2_afterpublicconsultation_en.pdf).

Required implementation controls:

- Use a bank/provider redirect; never collect or proxy BankID codes or online-bank
  credentials in Talli.
- Bind consent state, provider connection and selected account to one Talli
  company. Re-check company access at every sync and callback.
- Encrypt provider tokens and connection references; keep them backend-only;
  redact credentials and raw identifiers from logs.
- Request balances and booked transactions only. Do not request payment initiation
  or unrelated enrichment products.
- Treat provider and bank payloads as untrusted. Validate size, type, currency,
  dates and pagination; persist sync attempts and unknown outcomes idempotently.
- Show who connected the account, which account is covered, earliest covered date,
  last successful sync, next reauthentication date, and a revoke/disconnect action.
- Make revocation stop future collection promptly. Define deletion and legally
  required accounting-retention behavior separately; revoking a feed should not
  silently erase ledger evidence already used in bookkeeping.
- Complete a DPIA/legitimate data-protection assessment, DPA/subprocessor review,
  breach terms, deletion/return test, security review, and incident drill before
  production.

## Reliability and vendor exit

The provider should not be the source of accounting truth. Talli should own a
canonical bank-account and transaction model, including provider-independent
fields, the original source, import/sync time, booked status, and a stable dedupe
fingerprint. Provider references should be scoped to an adapter, never used as
Talli's business identity.

Changing providers will require every customer to grant a new consent; PSD2 does
not make the old provider's consent portable. The exit plan therefore must include:

1. export of Talli's canonical transactions and sync audit trail;
2. disconnect without losing ledger links or accounting documents;
3. overlap reconciliation between old provider, new provider and bank statement;
4. a customer reconnect campaign with an explicit deadline;
5. bank-file import throughout the transition; and
6. contract rights to data return/deletion, incident records and reasonable
   termination assistance.

Reliability must be measured during the pre-launch validation group, not inferred
from provider bank counts. For every target bank, capture consent completion,
initial backfill completeness, daily sync success, freshness, duplicate/correction
behavior, reconnect friction, mean recovery time, and provider support response.
Tink's own public pricing page is a useful warning: guaranteed response and
resolution times are only stated for Enterprise customers. [Tink
pricing](https://www.tink.com/pricing/).

## Required bank-file fallback

Automatic sync remains the normal path, but launch still needs a file path for:

- joining mid-year when the bank API cannot return January-to-date history;
- provider/bank outages and expired or revoked consent;
- an unsupported bank or account type discovered after purchase;
- provider migration; and
- independent year-end completeness checks.

The existing CSV path should be hardened into a provider-independent import:

- accept original bank CSV at minimum; add ISO 20022 CAMT.053 where validation
  users' banks provide it;
- preserve the original file as an accounting document and its SHA-256 hash;
- map columns explicitly and preview account, period, row count, opening/closing
  balance where available, currency, and ignored rows before acceptance;
- derive a stable fingerprint from account, booking/value date, amount, currency,
  text/reference and occurrence index; never rely only on a vendor transaction ID;
- merge safely with synced records, show duplicates and corrections, and never
  post ledger entries automatically;
- record provenance per row (`bank_sync`, `bank_csv`, or `camt053`) and the covered
  date interval;
- block annual filing readiness when January-to-year-end coverage has an unexplained
  gap or the closing bank balance is not reconciled.

PDF statements can support human reconciliation, but should not be the primary
machine import because they do not provide a stable structured transaction
contract.

## Implementation shape and effort

The repo already has the correct starting seam: a disabled provider-neutral port,
replay-safe webhook hashing, redacted diagnostics, CSV import, and idempotent bank
transactions. The backend rebuild should preserve the seam but move it behind the
canonical transaction-capture capability and durable external-I/O state machine,
consistent with ADR-0011 and ADR-0012.

Provider work is medium-sized even with an aggregator. It includes consent
start/callback/reconnect, encrypted connection storage, durable scheduled and
owner-triggered sync, pagination/cursors, correction and duplicate handling,
coverage gaps, connection status UX, deletion/revocation, telemetry, outage
recovery, file fallback, and a real-bank validation matrix. A provider SDK alone
does not complete these controls.

The adapter should expose capabilities rather than assuming webhooks or perfect
cursors:

```text
begin_consent(company, bank, return_url)
complete_consent(company, state, callback)
sync_accounts(connection, requested_interval)
sync_transactions(account, requested_interval, continuation)
disconnect(connection)
capabilities(bank, business_context)
```

Persist sync checkpoints only after the page/batch is durably accepted. A retry
must be harmless, and an unknown provider outcome must reconcile before another
request is treated as new.

## Commercial bake-off before selection

Without signing up or contacting vendors during this research, the public record
cannot answer the final price, contractual SLA, or exact live coverage. The next
decision should request the same written package from Neonomics and Enable Banking,
with Mastercard/Aiia and Tink added only if needed:

- exact NOK setup, minimum monthly/annual, per-connection, per-call, reconnect,
  sandbox, support and overage charges; currency, VAT and contract term;
- current Norwegian **business** bank/account capability export;
- whether Talli operates under the provider's AISP licence for this exact
  accounting use case;
- consent owner, customer-facing terms, 180-day reauthentication behavior and
  revocation flow;
- initial/ongoing history, background refresh, rate limits, corrections, pending
  items, identifiers and gap signaling;
- production onboarding/KYB time, sandbox realism and access to restricted real
  accounts for validation;
- uptime/support SLA, status feed, incident notice and service credits;
- DPA roles, subprocessors/regions, encryption, token custody, retention/deletion,
  audit evidence and breach notice;
- export/termination assistance and a no-penalty validation exit.

Then run the same scripted test with consenting validation companies at DNB,
SpareBank 1 and Nordea Business first, followed by other banks required to reach
the market-coverage target. No production purchase or charge is authorised until
Kristian approves the provider and full expected cost.

## Resolution

The way forward is clear enough to plan:

- **Route:** licensed-provider AISP service.
- **First comparison:** Neonomics versus Enable Banking.
- **Fallback bidders:** Mastercard/Aiia and Tink only if coverage or commercial
  terms require them.
- **Not for launch:** Talli's own AISP licence or separate integrations with every
  bank.
- **Required product behavior:** automatic read-only sync, visible consent and
  coverage state, immediate initial backfill, conservative scheduled refresh,
  provider-neutral storage, and a fully supported bank-file fallback.
- **Selection gate:** written cost/contract review plus representative real-company
  bank tests; provider marketing claims alone are insufficient.
