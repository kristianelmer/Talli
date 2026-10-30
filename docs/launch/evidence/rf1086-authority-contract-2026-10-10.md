# RF-1086 authority contract — 2026-10-10

Status: public-source contract review; no launch or filing authorization.

Verified: 2026-10-10 UTC. Repository baseline: `48b428507975ec65a602a847d709d149d0eb5001`, branch `codex/talli-release-integration`. Implementation statements below concern the cited files at that SHA, not concurrent uncommitted approval work. No tests, CI, authentication, provider submissions, deployments, or paid services were run. Only this note was written.

## Version finding

The [official SwaggerHub registry][registry], read on 2026-10-10, selects **1.2.0** as its default and marks it published; its created/modified timestamp is **2026-08-25T14:46:24Z**. It also exposes **1.3.0**, created/modified **2026-10-05T11:05:13Z**, but marks it **unpublished**. The October date is therefore verified as draft metadata, not evidence of a production release. Registry response SHA-256: `c0aa464e7c1c20574f915d35241141e37d0b6887849783c3561a03aaa8778dfd`.

The fetched [1.2.0 OpenAPI][oas12] SHA-256 is `1dc44e55fd993872e1cfd30fdbe59bd2f612e8e34de6d3e4c5dfdf34ab022947`; [1.3.0][oas13] is `72130ca86eea830e58ca383c97156ee479c70fca99af065bbe964910f9c9ba50`. A sorted structural JSON comparison found only `info.version` and addition of `UNDER_BEHANDLING` to `PrefillPage.oppgaveStatus`; 1.2.0 allows `AVVIST` and `GODKJENT`. Filing routes, parameters, responses, and servers are identical. Both use URL major version `/v1`; specification version 1.3.0 does not imply a `/v1.3` route. [Sources: OpenAPI 1.2.0][oas12], [draft 1.3.0][oas13].

The [official RF documentation source][prose] was last changed in commit `02072fe49d98fafda31fd7813badb84ab9640a6a`, dated **2026-08-26T08:01:05Z** in the [file history][history]. Its front matter still says December 19, 2024. Use the source revision and registry metadata instead of that stale date. It says five endpoints but enumerates six, including prefill. [Source revision][prose], [history][history].

## Published routes versus implementation

All official entries below are from **OpenAPI 1.2.0**, verified 2026-10-10. Its servers are `https://api-test.sits.no/api/aksjonaerregister/v1` and `https://api.skatteetaten.no/api/aksjonaerregister/v1/`. Talli's [adapter at the baseline SHA][adapter] uses those hosts and the following relative routes. [Official specification][oas12].

| Operation | Published contract | Baseline implementation / assessment |
| --- | --- | --- |
| Main | `POST /{inntektsaar}/1086H`; XML body; required UUID `idempotencyKey` header; HTTP 200 JSON `hovedskjemaId` UUID | Same route/header/body; additionally tolerates lowercase `hovedskjemaid`, matching the prose example. |
| Child | `POST /{inntektsaar}/{hovedskjemareferanse}/1086U`; XML body; required UUID key; HTTP 200 without response content | Same route and main UUID reference; ignores successful body and accepts other 2xx, including 204. |
| Confirm | `POST /{inntektsaar}/{hovedskjemareferanse}/bekreft?antall_underskjema=N`; HTTP 200 JSON delivery reference, `dialogId`, `forsendelseId` | Same route/count; sends a UUID key even though this operation omits that header in OpenAPI; requires both UUID references. |
| Archive page | `GET /{inntektsaar}/forsendelser/{forsendelseid}/dokumenter`; zero-based page; size 1–50, default 10; JSON pagination and inline XML strings | Sends explicit size 50. Also tolerates narrow document-reference objects beyond the declared string schema. |
| Document | `GET /{inntektsaar}/forsendelser/{forsendelseId}/dokumenter/{dokumentId}`; binary JSON/XML/PDF/CSV responses | Route matches. Media allowlist excludes declared `application/json` and `text/csv`, while adding `text/xml`, `text/plain`, and `application/octet-stream`. |
| Prefill | `GET /prefill/{inntektsaar}/{organisasjonsnummer}?page=N`; JSON `PrefillPage` | No method in the five-operation adapter. This is a missing read capability, not a specified prerequisite for the POST sequence. |

