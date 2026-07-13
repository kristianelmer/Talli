-- The service-role client is used only for operator provisioning and isolated
-- rehearsal cleanup. Keep its public-schema grants explicit instead of granting
-- it blanket access to every customer table.

grant usage on schema public to service_role;

grant select, insert, update, delete
on public.support_operators
to service_role;

grant select, delete
on public.launch_signoffs, public.launch_signoff_events, public.companies
to service_role;
