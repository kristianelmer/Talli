# RF-1086 unknown-outcome read contracts — 2026-10-10

Status: public-document research; no filing/retry/activation authority.

**Finding:** the reviewed published contracts support reading an identified RF transmission and discovering candidate Dialogporten dialogs. They do **not document a complete read-only resolution for every unknown main, child, or confirmation operation**. That is an evidence gap, not proof that provider-side recovery is impossible.

Reviewed 2026-10-10 UTC. Local baseline: `ee8b3bd7f83008116c95eb58e4455fb483d9bb0f`. Only this note and new private research artifacts were written. No authenticated/provider operation, POST, token, DB, test, CI, deployment, activation, spending, or outreach occurred.

## Verified RF contract

Existing exact registry/spec bytes confirm **default/published 1.2.0**, created/modified **2026-08-25T14:46:24Z**. **1.3.0**, dated **2026-10-05T11:05:13Z**, remains unpublished; its only functional schema change is prefill status `UNDER_BEHANDLING`. It adds no recovery route. [Registry][registry], [1.2.0][rf12], [draft 1.3.0][rf13].

The complete published 1.2.0 operation set, relative to `/api/aksjonaerregister/v1`, is:

| Method / path | Recovery-relevant contract |
| --- | --- |
| `POST /{inntektsaar}/1086H` | XML; required UUID key; returns `hovedskjemaId`. |
| `POST /{inntektsaar}/{hovedskjemareferanse}/1086U` | XML; required UUID key; success has no child identifier/body. |
| `POST /{inntektsaar}/{hovedskjemareferanse}/bekreft` | Required `antall_underskjema`; returns delivery reference, `dialogId`, `forsendelseId`. OpenAPI omits the key header here. |
| `GET /{inntektsaar}/forsendelser/{forsendelseid}/dokumenter` | Paginated submitted XML documents; requires a transmission ID, not a main ID/key. |
| `GET /{inntektsaar}/forsendelser/{forsendelseId}/dokumenter/{dokumentId}` | Reads one identified document; specification calls these IDs Dialogporten Transmission/Attachment IDs. |
| `GET /prefill/{inntektsaar}/{organisasjonsnummer}` | Prior-year prefill, with status and XML; no operation key/main/dialog/transmission reference in `PrefillPage`. |

Source: [OpenAPI 1.2.0][rf12], read 2026-10-10. No GET-by-main, GET-by-idempotency-key, draft-child enumeration/status/count, or confirmation-state-by-main operation appears in that complete path/parameter set. Neither does it specify that a main UUID may substitute for `forsendelseId`.

The [official RF prose][rf-prose], revision **02072fe49d98fafda31fd7813badb84ab9640a6a, 2026-08-26**, recommends archive pagination for submitted main/child forms, with the main first. It describes repeat POSTs with identical body/key returning the first response, and `GLD_019`/409 for key reuse. It does not specify key lifetime, concurrent duplicate semantics, a read lookup, draft-document visibility, or main/key-to-Dialogporten correlation. Its example's delivery reference equals its main ID; that example does not establish a universal identity rule. Confirmation deduplication remains unresolved because its OpenAPI header definition differs from the broad prose. [RF prose][rf-prose], [1.2.0][rf12].

## Verified Dialogporten readers and limits

The official [OpenAPI page][dp-openapi-page] links the production Swagger UI. Its public **v1** JSON, fetched 2026-10-10, exposes these relevant end-user GETs under `/dialogporten/api/v1/enduser`:

- `/dialogs`: paginated search; party/resource, external reference, status, process, and date filters. A bounded party/resource search can discover **candidates**; `externalReference` is service-specific, not declared to be an RF key/main ID. [Production v1 schema][dp-spec], [search guide, page date 2026-04-23][dp-search].
- `/dialogs/{dialogId}/transmissions` and `/dialogs/{dialogId}/transmissions/{transmissionId}`: list/read transmission metadata and attachment references. `relatedTransmissionId` expresses a relation chosen by the service owner; it is not a guarantee that every RF child or retry has its own transmission. [Production v1 schema][dp-spec], [transmission guide, page date 2026-09-04][dp-transmission].
- `/dialogs/{dialogId}`: aggregate with transmissions and authorization/exclusion information. **It can populate seen-log metadata and generate an event**; it is not wholly free of side effects. Search/list APIs do not populate that log. Neither action submits RF data. [Details guide][dp-details], [seen-log guide, page date 2026-04-23][dp-seen].
- `/dialoglookup?instanceRef=…`: resolves supported Altinn instance, correspondence, or dialog URNs. An RF main ID/key is not among its documented accepted reference formats. [Lookup guide, page date 2026-04-23][dp-lookup], [production v1 schema][dp-spec].

