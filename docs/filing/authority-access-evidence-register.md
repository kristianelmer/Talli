# Authority Access Evidence Register

Status: test access, Maskinporten authentication, and delegated system-user authorization proven; synthetic submission pending

Last updated: 2026-07-13

Applies to: RF-1086 and skattemelding for AS

This register records external authority-access evidence for Talli. It deliberately
separates five different gates:

1. Skatteetaten grants the organization access to a service in test.
2. The relevant scope is attached and usable on the Maskinporten test client.
3. Talli can issue a valid Maskinporten token with its own signing key.
4. Altinn system-user authorization permits Talli to act for the filing company.
5. A synthetic submission, feedback retrieval, receipt, and archive flow succeeds.

Passing an earlier gate does not imply that a later gate or production access has
passed.

## Official Sources

- Digdir Maskinporten consumer guide:
  https://docs.digdir.no/docs/Maskinporten/maskinporten_guide_apikonsument
- Digdir JWT grant specification:
  https://docs.digdir.no/docs/Maskinporten/maskinporten_protocol_jwtgrant
- Skatteetaten RF-1086 API documentation:
  https://skatteetaten.github.io/api-dokumentasjon/api/innrapportering-aksjonaerregisteroppgave
- Skatteetaten skattemelding system-supplier API documentation:
  https://github.com/Skatteetaten/skattemeldingen/blob/master/docs/api-v2/README.md
- Skatteetaten external API support portal:
  https://eksternjira.sits.no/plugins/servlet/desk/site/global

## Organization and Test Client

| Item | Recorded value | Evidence status |
| --- | --- | --- |
| System supplier | ELMER WELFIS / Talli | Confirmed in access request and approval |
| Organization number | `930835978` | Confirmed in access request and approval |
| Environment | Test / TT02 only | Confirmed in access request and approval |
| Maskinporten client id | `7166e743-978e-4a60-8a2d-0a5c00fe6ad0` | Confirmed in Digdir self-service UI |
| Client name | `Talli test - RF-1086 og systembruker` | Confirmed in Digdir self-service UI |

The client id, organization number, public key id, and public scopes are not
credentials. Private keys, assertions, access tokens, certificate passwords, and
other secrets must never be recorded in this register.

## Evidence Timeline

| Date | Evidence | Result |
| --- | --- | --- |
| 2026-06-30 | Email request to Skatteetaten for RF-1086 test access | Requested RF-1086 reporting and file-upload scopes for the TT02 client |
| 2026-06-30 | Follow-up email request for skattemelding for AS | Requested `skatteetaten:formueinntekt/skattemelding` for the same TT02 client |
| 2026-07-13 | Access application submitted through Skatteetaten's external API support portal | Requested `Aksjonærregisteret - Innrapportering aksjonærregisteroppgave` and `Skattemeldingen - Innrapportering skattemelding`, Test only |
| 2026-07-13 | Skatteetaten Fagsupport response | Granted `Innrapportering aksjonærregisteroppgave (DM-8)` and `Innrapportering skattemelding (DM-30)` in Test to organization `930835978` |
| 2026-07-13 | Digdir client scope inspection | Main RF-1086 scope is usable; skattemelding scope is usable after being added; RF-1086 file-upload scope still displays `Tilgang mangler` |
| 2026-07-13 | Support follow-up | Asked whether the separate RF-1086 file-upload scope is still required and, if so, requested access |
| 2026-07-13 | Local key verification | Located the client-bound private key outside the repository; permissions are `0600`, OpenSSL validation passed, and the derived public key is 4096-bit RSA |
| 2026-07-13 | Maskinporten JWT grant for main RF-1086 scope | HTTP 200; token issued with the requested scope, expected test issuer/client id, `private_key_jwt`, and 120-second lifetime |
| 2026-07-13 | Maskinporten JWT grant for skattemelding scope | HTTP 200; token issued with the requested scope, expected test issuer/client id, `private_key_jwt`, and 120-second lifetime |
| 2026-07-13 | Altinn TT02 System Register read | Found existing visible system `930835978_talli`, named `Talli`, linked to the expected vendor and Maskinporten client; it initially contained only the RF-1086 resource |
| 2026-07-13 | Altinn TT02 System Register rights update | Preserved the RF-1086 resource and added `app_skd_formueinntekt-skattemelding-v2`; HTTP 200 update and HTTP 200 read-back confirmed both resources, the expected client link, and `isVisible=true` |
| 2026-07-13 | Standard system-user request for test company `310279617` | Created request `3d0a9681-87fc-4cd0-967d-cc736d93a686`; HTTP 201, status `New`, and both filing resources confirmed by API read-back |
| 2026-07-13 | TT02 approval troubleshooting | Chrome repeatedly redirected through `reportee/changeandredirect` and remained on `Laster forespørsel`; disabling the site-specific content blocker did not resolve the loop. Safari with high-assurance TestID and the direct confirmation URL loaded the correct company context without creating a duplicate request. |
| 2026-07-13 | TT02 system-user approval | The approval UI confirmed Talli, `LOGISK ØDE TIGER AS` (`310279617`), and both requested services. A vendor API read returned HTTP 200 and status `Accepted` for request `3d0a9681-87fc-4cd0-967d-cc736d93a686`. |
| 2026-07-13 | System-user-bound Maskinporten grant | HTTP 200; one 120-second token carried both Skatteetaten scopes plus `urn:altinn:systemuser` details for customer `0192:310279617`, system `930835978_talli`, and the accepted system-user id. No access token or assertion was retained. |

