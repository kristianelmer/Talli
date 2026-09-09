-- Apply only after generated technical signoff transport replaces web persistence.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
do $guard$ begin
  if pg_catalog.to_regprocedure('backend_system.record_launch_signoff_v1(text,text,text,timestamptz,text,text)') is null
    or pg_catalog.to_regprocedure('backend_system.list_launch_signoffs_v1()') is null
  then raise exception 'launch_signoff_backend_cutover_required'; end if;
end $guard$;
revoke select,insert,update on public.launch_signoffs from authenticated;
drop policy "active operators can read launch signoffs" on public.launch_signoffs;
drop policy "admin operators can create launch signoffs" on public.launch_signoffs;
drop policy "admin operators can update launch signoffs" on public.launch_signoffs;
commit;