Table sources: [published OpenAPI 1.2.0][oas12], [official prose revision dated 2026-08-26][prose], [adapter][adapter], [adapter tests][adapter-tests], all read 2026-10-10. The tests are mocked characterization evidence and were not executed in this review.

The MIME difference concerns **downloaded document responses**. The filing adapter emits `application/xml` for main/child requests; generic port inputs do not establish a different emitted request type. Restricting downloaded feedback to XML/PDF may be an intentional supported-scope subset. Excluded optional JSON/CSV responses alone do not establish a broken filing flow; evidence is needed that every document required by the supported flow uses an admitted type. Likewise, confirmation's extra key header is not shown to be rejected by the provider. [Adapter][adapter], [feedback acquisition][dialog-feedback], baseline SHA; [OpenAPI 1.2.0][oas12], reviewed 2026-10-10.

## Identities, retries, and unknown outcomes

The official prose requires a fresh UUID for each new call and states that repeated POSTs with the same body/key return the original response. It specifies `GLD_019`/409 for a previously used key. Neither the reviewed prose nor either specification supplies key retention duration, simultaneous duplicate-call guarantees, or a lookup-by-key recovery route. **Unresolved:** confirmation's omitted OpenAPI header conflicts with that broad prose wording; sending a header does not prove that confirm deduplication is enforced. [Official prose, source revision dated 2026-08-26][prose]; [OpenAPI 1.2.0][oas12], [draft 1.3.0][oas13].

Talli sends main first, each child sequentially against the persisted main reference, then confirms the actual child count. Each logical mutation gets its own persisted key/body hash; allowed retries preserve the key. Confirmation's local operation hash covers main ID and count even though its HTTP body is empty. The execution journal retains `dialogId`/`forsendelseId`; the adapter returns the delivery reference but the journaled executor does not retain it there. These are implementation choices, not authority guarantees. [Baseline executor][executor], [durable journal][durable-journal], [operation SQL][operation-sql].

The durable source path permits I/O only after a newly committed intent. Existing prepared/unknown events stop replay; generic response/persistence errors become unknown. SQL locks the submission while preparing an intent, checks predecessor success and payload identity, preserves retry keys, and rejects cross-operation key reuse. Locks do not span provider I/O. Local competing dispatch tests check that only one main call proceeds; this establishes Talli's intended admission behavior, not provider concurrency semantics. [Durable journal][durable-journal], [operation SQL][operation-sql], [execution tests][execution-tests], baseline SHA, reviewed 2026-10-10.

The adapter makes one request, disables redirects, and classifies network/timeout/redirect failures as unknown network errors without replay. Recovery's authority interface exposes only archive-list and document-read methods. Successful HTTP status or confirmation references alone do not become final acceptance in Talli: reconciliation classifies retained feedback, checks related identities, and keeps missing/conflicting/unrecognized evidence in processing, unknown, or action-required states. [Adapter][adapter], [feedback][feedback], [dialog feedback][dialog-feedback], baseline SHA, reviewed 2026-10-10. These are local safety policies; the RF OpenAPI defines transport references, not Talli's acceptance classification. [OpenAPI 1.2.0][oas12].

The documented TT02 run on **2026-07-14**, against code `1d06b06`, observed an initial `GLD_021 / GLD_1017` archive miss followed by retrieval of two submitted XML documents. That is historical test evidence, not a published eventual-consistency SLA or proof of current full-year acceptance. Official prose specifies `GLD_021` as 404 but does not list `GLD_1017`. [Dated local TT02 evidence][tt02], [official prose revision dated 2026-08-26][prose].

