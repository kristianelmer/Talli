# Supported domestic investment patterns

Status: normative implementation input for issue #190

Source cut: 2026-08-31 (Europe/Oslo)

Product boundary: the [owner-approved resolution of issue #172](https://github.com/kristianelmer/Talli/issues/172#issuecomment-5423704900)

## Purpose and interpretation

This evidence map turns the official rules relevant to a small Norwegian holding AS into a deliberately narrower deterministic product boundary. It is not a statement that other investments or accounting treatments are unlawful. “Hard block” means that Talli must stop the affected workflow and dependent completion/filing gates, explain the unsupported fact, and preserve truthful read/export access. It must not guess a tax class, ownership fact, fund percentage, accounting policy, or value.

The law and official guidance establish the accounting, tax, filing, documentation, and retention requirements. The accepted event shapes, source topology, separate book/tax measures, idempotency, and fail-closed rules below are Talli controls for meeting them. “Low-volume” is an owner-approved product boundary, not a statutory numeric threshold; #172 expressly rejects an arbitrary transaction-count limit and instead blocks activity that indicates active trading, incomplete evidence, or an unusable self-service case.

This map establishes data and evidence requirements only. It is not evidence that a broker, fund, bank, or data provider is selected, connected, activated, or authorized for live use.

The consolidated law at the source cut must not be applied blindly to an earlier company-year. Talli must select the version applicable to the event and company-year. The 2026 fund rules noted below apply from income year 2026.

## Primary-source register

The evidence below is pinned to the requested 2026-08-31 source cut.

| Source | Version or use |
| --- | --- |
| [Skatteloven](https://lovdata.no/lov/1999-03-26-14/) | Consolidated text, last amended by LOV-2026-06-23-66. Core sections: [§ 2-38](https://lovdata.no/lov/1999-03-26-14/%C2%A72-38), [§ 6-24](https://lovdata.no/lov/1999-03-26-14/%C2%A76-24), [§ 10-4](https://lovdata.no/lov/1999-03-26-14/%C2%A710-4), [§ 10-20](https://lovdata.no/lov/1999-03-26-14/%C2%A710-20), [§ 10-32](https://lovdata.no/lov/1999-03-26-14/%C2%A710-32), and [§ 10-36](https://lovdata.no/lov/1999-03-26-14/%C2%A710-36). |
| [Skatteetaten: Fritaksmetoden](https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/fradrag/aksjer/fritaksmetoden/) | Current source-owner summary of eligible income, 3% inclusion, losses, funds, and exclusions. |
| [Skatte-ABC 2025/2026: Norwegian exemption-method objects](https://www.skatteetaten.no/rettskilder/type/handboker/skatte-abc/gjeldende/f-32-fritaksmetoden/F-32.020/F-32.022/) | Current administrative practice for shares and fund units in entities resident in Norway. |
| [Skatte-ABC 2025/2026: share dividends](https://oppslag.rettskilder.skatteetaten.no/rettskilder2/type/handboker/skatte-abc/gjeldende/skatteabc-A-6) | Current decision-date, ownership, lawful-dividend, and accounting-period evidence. |
| [Skatte-ABC 2025/2026: fund distributions](https://www.skatteetaten.no/rettskilder/type/handboker/skatte-abc/gjeldende/v-6-verdipapirfond/V-6.006/V-6.007/) and [fund realizations](https://www.skatteetaten.no/rettskilder/type/handboker/skatte-abc/gjeldende/v-6-verdipapirfond/V-6.006/V-6.020/) | Current fund scope, equity-share split, realization, and FIFU guidance, including the 2026 changes. |
| [Skatteetaten: shares owned by a company](https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/fradrag/aksjer/aksjer-i-naring-selskapets-aksjer/) | Current company-tax guidance for dividends, gains/losses, RF-1088S, and year-end tax values. |
| [Skatteetaten: RF-1086](https://www.skatteetaten.no/bedrift-og-organisasjon/rapportering-og-bransjer/aksjonarregisteroppgaven/) and [2025 official instructions (RF-1087)](https://www.skatteetaten.no/globalassets/skjema/2025/rettledning/rf-1087_2025ny_bm.pdf) | Current filing route and latest completed-year instructions available at the source cut. |
| [Regnskapsloven](https://lovdata.no/lov/1998-07-17-56/) | Consolidated text. Core sections: [§§ 5-1 to 5-8](https://lovdata.no/lov/1998-07-17-56/kap5) and [§ 6-2](https://lovdata.no/lov/1998-07-17-56/%C2%A76-2). |
| [NRS 8 God regnskapsskikk for små foretak](https://www.regnskapsstiftelsen.no/wp-content/uploads/2026/01/NRS-8-God-regnskapsskikk-for-sma-foretak-2025-desember.pdf) | Norsk RegnskapsStiftelse, December 2025; used only after eligibility for the small-entity rules and the selected accounting policy are established. Relevant sections: 4.3.3, 4.4.4, and 5.3.2. |
| [Bokføringsloven](https://lovdata.no/lov/2004-11-19-73/) and [bokføringsforskriften](https://lovdata.no/forskrift/2004-12-01-1558/) | Documentation, traceability, balance evidence, correction, retention, and securities-register evidence. |
| [Skatteetaten: SAF-T questions and answers](https://www.skatteetaten.no/bedrift-og-organisasjon/starte-og-drive/rutiner-regnskap-og-kassasystem/saf-t-regnskap/sporsmal-og-svar---standardformat-regnskap/) and [format documentation](https://www.skatteetaten.no/bedrift-og-organisasjon/starte-og-drive/rutiner-regnskap-og-kassasystem/saf-t-regnskap/dokumentasjon/) | Current scope and 2026 format versions. |
| [Altinn: transfer of shares](https://info.altinn.no/starte-og-drive/drive-bedrift/drift-og-administrasjon/aksjeeier) | Current official operational guidance for agreements, notice, consent/pre-emption, and the shareholder register. |

## Accepted envelope

An investment event is accepted only when every applicable positive fact is evidenced:

- The investor is the in-scope Norwegian holding AS, the event belongs to its calendar company-year, and every amount and settlement account is in NOK.
- The instrument is either one ordinary share class in an identifiable Norwegian AS/ASA or a unit class in an identifiable qualifying Norwegian `verdipapirfond`. A marketing label such as “aksjefond” or “ETF” is not proof of legal or tax type.
- The event is a simple cash purchase, cash sale/redemption, lawful cash dividend, or ordinary cash fund distribution. There is no leverage, short sale, securities lending, derivative, conversion, in-kind consideration, special right, or corporate action.
- Issuer/fund identity, organization number or ISIN, instrument/share class, quantity, ownership/trade date, settlement date, gross amount, fees, counterparty/provider, NOK currency, and immutable source references are complete.
- The book classification and company-year accounting policy are explicit. Tax eligibility and the applicable tax-law version are separately explicit. A listing or cash movement alone proves neither.

Norwegian AS/ASA shares are objects under the exemption method for a Norwegian AS investor when the distribution is lawful: gains are exempt, losses are not deductible, and 3% of a qualifying dividend is ordinarily taxable income under [skatteloven § 2-38](https://lovdata.no/lov/1999-03-26-14/%C2%A72-38) and [Skatteetaten's current guidance](https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/fradrag/aksjer/fritaksmetoden/). Talli may therefore accept both Norwegian private-company shares and simple low-volume listed Norwegian shares without treating “private” or “listed” as the tax conclusion.

From income year 2026, the fund regime applies to UCITS funds, Norwegian national funds, and qualifying foreign equivalents under [skatteloven § 10-20 seventh paragraph](https://lovdata.no/lov/1999-03-26-14/%C2%A710-20). Talli's narrower domestic route accepts only a positively identified Norwegian qualifying fund with provider-issued tax data sufficient for every split below. It does not infer qualification or percentages.

## Deterministic event map

### Purchase

Required primary evidence is a broker contract note or executed private-share/subscription agreement, plus settlement evidence. For a private-company transfer, also require the acquirer's notice to the issuer and dated evidence of entry in the issuer's shareholder register; consent and pre-emption must be resolved where applicable. Altinn states that the agreement should identify the parties, shares, and price, that the acquirer must notify the board, and that the shareholder register is updated immediately after completion ([Altinn: Aksjeeier](https://info.altinn.no/starte-og-drive/drive-bedrift/drift-og-administrasjon/aksjeeier)). A bank payment alone is insufficient.

Acquisition cost is purchase price plus purchase expenses under [regnskapsloven § 5-4](https://lovdata.no/lov/1998-07-17-56/%C2%A75-4). Tax basis likewise includes acquisition costs under [skatteloven § 10-32](https://lovdata.no/lov/1999-03-26-14/%C2%A710-32); acquisition and realization costs tied to exemption-method shares are not separately deductible under [§ 6-24](https://lovdata.no/lov/1999-03-26-14/%C2%A76-24). Preserve gross price and each fee separately even when the canonical lot stores their sum.

Talli creates one immutable acquisition lot keyed by issuer/fund and class, event date, quantity, book cost, tax basis, and source evidence. A simple settled purchase posts investment at book acquisition cost against bank. If ownership transfers before cash settlement, it posts a documented settlement payable and clears that payable against the linked bank movement; settlement is not allowed to change the lot's ownership date.

### Sale or fund redemption

Required evidence is the executed agreement or broker/fund contract note, quantity/class, transfer or trade date, gross consideration, sale costs, settlement date, and linked bank evidence. Share gain or loss is net consideration after realization costs less tax basis under [skatteloven § 10-32](https://lovdata.no/lov/1999-03-26-14/%C2%A710-32); those realization costs are not a separate deduction for exemption-method shares under [§ 6-24](https://lovdata.no/lov/1999-03-26-14/%C2%A76-24). Tax timing follows transfer of ownership, normally the trade/agreement date, rather than blindly using the bank date ([Skatte-ABC 2025/2026: timing of share gains and losses](https://www.skatteetaten.no/rettskilder/type/handboker/skatte-abc/gjeldende/t-4-tidfesting--realisasjonsprinsippet/T-4.058/T-4.062/)).

Tax lots are consumed first-in-first-out within the same issuer and share class under [skatteloven § 10-36](https://lovdata.no/lov/1999-03-26-14/%C2%A710-36). The same rule applies per share class in each fund ([Skatte-ABC 2025/2026: fund realization](https://www.skatteetaten.no/rettskilder/type/handboker/skatte-abc/gjeldende/v-6-verdipapirfond/V-6.006/V-6.020/)). Unknown acquisition chronology is a hard block; Talli does not silently substitute the statutory lowest-basis fallback.

For a qualifying ordinary Norwegian share, realized book gain/loss remains a real accounting result, while the tax engine records the gain as exempt or the loss as non-deductible. The 3% rule does not apply to realization gains or losses. Talli must persist book proceeds, derecognized book cost, book gain/loss, tax basis, tax gain/loss, and exemption adjustment as separate measures.

For a fund realization, the equity percentage is the average of the fund's deemed equity percentage at the beginning of the acquisition year and sale year, using the statutory year-end substitute where the fund was established during the relevant year. The resulting equity portion of gain is exempt and the equity portion of loss is non-deductible; the remaining portion is taxable/deductible under [skatteloven § 10-20 sixth paragraph](https://lovdata.no/lov/1999-03-26-14/%C2%A710-20) and [Skatte-ABC 2025/2026 section V-6-3.3](https://www.skatteetaten.no/rettskilder/type/handboker/skatte-abc/gjeldende/v-6-verdipapirfond/V-6.006/V-6.020/). Talli must retain both annual percentages and the exact split calculation.

### Received cash dividend from a Norwegian AS/ASA

Required evidence is the issuer, share class, gross amount, decision and payment dates, competent-body resolution, ownership at the decision date, payment evidence, and positive lawful-dividend classification. A dividend is normally earned for tax when the general meeting decides it, or when an authorized board decides it; actual payment can occur later ([Skatte-ABC 2025/2026 sections A-6-3 and A-6-10](https://oppslag.rettskilder.skatteetaten.no/rettskilder2/type/handboker/skatte-abc/gjeldende/skatteabc-A-6)). Talli therefore records the receivable and dividend income from the supported decision, then clears the receivable on bank settlement. It never dates income from the bank row alone.

For an ordinary qualifying dividend, tax inclusion is exactly 3% of gross qualifying dividend; at the current 22% ordinary income rate that produces 0.66% effective tax ([Skatteetaten: Fritaksmetoden](https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/fradrag/aksjer/fritaksmetoden/)). This is a tax adjustment, not a second dividend or ledger receipt.

The 3% inclusion does not apply to a dividend within the statutory group exception. That exception requires the companies to be in the same group and the conditions in [skatteloven § 10-4](https://lovdata.no/lov/1999-03-26-14/%C2%A710-4), including more than nine-tenths of shares and corresponding votes at the end of the income year, to be evidenced. Do not encode the simplified “90% or more” wording as the legal threshold. Missing vote, ownership, timing, or group evidence means the ordinary 3% route or a hard block; it never means automatic zero inclusion.

NRS 8 section 5.3.2 permits dividend income when the decision is made, but distinguishes income earned after acquisition from return of invested capital and permits other timing policies in specified control/influence cases. Talli freezes decision-year recognition for this supported pattern. A claimed prior-year accrual, repayment of paid-in capital, distribution soon after a material acquisition where the income/capital split matters, or any other policy conflict hard-blocks rather than being recast as an ordinary dividend ([NRS 8, section 5.3.2](https://www.regnskapsstiftelsen.no/wp-content/uploads/2026/01/NRS-8-God-regnskapsskikk-for-sma-foretak-2025-desember.pdf)).

### Received cash distribution from a Norwegian fund

Required evidence is the fund and class, gross distribution, decision/entitlement and payment dates, units held, provider tax statement, and the fund's equity percentage at the beginning of the income year, or at year-end if the fund was established during that year. The distribution is classified under [skatteloven § 10-20 second and third paragraphs](https://lovdata.no/lov/1999-03-26-14/%C2%A710-20):

| Documented opening equity percentage | Deterministic tax classification |
| --- | --- |
| More than 80% | 100% dividend-character income. The exemption method applies and 3% of that qualifying portion is included. |
| Less than 20% | 100% ordinary interest income; no exemption-method treatment. |
| 20% through 80% inclusive | Proportional dividend/interest split using the documented percentage; the exemption method and 3% inclusion apply only to the dividend-character portion. |

The official treatment for company investors is confirmed in [Skatte-ABC 2025/2026 section V-6-3.1.4](https://www.skatteetaten.no/rettskilder/type/handboker/skatte-abc/gjeldende/v-6-verdipapirfond/V-6.006/V-6.007/). Persist the gross distribution, provider percentage, dividend portion, interest portion, 3% inclusion, and source revision separately. Missing fund reporting or a complex distribution is a hard block even though [§ 10-20 ninth paragraph](https://lovdata.no/lov/1999-03-26-14/%C2%A710-20) supplies adverse statutory fallbacks; Talli's accepted route requires positive, reviewable tax evidence.

## Book classification and year-end measurement

Book classification depends on the purpose of ownership, not simply on whether the instrument is private or listed. Assets intended for permanent ownership/use are fixed assets; others are current assets under [regnskapsloven § 5-1](https://lovdata.no/lov/1998-07-17-56/%C2%A75-1). Talli requires an explicit, versioned classification and does not infer “current” from a broker or “fixed” from an unlisted issuer.

For a small entity using NRS 8:

- Financial fixed assets are initially measured at cost and are subject to impairment/reversal rules. Subsidiaries, associates, and other long-term shares have distinct balance presentation ([NRS 8 section 4.3.3](https://www.regnskapsstiftelsen.no/wp-content/uploads/2026/01/NRS-8-God-regnskapsskikk-for-sma-foretak-2025-desember.pdf)).
- Short-term shares/fund units use lower of acquisition cost and fair value; listed securities are normally short-term absent evidence of lasting ownership. NRS 8 permits FIFO for interchangeable financial current assets as a small-entity simplification, even though average cost is otherwise described. Talli freezes FIFO for the accepted route so book and tax lot consumption remain deterministic ([NRS 8 section 4.4.4](https://www.regnskapsstiftelsen.no/wp-content/uploads/2026/01/NRS-8-God-regnskapsskikk-for-sma-foretak-2025-desember.pdf)).
- Instruments meeting every condition for a trading portfolio on a regulated market are ordinarily measured at fair value under [regnskapsloven § 5-8](https://lovdata.no/lov/1998-07-17-56/%C2%A75-8), although a small entity may choose the § 5-2 route. Active trading is outside Talli's boundary, so an instrument classified as a trading-portfolio holding hard-blocks rather than silently changing the accounting policy.

At year end, Talli must preserve quantity, book classification, acquisition lots, book cost, selected measurement rule, observable price or valuation evidence, impairment/valuation calculation, book closing value, tax basis, and tax value as separate facts. A tax-exempt loss can still require a book write-down. Documentation for every material balance is required by [bokføringsloven § 11](https://lovdata.no/lov/2004-11-19-73/%C2%A711), securities registered in a securities register require a holdings statement under [bokføringsforskriften § 6-3](https://lovdata.no/forskrift/2004-12-01-1558/%C2%A76-3), and any valuation judgment must retain method and assumptions under [§ 6-4](https://lovdata.no/forskrift/2004-12-01-1558/%C2%A76-4).

## Cross-output reconciliation

One accepted event must project from the same immutable facts; no filing adapter may recompute ownership, lots, or tax classification independently.

| Output | Required implication |
| --- | --- |
| Positions and lots | Opening quantity + accepted purchases - accepted sales = closing quantity for each issuer/fund and class. Lot quantities, book cost, and tax basis reconcile independently. |
| Ledger | Purchases, disposal proceeds/cost, realized book result, receivables/payables, dividend/distribution income, bank settlement, and year-end measurement are balanced and traceable. Tax-only exemption and 3% adjustments are not invented ledger cash/income. |
| Company tax | Ordinary domestic share gains are excluded, losses added back, qualifying dividends carry the 3% inclusion unless the proved group exception applies, and fund income/gains/losses use the documented statutory split. The company must also report share wealth values even though an AS pays no wealth tax; RF-1088S is informational and must be reviewed/corrected ([Skatteetaten: shares owned by a company](https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/fradrag/aksjer/aksjer-i-naring-selskapets-aksjer/)). |
| Annual accounts | Investment classification, closing measurement, realized/unrealized financial result, dividend/distribution income, and required balance/note lines derive from the selected policy. Annual accounts remain a separate obligation from the tax return ([Brønnøysundregistrene: annual-account contents](https://www.brreg.no/innsending-av-arsregnskap/hva-skal-arsregnskapet-inneholde/)). |
| SAF-T | Every booked investment journal and master-data reference flows through the same ledger export. SAF-T is an audit-request format, not a substitute for ordinary tax reporting. Electronic accounting systems are generally in scope; the sub-NOK 5 million exception does not apply when booked data is nevertheless electronically available ([Skatteetaten: SAF-T questions and answers](https://www.skatteetaten.no/bedrift-og-organisasjon/starte-og-drive/rutiner-regnskap-og-kassasystem/saf-t-regnskap/sporsmal-og-svar---standardformat-regnskap/)). For financial year 2026, version 1.30 remains usable and 1.40 is optional; 1.40 becomes the sole valid version from 2027 ([format documentation](https://www.skatteetaten.no/bedrift-og-organisasjon/starte-og-drive/rutiner-regnskap-og-kassasystem/saf-t-regnskap/dokumentasjon/)). |
| Company archive | Store the source document, provider statement, decision/contract, identity/class, dates, quantities, price/fees, bank evidence, lot allocations, calculations, classification/policy, year-end evidence, corrections, and output references. Booked facts and balance documentation are retained for five years after year-end; relevant agreements/correspondence have a three-year-six-month statutory period under [bokføringsloven § 13](https://lovdata.no/lov/2004-11-19-73/%C2%A713). Talli retains the full evidence pack for at least the longer five-year period as its simpler control. |

### RF-1086 boundary

RF-1086 reports the issuing company's own capital, shares, shareholder events, and distributions. The official instructions say the return has company data plus one set of shareholder data per shareholder; ownership changes and dividends are reported by the company in which the event occurs ([RF-1087 instructions, pp. 2–3 and post 8](https://www.skatteetaten.no/globalassets/skjema/2025/rettledning/rf-1087_2025ny_bm.pdf)). Skatteetaten also states that every Norwegian AS/ASA files annually, while the company is exempt where VPS performs the reporting ([RF-1086 page](https://www.skatteetaten.no/bedrift-og-organisasjon/rapportering-og-bransjer/aksjonarregisteroppgaven/)).

Therefore, as a direct inference from the official reporting model:

- Buying or selling a portfolio holding does not change the holding AS's own issued shares and must not create a transaction in its own RF-1086.
- The Norwegian target issuer reports a private-share transfer and a dividend it pays; VPS may report the corresponding registered-share event. Talli must not file for an unrelated issuer.
- Talli reconciles the investor's positions, issuer/VPS evidence, RF-1088S/pre-filled information, company-tax facts, and ledger. If the target issuer is separately a Talli company, its RF-1086 remains a separately authorized company workflow.

## Evidence, corrections, and manual fallback

Each booked event requires correct, complete, immutable documentation that demonstrates the entry and links primary and corroborating documents under [bokføringsloven § 10](https://lovdata.no/lov/2004-11-19-73/%C2%A710). Ordinary broker/fund contract notes plus linked bank evidence are supported. A manual fallback is supported only when the user supplies the same complete authoritative fields and documents; manual entry is not permission to omit provider evidence or choose tax treatment.

Corrections are append-only reversals and replacements linked to the original event and reason; original booked information remains visible as required by [bokføringsloven § 9](https://lovdata.no/lov/2004-11-19-73/%C2%A79). Replaying the same immutable source/event is idempotent. A source reused with different economic facts is rejected, not posted as a second transaction.

## Hard-block matrix

| Block | Reason and official boundary |
| --- | --- |
| Foreign issuer/fund, withholding, foreign-tax credit, or FX | Residence, EEA substance, low-tax exclusions, outside-EEA ownership/time tests, treaty treatment, credit evidence, and NOK conversion introduce facts not present in the domestic route ([Skatteetaten: Fritaksmetoden](https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/fradrag/aksjer/fritaksmetoden/)). Block even if the broker reports NOK. |
| Crypto or tokenized asset | Virtual assets are not ordinary shares/fund units and have separate realization and income rules ([Skatteetaten: virtual assets](https://www.skatteetaten.no/person/skatt/hjelp-til-riktig-skatt/aksjer-og-verdipapirer/om/virtuell-valuta/skatteregler---virtuell-valuta/)). |
| Derivative, option, warrant, convertible, structured product, short, margin, or securities loan | Exemption treatment can depend on the instrument and underlying; the official exemption guidance expressly treats derivatives and other products separately ([Skatteetaten: Fritaksmetoden](https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/fradrag/aksjer/fritaksmetoden/)). |
| Active/high-volume trading | Whether activity is systematic, continuing, short-term-profit-oriented business is fact-sensitive, and trading-portfolio classification changes book measurement ([Skatte-ABC: investment activity as business](https://www.skatteetaten.no/rettskilder/type/handboker/skatte-abc/gjeldende/v-9-virksomhet--allment/V-9.009/V-9.051/); [regnskapsloven § 5-8](https://lovdata.no/lov/1998-07-17-56/%C2%A75-8)). Do not invent a public numeric safe harbor. |
| Complex fund fact or distribution | Missing/uncertain legal fund type, annual equity percentage, underlying-fund data, provider tax statement, accumulation/distribution character, return of capital, or non-cash distribution prevents the exact [§ 10-20](https://lovdata.no/lov/1999-03-26-14/%C2%A710-20) split. |
| Corporate action or unusual ownership right | Merger, demerger, liquidation, conversion, split/reverse split, bonus issue, rights issue, redemption, capital repayment, gift/inheritance, treasury shares, non-cash or skewed distribution can change realization, basis, paid-in capital, timing, or RF-1086 treatment. The official company-share guidance lists such events as basis-changing cases ([Skatteetaten: shares owned by a company](https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/fradrag/aksjer/aksjer-i-naring-selskapets-aksjer/)). |
| Unclear tax, accounting, ownership, entitlement, or evidence | Missing exemption eligibility, lawfulness, group votes/ownership, transfer date, class, chronology, book classification/policy, tax value, or reconciliation is a hard block. An accountant-review label is an exit route, not authority for Talli to post or file a guess. |

## Implementation constraints

The supported implementation must:

1. Accept only the four semantic event types above through one versioned Python policy: purchase, sale/redemption, received share dividend, and received fund distribution.
2. Keep book value, tax basis, realized book result, taxable/exempt gain or loss, dividend/interest split, 3% inclusion, and year-end tax value as distinct persisted measures.
3. Use stable issuer/fund plus class identity and tax FIFU lots; preserve source precision and apply rounding only at a named output boundary.
4. Record ownership/trade, decision/entitlement, and settlement dates separately. Bank evidence settles an already classified event; it does not select recognition date or tax treatment.
5. Require positive domestic, instrument, fund, lawfulness, group-exception, policy, and evidence facts. Unknown is never coerced to `false`, zero, ordinary dividend, or 100% equity.
6. Project the same accepted fact and calculation IDs to positions/lots, ledger, company tax, annual accounts, SAF-T, and archive. RF-1086 receives only the holding AS's own issuer events, never portfolio activity.
7. Make every command atomic and replay-idempotent, and correct only by linked reversal/replacement. Any failing projection leaves every output unchanged.
8. Re-run the company-year eligibility and filing gates when a new investment fact changes the boundary. A hard block must propagate to every dependent annual completion claim without erasing prior records or export access.
