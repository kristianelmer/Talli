-- Application rollback preserves archive invalidation and retained evidence.
-- Removing these triggers could make old export receipts appear current.
-- Empty disposable topology teardown removes triggers with their owning tables.
begin;
commit;
