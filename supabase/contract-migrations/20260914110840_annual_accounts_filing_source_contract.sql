-- #153 positive company/year source coverage. Installed after filing expansion;
-- execution remains unavailable before cutover and after rollback.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table accounts153_source_borrowed_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text:='annual_accounts_filing_store_owner'; v_prior jsonb; begin
 if not pg_catalog.pg_has_role(current_user,r,'SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into v_prior
  from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user)
   and m.grantor=(select oid from pg_catalog.pg_roles where rolname=current_user);
  insert into accounts153_source_borrowed_roles values(r,v_prior);
  execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
 end if;
end; $borrow$;
set local role annual_accounts_filing_store_owner;

create function annual_accounts_filing.read_source_snapshot_v1(p_company uuid,p_year integer,p_subject text) returns jsonb
language plpgsql volatile security definer set search_path='' as $function$
declare workspace jsonb; inventory jsonb; coverage jsonb; source_revision text; phase text;
 families constant text[]:=array['filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs'];
 row_keys constant text[]:=array['previews','submissions','overrides','review_comments','permissions','test_evidence'];
 counts jsonb:='{}'::jsonb; digests jsonb:='{}'::jsonb; i integer; valid_inventory boolean;
 reconciled text[]; retained_ids jsonb; fences_valid boolean; modes_valid boolean; extent_valid boolean;
begin
 perform annual_accounts_filing.verified_filing_actor_v1(p_subject);
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'annual_accounts_not_found'; end if;
 if p_year is null or p_year not between 2000 and 2100 then raise exception 'annual_accounts_invalid_input'; end if;
 if pg_catalog.current_setting('transaction_isolation') not in ('repeatable read','serializable') then
  raise exception 'annual_accounts_unavailable';
 end if;
 phase:=annual_accounts_filing.filing_phase_v1();
 if phase is null or phase not in ('cutover','contracted') then raise exception 'annual_accounts_unavailable'; end if;
 workspace:=annual_accounts_filing.read_workspace_v1(p_company,p_year,p_subject);
 select s.source_revision into source_revision from backend_system.annual_accounts_migration_state s where singleton;
 select pg_catalog.jsonb_object_agg(resource,definition_sha256 order by resource),
  count(*) filter(where resource=any(array(select 'table:public.'||f.name from unnest(families) as f(name))))=6
   and pg_catalog.bool_and(definition_sha256=pg_catalog.encode(extensions.digest(definition::text,'sha256'),'hex'))
 into inventory,valid_inventory from backend_system.annual_accounts_migration_inventory;
 select coalesce(array_agg(distinct family order by family),'{}'::text[]) into reconciled
 from backend_system.annual_accounts_reconciliations r
 where r.phase='cutover' and r.source_count=r.target_count and r.source_digest=r.target_digest and r.family=any(families);
 -- Historical identities must not disappear from the current source. Keep only
 -- this company's requested year; no sibling or other-company row is disclosed.
 select coalesce(pg_catalog.jsonb_agg(source_id order by source_id),'[]'::jsonb) into retained_ids
 from (select distinct source_id from backend_system.annual_accounts_source_rows
       where family='filing_submissions' and classification='accounts'
         and payload->>'company_id'=p_company::text and payload->>'income_year'=p_year::text) preserved;
 for i in 1..6 loop
  counts:=counts||pg_catalog.jsonb_build_object(families[i],pg_catalog.jsonb_array_length(workspace->row_keys[i]));
  digests:=digests||pg_catalog.jsonb_build_object(families[i],pg_catalog.encode(extensions.digest((workspace->row_keys[i])::text,'sha256'),'hex'));
 end loop;
 -- Source coverage is bound to the declared six-table Accounts extent. An added
 -- journal/store needs a new source contract before history can be complete.
 select count(*)=6 and pg_catalog.bool_and(c.relname=any(families)) into extent_valid
 from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid=c.relnamespace
 where n.nspname='annual_accounts_filing' and c.relkind in ('r','p');
 -- Check the exact installed fences, not merely their names. A changed legacy
 -- writer barrier cannot support a claim that the owned store is complete.
 select count(*)=6 and pg_catalog.bool_and(x.convalidated and pg_catalog.pg_get_constraintdef(x.oid)='CHECK (false)') into fences_valid
 from pg_catalog.pg_constraint x join pg_catalog.pg_class c on c.oid=x.conrelid
 join pg_catalog.pg_namespace n on n.oid=c.relnamespace
 where n.nspname='public' and c.relname=any(families)
  and x.conname='accounts153_legacy_writer_retired' and x.contype='c';
 fences_valid := coalesce(fences_valid,false) or coalesce(annual_accounts_filing.generic_store_retired_v1(),false);
 -- Retain the predecessor's declared mode checks. Production-labelled legacy
 -- adapter records still need explicit unknown handling by the owner projector.
 select count(*)=3 and pg_catalog.bool_and(x.convalidated and pg_catalog.pg_get_constraintdef(x.oid)=original->>'definition') into modes_valid
 from pg_catalog.pg_constraint x
 join backend_system.annual_accounts_migration_inventory m on m.resource='table:public.filing_submissions'
 cross join lateral pg_catalog.jsonb_array_elements(m.definition->'constraints') original
 where x.conrelid='annual_accounts_filing.filing_submissions'::regclass
  and x.conname in ('filing_submissions_mode_check','filing_submissions_adapter_mode_check','filing_submissions_authority_mode_shape_check')
  and x.conname=original->>'name' and x.contype='c';
 coverage:=pg_catalog.jsonb_build_object(
  'scope','talli_recorded_annual_accounts','companyId',p_company,'incomeYear',p_year,
  'sourceRevision',source_revision,'phase',phase,'inventory',inventory,
  'inventoryValid',coalesce(valid_inventory,false),'reconciledFamilies',reconciled,
  'quarantineClear',not exists(select 1 from backend_system.annual_accounts_quarantine),
  'sourceRowsValid',not exists(select 1 from backend_system.annual_accounts_source_rows
    where source_sha256<>pg_catalog.encode(extensions.digest(payload::text,'sha256'),'hex')),
  'retainedSubmissionIds',retained_ids,'familyCounts',counts,'familyDigests',digests,
  'legacyFencesValid',coalesce(fences_valid,false),'modeChecksValid',coalesce(modes_valid,false),
  'declaredExtentValid',coalesce(extent_valid,false));
 return pg_catalog.jsonb_build_object('companyId',p_company,'incomeYear',p_year,
  'asOf',pg_catalog.transaction_timestamp(),'workspace',workspace,'coverage',coverage,'completeEnumeration',true);
end; $function$;
revoke all on function annual_accounts_filing.read_source_snapshot_v1(uuid,integer,text) from public,anon,authenticated,service_role;
grant execute on function annual_accounts_filing.read_source_snapshot_v1(uuid,integer,text) to annual_accounts_filing_workflow_executor;
reset role;
do $restore$ declare r record; begin
 for r in select * from accounts153_source_borrowed_roles loop
  if r.prior is null then
   execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  else
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
