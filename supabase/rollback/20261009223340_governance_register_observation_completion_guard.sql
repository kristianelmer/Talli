-- Retain the final-write safety fence and its narrow public RF dependency.
-- Removing it would reopen old-backend stale admission and replay disclosure.
-- No stored evidence or event is changed by application rollback.
begin;
commit;
