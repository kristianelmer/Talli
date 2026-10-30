-- Closed V3 claim: historical recovery before every live first-effect check.
-- No ordinary/runtime grants, provider effects or legacy routine edits.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_claim_v3_roles(role_name text,prior jsonb) on commit drop;
create temporary table rf193_claim_v3_create(added boolean) on commit drop;
do $borrow$
declare name text; prior jsonb; schema_owner text;
begin
 select pg_catalog.pg_get_userbyid(nspowner) into strict schema_owner from pg_catalog.pg_namespace where nspname='shareholder_register_filing';
 for name in select distinct value from unnest(array['shareholder_register_filing_store_owner',schema_owner]) value loop
  if not pg_catalog.pg_has_role(current_user,name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into prior
    from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(name) and m.member=current_user::regrole and m.grantor=m.member;
   insert into pg_temp.rf193_claim_v3_roles values(name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',name,current_user,current_user);
  end if;
 end loop;
 insert into pg_temp.rf193_claim_v3_create select not pg_catalog.has_schema_privilege('shareholder_register_filing_store_owner','shareholder_register_filing','CREATE');
 if (select added from pg_temp.rf193_claim_v3_create) then
  execute pg_catalog.format('set local role %I',schema_owner);
  grant create on schema shareholder_register_filing to shareholder_register_filing_store_owner;
  reset role;
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;


do $guard_drift$
declare existing pg_catalog.pg_proc%rowtype;
begin
 select * into existing from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure('shareholder_register_filing.lock_source_claim_recovery_v3(uuid,text,text)');
 if existing.oid is not null and (existing.proowner<>current_user::regrole or not existing.prosecdef
  or existing.provolatile<>'v' or existing.proparallel<>'u' or existing.proconfig is distinct from array['search_path=""']::text[]
  or existing.prolang<>(select oid from pg_catalog.pg_language where lanname='plpgsql')
  or pg_catalog.md5(existing.prosrc)<>'d22b5e33fce0955f4295c04d0cff117f')
 then raise exception 'rf1086_claim_v3_definition_drift'; end if;
end; $guard_drift$;

create or replace function shareholder_register_filing.lock_source_claim_recovery_v3(p_approval uuid,p_manifest_sha text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $guard$
declare a shareholder_register_filing.filing_approval_snapshots%rowtype;
 b shareholder_register_filing.source_approval_bindings%rowtype;
 actor uuid:=shareholder_register_filing.verified_actor_v1();
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed'
  or actor is null or p_subject is distinct from actor::text or p_manifest_sha is null or p_manifest_sha !~ '^[a-f0-9]{64}$'
 then raise exception 'rf1086_forbidden'; end if;
 select * into a from shareholder_register_filing.filing_approval_snapshots where id=p_approval;
 select * into b from shareholder_register_filing.source_approval_bindings where approval_id=p_approval;
 if a.id is null or b.approval_id is null or a.user_id is distinct from actor or a.approved_by is distinct from actor
  or b.approved_by is distinct from actor or b.company_id is distinct from a.company_id or b.income_year is distinct from a.income_year
  or b.preview_id is distinct from a.preview_id or a.case_profile is distinct from 'rf1086_full_year_v1'
  or b.manifest_sha256 is distinct from p_manifest_sha or a.manifest_hash is distinct from p_manifest_sha
  or b.payload_sha256 is distinct from a.payload_hash or a.manifest is distinct from b.manifest_text::jsonb
  or not shareholder_register_filing.can_read_company_v1(a.company_id)
 then raise exception 'rf1086_source_claim_mismatch'; end if;
 -- Historical access omits MFA/pilot/eligibility only. Live accepted OWNER is
 -- mandatory before and after both waits; caller-supplied company is absent.
 perform public.company_archive_lock_company_v1(a.company_id);
 if not shareholder_register_filing.can_read_company_v1(a.company_id)
 then raise exception 'rf1086_forbidden'; end if;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('rf1086:year-source:'||a.company_id::text||':'||a.income_year::text,0));
 if shareholder_register_filing.verified_actor_v1() is distinct from actor
  or not shareholder_register_filing.can_read_company_v1(a.company_id)
 then raise exception 'rf1086_forbidden'; end if;
 return pg_catalog.jsonb_build_object('companyId',a.company_id,'incomeYear',a.income_year);
end; $guard$;

do $version$
declare old pg_catalog.pg_proc%rowtype; existing pg_catalog.pg_proc%rowtype;
 body text; definition text; anchor text; replacement text;
begin
 select * into strict old from pg_catalog.pg_proc where oid='shareholder_register_filing.claim_source_submission_v2(uuid,text,uuid,text,text)'::regprocedure;
 if old.proowner<>current_user::regrole or not old.prosecdef or old.provolatile<>'v' or old.proparallel<>'u'
  or old.prokind<>'f' or old.proretset or old.prorettype<>'jsonb'::regtype
  or old.proconfig is distinct from array['search_path=""']::text[]
  or old.prolang<>(select oid from pg_catalog.pg_language where lanname='plpgsql')
  or old.proargnames is distinct from array['p_approval','p_manifest_sha','p_expected_head','p_annual_text','p_subject']::text[]
  or pg_catalog.md5(old.prosrc)<>'c04c9ed7d713e798ba997aa85fa47117'
  or not pg_catalog.has_function_privilege('shareholder_register_filing_executor',old.oid,'EXECUTE')
  or exists(select 1 from pg_catalog.aclexplode(coalesce(old.proacl,pg_catalog.acldefault('f',old.proowner))) x
   where x.grantee not in (old.proowner,'shareholder_register_filing_executor'::regrole))
 then raise exception 'rf1086_claim_v3_definition_drift'; end if;
 body:=old.prosrc;
 anchor:=' if a.id is null or b.approval_id is null or a.invalidated_at is not null or a.user_id is distinct from actor';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_claim_v3_definition_drift'; end if;
 body:=replace(body,anchor,' if a.id is null or b.approval_id is null or a.user_id is distinct from actor');
 anchor:=' perform shareholder_register_filing.assert_source_approval_guards_v1(a.company_id,a.income_year);';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_claim_v3_definition_drift'; end if;
 body:=replace(body,anchor,' perform shareholder_register_filing.lock_source_claim_recovery_v3(p_approval,p_manifest_sha,p_subject);');
 anchor:=' if shareholder_register_filing.assert_fresh_owner_v1(a.company_id) is distinct from actor then raise exception ''rf1086_forbidden''; end if;';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_claim_v3_definition_drift'; end if;
 replacement:=E' select * into a from shareholder_register_filing.filing_approval_snapshots where id=p_approval;\n'
  ||E' select * into b from shareholder_register_filing.source_approval_bindings where approval_id=p_approval;\n'
  ||E' if a.id is null or b.approval_id is null or a.invalidated_at is not null or a.user_id is distinct from actor\n'
  ||E'  or b.manifest_sha256 is distinct from p_manifest_sha or a.manifest_hash is distinct from b.manifest_sha256\n'
  ||E'  or a.manifest is distinct from b.manifest_text::jsonb then raise exception ''rf1086_source_claim_mismatch''; end if;\n'
  ||E' perform shareholder_register_filing.assert_source_approval_guards_v1(a.company_id,a.income_year);\n'||anchor;
 body:=replace(body,anchor,replacement);
 anchor:=' if a.manifest->>''schemaVersion'' is distinct from ''production-source-approval-v2''';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_claim_v3_definition_drift'; end if;
 body:=replace(body,anchor,' if a.manifest->>''schemaVersion'' is distinct from ''production-source-approval-v3''');
 anchor:=' checked:=shareholder_register_filing.append_source_approval_v2(';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_claim_v3_definition_drift'; end if;
 body:=replace(body,anchor,' checked:=shareholder_register_filing.append_source_approval_v3(');
 select * into existing from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure('shareholder_register_filing.claim_source_submission_v3(uuid,text,uuid,text,text)');
 if existing.oid is not null and (existing.proowner<>old.proowner or existing.prosrc is distinct from body
  or existing.proconfig is distinct from old.proconfig or existing.prosecdef is distinct from old.prosecdef
  or existing.provolatile is distinct from old.provolatile or existing.proparallel is distinct from old.proparallel
  or existing.prolang<>old.prolang)
 then raise exception 'rf1086_claim_v3_definition_drift'; end if;
 definition:=pg_catalog.pg_get_functiondef(old.oid);
 if length(definition)-length(replace(definition,old.prosrc,''))<>length(old.prosrc) then raise exception 'rf1086_claim_v3_definition_drift'; end if;
 execute replace(replace(definition,old.prosrc,body),'claim_source_submission_v2(','claim_source_submission_v3(');
end; $version$;

do $closed$
declare routine regprocedure; grantee_name text;
begin
 for routine in select unnest(array[
  'shareholder_register_filing.lock_source_claim_recovery_v3(uuid,text,text)'::regprocedure,
  'shareholder_register_filing.claim_source_submission_v3(uuid,text,uuid,text,text)'::regprocedure]) loop
  execute pg_catalog.format('revoke all on function %s from public',routine);
  for grantee_name in select distinct r.rolname from pg_catalog.pg_proc p cross join lateral pg_catalog.aclexplode(p.proacl) a
   join pg_catalog.pg_roles r on r.oid=a.grantee where p.oid=routine::oid and a.grantee<>p.proowner loop
   execute pg_catalog.format('revoke all on function %s from %I',routine,grantee_name);
  end loop;
 end loop;
end; $closed$;

reset role;
do $restore$
declare item record; schema_owner text;
begin
 if (select added from pg_temp.rf193_claim_v3_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='shareholder_register_filing';
  execute pg_catalog.format('set local role %I',schema_owner);
  revoke create on schema shareholder_register_filing from shareholder_register_filing_store_owner;
  reset role;
 end if;
 for item in select * from pg_temp.rf193_claim_v3_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',item.role_name,current_user,current_user);
  if item.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   item.role_name,current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
