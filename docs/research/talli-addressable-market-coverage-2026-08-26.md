# Talli addressable market and 80% coverage gap

Date: 2026-08-26  
Question: [Measure Talli's addressable market and 80% coverage gap](https://github.com/kristianelmer/Talli/issues/166)  
Code baseline: [`f55e7f15`](https://github.com/kristianelmer/Talli/tree/f55e7f15a8e64a2aacee29419cb60c338e141c27)

## Answer

Do not claim that Talli covers 80% of its addressable market yet.

The best current registry estimate is a **broad candidate frame of 46,339 AS companies**, not a proven addressable-market count. It is the union of:

- 12,699 active, current-filing, non-VAT, no-employee AS companies under SN2025 code `64.323` (`Andre egeninvesteringsselskaper`); and
- 37,118 AS companies passing the same filters whose registered name contains `holding`;
- less the 3,478 companies in both groups.

The 12,699 code-based companies are the higher-signal core. The 46,339 union is a useful upper screening frame. Neither number proves that a company is privately owner-managed, has a self-service buyer, or fits Talli's accounting rules. A defensible final denominator therefore needs a company-level sample audit.

A deterministic sample of 300 companies from the 12,699-company core produced:

- **52.3%** passing a cautious public-data screen;
- **87.7%** passing a deliberately optimistic screen that ignores audit status and long-term debt; and
- several important Talli blockers that the public key-figures API cannot see.

These are screening results, not product-coverage estimates. The optimistic result has a two-sided 95% Wilson interval of 83.5%–90.9%, but it still ignores shareholder structure, share classes, investment type and tax treatment, owner dividends, loans, unpaid items, transaction volume, and whether the owner would buy self-service software. It cannot clear the 80% gate.

For planning, treat current end-to-end coverage as **unknown and below the launch gate until measured**. The largest measured gaps to investigate first are audit/filing shape, long-term debt or loans, and operating income. Likely large but currently unmeasured gaps are owner dividends, shareholder/intercompany loans, unsupported investments, and shareholder/share-class complexity.

## What the official registers show

Norway changed from SN2007 to SN2025 in September 2025. The official correspondence maps former code `64.308` (`Familieeide egeninvesteringsselskaper`) one-to-one to `64.323` (`Andre egeninvesteringsselskaper`). This makes `64.323` the best current industry-code starting point, but not a product-fit test. [SSB's SN2025 correspondence table](https://www.ssb.no/virksomheter-foretak-og-regnskap/metoder-og-dokumentasjon/ny-standard-for-naeringsgruppering-innfores-1.september-2025/_/attachment/inline/c8b94163-10db-40c9-b0b2-7f8915293df0%3A547e2dfa4544867e783574eaeb3ff8022062a3a0/Korrespondansetabell%20SN2025-SN2007_14.04.2026.pdf)

Registry counts were read from Brønnøysundregistrene's Enhetsregister API on 2026-08-26. The API documents filters for organisation form, industry code, bankruptcy/liquidation status, latest accounts, VAT registration, employee count, name, and sorting. [Enhetsregister API documentation](https://data.brreg.no/enhetsregisteret/api/dokumentasjon/no/index.html)

| Screen | Companies | What it means |
| --- | ---: | --- |
| AS with code `64.323` | 14,004 | Registered code only |
| Same, excluding bankruptcy/liquidation statuses | 13,917 | Registry-active proxy |
| Same, latest accounts are 2025 | 13,752 | Current annual-filing proxy |
| Same, not VAT-registered and no registered employees | **12,699** | Higher-signal core candidate frame |
| AS name contains `holding`, with the same activity/filing/VAT/employee filters | 37,118 | Broad name-based candidates |
| Overlap of the last two rows | 3,478 | Deduplicated when building the union |
| Broad union | **46,339** | Upper screening frame, not proven buyers |

The live count queries are:

- [All `64.323` AS companies](https://data.brreg.no/enhetsregisteret/api/enheter?organisasjonsform=AS&naeringskode=64.323&size=1)
- [Active `64.323` AS companies with 2025 accounts, no VAT registration, and zero registered employees](https://data.brreg.no/enhetsregisteret/api/enheter?organisasjonsform=AS&naeringskode=64.323&konkurs=false&underAvvikling=false&underTvangsavviklingEllerTvangsopplosning=false&sisteInnsendteAarsregnskap=2025&registrertIMvaregisteret=false&fraAntallAnsatte=0&tilAntallAnsatte=0&size=1)
- [Name contains `holding`, with the same filters](https://data.brreg.no/enhetsregisteret/api/enheter?organisasjonsform=AS&navn=holding&konkurs=false&underAvvikling=false&underTvangsavviklingEllerTvangsopplosning=false&sisteInnsendteAarsregnskap=2025&registrertIMvaregisteret=false&fraAntallAnsatte=0&tilAntallAnsatte=0&size=1)
- [`64.323` and name contains `holding`, with the same filters](https://data.brreg.no/enhetsregisteret/api/enheter?organisasjonsform=AS&naeringskode=64.323&navn=holding&konkurs=false&underAvvikling=false&underTvangsavviklingEllerTvangsopplosning=false&sisteInnsendteAarsregnskap=2025&registrertIMvaregisteret=false&fraAntallAnsatte=0&tilAntallAnsatte=0&size=1)

The union is intentionally broad:

- An industry code says how the entity is classified, not which transactions, owners, assets, or filing cases it has.
- A name containing `holding` is only a search hint. It includes some centrally managed subsidiaries and misses holdings with other names.
- No public registry field directly identifies a plausible self-service buyer.
- `erIKonsern` is not a safe exclusion: an owner-managed holding company may be a parent in a group precisely because it owns an operating company.
- `64.210` (`Holdingforetak i finanskonsern`), `64.220` (`Spesielle holdingselskaper`), and `64.322` (investment companies in financial groups/public administration) should not be added automatically. Their labels describe the regulated or special-purpose cases the destination excludes.

The broad union should therefore be used to draw and weight a validation sample, not as a public total-addressable-market claim.

## What Talli supports in the code baseline

The current onboarding gate only proves that an entity is an AS. It does not encode the full simple-holding boundary, so downstream rules define actual end-to-end fit. [Customer onboarding source](https://github.com/kristianelmer/Talli/blob/f55e7f15a8e64a2aacee29419cb60c338e141c27/apps/web/app/lib/customer-onboarding.ts), [AS identity assertion](https://github.com/kristianelmer/Talli/blob/f55e7f15a8e64a2aacee29419cb60c338e141c27/apps/web/app/lib/brreg.ts)

For the complete annual compliance loop, the current code supports a narrow shape:

- ordinary AS, one ordinary share class;
- small-enterprise annual accounts without a required audit or annual report;
- bank, Norwegian private-company share investments under clear `fritaksmetoden`, narrow administrative costs, interest, and tax settlement;
- no VAT, payroll, invoicing, customer/supplier ledger, property accounting, or broad operating activity;
- no unpaid items in the simple annual loop;
- no shareholder/intercompany loan case in the automatic company-tax-return path;
- no declared owner dividend in the automatic company-tax-return path, even though separate corporate-document and ledger work exists;
- no unclear/foreign/outside-`fritaksmetoden` investment in the automatic path; and
- no production claim merely because a standalone domain type exists: for example, the web purchase flow accepts only Norwegian private-company shares with `fritaksmetoden`.

Primary code evidence:

- [Annual-accounts blockers and narrow payload](https://github.com/kristianelmer/Talli/blob/f55e7f15a8e64a2aacee29419cb60c338e141c27/apps/web/app/lib/annual-accounts.ts)
- [Company-tax-return blockers](https://github.com/kristianelmer/Talli/blob/f55e7f15a8e64a2aacee29419cb60c338e141c27/apps/web/app/lib/company-tax-return.ts)
- [Annual readiness, including unpaid-item blocking](https://github.com/kristianelmer/Talli/blob/f55e7f15a8e64a2aacee29419cb60c338e141c27/apps/web/app/lib/annual-readiness.ts)
- [Web share-purchase boundary](https://github.com/kristianelmer/Talli/blob/f55e7f15a8e64a2aacee29419cb60c338e141c27/apps/web/app/lib/share-purchase.ts)
- [RF-1086 ordinary-share-class readiness](https://github.com/kristianelmer/Talli/blob/f55e7f15a8e64a2aacee29419cb60c338e141c27/holding_core/readiness.py)
- [Product decision excluding broad operating workflows](https://github.com/kristianelmer/Talli/blob/f55e7f15a8e64a2aacee29419cb60c338e141c27/docs/adr/0001-position-as-holding-first-not-fiken-clone.md)

This is stricter than the repo's plain-language `simple holding AS` definition. Coverage must be tested against the full code path for all three filings, not against that label alone.

## The 300-company screening sample

The sample was drawn from the 12,699-company core, not the broader name-based stratum:

1. Fetch all `64.323` AS entities by requesting the first 10 pages sorted by organisation number ascending and descending, then deduplicate. This works around the API's 10,000-result window and recovered all 14,004 entities reported by the count query.
2. Apply the active, 2025-accounts, no-VAT, and zero-employee filters locally.
3. Sort candidates by `SHA-256("talli-coverage-v1:" + organisation_number)` and take the first 300.
4. Fetch each sampled company's latest company accounts from Brønnøysundregistrene's open key-figures endpoint. All 300 returned 2025 company accounts. The API itself says its open part contains key figures from the latest submitted annual accounts. [Regnskapsregister API specification](https://data.brreg.no/regnskapsregisteret/regnskap/v3/api-docs/regnskapsregisteret)
5. Keep only aggregate results. No sampled organisation numbers or personal data are stored in this repository.

| Observed public-data pattern | Sample | Share | 95% Wilson interval | Talli meaning |
| --- | ---: | ---: | ---: | --- |
| Small-enterprise rules | 299/300 | 99.7% | 98.1%–99.9% | Strong fit signal |
| Audit opt-out recorded | 225/300 | 75.0% | 69.8%–79.6% | Missing opt-out needs classification; it is not automatically proof of mandatory audit |
| Parent-company flag | 10/300 | 3.3% | 1.8%–6.0% | Not a blocker by itself; group facts still need checking |
| Non-zero operating income | 36/300 | 12.0% | 8.8%–16.2% | Likely invoicing/operating or other unsupported income |
| Non-zero long-term debt | 57/300 | 19.0% | 15.0%–23.8% | Likely loan/intercompany complexity; exact type is hidden |
| Non-zero wage cost | 0/300 | 0% | 0%–1.3% | Expected after the zero-employee registry filter, but prior-year payroll can still be missed |

The **cautious screen** required small-enterprise status, audit opt-out, zero operating income, zero wage cost, zero inventory, zero goodwill, and zero long-term debt. It passed 157/300 (52.3%, 95% CI 46.7%–57.9%).

The **optimistic screen** required only small-enterprise status and no reported operating income, wage cost, inventory, or goodwill. It passed 263/300 (87.7%, 95% CI 83.5%–90.9%). It intentionally ignored audit status and long-term debt.

Neither screen is an eligibility test. The open key-figures API omits the detail needed to identify many of Talli's rules, and absent fields cannot safely be treated as zero. The screens show why a registry-only 80% claim would be unsafe: reasonable treatments of visible ambiguity move the result from about 52% to 88% before hidden blockers are considered.

## Largest gaps to measure next

### Measured in the core sample

1. **Audit and annual-account filing shape — up to 25%.** A quarter of the sample had no audit opt-out recorded in the key figures. This mixes mandatory audit, voluntary audit, and possible data gaps, so it needs manual classification.
2. **Long-term debt and loans — 19%.** Talli's automatic tax-return path blocks shareholder/intercompany loans, while the public key figures expose only the amount, not the counterparty or loan type.
3. **Operating income — 12%.** These companies passed the no-VAT/no-employee screen but still reported operating income. Some may be simple non-VAT income; others need invoicing, receivables, or an operating module.

These categories overlap and must not be added together.

### Important but not measurable from the open key figures

- owner dividends;
- shareholder and intercompany loan direction, terms, and security;
- Norwegian private shares versus listed securities, funds, foreign shares, property, or other assets;
- whether each investment is clearly within `fritaksmetoden`;
- number and type of share classes;
- foreign or corporate shareholders and unequal dividend rights;
- group contributions, tax credits, losses, prior-year corrections, and unpaid items;
- transaction count and whether every source document and bank movement can be reconstructed; and
- owner management and willingness to buy self-service software.

Skatteetaten's shareholder-register extract can supply year-end owners, share class, share count, and total company shares. Skatteetaten also warns that reported data may contain errors and that business use of the personal data needs its own lawful basis and secure handling. Do not order or retain the extract until that privacy step is approved. [Skatteetaten: Aksjonærregisteret](https://www.skatteetaten.no/deling/aksjonarregisteret/)

## Repeatable proof for the 80% gate

Use this before general availability and repeat it against the latest complete accounting year after any material support-boundary change.

1. **Freeze the eligibility matrix.** Give every supported and unsupported pattern a machine-readable code tied to the exact Talli commit. A company is a pass only if it can complete bookkeeping and all three direct filings without a manual workaround.
2. **Build the broad frame.** Re-run the two Enhetsregister screens (`64.323` and name contains `holding`), deduplicate, and preserve the query date, API version, row counts, and a hash of the organisation-number list outside the public repo.
3. **Apply only safe automatic exclusions.** Exclude non-AS, bankruptcy/liquidation, no current annual accounts, VAT registration, registered employees, and clearly regulated/special-purpose codes. Do not exclude a company merely because it is in a group.
4. **Draw a deterministic stratified sample of at least 600.** Stratify at minimum by code-based versus name-only candidates, asset-size band, company age, parent/group flag, and geography. Weight the result back to the candidate frame. A simple unweighted sample of 600 needs at least 497 passes (82.8%) for a one-sided 95% Wilson lower bound above 80%; a weighted design must use its survey-weighted lower bound instead.
5. **Classify with official evidence.** Use Enhetsregister entity/role/group data, latest Regnskapsregister key figures and annual-accounts copy, and—only after privacy approval—the shareholder-register extract. Record `pass`, a specific unsupported-pattern code, or `unknown`. Count `unknown` as fail for the launch gate.
6. **Double-check ambiguous cases.** Two independent reviewers should agree on every `unknown` and a random 10% of pass/fail classifications. Resolve disagreements against the frozen eligibility matrix, not intuition.
7. **Test the product, not just the paperwork.** A representative subset of public-data passes must become synthetic golden cases, and the private pre-launch group must prove bank sync, current-year reconstruction, bookkeeping, readiness, and all three filing paths. Public accounts cannot prove voucher completeness or transaction classification.
8. **Pass only on the lower bound.** Launch clears this gate only when the one-sided 95% lower confidence bound for the weighted supported share is at least 80%, with no open unknown category large enough to reverse the result.
9. **Publish the boundary, not the raw sample.** Keep personal/company-level research data out of the repo. Publish aggregate counts, method, uncertainty, exclusions, and the eligibility wording customers will see.

## Decision

The map should carry forward these facts:

- Use **46,339** only as the current broad registry candidate frame and **12,699** as its higher-signal industry-coded core, both dated 2026-08-26.
- Do not publish either as the addressable-market total and do not claim 80% coverage.
- Assume the current product needs scope work until the 600-company weighted audit and pre-launch validation prove otherwise.
- Investigate audit/annual-account shape, long-term debt/loans, and operating income first; then measure the hidden dividend, shareholder, investment, and tax patterns.
- Decide which extra product patterns to add only after the weighted gap table shows what is needed to move the conservative lower bound above 80%.
