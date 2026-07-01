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
- [ ] Add the per-obligation scope (table below). **None of the filing scopes are self-serve** — when
      you add them the portal warns *"Det er lagt til scopes på klienten som virksomheten din ikke har
      tilgang til … Kontakt API-tilbyder for å be om tilgang."* You can still **save the client** (the
      scopes attach as pending) — do so to obtain the **client_id**, which you need for the access
      requests. Then request access per scope:
      - **RF-1086** (`skatteetaten:innrapporteringaksjonaerregisteroppgave` +
        `…aksjonaerregisteroppgavefilopplasting`, the file-upload variant) → **Skatteetaten** grants the
        scope to your org / client; for a real submission a customer also delegates via Altinn.
      - **`altinn:authentication/systemregister.write`** (needed for Step 4a) → it **is** selectable in
        the TT02 self-service scope picker (search `systemregister`), but it still attaches as
        **"Tilgang mangler"** like the filing scopes — it cannot be self-granted. Email
        **servicedesk@altinn.no** with client_id, org number, "TT02", and that you need the scope as a
        *systemleverandør* to register systems.
- [ ] Smoke-test signing against the **test** token endpoint (`https://test.maskinporten.no/token`,
      JWT `aud=https://test.maskinporten.no/`, `iss=client_id`, `exp − iat ≤ 120s`). A delegated
      call on behalf of a company additionally needs the `consumer_org` claim / systembruker from
      Step 4 and a Tenor subject from Step 5, so a full accepted submission comes after those.

#### Live state — TT02 Maskinporten test client (2026-06-30)

Created via **sjolvbetjening.test.samarbeid.digdir.no** (the TT02 self-service unlocked once Altinn
right *"Tilgang til testmiljøet for ID-porten/Maskinporten Selvbetjening"* was delegated to self).

- **Operating org:** ELMER WELFIS, org nr **930835978** (ENK).
- **client_id:** `7166e743-978e-4a60-8a2d-0a5c00fe6ad0` (Maskinporten, app type `web`,
  `private_key_jwt`, grant `urn:ietf:params:oauth:grant-type:jwt-bearer`, access-token lifetime 120 s).
- **Public key kid:** `2d275f93-10a2-4839-993e-b14da2b84ad8` (RS256/RSA, expires 30.06.2027), derived
  from `~/talli-test.pem` and uploaded under "Egne public nøkler". JWK saved at `~/talli-test.jwk.json`.
