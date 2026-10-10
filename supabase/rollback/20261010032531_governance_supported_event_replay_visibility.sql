-- Retain committed-event replay visibility and all historical rows. Restoring
-- FOR UPDATE would hide immutable rows under forced RLS and reopen the defect.
-- No runtime authority or stored evidence was added by this repair.
begin;
commit;
