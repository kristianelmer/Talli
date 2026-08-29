# Talli Human Launch Decisions — Norway

Status: recommendations reviewed; founder approved the provider-enquiry,
no-longitudinal-cohort and 2+8 directions on 2026-08-29. Exact provider,
legal/privacy text, participant-data, production, launch and spending approvals
remain gated

Research date: 2026-08-28

Scope: Norwegian AISP choice, first-party marketing measurement, 2+8 validation,
and final unrestricted-launch signoff

External facts use only official regulator, legislation, provider, W3C, and
Norwegian public-authority sources. **Recommendation** identifies Talli's proposed
decision. **Unknown** requires written provider confirmation or named human
approval. Public provider material is not proof for a particular bank, business
account, contract, or production journey.

## Executive recommendation

1. Keep Neonomics as the first-adapter candidate and Enable Banking as an
   independently conforming fallback, but production-approve neither from public
   evidence. Run equal written diligence and live conformance against the exact
   founder-approved bank/account-product list.
2. Launch marketing measurement without a longitudinal acquisition-to-company-
   year/refund cohort. Retain the consented 30-minute first-party session and
   separately governed operational aggregates; keep attributed long-cycle metrics
   null until a new privacy/legal design is approved.
3. Run a purposive 2+8 program: two anchor company-years to calibrate the complete
   evidence method, then eight overlapping varied company-years, targeting ten
   completed packages. This validates Talli's boundary; it is not a statistical
   market-representation claim.
4. Open unrestricted launch only on one immutable candidate with all 12 evidence
   lanes green/current and all 14 human signoffs approved. Founder signs last and
   cannot waive a red lane.

Approval artifacts:

- [non-binding bank-provider RFI](bank-provider-rfi-2026-08-29.md);
- [marketing-measurement decision and exact notice candidate](../legal/marketing-measurement-decision-draft.md); and
- [representative 2+8 validation design](../launch/representative-validation-2-plus-8-plan.md).

## 1. Neonomics versus Enable Banking

