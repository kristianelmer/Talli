-- Roll back only before any 2025 evidence exists; never erase or rewrite accepted promises.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
lock table public.company_eligibility_assessments, public.company_year_admissions,
  public.company_year_acceptances in access exclusive mode;
do $no_2025$
begin
  if exists(select 1 from public.company_eligibility_assessments where accounting_year=2025)
    or exists(select 1 from public.company_year_admissions where accounting_year=2025)
    or exists(select 1 from public.company_year_acceptances where accounting_year=2025) then
    raise exception 'company_year_2025_rollback_requires_retaining_existing_promises';
  end if;
end
$no_2025$;

alter table public.company_eligibility_assessments
  drop constraint company_eligibility_assessments_year_manifest_v2,
  add constraint company_eligibility_assessments_accounting_year_check check (accounting_year=2026),
  add constraint company_eligibility_assessmen_capability_manifest_version_check check (capability_manifest_version='2026.1'),
  add constraint company_eligibility_assessment_capability_manifest_sha256_check check (capability_manifest_sha256='9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de');

alter table public.company_year_admissions
  drop constraint company_year_admissions_year_manifest_v2,
  add constraint company_year_admissions_accounting_year_check check (accounting_year=2026),
  add constraint company_year_admissions_capability_manifest_version_check check (capability_manifest_version='2026.1'),
  add constraint company_year_admissions_capability_manifest_sha256_check check (capability_manifest_sha256='9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de');

alter table public.company_year_acceptances
  drop constraint company_year_acceptances_year_manifest_v2,
  add constraint company_year_acceptances_accounting_year_check check (accounting_year=2026),
  add constraint company_year_acceptances_capability_manifest_version_check check (capability_manifest_version='2026.1'),
  add constraint company_year_acceptances_capability_manifest_sha256_check check (capability_manifest_sha256='9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de');

alter table public.company_year_admissions
  drop constraint company_year_admissions_2025_promise_extent,
  drop constraint company_year_admissions_reconstruct_from_check,
  add constraint company_year_admissions_reconstruct_from_check
    check (reconstruct_from=date '2026-01-01');

