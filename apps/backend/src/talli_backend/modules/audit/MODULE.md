# Audit contract shell

`AuditEventDraft` and `AuditInclusion` declare the target append contract for the exact existing Audit inclusion in the Company Tax TT02 evidence import. The named application workflow calls it only when the idempotent import creates rows, inside the same Postgres transaction. Failure aborts the import; replay neither rewrites attribution nor appends another event.

This is the not-yet-migrated dependency allowance from #132. `public.audit_events` remains the single canonical legacy store. No Audit table, retention, ordering rule, query, existing producer or stage completion moves here. The legacy implementation is bound through `PostgresCompanyTaxTransaction`; #155 replaces that implementation at the Audit stage. This shell does not alter any frozen web compatibility tuple.

<!-- architecture-inventory
{"dependencies":[],"ownedTables":[],"ports":["AuditInclusion"],"publicEntryPoints":["talli_backend.modules.audit.public"]}
-->

`audit_inclusion_adapter` registers the declared adapter implementation without adding runtime policy.