- **Scopes on the client:**
  `skatteetaten:innrapporteringaksjonaerregisteroppgave` (⏳ awaiting SKD grant),
  `skatteetaten:innrapporteringaksjonaerregisteroppgavefilopplasting` (⏳ awaiting SKD grant),
  `altinn:authentication/systemregister.write` (✅ **ACTIVE** 2026-07-01 — token request returns
  HTTP 200; used to register the system, see Step 4a live result).
  - ⏭️ **Not yet attached:** `skatteetaten:formueinntekt/skattemelding` (#87). SKD grants don't
    auto-activate on the client — once granted, **add this scope to the client** in the Digdir
    self-service portal (and `altinn:instances.read` / `altinn:instances.write` for the Altinn3 app).
  - ✅ **Active for vendor-initiated Step 4b (2026-07-01):**
    `altinn:authentication/systemuser.request.write` + `altinn:authentication/systemuser.request.read`.
    Altinn granted these to org 930835978, and after **adding both to the client** in the Digdir
    self-service portal, token requests return **HTTP 200**. (Before adding to the client they returned
    MP-200 "invalid scopes for client" even though the org had the grant.)
- **Signing smoke-test PASSED:** `POST https://test.maskinporten.no/token` with a `private_key_jwt`
  assertion (`aud=https://test.maskinporten.no/`, `iss=client_id`, `exp−iat=30 s`) returned
  **HTTP 400 `invalid_scope` (MP-250)** — i.e. Maskinporten authenticated the client/key/kid
  successfully and only the scope grant is missing. This proves key + kid + client_id + JWT signing
  work end-to-end. **Confirmed 2026-07-01:** with `systemregister.write` granted, the same flow
  returns **HTTP 200** and a valid access token (`consumer.ID` `0192:930835978`).
- **Next external requests:** (1) order RF-1086 scope access at the Skatteetaten SBS page
  (`…/aksjonarregisteroppgaven-sbs/#bestill-tilgang-til-tjenesten-krever-innlogging`, requires login);
  (2) email `servicedesk@altinn.no` for `systemregister.write`. Note: RF-1086 also "krever systemtilgang
  med systembruker", so Step 4 (systembruker on a Tenor test AS) is on #81's path too, not only #84/#87.

#### Access-request log

| Date | Obligation | Authority | Channel | Request | Status |
|---|---|---|---|---|---|
| 2026-06-30 | #81 RF-1086 | Skatteetaten | email `altinnreetablering@skatteetaten.no` (overgangsfase; eksternjira brukerstøtte requires a brukerkonto we don't yet have) | Test access to scopes `skatteetaten:innrapporteringaksjonaerregisteroppgave` + `…filopplasting` for org 930835978 / client_id `7166e743-978e-4a60-8a2d-0a5c00fe6ad0` | ⏳ sent, awaiting grant |
| 2026-06-30 | #87 skattemelding | Skatteetaten | same thread (`altinnreetablering@skatteetaten.no`) | scope `skatteetaten:formueinntekt/skattemelding` (test) — verified 2026-06-30 from Skatteetaten api-dokumentasjon; Altinn3 app `skd/formueinntekt-skattemelding-v2`, systembruker resource `app_skd_formueinntekt-skattemelding-v2` | ⏳ sent, awaiting grant |
| 2026-06-30 | #84/#87 systembruker | Altinn | email `servicedesk@altinn.no` | (1) grant `altinn:authentication/systemregister.write` (TT02) + (2) enable real org 930835978 in TT02 systemregister, for client_id above | ✅ **granted 2026-07-01** — `systemregister.write` active (token 200); org 930835978 accepted (Step 4a POST succeeded, no separate enablement needed) |
| 2026-06-30 | #81/#84/#87 systembruker (vendor-initiated) | Altinn | email `servicedesk@altinn.no` (same thread) | also grant `altinn:authentication/systemuser.request.write` + `…/systemuser.request.read` (TT02) for client_id above — required for vendor-initiated Step 4b `/systemuser/request/vendor`; **not** included in request above | ✅ **active 2026-07-01** — granted to org, added to the client in the Digdir portal, token requests return HTTP 200 |

Note: the Skatteetaten SBS "Bestill tilgang" link routes to the eksternjira brukerstøtte
(`eksternjira.sits.no`), which needs a per-virksomhet brukerkonto. Until that account exists, the
overgangsfase email `altinnreetablering@skatteetaten.no` is the sanctioned channel for the reetablerte
tjenester (RF-1086 is one).

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

**4a — concrete payload (RF-1086 rehearsal, owner-managed single right).** Drafted 2026-06-30 for the
TT02 client. Uses the single right `ske-innrapportering-aksjonaerregisteroppgave` (one fullmaktsområde —
cleanest for the first end-to-end test; mixing services across fullmaktsområder can break the customer's
all-or-nothing delegation, esp. for klientsystemer):

```json
{
  "id": "930835978_talli",
  "vendor": { "authority": "iso6523-actorid-upis", "ID": "0192:930835978" },
  "name": { "nb": "Talli", "nn": "Talli", "en": "Talli" },
  "description": {
    "nb": "Talli leverer aksjonærregisteroppgaven (RF-1086) for enkle holdingselskap (AS) på vegne av selskapet selv.",
    "nn": "Talli leverer aksjonærregisteroppgåva (RF-1086) for enkle holdingselskap (AS) på vegne av selskapet sjølv.",
    "en": "Talli files the shareholder register statement (RF-1086) for simple holding companies (AS) on behalf of the company itself."
  },
  "rights": [
    { "resource": [ { "id": "urn:altinn:resource", "value": "ske-innrapportering-aksjonaerregisteroppgave" } ] }
  ],
  "accessPackages": [],
  "clientId": [ "7166e743-978e-4a60-8a2d-0a5c00fe6ad0" ],
  "allowedredirecturls": [],
  "isVisible": true
}
```

Send it once `altinn:authentication/systemregister.write` is granted and the org is enabled in TT02:
1. Get a Maskinporten **test** token with scope `altinn:authentication/systemregister.write`
   (same `private_key_jwt` flow proven in Step 3's smoke-test; `aud=https://test.maskinporten.no/`).
2. `POST https://platform.tt02.altinn.no/authentication/api/v1/systemregister/vendor`
   with `Authorization: Bearer <token>`, `Content-Type: application/json`, body = the payload above.
   (PUT the **full** payload to edit later — PUT overwrites the whole definition.)

> ✅ **DONE 2026-07-01 (live TT02).** Acquired a `systemregister.write` token (HTTP 200) and POSTed
> the payload above → **HTTP 200**, system `930835978_talli` created (no separate TT02 org-enablement
> was needed — the real org was accepted). Verified with
> `GET .../systemregister/vendor/930835978_talli` → returns the full def (`rights` =
> `ske-innrapportering-aksjonaerregisteroppgave`, `clientId` = `7166e743-…`, `isVisible: true`,
> `isDeleted: false`). Token minted locally via `/tmp/talli-mp-token.py` (signs a `private_key_jwt`
> with `~/talli-test.key` + kid `2d275f93-…`). To edit later, GET → modify → **PUT** the full payload.

**Extending to #87 / #84 later (PUT full payload):** add the skattemelding submission resource
`app_skd_formueinntekt-skattemelding-v2` and the Regnskapsregisteret årsregnskap right/package as
additional `rights` / `accessPackages`. Because a customer must be able to delegate **every** requested
right (OG-forhold), prefer **per-obligation system definitions or a minimal set per test** over one
system that bundles all three across fullmaktsområder.


**4b — Customer side (per company): create the systembruker.** Two ways:
  - **User-initiated (portal):** the company logs into Altinn (**tt02.altinn.no**), selects the org, then
    **Profil → Tilgangsstyring → Systemtilgang / Systembrukere → "Opprett ny systembruker"**, picks
    **Talli** from the list, and approves the pre-defined access packages. (The company must hold the
    authority to delegate every package requested — it's an all-or-nothing "OG-forhold".)
  - **Vendor-initiated (Talli's preferred, from the app):** standard `/vendor` endpoint (use this — *not*
    `/vendor/agent`, which is only for klientsystem / regnskapsfører-for-many-clients). Flow:

    1. **Request token** for Talli-as-itself (no `authorization_details`), scope
       `altinn:authentication/systemuser.request.write`.
    2. **Create the request:**
       ```http
       POST https://platform.tt02.altinn.no/authentication/api/v1/systemuser/request/vendor
       Authorization: Bearer <token w/ systemuser.request.write>
       Content-Type: application/json
       ```
       ```json
       {
         "externalRef": "talli_rf1086_<customerOrgNo>",
         "systemId": "930835978_talli",
         "partyOrgNo": "<customer holding-AS orgNo, 9 digits>",
         "integrationTitle": "Talli aksjonærregisteroppgave",
         "rights": [
           { "Resource": [ { "id": "urn:altinn:resource", "value": "ske-innrapportering-aksjonaerregisteroppgave" } ] }
         ],
         "redirectUrl": "<a pre-registered allowedredirecturl, optional>"
       }
       ```
       Use `rights` (not `accessPackages`) because the 4a system def uses the single right resource.
       Response is `status: "New"` + a **`confirmUrl`** (TT02 domain
       `https://am.ui.tt02.altinn.no/accessmanagement/ui/systemuser/request?id=<requestId>`).
    3. **Customer approves:** hand the `confirmUrl` to the company; an access-manager for the org opens it,
       sees the requested right, and approves → status flips `New → Accepted` and the systembruker is
       created automatically. (Other terminal states: `Rejected`, `TimedOut` after 10 days.)
    4. **Poll status** by request id
       `GET .../systemuser/request/vendor/{requestId}` or idempotently by ref
       `GET .../systemuser/request/vendor/byexternalref/{systemId}/{orgNo}/{externalRef}`
       (scope `altinn:authentication/systemuser.request.read`).
    5. **Retrieve the created systembruker UUID** (needed only if you pin tokens by `externalRef`):
       `GET .../systemuser/vendor/byquery?system-id=930835978_talli&orgno=<customerOrgNo>` →
       `{ "id": "<systemuser UUID>", "userType": "standard", … }`.
- [ ] For the TT02 rehearsal, register Talli's system (4a), then create the systembruker for the
      **Tenor test AS** (Step 5) — vendor-initiated `/vendor` request is closest to Talli's real owner
      flow (the owner approves a `confirmUrl`); user-initiated portal is a simpler fallback for a first pass.

> Sources: Altinn systemuserrequest guide + API reference
> (`docs.altinn.studio/nb/authorization/guides/system-vendor/system-user/systemuserrequest/`,
> `.../api/authentication/systemuserapi/systemuserrequest/external/`, `.../byquery/`);
> Skatteetaten `api-dokumentasjon/docs/om/systembruker.md`.

### Step 5 — Synthetic test subjects (Tenor)

- [ ] Obtain **Tenor** synthetic test organisations/persons for the test environments. Never
      use real customer data in TT02 / Skatteetaten test env.

## Per-obligation scopes and test surfaces

| Obligation (label) | Issue | `obligation` value | Maskinporten scope(s) | Test surface |
|---|---|---|---|---|
| Aksjonærregisteroppgaven (RF-1086) | #81 | `aksjonaerregisteroppgaven` | `skatteetaten:innrapporteringaksjonaerregisteroppgave` | Skatteetaten test env; POST 1086H / 1086U / bekreft, GET dokumenter |
| Årsregnskap (RR-0002) | #84 | `aarsregnskap` | `altinn:instances.read`, `altinn:instances.write` | Regnskapsregisteret machine API via Altinn3 **TT02**; system user fills + locks, **ID-porten** signs (hybrid); `dataFormatId=1266` |
| Skattemelding for AS | #87 | `skattemelding` | `skatteetaten:formueinntekt/skattemelding` (+ `altinn:instances.read`, `altinn:instances.write` for the Altinn3 app `skd/formueinntekt-skattemelding-v2`). **NOT** `skatteetaten:skattemeldingupersonlig` — see note. | Skatteetaten external test env (`api-test.sits.no`) + Altinn3 `skd.apps.tt02.altinn.no`; systembruker resource `app_skd_formueinntekt-skattemelding-v2`; owner-managed **system-supplier submission** of the company's *own* return (company = data subject + submitter, Talli = its system via Altinn delegation); final BankID sign done by a person in Altinn UI. 2025 schema `skattemeldingUpersonlig_v5` / `naeringsspesifikasjon_v6` |

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

### RF-1086 (#81) — concrete TT02 call sequence

This is the rehearsal Talli already models in `holding_core.rf1086_submission`
(`prepare_rf1086_api_calls`) and documents in `rf1086-production-submission-runbook.md`. The
test-environment differences are: the `api-test.sits.no` base URL, the synthetic Tenor subject,
and the test Maskinporten token. **Live test scope = stiftelse / no-activity only** (the
production gate excludes K/S/U share events; keep the rehearsal to an allowed shape).

**Generate + validate the XML locally first (Talli CLI, no network):**

```bash
# 1. Build the RF-1086 hovedskjema + underskjema XML files from a deterministic case
uv run python -m holding_cli.main simulate-aksjonaerregister --case case.json --out out/rf1086

# 2. Validate the generated files against the official XSDs (docs/filing/*.xsd) before sending
uv run python -m holding_cli.main validate-rf1086-xml \
  --hovedskjema out/rf1086/1086H.xml \
  --underskjema out/rf1086/1086U-*.xml

# 3. Preview the exact submission/receipt plan (endpoints, order, idempotency keys)
cat preview.json | uv run python -m holding_cli.main simulate-rf1086-submission --stdin-json
```

**Acquire the test token (Maskinporten, on behalf of the Tenor test AS):**

The SKD RF-1086 API takes the **Maskinporten access token directly** — there is **no Altinn token
exchange** for this API. The `private_key_jwt` grant signed with `~/talli-test.key`
(kid `2d275f93-10a2-4839-993e-b14da2b84ad8`) must carry an `authorization_details` claim of type
`urn:altinn:systemuser` naming the customer org, so Maskinporten resolves the Step-4b systembruker
and enriches the returned token with `systemuser_id` / `system_id`:

```jsonc
// JWT grant claims (header: { "alg": "RS256", "kid": "<kid>" })
{
  "iss": "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",   // = sub = Talli's client_id
  "sub": "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
  "aud": "https://test.maskinporten.no/",           // trailing slash required
  "scope": "skatteetaten:innrapporteringaksjonaerregisteroppgave",
  "iat": <now>, "exp": <now+119>, "jti": "<uuid>",   // exp-iat ≤ 120s
  "authorization_details": [
    { "type": "urn:altinn:systemuser",
      "systemuser_org": { "authority": "iso6523-actorid-upis", "ID": "0192:<customerOrgNo>" } }
  ]
}
```

```bash
# POST the signed assertion to the test token endpoint
ACCESS_TOKEN=$(curl -sS -X POST https://test.maskinporten.no/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer" \
  --data-urlencode "assertion=${SIGNED_JWT}" | jq -r '.access_token')
```

The returned token's `authorization_details` will include `systemuser_id` + `system_id`, `consumer.ID`
= Talli's vendor org `0192:930835978`, and `systemuser_org.ID` = the customer. (Same flow proven by
the Step-3 smoke-test, which returned MP-250 `invalid_scope` only because the scope grant was still
pending — auth + signing were already correct.) Reference: Altinn usetoken guide + Skatteetaten
`systembruker.md`.

**POST the filing in order** (base `https://api-test.sits.no/api/aksjonaerregister/v1/{inntektsaar}`,
one new `idempotencyKey` UUID per distinct logical call/body):

```bash
BASE="https://api-test.sits.no/api/aksjonaerregister/v1/${INNTEKTSAAR}"
H_AUTH="Authorization: Bearer ${ACCESS_TOKEN}"
H_ACCEPT="Accept: application/json"
H_XML="Content-Type: application/xml"

# (a) Hovedskjema → returns {hovedskjemaid}
HOVEDID=$(curl -sS -X POST "$BASE/1086H" \
  -H "$H_AUTH" -H "$H_ACCEPT" -H "$H_XML" -H "idempotencyKey: $(uuidgen)" \
  --data-binary @out/rf1086/1086H.xml | jq -r '.hovedskjemaid')

# (b) Underskjema — one POST per shareholder (200, no body)
curl -sS -X POST "$BASE/$HOVEDID/1086U" \
  -H "$H_AUTH" -H "$H_ACCEPT" -H "$H_XML" -H "idempotencyKey: $(uuidgen)" \
  --data-binary @out/rf1086/1086U-<shareholderId>.xml

# (c) Bekreft — pass the underskjema count; returns the receipt references
curl -sS -X POST "$BASE/$HOVEDID/bekreft?antall_underskjema=${COUNT}" \
  -H "$H_AUTH" -H "$H_ACCEPT" -H "idempotencyKey: $(uuidgen)"
  # → oppgavegiversLeveranseReferanse, dialogId, forsendelseId

# (d) Dokumenter — retrieve feedback / archive references
curl -sS -X GET "$BASE/$HOVEDID/dokumenter" -H "$H_AUTH" -H "$H_ACCEPT"
```

**Capture as evidence** (maps to `authority_test_runs`, see "How this maps to Talli's gates"):
- **Accepted status** — the `bekreft` 200 response.
- **Receipt reference** — `oppgavegiversLeveranseReferanse` (and `forsendelseId`).
- **Archive reference** — the feedback document id(s) from `GET /dokumenter`.

Idempotency, retry, and failure-handling rules are authoritative in
`rf1086-production-submission-runbook.md` (§Idempotency Policy, §Failure Handling) — the same
rules apply in test; only the base URL and subject change.

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
| 1. Operating entity registered (ENK, org nr) | ☑ | ☑ | ☑ |
| 2. Virksomhetssertifikat (test self-signed) | ☑ | ☑ | ☑ |
| 3. Maskinporten client + scope | ◑ client+key done; scope `Tilgang mangler` | ◑ | ◑ |
| 4. Altinn system user + access pkg | ◑ **4a DONE** (system `930835978_talli` registered); all 3 Altinn scopes active on client; 4b needs a Tenor test AS | ◑ 4a done (shared system); 4b + årsregnskap pkg pending | ◑ 4a done (shared system); 4b + skattemelding resource pending |
| 5. Tenor test subjects | ☐ | ☐ | ☐ |
| 6. Accepted test submission | ☐ | ☐ | ☐ |
| 7. `authority_permissions` recorded | ☐ | ☐ | ☐ |
| 8. `authority_test_runs` accepted | ☐ | ☐ | ☐ |
| 9. `*_authority` launch signoff | ☐ | ☐ | ☐ |

Step 3 status (2026-06-30): one shared TT02 client `7166e743-978e-4a60-8a2d-0a5c00fe6ad0`
(kid `2d275f93-10a2-4839-993e-b14da2b84ad8`) created with all three scopes attached as pending;
Maskinporten signing smoke-test passed (auth OK, only scope grant missing). See the "Live state"
block under Step 3.

Step 4 status (2026-07-01): **4a DONE** — `systemregister.write` grant went live, a token minted
(HTTP 200), and the systemregister payload POSTed successfully → system **`930835978_talli`**
registered in TT02 (GET confirms `rights` = RF-1086 resource, `clientId` = the Step-3 client,
`isVisible: true`). Remaining for 4b: (a) add `systemuser.request.write`/`.read` to the client in
the Digdir portal (granted to the org but MP-200 until on the client), and (b) a Tenor test AS
(Step 5) to be the customer `partyOrgNo`. RF-1086 token confirmed to use `authorization_details`
type `urn:altinn:systemuser` against the SKD API directly (no Altinn exchange).

Steps 1–5 are shared and only need to be done once; the per-obligation columns diverge from
Step 3 (scopes) onward.
