# RF-1086 capital scope — 2026-10-10

Status: public-source semantics and local scope review; no production acceptance, legal/compliance conclusion, or launch authorization.

Reviewed 2026-10-10 UTC against local SHA `9212dde76b3048c877b4dd4b0d8246c415ccc9bb`. Cited implementation files match that SHA. No code, approval source, provider-contract note, tests, CI, DB, credentials, deployments, submissions, spending, or outreach were changed/run. Graphify was unavailable; no installation or graph generation was attempted.

## Sources and freshness

The [current RF page][rf-page] links **RF-1087 guidance for income year 2025**, file `rf-1087_2025ny_bm.pdf`. Its downloaded response reports Last-Modified **2026-05-05 12:05:47 GMT**; PDF metadata reports creation/modification **2026-05-04**. The older `rf-1087_2025_bm.pdf` remains downloadable but is not the currently linked file. This review uses the linked version, including posts 5/6, 9/23, 15/29, and 16. Its page 7 was visually checked. These are document/capture dates, not a claim that 2026 filing guidance has been published. [Current page][rf-page], [linked 2025 guide][guide], read 2026-10-10.

Skatte-ABC **A-6** displays publication **2026-01-07**; Brønnøysund's increase guide displays **2025-10-14**, reduction guide **2024-05-29**. The Lovdata sources below are the **consolidated NL** chapters retrieved 2026-10-10, not original historical LTI enactment text. [Skatte-ABC][abc], [increase][brreg-increase], [reduction][brreg-reduction], [chapter 10][law10], [chapter 12][law12].

## Established semantics and exact local boundaries

| Variant | Official evidence | Baseline behavior / scope |
| --- | --- | --- |
| `cash_issue` | Cash new-share issuance uses posts 9/23. Detailed design `Valideringer!G87` (`MAKJ_008`) distinguishes **Nyemisjon `N`** from formation `T` and compares issued shares × (nominal + premium per share) with total acquisition amounts. | Emits `N` in 17670/17745; per-share premium in 23948 and total acquisition value in 17636. Replay requires positive allocated shares, existing nominal retained, exact acquisition amounts, and closing share/capital reconciliation. |
| `cash_nominal_increase` | Cash nominal increase uses posts 15/29, distinct from debt conversion. SBS XML has **`6`** in 28268; detailed design names that value and the relevant fields. | Emits `6` in 28268/28267; unchanged share count, each current holder once, nominal increase allocated by event-time holdings, premium totals reconciled. **Source workflow explicitly rejects this variant** with `rf1086_source_governance_nominal_increase_unavailable`; the Governance producer has no nominal-increase variant. Rendering support is not production source support. |
| `loss_covering_reduction` | Post 16 reports reduction of nominal capital for loss/fund transfer, separately identifying paid-in/fund-issued parts; fund-issued capital is reduced first. It has **no shareholder event**. | Only registered, positive nominal reductions with unchanged share count and **`fund_issued_capital_before=0`**; tax paid-in capital must cover registered capital. Emits paid-in reduction 17717 and fund-issued reduction 17721=0, with no repayment event; preserves tax paid-in capital/premium. |

Official sources: [2025 guide, pp. 4, 7, 9, 12][guide], [cash-versus-conversion examples][examples], [detailed design][design], [SBS nominal XML][nominal-example], all fetched 2026-10-10. Local sources: [codes][codes], [renderer][rendering], [replay validation][readiness], [source workflow][workflow], [v2 Governance mapping][context], baseline SHA above.

`codes.py` already marks `N` and `6` verified, with `production_blocker=False`; its code-blocker/exclusion functions therefore do not exclude them. The source boundary separately admits governed capital receipts for cash issues and loss-cover reductions only. The source register's historical no-activity wording must not be substituted for these exact code predicates, nor does this review establish a deployed enablement state. [Code decisions][codes], [source workflow][workflow], [source evidence register][register], baseline SHA.

