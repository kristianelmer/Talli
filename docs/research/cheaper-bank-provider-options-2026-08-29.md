# Cheaper Bank-Data Provider Options

Status: preliminary primary-source screen; three non-binding RFIs sent; no
provider is selected or authorized

Date: 2026-08-29

## Question and Constraints

Could a licensed provider supply Talli with consented, read-only Norwegian
business-account data more cheaply than Neonomics or Enable Banking?

The screen keeps the approved requirements: Talli must not become its own AISP;
payment initiation is out of scope; production must cover the main Norwegian
business banks and ordinary business payment accounts; and the offer must fit the
current commercial limits. In particular, NOK 10,000 setup is rejected and the
viable amount must be materially lower.

Public material cannot prove the final price or a bank/account combination. A
candidate remains an RFI lead until it supplies a written quote, legal-role model,
dated business-bank matrix, contract/privacy/security pack and representative
production evidence.

## Outcome

Three additional candidates deserve a price request:

1. **GoCardless Bank Account Data** has the strongest chance of being the cheapest.
   Its January 2026 product description includes Bank Account Data in all three
  ordinary pricing plans and its public UK standard payments plan has no setup or
  monthly fee. However, GoCardless does not publish a Norwegian AIS-only commercial
  schedule, access is eligibility-controlled, and paid verification may be needed
   to remove an end-user warning. The current official API schema still defines a
   “Free usage limit exceeded” response, but does not state that limit. Treat
   “possibly free or very cheap” as a lead, not a quoted fact.
2. **Open Payments** is the strongest verified corporate/accounting fit. It
   documents the target Norwegian bank families, supplies its regulated licence
   route without a separate charge, and says developers can start free with no
   startup fee or lock-in. Its current production pricing is nevertheless tailored
   and unpublished, so those statements are negotiating evidence, not a quote.
3. **Aritma** is the strongest Norwegian technical fit. It is aimed at ERP and
   accounting products, claims all major Norwegian business banks and a full year
   of transaction history, and offers a sandbox. Pricing is tailored and
   unpublished, and the public material does not prove that Aritma would be the
   customer-facing AISP for Talli's exact flow.

Finshark is a worthwhile fourth quote if the first three fail. Salt Edge does not
presently show enough Norwegian connections to displace the shortlist.

## Candidate Screen

