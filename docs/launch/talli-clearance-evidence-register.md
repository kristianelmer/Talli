# Talli Clearance Evidence Register

Status: invite-only beta copy and legal-operator implementation complete locally; production launch remains blocked
Last updated: 2026-07-15
Blocks: hosted evidence, runtime signoffs, and the intentionally missing `founder_production_go_live` approval

This register turns `docs/launch/clearance-checklist.md` into a reviewable
evidence log. It is not trademark clearance.

Machine-checkable signoff gate:

- Implementation: `app/lib/launch-signoff.ts`
- Test: `npm run test:launch-signoff`
- Required key for this issue: `launch_legal_name_public_copy`
- Final production key: `founder_production_go_live` — **not approved**. It requires
  a later explicit founder confirmation after hosted security, authority, beta,
  professional-review/risk-acceptance, and payment evidence passes.
- Closure rule: reviewer, review date, evidence link, and decision must be
  recorded as `approved`. Pending, rejected, incomplete, or stale evidence keeps
  #71 open.

## Search Sources

Official/manual sources to use for final review:

- Patentstyret trademark/design/patent search: https://search.patentstyret.no/advanced/
- Patentstyret company-name/distinctive-sign guidance: https://www.patentstyret.no/immaterielle-rettigheter/foretaksnavn
- Brønnøysund register search: https://www.brreg.no/registersok/
- Altinn name-choice guidance: https://info.altinn.no/starte-og-drive/starte/valg-av-navn/

Supplemental web search notes from 2026-06-16:

- Search surfaced an old Patentstyret bulletin hit for `Flli Talli SpA`, apparently unrelated goods/classes.
- Search surfaced `talli.ai`, a separate product/brand outside `talli.no`.
- Search surfaced Brønnøysund/person-name references containing `Talli`, not clear product/company-name conflicts.

Supplemental web search notes from 2026-06-17:

- Patentstyret-indexed result still surfaces `Flli Talli SpA` in an old 2012
  trademark bulletin, with goods outside accounting/finance software. This is
  not clearance because it is not a live official trademark-search decision.
- Brønnøysund-indexed results surface `BASSAM TALLI SKREDDER OG SYSTUE`
  (`929 054 466`) and a related sub-entity (`929 234 812`), apparently sewing
  repair, not accounting/filing software. This is not company-name clearance.
- Patentstyret's public site describes Patentstyret/NIPO as granting patent,
  trademark and design registrations in Norway. Final clearance should use
  Patentstyret's own search UI and, if doubt remains, counsel.

These supplemental notes are weak evidence. Final decision must use the official
search sources above and, if doubt remains, trademark counsel.

## Decision Register

| Gate | Evidence needed | Current evidence | Decision | Reviewer/date |
| --- | --- | --- | --- | --- |
| Trademark search | Patentstyret search for `Talli`, close variants, similar accounting/finance software marks, relevant Nice classes | Official Patentstyret search completed 2026-06-24 for `Talli` and close variants across Nice classes 9/35/36/42; no confusingly similar accounting/finance mark found. Prior supplemental hit `Flli Talli SpA` confirmed out-of-scope. | Approved — no conflict | Kristian Elmer (founder), 2026-06-24 |
| Company-name conflict | Brønnøysund search for `Talli`, variants, confusingly similar accounting/finance company names | Official Brønnøysund register search completed 2026-06-24; no active confusingly similar accounting/software/finance company found. `Bassam Talli Skredder og Systue` confirmed unrelated (sewing/repair). | Approved — no conflict | Kristian Elmer (founder), 2026-06-24 |
| Domain ownership | Registrar/account evidence for `talli.no` | Founder confirmed `talli.no` is owned/controlled by the founder/company (2026-06-24). Registrar/Norid evidence to be attached to the launch signoff record. | Approved — ownership confirmed | Kristian Elmer (founder), 2026-06-24 |
| Fallback name | Written fallback if `Talli` conflicts | Not required — `Talli` cleared on both official trademark and company-name searches (2026-06-24). | Approved — not required | Kristian Elmer (founder), 2026-06-24 |
| Public copy | Homepage/app/pricing/legal copy reviewed against non-affiliation and no-production-claim rules | Founder HITL approved the invite-only free-beta posture 2026-07-15. The customer-ready branch removes accountant-replacement, human-review, live-payment, and definitive-delivery claims; identifies ELMER WELFIS; and is enforced by `npm run test:launch-copy`. Rendered deployment review remains pending. | Approved design and local implementation; deployed rendering pending | Kristian Elmer (founder), 2026-07-15 |
| Pricing/refund/support boundary | Pricing and refund wording reviewed against founder pricing gate | Founder attested pricing/refund posture 2026-06-24 (`docs/billing/founder-pricing-gate.md`, signoff key `billing_refund`); support-boundary and refund wording finalized in `docs/legal/terms-of-service-draft.md` under #72 (2026-06-27). | Approved — founder attestation + finalized terms | Kristian Elmer (founder), 2026-06-27 |
| Authority wording | No implication of endorsement by Fiken, Altinn, Skatteetaten, or Brønnøysundregistrene | Required non-affiliation wording approved for public use 2026-06-24: "Talli er ikke tilknyttet, godkjent av eller drevet av Fiken, Altinn, Skatteetaten eller Brønnøysundregistrene." No endorsement implied. | Approved — no endorsement implied | Kristian Elmer (founder), 2026-06-24 |
| Security/restore | Backup/restore, security baseline, RLS/storage audit evidence | Local signed-AAL2 migration, fresh PostgreSQL lifecycle, local Supabase advisors/RLS, and persisted browser tests pass 2026-07-15. Hosted MFA enrollment/recovery, staging/production RLS/storage, and production restore signoff remain pending. | Pending (local boundary green; hosted and restore evidence outstanding) | Pending |

