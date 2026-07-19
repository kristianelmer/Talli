# Skatteetaten Production Access Research — Skattemelding for AS

Status: official-source research complete; production filing remains disabled
Research date: 2026-07-14
Scope: Talli as a Norwegian sluttbrukersystemleverandør (SBS) preparing a
company tax return for a customer that files for its own organization

This document records the current official onboarding and runtime boundary for
production company-tax-return filing. It is not an approval to create production
instances or enable a production adapter. The external approvals and internal
release evidence in [Fail-closed release boundary](#fail-closed-release-boundary)
must exist before production use.

## Decision Summary

The supported production model is:

1. Talli obtains separate production access from Skatteetaten, Digdir, and
   Altinn.
2. Each customer approves an Altinn **standard / own-system Systembruker** for
   its own organization.
3. Talli uses Systembruker to fetch and validate the current tax return, create
   an Altinn instance, and upload the files.
4. Talli stops at `Bekreftelse` and hands the instance to a person.
5. A person authenticated through **ID-porten** reviews and submits the tax
   return and business specification.
6. Talli resumes read-only, retrieves the asynchronous `tilbakemelding` XML,
   and archives the official references and sanitized outcome.

The final submission must not be automated with Systembruker. Skatteetaten's
11 June 2026 SBS presentation states on PDF page 18 that Systembruker may call
validation, create an instance, and upload files, but that an ID-porten-authenticated
person must submit the tax return and business specification. This newer,
explicit boundary supersedes older examples that show two machine-callable
`process/next` operations. Source: [Skatteetaten SBS presentation, page
18](https://www.skatteetaten.no/contentassets/fd26e08a23cc49549506dcefa74612bb/2026-6-2026-06-11-fellesmote-skattemeldingen-for-sbs.pdf#page=18).

## Confirmed Prerequisites

### 1. Skatteetaten supplier access

Skatteetaten requires the supplier to apply for permission. Its current access
page explicitly supports scope applications for both test and production,
includes **Skattemeldingen**, and requires acceptance of the SBS terms. The
application is submitted through Skatteetaten's support service. Source:
[Skatteetaten access application](https://www.skatteetaten.no/samarbeidspartnere/sluttbrukersystemer/sbs-nyheter/her-kan-du-soke-om-tilgang-til-tjenester-for-innrapportering-til-skatteetaten/).

The person submitting the application needs access to the support service. As
of May 2026, the current Altinn 3 access package is **Teknisk samhandling med
Skatteetaten**; alternatively, the relevant support-administration single
service can be delegated. Source: [Skatteetaten support-service access
update](https://www.skatteetaten.no/samarbeidspartnere/sluttbrukersystemer/sbs-nyheter/brukerstottetjenesten-altinn-3/).

The application should request production access to **Skattemeldingen** for the
supplier organization and identify the production Maskinporten client. The
service scope is:

`skatteetaten:formueinntekt/skattemelding`

Skatteetaten's API catalogue says this scope is required and that Skatteetaten
must grant the organization access. Source: [official API catalogue at commit
`31f2bf0`](https://github.com/Skatteetaten/api-dokumentasjon/blob/31f2bf07fa903727931a09facd4153d1efb109ef/docs/api/innrapportering-skattemelding.md#tilgang-til-api-et).

The supplier terms make the following production prerequisites explicit:

- Skatteetaten permission is application-based.
- The supplier must accept the terms and any applicable service description,
  complete integration testing, and connect to production.
- Skatteetaten may request documentation showing how the integration was
  tested.
- The supplier needs valid customer agreements and data-processing agreements,
  its own access control, privacy/security controls and documented internal
  control, customer support, incident handling, and contingency procedures.
- The supplier must subscribe to Skatteetaten's service-status notifications
  and should follow Digdir status notifications.

Source: [Skatteetaten SBS terms](https://www.skatteetaten.no/samarbeidspartnere/sluttbrukersystemer/bruksvilkar/),
especially `Tilgang til tjenestene`, `Test av integrasjon`, `Personvern og
informasjonssikkerhet`, and `Driftsvarsler`.

No public primary source defines a guaranteed approval time or states that one
particular receipt automatically satisfies production certification. The
application must therefore ask Skatteetaten to adjudicate Talli's TT02 evidence.

### 2. Digdir and Altinn supplier onboarding

Altinn's current Systembruker onboarding requires:

- a Norwegian organization number;
- accepted Maskinporten/ID-porten terms;
- accepted Altinn terms;
- a production Maskinporten client; and
- access to the Systembruker control-plane APIs.

The system supplier must use Altinn's linked registration form to obtain these
control-plane scopes:

- `altinn:authentication/systemregister.write`
- `altinn:authentication/systemuser.request.read`
- `altinn:authentication/systemuser.request.write`

Source: [Altinn Systembruker onboarding](https://docs.altinn.studio/en/authorization/getting-started/systemuser/#system-vendor).

These administrative scopes are distinct from the runtime filing scopes. They
should be treated as control-plane authority and may be isolated on a separate
Maskinporten client.

### 3. Production Maskinporten client

Production self-service is at
[sjolvbetjening.samarbeid.digdir.no](https://sjolvbetjening.samarbeid.digdir.no).
Access is protected by Ansattporten and must be delegated through Altinn by an
authorized person. The relevant right for managing test and production clients
is **Selvbetjening av klienter i ID-porten/Maskinporten**. Sources:
[Digdir self-service access](https://docs.digdir.no/docs/Maskinporten/maskinporten_sjolvbetjening_web.html#tilgang-i-test-og-produksjonsmiljo)
and [Altinn's current client setup guide](https://docs.altinn.studio/en/authorization/getting-started/maskinportenclient/#setting-up-the-maskinporten-client).

Create a production client for the supplier organization, select Maskinporten,
and add only approved scopes. Register the public JWK or PEM key and keep the
private key in production secret storage. Current official client documentation
permits a registered JWK/PEM key; it does **not** require a CA-issued
virksomhetssertifikat when that mechanism is used. A self-registered asymmetric
key has a maximum one-year lifetime and must be rotated before expiry. Sources:
[Altinn client key setup](https://docs.altinn.studio/en/authorization/getting-started/maskinportenclient/#setting-up-the-maskinporten-client)
and [Digdir client-registration rules](https://docs.digdir.no/docs/idporten/oidc/oidc_func_clientreg.html#bruk-av-asymmetrisk-nokkel).

For the filing runtime, the client needs:

- `skatteetaten:formueinntekt/skattemelding`
- `altinn:instances.read`
- `altinn:instances.write`

The Skatteetaten scope is granted by Skatteetaten. The two Altinn scopes are the
instance read/write scopes documented for this filing flow. Source: [official
Skatteetaten API guide at commit `4d7cd2c`, lines
70–76](https://github.com/Skatteetaten/skattemeldingen/blob/4d7cd2cd7594ba253479d4e543ba2f8e3ea5d017/docs/api-v2/README.md#L70-L76).

## Scope and Resource Matrix

| Purpose | Scope or right | Granted/configured by | Used for |
| --- | --- | --- | --- |
| Skatteetaten runtime | `skatteetaten:formueinntekt/skattemelding` | Skatteetaten grants; supplier adds to production client | Fetch current document and validate against Skatteetaten |
| Altinn app runtime | `altinn:instances.read` | Altinn/Digdir scope on production client | Read instance, status, data metadata, receipt |
| Altinn app runtime | `altinn:instances.write` | Altinn/Digdir scope on production client | Create instance, upload data, advance to confirmation |
| System registration | `altinn:authentication/systemregister.write` | Altinn supplier onboarding | Create/update the production system definition |
| System-user request | `altinn:authentication/systemuser.request.write` | Altinn supplier onboarding | Create own-system request and verify the resulting user |
| System-user request status | `altinn:authentication/systemuser.request.read` | Altinn supplier onboarding | Read request lifecycle/status |
| Fine-grained Altinn right | `app_skd_formueinntekt-skattemelding-v2` | Put in system definition and customer Systembruker grant | Authorize Systembruker for the Skatteetaten Altinn app |

The exact app resource is confirmed in the service-specific guide: [official
Skatteetaten API guide, lines
111–116](https://github.com/Skatteetaten/skattemeldingen/blob/4d7cd2cd7594ba253479d4e543ba2f8e3ea5d017/docs/api-v2/README.md#L111-L116).
Do not substitute a generic access package unless Skatteetaten explicitly
instructs Talli to do so.

## Production System Registration

Register a separate production system definition in Altinn. A Maskinporten
token carrying `altinn:authentication/systemregister.write` authenticates the
request. The system definition must contain:

- `id` in the form `<supplierOrgNo>_<chosenName>`;
- `vendor.ID` in the form `0192:<supplierOrgNo>`;
- `nb`, `nn`, and `en` name and description;
- the individual right `app_skd_formueinntekt-skattemelding-v2`;
- the production Maskinporten client ID;
- exact HTTPS redirect URLs if the vendor-controlled return flow uses one; and
- `isVisible: true` only if Talli also wants customers to create the system
  access through the Altinn portal.

Source: [Altinn system-registration guide](https://docs.altinn.studio/en/authorization/guides/system-vendor/system-user/systemregistration/#instructions)
and [Altinn create-system API](https://docs.altinn.studio/en/api/authentication/systemuserapi/systemregister/create/).

The relative endpoint is:

`POST authentication/api/v1/systemregister/vendor`

Using Altinn's documented production platform host gives:

`POST https://platform.altinn.no/authentication/api/v1/systemregister/vendor`

The full production URL is an environment-host composition: the API path is
explicit in the system-register documentation, while `platform.altinn.no` is
explicitly the production host throughout the current Systembruker API guide.
It should be confirmed in the Skatteetaten/Altinn production-access ticket
before the first call.

Minimal service-specific portion of the system definition:

```json
{
  "id": "<supplierOrgNo>_talli_tax_return",
  "vendor": {
    "authority": "iso6523-actorid-upis",
    "ID": "0192:<supplierOrgNo>"
  },
  "rights": [
    {
      "resource": [
        {
          "id": "urn:altinn:resource",
          "value": "app_skd_formueinntekt-skattemelding-v2"
        }
      ]
    }
  ],
  "accessPackages": [],
  "clientId": ["<productionMaskinportenClientId>"],
  "allowedredirecturls": ["https://<talli-production-host>/<exact-return-path>"],
  "isVisible": true
}
```

Use `POST` once to create. When changing a system, `PUT` replaces the complete
definition, so fetch the existing definition and send the complete updated
body. Source: [Altinn system-registration guide, step
9](https://docs.altinn.studio/en/authorization/guides/system-vendor/system-user/systemregistration/#step-by-step).

## Customer Own-System Approval

Talli customers file for their own organization. The correct Altinn model is a
**standard Systembruker for own system**, not the agent/client-system model used
by accountants or other service providers filing for clients. Altinn permits
both user-controlled and vendor-controlled creation for an own-system user.
Source: [Altinn Systembruker guide](https://docs.altinn.studio/en/authorization/guides/system-vendor/system-user/#system-user-for-own-system).

The preferred product flow is vendor-controlled:

1. Talli mints an administrative Maskinporten token with
   `altinn:authentication/systemuser.request.write`.
2. Talli posts to:
   `https://platform.altinn.no/authentication/api/v1/systemuser/request/vendor`.
3. The body identifies the production system, the customer's nine-digit
   `partyOrgNo`, an opaque `externalRef`, and the exact app right.
4. Altinn returns `status: "New"` and a `confirmUrl`. Talli must relay the
   returned URL securely and must not construct or guess it.
5. A person representing the customer opens the URL, selects the customer
   organization, and approves the requested access.
6. The request becomes `Accepted`. Talli verifies the created user through the
   production `byquery` endpoint before attempting any runtime token.

Source: [Altinn create-Systembruker guide](https://docs.altinn.studio/en/authorization/guides/system-vendor/system-user/systemuserrequest/#1-create-system-user-for-own-system).

The approving person must be **Tilgangsstyrer** for the selected organization
and must personally hold the permissions requested by the system. The customer
can alternatively create the access through Altinn's `Systemtilganger` UI; the
official guide notes that activation may take up to five minutes. Source:
[Altinn own-system access guide, updated 30 June
2026](https://info.altinn.no/hjelp/ny-tilgangsstyring/steg-for-steg-guider/opprette-systemtilgang-i-altinn/).

Do not call `/systemuser/request/vendor/agent/` for the supported Talli model.
That endpoint is for a system acting on behalf of the end user's clients and
requires a later client-delegation step.

## Production Token Flow

### Maskinporten Systembruker token

For a specific customer, Talli creates a signed JWT grant containing:

- `iss` (and, where used by the library, `sub`) set to the production client ID;
- a short `iat`/`exp` window and unique `jti`;
- the least-privilege runtime scope(s); and
- the RAR `authorization_details` entry:

```json
{
  "type": "urn:altinn:systemuser",
  "systemuser_org": {
    "authority": "iso6523-actorid-upis",
    "ID": "0192:<customerOrgNo>"
  },
  "externalRef": "<opaque-reference-if-one-was-used>"
}
```

Only one customer organization may be requested per grant. If the Systembruker
was created with `externalRef`, the same value is required to select it. Source:
[Altinn: using Systembruker](https://docs.altinn.studio/en/authorization/guides/system-vendor/system-user/usetoken/#request-system-access-token-jwt-grant).

The production Maskinporten metadata currently declares:

- issuer / JWT `aud`: `https://maskinporten.no/`
- token endpoint: `https://maskinporten.no/token`
- grant: `urn:ietf:params:oauth:grant-type:jwt-bearer`

Resolve these values from [Maskinporten's live production
metadata](https://maskinporten.no/.well-known/oauth-authorization-server), not
from a hard-coded example. The token request is an HTTP `POST` with
`application/x-www-form-urlencoded`, containing `assertion=<signed-jwt>` and
the JWT-bearer `grant_type`. Source: [Digdir token protocol](https://docs.digdir.no/docs/Maskinporten/maskinporten_protocol_token.html#request).

Use separate least-privilege tokens:

- a Systembruker token with
  `skatteetaten:formueinntekt/skattemelding` for the Skatteetaten API; and
- a Systembruker token with `altinn:instances.read altinn:instances.write` for
  the Altinn instance/app operations.

### Exchange for Altinn app operations

Altinn Apps do not accept the Maskinporten token directly in this flow. Exchange
the Altinn-scoped Systembruker token with:

```http
GET https://platform.altinn.no/authentication/api/v1/exchange/maskinporten
Authorization: Bearer <maskinporten-system-user-token>
```

Use the returned Altinn token for the app and platform APIs. The current Altinn
SBS guide documents the provider-specific `/exchange/maskinporten` path and
the Systembruker token exchange. Source: [Altinn SBS setup, step
6](https://docs.altinn.studio/en/altinn-studio/v8/guides/integration/sbs/setup/#6-fiken-can-authenticate-against-maskinporten-with-the-system-user).

## Runtime Filing Sequence and Human Boundary

### Production endpoints

| Component | Production endpoint |
| --- | --- |
| Skatteetaten tax API base | `https://api.skatteetaten.no` |
| Altinn app base | `https://skd.apps.altinn.no/skd/formueinntekt-skattemelding-v2/` |
| Altinn token exchange | `https://platform.altinn.no/authentication/api/v1/exchange/maskinporten` |
| Human viewer | `https://skatt.skatteetaten.no/web/skattemelding-visning/altinn?appId=skd/formueinntekt-skattemelding-v2&instansId=<partyId>/<instanceUuid>` |

The Skatteetaten API and app hosts are explicit in the official service guide:
[tax API environment table](https://github.com/Skatteetaten/skattemeldingen/blob/4d7cd2cd7594ba253479d4e543ba2f8e3ea5d017/docs/api-v2/README.md#L161-L166)
and [Altinn app base](https://github.com/Skatteetaten/skattemeldingen/blob/4d7cd2cd7594ba253479d4e543ba2f8e3ea5d017/docs/api-v2/README.md#L2182-L2203).

### Systembruker preparation

1. Fetch the current Skatteetaten document/draft for the customer and income
   year. Retain the authority document reference needed for real validation.
2. Validate the complete tax return and business specification through the real
   `valider` endpoint. `validertest` is explicitly not suitable for validation
   for submission because it does not run controls against the current draft.
3. Create an instance in
   `skd/formueinntekt-skattemelding-v2`, including `inntektsaar`.
4. If attachments are required, upload them first and include their returned
   IDs in the tax-return XML. If Talli has no approved attachment flow, stop.
5. Upload the combined XML as data type
   `skattemeldingOgNaeringsspesifikasjon` with:
   - `Content-Type: text/xml`
   - `Content-Disposition: attachment; filename=skattemelding.xml`
6. Advance the instance once to `Bekreftelse` (uploaded and ready for personal
   confirmation).

Source: [official Altinn3 filing sequence](https://github.com/Skatteetaten/skattemeldingen/blob/4d7cd2cd7594ba253479d4e543ba2f8e3ea5d017/docs/api-v2/README.md#altinn3-api)
and [upload contract, lines
2336–2374](https://github.com/Skatteetaten/skattemeldingen/blob/4d7cd2cd7594ba253479d4e543ba2f8e3ea5d017/docs/api-v2/README.md#L2336-L2374).

### Human submission

At `Bekreftelse`, Talli opens the exact production viewer URL using the instance
ID returned by Altinn. The person authenticates with ID-porten, selects the
company, reviews the rendered tax return and business specification, and
performs the final submission.

Talli must not call the final transition with a Systembruker token. The
authoritative boundary is the newer [11 June 2026 Skatteetaten presentation,
page 18](https://www.skatteetaten.no/contentassets/fd26e08a23cc49549506dcefa74612bb/2026-6-2026-06-11-fellesmote-skattemeldingen-for-sbs.pdf#page=18).
The production viewer pattern is documented in the [official API guide, lines
2389–2398](https://github.com/Skatteetaten/skattemeldingen/blob/4d7cd2cd7594ba253479d4e543ba2f8e3ea5d017/docs/api-v2/README.md#L2389-L2398).

### Receipt retrieval

After personal submission, Skatteetaten processes the filing asynchronously and
uploads the XML receipt/feedback to the same Altinn instance. Talli then:

1. reads the instance metadata with an exchanged Altinn token;
2. locates the data element whose `dataType` is `tilbakemelding`; and
3. downloads that data element from
   `<app-base>/instances/<instance-id>/data/<data-id>`.

The receipt may not be available immediately. Source: [official receipt
retrieval contract, lines
2412–2424](https://github.com/Skatteetaten/skattemeldingen/blob/4d7cd2cd7594ba253479d4e543ba2f8e3ea5d017/docs/api-v2/README.md#L2412-L2424).

It is a supported inference, rather than a single express sentence, that Talli
may perform this post-human retrieval with its accepted Systembruker: Altinn's
current guide authorizes exchanged Systembruker tokens for app operations, and
the receipt contract uses instance read/data read. Confirm this composition in
the production-access ticket and preserve fail-closed behavior until verified.

## Documentation Discrepancies and Safe Resolution

### Maskinporten exchange path

The Skatteetaten repository currently shows both ID-porten and Maskinporten
tokens being exchanged through `/exchange/id-porten` ([lines
2204–2214](https://github.com/Skatteetaten/skattemeldingen/blob/4d7cd2cd7594ba253479d4e543ba2f8e3ea5d017/docs/api-v2/README.md#L2204-L2214)).
Current Altinn documentation uses `/exchange/maskinporten` for a Maskinporten
Systembruker token. Use the current Altinn path and ask Skatteetaten to confirm
it in writing before production.

### Final `process/next`

The same repository presents two API transitions, including one to final
`Tilbakemelding`. The newer 11 June 2026 Skatteetaten presentation explicitly
limits Systembruker to validation, instance creation, and upload, and requires
an ID-porten-authenticated person to submit. Talli must stop after the first
transition to `Bekreftelse`.

### Maskinporten audience formatting

Some Altinn examples omit the trailing slash in `aud`. Digdir's protocol
requires `aud` to equal the Maskinporten issuer exactly, and the production
metadata currently returns `https://maskinporten.no/`. Resolve from
`.well-known` and preserve the trailing slash.

### System-register scope name

One generic Altinn client-setup table lists
`altinn:authentication/systemregister`, but the specific, newer Systembruker
onboarding, system-registration, and SBS setup guides require
`altinn:authentication/systemregister.write`. Use the `.write` scope and verify
the grant in production.

### Authentication key versus virksomhetssertifikat

Older project notes say production Maskinporten requires a paid CA-issued
virksomhetssertifikat. Current Digdir/Altinn client documentation permits a
pre-registered asymmetric JWK/PEM public key with the private key held by the
client. A CA certificate remains an available mechanism, but is not documented
as mandatory for this production client.

### Individual resource versus access package

The service-specific Skatteetaten guide names the exact resource
`app_skd_formueinntekt-skattemelding-v2`. Generic Altinn examples use unrelated
access packages. Talli should register and request the exact individual right
unless Skatteetaten explicitly provides a replacement.

## Items Requiring Written Authority Confirmation

Ask Skatteetaten/Altinn in the production-access ticket to confirm:

1. whether Talli's sanitized TT02 `validertOK`, personally submitted instance,
   official `tilbakemelding`, and archive evidence satisfies the completed-test
   requirement;
2. whether the final receipt outcome is accepted despite any guidance/deviation
   codes, and what evidence is required to classify it as accepted;
3. the production `/exchange/maskinporten` route for this app;
4. that Systembruker must stop at `Bekreftelse` and the person must make the
   final transition through ID-porten;
5. that the same accepted Systembruker may resume read-only to retrieve the
   `tilbakemelding` after the person's submission;
6. whether Skatteetaten requires a coordinated first-production pilot or any
   additional certification; and
7. the expected production scope grant/client association and support channel.

These are questions, not currently proven requirements. No public primary
source guarantees that the existing TT02 evidence alone grants production
approval or that a coordinated pilot is mandatory.

## Fail-Closed Release Boundary

Keep the company-tax production adapter unimplemented/disabled until all of the
following have durable evidence:

- Skatteetaten has granted the production service scope to the supplier and the
  production client.
- The Skatteetaten SBS terms are accepted, and current customer contracts/DPA,
  support, incident, security, privacy, internal-control, and status-subscription
  obligations are operational.
- Altinn has granted the three Systembruker control-plane scopes.
- A production Maskinporten client exists with approved runtime scopes, a
  production-only key in managed secret storage, rotation and revocation
  procedures, and no test fallback.
- The production Altinn system is registered with the exact app right and
  production client ID.
- A customer own-system request reaches `Accepted` and a production
  Systembruker token can be obtained without storing customer or personal
  identifiers in logs.
- The real `valider` path, immutable preview/body hash, idempotent instance
  journal, upload flow, first transition, and read-only resume are implemented
  and tested.
- Attachment handling is implemented and evidenced, or a machine-enforced
  no-attachment support boundary blocks `required` and `unknown` cases.
- The human ID-porten handoff is the only final-submission path; no server-side
  code can perform the second `process/next` with Systembruker.
- Structured receipt parsing, sanitized outcome classification, receipt/data/
  archive references, and immutable audit evidence are deployed and verified.
- Only a named authority reviewer—not an owner-entered status—can promote test
  evidence to accepted.
- Deployed tenant isolation, security review, restore evidence, production
  credential review, billing/readiness gates, and named
  `tax_return_authority` signoff all pass.
- A kill switch and monitored first-production procedure exist. A production
  filing must never be used merely as a connectivity probe.

Until every gate passes, product copy and runtime behavior must continue to say
and enforce `production_disabled`.

## Current Timing Note

The current date is in ISO week 29. Skatteetaten's 11 June 2026 presentation
states on PDF page 27 that Slack/support remain open in weeks 28–31 but replies
should not be expected, week 32 has low staffing with replies not expected, and
normal staffing returns in week 33. The production application can be prepared
or submitted, but a response may not arrive until week 33. Source:
[Skatteetaten SBS presentation, page
27](https://www.skatteetaten.no/contentassets/fd26e08a23cc49549506dcefa74612bb/2026-6-2026-06-11-fellesmote-skattemeldingen-for-sbs.pdf#page=27).

## Primary Sources

- [Skatteetaten access application](https://www.skatteetaten.no/samarbeidspartnere/sluttbrukersystemer/sbs-nyheter/her-kan-du-soke-om-tilgang-til-tjenester-for-innrapportering-til-skatteetaten/)
- [Skatteetaten SBS terms](https://www.skatteetaten.no/samarbeidspartnere/sluttbrukersystemer/bruksvilkar/)
- [Skatteetaten support-service access update](https://www.skatteetaten.no/samarbeidspartnere/sluttbrukersystemer/sbs-nyheter/brukerstottetjenesten-altinn-3/)
- [Skatteetaten company-tax API guide, pinned commit](https://github.com/Skatteetaten/skattemeldingen/blob/4d7cd2cd7594ba253479d4e543ba2f8e3ea5d017/docs/api-v2/README.md)
- [Skatteetaten API catalogue, pinned commit](https://github.com/Skatteetaten/api-dokumentasjon/blob/31f2bf07fa903727931a09facd4153d1efb109ef/docs/api/innrapportering-skattemelding.md)
- [Skatteetaten SBS presentation, 11 June 2026](https://www.skatteetaten.no/contentassets/fd26e08a23cc49549506dcefa74612bb/2026-6-2026-06-11-fellesmote-skattemeldingen-for-sbs.pdf)
- [Digdir Maskinporten self-service](https://docs.digdir.no/docs/Maskinporten/maskinporten_sjolvbetjening_web.html)
- [Digdir Maskinporten token protocol](https://docs.digdir.no/docs/Maskinporten/maskinporten_protocol_token.html)
- [Maskinporten production metadata](https://maskinporten.no/.well-known/oauth-authorization-server)
- [Altinn Systembruker onboarding](https://docs.altinn.studio/en/authorization/getting-started/systemuser/)
- [Altinn production Maskinporten client](https://docs.altinn.studio/en/authorization/getting-started/maskinportenclient/)
- [Altinn system registration](https://docs.altinn.studio/en/authorization/guides/system-vendor/system-user/systemregistration/)
- [Altinn own-system Systembruker request](https://docs.altinn.studio/en/authorization/guides/system-vendor/system-user/systemuserrequest/)
- [Altinn Systembruker token](https://docs.altinn.studio/en/authorization/guides/system-vendor/system-user/usetoken/)
- [Altinn SBS token exchange](https://docs.altinn.studio/en/altinn-studio/v8/guides/integration/sbs/setup/)
- [Altinn customer own-system UI](https://info.altinn.no/hjelp/ny-tilgangsstyring/steg-for-steg-guider/opprette-systemtilgang-i-altinn/)
