-- Retain the required company-lock backstop and all immutable amendments.
-- Removing it would restore a direct-row-write bypass of the released guard.
-- This repair added no runtime authority or writer contract to withdraw.
begin;
commit;
