-- Backend-system technical signoff transport. No filing/release policy changes.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
do $roles$
begin
  if not exists(select 1 from pg_catalog.pg_roles where rolname='launch_signoff_store_owner') then
    create role launch_signoff_store_owner nologin noinherit nobypassrls;
  end if;
  if not exists(select 1 from pg_catalog.pg_roles where rolname='launch_signoff_executor') then
    create role launch_signoff_executor nologin noinherit nobypassrls;
  end if;
  perform pg_catalog.set_config('talli.launch_signoff_schema_membership_added',
    (not pg_catalog.pg_has_role(current_user,'ledger_store_owner','USAGE'))::text,true);
  if pg_catalog.current_setting('talli.launch_signoff_schema_membership_added')='true' then
    execute pg_catalog.format('grant ledger_store_owner to %I',current_user);
  end if;
  execute pg_catalog.format('grant launch_signoff_store_owner, launch_signoff_executor to %I',current_user);
end $roles$;
grant usage on schema backend_system, public to launch_signoff_store_owner, launch_signoff_executor;
grant create on schema backend_system to launch_signoff_store_owner;
grant execute on function public.company_access_auth_uid_v1(),public.company_access_auth_jwt_v1(),
  public.company_access_is_active_admin_v1(),public.company_access_is_active_operator_v1()
to launch_signoff_store_owner;
grant select,insert,update on public.launch_signoffs to launch_signoff_store_owner;

create function backend_system.assert_launch_signoff_operator_v1(p_admin boolean)
returns uuid language plpgsql security definer set search_path='' as $function$
declare
  v_actor uuid:=nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid;
  v_claims jsonb:=nullif(pg_catalog.current_setting('talli.verified_actor_claims',true),'')::jsonb;
begin
  if v_actor is null or v_claims->>'sub' is distinct from v_actor::text
    or v_claims->>'role' is distinct from 'authenticated'
    or public.company_access_auth_uid_v1() is distinct from v_actor
    or not public.company_access_is_active_operator_v1()
    or (p_admin and not public.company_access_is_active_admin_v1())
  then raise exception 'launch_signoff_operator_required'; end if;
  return v_actor;
end $function$;

create policy backend_launch_signoff_read on public.launch_signoffs
for select to launch_signoff_store_owner
using (backend_system.assert_launch_signoff_operator_v1(false) is not null);
create policy backend_launch_signoff_insert on public.launch_signoffs
for insert to launch_signoff_store_owner
with check (recorded_by=backend_system.assert_launch_signoff_operator_v1(true));
create policy backend_launch_signoff_update on public.launch_signoffs
for update to launch_signoff_store_owner
using (backend_system.assert_launch_signoff_operator_v1(true) is not null)
with check (recorded_by=backend_system.assert_launch_signoff_operator_v1(true));

create function backend_system.list_launch_signoffs_v1()
returns setof public.launch_signoffs language plpgsql security definer set search_path='' as $function$
begin
  perform backend_system.assert_launch_signoff_operator_v1(false);
  return query select * from public.launch_signoffs order by updated_at desc;
  perform backend_system.assert_launch_signoff_operator_v1(false);
end $function$;

create function backend_system.record_launch_signoff_v1(
  p_key text,p_status text,p_reviewer text,p_reviewed_at timestamptz,p_evidence_link text,p_decision text
) returns setof public.launch_signoffs language plpgsql security definer set search_path='' as $function$
declare
  v_actor uuid:=backend_system.assert_launch_signoff_operator_v1(true);
  v_result public.launch_signoffs%rowtype;
begin
  if p_reviewed_at is null or p_reviewed_at>pg_catalog.clock_timestamp()
    or p_reviewer is null or p_evidence_link is null or p_decision is null
    or (p_status='approved' and (pg_catalog.btrim(p_reviewer)='' or pg_catalog.btrim(p_evidence_link)='' or pg_catalog.btrim(p_decision)=''))
  then raise exception 'launch_signoff_invalid'; end if;
  insert into public.launch_signoffs(key,status,reviewer,reviewed_at,evidence_link,decision,recorded_by,updated_at)
  values(p_key,p_status,pg_catalog.btrim(p_reviewer),p_reviewed_at,pg_catalog.btrim(p_evidence_link),pg_catalog.btrim(p_decision),v_actor,pg_catalog.clock_timestamp())
  on conflict(key) do update set status=excluded.status,reviewer=excluded.reviewer,reviewed_at=excluded.reviewed_at,
    evidence_link=excluded.evidence_link,decision=excluded.decision,recorded_by=excluded.recorded_by,updated_at=excluded.updated_at
  returning * into v_result;
  if v_result.key is null then raise exception 'launch_signoff_unavailable'; end if;
  perform backend_system.assert_launch_signoff_operator_v1(true);
  return next v_result;
end $function$;

alter function backend_system.assert_launch_signoff_operator_v1(boolean) owner to launch_signoff_store_owner;
alter function backend_system.list_launch_signoffs_v1() owner to launch_signoff_store_owner;
alter function backend_system.record_launch_signoff_v1(text,text,text,timestamptz,text,text) owner to launch_signoff_store_owner;
revoke all on function backend_system.assert_launch_signoff_operator_v1(boolean),
  backend_system.list_launch_signoffs_v1(),backend_system.record_launch_signoff_v1(text,text,text,timestamptz,text,text)
from public,anon,authenticated,service_role;
grant execute on function backend_system.assert_launch_signoff_operator_v1(boolean),
  backend_system.list_launch_signoffs_v1(),backend_system.record_launch_signoff_v1(text,text,text,timestamptz,text,text)
to launch_signoff_executor;
revoke create on schema backend_system from launch_signoff_store_owner;
do $runtime$
begin
  if exists(select 1 from pg_catalog.pg_roles where rolname='talli_ledger_backend') then
    grant launch_signoff_executor to talli_ledger_backend with inherit false,set true;
  end if;
  execute pg_catalog.format('revoke launch_signoff_store_owner, launch_signoff_executor from %I',current_user);
  if pg_catalog.current_setting('talli.launch_signoff_schema_membership_added')='true' then
    execute pg_catalog.format('revoke ledger_store_owner from %I',current_user);
  end if;
end $runtime$;
commit;