## Required contract/regression follow-up

These are proposed checks, not completed results:

1. Pin the published 1.2.0 JSON/hash and registry publication metadata; rerun a structural diff when the default or publication flag changes. Keep draft 1.3.0's prefill status as a watch item. [Registry][registry], [1.2.0][oas12], [draft 1.3.0][oas13].
2. Add an official-shape fixture using main HTTP 200 with `hovedskjemaId`, child empty HTTP 200, inline XML archive strings, integer pagination, and distinct keys per operation. Existing adapter tests' combined route test uses main 201, child 204, and a document-reference object; those test tolerated shapes rather than the complete published happy path. [1.2.0][oas12], [baseline adapter tests][adapter-tests].
3. Resolve/record confirmation idempotency explicitly with authoritative clarification or a separately authorized synthetic contract exercise: same path/count/key, response loss, then same-key retry. Check changed count/path under the same key and duplicate 409 behavior. Preserve the current unknown-outcome stop until behavior is evidenced. The reviewed sources alone cannot settle this. [Prose][prose], [1.2.0][oas12], [durable journal][durable-journal].
4. Decide the document media policy explicitly: support the declared JSON/CSV originals, or document that the product only retrieves XML/PDF receipt artifacts and treats other declared types as unsupported. Test retention before classification; adding a MIME type must not make its bytes prove acceptance. [1.2.0][oas12], [adapter][adapter], [dialog feedback][dialog-feedback].
5. Retain checks for competing dispatch, crash after intent/before I/O, provider effect followed by response loss, outcome-write failure, same-key retry after a new grant, blocked stale retry, complete pagination, mismatched references, conflicting feedback, and no POST through recovery. Existing source files contain tests for these boundaries; their current execution status is outside this review. [Execution tests][execution-tests], [pagination tests][pagination-tests], [feedback tests][feedback-tests], [adapter tests][adapter-tests].
6. If prefill is added, treat it as separately sourced previous-year input and never as final acceptance of the current filing; test the published `AVVIST`/`GODKJENT` enum and fail closed on unexpected statuses. The draft's new enum alone does not authorize treating `UNDER_BEHANDLING` as accepted. [1.2.0][oas12], [draft 1.3.0][oas13], [prose][prose].

## Access and schema evidence limits

The RF prose requires Maskinporten scope `skatteetaten:innrapporteringaksjonaerregisteroppgave` and Systembruker; standard Systembruker may use the single right `ske-innrapportering-aksjonaerregisteroppgave`. A registered vendor system is not customer approval or filing authorization. [RF prose revision dated 2026-08-26][prose], [official Systembruker guide, read 2026-10-10][systemuser].

At official documentation repository HEAD `82c52dcb686cfd0eab74907096335cccd3f3e4ad` (**2026-10-05T11:24:02Z**), the fetched main XSD, child XSD, and class code-list hashes still match Talli's 2026-09-17 pins: `194670070a54772ad7e026e37be1d87e7840dab7621c966a881e909d00d119df`, `a0f6b2a8d249f3f40290036314d3b1f5c1b3aed3ba90f58e5ce7b264c9ec33b7`, and `a50b180de6b6538853eff7087df609e4f54132405e6057fdf8914b1a9f162ffd`. Matching bytes prove schema/code-list provenance, not event semantics, acceptance, production readiness, or tax correctness. [Official revision][official-head], [main XSD][main-xsd], [child XSD][child-xsd], [code list][class-list], [Talli source register][source-register].

This read-only review does not establish the deployed provider version, live full-year acceptance, simultaneous duplicate-request behavior, idempotency expiry, confirmation replay behavior, or a regulatory/product promise. Those remain evidence questions.