Governance's cash subset requires one ordinary class, Norwegian subscribers, cash only, binding subscription, no special terms/direct-use exception, resolved issue-cost judgment, full timely payment, independent confirmation, and matching bank evidence. Registration adds articles, receipt, and independent register facts. Its loss subset requires loss only, available other equity exhausted, no value transfer, unchanged owners/share count, no creditor-notice route, and no simultaneous capital change. These are deliberate product exclusions, not evidence that the excluded alternatives are unlawful. [Governance validation][governance], baseline SHA. Brønnøysund separately describes cash, assets, debt conversion, and fund issuance as different routes. [Increase guide, updated 2025-10-14][brreg-increase].

## Nominal capital, actual contributions, and paid-in facts

**Do not infer tax paid-in amounts from registered nominal capital or ledger equity.** RF post 5 reports actual paid-in capital even when capital has been lost; post 6 preserves actually paid-in premium despite costs charged against it. Post 16's paid-in reduction is a reduction of registered capital, not a shareholder repayment. [Linked 2025 guide, posts 5/6/16][guide]. Skatte-ABC distinguishes tax paid-in capital attached to each share from the shareholder's purchase price; it may differ among shares in one company. [A-6-7.2, published 2026-01-07][abc].

Talli's source carries four reviewed, document-linked opening/closing tax paid-in totals, separate from the register observation's capital/count/nominal/holdings. The replay preserves those totals on the zero-fund/no-payout loss branch; it does not calculate a general per-share tax-basis ledger. Aggregate RF reporting can be sufficient for this subset; absence of a general lot model does not itself prove its output incorrect. Historical amounts, contribution provenance, and the zero-fund assertion still need reviewed originals rather than register arithmetic. [Paid-in facts][public], [source validation][year-source], [replay][readiness], baseline SHA; [RF post 5][guide], [A-6-7.2/7.7][abc].

Fund-issued capital is not interchangeable with freshly paid cash. Skatte-ABC describes redistribution of existing share tax positions for new bonus shares and special origin/allocation rules for mixed paid-in/earned funds. The zero-fund restriction avoids that general allocation problem; it must not be replaced by guessing `fund=registered capital − tax paid-in capital`. [A-6-7.5/7.6, published 2026-01-07][abc], [local loss validation][readiness].

Registration and payment evidence matter separately: consolidated §10-9 requires full contribution before notification; §10-10 makes registration the capital-increase effective point. Loss-only reductions without creditor notice take effect at registration under §12-5; that provision restricts dividends for three years with stated exceptions. Talli conservatively rejects later dividend events after loss coverage because its RF source lacks a verified clearance fact. The statutory exceptions do not compel wider product scope. [Consolidated chapter 10][law10], [chapter 12 §§12-1/12-5][law12], retrieved 2026-10-10; [local replay][readiness].

## Interpretation and evidence still required

