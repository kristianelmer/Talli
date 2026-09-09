# Proposed source and order amendment for completing issue #192

> **Approved on 9 September 2026.** Kristian replied "approved" to both linked
> proposals; see the [decision record](https://github.com/kristianelmer/Talli/issues/192#issuecomment-5599100453)
> and current ADR 0013. The proposal text below is retained as reviewed, including
> its historical pending status. The separate approved option B controls the
> interim/final sequence; approval is not gate or completion evidence.

Status: **DRAFT FOR KRISTIAN — not approved or applied**. Prepared 7 September 2026 against repository revision `27a2eecb` and read-only live issue bodies/comments. This proposal does not close #192, modify a manifest, advance a migration, authorize a provider call, or grant any spending/production authority.

## Decision in one paragraph

**Recommend option B:** permit #192 to remain open while its completed, safe billing checkpoint is integrated and the existing source-owning stages proceed, one at a time, in their existing relative order. Resume #192's final source-backed integration immediately after #149 and before #194. Add the exact producer obligations and versioned-year prerequisite below to that handoff. Preserve every original #192 acceptance criterion; neither missing-source defaults nor fixture evidence count as completion. Option A may expose already-existing authoritative facts, but the current product has no authoritative all-three-filings readiness/submission producers from which to complete #192 now.

Approval wording: “I approve option B in this draft: keep #192 open, allow only the gated interim integration described here before #150, keep the source-owning stages in their current relative order, and require full #192 source-backed acceptance after #149 and before #194. Preserve all original acceptance, source ownership, immutable gates, and action-time approvals.”

The separate four-deletion legacy-retirement amendment is outside this approval. Its approval and implementation remain necessary before the interim checkpoint can pass architecture checks.

## Why the current order cannot finish #192

The approved route is `#137 → #192 → #150 → #151 → #146 → #152 → #153 → #193 → #149 → #194`. #192 must finish before authority connections resume. However:

- Checkout requires definitive Company Access eligibility **and trustworthy filing readiness**. `application/annual_checkout_prerequisites.py:1–16` explicitly assigns aggregate readiness to Annual Compliance #149 after #193/#153 and returns `FILING_NOT_READY`. The independent persistence verifier is also unavailable by default. `AnnualCheckoutPrerequisites` carrying a digest is a receiver contract, not an implemented source.
- #149 consumes the three filing capabilities' public readiness/completion contracts. Its live issue is blocked by #193 and #153. #193 requires the migrated production-capable filing paths and is blocked by #153; its RF-1086, tax and annual-accounts sub-slices must finish sequentially.
- `adapters/postgres_annual_refund.py:79–88` defaults to an unavailable fact resolver. `modules/billing/public.py:1426` requires authoritative incident, purchase, first-purchase and production-submission facts. Purchase/first-purchase facts are billing-owned; incident and submission authority are missing. Absence of a source cannot establish “no production filing.”
- Company Access's active manifest is fixed to accounting year 2026 (`modules/company_access/capability_manifest.json:4` and `public.py:578–579`). New-year renewal cannot claim 2027 eligibility by changing a billing date or copying the 2026 promise. The approved product instead requires a boundary version for each accounting year.

This forms a real ordering cycle: completing #192 requires source work that the route forbids starting until #192 completes. It is not resolved by a Boolean readiness adapter, hashes around synthetic facts, a mutable browser readiness row, an operational launch signoff, or a successful local payment fixture.

## Option A — narrow earlier source prerequisites

Proposed permission: before leaving the present #192 lane, permit **only source-owned public projections backed by facts that already have a canonical owner, implementation and persisted evidence**. Schedule each owning change serially under the integration owner, with manifest/ADR review and source-contract/RLS/rollback tests. Return immutable references, source version, company/year, evaluation time and completeness boundaries; never add billing decisions to the producer or duplicate a writer.

Concrete eligible starting material is the existing Company Access accepted assessment/legal/admission projection and billing's original purchase/capture/first-purchase records. Their existence does not establish all filing readiness or incident cause. Any additional producer must be identified by its exact existing canonical source before implementation authority is exercised.

At the audited revision, Annual Compliance, company-tax and annual-accounts canonical backend implementations are absent; the RF capability does not provide the required complete all-obligation production history. No sufficient set of existing authoritative producers has been found. Therefore **option A alone cannot complete #192 in its current lane**. Creating the missing filing/aggregate capabilities or promoting frozen legacy tables to new billing authority would require a broader, separately enumerated order amendment. Do not treat conditional approval of A as permission for that work.

## Option B — retain #192 acceptance and move final integration

Approve this exact revised sequence:

`#137 → #192 interim billing checkpoint (issue stays open) → #150 → #151 → #146 → #152 → #153 → #193 [RF → tax → accounts] → #149 → source-owned admission/year prerequisite → #192 final integration and acceptance → #194 → existing tail`

The Company Access prerequisite is one bounded change to the already-canonical capability, not a new parallel migration: implement immutable accounting-year-selected capability/admission manifests and current-year renewal rechecks under the existing #172 boundary. Preserve accepted 2026 references, fail closed for years without validated support, and do not claim 2027 coverage until that exact year's source/rule evidence passes. If that evidence requires a boundary change, reopen the relevant decision rather than invent coverage. A mechanism-only test does not satisfy the promised working annual renewal.

### Interim checkpoint and permission to start #150

This is an explicit exception to #180's “finish the slice before the next capability” and the current continuous-main completion rule, solely for #192's missing producer dependency. The checkpoint must complete the currently implementable billing work, preserve truthful unavailable acquisition/renewal states, preserve historical recovery/cancellation/refund records and read/export rights, resolve the separate four-deletion amendment, pass independent review and two complete immutable 11/11 gates, merge through protected Release/Preview, and pass exact-main Release/Preview. Then #150's blocker changes from “#192 closed” to that exact checkpoint receipt. #192 remains open with its outstanding acceptance listed. No issue, source or gate may label the checkpoint full annual billing completion.

Only one capability owner may edit business state at a time. While #150 through #149 execute, #192 may receive read-only analysis; its implementation is paused. The next owner gets the existing public billing contracts, not permission to mutate billing policy or bypass it. No frozen-facade expansion or relaxed baseline is authorized.

### Producer obligations before final #192 acceptance

1. **Filing owners (#151/#152/#153 and #193):** implement and expose immutable company/year/obligation readiness, actual submission history, terminal/unknown outcomes, corrections and coverage evidence through their public contracts. Negative “none submitted” evidence must establish completeness across all three sources; an absent row/adapter is unavailable. Preserve the approved genuine-company final production evidence and separate action-time authorizations.
2. **Annual Compliance (#149):** aggregate the three source-owned readiness/completion contracts, including non-billing hard blocks, with versioned identity and a verifier of current evidence. Define readiness before charging independently of paid entitlement so payment is not required to become ready to pay. Preserve source-owned obligation decisions. This adds the missing #192 handoff explicitly; it does not silently expand a behavior-preserving migration.
3. **Incident producers:** each existing owner publishes only facts it can attest: Company Access owns accepted eligibility and authoritative later rechecks; billing's provider boundary owns recorded payment outcomes; filing capabilities own filing failures/outcomes. Require actual evidence for attribution, event time and company/year. Billing alone applies #177's refund classification and monetary policy. Technical incident/worker infrastructure cannot invent commercial liability or membership authority. If a required non-payment incident has no approved canonical producer, identify and schedule that exact owner before final #192; this draft creates no generic omniscient incident service.
4. **Billing/application final integration:** bind those real contracts, implement separately authorized durable automatic processing without fabricated owner claims, and prove admission/renewal, automatic full and partial refunds, cancellation, receipts, replay/retry and actionable owner/operator exit over the actual source-backed runtime. Preserve current owner/MFA and case-bound support rechecks, atomic rollback, exact consent/provider identity and free-validation separation.

#193's genuine filing evidence must use independently authorized company/filing access. Any existing free-validation exemption remains exact and separate from paid entitlement; this amendment creates none. If those action-time conditions are not met, #193 remains blocked. Option B resolves the code-order cycle, not external permission or evidence gates.

## Evidence and scope that remain mandatory

Final #192 still requires actual designated Vipps Merchant Test, every A1–A8 criterion, source-backed negative/concurrency/duplicate/rollback tests, security/privacy/accounting reconciliation, complete browser/mobile customer and operator flows, independent exact-revision review, two distinct linked immutable complete 11/11 gates, protected-main integration and exact-main Release/nonproduction Preview evidence. #197's billing tranche continues to require **full** #192, and #194 cannot begin before full #192. #189, the #193 per-filing proofs, #197/#199 and #198 remain mandatory. `release/production` stays independent and frozen; no live charge, paid action, credential activation, real filing, named-data access, outreach, or launch follows from this approval.

After approval, record the exact decision on #165/#180/#192 and affected blocker/source tickets; amend ADR-0013 and the control-plane handoff; reflect the truthful scope/order in relevant manifests and tests. Keep the immutable compatibility baseline and all historical proof unchanged. This draft applies none of those changes.

## Verified decision sources

- [#192 live acceptance and placement](https://github.com/kristianelmer/Talli/issues/192): post-billing slice; finish before authority connections resume; A1–A8 remain binding.
- [#177 commercial resolution](https://github.com/kristianelmer/Talli/issues/177#issuecomment-5424235266): no charge while filing readiness is blocked; automatic fact-based refund, renewal/cancellation and five-business-day initiation rules.
- [#172 atomic company-year and year-versioned boundary](https://github.com/kristianelmer/Talli/issues/172#issuecomment-5423704900): complete supported year, no sold partial path, accepted promises immutable, additive support after evidence.
- [#180 approved route](https://github.com/kristianelmer/Talli/issues/180#issuecomment-5424361973) and [narrow #189-only overlap amendment](https://github.com/kristianelmer/Talli/issues/180#issuecomment-5478119293): no existing exception for #192's source cycle.
- [#149](https://github.com/kristianelmer/Talli/issues/149) and [#193](https://github.com/kristianelmer/Talli/issues/193): exact owners, prerequisites, serialization and required filing proof.
- [#192 current ownership/acceptance checkpoint](https://github.com/kristianelmer/Talli/issues/192#issuecomment-5563509657): #150 unclaimed, source/MT/worker authority and two complete gates still due; 2026-only sales admission.
- Repository `docs/adr/0011-enforce-capability-owned-contracts-data-and-workflows.md`: immutable public source contracts, no private-table reads or duplicated business policy, declared thin workflows, no operational-control-plane business policy.
- Repository `docs/adr/0013-enforce-the-architecture-and-migrate-serially.md`, accepted amendments dated 26/27/28/30 August: serialized ownership, frozen future facades, no suppression of source/auth/accounting safety failures. The 28 August #188/#199 split is precedent for an **explicit** producer/integration split, not authority to apply one to billing without a new decision.
- Repository `docs/architecture/mass-market-execution-control-plane.md:50`, `:94`, `:267–275`; `architecture/evidence/issues/192/requirements.json:1368`; the source paths above. Local paths refer to the audited checkout at `/Users/kristianelmer/.codex/worktrees/192-cancellation-01a07a7f/Holding accounting`.
