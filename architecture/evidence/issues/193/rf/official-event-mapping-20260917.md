# RF-1086 event mapping evidence — 17 September 2026

This research establishes encoded meanings and an offline capital-event subset. It does not establish TT02 conformance, production acceptance, production source integration, or completion of RF release criteria. All fetched artifacts are public first-party material; no private company data is included here.

## Encoded meanings

The labelled Skatteetaten SBS examples resolve earlier unsupported inferences. Formation is **T**, purchase **K**, sale **R**, and ordinary dividend **Y**. An unlabelled transport example containing N cannot establish formation semantics. N denotes new issuance.

| Meaning and field | First-party evidence | SHA-256 of downloaded bytes |
| --- | --- | --- |
| Formation: main 17670 = T | [Formation main](https://www.skatteetaten.no/contentassets/050b9c39dcdd460d91a2addaf67a6eeb/stiftelseavselskap_hovedskjema.txt) | `e17122a053a5afbbbc22fc973b14237a4333e8eaac2242d99729770210ff6c20` |
| Formation: shareholder 17745 = T | [Formation shareholder](https://www.skatteetaten.no/contentassets/050b9c39dcdd460d91a2addaf67a6eeb/stiftelseavselskap_underskjema.txt) | `78178e1b040adcf13a0f813217788ad9f4757f96b1075a61a8e56ca00ac8b43e` |
| Sale: shareholder 17753 = R | [Seller](https://www.skatteetaten.no/contentassets/050b9c39dcdd460d91a2addaf67a6eeb/kjopogsalg_underskjema_en.txt) | `41a150eba0eec7e11aa57d1e2c48ce9b8bf868229b5a1a5294461423b5f3b65d` |
| Purchase: shareholder 17745 = K | [Buyer](https://www.skatteetaten.no/contentassets/050b9c39dcdd460d91a2addaf67a6eeb/kjopogsalg_underskjema_to.txt) | `795311baa395715a5c413a5da818f5204c1cac4b67bbea6a3a2fdc87334e6054` |
| Dividend: main 36564 = Y; 17665 holds total amount | [Dividend main](https://www.skatteetaten.no/contentassets/050b9c39dcdd460d91a2addaf67a6eeb/utbytte_hovedskjema.txt) | `1d94f08caa2182e70c73b92c08324b15d29a3c6acf956d4796bfef71c9ce039a` |
| Cash nominal increase: main 28268 = 6 | [Nominal increase main](https://www.skatteetaten.no/contentassets/050b9c39dcdd460d91a2addaf67a6eeb/nyemisjon_hovedskjema.txt) | `97834a7470cc998380084b5d8c9ad12ce51b4636d75a324f587f2b220cec6d20` |

The last example is formation followed by a nominal increase. Its filename alone does not prove N. The [RF-1086 detailed design workbook](https://www.skatteetaten.no/contentassets/d70d335c2a024f7ea7eb421fc53f4ec7/rf-1086_detaljert_design_2024.xlsx), SHA-256 `7db3fed16350832056c3b363eb16ee03df49031358372026af73b6c899bc5c7d`, establishes N explicitly in worksheet `Valideringer`: row 87 / MAKJ_008 pairs Nyemisjon (N) with Stiftelse (T), connects company post 9 and shareholder post 23, and reconciles nominal plus premium **per share** times issued count against total acquisition values. Rows 86 and 93 independently label N. Rows 91–92 reconcile post 15 capital/premium with post 29 and identify nominal increase code 6. This workbook carries historical rule notes; those notes are semantic evidence, not a claim every historical validation rule is still active.

## Registered capital changes

The [2025 official guidance](https://www.skatteetaten.no/globalassets/skjema/2025/rettledning/rf-1087_2025ny_bm.pdf), SHA-256 `f6607bccb036fbb1e79e0b279abcdf7fbf6800cdc4940f1f9e4ee59ab36667be`, page 7, distinguishes post 16 loss cover from post 17 owner repayment. Post 16 has no shareholder event, consumes fund-issued capital first, and reports nominal reduction, remaining nominal value, and effective date. Post 15 has matching shareholder post 29. The guidance also requires matching company/shareholder event times. The implemented subset accepts owner-confirmed registered events and excludes fund-issued capital, owner repayments, share cancellations, conversions, mergers, and demergers.

The [official examples](https://www.skatteetaten.no/bedrift-og-organisasjon/rapportering-og-bransjer/aksjonarregisteroppgaven/eksempler-pa-utfylling-av-aksjonarregisteroppgaven/) section on internal transfer to reserves by nominal reduction confirms that post 16 does not reduce tax paid-in capital when no money is repaid. **Implementation inference:** applying that same no-payout distinction to loss cover preserves tax paid-in capital and premium while reducing registered share capital and nominal value. The directly cited example is an internal transfer to reserves; it is not a separately accepted loss-cover filing. The renderer does not emit post 17 or 27 repayment data for loss cover.

Element order and identifiers come from the [official main schema](https://github.com/Skatteetaten/api-dokumentasjon/blob/4c905cc81af44606fb1ab49132c46c49717e189b/static/download/aksjonaerregisteroppgaveHovedskjema.xsd) and [shareholder schema](https://github.com/Skatteetaten/api-dokumentasjon/blob/4c905cc81af44606fb1ab49132c46c49717e189b/static/download/aksjonaerregisteroppgaveUnderskjema.xsd). Hashes are recorded in `docs/filing/rf1086-official-sources.json`. Post 16 is group 3464 under 3460, with fields 17717, 23960, 23961, 17720, 17721. Post 15 is group 3463; post 29 is group 4987 under 3997. Loss cover has no event-code field.

## Implemented and verified boundary

Three explicit offline types cover ordinary cash new shares, ordinary cash nominal increases, and nominal loss cover without fund-issued capital. Admission for every RF case, including the predecessor formation/transfer/dividend/no-activity variants, replays the whole case chronology, checking unique holders, registration assertions, timestamps, allocations, event-time holdings, nominal values, registered capital, tax paid-in capital, premium and closing balances. Decimal arithmetic rejects disagreement rather than relying on floating-point tolerances. New-share premium is per share; nominal-increase premium is the total, allocated across holders.

Focused tests validate all three generated document pairs against the current official XSD and verify code/field semantics, unchanged tax paid-in capital for loss cover, absence of payout fields, mixed capital chronology, and malformed or inconsistent case rejection. Hosted source integration for the new events remains pending; the no-activity renderer also blocks unexplained capital or holding changes. Production activation requires its separate evidence and owner controls.

## Review corrections after 81a37a33

The original independent Spec review is preserved in `reviews/spec-81a37a33.md`. Public event values now reject a discriminator that disagrees with their class, preventing readiness/rendering variant mismatch. The supported AS path requires at least NOK 30,000 registered capital and non-empty shareholder holdings; the loss-cover golden case is corrected to NOK 40,000 → NOK 30,000. See [Brønnøysundregistrene capital requirements](https://www.brreg.no/aksjeselskap/aksjekapital/).

A dividend following a loss-covering reduction in the same case now blocks pending verified distribution-restriction clearance. Registration confirmation alone does not prove creditor notice or an applicable exception. [Brønnøysundregistrene guidance](https://www.brreg.no/aksjeselskap/aksjekapital/nedsettelse-av-aksjekapital/) describes the three-year restriction for loss coverage without creditor notice. The current RF input lacks authoritative clearance facts, including restrictions originating in earlier years. This is an explicit unresolved source requirement, not permanent removal of the accepted #172 dividend/loss-cover patterns. No production readiness for those complete patterns is claimed.
