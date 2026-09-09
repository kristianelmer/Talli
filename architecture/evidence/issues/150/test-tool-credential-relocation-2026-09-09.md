# #150 remaining standalone test-tool credential consumers

Status: **implemented locally; independent review corrections and final stage gates in progress**. Kristian explicitly approved this reviewed proposal on 9 September 2026 with **“Approve the exact relocation”**. This is a separate approval from the two-coordinator RF amendment.
Source: `b30312de11ad942479421def243e4a2252fbf166` and the current #150 branch.

#150 requires retiring TypeScript authority credential paths. The approved RF relocation explicitly excludes the token-smoke command and the three separate authority test scripts (binding scope, item 5). Their remaining imports prevent deleting `apps/web/app/lib/maskinporten.ts` even after the web cutover. None is an ordinary customer action or a registered business-persistence tuple.

## Proposed exact change

Relocate the four existing standalone commands to backend-only Python entrypoints while preserving their current command names, local input/evidence files, approved-write switches, environment restrictions, fixed provider endpoints, operation ordering and explicit human handoffs. Keep the three filing harnesses as frozen compatibility tools owned by their respective filing stages. #151/#152/#153 absorb or retire them; this work does not start those capability migrations.

| Existing entrypoint | Destination, invoked through its existing npm command |
|---|---|
| `scripts/maskinporten-token-smoke.mjs` | `apps/backend/src/talli_backend/authority_tools/token_smoke.py` |
| `scripts/rf1086-authority-test.mjs` | `apps/backend/src/talli_backend/authority_tools/rf1086_test.py` |
| `scripts/company-tax-return-authority-test.mjs` | `apps/backend/src/talli_backend/authority_tools/company_tax_test.py` |
| `scripts/annual-accounts-authority-test.mjs` | `apps/backend/src/talli_backend/authority_tools/annual_accounts_test.py` |

The isolated CLI-only grant helper is physically located at
`apps/backend/src/talli_backend/authority_tools/_grant.py`. It is shared only by
these four standalone commands; the Authority Connections provider port retains
its separate four-scope allowlist and required original RF external reference.
The private `_shareholder_write_order` function inside `authority_tools/rf1086_test.py`
uses one fixed JSON-only Node `localeCompare` expression to preserve the original
subdocument order, including mixed-case and non-ASCII identifiers. It receives only
the identifier list and normal runtime/locale environment, with no provider
credentials or `NODE_OPTIONS`; it has no caller-selected code, module or path.
Filename/hash/UUID-key ordering separately preserves JavaScript's default UTF-16
sort and integer object-key ordering. This helper does not generate or change XML.

The two filing tools share only the private implementation helper `apps/backend/src/talli_backend/authority_tools/_filing.py` for bounded HTTP responses, atomic local evidence and the fixed credential-free payload subprocess. It is not a public port or generic proxy.

The backend alone reads the existing private-key file, checks its restrictive permissions, signs grants, exchanges tokens and makes authority calls. The token-smoke command keeps its existing explicitly selected test/production environment, configured scope, required System User organization, and optional external reference. Its CLI-only grant helper retains the existing System User RAR behavior; it does not widen the web provider port’s four-scope allowlist or weaken that port’s required original external reference. The token-smoke command returns only its existing redacted token summary (`environment`, `scope`, `tokenType`, `expiresIn`, `accessTokenPresent`); no grant, private key or bearer reaches stdout, evidence or web. No HTTP endpoint, generic proxy, arbitrary URL/method contract, browser credential flow or new database resource is added.

The three test scripts keep their existing fixed test-environment gates and remain off without their exact approved-test-write environment switches. Test-tool implementation is not approval to run them against a provider. Existing evidence files and original resumed test intent remain intact. Local XML generation/validation keeps the existing `holding_cli` and existing TypeScript pure statutory generators, invoked only to produce the same XML bytes; those generators receive no credentials and their policy is not migrated here.

## Fixed transitive transport scope