These require end-user authorization and `digdir:dialogporten`; service-owner APIs require separate service-provider authority and must not be treated as a Talli supplier entitlement. Search results are summaries; unauthorized/excluded transmissions or attachments can hide relevant evidence. A list's absence, 404, time filter, generic completion status, or fuzzy text match cannot establish non-delivery or RF acceptance. [Production v1 schema][dp-spec], [search][dp-search], [transmission][dp-transmission].

Pinned first-party source handlers for transmission list/get use read queries and show exclusion filtering, but their repository revision is not a verified production build. The production schema above is the deployed documentation pin; generic docs can default to staging/Dev. [Source revision 1eb4fbbc91d0f9c8248160cbc0fc03306e83aa8e][dp-source], [OpenAPI page][dp-openapi-page].

## What can be resolved without filing mutations

| Unknown stage | Retained identity | Read-only evidence available / remaining gate |
| --- | --- | --- |
| Main | Original XML/hash/key; main response missing | No documented RF read keyed by those facts. Dialog search may find candidates; an authoritative RF main/key-to-dialog/operation mapping is still needed. A failed search is not proof the main was never stored. |
| Child | Persisted main ID plus exact child XML/hash/key | No documented reader for children staged under that main before confirmation. Later transmission archives can show a submitted bundle if its transmission is independently identified; that is not automatically an operation-level child receipt. Do not call confirm merely to discover whether a child arrived. |
| Confirm | Main and successful child journal; confirmation response missing | Dialog search/list can find a candidate submission and related feedback. RF archive bytes can then be compared using its identified transmission. Promoting the unknown intent requires authoritative correlation, completeness, original identity, and uniqueness; organization/year/time/content similarity alone is insufficient. |
| Confirmed references retained | Valid journaled `dialogId`/`forsendelseId` | Published archive/document readers and related Dialogporten transmissions support the existing feedback path, retaining originals and classifying related receipts. This is feedback reconciliation, distinct from recovering a lost earlier operation result. |

This table distinguishes contract facts from engineering inference: the RF paths and Dialogporten fields exist; candidate-to-intent sufficiency and required evidence are proposed recovery criteria. [1.2.0][rf12], [RF prose][rf-prose], [Dialogporten v1][dp-spec]. Prefill, including the unpublished draft status, supplies neither key correlation nor a guarantee about this exact invocation. It cannot by itself clear unknown.

Talli currently stops prepared/unknown operations at `recovery_required`. Its retained feedback preparer requires a **confirmed** dispatch assessment and exact journaled confirmation references; discovery additionally binds company/resource, the known Submission transmission, and related feedback. No current reader turns a candidate dialog into mutation success. [Dispatch assessment][dispatch], [recovery preparer][recovery], [Dialogporten adapter][dp-adapter], local baseline above.

## Safe technical next steps and external gates

1. Preserve original request bytes, hashes, method/path/query/count, keys, approval, committed intents, and every trustworthy response fragment. Do not regenerate XML or rotate keys for an unresolved intent. Expose the unknown stage and available identities in a recovery dossier. [Current adapter][adapter], [dispatch][dispatch].
2. Prepare a bounded, authorized GET-only candidate-discovery design, with pagination and exclusion checks, separately from the confirmed-feedback reader. Retain exact metadata and archive originals; never follow arbitrary presentation/action URLs. Keep candidates as evidence, not success/retry grants. [Dialogporten v1][dp-spec], [current adapter][dp-adapter].
3. Resolve external semantics through authoritative documentation or a separately authorized synthetic exercise: main/key correlation, staged child visibility/identity, confirmation correlation/deduplication, retention, complete versus filtered results, and delayed publication. No such exercise occurred here. Missing public documentation does not justify declaring recovery impossible.
4. If exact-key replay is later chosen, acknowledge it remains a **POST**. Official idempotency prose makes it a possible alternative to blind resend, but it is not a non-mutating lookup and does not itself authorize replay of a stopped Talli intent. Confirm's count/path/key behavior especially needs explicit evidence. [RF prose][rf-prose], [1.2.0][rf12], [dispatch][dispatch].

