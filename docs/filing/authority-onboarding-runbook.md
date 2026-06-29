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

### Step 1 — Register the operating entity as an ENK (get an organisasjonsnummer)

Talli's operating entity holds the Maskinporten client and acts as the system supplier. It does
**not** have to be an AS — an **enkeltpersonforetak (ENK)** has an organisasjonsnummer and is
sufficient for the Maskinporten / Altinn / virksomhetssertifikat integration. (Talli's
*customers* must still be AS — that is the product's scope; this step is only about Talli itself.)

> Already have an active ENK? **Reuse it** — an existing, still-registered ENK's org number
> satisfies every downstream step, so you skip the NOK 2 181 registration fee. Just bring its
> details up to date via a **free endringsmelding** (Samordnet registermelding → "endre" in
> Altinn): update the næringskode to 62.010 if needed, and confirm no outstanding tax/MVA from
> prior activity. Verify it is still **aktiv** (not slettet/under avvikling) at brreg.no first.

> Liability note: an ENK gives **no liability shield** — the innehaver is personally liable. Since
> Talli submits statutory filings on behalf of customers and processes their financial data
> (see the DPA / ToS in `docs/legal/`), revisit the AS question before onboarding live customers.
> An ENK can be converted to an AS later, but the org number changes, which means re-doing
> Steps 2–4. Plan accordingly.

- [ ] **Innehaver**: a person with a Norwegian fødselsnummer / D-nummer (you). No share capital
      and no founding document required for an ENK.
- [ ] Submit **Samordnet registermelding** (Altinn form **BR-1010 / "Registrer ny verksemd"**) to
      register the ENK in **Enhetsregisteret**. Issues the **organisasjonsnummer** (ENK is usually
      faster than an AS — often days). **Fee (current Brønnøysund table): NOK 2 181 digital /
      2 746 paper** for an ENK in Enhetsregisteret — choose **Digitalt** for the lower fee.
      (For comparison: an AS is 6 825 digital; adding Foretaksregisteret later is 3 185.)
- [ ] **Foretaksregisteret is not required** for Talli. An ENK only needs Foretaksregisteret if
      it resells purchased goods, has >5 employees, operates as statsautorisert regnskapsfører/
      revisor, or takes pant i varelager — none apply to Talli (a software service, not an
      accountant/auditor firm). Verified: Buypass/Commfides issue a virksomhetssertifikat, and
      Maskinporten works, on the **Enhetsregisteret** org number alone. You *may* still opt in
      (it's a right, not a duty) for foretaksnavn protection + a firmaattest, for a one-time fee
      (tilleggsregistrering: NOK 3 185 digital).
- [ ] **Næringskode (NACE)**: pick the closest main activity — **62.010 Programmeringstjenester**
      ("Programvareutvikling") fits a filing-assistant SaaS. It only feeds SSB statistics, has
      **no effect** on the virksomhetssertifikat / Maskinporten / Altinn (those bind to the org
      number), and can be changed later for free. Alternatives if preferred: 63.110
      (databehandling/datalagring) or 58.290 (utgivelse av annen programvare). Don't overthink it.
- [ ] Confirm you hold the **Tilgangsstyrar (Access manager)** role on the new org in Altinn —
      required later to delegate access packages to the system user. Getting this now avoids a
      round-trip at Step 4.

### Step 2 — Client key / certificate

Maskinporten signs the client-assertion JWT with your key. The requirement **differs by
environment**, which matters for cost while doing action item 1 (test-env onboarding only):

- **Test environment (free):** Maskinporten's test/ver2 accepts a **self-generated key pair /
  self-signed certificate** — no CA purchase needed. Do the entire test integration this way and
  defer spend.
  - [ ] Generate a key pair locally, e.g. `openssl genrsa -out talli-test.key 4096` then
        `openssl req -new -x509 -key talli-test.key -out talli-test.pem -days 1095 -subj "/CN=Talli test"`.
  - [ ] Keep the private key secure; you upload only the **public** key/cert at Step 3 (test).
- **Production (paid, defer until cutover):** production Maskinporten requires a CA-issued
  **virksomhetssertifikat** from **Buypass** or **Commfides** for org 930835978 (~NOK 1 500–4 000/yr).
  - [ ] Buy it only when moving an obligation to production. Order the **soft/file-based** cert
        (server use), not a smartkort, and keep the key in production-separated storage.

### Step 3 — Maskinporten client (Samarbeidsportalen)

- [ ] **Test access:** go to **samarbeid.digdir.no**, log in with **ID-porten as the org's
      authorised person** (innehaver for an ENK) to start registration + accept Digdir's
      bruksvilkår. A brand-new org may get *"Din virksomhet er ikke registrert som bruker av
      denne tjenesten enda"* — if so, email **servicedesk@digdir.no** with org number, contact
      person, purpose, and a screenshot to be enrolled as a Maskinporten customer (a few business
      days). Self-registration by email requires the org's **registered email domain**, which is a
      snag for ENKs with only a personal email.
- [ ] **Sign the supplier terms (bruksvilkår):** once Digdir enrols the org, the **authorised
      signer** registers as a user with the org's **@-domain email** at
      **https://minside-samarbeid.digdir.no/**, opens **"Virksomhetens bruksvilkår"** →
      **"Bruksvilkår for leverandører"**, reads and signs. ⚠️ Sign **only** that one — not the other
      terms. This must be done before the Maskinporten client can be created.
- [ ] **Delegate the test self-service right (Altinn, prerequisite):** TT02 access in
      Samarbeidsportalen is Ansattporten-gated. As ENK innehaver, in **Altinn → Tilgangsstyring →
      Brukere → + Ny bruker** (add yourself), grant **"Selvbetjening for testing i
      ID-porten/Maskinporten"** (test-only) or **"Selvbetjening av klienter i ID-porten/Maskinporten"**
      (test + prod). Without this, the test environment does not appear in the portal.
- [ ] Register a Maskinporten **integration (oauth2 client)** with: `integration_type=maskinporten`,
      `token_endpoint_auth_method=private_key_jwt`, `grant_types=jwt-bearer`, a clear `description`,
      and **upload your own public key/JWK** (the self-generated key from Step 2; `kid` must be
      globally unique). One client per scope is recommended (for a test rehearsal one client with all
      scopes is fine). **As a supplier using Altinn delegation, create the integration as belonging to
      yourself — do NOT pick "på vegne av en kunde".** At token time pass the customer's org as the
      `consumer_org` claim; Maskinporten then checks Altinn for a valid delegation.
      Navigation: **samarbeid.digdir.no → Virksomhetens tjenester → Administrasjon av tjenester →
      "Integrasjoner" in the *test* environment → Ny integrasjon → Difi-tjeneste = Maskinporten**.
      Add the public key under **"Egne public nøkler"** at the bottom of the client page (PEM must be
      converted to JWK first — see the `node` one-liner in the team notes).
- [ ] Add the per-obligation scope (table below). Altinn-delegated scopes appear under **"Scopes
      tilgjengelig for alle"**; some scopes still require **API-owner grant** (Skatteetaten /
      Brønnøysund) before they activate. Record the auto-assigned **client_id**.
- [ ] Smoke-test signing against the **test** token endpoint (`https://test.maskinporten.no/token`,
      JWT `aud=https://test.maskinporten.no/`, `iss=client_id`, `exp − iat ≤ 120s`). A delegated
      call on behalf of a company additionally needs the `consumer_org` claim / systembruker from
      Step 4 and a Tenor subject from Step 5, so a full accepted submission comes after those.

### Step 4 — Altinn system user + access packages (systembruker + tilgangspakker)

This step has **two sides**: Talli (the *sluttbrukersystemleverandør* / SBSL) registers its **system**
once; then **each customer company** creates a **systembruker** that points at that system and approves
the access packages. A systembruker is "a template's instance" — the system in the systemregister is the
template, the systembruker is the per-company grant. Source:
https://docs.altinn.studio/nb/authorization/guides/system-vendor/system-user/

Talli's model is **"systembruker for eget system"**, *not* klientsystem: every customer holding-AS files
its **own** årsregnskap/skattemelding through Talli (Talli is **not** a regnskapsfører/revisor). So the
required access packages must be `isAssignable=false` and `isDelegable=true`, and creation can be either
user-initiated or vendor-initiated.

**4a — Supplier side (Talli, once): register the system in the Systemregister.** This is an **API call,
not a portal click** —
`POST https://platform.tt02.altinn.no/authentication/api/v1/systemregister/vendor` (prod:
`platform.altinn.no`), with a **Maskinporten token** that carries the scope
`altinn:authentication/systemregister.write` (this scope must be added to the Step-3 client). JSON payload
fields (see systemregistration guide):
  - `id`: `{orgnr}_{name}`, e.g. `930835978_talli`.
  - `vendor.ID`: `0192:930835978` (Enhetsregisteret ref). **Must match the org number in the token.**
  - `name` / `description`: texts for `nb`, `nn`, `en`.
  - `accessPackages` / `rights`: the packages the system needs (e.g. Regnskapsregisteret innsending for
    årsregnskap). **Must be defined before any systembruker can be created.**
  - `clientId`: list of Maskinporten client UUIDs from Step 3.
  - `isVisible: true` so customers can self-select Talli in the Altinn portal (user-initiated creation).
  - `allowedredirecturls`: optional, for vendor-initiated `confirmUrl` redirects.
  - **PUT overwrites the whole definition** — to edit, GET the current def, modify, PUT the full payload.
  - ⚠️ **TT02 caveat:** to use a real org number in TT02 you may need to have it enabled there —
    email **servicedesk@altinn.no** to get the ENK org registered in TT02 if the call rejects the org.

**4b — Customer side (per company): create the systembruker.** Two ways:
  - **User-initiated (portal):** the company logs into Altinn (**tt02.altinn.no**), selects the org, then
    **Profil → Tilgangsstyring → Systemtilgang / Systembrukere → "Opprett ny systembruker"**, picks
    **Talli** from the list, and approves the pre-defined access packages. (The company must hold the
    authority to delegate every package requested — it's an all-or-nothing "OG-forhold".)
  - **Vendor-initiated (Talli's preferred, from the app):**
    `POST .../authentication/api/v1/systemuser/request/vendor` with `systemId`, the customer's
    `partyOrgNo`, and `accessPackages` → returns a `confirmUrl` deeplink → Talli hands the link to the
    customer → customer approves → request status flips to `Accepted`.
- [ ] For the TT02 rehearsal, register Talli's system (4a), then have the **Tenor test AS** (Step 5)
      create the systembruker (4b, user-initiated is simplest for a first pass).

### Step 5 — Synthetic test subjects (Tenor)

- [ ] Obtain **Tenor** synthetic test organisations/persons for the test environments. Never
      use real customer data in TT02 / Skatteetaten test env.

## Per-obligation scopes and test surfaces

| Obligation (label) | Issue | `obligation` value | Maskinporten scope(s) | Test surface |
|---|---|---|---|---|
| Aksjonærregisteroppgaven (RF-1086) | #81 | `aksjonaerregisteroppgaven` | `skatteetaten:innrapporteringaksjonaerregisteroppgave` | Skatteetaten test env; POST 1086H / 1086U / bekreft, GET dokumenter |
| Årsregnskap (RR-0002) | #84 | `aarsregnskap` | `altinn:instances.read`, `altinn:instances.write` | Regnskapsregisteret machine API via Altinn3 **TT02**; system user fills + locks, **ID-porten** signs (hybrid); `dataFormatId=1266` |
| Skattemelding for AS | #87 | `skattemelding` | submission/validation flow (`skd/formueinntekt-skattemelding-v2`, + `altinn:instances.*`). **NOT** `skatteetaten:skattemeldingupersonlig` — see note. | Skatteetaten external test env; owner-managed **system-supplier submission** of the company's *own* return (company = data subject + submitter, Talli = its system via Altinn delegation). 2025 schema `skattemeldingUpersonlig_v5` / `naeringsspesifikasjon_v6` |

Trace any payload fields to the maps/evidence registers in `docs/filing/` — do not invent fields.

**All three authenticate via Maskinporten** (Skatteetaten APIs and the Altinn systembruker alike) —
the token protocol is identical. What differs is the **authorization / access-grant model** on top:
- **RF-1086** — Maskinporten token; Skatteetaten (API-tilbyder) grants the scope, Altinn-delegated
  per customer (scope appears under "Scopes tilgjengelig for alle").
- **Årsregnskap** — Maskinporten token via an **Altinn systembruker** (customer creates it at
  Profil → Tilgangsstyring → Systemtilgang/Systembrukere, **TT02**, selecting Talli's registered
  system per Step 4) with the **Regnskapsregisteret – innsending av årsregnskap** access package;
  signing needs **ID-porten**.
- **Skattemelding** — Maskinporten token. Use the **submission/validation flow**
  (`skd/formueinntekt-skattemelding-v2`) where the **company files its *own* return** via Talli
  (Altinn delegation). ⚠️ Do **NOT** use the `skatteetaten:skattemeldingupersonlig` near-time data
  API: per Skatteetaten it serves confidential data about *other* taxpayers and requires a
  statutory **hjemmel i lov (not consent)** plus a basis lifting Skatteetaten's taushetsplikt, and
  is "ikke tilrettelagt for systembrukerløsningen og visning i sluttbrukersystem" — Talli cannot
  meet that and does not need it for owner-managed filing. In the Skatteetaten **systemleverandør**
  dialogue, request the submission/validation API and confirm (a) owner-managed AS filing of its
  own return and (b) that displaying the company's own return in Talli's UI is permitted. This is
  the slowest-lead, least-certain gate — reasonable to let RF-1086 + årsregnskap lead.

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
| 1. Operating entity registered (ENK, org nr) | ☐ | ☐ | ☐ |
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