| Factor | Neonomics — sourced fact | Enable Banking — sourced fact | Recommendation / unknown |
| --- | --- | --- | --- |
| Regulated role | [Finanstilsynet](https://www.finanstilsynet.no/en/finanstilsynets-registry/details/?id=199328) lists Neonomics AS (`919041021`) as a Norwegian payment institution with account-information service | Provider identifies Enable Banking Oy (`2988499-7`) as a FIN-FSA-registered AISP; preserve the current Norway-passport extract from the [EBA register](https://euclid.eba.europa.eu/register/pir/disclaimer) | Legal must confirm the provider is the customer-facing AISP for Talli's exact model and that Talli is not an unlicensed AISP/agent |
| Customer model | An unlicensed customer may use Neonomics' licence; Neonomics approves the AIS journey and publishes an independent-controller model ([FAQ](https://www.neonomics.io/customers-frequently-asked-questions)) | The regulated flow uses Enable's registration; own-licence TPP mode is separate ([API terms](https://tilisy.enablebanking.com/terms), [widgets](https://enablebanking.com/docs/api/widgets)) | Contract must allocate AISP, controller/processor/joint-controller, consent, support, complaints and incidents end to end |
| Norway business coverage | API has `business-accounts`; public [coverage](https://www.neonomics.io/market-coverage) lists 124 Norwegian institutions but labels the catalogue consumer-bank coverage | On 2026-08-28 the provider's [live endpoint](https://auth.enablebanking.com/api/aspsps?sandbox=false&country=NO&psu_type=business&service=AIS) returned 123 Norwegian business-AIS entries: 111 non-beta and 12 beta | Neither count proves usable launch coverage. Require a signed bank/product/capability matrix and live evidence; exclude beta unless approved |
| API fit | Accounts, balances, transactions, SCA/consent and cursors; documented four-call daily constraint and bank-dependent history ([API](https://docs.neonomics.io/reference/gettransactionsbyaccountid)) | ASPSP metadata, accounts, balances, transactions, continuation, session deletion and bank-consent closure where possible ([API](https://enablebanking.com/docs/api/reference/)) | Both must pass the same pagination, pending/reversed, duplicate/gap, refresh, revoke, reconnect, degraded-bank and file-fallback suite |
| Onboarding / price | Sandbox, then CDD, commercial agreement, production keys and journey approval; public price absent | Sandbox/restricted own-account evaluation, then contract and KYB; volume price has an undisclosed monthly minimum ([FAQ](https://enablebanking.com/docs/faq/)) | Comparable signed quote and explicit cost approval are required before activation |
| Public assurance | [August 2026 merchant terms](https://cdn.prod.website-files.com/629617bde59a77881cb85420/6a79bcf20570e3adef9bdf87_Merchant%20T%26Cs%20-%20August%202026.pdf) are as-is/as-available and publish no binding SLA | Publishes ISO 27001:2022/continuity claims, but material details describe own-licence single-tenant TPP infrastructure, not clearly the shared AISP service ([risk docs](https://enablebanking.com/docs/tpp/operational-risk-management)) | Obtain current assurance scope and binding SLA/support/incident/RTO/RPO/audit terms; do not rank reliability from asymmetric disclosures |
| Privacy / exit | Public policy describes end-user data and purpose-dependent retention, not Talli's deletion/exit rights ([privacy](https://webassets.neonomics.io/assets/Neonomics_Privacy_Policy_NO-English.pdf)) | Regulated-flow notice publishes 60-second account-data conversion, 15-minute credential, up-to-180-day session and 30-day IP/User-Agent retention ([privacy](https://tilisy.enablebanking.com/privacy)); commercial exit terms absent | Require complete data roles, subprocessors/transfers, revoke/export, portability, backup expiry, deletion certificate and transition help |

### Current incident caution

**Fact:** Neonomics' official status page says a high-failure-rate incident opened
19 August 2026 and TietoEvry banks remained disabled at its 24 August update;
many Norwegian entries in the coverage list are labelled TietoEvry. Source:
[Neonomics incident](https://status.neonomics.io/incidents/5yh0dy0rnj75).

**Recommendation:** treat this as dated concentration/fallback evidence, not proof
that Enable Banking is more reliable. Comparable historical availability, bank-
dependency exclusions, impact and recovery data were not available on an equal
basis. Require the same dated reliability dataset from both providers.

### Existing internal cost ceilings

These are owner-approved Talli decisions from GitHub issue
[#174](https://github.com/kristianelmer/Talli/issues/174), not provider facts:

- all-in bank-data cost no more than **NOK 300 per connected company/year** at
  expected nightly plus owner-triggered usage;
- fixed recurring cost no more than **NOK 2,000/month before 100 paying
  companies**;
- one-time setup/onboarding no more than **NOK 10,000**;
- no long lock-in, punitive validation exit, or unbounded call/overage exposure;
- assess VAT separately.

### Exact provider evidence and quote checklist

Obtain one dated written response and proposed contract pack from each provider:

1. Legal entity, licence/registration, current Norway passport, service used,
   exact AISP/TSP and GDPR role at every step, end-user terms and support/complaint
   ownership.
2. Machine-readable exact launch-bank matrix: business products, beta status,
   account/holder/balance/booked/pending data, immediate/recurring history,
   refresh limits, SCA renewal/revocation, incidents, success/latency and test date.
3. Complete quote: setup, sandbox, minimum, account/call/user usage and overage,
   support, currency, VAT, indexation, minimum term, renewal and termination fees;
   model it at launch, 25 and 100 companies against every ceiling above.
4. Binding SLA: availability formula/target, bank exclusions, maintenance, P1
   response/restore, credits, status feed, 24/7 escalation, incident/update/RCA
   deadlines, RTO/RPO and regulatory/privacy cooperation.
5. Current security pack: certification/scope, penetration and continuity summaries,
   tenant isolation, encryption/keys, access review, vulnerability remediation,
   hosting/backup regions, subprocessors and relevant supervisory remediation.
6. Complete data schedule: payload/log/identifier/consent data, purpose, role,
   storage, retention, backups, transfers, data-subject help and breach handling.
7. API lifecycle: rate limits, idempotency, pagination, polling/webhooks, degraded-
   bank status, deprecation/version overlap, replay, gap detection and reconnect.
8. Exit/contract: notice and rights, read/export window, consent closure/migration,
   secret removal, deletion/backup certificate, transition help, insolvency/change-
   of-control treatment, liability, audit/regulator access and subcontractor change.

[DORA Article 30](https://eur-lex.europa.eu/eli/reg/2022/2554/oj/eng) is a useful
regulated procurement benchmark for written allocation, service levels, processing
locations, security, data recovery/return, incident assistance and termination.
**Unknown:** legal must determine which DORA duties bind Talli directly. If either
provider acts as Talli's processor, [GDPR Article 28](https://eur-lex.europa.eu/eli/reg/2016/679/oj)
and [Datatilsynet's DPA guidance](https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/hvordan-lage-en-databehandleravtale/)
apply to that relationship.

**Fail closed:** do not approve `bank_aisp` until licence/role, coverage, quote,
contract, privacy, security, exit, cost and live evidence refer to the same current
provider/configuration. If provider state is stale or ambiguous, sync stays off;
read/export and CSV/CAMT.053 fallback remain available.

## 2. First-party marketing measurement

### Sourced facts

- Ekomloven § 3-15 requires prior GDPR-valid consent before storing or accessing
  terminal information unless a narrow transmission/strictly-necessary exception
  applies; first-party/session storage is not exempt. Sources: [Lovdata](https://lovdata.no/lov/2024-12-13-76/%C2%A73-15),
  [Nkom](https://nkom.no/internett/informasjonskapsler-cookies), and
  [Datatilsynet](https://www.datatilsynet.no/personvern-pa-ulike-omrader/internett-og-apper/bruk-av-informasjonskapsler-og-andre-sporingsteknologier/).
- Consent must be voluntary, specific, informed, affirmative, demonstrable and as
  easy to refuse/withdraw as to give. Sources: [GDPR Article 7](https://eur-lex.europa.eu/eli/reg/2016/679/art_7/oj/eng),
  [Datatilsynet](https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/om-behandlingsgrunnlag/samtykke/), and
  [EDPB Guidelines 05/2020](https://www.edpb.europa.eu/our-work-tools/our-documents/guidelines/guidelines-052020-consent-under-regulation-2016679_en).
- The notice must disclose controller, purpose/basis, data, recipients/transfers,
  retention, rights/withdrawal/complaint, optionality and relevant automated
  processing ([GDPR Article 13](https://eur-lex.europa.eu/eli/reg/2016/679/art_13/oj/eng)).
  A random/hashed ID is not automatically anonymous under GDPR Article 4 and
  Recital 26 ([official text](https://eur-lex.europa.eu/eli/reg/2016/679/oj)).

### Recommendation / human decision

Approve **no longitudinal marketing cohort for launch**. Keep the implemented
consented 30-minute first-party session and bounded event/reason/source vocabulary.
Keep company-year, purchase, refund and support facts in separately governed
operational capabilities; report coarse operational totals separately; leave
source-attributed company-year/refund rates and purchase-to-completion median null.

A durable acquisition-to-company-year join remains processing even if hashed or
only aggregates are shown. If later required, approve it as a new purpose/design
with basis, notice/consent, minimization, small-cell policy, retention, withdrawal/
deletion, processor/log review and legal/privacy evidence.

Founder/legal/privacy must approve the exact checklist in
[marketing-measurement-decision-draft.md](../legal/marketing-measurement-decision-draft.md):
field/log/recipient inventory; Recital 26 classification; purpose/basis; § 3-15
analysis; exact first/full-layer copy; equal ungated choice; consent proof tied to
notice digest; withdrawal/deletion; retention/purge; processors/regions/transfers;
URL/query/log leakage; cohort choice; approver/date/scope/expiry. Until then, do
not call the session anonymous or publish a notice that says no marketing
measurement occurs.

## 3. Practical 2+8 validation program

This is purposive acceptance validation, not a population estimate. GitHub
[#197](https://github.com/kristianelmer/Talli/issues/197) and the
[control plane](../architecture/mass-market-execution-control-plane.md) remain the
binding internal acceptance sources.

### Two anchor company-years

Start two overlapping, eligible cases early: one closed historical reconstruction
with strong incumbent/filing evidence, and one current-year case with live read-only
banking plus file fallback. Use them to calibrate evidence capture, difference
classification, participant independence, support timing, withdrawal/delete/export,
incident handling and the complete ledger-to-filings-to-archive trace. They do not
lower later coverage requirements.

### Eight varied company-years

Add eight independently operated cases, targeting ten completed packages total.
Across anchors, varied cases and golden evidence, cover every accepted common
pattern twice: no-activity/new/opening/January and at least three mid-year
reconstructions; one/multiple Norwegian shareholders; supported private/listed
investments; purchase/sale/dividend/gain/loss; ordinary capital/loss coverage;
bank/owner/intercompany debt and group contribution; interest/tax/admin costs;
varied banks, sync and fallback. Run six sanitized rejects for audit/consolidation,
operating activity, foreign/unclear tax, company-to-person loan, complex finance/
reorganization, and incomplete reconstruction; rejects do not count as completed.

Before named intake require definitive eligibility, authorized pinned terms/DPA,
purpose/confidentiality, withdrawal/export/delete/retention/incident/exit terms,
current tenant isolation/private storage/MFA/redacted logs/backup/restore, and named
contacts. Participants make every accounting decision and operate Talli themselves.

Compare bank/source evidence, incumbent ledger/SAF-T, corporate documents and filed
outputs. Disposition every difference as Talli defect, source defect, presentation-
only or unresolved judgment. Pass requires every critical journey completed, at
least 90% of core tasks without intervention, median support below 30 minutes per
company-year, no Talli accounting judgment, repeated confusion fixed/rerun, zero
unexplained material differences/incidents/duplicates, and one genuine final
outcome for each of RF-1086, company tax and annual accounts.

Eight completed years may be sufficient only at full evidence saturation; extend
to 12 for single-covered patterns, unstable discrepancies or unsettled support.
Use W3C's official [WCAG-EM](https://www.w3.org/WAI/test-evaluate/conformance/wcag-em/)
to scope, sample complete processes, evaluate and report accessibility, combining
automated/manual checks and disabled-user participation where practicable. Talli's
acceptance remains WCAG 2.2 AA even though Norwegian private-sector regulation
currently references a narrower minimum ([Uu-tilsynet](https://www.uutilsynet.no/regelverk/kva-seier-forskrifta/153)).

## 4. Final launch signoff order

Freeze one candidate and record exact release/deployment/backend/database versions,
capability/schema/provider configurations, evidence digests, reviewers, dates,
conditions and expiry. All 12 lanes must be green on it: boundary, architecture,
accounting/archive, filings, authority, banking, billing, security/privacy/legal,
reliability, frontend, representative validation and public marketing.

Record these approvals; dependencies may run in parallel, but founder is last:

1. `architecture_migration_release`
2. `seller_terms_pricing`
3. `privacy_dpa_subprocessors`
4. `accounting_system_saf_t_archive`
5. `supported_boundary_validation`
6. `rf1086_authority`
7. `company_tax_authority`
8. `annual_accounts_authority`
9. `security_restore_incident_capacity`
10. `accessibility_ux_support`
11. `bank_aisp`
12. `billing_refund`
13. `claims_marketing`
14. `founder_unrestricted_go_live`

Final sequence: first 13 current → deploy with paid admission, charging, bank sync
and filings off → verify deployed hashes → rehearse independent kill/rollback/
unknown-effect reconciliation while preserving read/export → founder signs → enable
only evidenced and separately authorized capabilities. A later stale/red lane blocks
new paid admission and its affected operation until a new immutable clearance passes.

Current implementation note: `apps/web/app/lib/launch-signoff.ts` contains a
narrower nine-key filing-era gate. It is not evidence that this final 14-signoff
#198 gate exists or passes.