[registry]: https://api.swaggerhub.com/apis/skatteetaten/innrapportering-aksjonaerregister-api
[oas12]: https://api.swaggerhub.com/apis/skatteetaten/innrapportering-aksjonaerregister-api/1.2.0
[oas13]: https://api.swaggerhub.com/apis/skatteetaten/innrapportering-aksjonaerregister-api/1.3.0
[prose]: https://github.com/Skatteetaten/api-dokumentasjon/blob/02072fe49d98fafda31fd7813badb84ab9640a6a/docs/api/innrapportering-aksjonaerregisteroppgave.md
[history]: https://api.github.com/repos/Skatteetaten/api-dokumentasjon/commits?path=docs/api/innrapportering-aksjonaerregisteroppgave.md&per_page=10
[systemuser]: https://skatteetaten.github.io/api-dokumentasjon/om/systembruker
[official-head]: https://github.com/Skatteetaten/api-dokumentasjon/commit/82c52dcb686cfd0eab74907096335cccd3f3e4ad
[main-xsd]: https://raw.githubusercontent.com/Skatteetaten/api-dokumentasjon/82c52dcb686cfd0eab74907096335cccd3f3e4ad/static/download/aksjonaerregisteroppgaveHovedskjema.xsd
[child-xsd]: https://raw.githubusercontent.com/Skatteetaten/api-dokumentasjon/82c52dcb686cfd0eab74907096335cccd3f3e4ad/static/download/aksjonaerregisteroppgaveUnderskjema.xsd
[class-list]: https://raw.githubusercontent.com/Skatteetaten/api-dokumentasjon/82c52dcb686cfd0eab74907096335cccd3f3e4ad/static/download/aksjeklasse_kodeliste.xml
[adapter]: https://github.com/kristianelmer/Tilli/blob/48b428507975ec65a602a847d709d149d0eb5001/apps/backend/src/talli_backend/adapters/rf1086_authority.py
[adapter-tests]: https://github.com/kristianelmer/Tilli/blob/48b428507975ec65a602a847d709d149d0eb5001/apps/backend/tests/test_rf1086_authority.py
[executor]: https://github.com/kristianelmer/Tilli/blob/48b428507975ec65a602a847d709d149d0eb5001/apps/backend/src/talli_backend/modules/shareholder_register_filing/production.py
[durable-journal]: https://github.com/kristianelmer/Tilli/blob/48b428507975ec65a602a847d709d149d0eb5001/apps/backend/src/talli_backend/modules/shareholder_register_filing/source_dispatch_execution.py
[operation-sql]: https://github.com/kristianelmer/Tilli/blob/48b428507975ec65a602a847d709d149d0eb5001/supabase/migrations/20260929182856_rf1086_durable_source_operation_intent.sql
[execution-tests]: https://github.com/kristianelmer/Tilli/blob/48b428507975ec65a602a847d709d149d0eb5001/apps/backend/tests/test_rf1086_source_dispatch_execution.py
[feedback]: https://github.com/kristianelmer/Tilli/blob/48b428507975ec65a602a847d709d149d0eb5001/apps/backend/src/talli_backend/modules/shareholder_register_filing/feedback.py
[dialog-feedback]: https://github.com/kristianelmer/Tilli/blob/48b428507975ec65a602a847d709d149d0eb5001/apps/backend/src/talli_backend/modules/shareholder_register_filing/dialog_feedback.py
[pagination-tests]: https://github.com/kristianelmer/Tilli/blob/48b428507975ec65a602a847d709d149d0eb5001/apps/backend/tests/test_rf1086_feedback_pagination.py
[feedback-tests]: https://github.com/kristianelmer/Tilli/blob/48b428507975ec65a602a847d709d149d0eb5001/apps/backend/tests/test_rf1086_dialog_feedback.py
[tt02]: https://github.com/kristianelmer/Tilli/blob/48b428507975ec65a602a847d709d149d0eb5001/docs/filing/evidence/rf1086-tt02-2026-07-14.md
[source-register]: https://github.com/kristianelmer/Tilli/blob/48b428507975ec65a602a847d709d149d0eb5001/docs/filing/rf1086-official-sources.json
