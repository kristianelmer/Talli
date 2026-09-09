# RF archive-source independent backend review

Verdict: **no actionable finding in the reviewed backend slice**. Read-only review of the RF public archive query/snapshot, preparation service validation, archive unit cases, and only `PostgresShareholderRegisterFilingSession.archive_source`. Reviewer authored the web receiver and does not independently certify it here. No database, provider, hosted call, test execution or repository edit was performed for this review.

- The adapter binds actor identity to its verified session and uses repeatable-read plus the existing accepted-member assertion. It introduces no owner-only, fresh-MFA, paid-entitlement, current-year or consequential-action requirement for this read. Table read policies retain accepted-member visibility; the separate archive export keeps its original authorization/effect boundary.
- Previews and simulations are selected by exact company **and year in SQL before `_wire_record`**. Another year’s malformed optional-code preview or nested simulation payload is therefore not decoded. Production/approval/artifact collections are not read. Selected malformed preview construction is sanitized as unavailable; selected nested receipt response validation remains the API boundary’s responsibility. Root separately owns the API no-store correction; this review does not certify that correction.
- Comments and permissions remain company-wide. Comments do not join or decode their preview parent, so an older-year note survives even when that year’s preview is unusable. The service accepts that intended extent while enforcing RF target/obligation, company identity, typed records and unique IDs.
- Test evidence IDs derive only from the selected `test_authority` simulations. The SQL query applies those IDs, company and RF obligation; the service requires the exact referenced set. Simulations without such references do not cause a broad authority-evidence read. Unrelated evidence is never decoded; missing/misbound required evidence fails closed.
- The snapshot remains immutable and preserves the original nested simulation values. Existing all-history workspace behavior is unchanged. The 28 provided archive unit cases cover typed scope, exact company/year, obligation/target, duplicate/untyped rows, missing/excess evidence, simulation-mode filtering, company-wide comments, empty-year results and original nested payload identity. They are service-level cases; actual SQL/RLS/lifecycle verification remains B’s separate evidence.

Review scope is the approved behavior-preserving archive receiver handoff, not complete #151 acceptance or a new submission-history completeness claim.

## Reviewed source digests

- `apps/backend/src/talli_backend/modules/shareholder_register_filing/public.py`: `a9c0c54763ec7311d03b2370b961a6509ed6927ff157a28a252cbf0daee6a674`
- `apps/backend/src/talli_backend/modules/shareholder_register_filing/preparation.py`: `08961239e7377613f0683246f013f2ba7535f87827f8ad117a5862190f6ca7de`
- `apps/backend/src/talli_backend/adapters/postgres_shareholder_register_filing.py`: `bc061d7ba670dbb5ffca303464c4a71c3be5673adbb82de9d424ddbe58349f99`
- `apps/backend/tests/test_rf1086_archive_source.py`: `e0367f487269b294f5f96f40f7c5e9f98c7e5952696caf00b6e705dca06557b4`

The adapter method body alone (from `async def archive_source` through its return) has SHA256 `7cc146f2e334334d7dd8c32eb3d6bad53d403ab78f141460f61931ad780d269d`; other adapter methods were outside this bounded review.

## Separate root-requested adjacent validation characterization

After completing the backend archive-only review, root requested that any concrete adjacent selected-workspace validation gap be flagged. One local fake-session request reproduced it: the existing original simulation oracle, with selected `receipt_metadata` replaced by an invalid object, reaches `main.py:10079–10084` workspace wire construction outside the archive-specific `ValidationError` translation. The response is sanitized `500 INTERNAL_SERVER_ERROR`, but has no `Cache-Control` header. The synthetic receipt marker is not exposed. This is separate from the reviewed archive-source service/adapter, which has no additional finding.

Reproduction: `/tmp/talli-151-workspace-validation-repro.py`; observed response `/tmp/talli-151-workspace-validation-repro.json`. Exactly one in-process TestClient request using the existing fake session was run, with no database/provider/hosted calls. Root was sent the bounded suggestion to handle this workspace output-validation failure as unavailable503/no-store. No general main.py review or source edit was performed.

### Adjacent workspace finding closed

Independently re-read the narrow correction: only workspace output DTO construction is wrapped in `except ValidationError`, translated to the existing RF dependency-unavailable error. Workflow/query execution is outside that catch, so this does not hide unrelated application failures or weaken row guards. The regression now covers archive-source and workspace; the supplied red log confirms the original workspace500.

One replay of the original local fake-session request now returns **503 `SHAREHOLDER_REGISTER_FILING_DEPENDENCY_UNAVAILABLE`**, `Cache-Control: no-store`, the original correlation ID and no synthetic receipt contents. No suite, DB, provider or hosted calls were run. Closure evidence is `/tmp/talli-151-workspace-validation-correction.json`; exact file and handler hashes are in `/tmp/talli-151-workspace-validation-correction-review.json`. This closes the bounded finding only and grants no browser, database-lifecycle or complete RF-flow credit.
