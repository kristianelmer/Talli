-- Keep staged read/assertion contracts and their closed runtime grants. Removing
-- them could break a later owner migration's explicit public SQL dependency.
-- No evidence, historical API or business behavior is rewritten by rollback.
begin;
commit;