| Candidate | Primary-source evidence | Price signal | Talli decision |
| --- | --- | --- | --- |
| GoCardless Bank Account Data | [Current documentation](https://docs.gocardless.com/docs/bank-account-data) says GoCardless acts as authorized AISP across the EEA and supplies accounts, balances and transactions. Its linked [live coverage sheet](https://gocardless.com/bank-account-data/coverage/) marks business-account support for DNB, Nordea Business, Handelsbanken, Danske Bank Business and most named SpareBank 1 regional banks; Nordea Business is not marked for corporate accounts, and SpareBank 1 Sørøst-Norge has no current account-type marks. [January 2026 service terms](https://assets.ctfassets.net/40w0m41bmydz/3NuGGxoeVyKUEHQOZECAMf/4cb997a8f07eb5f8a063095f3a505fe7/Bank_Account_Data_Service_Terms_-_January_2026_.pdf) say GoCardless SAS supplies AIS to EEA end users, access must be requested and approved, background access is normally limited to four times per day, and EEA users reauthenticate at 180 days. | The [January 2026 product description](https://assets.ctfassets.net/40w0m41bmydz/3PX4jCSLLCArsATSolhcQm/20da06a11eb07061ea16dd857f88f46a/GoCardless_Product_Description_Document_-_January_2026.docx.pdf) lists Bank Account Data in Standard, Advanced and Pro for EEA customers. The [public pricing page](https://gocardless.com/pricing) says ordinary plans are pay-as-you-go with no setup cost or monthly fee, but it prices payments rather than a Norwegian AIS-only deployment. The current [official API schema](https://bankaccountdata.gocardless.com/api/swagger.json) defines a free-usage-limit response without publishing the allowance, and documentation says account verification is available only to paying customers. | **First additional RFI.** Ask for an AIS-only quote with zero payments, the current free allowance, whether a data-only customer can pay zero fixed/setup cost, the paid-verification price, and written confirmation of the remaining corporate/SpareBank gaps and former-Danske successor path. |
| Open Payments | [Current documentation](https://docs.openpayments.io/docs/introduction) covers corporate AIS. Its official material documents [Nordea Norway](https://www.openpayments.io/integrera/nordea-no) and current Norwegian DNB, Danske, SEB and Handelsbanken functionality; the main bank list also names the SpareBank 1 family. The provider says it is licensed by the Swedish FSA, and its [FAQ](https://www.openpayments.io/international-payments) says customers can use that licence without a separate charge. | [Current pricing](https://www.openpayments.io/pricing) is tailored and unpublished. The FAQ says no startup fee, hidden cost or lock-in for developers and that they can start free, but it does not prove the production AIS price. | **Second additional RFI.** Best verified corporate/accounting fit. Demand the current AIS-only production price and confirm each regional bank, ordinary account type and the former-Danske successor path. |
| Aritma | The [current Banking API](https://developer.aritma.com/apis/banking) covers accounts, balances, transactions and consent, claims all major Norwegian business banks and a full year of transactions. The [API platform](https://www.aritma.com/no/produkter/api-platform) is white-label, built for ERP/fintech products and claims full Nordic bank coverage. Its current consent flow uses a provider-hosted redirect, but the reviewed public material does not establish which party is the regulated AISP for Talli's customer flow. | The [pricing page](https://www.aritma.com/no/pricing) is quote-only, says price depends on bank connections and transaction volume, and offers a sandbox before commitment. Current consent documentation refers to a possible pay-per-consent model without publishing its rate. | **Third additional RFI, conditional on role.** First require written confirmation that Aritma—not Talli—is the customer-facing AISP and that no bilateral bank agreements are needed. If yes, request the same AIS-only quote. |
| Finshark | [Official product material](https://finshark.io/) says Finshark is a Swedish-licensed Payment Institution passported across the EEA with 99% Scandinavian account coverage. [Current documentation](https://docs.finshark.io/faqs) explicitly supports authorization for business accounts and account/balance/transaction retrieval. | No public production price; production access requires provider approval. | **Fourth-price-check candidate.** Require the exact Norwegian corporate matrix and confirm its data product supports recurring accounting sync, not only one-time KYC insights. |
| Salt Edge | The [Partner Program](https://www.saltedge.com/products/account_information) allows an unlicensed company to use Salt Edge's regulated route and supports personal and business accounts. Its current public coverage reports only 16 Norwegian connections. | No public production price. | **Low priority.** The narrow public Norway count makes required coverage doubtful. |
| Mastercard Open Banking / Aiia | Mastercard documents a [Norwegian accounting use case](https://www.mastercard.com/news/europe/no/redaksjon/pressemeldinger/no-no/2024/duett-tar-i-bruk-open-banking-fra-mastercard-for-a-forenkle-og-automatisere-regnskap-for-virksomheter-i-norge/) with bank-data reconciliation and says its APIs reach all Norwegian banks. Its [Nordea help material](https://www.mastercard.com/mt/en/business/open-finance/help-articles/nordics-dk-se-no-fi-nordea.html) documents Business and Corporate flows. | No public price; positioning and customers are enterprise-scale. | **Technically strong, unlikely cheapest.** Keep as a benchmark only unless Mastercard offers a startup-sized quote. |

## Options That Do Not Solve the Requirement

- **finAPI** publishes attractive B2X pricing, but its [current country coverage](https://www.finapi.io/en/products/country-coverage/) lists 13 markets and excludes Norway.
- **Direct bank PSD2 APIs** may have no per-call aggregator fee, but production
  access requires Talli to be a licensed AISP with qualified certificates. DNB's
  [production guide](https://developer.dnb.no/documentation/psd2-accounts/prod/1.19.0/guide)
  states those requirements explicitly. That route violates the approved
  licensed-provider architecture and is not a cheap shortcut.

## Recommended Next Move

Send the existing non-binding RFI to GoCardless, Open Payments and Aritma, adding
two pointed questions:

1. Can Talli use account-information-only production service with no payment
   processing, zero setup fee and no fixed monthly minimum?
2. If not, what is the lowest complete price at 1, 25 and 100 connected Norwegian
   companies, including paid verification, support and every bank/onboarding fee?

Do not change the implementation choice until the two original replies and these
additional quotes can be compared on the same evidence checklist.

## Enquiry Status

The recommended RFIs were sent from `post@talli.no` on 2026-08-29 to GoCardless,
Open Payments and Aritma. GoCardless acknowledged receipt as ticket `4436853`.
Open Payments and Aritma are evidenced in the Mail Sent folder. See
`docs/research/bank-provider-rfi-2026-08-29.md` for the exact dispatch record and
limits. No reply or sent-message record is treated as a selection or pass.
