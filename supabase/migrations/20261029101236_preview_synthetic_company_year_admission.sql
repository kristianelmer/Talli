-- #228: explicitly synthetic facts for the one already-owned private Preview fixture.
-- No arbitrary company creation, Brreg impersonation, role expansion or provider activation.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';

do $preview_synthetic$
declare
  item record;
  definition text;
  body text;
  before_self_grant record;
  borrowed boolean:=false;
  actor text:=current_user;
  marker constant text:='  -- private-preview synthetic registry admission v1';
  year_marker constant text:='  -- company-year 2025 paired-manifest v1';
  source_guard constant text:=$source_guard$(p_source is distinct from 'brreg' and (
       p_source is distinct from 'browser_test'
       or p_org_number is distinct from '992803750'
       or pg_catalog.current_setting('transaction_isolation')<>'read committed'
       or not exists (
         select 1 from pg_catalog.pg_proc active
         where active.pronamespace='public'::regnamespace
           and active.proname='company_access_admit_company_year'
           and pg_catalog.strpos(active.prosrc,'-- private-preview synthetic registry admission v1')>0
       )
       or not exists (
         select 1 from public.companies fixture
         where fixture.org_number=p_org_number
           and fixture.source='browser_test'
           and fixture.name=p_name
           and fixture.name ilike 'synthetic private preview %'
           and fixture.entity_type=p_entity_type and fixture.status_text=p_status_text
           and coalesce(fixture.address,'')=coalesce(p_address,'')
           and coalesce(fixture.postal_code,'')=coalesce(p_postal_code,'')
           and coalesce(fixture.city,'')=coalesce(p_city,'')
           and fixture.identity_confirmed_at is not null
           and fixture.identity_locked_at is not null
           and fixture.created_by=p_verified_subject
           and public.company_access_is_accepted_owner_v1(fixture.id)
           and public.company_access_has_fresh_mfa_v1()
       )
     ))$source_guard$;
begin
  if not pg_catalog.pg_has_role(current_user,'company_access_executor','USAGE') then
    select m.admin_option,m.inherit_option,m.set_option into before_self_grant
      from pg_catalog.pg_auth_members m
      where m.roleid='company_access_executor'::regrole and m.member=current_user::regrole
        and m.grantor=current_user::regrole;
    execute pg_catalog.format(
      'grant company_access_executor to %I with inherit true, set true granted by %I',actor,actor);
    borrowed:=true;
  end if;
  select p.oid,p.prosrc,p.proowner,p.proacl,p.proconfig,p.prosecdef into strict item
  from pg_catalog.pg_proc p where p.pronamespace='public'::regnamespace
    and p.proname='company_access_admit_company_year';
  if item.proowner<>'company_access_executor'::regrole or not item.prosecdef
    or pg_catalog.strpos(item.prosrc,'-- company-access RF guard v1')=0
    or pg_catalog.strpos(item.prosrc,year_marker)=0 then
    raise exception 'preview_synthetic_registry_function_precondition';
  end if;
  body:=item.prosrc;
  if pg_catalog.strpos(body,marker)>0
    or (pg_catalog.length(body)-pg_catalog.length(pg_catalog.replace(body,
      'p_source is distinct from ''brreg''','')))<>pg_catalog.length('p_source is distinct from ''brreg''')
    or (pg_catalog.length(body)-pg_catalog.length(pg_catalog.replace(body,year_marker,'')))<>pg_catalog.length(year_marker) then
    raise exception 'preview_synthetic_registry_anchor_shape';
  end if;
  body:=pg_catalog.replace(body,'p_source is distinct from ''brreg''',source_guard);
  -- Keep the year marker first so that the preceding year rollback/recutover remains exact.
  body:=pg_catalog.replace(body,year_marker,year_marker||E'\n'||marker);
  definition:=pg_catalog.pg_get_functiondef(item.oid);
  execute pg_catalog.replace(definition,item.prosrc,body);
  if not exists(select 1 from pg_catalog.pg_proc p where p.oid=item.oid
    and p.proowner=item.proowner and p.proacl is not distinct from item.proacl
    and p.proconfig is not distinct from item.proconfig and p.prosecdef=item.prosecdef) then
    raise exception 'preview_synthetic_registry_function_security_drift';
  end if;
  if borrowed then
    if before_self_grant.admin_option is null then
      execute pg_catalog.format('revoke company_access_executor from %I granted by %I',actor,actor);
    else
      execute pg_catalog.format(
        'grant company_access_executor to %I with admin %s, inherit %s, set %s granted by %I',
        actor,before_self_grant.admin_option,before_self_grant.inherit_option,before_self_grant.set_option,actor);
    end if;
  end if;
end
$preview_synthetic$;

commit;
