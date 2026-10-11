-- Closed V3 operation intents: historical recovery before current admission.
-- No ordinary/runtime grants, provider effects or legacy routine edits.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_operation_v3_roles(role_name text,prior jsonb) on commit drop;
create temporary table rf193_operation_v3_create(added boolean) on commit drop;
do $borrow$
declare name text; prior jsonb; schema_owner text;
begin
 select pg_catalog.pg_get_userbyid(nspowner) into strict schema_owner from pg_catalog.pg_namespace where nspname='shareholder_register_filing';
 for name in select distinct value from unnest(array['shareholder_register_filing_store_owner',schema_owner]) value loop
  if not pg_catalog.pg_has_role(current_user,name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into prior
    from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(name) and m.member=current_user::regrole and m.grantor=m.member;
   insert into pg_temp.rf193_operation_v3_roles values(name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',name,current_user,current_user);
  end if;
 end loop;
 insert into pg_temp.rf193_operation_v3_create select not pg_catalog.has_schema_privilege('shareholder_register_filing_store_owner','shareholder_register_filing','CREATE');
 if (select added from pg_temp.rf193_operation_v3_create) then
  execute pg_catalog.format('set local role %I',schema_owner);
  grant create on schema shareholder_register_filing to shareholder_register_filing_store_owner;
  reset role;
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;


do $version$
declare old pg_catalog.pg_proc%rowtype; existing pg_catalog.pg_proc%rowtype;
 original jsonb; body text; anchor text;
begin
 select * into strict old from pg_catalog.pg_proc where oid='shareholder_register_filing.prepare_source_operation_v1(uuid,text,text,text,uuid,uuid,text,text)'::regprocedure;
 original:=pg_catalog.to_jsonb(old);
 if old.proowner<>current_user::regrole or not old.prosecdef or old.provolatile<>'v' or old.proparallel<>'u'
  or old.prokind<>'f' or old.proretset or old.prorettype<>'jsonb'::regtype
  or old.proconfig is distinct from array['search_path=""']::text[]
  or old.prolang<>(select oid from pg_catalog.pg_language where lanname='plpgsql')
  or old.proargnames is distinct from array['p_submission','p_manifest_sha','p_operation','p_body_sha','p_key','p_expected_event','p_annual_text','p_subject']::text[]
  or pg_catalog.md5(old.prosrc)<>'46ccd80ea377dee72e645e2faa3de42a'
  or exists(select 1 from pg_catalog.aclexplode(coalesce(old.proacl,pg_catalog.acldefault('f',old.proowner))) x
   where x.grantee<>old.proowner)
 then raise exception 'rf1086_operation_v3_definition_drift'; end if;
 body:=old.prosrc;
 -- fixed binding row declaration.
 anchor:=' context jsonb;
';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_operation_v3_definition_drift'; end if;
 body:=replace(body,anchor,' context jsonb; pilot record;
');
 -- historical owner/company/year lock before fresh rules.
 anchor:=' perform shareholder_register_filing.assert_source_approval_guards_v1(s.company_id,s.income_year);
 perform shareholder_register_filing.assert_source_dispatch_authority_v1(s.approval_id,p_subject);';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_operation_v3_definition_drift'; end if;
 body:=replace(body,anchor,' perform shareholder_register_filing.lock_source_claim_recovery_v3(s.approval_id,p_manifest_sha,p_subject);');
 -- stored version checked only after existing intent disposition.
 anchor:='  or a.manifest->>''schemaVersion'' is distinct from ''production-source-approval-v2''
';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_operation_v3_definition_drift'; end if;
 body:=replace(body,anchor,'');
 -- current head checked only for new or retryable effect.
 anchor:='  or shareholder_register_filing.submission_head_internal_v1(s.company_id,s.income_year) is distinct from s.id
';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_operation_v3_definition_drift'; end if;
 body:=replace(body,anchor,'');
 -- fresh policy and exact current Authority/Billing binding after history.
 anchor:=' if p_operation=''post_hovedskjema'' then';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_operation_v3_definition_drift'; end if;
 body:=replace(body,anchor,' -- Only a real absent/retryable next intent reaches current admission.
 if a.manifest->>''schemaVersion'' is distinct from ''production-source-approval-v3''
  or shareholder_register_filing.submission_head_internal_v1(s.company_id,s.income_year) is distinct from s.id
 then raise exception ''rf1086_source_operation_identity_changed''; end if;
 perform shareholder_register_filing.assert_source_approval_guards_v1(s.company_id,s.income_year);
 perform shareholder_register_filing.assert_source_dispatch_authority_v1(s.approval_id,p_subject);
 select e.* into pilot from billing.read_rf_pilot_v1(s.entitlement_id,s.company_id,s.user_id) e;
 if p_expected_request is null or nullif(btrim(p_expected_external),'''') is null
  or pilot.id is null or pilot.system_user_request_id is distinct from p_expected_request
  or pilot.system_user_external_reference is distinct from p_expected_external
 then raise exception ''rf1086_source_dispatch_binding_changed''; end if;
 if p_operation=''post_hovedskjema'' then');
 -- main uses full owned current V3 context and adapter-derived annual proof.
 anchor:='context:=shareholder_register_filing.source_approval_context_internal_v2(';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_operation_v3_definition_drift'; end if;
 body:=replace(body,anchor,'context:=shareholder_register_filing.source_approval_context_internal_v3(');
 select * into existing from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure('shareholder_register_filing.prepare_source_operation_v3(uuid,text,text,text,uuid,uuid,text,uuid,text,text)');
 if existing.oid is not null and (existing.proowner<>old.proowner or existing.prosrc is distinct from body
  or existing.proconfig is distinct from old.proconfig or existing.prosecdef is distinct from old.prosecdef
  or existing.provolatile is distinct from old.provolatile or existing.proparallel is distinct from old.proparallel
  or existing.prolang<>old.prolang or existing.proargnames is distinct from array['p_submission','p_manifest_sha','p_operation','p_body_sha','p_key','p_expected_event','p_annual_text','p_expected_request','p_expected_external','p_subject']::text[]
  or existing.prokind<>'f' or existing.proretset or existing.prorettype<>'jsonb'::regtype)
 then raise exception 'rf1086_operation_v3_definition_drift'; end if;
 execute 'create or replace function shareholder_register_filing.prepare_source_operation_v3('
  ||'p_submission uuid,p_manifest_sha text,p_operation text,p_body_sha text,p_key uuid,p_expected_event uuid,'
  ||'p_annual_text text,p_expected_request uuid,p_expected_external text,p_subject text) '
  ||'returns jsonb language plpgsql volatile security definer set search_path='''''
  ||' as '||pg_catalog.quote_literal(body);
 if (select pg_catalog.to_jsonb(p) from pg_catalog.pg_proc p where p.oid=old.oid) is distinct from original
 then raise exception 'rf1086_operation_v3_legacy_changed'; end if;
end; $version$;

do $closed$
declare routine regprocedure:='shareholder_register_filing.prepare_source_operation_v3(uuid,text,text,text,uuid,uuid,text,uuid,text,text)'::regprocedure; grantee_name text;
begin
 execute pg_catalog.format('revoke all on function %s from public',routine);
 for grantee_name in select distinct r.rolname from pg_catalog.pg_proc p cross join lateral pg_catalog.aclexplode(p.proacl) a
  join pg_catalog.pg_roles r on r.oid=a.grantee where p.oid=routine::oid and a.grantee<>p.proowner loop
  execute pg_catalog.format('revoke all on function %s from %I',routine,grantee_name);
 end loop;
end; $closed$;

reset role;
do $restore$
declare item record; schema_owner text;
begin
 if (select added from pg_temp.rf193_operation_v3_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='shareholder_register_filing';
  execute pg_catalog.format('set local role %I',schema_owner);
  revoke create on schema shareholder_register_filing from shareholder_register_filing_store_owner;
  reset role;
 end if;
 for item in select * from pg_temp.rf193_operation_v3_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',item.role_name,current_user,current_user);
  if item.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   item.role_name,current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
