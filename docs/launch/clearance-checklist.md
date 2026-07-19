# Talli Launch Clearance Checklist

Status: pre-production copy baseline cleared; production and corporate-document human review still required
Last updated: 2026-07-14
Working brand: Talli  
Domain note: `talli.no` is secured

This checklist prevents the app from shipping with unclear brand rights, misleading authority language, or product claims that run ahead of the production filing/security gates. It cannot be completed by code implementation alone.

The dependency order and complete remaining-gap inventory are maintained in
[`customer-ready-decision-map.md`](./customer-ready-decision-map.md).

## Official Search Sources

- Patentstyret search service for trademarks, patents, and design: https://search.patentstyret.no/advanced/
- Patentstyret guidance on company names and distinctive signs: https://www.patentstyret.no/immaterielle-rettigheter/foretaksnavn
- Brønnøysundregistrene register search: https://www.brreg.no/registersok/
- Altinn name-choice guidance and `navnesok.no` note: https://info.altinn.no/starte-og-drive/starte/valg-av-navn/

## Human Clearance Steps

These steps must be completed and signed off before public launch copy uses `Talli` as the final product/company name.

| Step | Required evidence | Human decision |
| --- | --- | --- |
| Trademark search | Patentstyret search for `Talli`, close variants, similar accounting/finance software names, and relevant Nice classes | Approve, reject, or send to trademark counsel |
| Company-name conflict check | Brønnøysund search for `Talli`, close variants, and confusingly similar Norwegian company names | Approve, reject, or choose a different legal/company name |
| Domain ownership | Registrar/account evidence that `talli.no` is controlled by the founder/company | Confirm as domain ownership only, not trademark clearance |
| Launch naming decision | Written decision on product name, legal entity name, domain, and fallback if a conflict appears | Founder/legal sign-off |
| Launch copy review | Review of homepage, onboarding, pricing, authority-flow copy, terms, and support boundary wording | Founder/legal sign-off |

## Required Non-Affiliation Language

Use clear language wherever the product mentions Fiken, Altinn, Skatteetaten, Brønnøysundregistrene, or public filing integrations.

Recommended Norwegian wording:

> Talli er ikke tilknyttet, godkjent av eller drevet av Fiken, Altinn, Skatteetaten eller Brønnøysundregistrene.

Recommended integration wording:

> Innsending skjer gjennom offentlige myndighetsløsninger der Talli har nødvendig tilgang. Offentlige tilbakemeldinger og kvitteringer lagres når de er tilgjengelige.

Do not imply that a public authority, Fiken, or any registry endorses Talli unless there is written evidence that explicitly permits that claim.

## Claims Not Allowed Before Production Gates

Do not use these claims until RF-1086 production validation, submission, receipt, security, and legal launch gates are complete:

- "Direkte innsending" or "send inn direkte" for live authority filing.
- "Ferdig innsendt" unless a real authority receipt has been stored for that filing.
- "Godkjent av Skatteetaten", "godkjent av Altinn", "godkjent av Brønnøysundregistrene", or "godkjent av Fiken".
- "Garantert riktig", "unngå gebyr", "ingen risiko for dagmulkt", or similar guarantee language.
- "Erstatter regnskapsfører" or legal/tax advisory claims.
- "Alt du trenger for alle AS" because Talli is holding-first and excludes many AS cases.

Allowed before production filing is enabled:

- "Holding-first regnskaps- og innsendingsapp under utvikling."
- "Forbereder aksjonærregisteroppgaven, årsregnskap og skattemelding for enkle norske holding-AS."
- "Direkte innsending åpnes først når myndighetstilgang, testmiljø og sikkerhetsgjennomgang er fullført."

## Final Launch Gate

Public launch may proceed only when each item has a named reviewer, date, evidence link, and decision:

- Trademark search reviewed.
- Brønnøysund company-name conflict check reviewed.
- `talli.no` ownership confirmed.
- Non-affiliation language present in public copy and terms.
- Production direct-filing claims removed or backed by completed production gates.
- Backup/restore launch gate passed within the last 30 days. Required evidence: `npm run test:backup-restore`, a recorded restore target, and no missing launch-critical rows.
- Pricing copy reviewed against refund/support-boundary policy.
- Terms, privacy policy, DPA, retention, export, and incident language reviewed.
- Security baseline sign-off completed.
- Corporate-document templates, accounting policy, PDF goldens, deployed RLS
  and private storage, backup/restore, and corporate public copy approved under
  `docs/launch/corporate-document-release-gate.md`.
- `TALLI_CORPORATE_DOCUMENTS_ENABLED=false` remains unchanged until all six
  corporate-document release rows contain a named reviewer, date, immutable
  evidence reference, and approval.

## Latest Local Corporate-Document Evidence

The 2026-07-14 local rehearsal passed deterministic rendering, extracted-text
checks, four-page visual inspection, canonical decision/content hashing,
private-storage orchestration tests, a fresh PostgreSQL 16 lifecycle rehearsal,
typecheck, production build, and dependency audit. Exact commands and hashes
are in `docs/launch/evidence/corporate-document-local-rehearsal.md`.

That local evidence does not approve the feature for production. A fresh local
Supabase deployment-shaped authenticated/RLS/Storage/browser run now passes,
but deployed staging/production isolation and restore evidence remain pending.
Legal, accounting, product/security, and restore reviewers are also still
pending.

If any item is unresolved, launch may still run as a private waitlist or prototype page, but it must not claim live direct filing or final legal clearance.