## Approved Public Copy Baseline

Allowed before production filing:

- `Invitasjonsbasert gratis beta.`
- `Produksjonsinnsending og live betaling er ikke tilgjengelig i betaen.`
- `Talli hjelper inviterte betabrukere med å forberede og kontrollere utkast for støttede, enkle norske AS.`
- `Direkte innsending åpnes først når myndighetstilgang, testmiljø og sikkerhetsgjennomgang er fullført.`

Required non-affiliation wording:

> Talli er ikke tilknyttet, godkjent av eller drevet av Fiken, Altinn, Skatteetaten eller Brønnøysundregistrene.

## Not Approved Before Gates Pass

- `Direkte innsending` for live filing.
- `Ferdig innsendt` without real authority receipt.
- `Godkjent av` any public authority or Fiken.
- Guarantee language about correctness, penalties, or avoiding fees.
- `Erstatter regnskapsfører`.
- Human/accountant review or professional-quality-assurance claims.
- Live payment or paid-customer availability.
- Claims that Talli covers all AS companies.

## Final production lock

`founder_production_go_live` is intentionally **missing / not approved**. Neither a
merge, deployment, passing local test, authority sandbox receipt, nor another
signoff may substitute for it. An admin operator may record it only after a later
explicit founder confirmation made with the complete hosted evidence set in view.

Until then:

- production authority adapters remain disabled;
- Vipps/live charging remains disabled;
- paid-customer admission remains disabled;
- public copy remains invite-only beta/pre-production copy.

## Launch Signoff Record To Apply

All brand/name/domain/public-copy/authority/pricing clearance evidence above is
recorded as **approved**. To close the in-app gate, an admin operator records the
`launch_legal_name_public_copy` signoff in the app operator section
(`recordLaunchSignoff`) with the values below. These values are validated against
`buildLaunchSignoffRecord` by `npm run test:launch-signoff` (test: "documented
launch_legal_name_public_copy entry is a valid approved record"), so they can be
entered into the operator form verbatim.

| Field | Value |
| --- | --- |
| key | `launch_legal_name_public_copy` |
| status | `approved` |
| reviewer | `Kristian Elmer (founder)` |
| reviewedAt | `2026-06-24T00:00:00Z` |
| evidenceLink | `docs/launch/talli-clearance-evidence-register.md` (or its GitHub blob URL) |
| decision | `Trademark (Patentstyret), company-name (Brønnøysund), talli.no ownership, fallback (not required), public copy, and authority wording all approved 2026-06-24; pre-production public-copy baseline enforced by test:launch-copy.` |
| recordedBy | (filled automatically with the admin operator's user id) |

Recording this one key closes #71's in-app requirement. The overall launch gate
(`buildLaunchSignoffGate`) stays blocked until the other keys (e.g.
`security_restore`, filing-authority keys, and `founder_production_go_live`) are
also approved and fresh.

## Required Human Signoff

Evidence status (2026-06-27): trademark/name, `talli.no` ownership, fallback (not
required), public copy, authority wording, and pricing/refund/support boundary all
**approved** by Kristian Elmer (founder). Legal pack finalized and approved separately
under #72 / `legal_policy_pack` (2026-06-27). Remaining to close #71: record the
`launch_legal_name_public_copy` signoff in the app operator section, and complete the
production restore signoff (automated `npm run test:backup-restore` is green).
This issue-specific signoff does not approve production launch; the separate
`founder_production_go_live` key remains unapproved.

Issue #71 can close only when:

- founder/legal reviewer records trademark/name decision;
- `talli.no` ownership evidence is linked;
- fallback name decision is recorded;
- public copy and legal drafts are approved;
- production direct-filing claims are either removed or backed by completed filing gates.
