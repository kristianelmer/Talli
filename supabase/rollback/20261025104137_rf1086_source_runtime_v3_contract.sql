-- RETENTIVE CLOSURE: stop new V2/V3 source effects; keep all data and bodies.
-- Legacy source writers STAY CLOSED. No automatic downgrade to a V1 factory.
-- Profile: rf1086-v3-retentive-read-only-rollback-v1, NOT pre-contract ACL restoration.
-- lock_source_claim_recovery_v3 was newly enabled during activation and is
-- intentionally retained as a historical read port. This file never GRANTs it.
-- Consumer: Session.source_operation_recovery_v3 -> DispatchV3.send; confirmed
-- history returns and unknown history refuses BEFORE current/provider admission.
-- The SQL port only reads exact original-actor/current-OWNER bindings and takes
-- company/year locks. All eight other new entrypoints and seven old writers close.
-- Retained reads and finish/reconciliation ports remain unchanged.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:rf1086:source-runtime:v3',0));
do $principal$ begin
 if current_user<>session_user then raise exception 'rf1086_runtime_v3_migration_principal_required'; end if;
end; $principal$;

create temporary table rf193_runtime_v3_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$
declare role_name text; prior jsonb;
begin
 foreach role_name in array array['shareholder_register_filing_store_owner','corporate_governance_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,role_name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into prior
    from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(role_name)
     and m.member=current_user::regrole and m.grantor=m.member;
   insert into pg_temp.rf193_runtime_v3_roles values(role_name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',role_name,current_user,current_user);
  end if;
 end loop;
end; $borrow$;

-- Closed callgraph catalogue: only these entrypoints gain runtime execution.
create temporary table rf193_runtime_v3_entries(signature text primary key,owner_name name) on commit drop;
insert into pg_temp.rf193_runtime_v3_entries values
 ('shareholder_register_filing.lock_year_source_capture_v2(uuid,integer)','shareholder_register_filing_store_owner'),
 ('shareholder_register_filing.append_year_source_v2(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamp with time zone)','shareholder_register_filing_store_owner'),
 ('shareholder_register_filing.read_source_approval_context_v3(uuid,uuid,text,text)','shareholder_register_filing_store_owner'),
 ('shareholder_register_filing.append_source_approval_v3(uuid,uuid,text,text,text,text)','shareholder_register_filing_store_owner'),
 ('shareholder_register_filing.lock_source_claim_recovery_v3(uuid,text,text)','shareholder_register_filing_store_owner'),
 ('shareholder_register_filing.claim_source_submission_v3(uuid,text,uuid,text,text)','shareholder_register_filing_store_owner'),
 ('shareholder_register_filing.prepare_source_operation_v3(uuid,text,text,text,uuid,uuid,text,uuid,text,text)','shareholder_register_filing_store_owner'),
 ('corporate_governance.read_guarded_reporting_register_evidence_v1(uuid,integer,text)','corporate_governance_store_owner'),
 ('corporate_governance.prepare_rf_year_source_governance_proof_v1(uuid,integer,text,text)','corporate_governance_store_owner');
create temporary table rf193_runtime_v3_retired(signature text primary key) on commit drop;
insert into pg_temp.rf193_runtime_v3_retired values
 ('shareholder_register_filing.append_year_source_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamp with time zone)'),
 ('shareholder_register_filing.append_source_approval_v1(uuid,uuid,text,text,text,text)'),
 ('shareholder_register_filing.append_source_approval_v2(uuid,uuid,text,text,text,text)'),
 ('shareholder_register_filing.claim_source_submission_v1(uuid,text,uuid,text)'),
 ('shareholder_register_filing.claim_source_submission_v2(uuid,text,uuid,text,text)'),
 ('shareholder_register_filing.prepare_source_operation_v1(uuid,text,text,text,uuid,uuid,text,text)'),
 ('shareholder_register_filing.prepare_source_operation_v2(uuid,text,text,text,uuid,uuid,text,uuid,text,text)');

do $validate$
declare entry record; routine pg_catalog.pg_proc%rowtype; runtime oid:='shareholder_register_filing_executor'::regrole;
 legacy_body text;
 legacy_prefix constant text:=E'begin\n -- rf193-company-guard-v1\n perform shareholder_register_filing.lock_preview_write_v1(p_preview_id,false);\n'
  ||E' -- rf193-legacy-source-approval-denied-v1\n'
  ||E' IF EXISTS(SELECT 1 FROM shareholder_register_filing.source_previews WHERE id=p_preview_id)\n'
  ||E'   OR EXISTS(SELECT 1 FROM shareholder_register_filing.filing_previews WHERE id=p_preview_id AND source=''rf1086-full-year-v1'')\n'
  ||E' THEN RAISE EXCEPTION ''rf1086_source_production_admission_required''; END IF;\n';
begin
 select prosrc into strict legacy_body from pg_catalog.pg_proc
  where oid='shareholder_register_filing.approve_production_filing(uuid,uuid,jsonb,text,text)'::regprocedure;
 if pg_catalog.left(legacy_body,pg_catalog.length(legacy_prefix))<>legacy_prefix
 then raise exception 'rf1086_runtime_v3_legacy_approval_bypass'; end if;

 for entry in select signature,owner_name from pg_temp.rf193_runtime_v3_entries
  union all select signature,'shareholder_register_filing_store_owner'::name from pg_temp.rf193_runtime_v3_retired loop
  select * into strict routine from pg_catalog.pg_proc where oid=entry.signature::regprocedure;
  if routine.proowner<>entry.owner_name::regrole or routine.prokind<>'f' or not routine.prosecdef
   or routine.proconfig is distinct from array['search_path=""']::text[]
   or routine.provolatile<>'v' or routine.proparallel<>'u'
  then raise exception 'rf1086_runtime_v3_definition_drift'; end if;
  if exists(select 1 from pg_catalog.aclexplode(coalesce(routine.proacl,pg_catalog.acldefault('f',routine.proowner))) a
   where a.privilege_type<>'EXECUTE' or (a.is_grantable and a.grantee<>routine.proowner)
    or (a.grantee not in (routine.proowner,runtime)
     and not (entry.signature='corporate_governance.read_guarded_reporting_register_evidence_v1(uuid,integer,text)'
      and a.grantee='corporate_governance_workflow_executor'::regrole)))
  then raise exception 'rf1086_runtime_v3_acl_drift'; end if;
 end loop;
 if pg_catalog.pg_has_role('shareholder_register_filing_executor','shareholder_register_filing_store_owner','MEMBER')
  or pg_catalog.pg_has_role('shareholder_register_filing_executor','corporate_governance_store_owner','MEMBER')
  or not pg_catalog.has_schema_privilege('shareholder_register_filing_executor','corporate_governance','USAGE')
 then raise exception 'rf1086_runtime_v3_role_drift'; end if;
end; $validate$;

set local role shareholder_register_filing_store_owner;
revoke all on function
 shareholder_register_filing.append_year_source_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamp with time zone),
 shareholder_register_filing.append_source_approval_v1(uuid,uuid,text,text,text,text),
 shareholder_register_filing.append_source_approval_v2(uuid,uuid,text,text,text,text),
 shareholder_register_filing.claim_source_submission_v1(uuid,text,uuid,text),
 shareholder_register_filing.claim_source_submission_v2(uuid,text,uuid,text,text),
 shareholder_register_filing.prepare_source_operation_v1(uuid,text,text,text,uuid,uuid,text,text),
 shareholder_register_filing.prepare_source_operation_v2(uuid,text,text,text,uuid,uuid,text,uuid,text,text)
 from shareholder_register_filing_executor;
revoke all on function
 shareholder_register_filing.lock_year_source_capture_v2(uuid,integer),
 shareholder_register_filing.append_year_source_v2(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamp with time zone),
 shareholder_register_filing.read_source_approval_context_v3(uuid,uuid,text,text),
 shareholder_register_filing.append_source_approval_v3(uuid,uuid,text,text,text,text),
 shareholder_register_filing.claim_source_submission_v3(uuid,text,uuid,text,text),
 shareholder_register_filing.prepare_source_operation_v3(uuid,text,text,text,uuid,uuid,text,uuid,text,text)
 from shareholder_register_filing_executor;
reset role;
set local role corporate_governance_store_owner;
revoke all on function corporate_governance.read_guarded_reporting_register_evidence_v1(uuid,integer,text),
 corporate_governance.prepare_rf_year_source_governance_proof_v1(uuid,integer,text,text)
 from shareholder_register_filing_executor;
reset role;

do $verify$
declare entry record;
begin
 for entry in select signature from pg_temp.rf193_runtime_v3_entries
  where signature<>'shareholder_register_filing.lock_source_claim_recovery_v3(uuid,text,text)' loop
  if pg_catalog.has_function_privilege('shareholder_register_filing_executor',entry.signature,'EXECUTE')
  then raise exception 'rf1086_runtime_v3_closure_failed'; end if;
 end loop;
 for entry in select signature from pg_temp.rf193_runtime_v3_retired loop
  if pg_catalog.has_function_privilege('shareholder_register_filing_executor',entry.signature,'EXECUTE')
  then raise exception 'rf1086_runtime_v3_legacy_writer_open'; end if;
 end loop;
 -- No alternate direct source writer through table privileges.
 if pg_catalog.has_table_privilege('shareholder_register_filing_executor','shareholder_register_filing.year_source_versions','INSERT,UPDATE,DELETE')
  or pg_catalog.has_table_privilege('shareholder_register_filing_executor','shareholder_register_filing.source_approval_bindings','INSERT,UPDATE,DELETE')
  or pg_catalog.has_table_privilege('shareholder_register_filing_executor','shareholder_register_filing.source_submission_bindings','INSERT,UPDATE,DELETE')
 then raise exception 'rf1086_runtime_v3_direct_writer_open'; end if;
 -- Preserve owner-to-owner receiver/invalidation grants. They are NOT runtime
 -- entrypoints, and neither are any parser, trigger or annual/approval helper.
 if exists(select 1 from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
  where ((n.nspname='shareholder_register_filing' and (p.proname like 'year_source_v2_%'
    or p.proname in ('receive_year_source_governance_proof_v1','invalidate_year_source_governance_proofs_v1',
      'assert_year_source_v2_internal_v1','assert_retained_annual_readiness_v2_shape_internal_v1',
      'source_annual_binding_internal_v2','source_approval_context_internal_v3')))
   or (n.nspname='corporate_governance' and p.proname in ('rf_year_source_fact_internal_v1',
      'rf_year_source_chain_internal_v1','invalidate_rf_year_source_proof_internal_v1')))
   and (pg_catalog.has_function_privilege('shareholder_register_filing_executor',p.oid,'EXECUTE')
    or pg_catalog.has_function_privilege('anon',p.oid,'EXECUTE')
    or pg_catalog.has_function_privilege('authenticated',p.oid,'EXECUTE')
    or pg_catalog.has_function_privilege('service_role',p.oid,'EXECUTE')))
 then raise exception 'rf1086_runtime_v3_internal_helper_open'; end if;
end; $verify$;

do $restore$
declare item record;
begin
 for item in select * from pg_temp.rf193_runtime_v3_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',item.role_name,current_user,current_user);
  if item.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
    item.role_name,current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
