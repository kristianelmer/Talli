# Talli Clearance Evidence Register

Status: prepared for founder/legal review  
Last updated: 2026-06-17  
Blocks: #71 remains open until human/legal signoff

This register turns `docs/launch/clearance-checklist.md` into a reviewable
evidence log. It is not trademark clearance.

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
| Trademark search | Patentstyret search for `Talli`, close variants, similar accounting/finance software marks, relevant Nice classes | Not completed in official UI. Supplemental searches on 2026-06-16 and 2026-06-17 show apparently unrelated uses that require review. | Pending | Pending |
| Company-name conflict | Brønnøysund search for `Talli`, variants, confusingly similar accounting/finance company names | Not completed in official UI. Supplemental 2026-06-17 search found unrelated `Bassam Talli` sewing/repair entities. | Pending | Pending |
| Domain ownership | Registrar/account evidence for `talli.no` | Founder stated `talli.no` secured. Need registrar screenshot/account evidence. | Pending | Pending |
| Fallback name | Written fallback if `Talli` conflicts | None selected. | Pending | Pending |
| Public copy | Homepage/app/pricing/legal copy reviewed against non-affiliation and no-production-claim rules | Current app copy says production filing remains gated. Legal policy drafts exist in `docs/legal/`. | Pending | Pending |
| Pricing/refund/support boundary | Pricing and refund wording reviewed against founder pricing gate | `docs/billing/founder-pricing-gate.md` and `docs/legal/terms-of-service-draft.md` exist. | Pending | Pending |
| Authority wording | No implication of endorsement by Fiken, Altinn, Skatteetaten, or Brønnøysundregistrene | Required wording exists in checklist; final public copy review pending. | Pending | Pending |
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

Issue #71 can close only when:

- founder/legal reviewer records trademark/name decision;
- `talli.no` ownership evidence is linked;
- fallback name decision is recorded;
- public copy and legal drafts are approved;
- production direct-filing claims are either removed or backed by completed filing gates.
