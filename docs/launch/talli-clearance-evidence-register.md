# Talli Clearance Evidence Register

Status: brand + public-copy clearance complete (2026-06-24); pending only the in-app `launch_legal_name_public_copy` signoff  
Last updated: 2026-06-24  
Blocks: #71 remains open until the in-app launch signoff (`launch_legal_name_public_copy`) is recorded by an admin operator

This register turns `docs/launch/clearance-checklist.md` into a reviewable
evidence log. It is not trademark clearance.

Machine-checkable signoff gate:

- Implementation: `app/lib/launch-signoff.ts`
- Test: `npm run test:launch-signoff`
- Required key for this issue: `launch_legal_name_public_copy`
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
| Public copy | Homepage/app/pricing/legal copy reviewed against non-affiliation and no-production-claim rules | Pre-production public-copy baseline approved for public use 2026-06-24; production direct-filing claims ("direkte innsending", "ferdig innsendt", "godkjent av") remain blocked until filing gates pass. Enforced by `npm run test:launch-copy`. | Approved — pre-production baseline | Kristian Elmer (founder), 2026-06-24 |
| Pricing/refund/support boundary | Pricing and refund wording reviewed against founder pricing gate | `docs/billing/founder-pricing-gate.md` and `docs/legal/terms-of-service-draft.md` exist. | Pending | Pending |
| Authority wording | No implication of endorsement by Fiken, Altinn, Skatteetaten, or Brønnøysundregistrene | Required non-affiliation wording approved for public use 2026-06-24: "Talli er ikke tilknyttet, godkjent av eller drevet av Fiken, Altinn, Skatteetaten eller Brønnøysundregistrene." No endorsement implied. | Approved — no endorsement implied | Kristian Elmer (founder), 2026-06-24 |
| Security/restore | Backup/restore, security baseline, RLS/storage audit evidence | Security docs and RLS audit exist; production restore signoff still pending. | Pending | Pending |

## Approved Public Copy Baseline

Allowed before production filing:

- `Holding-first regnskaps- og innsendingsapp under utvikling.`
- `Forbereder aksjonærregisteroppgaven, årsregnskap og skattemelding for enkle norske holding-AS.`
- `Direkte innsending åpnes først når myndighetstilgang, testmiljø og sikkerhetsgjennomgang er fullført.`

Required non-affiliation wording:

> Talli er ikke tilknyttet, godkjent av eller drevet av Fiken, Altinn, Skatteetaten eller Brønnøysundregistrene.

## Not Approved Before Gates Pass

- `Direkte innsending` for live filing.
- `Ferdig innsendt` without real authority receipt.
- `Godkjent av` any public authority or Fiken.
- Guarantee language about correctness, penalties, or avoiding fees.
- `Erstatter regnskapsfører`.
- Claims that Talli covers all AS companies.

## Required Human Signoff

Evidence status (2026-06-24): trademark/name, `talli.no` ownership, fallback (not required), public copy, and authority wording all **approved** by Kristian Elmer (founder). Remaining to close #71: record the `launch_legal_name_public_copy` signoff in the app operator section. (Legal drafts are approved separately under #72 / `legal_policy_pack`.)

Issue #71 can close only when:

- founder/legal reviewer records trademark/name decision;
- `talli.no` ownership evidence is linked;
- fallback name decision is recorded;
- public copy and legal drafts are approved;
- production direct-filing claims are either removed or backed by completed filing gates.
