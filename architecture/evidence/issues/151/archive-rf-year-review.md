# RF archive source scope review

Read-only source review on 2026-09-09, during mutable #151 integration. No database, provider, browser or suite was run; no source edits. This confirms a receiver-scope regression and recommends a bounded correction, not a final #151 acceptance verdict.

## Confirmed blocker

`apps/web/app/archive/[companyId]/[incomeYear]/download/route.ts:69–78` requests all-year RF workspaces, and filters preview/simulation year only after full backend/HTTP decoding. `postgres_shareholder_register_filing.py:230–274` selects and decodes every year's preview. An unrelated 2024 RF preview with legal JSONB `issues = [{"level":"warning","message":"historical"}]` reaches `_wire_record`: `Rf1086ReadinessIssue(**issue)` raises for the missing `code`, preventing a valid 2025 archive.

This is a concretely admissible retained row, not hypothetical arbitrary table corruption: `0001_authenticated_workspace.sql:322–337` constrains JSONB presence but not its inner shape; the RF expand copies the existing shape via `LIKE ... INCLUDING ALL` and adds identity/label constraints only. Its `classify_legacy_row_v1` inspects filing/scope/parent identity, not this JSON payload, so it classifies the otherwise valid row as RF and preserves it. The retained row can also have `setup_id = null`, which was and remains legal. A simulation's incompletely shaped nested JSON similarly passes SQL but can fail the new typed response.

Pinned 91b original archive lines 284–287 and 322–326 selects simulations and previews by company AND requested year before reading payloads. The old company's comments and permissions remain company-wide without decoding another year's preview. Thus an invalid unrelated year previously did not block the valid requested year.

## Minimal correction

Add one named immutable RF archive query/result and generated read route. Required scope is verified actor + company + requested income year. Keep the existing workspace/list contract unchanged. The projection should contain exactly:

- Previews and simulations selected in SQL by requested company/year before DTO decoding.
- Review comments and permissions selected by company, preserving the original company-wide records and ordering.
- Test evidence selected only by IDs referenced by the selected `test_authority` simulations, with explicit company/RF obligation checks, preserving the original archive selection.

Do not include or decode unrelated overrides, approval manifests, production submissions or feedback artifact arrays: this receiver did not export them. Apply the same current membership/RLS and response scope/unique-ID validation; keep malformed selected-year data fail-closed. No raw JSON fallback, new writer, production feature, annual-readiness decision or relaxed supported-case rule is needed. The query can use the existing repeatable-read transaction and closed record converters; comments require company binding, not inclusion of their parent's preview payload in the returned snapshot.

The receiver continues its original generic sibling query expressions and effect order, replacing only its added RF workspace read with this exact projection. All source reads must finish before `company_archive_complete_export`.

## Required focused proof

Use an actual retained SQL fixture: valid 2025 snapshot/simulation plus a 2024 RF preview with the legal incomplete issue object (and a malformed nested 2024 simulation if useful). Show 2025 projection/export succeeds and retains the 2024 comment/company permission, while requesting 2024 still fails before export completion. Confirm selected-year test evidence is included, unreferenced evidence is excluded, and other-company rows never enter. Preserve original generic sibling call chains and timestamp/payload byte semantics. This review did not run that proof.

## Source hashes at review

```json
{
  "apps/web/app/archive/[companyId]/[incomeYear]/download/route.ts": "f70996b8065c1b1db4f7bd02d08bd3411d9c082935b1ad2938650dcf095b2cb1",
  "apps/backend/src/talli_backend/adapters/postgres_shareholder_register_filing.py": "2fba00024dbc46975df9bc7e8bdcddb6b5a0a196a4a0f2ccab71e2540a947629",
  "apps/backend/src/talli_backend/modules/shareholder_register_filing/preparation.py": "5b39c8c601da80ba3cab88eca1735836717bb408d01f60021592644dccc95141",
  "apps/backend/src/talli_backend/main.py": "ad5117873749ce22790b46de33ab919290c263205cf2c6a528c05a2522f3b36d",
  "supabase/migrations/0001_authenticated_workspace.sql": "efa28a79444eea498e526d26912f3bb3f60b044b1ab0209602296e9cee6ad0ca",
  "supabase/migrations/20260909190548_shareholder_register_filing_capability.sql": "979f4717d9810bd7f6ff6462c73e1a1cd61e2a01721538dc8b30534a02ee8f3b"
}
```