do $paired_company_years$
declare
  item record;
  replacement record;
  definition text;
  body text;
  before_self_grant record;
  borrowed boolean:=false;
  actor text:=current_user;
  function_count integer:=0;
  marker constant text:='  -- company-year 2025 paired-manifest v1';
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
  for item in
    select p.oid,p.proname,p.prosrc,p.proowner,p.proacl,p.proconfig,p.prosecdef
    from pg_catalog.pg_proc p
    where p.pronamespace='public'::regnamespace and p.proname in (
      'company_access_admit_company_year','company_access_recheck_company_year_eligibility')
    order by p.proname
  loop
    function_count:=function_count+1;
    if item.proowner<>'company_access_executor'::regrole or not item.prosecdef
      or pg_catalog.strpos(item.prosrc,marker)=0
      or pg_catalog.strpos(item.prosrc,'-- company-access RF guard v1')=0 then
      raise exception 'company_year_2025_function_precondition:%',item.proname;
    end if;
    body:=item.prosrc;
    for replacement in select forward.after_text as before_text, forward.before_text as after_text from (values
      ('p_accounting_year is distinct from 2026',
       '(p_accounting_year is null or p_accounting_year not in (2025, 2026))'),
      ('p_capability_manifest_version is distinct from ''2026.1''',
       'p_capability_manifest_version is distinct from (p_accounting_year::text || ''.1'')'),
      ('p_capability_manifest_sha256 is distinct from ''9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de''',
       'p_capability_manifest_sha256 is distinct from (case p_accounting_year when 2026 then ''9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de'' when 2025 then ''2ac7047f632078b0438770d172d4c2289fd947b28e93c3a7eebc6995eb519fbe'' end)')
    ) forward(before_text,after_text)
    loop
      if (pg_catalog.length(body)-pg_catalog.length(pg_catalog.replace(body,replacement.before_text,'')))
        <>pg_catalog.length(replacement.before_text) then
        raise exception 'company_year_2025_anchor_shape:%:%',item.proname,replacement.before_text;
      end if;
      body:=pg_catalog.replace(body,replacement.before_text,replacement.after_text);
    end loop;
    if item.proname='company_access_admit_company_year' then
      if (pg_catalog.length(body)-pg_catalog.length(pg_catalog.replace(body,E'\n  v_fingerprint :=','')))
        <>pg_catalog.length(E'\n  v_fingerprint :=') then
        raise exception 'company_year_2025_promise_anchor_shape';
      end if;
      if (pg_catalog.length(body)-pg_catalog.length(pg_catalog.replace(body,$promise_guard$
  if p_accounting_year=2025 and v_company_year_promise is distinct from
    pg_catalog.jsonb_build_object(
      'accountingYear',2025,'startsOn','2025-01-01','endsOn','2025-12-31',
      'reconstructionRequiredFrom','2025-01-01','onlyAccountingAndFilingProduct',true,
      'customerClaims',v_capability_manifest->'promise'->'customerClaims'
    ) then
    raise exception 'company_access_invalid_request' using errcode='P0001';
  end if;

  v_fingerprint :=$promise_guard$,''))) <> pg_catalog.length($promise_guard$
  if p_accounting_year=2025 and v_company_year_promise is distinct from
    pg_catalog.jsonb_build_object(
      'accountingYear',2025,'startsOn','2025-01-01','endsOn','2025-12-31',
      'reconstructionRequiredFrom','2025-01-01','onlyAccountingAndFilingProduct',true,
      'customerClaims',v_capability_manifest->'promise'->'customerClaims'
    ) then
    raise exception 'company_access_invalid_request' using errcode='P0001';
  end if;

  v_fingerprint :=$promise_guard$) then
        raise exception 'company_year_2025_rollback_promise_shape';
      end if;
      body:=pg_catalog.replace(body,$promise_guard$
  if p_accounting_year=2025 and v_company_year_promise is distinct from
    pg_catalog.jsonb_build_object(
      'accountingYear',2025,'startsOn','2025-01-01','endsOn','2025-12-31',
      'reconstructionRequiredFrom','2025-01-01','onlyAccountingAndFilingProduct',true,
      'customerClaims',v_capability_manifest->'promise'->'customerClaims'
    ) then
    raise exception 'company_access_invalid_request' using errcode='P0001';
  end if;

  v_fingerprint :=$promise_guard$,E'\n  v_fingerprint :=');
      if (pg_catalog.length(body)-pg_catalog.length(pg_catalog.replace(body,
        'p_reconstruct_from is distinct from pg_catalog.make_date(p_accounting_year,1,1)','')))
        <>pg_catalog.length('p_reconstruct_from is distinct from pg_catalog.make_date(p_accounting_year,1,1)') then
        raise exception 'company_year_2025_reconstruction_shape';
      end if;
      body:=pg_catalog.replace(body,'p_reconstruct_from is distinct from pg_catalog.make_date(p_accounting_year,1,1)',
        'p_reconstruct_from is distinct from date ''2026-01-01''');
    end if;
    if pg_catalog.strpos(body,E'\nbegin\n')=0 then
      raise exception 'company_year_2025_entry_shape:%',item.proname;
    end if;
    body:=pg_catalog.replace(body,marker||E'\n','');
    definition:=pg_catalog.pg_get_functiondef(item.oid);
    execute pg_catalog.replace(definition,item.prosrc,body);
    if not exists(select 1 from pg_catalog.pg_proc p where p.oid=item.oid
      and p.proowner=item.proowner and p.proacl is not distinct from item.proacl
      and p.proconfig is not distinct from item.proconfig and p.prosecdef=item.prosecdef) then
      raise exception 'company_year_2025_function_security_drift:%',item.proname;
    end if;
  end loop;
  if function_count<>2 then raise exception 'company_year_2025_function_count'; end if;
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
$paired_company_years$;

commit;
