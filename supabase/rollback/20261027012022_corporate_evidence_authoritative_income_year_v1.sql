-- Bind Documents evidence to the owning Corporate receipt year.
-- Public document/attestation commands derive scope from the guarded decision.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table corporate_evidence_year_authority(role_name text, prior jsonb) on commit drop;
do $borrow$
declare p jsonb; r text;
begin
 foreach r in array array['corporate_governance_workflow_executor','ledger_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(r)
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.corporate_evidence_year_authority values(r,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
create temporary table corporate_evidence_year_schema_create(borrowed boolean) on commit drop;
do $create$ begin
 if not pg_catalog.has_schema_privilege('corporate_governance_workflow_executor','backend_system','CREATE') then
  insert into pg_temp.corporate_evidence_year_schema_create values(true);
  set local role ledger_store_owner;
  grant create on schema backend_system to corporate_governance_workflow_executor;
  reset role;
 end if;
end; $create$;
set local role corporate_governance_workflow_executor;
do $patch$
declare row record; routine oid; body text; changed text; definition text; current_hash text;
begin
 for row in select * from (values
  ('backend_system.register_corporate_governance_documents_v1(text,jsonb,text)','bb0efc9aad7f4301427e692a45a0a831a40331ba5e83d452a09c4afd48988854','79635e96c384dbe00737ca02ba646f8cf46a922e48bb16b3cd9ea9a7f3a9088b'),
  ('backend_system.attest_corporate_governance_signed_artifact_v1(text,jsonb,text)','5edc850726104e367c28aff3a7068cd572954ac1f9b77f5b26c562a860981a12','6e07b7c7a8aca0cb31533c6ff9bce0da9133f05e5723f845fd3e63966611a1d0')
 ) expected(signature,before_hash,after_hash) loop
  routine:=pg_catalog.to_regprocedure(row.signature);
  select p.prosrc,pg_catalog.pg_get_functiondef(p.oid) into body,definition from pg_catalog.pg_proc p
   where p.oid=routine and p.proowner='corporate_governance_workflow_executor'::regrole and p.prosecdef;
  if body is null then raise exception 'corporate_evidence_year_predecessor_required'; end if;
  current_hash:=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(body,'UTF8')),'hex');
  if current_hash=row.after_hash then continue; end if;
  if current_hash<>row.before_hash then raise exception 'corporate_evidence_year_definition_drift'; end if;
  changed:=pg_catalog.replace(body,'(v_result ->> ''incomeYear'')::integer','(p_request ->> ''incomeYear'')::integer');
  if pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(changed,'UTF8')),'hex')<>row.after_hash then
   raise exception 'corporate_evidence_year_patch_unproven'; end if;
  execute pg_catalog.replace(definition,body,changed);
 end loop;
end; $patch$;
reset role;
do $create_restore$ begin
 if exists(select 1 from pg_temp.corporate_evidence_year_schema_create) then
  set local role ledger_store_owner;
  revoke create on schema backend_system from corporate_governance_workflow_executor;
  reset role;
 end if;
end; $create_restore$;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.corporate_evidence_year_authority loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