- The shared RF transport has the five already reviewed `rf1086-authority-client.ts` methods through `adapters/rf1086_authority.py`: main XML, subdocument XML, confirmation, list documents, get document. The existing test harness calls only main XML, subdocument XML, confirmation and list documents; it hashes embedded document entries as its source currently does. Do not silently add `getDocument` downloads or new acceptance policy. Its archive polling, exact UUIDs/hash/evidence continuation and supported formation/no-activity limit remain unchanged.
- Annual accounts relocates `exchangeMaskinportenForAnnualAccountsAltinnToken` (the fixed existing Altinn GET exchange) and existing transport methods from `annual-accounts-authority-client.ts`: `createInstance`, `uploadMainForm`, `uploadCompanyAccounts`, `validateInstance`, `lockForSigning`, `getSigningHandoff`, `getSubmissionEvidence`. Preserve the current refusal of production transport, attachment identities, task/state readback and person-signing handoff. Frozen helper destination: `authority_tools/annual_accounts_transport.py`.
- Company tax relocates `exchangeMaskinportenForAltinnToken` (the fixed existing Altinn GET exchange) and current transport methods from `company-tax-return-authority-client.ts`: `fetchCurrent`, `validateTest`, `createInstance`, `uploadEnvelope`, `replaceEnvelope`, `getEnvelopeScan`, `getInstance`, `advanceToConfirmation`, `getFeedbackReceipt`, `startValidation`, `getValidationStatus`, `getValidationResult`, plus its pure owner-confirmation URL construction. Preserve supported modes, existing original-instance/data identifiers, scan/validation/readback/feedback evidence and owner confirmation. Frozen helper destination: `authority_tools/company_tax_transport.py`.
- The exact existing account scope is `altinn:instances.read altinn:instances.write`; tax uses those plus `skatteetaten:formueinntekt/skattemelding`; RF uses `skatteetaten:innrapporteringaksjonaerregisteroppgave`. Any necessary backend grant helper extension is private to these fixed CLI workflows and must not widen the web-facing Authority Connections provider port.
- Extract only `renderCompanyTaxReturnEnvelope`, `renderCompanyTaxReturnValidationEnvelope`, `summarizeCompanyTaxReturnValidation` and their current pure helpers/types from the credential-bearing tax client into `apps/web/app/lib/company-tax-return-authority-payload.ts` before deleting that client. A fixed JSON/XML-only subprocess entrypoint, `scripts/authority-tool-payload.mjs`, calls the unchanged current pure annual/tax generators; no credential is provided to it and no arbitrary code/module/path dispatch is accepted.
- Existing TypeScript helpers that generate statutory XML or classify filing evidence stay with their frozen filing owners. Credential-bearing transport implementations and callers are removed after equivalent local coverage. Historical evidence is preserved as historical evidence.

## Review and acceptance

Before removal, characterize exact source behavior and compare generated bytes, request sequences, original evidence continuation, redacted diagnostics, environment/write gates, actual timeout behavior and human handoffs using local fixtures. The RF helper already has response caps and redirect refusal; the annual/tax helpers currently have 20-second default timeouts (the earlier 15-second description was a transcription error; both source `validTimeout` functions use 20,000 ms) but lack explicit response-byte caps and redirect refusal. Record that difference honestly; preserve accepted payload semantics and add bounded response/redirect safeguards with dedicated characterization for any behavior change. Add secret-reflection tests and safe bounded replacements for upstream error descriptions rather than exposing returned private material. Register successor tests in the existing mandatory commands. Independently review the exact transport/helper diff; #150 still needs its full migration/rollback/browser envelope and two immutable complete gates.

This amendment permits only the enumerated standalone credential relocation. It does not permit other future registry deletions, filing table/schema migration, new filing functionality, actual test or production submissions, provider activation, spending, or production promotion.

Independent review: bounded source audit completed on 9 September 2026. This version incorporates corrections for the standalone grant semantics, both exchange helpers, RF embedded archive entries, pure tax helper retention, exact redacted token summary and actual existing transport bounds.
