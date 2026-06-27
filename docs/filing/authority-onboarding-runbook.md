# Authority Onboarding Runbook

Status: onboarding not started — production filing blocked for all obligations
Last updated: 2026-06-27
Covers: `aksjonærregisteroppgaven` (RF-1086, #81), `årsregnskap` (RR-0002, #84), `skattemelding for AS` (#87)

This runbook sequences the real-world steps that take Talli from "no authority access" to
"accepted test-environment submission" for each filing obligation, and maps every step to the
gate Talli already enforces in code. It is a working checklist, not permission to enable
production filing: live filing stays disabled until each obligation's gate is satisfied.

The actual account registrations, certificate purchases, and authority delegations are
real-world actions only the founder/org can perform. Talli's role is this runbook plus the
in-app evidence records described in [How this maps to Talli's gates](#how-this-maps-to-tallis-gates).

## Official Anchors

- Maskinporten docs: https://docs.digdir.no/docs/Maskinporten/
- Samarbeidsportalen (client registration): https://samarbeid.digdir.no/
- Altinn system user (systembruker) guide: https://docs.altinn.studio/en/authorization/guides/system-vendor/system-user/
- Altinn access packages (tilgangspakker): https://info.altinn.no/en/help/profile/single-services-and-rights/
- Tenor synthetic test data: https://www.skatteetaten.no/skjema/testdata/
- Brønnøysund start-a-business: https://www.brreg.no/bedrift/
- Per-obligation maps: [rf1086-production-submission-runbook.md](./rf1086-production-submission-runbook.md),
  [annual-accounts-authority-map.md](./annual-accounts-authority-map.md),
  [company-tax-return-authority-map.md](./company-tax-return-authority-map.md)

## The shared spine (do once)

These steps are prerequisites for all three obligations. Do them once; the per-obligation
scopes (next section) attach on top.

### Step 1 — Incorporate the AS (get an organisasjonsnummer)

The entity that holds the Maskinporten client and acts as the system supplier.

- [ ] Draft **stiftelsesdokument + vedtekter**. Aksjeloven requires min. **NOK 30 000** aksjekapital.
- [ ] Open an **aksjekapitalkonto**, deposit capital, obtain **bekreftelse** from bank, auditor,
      or authorised accountant (regnskapsfører).
- [ ] Submit **Samordnet registermelding** (Altinn form BR-1010) to **Foretaksregisteret**.
      Issues the **organisasjonsnummer** (≈1–3 weeks).
- [ ] Confirm you hold the **Tilgangsstyrar (Access manager)** role on the new org in Altinn —
      required later to delegate access packages to the system user. Getting this now avoids a
      round-trip at Step 4.

### Step 2 — Enterprise certificate (virksomhetssertifikat)

- [ ] Buy a **virksomhetssertifikat** from **Buypass** or **Commfides** for the org number.
      Used to sign the Maskinporten JWT client-assertion. Keep the private key in secure,
      production-separated storage (never in dev/local credential paths).

### Step 3 — Maskinporten client (Samarbeidsportalen)

- [ ] Log in to **samarbeid.digdir.no** as a representative of the org.
- [ ] Register a Maskinporten **client**; attach the **public key** from the virksomhetssertifikat.
- [ ] Request the per-obligation scopes (see table below). Some scopes require **API-owner
      approval** (Skatteetaten / Brønnøysund) before they activate.
- [ ] Note the issued **client_id** and token endpoint; verify the client-credentials flow in
      the Maskinporten **test (ver2/sandbox)** environment first.

### Step 4 — Altinn system user + access packages (systembruker + tilgangspakker)

- [ ] Register Talli's **system** in Altinn's system register with the required **access
      packages** (tilgangspakker — the 2025 granular replacement for the old Altinn roles).
- [ ] For each customer company (and for synthetic test subjects), the company's **Access
      manager** delegates the relevant access package(s) to the system user in Altinn.
      Suppliers cannot self-delegate; the company always approves.

### Step 5 — Synthetic test subjects (Tenor)

- [ ] Obtain **Tenor** synthetic test organisations/persons for the test environments. Never
      use real customer data in TT02 / Skatteetaten test env.

## Per-obligation scopes and test surfaces

| Obligation (label) | Issue | `obligation` value | Maskinporten scope(s) | Test surface |
|---|---|---|---|---|
| Aksjonærregisteroppgaven (RF-1086) | #81 | `aksjonaerregisteroppgaven` | `skatteetaten:innrapporteringaksjonaerregisteroppgave` | Skatteetaten test env; POST 1086H / 1086U / bekreft, GET dokumenter |
| Årsregnskap (RR-0002) | #84 | `aarsregnskap` | `altinn:instances.read`, `altinn:instances.write` | Regnskapsregisteret machine API via Altinn3 **TT02**; system user fills + locks, **ID-porten** signs (hybrid); `dataFormatId=1266` |
| Skattemelding for AS | #87 | `skattemelding` | `skatteetaten:formueinntekt/skattemelding`, `altinn:instances.read`, `altinn:instances.write` | Skatteetaten validation + Altinn3 app `skd/formueinntekt-skattemelding-v2`, external test env; 2025 schema `skattemeldingUpersonlig_v5` / `naeringsspesifikasjon_v6` |

Trace any payload fields to the maps/evidence registers in `docs/filing/` — do not invent fields.

> RF-1086 live scope is intentionally narrow: only `stiftelse` / no-activity (event code `N`).
> K/S/U (kjøp/salg/utbytte) stay excluded (`RF1086_EVENT_UNSUPPORTED`) until Skatteetaten
> code-list evidence or test-env acceptance is recorded.

## Run the test submissions (per obligation)

For each obligation, once Steps 1–5 are done and the scope is active:

1. [ ] Authenticate via Maskinporten (test env) using the virksomhetssertifikat.
2. [ ] Submit a synthetic-subject filing through the obligation's test surface (table above).
3. [ ] Confirm the authority returns an **accepted** status, a **receipt reference**, and an
       **archive reference**. Capture all three — they are required evidence.

## How this maps to Talli's gates

`buildFilingReleaseGates` (`app/lib/filing-release-gate.ts`) fail-closes each obligation to
`production_disabled` until **all** of the following exist for that obligation. Record them in
this order:

1. **`authority_permissions`** — owner confirms innsendingsrett for the obligation
   (`productionAuthorityGate`, `app/lib/authority-permission.ts`). `production_enabled` stays
   false until the rest below pass.
2. **`authority_test_runs`** — an **accepted** test run with `receipt_reference` +
   `archive_reference` (`buildAuthorityTestRun` / `authorityTestEvidenceGate`,
   `app/lib/authority-test-evidence.ts`). This is what Step "Run the test submissions" produces.
3. **`launch_signoffs`** — the obligation's signoff key approved (`buildLaunchSignoffRecord`,
   `app/lib/launch-signoff.ts`), recorded via admin-only `recordLaunchSignoff` (`app/actions.ts`):
   - RF-1086 → `rf1086_authority`
   - Årsregnskap → `annual_accounts_authority`
   - Skattemelding → `tax_return_authority`
4. Plus the shared gates already tracked elsewhere: billing, step-up auth, and security/restore.

Only when an obligation's permission, accepted test run, and approved signoff all pass can
`production_enabled` be flipped for that obligation. These records require live Supabase
credentials and the admin/step-up flow, so they are performed in the running app, not from CLI.

## Progress tracker

| Step | RF-1086 (#81) | Årsregnskap (#84) | Skattemelding (#87) |
|---|---|---|---|
| 1. AS incorporated (org nr) | ☐ | ☐ | ☐ |
| 2. Virksomhetssertifikat | ☐ | ☐ | ☐ |
| 3. Maskinporten client + scope | ☐ | ☐ | ☐ |
| 4. Altinn system user + access pkg | ☐ | ☐ | ☐ |
| 5. Tenor test subjects | ☐ | ☐ | ☐ |
| 6. Accepted test submission | ☐ | ☐ | ☐ |
| 7. `authority_permissions` recorded | ☐ | ☐ | ☐ |
| 8. `authority_test_runs` accepted | ☐ | ☐ | ☐ |
| 9. `*_authority` launch signoff | ☐ | ☐ | ☐ |

Steps 1–5 are shared and only need to be done once; the per-obligation columns diverge from
Step 3 (scopes) onward.
