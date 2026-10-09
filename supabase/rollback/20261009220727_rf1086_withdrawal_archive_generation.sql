-- Application rollback preserves archive-generation invalidation. Removing the
-- trigger could make older receipts current after a retained withdrawal.
-- Empty disposable topology teardown removes it with its RF-owned table.
begin;
commit;
