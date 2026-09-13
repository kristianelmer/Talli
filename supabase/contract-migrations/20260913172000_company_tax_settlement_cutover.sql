-- #146 CUTOVER: freeze the predecessor, reconcile, then enable exactly one writer.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
do $membership$
begin
 execute format('grant company_tax_filing_store_owner,company_tax_filing_workflow_executor,company_tax_filing_ledger_bridge_owner,banking_store_owner,documents_store_owner,company_archive_projection_executor to %I',current_user);
end;
$membership$;
select set_config('talli.tax146.principal',current_user,true);
grant create on schema public to company_tax_filing_store_owner;
set local role company_archive_projection_executor;
grant execute on function public.company_archive_track_source_write_v1() to company_tax_filing_store_owner;
reset role;

do $cutover$
declare
 v_phase text; v_inventory jsonb; v_source_count bigint; v_target_count bigint;
 v_source_digest text; v_target_digest text; v_resource text; v_definition jsonb;
 v_generation_before jsonb;
begin
 select phase into v_phase from backend_system.tax_settlement_migration_state where singleton for update;
 if v_phase in ('cutover','contracted') then return; end if;
 if v_phase is null or v_phase not in ('expanded','rolled_back') then raise exception 'tax_settlement_expansion_required'; end if;
 if (select relkind from pg_class where oid=to_regclass('public.holding_actions')) is distinct from 'r'::"char" then
  raise exception 'tax_settlement_predecessor_table_required';
 end if;
 lock table public.holding_actions in access exclusive mode;
 lock table company_tax_filing.settlements in access exclusive mode;
 -- These published predecessor contracts perform their own canonical row
 -- reconciliations before retiring their writers and physical investment stores.
 if to_regprocedure('backend_system.prepare_shareholder_loan_v1(jsonb,text)') is not null
  or to_regprocedure('backend_system.prepare_owner_dividend_payment_v1(jsonb,text)') is not null
  or to_regclass('public.investment_positions') is not null
  or to_regclass('public.investment_lots') is not null
  or exists(select 1 from pg_constraint where conrelid='public.holding_actions'::regclass
    and contype='f' and confrelid='ledger.entries'::regclass)
  or not exists(select 1 from pg_constraint where conrelid='public.holding_actions'::regclass
    and contype='f' and confrelid='banking.transactions'::regclass and confdeltype='r')
 then raise exception 'tax_settlement_predecessor_contracts_required'; end if;
 if exists(select 1 from public.holding_actions where action_type <> 'tax_settlement') then
  raise exception 'tax_settlement_unexpected_sibling_rows';
 end if;
 if exists(select 1 from pg_trigger where tgrelid='public.holding_actions'::regclass and not tgisinternal
   and tgname <> 'company_archive_track_holding_actions') then raise exception 'tax_settlement_unexpected_source_trigger'; end if;
 perform company_tax_filing.assert_source_record_v1(to_jsonb(s)) from public.holding_actions s;
 v_generation_before := (select coalesce(jsonb_agg(to_jsonb(g) order by company_id,income_year),'[]'::jsonb) from public.company_archive_source_generations g);
 -- Preserve source SQL metadata before retiring its physical relation. Only the
 -- migration owner can access this immutable inventory; rollback checks its hash.
 v_inventory := jsonb_build_object(
  'owner',(select pg_get_userbyid(relowner) from pg_class where oid='public.holding_actions'::regclass),
  'rls',(select relrowsecurity from pg_class where oid='public.holding_actions'::regclass),
  'forceRls',(select relforcerowsecurity from pg_class where oid='public.holding_actions'::regclass),
  'columns',(select jsonb_agg(jsonb_build_object('name',a.attname,'type',format_type(a.atttypid,a.atttypmod),'notNull',a.attnotnull,'default',pg_get_expr(d.adbin,d.adrelid)) order by a.attnum)
    from pg_attribute a left join pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum
    where a.attrelid='public.holding_actions'::regclass and a.attnum>0 and not a.attisdropped),
  'constraints',(select jsonb_agg(jsonb_build_object('name',conname,'definition',pg_get_constraintdef(oid)) order by conname) from pg_constraint where conrelid='public.holding_actions'::regclass),
  'policies',(select coalesce(jsonb_agg(jsonb_build_object('name',polname,'command',polcmd,'permissive',polpermissive,'roles',(select jsonb_agg(case when r=0 then 'public' else pg_get_userbyid(r) end) from unnest(polroles) r),'using',pg_get_expr(polqual,polrelid),'check',pg_get_expr(polwithcheck,polrelid)) order by polname),'[]'::jsonb) from pg_policy where polrelid='public.holding_actions'::regclass),
  'triggers',(select coalesce(jsonb_agg(jsonb_build_object('name',tgname,'definition',pg_get_triggerdef(oid),'mode',tgenabled) order by tgname),'[]'::jsonb) from pg_trigger where tgrelid='public.holding_actions'::regclass and not tgisinternal),
  'grants',(select coalesce(jsonb_agg(jsonb_build_object('role',case when x.grantee=0 then 'public' else pg_get_userbyid(x.grantee) end,'privilege',x.privilege_type,'grantable',x.is_grantable) order by x.grantee,x.privilege_type),'[]'::jsonb) from pg_class c cross join lateral aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) x where c.oid='public.holding_actions'::regclass)
 );
 insert into backend_system.tax_settlement_migration_inventory(resource,definition,definition_sha256)
 values('public.holding_actions',v_inventory,encode(extensions.digest(v_inventory::text,'sha256'),'hex')) on conflict do nothing;
 foreach v_resource in array array['backend_system.prepare_tax_settlement_v1(jsonb,text)','backend_system.complete_tax_settlement_v1(jsonb,uuid,jsonb,text)'] loop
  select jsonb_build_object('sql',pg_get_functiondef(p.oid),'owner',pg_get_userbyid(proowner),
    'grants',(select jsonb_agg(jsonb_build_object('role',case when x.grantee=0 then 'public' else pg_get_userbyid(x.grantee) end,'grantable',x.is_grantable) order by x.grantee) from aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) x where x.privilege_type='EXECUTE'))
   into v_definition from pg_proc p where p.oid=to_regprocedure(v_resource);
  if v_definition is null then raise exception 'tax_settlement_original_writer_missing'; end if;
  insert into backend_system.tax_settlement_migration_inventory(resource,definition,definition_sha256)
  values(v_resource,v_definition,encode(extensions.digest(v_definition::text,'sha256'),'hex')) on conflict do nothing;
 end loop;
 if exists(select 1 from backend_system.tax_settlement_migration_inventory where definition_sha256<>encode(extensions.digest(definition::text,'sha256'),'hex')) then
  raise exception 'tax_settlement_inventory_corrupt'; end if;
 insert into backend_system.tax_settlement_source_rows(source_id,source_sha256,payload)
 select id,encode(extensions.digest(to_jsonb(s)::text,'sha256'),'hex'),to_jsonb(s) from public.holding_actions s on conflict do nothing;
 if exists(select 1 from backend_system.tax_settlement_source_rows where source_sha256<>encode(extensions.digest(payload::text,'sha256'),'hex'))
  or exists(select 1 from backend_system.tax_settlement_quarantine where payload_sha256<>encode(extensions.digest(payload::text,'sha256'),'hex')) then
  raise exception 'tax_settlement_preserved_evidence_corrupt'; end if;
 if v_phase='expanded' and exists(select 1 from company_tax_filing.settlements t where not exists(
  select 1 from backend_system.tax_settlement_source_rows s where s.source_id=t.id and s.payload=to_jsonb(t))) then
  raise exception 'tax_settlement_unproven_target_rows'; end if;
 -- The inactive expanded target may be stale relative to the single old writer.
 -- At rollback/recutover every surviving target must already match source evidence.
 if v_phase='rolled_back' and exists(select 1 from company_tax_filing.settlements t left join public.holding_actions s using(id)
   where s.id is null or to_jsonb(s)<>to_jsonb(t)) then raise exception 'tax_settlement_recutover_conflict'; end if;
 drop trigger if exists company_archive_track_tax_settlements on company_tax_filing.settlements;
 delete from company_tax_filing.settlements;
 insert into company_tax_filing.settlements select * from public.holding_actions;
 select count(*),encode(extensions.digest(coalesce(string_agg(to_jsonb(s)::text,E'\n' order by id),''),'sha256'),'hex')
 into v_source_count,v_source_digest from public.holding_actions s;
 select count(*),encode(extensions.digest(coalesce(string_agg(to_jsonb(s)::text,E'\n' order by id),''),'sha256'),'hex')
 into v_target_count,v_target_digest from company_tax_filing.settlements s;
 insert into backend_system.tax_settlement_reconciliations(phase,source_count,target_count,source_digest,target_digest)
 values('cutover',v_source_count,v_target_count,v_source_digest,v_target_digest);
 revoke all on function backend_system.prepare_tax_settlement_v1(jsonb,text),backend_system.complete_tax_settlement_v1(jsonb,uuid,jsonb,text)
 from public,anon,authenticated,service_role,ledger_workflow_executor,talli_ledger_backend;
 drop table public.holding_actions;
 create view public.holding_actions with (security_barrier=true) as select * from company_tax_filing.settlements;
 alter view public.holding_actions owner to company_tax_filing_store_owner;
 revoke all on public.holding_actions from public,anon,authenticated,service_role;
 grant select on public.holding_actions to authenticated,documents_store_owner;
 create trigger company_archive_track_tax_settlements before insert or update or delete on company_tax_filing.settlements
 for each row execute function public.company_archive_track_source_write_v1('year','company_id');
 if v_generation_before is distinct from (select coalesce(jsonb_agg(to_jsonb(g) order by company_id,income_year),'[]'::jsonb) from public.company_archive_source_generations g) then
  raise exception 'tax_settlement_migration_changed_archive_generation'; end if;
 update backend_system.tax_settlement_migration_state set phase='cutover',changed_at=now() where singleton;
end;
$cutover$;
grant execute on function company_tax_filing.prepare_settlement_v1(jsonb,text),company_tax_filing.complete_settlement_v1(jsonb,uuid,text),
 ledger.post_company_tax_settlement_v1(text,uuid,integer,text,jsonb,text,text,text),
 banking.prepare_tax_settlement_transaction_v1(jsonb,text),banking.claim_tax_settlement_transaction_v1(jsonb,text),
 documents.lock_metadata_binding_v1(uuid,uuid,integer,text) to company_tax_filing_workflow_executor;
grant company_tax_filing_workflow_executor to talli_ledger_backend with inherit false,set true;
revoke create on schema public from company_tax_filing_store_owner;
do $cleanup$
begin
 execute format('revoke company_tax_filing_store_owner,company_tax_filing_workflow_executor,company_tax_filing_ledger_bridge_owner,banking_store_owner,documents_store_owner,company_archive_projection_executor from %I',current_user);
end;
$cleanup$;
commit;
