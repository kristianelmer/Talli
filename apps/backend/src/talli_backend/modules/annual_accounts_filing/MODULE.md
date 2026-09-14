# Annual Accounts Filing

<!-- architecture-inventory
{"dependencies":[],"ownedTables":[],"ports":[],"publicEntryPoints":["talli_backend.modules.annual_accounts_filing.public"]}
-->

## Purpose

Own the deterministic annual-accounts filing rules and RR0002 documents. Stage
#153 currently contains the pure calculation, XML and Accounts-specific readiness
slice. The legacy writer remains authoritative until the explicit database
cutover; this slice performs no persistence or provider operations.

## Owns and must not own

Accounts owns its ordered 21-field projection, feedback and deterministic XML.
Ledger owns the accounting entries. Corporate Governance and Documents own close
and signed-artifact facts. Annual owns common readiness aggregation and Billing
owns commercial eligibility and refunds. The named application workflow supplies
immutable source snapshots; the capability cannot discover other owners' tables.

## Public interface

Import only `talli_backend.modules.annual_accounts_filing.public`.
`AnnualAccountsSource` copies and recursively freezes Annual and ordered Ledger
facts. `build_annual_accounts` returns `AnnualAccountsCandidate`, whose notes,
fields and feedback are also recursively immutable. The candidate is a preview,
not an authorization, completeness attestation or evidence of authority acceptance.

`AnnualAccountsRenderInput` binds the candidate to organization, company name,
contact, approval date and confirming representative. `render_annual_accounts`
returns `AnnualAccountsDocuments`, preserving the released header, field/ORID,
blocking-code, contact, period, currency, integer and consistency validation
order. Invalid content raises the characterized `ValueError` message. Static XML
templates preserve original namespaces, element order, escaping and final newline.

`assess_annual_accounts_readiness` returns ordered `AnnualAccountsReadinessIssue`
values. `AnnualAccountsCorporateReadiness` carries the existing enabled flag and
Corporate-owned blockers. The pure contract does not certify their origin; the
durable filing workflow must obtain them through the owning public contracts.
General meeting approval, ledger scope, payload feedback and accepted/unaccepted
manual warnings retain their original order. Common Annual gates remain separate.

## Data and effects

No database tables, storage buckets, outbound ports or external effects are
activated by this slice. The canonical persistence/authorization boundary and
generated client are pending. The old direct RLS observations do not authorize
unaccepted membership or skipping fresh MFA in the future request boundary.

## Compatibility and failures

Live calculations retain ECMAScript binary64 reduction order, Number coercion,
half-up rounding toward positive infinity and signed zero. XML uses UTF-16 text
length, ECMAScript whitespace, safe whole integers and the Date.UTC year-0–99
rejection. These rules are local to the released Accounts profile, not shared
accounting policy or a dependency on Tax internals.

The offline public-data profile has distinct 22-field, Python-rounding,
account-coverage and attachment semantics. `AnnualAccountsOfflineSource` receives
the existing common Annual totals, common readiness issues and Accounts flags.
`build_annual_accounts_offline_payload`, `assess_annual_accounts_offline` and
`simulate_annual_accounts_offline` own the Accounts projection, attachment rules,
ordered Accounts blockers, preview and simulated receipt. The simulation returns
`AnnualAccountsOfflineSimulation`; all nested outputs are immutable. This profile
does not emit live XML or certify production readiness.

The existing root `holding_core.annual` public functions now adapt source/output
shapes to these contracts. Their Accounts-specific implementations are removed.
Common AnnualData totals, common readiness, Tax and Archive behavior remain byte
unchanged at the function/class definition level. These are existing common
source facts, not a second Accounts calculation or a new shared-kernel package.
The CLI remains a consumer of the same root public interface, preserving its
JSON, text, exit status and errors. Backend capability code never imports the
legacy root model.

## Tests

`apps/backend/tests/test_annual_accounts_filing.py` compares the public contracts
against immutable predecessor outputs: 67 payload cases, 175 exact XML/error cases,
11 readiness cases and nested immutability. The review follow-up includes deeply
nested ignored metadata and signed integer overflow probes. Architecture enforcement reconciles
the module manifest, documentation and language-aware dependency evidence.
`tests/test_annual_accounts_offline_migration.py` verifies 46 frozen root API cases
and 14 actual CLI executions against pre-migration output. Existing Annual, Tax
and Archive tests remain active. Evidence projection, provider-state relocation, generated workflow,
data migration/RLS/rollback and full stage-exit gates remain pending.
