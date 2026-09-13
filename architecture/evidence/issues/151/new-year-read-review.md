# Independent new-year read composition review

Reviewed `/tmp/talli-151-new-year-read-port.sql` SHA-256 `b2d5fff95ec1d0d9719888fd1208b71c75aed47fca1a2a479b880fdb24c587e9` against `backend_system.list_opening_snapshots_legacy_v1` in `supabase/migrations/20260827100000_ledger_capability.sql:1082` and the current published RF/Ledger SQL read ports. Source-only review; no database, browser, provider or hosted operations.

## Actionable finding

**Conflicting retained shareholder evidence can disappear into a successful opening projection.** Draft lines 166–175 consumes only `shareholder_register_filing.read_opening_shareholders_v1`. The current RF port (`20260909190548_shareholder_register_filing_capability.sql:1983–1988`, line numbers may shift during integration) returns canonical rows only; expand lines 228–234 omit quarantined shareholders from that table. Neither checks retained quarantine rows whose `original_row.setup_id` points to the requested setup.

Concrete source-derived regression: an actor is an accepted member of companies A and B. A has an otherwise valid 100-share opening and its proper A shareholder holds 100 shares. A second original shareholder has `company_id=B`, `setup_id=A's setup`, and zero shares. This state is permitted by predecessor independent foreign keys and the `share_count >= 0` constraint (`0001_authenticated_workspace.sql:233–243`). The original Ledger read aggregates both visible shareholders by setup ID; the original `LegacyOpeningSnapshotView` at pinned `91b178c2` rejects the foreign-company row. Migration correctly quarantines that conflicting row, but the new RF read returns only the valid A holder; the new projection succeeds, concealing retained conflicting evidence.

Keep the conflict quarantined. Make the RF-owned read port refuse the affected setup/company-year while linked quarantined shareholder evidence remains, or publish a narrow completeness result checked by this composition. Do not expose B's identity or raw evidence. Add a lifecycle regression with an actor accepted in both companies; do not infer company/year solely from the quarantine row's own company because the conflicting row belongs to B and has no income_year field.

## Preserved source behavior

- Actor/verified-subject validation, company-list cardinality/duplicate/null checks, page bounds, company hash, cursor signature/resource/age decoding are byte-identical through the cursor block (confirmed by local text comparison).
- Materialized accepted-member filtering precedes owner-port invocation; mixed hidden companies remain filtered. Current RF/Ledger ports recheck verified identity and membership.
- Descending `(created_at,id)` ordering, exclusive cursor boundary, `limit+1`, final-item cursor, and empty-page behavior agree with the original.
- Bank facts join by exact snapshot/company/year and check original recorder/time; missing or conflicting bank facts fail unavailable. Money stays PostgreSQL numeric → text, with the original cent-precision check for only returned page rows.
- Holder ordering and 101-row sentinel preserve the original 100-holder bound. Existing application models preserve sum/company/setup consistency.
- Explicit no-PUBLIC/authenticated/service-role execution and dedicated workflow execution remain in the draft.

This is a bounded source-review finding, not a full runtime verdict. B owns the final migration integration and database proof.
