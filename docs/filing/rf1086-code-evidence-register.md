# RF-1086 Code Evidence Register

Current mapping review: 17 September 2026, issue #193.

## Current official mapping

The labelled [Skatteetaten SBS examples](https://www.skatteetaten.no/samarbeidspartnere/sluttbrukersystemer/aksjonarregisteroppgaven-sbs/) supersede the earlier inferred codes below. Exact example, detailed-design workbook, schema and share-class code-list hashes are pinned in [rf1086-official-sources.json](rf1086-official-sources.json). `npm run check:rf1086-sources` checks the immutable GitHub sources and current published bytes; changed or unavailable sources fail the release rehearsal. The check never updates pins automatically.

| Event | Fields | Code | Official meaning evidence |
| --- | --- | --- | --- |
| Formation | 17670 / 17745 | `T` | Labelled `stiftelseavselskap_hovedskjema.txt` and `stiftelseavselskap_underskjema.txt` |
| Purchase | 17745 | `K` | Buyer example `kjopogsalg_underskjema_to.txt` |
| Sale | 17753 | `R` | Seller example `kjopogsalg_underskjema_en.txt` |
| Ordinary dividend | 36564 | `Y` | `utbytte_hovedskjema.txt` |
| Cash issue of new shares | 17670 / 17745 | `N` | Detailed design, Valideringer MAKJ_008 explicitly distinguishes Nyemisjon (N) and Stiftelse (T) |
| Cash nominal increase | 28268 / 28267 | `6` | `nyemisjon_hovedskjema.txt` post 15 and detailed design |
| Nominal reduction for loss coverage | Post 16 | No event-code field | Official guidance and detailed design; no owner repayment event |

Field 17665 reports the company's total dividend amount. It does not contain the share-class code. The company amount must reconcile with shareholder amounts.

The current XSDs were changed upstream on 15 September 2026 and enumerate event codes. Former sale `S` and dividend `U` values fail these schemas. The public API transport example's `N` did not prove formation semantics; the prior inference is corrected to `T`. Historical evidence and captured migration oracles remain unchanged; current tests state the exact superseding corrections.

**Limits:** official field meanings and schema validation do not prove service acceptance, complete source readiness, or authority entitlement. The operational production profile remains no-activity only. All broader patterns still require source integration, owner review and current service conformance. The accepted #172 launch scope remains required; this temporary operational boundary does not narrow it. RF acceptance and production activation remain pending.

## Historical register (16 June 2026; superseded)

The following preserves what was known before the current review. Its code meanings and scope descriptions are historical, not current instructions.


Status: live-scope decision register  
Last updated: 2026-06-16  
Target issue: #80

This register separates simulation support from production live filing support.
Talli may render XML for broader RF-1086 cases when the XML validates against
public XSDs, but live filing must not use unverified transaction-code meanings.

## Official Evidence Reviewed

- Skatteetaten RF-1086 API documentation:
  https://skatteetaten.github.io/api-dokumentasjon/api/innrapportering-aksjonaerregisteroppgave
- Skatteetaten RF-1086 examples:
  https://www.skatteetaten.no/bedrift-og-organisasjon/rapportering-og-bransjer/aksjonarregisteroppgaven/eksempler-pa-utfylling-av-aksjonarregisteroppgaven/
- Local copies of official XSDs:
  - `docs/filing/aksjonaerregisteroppgaveHovedskjema.xsd`
  - `docs/filing/aksjonaerregisteroppgaveUnderskjema.xsd`

## Decisions

| Event | Field | Code | Decision | Evidence |
| --- | --- | --- | --- | --- |
| `stiftelse` | `AksjerNyutstedteStiftelseMvType-datadef-17670` / `AksjeErvervType-datadef-17745` | `N` | Verified for live scope | Observed in Skatteetaten public API example. |
| `kjop` | `AksjeErvervType-datadef-17745` | `K` | Excluded from live scope | Public sources identify purchase label/reporting position, but XSD is free text and code value is not proven. |
| `salg` | `AksjerArvMvOmsattType-datadef-17753` | `S` | Excluded from live scope | Public sources identify sale label/reporting position, but XSD is free text and code value is not proven. |
| `utbytte` | `AksjeUtbytteHendelsestype-datadef-36564` | `U` | Excluded from live scope | Public sources identify dividend field/shape, but code value is not proven. |

## Live Filing Rule

RF-1086 production/live submission is limited to stiftelse/no-activity cases until
Skatteetaten code-list evidence or test-environment acceptance proves the
purchase, sale, and dividend code values.

If a case contains excluded events, production preparation returns:

- code: `RF1086_EVENT_UNSUPPORTED`
- user meaning: live filing is not enabled for these RF-1086 event types yet
- allowed fallback: simulation, XML export, archive, or external/accountant filing

## What Can Clear Exclusions Later

- Official Skatteetaten code list naming the exact code values.
- Official updated API docs with code-value examples for K/S/U meanings.
- Skatteetaten test-environment acceptance with submitted payload, accepted
  feedback, receipt/reference id, reviewer, and date recorded.
