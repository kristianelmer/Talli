-- BOUNDED ROLLBACK ARTIFACT: #190 authority cleanup.
-- Temporary migration authority is never restored during rollback.

begin;
commit;
