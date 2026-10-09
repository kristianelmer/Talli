-- Retain this staged public assertion and its closed consumer grants. A later
-- owner migration may depend on it; deleting it would break that dependency.
-- No Ledger evidence or existing posting/recovery routine is changed.
begin;
commit;