## Provenance

New exact primary bytes: `/private/tmp/talli-release-20261009/rf-unknown-contract-research` (`0700`, files `0600`). [Index](/private/tmp/talli-release-20261009/rf-unknown-contract-research/primary-source-index-v1.json) records 12 new source URLs/hashes/timestamps and references the existing three RF raw files without overwriting them. Index SHA-256: `1bcf243db72cd1ed03527d9f24aa47f6c1a6eaa891e7797c972356661c62d0b7`.

Key pins: production Dialogporten v1 JSON `ca0a7c636d0c130b52201a690039b91999c02d187b2b67914a6e4b10705b5102`; RF prose `2326c7d0cfb581da29ec6a114fda00508fa9d7325504968c7c89b492d2e1f3ce`; existing RF registry `c0aa464e7c1c20574f915d35241141e37d0b6887849783c3561a03aaa8778dfd`, 1.2.0 `1dc44e55fd993872e1cfd30fdbe59bd2f612e8e34de6d3e4c5dfdf34ab022947`, draft 1.3.0 `72130ca86eea830e58ca383c97156ee479c70fca99af065bbe964910f9c9ba50`.

[registry]: https://api.swaggerhub.com/apis/skatteetaten/innrapportering-aksjonaerregister-api
[rf12]: https://api.swaggerhub.com/apis/skatteetaten/innrapportering-aksjonaerregister-api/1.2.0
[rf13]: https://api.swaggerhub.com/apis/skatteetaten/innrapportering-aksjonaerregister-api/1.3.0
[rf-prose]: https://github.com/Skatteetaten/api-dokumentasjon/blob/02072fe49d98fafda31fd7813badb84ab9640a6a/docs/api/innrapportering-aksjonaerregisteroppgave.md
[dp-openapi-page]: https://docs.altinn.studio/en/dialogporten/reference/openapi/
[dp-spec]: https://platform.altinn.no/dialogporten/swagger/v1/swagger.json
[dp-search]: https://docs.altinn.studio/en/dialogporten/user-guides/searching-for-dialogs/
[dp-transmission]: https://docs.altinn.studio/en/dialogporten/reference/entities/transmission/
[dp-details]: https://docs.altinn.studio/en/dialogporten/user-guides/getting-dialog-details/
[dp-seen]: https://docs.altinn.studio/en/dialogporten/getting-started/seen-log/
[dp-lookup]: https://docs.altinn.studio/en/dialogporten/user-guides/looking-up-dialogs/
[dp-source]: https://github.com/Altinn/dialogporten/tree/1eb4fbbc91d0f9c8248160cbc0fc03306e83aa8e/src/Digdir.Domain.Dialogporten.Application/Features/V1/EndUser/Dialogs/Queries
[adapter]: https://github.com/kristianelmer/Tilli/blob/ee8b3bd7f83008116c95eb58e4455fb483d9bb0f/apps/backend/src/talli_backend/adapters/rf1086_authority.py
[dp-adapter]: https://github.com/kristianelmer/Tilli/blob/ee8b3bd7f83008116c95eb58e4455fb483d9bb0f/apps/backend/src/talli_backend/adapters/rf1086_dialogporten.py
[dispatch]: https://github.com/kristianelmer/Tilli/blob/ee8b3bd7f83008116c95eb58e4455fb483d9bb0f/apps/backend/src/talli_backend/modules/shareholder_register_filing/source_dispatch.py
[recovery]: https://github.com/kristianelmer/Tilli/blob/ee8b3bd7f83008116c95eb58e4455fb483d9bb0f/apps/backend/src/talli_backend/modules/shareholder_register_filing/source_recovery.py