## Current Scope State

| Scope | Client state | Decision |
| --- | --- | --- |
| `skatteetaten:innrapporteringaksjonaerregisteroppgave` | Attached; ordinary and system-user-bound tokens issued successfully on 2026-07-13 | Test authentication and delegated system-user authorization proven; provider API flow still pending |
| `skatteetaten:formueinntekt/skattemelding` | Attached; ordinary and system-user-bound tokens issued successfully on 2026-07-13 | Test authentication and delegated system-user authorization proven; validation and submission flow still pending |
| `skatteetaten:innrapporteringaksjonaerregisteroppgavefilopplasting` | Attached; `Tilgang mangler` | Do not request in a token until Skatteetaten confirms whether it is current and grants access if required |
| `altinn:authentication/systemregister.write` | Attached | Runtime proven through system update and read-back |
| `altinn:authentication/systemuser.request.read` | Attached | Runtime proven through request read-back before and after approval |
| `altinn:authentication/systemuser.request.write` | Attached | Runtime proven through HTTP 201 request creation |

## Signing-Key State

Digdir self-service shows one client-bound asymmetric public key:

| Item | Value |
| --- | --- |
| Key id (`kid`) | `2d275f93-10a2-4839-993e-b14da2b84ad8` |
| Algorithm | `RS256` |
| Key type | `RSA` |
| Public-key expiry | 2027-06-30 |

The corresponding private key was subsequently located outside the repository.
It has local mode `0600`, passes OpenSSL private-key validation, and derives a
4096-bit RSA public key with SHA-256 fingerprint
`7e649e303b4538953dd685f57951285192d42c4a52f1df89362b4fb3ac5f8b3e`.

Successful JWT grants for both active Skatteetaten scopes prove that this private
key matches the public key registered under the recorded `kid`. The private-key
path and contents are intentionally not committed or recorded here.

## Altinn Authorization Targets

The Skatteetaten documentation currently identifies these authorization resources:

| Filing | Resource/system authorization |
| --- | --- |
| RF-1086 | `ske-innrapportering-aksjonaerregisteroppgave` |
| Skattemelding for AS | `app_skd_formueinntekt-skattemelding-v2` |

Altinn TT02 now records both values on system `930835978_talli`, which is linked
to the expected Maskinporten client and remains visible. Standard system-user
request `3d0a9681-87fc-4cd0-967d-cc736d93a686` requests both values for test
company `310279617`. The request is `Accepted`. A subsequent Maskinporten grant
for both Skatteetaten scopes returned the matching customer, system id, and
system-user id in `authorization_details`, proving the delegated token path.

## Current Synthetic Filing-Company Candidate

Tenor candidate `310279617`, `LOGISK ØDE TIGER AS`, is the current preferred
company for the delegated-authorization test. Synthetic personal identifiers are
not recorded here.

| Criterion | Evidence | Assessment |
| --- | --- | --- |
| Legal form and status | AS; registered in Foretaksregisteret; not deleted, bankrupt, liquidating, or under compulsory dissolution | Pass |
| Holding-company activity | SN2025 `64.220`, `Spesielle holdingselskaper`; purpose and activity use the same description | Pass for synthetic holding scenario |
| Operational simplicity | Zero employees; not VAT registered; audit exemption elected | Pass |
| Capital structure | NOK 1,000,000 fully paid share capital; 500 shares at NOK 2,000 | Pass, though larger than a minimal holding company |
| Authorized test roles | Synthetic managing director and synthetic chairperson are present | Pass; the chairperson approved the request with high-assurance TestID in TT02 |
| Filing-data freshness | Latest annual accounts shown by the organization dataset are from 2019 | Historical register data is old, but this is not itself a blocker for synthetic submission testing |
| Skatteetaten submission environment | Tenor shows five `testinnsendingSkattEnhet` records covering income years 2022–2026 | Pass for environment presence; 2025 is available as a clean submission target |
| Existing 2025 return state | No draft or assessed skattemelding/selskapsmelding is shown; selected categories of source data are marked missing | Suitable clean starting point, but successful API validation/submission is still unproven |

The candidate passed the initial delegated-authorization test and remains selected
for the clean submission test. It must be replaced only if either filing API
rejects the company for reasons intrinsic to its test-data setup.

## Next Evidence Required

1. Run non-mutating provider connectivity checks with short-lived system-user
   tokens.
2. Validate a minimal 2025 skattemelding payload without final submission.
3. Execute synthetic RF-1086 and skattemelding submission flows and
   persist feedback, receipt, and archive references.
4. Keep production submission disabled until the filing-specific release gates and
   human signoffs pass.