The supported subset **can be encoded conservatively** with its present distinctions: real cash new-share issuance; zero-fund, no-payout loss coverage; nominal cash increases blocked at source capture. This is an engineering assessment of the predicates above, not a determination that all real cases satisfy them. These local exclusions describe present implementation; they do not authorize narrowing accepted launch promises. Any supported-boundary change requires reopening [#172](https://github.com/kristianelmer/Talli/issues/172) before a coverage claim. Before widening any branch, require:

1. **Cash versus conversion/fund provenance:** signed decision, contribution confirmation, actual cash, nominal/premium split, articles, and effective registration evidence. Do not reuse the cash equality rule for debt conversions: official examples distinguish their event types and valuation. Resolve issue costs without equating book premium with tax paid-in premium. [Examples][examples], [Brønnøysund increase guide][brreg-increase], [RF post 6][guide], [Governance][governance].
2. **Zero-fund and loss purpose:** reviewed historical capital composition and actual loss/other-equity evidence. Local facts encode aggregate tax totals and a literal zero, not a machine-derived history of fund origins. A register observation alone cannot establish that tax composition. Decide through domain signoff whether retained document roles/review prove this predicate for each supported case. [Paid-in/source facts][public], [source validation][year-source], [loss predicates][readiness], [RF post 16][guide].
3. **Nominal production extension:** a distinct authoritative Governance event and payment/register/economic binding. Existing `issued_share_count>0` cash producer must not be disguised with zero new shares. Until added, keep the explicit source rejection; a verified code and valid XML do not clear it. [Governance][governance], [source workflow][workflow], [source test][source-tests].
4. **Distribution clearance across years:** assess prior-year loss reductions, creditor procedure, later replenishment, and dates before supporting dividends/repayments. The replay's `loss_coverage_seen` check covers events in the supplied case; it does not itself prove absence of earlier restrictions. Keep unsupported clearances blocked or capture a reviewed, versioned clearance fact. [§12-5][law12], [replay][readiness].

Required regression evidence, without running tests here: multi-owner/partial new subscriptions and per-share versus total premium; actual contribution mismatches; gross tax premium versus book costs; event-time transfers before nominal increases; repeated loss reductions with tax paid-in greater than registered capital; unknown/nonzero fund composition rejection; no payout/owner event for post 16; prior-year restrictions; and registration crossing year-end. Existing tests cover basic field codes, reconciliations, malformed values, fund exclusion, post-loss dividend rejection, and nominal source rejection; this review does not establish the complete matrix's execution or provider acceptance. [Capital tests][capital-tests], [source tests][source-tests], baseline SHA; [2025 guidance][guide], [§12-5][law12].

## Durable provenance

Exact public response bodies are retained under **`/private/tmp/talli-release-20261009/rf-capital-research`**, directory mode `0700`; files are `0600`. [Primary-source index](/private/tmp/talli-release-20261009/rf-capital-research/primary-source-index-v1.json) contains all 13 source URLs, UTC retrieval times, complete SHA-256 hashes, byte lengths, and HTTP metadata. Index SHA-256: `e171aba9f5df346b5cb70df56c179b213cbc3e35765c2aa0b5554959e2ef2d7b`. Dynamic HTML hashes identify the capture, not immutable release versions.

| Key source artifact | SHA-256 |
| --- | --- |
| `rf1087-2025-current.pdf` | `f6607bccb036fbb1e79e0b279abcdf7fbf6800cdc4940f1f9e4ee59ab36667be` |
| `rf-1086_detaljert_design_2024.xlsx` | `7db3fed16350832056c3b363eb16ee03df49031358372026af73b6c899bc5c7d` |
| `nyemisjon_hovedskjema.txt` | `97834a7470cc998380084b5d8c9ad12ce51b4636d75a324f587f2b220cec6d20` |
| `skatteabc-A-6.html` | `b96d6b046f569f2c1451d92caab7aaa3c2b0d9ea033affaa96b004c8b841f018` |
| `lovdata-as-chapter10.html` | `e0bedc5e5e006d28cdbf49549450cb1db451938cb19839c5a847fee1c06d806b` |
| `lovdata-as-chapter12.html` | `898c0cc0317bacd3b9096bc028601edda5b478a731b0a7a37f582653cf98e890` |

Current main/child XSD bytes were downloaded at official revision `82c52dcb686cfd0eab74907096335cccd3f3e4ad`; their hashes match the 2026-09-17 source register (`194670…df` and `a0f6b2…b7`; full hashes in the index). The detailed design and nominal XML also match its pins. Schema/example provenance establishes allowed bytes and mapping evidence, not truth of submitted economic facts. [Main XSD][main-xsd], [child XSD][child-xsd], [source pins][pins].

[rf-page]: https://www.skatteetaten.no/bedrift-og-organisasjon/rapportering-og-bransjer/aksjonarregisteroppgaven/
[guide]: https://www.skatteetaten.no/globalassets/skjema/2025/rettledning/rf-1087_2025ny_bm.pdf
[examples]: https://www.skatteetaten.no/bedrift-og-organisasjon/rapportering-og-bransjer/aksjonarregisteroppgaven/eksempler-pa-utfylling-av-aksjonarregisteroppgaven/
[design]: https://www.skatteetaten.no/contentassets/d70d335c2a024f7ea7eb421fc53f4ec7/rf-1086_detaljert_design_2024.xlsx
[nominal-example]: https://www.skatteetaten.no/contentassets/050b9c39dcdd460d91a2addaf67a6eeb/nyemisjon_hovedskjema.txt
[abc]: https://oppslag.rettskilder.skatteetaten.no/rettskilder2/type/handboker/skatte-abc/gjeldende/skatteabc-A-6
[brreg-increase]: https://www.brreg.no/aksjeselskap/aksjekapital/forhoyelse-av-aksjekapital/
[brreg-reduction]: https://www.brreg.no/aksjeselskap/aksjekapital/nedsettelse-av-aksjekapital/
[law10]: https://lovdata.no/dokument/NL/lov/1997-06-13-44/KAPITTEL_10
[law12]: https://lovdata.no/dokument/NL/lov/1997-06-13-44/KAPITTEL_12
[main-xsd]: https://raw.githubusercontent.com/Skatteetaten/api-dokumentasjon/82c52dcb686cfd0eab74907096335cccd3f3e4ad/static/download/aksjonaerregisteroppgaveHovedskjema.xsd
[child-xsd]: https://raw.githubusercontent.com/Skatteetaten/api-dokumentasjon/82c52dcb686cfd0eab74907096335cccd3f3e4ad/static/download/aksjonaerregisteroppgaveUnderskjema.xsd
[codes]: https://github.com/kristianelmer/Tilli/blob/9212dde76b3048c877b4dd4b0d8246c415ccc9bb/apps/backend/src/talli_backend/modules/shareholder_register_filing/codes.py
[rendering]: https://github.com/kristianelmer/Tilli/blob/9212dde76b3048c877b4dd4b0d8246c415ccc9bb/apps/backend/src/talli_backend/modules/shareholder_register_filing/rendering.py
[readiness]: https://github.com/kristianelmer/Tilli/blob/9212dde76b3048c877b4dd4b0d8246c415ccc9bb/apps/backend/src/talli_backend/modules/shareholder_register_filing/readiness.py
[workflow]: https://github.com/kristianelmer/Tilli/blob/9212dde76b3048c877b4dd4b0d8246c415ccc9bb/apps/backend/src/talli_backend/application/shareholder_register_source_workflow.py
[context]: https://github.com/kristianelmer/Tilli/blob/9212dde76b3048c877b4dd4b0d8246c415ccc9bb/apps/backend/src/talli_backend/application/shareholder_register_source_context_v2.py
[governance]: https://github.com/kristianelmer/Tilli/blob/9212dde76b3048c877b4dd4b0d8246c415ccc9bb/apps/backend/src/talli_backend/modules/corporate_governance/service.py
[public]: https://github.com/kristianelmer/Tilli/blob/9212dde76b3048c877b4dd4b0d8246c415ccc9bb/apps/backend/src/talli_backend/modules/shareholder_register_filing/public.py
[year-source]: https://github.com/kristianelmer/Tilli/blob/9212dde76b3048c877b4dd4b0d8246c415ccc9bb/apps/backend/src/talli_backend/modules/shareholder_register_filing/year_source.py
[capital-tests]: https://github.com/kristianelmer/Tilli/blob/9212dde76b3048c877b4dd4b0d8246c415ccc9bb/apps/backend/tests/test_rf1086_capital_events.py
[source-tests]: https://github.com/kristianelmer/Tilli/blob/9212dde76b3048c877b4dd4b0d8246c415ccc9bb/apps/backend/tests/test_shareholder_register_capital_source_workflow.py
[register]: https://github.com/kristianelmer/Tilli/blob/9212dde76b3048c877b4dd4b0d8246c415ccc9bb/docs/filing/rf1086-code-evidence-register.md
[pins]: https://github.com/kristianelmer/Tilli/blob/9212dde76b3048c877b4dd4b0d8246c415ccc9bb/docs/filing/rf1086-official-sources.json
