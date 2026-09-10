-- Reviewed draft: reverse only the indicated #151 phase, never application deployment.
-- Canonical journal OIDs/records, hashes, references, IDs and active leases remain in place.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:rf1086:capability:v1',0));
do $guard$ begin
 if shareholder_register_filing.phase_v1() is distinct from 'contracted' then raise exception 'rf1086_phase_rollback_wrong_phase'; end if;
 if (select count(*) from pg_catalog.jsonb_object_keys((select original_relations from shareholder_register_filing.migration_state where singleton)))<>12
 then raise exception 'rf1086_original_metadata_incomplete'; end if;
end; $guard$;
create temporary table rf151_borrowed_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text; v_prior jsonb; begin
  foreach r in array array['shareholder_register_filing_store_owner','shareholder_register_filing_executor','ledger_store_owner','ledger_workflow_store_owner','company_access_executor','authority_connections_store_owner','billing_store_owner','documents_store_owner','company_archive_projection_executor'] loop
    if not pg_catalog.pg_has_role(current_user,r,'SET') then
      select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into v_prior
      from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
        and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user)
        and m.grantor=(select oid from pg_catalog.pg_roles where rolname=current_user);
      insert into rf151_borrowed_roles values(r,v_prior);
      execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
    end if;
  end loop;
end; $borrow$;

create temporary table rf151_schema_grants on commit drop as select
 not pg_catalog.has_schema_privilege('ledger_store_owner','ledger','CREATE') as ledger_create,false as company_access_create,not pg_catalog.has_schema_privilege('ledger_workflow_store_owner','backend_system','CREATE') as workflow_create,
 not pg_catalog.has_schema_privilege(current_user,'backend_system','CREATE') as backend_create;
grant create on schema ledger to ledger_store_owner;
grant create on schema backend_system to ledger_workflow_store_owner;
do $schema_grant$ begin execute pg_catalog.format('grant create on schema backend_system to %I',current_user); end; $schema_grant$;
-- SECTION A: recreate only absent original opening tables from pre-move metadata.
create temporary table rf151_reconstructed_openings(name text primary key) on commit drop;
do $reconstruct_opening_tables$
declare
  original_schema jsonb; original_relations jsonb; table_name text; shape jsonb;
  column_spec jsonb; constraint_spec jsonb; index_spec jsonb; column_position integer;
  expected_columns text[]; expected_types text[]; actual_columns text[];
  expected_default text; expected_not_null boolean; present_count integer;
begin
  select s.original_opening_schema,s.original_relations into original_schema,original_relations
    from shareholder_register_filing.migration_state s where singleton;
  if (select pg_catalog.array_agg(key order by key) from pg_catalog.jsonb_object_keys(original_schema) key)
    is distinct from array['opening_balance_setups','opening_shareholders']
  then raise exception 'rf1086_original_opening_schema_missing'; end if;
  select count(*) into present_count from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid=c.relnamespace
    where n.nspname='public' and c.relname=any(array['opening_balance_setups','opening_shareholders']);
  if present_count=2 then
    if exists(select 1 from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid=c.relnamespace
      where n.nspname='public' and c.relname=any(array['opening_balance_setups','opening_shareholders']) and c.relkind<>'r')
    then raise exception 'rf1086_existing_opening_relation_is_not_original_table'; end if;
    return;
  elsif present_count<>0 then raise exception 'rf1086_partial_opening_drop'; end if;
  if exists(select 1 from pg_catalog.pg_attribute
    where attrelid='ledger.entries'::regclass and attname='setup_id' and not attisdropped)
  then raise exception 'rf1086_opening_reconstruction_requires_retired_ledger_setup'; end if;
  -- Validate both complete, original column shapes before either CREATE.
  foreach table_name in array array['opening_balance_setups','opening_shareholders'] loop
    shape:=original_schema->table_name;
    if original_relations->table_name->>'owner' is distinct from current_user
      or pg_catalog.jsonb_typeof(shape->'columns') is distinct from 'array'
      or pg_catalog.jsonb_typeof(shape->'constraints') is distinct from 'array'
      or pg_catalog.jsonb_typeof(shape->'indexes') is distinct from 'array'
      or pg_catalog.jsonb_typeof(shape->'triggers') is distinct from 'array'
      or not(shape ? 'rls_enabled')
    then raise exception 'rf1086_original_opening_schema_invalid'; end if;
    expected_columns:=case table_name
      when 'opening_balance_setups' then array['id','company_id','income_year','bank_balance','share_capital','share_count','nominal_value','locked_at','created_by','created_at']
      else array['id','setup_id','company_id','name','shareholder_kind','national_id','org_number','share_count','created_by','created_at'] end;
    expected_types:=case table_name
      when 'opening_balance_setups' then array['uuid','uuid','integer','numeric','numeric','integer','numeric','timestamp with time zone','uuid','timestamp with time zone']
      else array['uuid','uuid','uuid','text','text','text','text','integer','uuid','timestamp with time zone'] end;
    select pg_catalog.array_agg(value->>'name' order by (value->>'attnum')::integer) into actual_columns
      from pg_catalog.jsonb_array_elements(shape->'columns');
    if actual_columns is distinct from expected_columns
    then raise exception 'rf1086_original_opening_columns_changed'; end if;
    column_position:=0;
    for column_spec in select value from pg_catalog.jsonb_array_elements(shape->'columns') order by (value->>'attnum')::integer loop
      column_position:=column_position+1;
      expected_default:=case
        when column_position=1 then 'gen_random_uuid()'
        when column_position=10 or (table_name='opening_balance_setups' and column_position=8) then 'now()'
        else null end;
      expected_not_null:=not(table_name='opening_shareholders' and column_position in (6,7));
      if (column_spec->>'attnum')::integer is distinct from column_position
        or column_spec->>'format_type' is distinct from expected_types[column_position]
        or (column_spec->>'not_null')::boolean is distinct from expected_not_null
        or column_spec->>'default_sql' is distinct from expected_default
        or column_spec->>'identity' is distinct from '' or column_spec->>'generated' is distinct from ''
        or column_spec->>'collation_schema' is not null or column_spec->>'collation_name' is not null
      then raise exception 'rf1086_original_opening_column_unsupported'; end if;
    end loop;
  end loop;
  -- Exact original columns from 0001; constraints and indexes below use captured definitions.
  create table if not exists public.opening_balance_setups (
    id uuid not null default pg_catalog.gen_random_uuid(),
    company_id uuid not null,
    income_year integer not null,
    bank_balance numeric not null,
    share_capital numeric not null,
    share_count integer not null,
    nominal_value numeric not null,
    locked_at timestamp with time zone not null default pg_catalog.now(),
    created_by uuid not null,
    created_at timestamp with time zone not null default pg_catalog.now()
  );
  create table if not exists public.opening_shareholders (
    id uuid not null default pg_catalog.gen_random_uuid(),
    setup_id uuid not null,
    company_id uuid not null,
    name text not null,
    shareholder_kind text not null,
    national_id text,
    org_number text,
    share_count integer not null,
    created_by uuid not null,
    created_at timestamp with time zone not null default pg_catalog.now()
  );
  insert into rf151_reconstructed_openings values('opening_balance_setups'),('opening_shareholders');
  -- Both tables exist before FK restoration; primary/unique constraints precede references.
  foreach table_name in array array['opening_balance_setups','opening_shareholders'] loop
    for constraint_spec in select value from pg_catalog.jsonb_array_elements(original_schema->table_name->'constraints')
      order by case when value->>'type' in ('p','u') then 0 when value->>'type'='f' then 2 else 1 end,value->>'name' loop
      execute pg_catalog.format('alter table public.%I add constraint %I %s',table_name,constraint_spec->>'name',constraint_spec->>'definition');
      if (select c.convalidated from pg_catalog.pg_constraint c where c.conrelid=pg_catalog.to_regclass('public.'||table_name) and c.conname=constraint_spec->>'name')
        is distinct from (constraint_spec->>'validated')::boolean
      then raise exception 'rf1086_original_opening_constraint_validation_changed'; end if;
    end loop;
    for index_spec in select value from pg_catalog.jsonb_array_elements(original_schema->table_name->'indexes') loop
      execute index_spec->>'definition';
    end loop;
  end loop;
end; $reconstruct_opening_tables$;


lock table public.opening_balance_setups,public.opening_shareholders,public.filing_previews,public.filing_submissions,public.filing_overrides,public.filing_review_comments,public.authority_permissions,public.authority_test_runs,shareholder_register_filing.opening_balance_setups,shareholder_register_filing.opening_shareholders,shareholder_register_filing.filing_previews,shareholder_register_filing.filing_submissions,shareholder_register_filing.filing_overrides,shareholder_register_filing.filing_review_comments,shareholder_register_filing.authority_permissions,shareholder_register_filing.authority_test_runs,shareholder_register_filing.filing_approval_snapshots,shareholder_register_filing.production_filing_submissions,shareholder_register_filing.production_filing_events,shareholder_register_filing.production_feedback_artifacts,ledger.opening_bank_inputs in access exclusive mode;
create temporary table rf151_saved_objects on commit drop as
 select original_objects,original_relations from shareholder_register_filing.migration_state where singleton;
-- These drafts preserve the original migration-owner path, not arbitrary DDL authority.
do $migration_owner$ declare n text; begin
 foreach n in array array['opening_balance_setups','opening_shareholders','filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs'] loop
  if (select original_relations->n->>'owner' from rf151_saved_objects) is distinct from current_user
  then raise exception 'rf1086_original_migration_owner_required'; end if;
 end loop;
end; $migration_owner$;

-- A bounded migration-only SELECT policy is removed before COMMIT. Existing
-- force-RLS flags and grants are preserved; no application role receives it.
create temporary table rf151_reverse_read_access(relation text primary key,owner name,had_select boolean) on commit drop;
create temporary table rf151_reverse_hashes(relation text primary key,digest text) on commit drop;
create temporary table rf151_reverse_triggers(relation text,name name,enabled "char",primary key(relation,name)) on commit drop;
do $read_snapshot$ declare relation text; owner_role name; migration_role name:=current_user; had_select boolean; digest text; begin
 foreach relation in array array['shareholder_register_filing.opening_balance_setups','shareholder_register_filing.opening_shareholders','shareholder_register_filing.filing_previews','shareholder_register_filing.filing_submissions','shareholder_register_filing.filing_overrides','shareholder_register_filing.filing_review_comments','shareholder_register_filing.authority_permissions','shareholder_register_filing.authority_test_runs','shareholder_register_filing.filing_approval_snapshots','shareholder_register_filing.production_filing_submissions','shareholder_register_filing.production_filing_events','shareholder_register_filing.production_feedback_artifacts','ledger.opening_bank_inputs','shareholder_register_filing.migration_inventory','shareholder_register_filing.migration_quarantine'] loop
  select pg_catalog.pg_get_userbyid(c.relowner),exists(select 1 from pg_catalog.aclexplode(c.relacl) a
   where a.grantee=(select oid from pg_catalog.pg_roles where rolname=migration_role) and a.privilege_type='SELECT')
  into owner_role,had_select from pg_catalog.pg_class c where c.oid=pg_catalog.to_regclass(relation);
  if owner_role is null then raise exception 'rf1086_reverse_relation_missing'; end if;
  insert into rf151_reverse_read_access values(relation,owner_role,had_select);
  execute pg_catalog.format('set local role %I',owner_role);
  if owner_role<>migration_role then execute pg_catalog.format('grant select on %s to %I',relation,migration_role); end if;
  execute pg_catalog.format('create policy rf151_reverse_read_snapshot on %s for select to %I using(true)',relation,migration_role);
  execute 'reset role';
  execute pg_catalog.format('select pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E''\n'' order by pg_catalog.to_jsonb(t)::text),pg_catalog.left(''x'',0)),''sha256''),''hex'') from %s t',relation) into digest;
  insert into rf151_reverse_hashes values(relation,digest);
 end loop;
end; $read_snapshot$;
-- Avoid turning projection refresh into business/archive writes. Restore every
-- original trigger enable mode; internal FK constraints are never disabled.
do $suspend_projection_triggers$ declare t record; begin
 for t in select n.nspname||'.'||c.relname relation,g.tgname,g.tgenabled
  from pg_catalog.pg_trigger g join pg_catalog.pg_class c on c.oid=g.tgrelid
  join pg_catalog.pg_namespace n on n.oid=c.relnamespace
  where n.nspname='public' and c.relname=any(array['opening_balance_setups','opening_shareholders','filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs']) and not g.tgisinternal loop
  insert into rf151_reverse_triggers values(t.relation,t.tgname,t.tgenabled);
  execute pg_catalog.format('alter table %s disable trigger %I',t.relation,t.tgname);
 end loop;
end; $suspend_projection_triggers$;
-- SECTION B: copy into new original tables only. No triggers yet, so no archive effects.
-- Original FK/check constraints stay active throughout. RLS/ACL restored in C before COMMIT.
do $restore_opening_rows$
declare q record; table_name text; expected_keys text[]; keys text[];
begin
  if not exists(select 1 from rf151_reconstructed_openings) then return; end if;
  if exists(select 1 from shareholder_register_filing.opening_balance_setups r
    left join ledger.opening_bank_inputs b on b.snapshot_id=r.id and b.company_id=r.company_id and b.income_year=r.income_year
    where b.snapshot_id is null or b.recorded_by is distinct from r.created_by or b.recorded_at is distinct from r.created_at)
  then raise exception 'rf1086_rollback_bank_input_missing'; end if;
  insert into public.opening_balance_setups(id,company_id,income_year,bank_balance,share_capital,share_count,nominal_value,locked_at,created_by,created_at)
    select r.id,r.company_id,r.income_year,b.bank_balance_nok,r.share_capital,r.share_count,r.nominal_value,r.locked_at,r.created_by,r.created_at
    from shareholder_register_filing.opening_balance_setups r join ledger.opening_bank_inputs b
      on b.snapshot_id=r.id and b.company_id=r.company_id and b.income_year=r.income_year;
  -- Quarantine is retained historical evidence; do not silently discard or merge its identity.
  foreach table_name in array array['opening_balance_setups','opening_shareholders'] loop
    select pg_catalog.array_agg(a.attname::text order by a.attname::text) into expected_keys from pg_catalog.pg_attribute a
      where a.attrelid=pg_catalog.to_regclass('public.'||table_name) and a.attnum>0 and not a.attisdropped;
    for q in select * from shareholder_register_filing.migration_quarantine where family=table_name order by record_id loop
      select pg_catalog.array_agg(key order by key) into keys from pg_catalog.jsonb_object_keys(q.original_row) key;
      if keys is distinct from expected_keys or (q.original_row->>'id')::uuid is distinct from q.record_id
      then raise exception 'rf1086_quarantined_opening_record_invalid'; end if;
      if table_name='opening_balance_setups' and not exists(select 1 from ledger.opening_bank_inputs b
        where b.snapshot_id=q.record_id and b.company_id=(q.original_row->>'company_id')::uuid
          and b.income_year=(q.original_row->>'income_year')::integer
          and b.recorded_by=(q.original_row->>'created_by')::uuid
          and b.recorded_at=(q.original_row->>'created_at')::timestamptz
          and b.bank_balance_nok=(q.original_row->>'bank_balance')::numeric)
      then raise exception 'rf1086_quarantined_opening_bank_binding_invalid'; end if;
      -- Any canonical/quarantine identity collision raises through the original PK.
      execute pg_catalog.format('insert into public.%I select * from pg_catalog.jsonb_populate_record(null::public.%I,$1)',table_name,table_name) using q.original_row;
    end loop;
  end loop;
  insert into public.opening_shareholders(id,setup_id,company_id,name,shareholder_kind,national_id,org_number,share_count,created_by,created_at)
    select id,setup_id,company_id,name,shareholder_kind,national_id,org_number,share_count,created_by,created_at
    from shareholder_register_filing.opening_shareholders;
  if (select count(*) from public.opening_balance_setups)<>(select count(*) from shareholder_register_filing.opening_balance_setups)+(select count(*) from shareholder_register_filing.migration_quarantine where family='opening_balance_setups')
    or (select count(*) from public.opening_shareholders)<>(select count(*) from shareholder_register_filing.opening_shareholders)+(select count(*) from shareholder_register_filing.migration_quarantine where family='opening_shareholders')
  then raise exception 'rf1086_opening_reconstruction_extent_mismatch'; end if;
end; $restore_opening_rows$;


-- SECTION E: after B, before canonical storage can be removed; original two
-- incoming generic setup FKs return to public. No Ledger column/FK is recreated.
-- Exact predecessor constraints: public.filing_previews/filing_submissions,
-- setup_id -> public.opening_balance_setups(id), ON DELETE RESTRICT, immediate.
do $restore_public_opening_references$
declare table_name text; constraint_name text; original_constraint record; setup_att smallint; id_att smallint;
begin
  if not exists(select 1 from rf151_reconstructed_openings) then return; end if;
  select attnum into id_att from pg_catalog.pg_attribute where attrelid='public.opening_balance_setups'::regclass and attname='id';
  foreach table_name in array array['filing_previews','filing_submissions'] loop
    constraint_name:=table_name||'_setup_id_fkey';
    select attnum into setup_att from pg_catalog.pg_attribute where attrelid=pg_catalog.to_regclass('public.'||table_name) and attname='setup_id';
    select * into original_constraint from pg_catalog.pg_constraint
      where conrelid=pg_catalog.to_regclass('public.'||table_name) and conname=constraint_name;
    if not found or original_constraint.contype<>'f' or original_constraint.conkey<>array[setup_att]
      or original_constraint.confdeltype<>'r' or original_constraint.confupdtype<>'a'
      or original_constraint.condeferrable or original_constraint.condeferred or not original_constraint.convalidated
      or original_constraint.confrelid not in ('public.opening_balance_setups'::regclass,'shareholder_register_filing.opening_balance_setups'::regclass)
    then raise exception 'rf1086_original_incoming_opening_constraint_changed'; end if;
    if original_constraint.confrelid='public.opening_balance_setups'::regclass then
      if original_constraint.confkey<>array[id_att] then raise exception 'rf1086_original_incoming_opening_key_changed'; end if;
    else
      if original_constraint.confkey<>array[(select attnum from pg_catalog.pg_attribute where attrelid='shareholder_register_filing.opening_balance_setups'::regclass and attname='id')]
      then raise exception 'rf1086_canonical_incoming_opening_key_changed'; end if;
      execute pg_catalog.format('alter table public.%I drop constraint %I',table_name,constraint_name);
      execute pg_catalog.format('alter table public.%I add constraint %I foreign key(setup_id) references public.opening_balance_setups(id) on delete restrict',table_name,constraint_name);
    end if;
  end loop;
end; $restore_public_opening_references$;

-- Exact original bank-input relationship is necessary before restoring a source projection.
do $bank_binding$ begin
 if exists(select 1 from shareholder_register_filing.opening_balance_setups r
 left join ledger.opening_bank_inputs b on b.snapshot_id=r.id and b.company_id=r.company_id and b.income_year=r.income_year
 where b.snapshot_id is null or b.recorded_by is distinct from r.created_by or b.recorded_at is distinct from r.created_at)
 then raise exception 'rf1086_rollback_bank_input_missing'; end if;
end; $bank_binding$;

do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.opening_balance_setups r join public.opening_balance_setups p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('opening_balance_setups',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.opening_balance_setups(id,company_id,income_year,bank_balance,share_capital,share_count,nominal_value,locked_at,created_by,created_at) select r.id,r.company_id,r.income_year,b.bank_balance_nok,r.share_capital,r.share_count,r.nominal_value,r.locked_at,r.created_by,r.created_at from shareholder_register_filing.opening_balance_setups r join ledger.opening_bank_inputs b on b.snapshot_id=r.id and b.company_id=r.company_id and b.income_year=r.income_year on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,income_year=excluded.income_year,bank_balance=excluded.bank_balance,share_capital=excluded.share_capital,share_count=excluded.share_count,nominal_value=excluded.nominal_value,locked_at=excluded.locked_at,created_by=excluded.created_by,created_at=excluded.created_at;
do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.opening_shareholders r join public.opening_shareholders p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('opening_shareholders',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.opening_shareholders(id,setup_id,company_id,name,shareholder_kind,national_id,org_number,share_count,created_by,created_at) select r.id,r.setup_id,r.company_id,r.name,r.shareholder_kind,r.national_id,r.org_number,r.share_count,r.created_by,r.created_at from shareholder_register_filing.opening_shareholders r on conflict(id) do update set id=excluded.id,setup_id=excluded.setup_id,company_id=excluded.company_id,name=excluded.name,shareholder_kind=excluded.shareholder_kind,national_id=excluded.national_id,org_number=excluded.org_number,share_count=excluded.share_count,created_by=excluded.created_by,created_at=excluded.created_at;
do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.filing_previews r join public.filing_previews p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('filing_previews',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.filing_previews(id,company_id,setup_id,income_year,filing,status,issues,preview,hovedskjema_xml,underskjema_xml,source,created_by,created_at) select r.id,r.company_id,r.setup_id,r.income_year,r.filing,r.status,r.issues,r.preview,r.hovedskjema_xml,r.underskjema_xml,r.source,r.created_by,r.created_at from shareholder_register_filing.filing_previews r on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,setup_id=excluded.setup_id,income_year=excluded.income_year,filing=excluded.filing,status=excluded.status,issues=excluded.issues,preview=excluded.preview,hovedskjema_xml=excluded.hovedskjema_xml,underskjema_xml=excluded.underskjema_xml,source=excluded.source,created_by=excluded.created_by,created_at=excluded.created_at;
do $restore_generic_quarantine$
declare q record; existing_row jsonb; expected_keys text[]; actual_keys text[];
begin
 select array_agg(a.attname::text order by a.attname::text) into expected_keys from pg_catalog.pg_attribute a
 where a.attrelid='public.filing_previews'::regclass and a.attnum>0 and not a.attisdropped;
 for q in select * from shareholder_register_filing.migration_quarantine where family='filing_previews' order by record_id loop
  select array_agg(key order by key) into actual_keys from jsonb_object_keys(q.original_row) key;
  if actual_keys is distinct from expected_keys or (q.original_row->>'id')::uuid is distinct from q.record_id
  then raise exception 'rf1086_quarantined_generic_record_invalid'; end if;
  if exists(select 1 from shareholder_register_filing.filing_previews where id=q.record_id)
  then raise exception 'rf1086_rollback_conflicting_projection'; end if;
  select to_jsonb(p) into existing_row from public.filing_previews p where id=q.record_id;
  if existing_row is not null and existing_row is distinct from q.original_row
  then raise exception 'rf1086_rollback_conflicting_projection'; end if;
  if existing_row is null then insert into public.filing_previews select * from jsonb_populate_record(null::public.filing_previews,q.original_row); end if;
 end loop;
end; $restore_generic_quarantine$;

do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.authority_permissions r join public.authority_permissions p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('authority_permissions',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.authority_permissions(id,company_id,obligation,submitter_user_id,confirmed_by,confirmed_at,production_enabled,updated_at) select r.id,r.company_id,r.obligation,r.submitter_user_id,r.confirmed_by,r.confirmed_at,r.production_enabled,r.updated_at from shareholder_register_filing.authority_permissions r on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,obligation=excluded.obligation,submitter_user_id=excluded.submitter_user_id,confirmed_by=excluded.confirmed_by,confirmed_at=excluded.confirmed_at,production_enabled=excluded.production_enabled,updated_at=excluded.updated_at;
do $restore_generic_quarantine$
declare q record; existing_row jsonb; expected_keys text[]; actual_keys text[];
begin
 select array_agg(a.attname::text order by a.attname::text) into expected_keys from pg_catalog.pg_attribute a
 where a.attrelid='public.authority_permissions'::regclass and a.attnum>0 and not a.attisdropped;
 for q in select * from shareholder_register_filing.migration_quarantine where family='authority_permissions' order by record_id loop
  select array_agg(key order by key) into actual_keys from jsonb_object_keys(q.original_row) key;
  if actual_keys is distinct from expected_keys or (q.original_row->>'id')::uuid is distinct from q.record_id
  then raise exception 'rf1086_quarantined_generic_record_invalid'; end if;
  if exists(select 1 from shareholder_register_filing.authority_permissions where id=q.record_id)
  then raise exception 'rf1086_rollback_conflicting_projection'; end if;
  select to_jsonb(p) into existing_row from public.authority_permissions p where id=q.record_id;
  if existing_row is not null and existing_row is distinct from q.original_row
  then raise exception 'rf1086_rollback_conflicting_projection'; end if;
  if existing_row is null then insert into public.authority_permissions select * from jsonb_populate_record(null::public.authority_permissions,q.original_row); end if;
 end loop;
end; $restore_generic_quarantine$;

do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.authority_test_runs r join public.authority_test_runs p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('authority_test_runs',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.authority_test_runs(id,company_id,obligation,environment,status,test_reference,feedback_summary,receipt_reference,archive_reference,evidence_url,payload_hash,recorded_by,recorded_at) select r.id,r.company_id,r.obligation,r.environment,r.status,r.test_reference,r.feedback_summary,r.receipt_reference,r.archive_reference,r.evidence_url,r.payload_hash,r.recorded_by,r.recorded_at from shareholder_register_filing.authority_test_runs r on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,obligation=excluded.obligation,environment=excluded.environment,status=excluded.status,test_reference=excluded.test_reference,feedback_summary=excluded.feedback_summary,receipt_reference=excluded.receipt_reference,archive_reference=excluded.archive_reference,evidence_url=excluded.evidence_url,payload_hash=excluded.payload_hash,recorded_by=excluded.recorded_by,recorded_at=excluded.recorded_at;
do $restore_generic_quarantine$
declare q record; existing_row jsonb; expected_keys text[]; actual_keys text[];
begin
 select array_agg(a.attname::text order by a.attname::text) into expected_keys from pg_catalog.pg_attribute a
 where a.attrelid='public.authority_test_runs'::regclass and a.attnum>0 and not a.attisdropped;
 for q in select * from shareholder_register_filing.migration_quarantine where family='authority_test_runs' order by record_id loop
  select array_agg(key order by key) into actual_keys from jsonb_object_keys(q.original_row) key;
  if actual_keys is distinct from expected_keys or (q.original_row->>'id')::uuid is distinct from q.record_id
  then raise exception 'rf1086_quarantined_generic_record_invalid'; end if;
  if exists(select 1 from shareholder_register_filing.authority_test_runs where id=q.record_id)
  then raise exception 'rf1086_rollback_conflicting_projection'; end if;
  select to_jsonb(p) into existing_row from public.authority_test_runs p where id=q.record_id;
  if existing_row is not null and existing_row is distinct from q.original_row
  then raise exception 'rf1086_rollback_conflicting_projection'; end if;
  if existing_row is null then insert into public.authority_test_runs select * from jsonb_populate_record(null::public.authority_test_runs,q.original_row); end if;
 end loop;
end; $restore_generic_quarantine$;

do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.filing_submissions r join public.filing_submissions p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('filing_submissions',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.filing_submissions(id,preview_id,company_id,setup_id,income_year,filing,mode,adapter_mode,payload_hash,idempotency_key,status,authority_confirmed_by,authority_confirmed_at,preview_confirmed_by,preview_confirmed_at,calls,receipt_id,feedback_document_ids,feedback_items,receipt_metadata,submitted_payload_ref,submitted_payload,failure_code,failure_message,created_by,submitted_by,created_at,updated_at,authority_test_run_id) select r.id,r.preview_id,r.company_id,r.setup_id,r.income_year,r.filing,r.mode,r.adapter_mode,r.payload_hash,r.idempotency_key,r.status,r.authority_confirmed_by,r.authority_confirmed_at,r.preview_confirmed_by,r.preview_confirmed_at,r.calls,r.receipt_id,r.feedback_document_ids,r.feedback_items,r.receipt_metadata,r.submitted_payload_ref,r.submitted_payload,r.failure_code,r.failure_message,r.created_by,r.submitted_by,r.created_at,r.updated_at,r.authority_test_run_id from shareholder_register_filing.filing_submissions r on conflict(id) do update set id=excluded.id,preview_id=excluded.preview_id,company_id=excluded.company_id,setup_id=excluded.setup_id,income_year=excluded.income_year,filing=excluded.filing,mode=excluded.mode,adapter_mode=excluded.adapter_mode,payload_hash=excluded.payload_hash,idempotency_key=excluded.idempotency_key,status=excluded.status,authority_confirmed_by=excluded.authority_confirmed_by,authority_confirmed_at=excluded.authority_confirmed_at,preview_confirmed_by=excluded.preview_confirmed_by,preview_confirmed_at=excluded.preview_confirmed_at,calls=excluded.calls,receipt_id=excluded.receipt_id,feedback_document_ids=excluded.feedback_document_ids,feedback_items=excluded.feedback_items,receipt_metadata=excluded.receipt_metadata,submitted_payload_ref=excluded.submitted_payload_ref,submitted_payload=excluded.submitted_payload,failure_code=excluded.failure_code,failure_message=excluded.failure_message,created_by=excluded.created_by,submitted_by=excluded.submitted_by,created_at=excluded.created_at,updated_at=excluded.updated_at,authority_test_run_id=excluded.authority_test_run_id;
do $restore_generic_quarantine$
declare q record; existing_row jsonb; expected_keys text[]; actual_keys text[];
begin
 select array_agg(a.attname::text order by a.attname::text) into expected_keys from pg_catalog.pg_attribute a
 where a.attrelid='public.filing_submissions'::regclass and a.attnum>0 and not a.attisdropped;
 for q in select * from shareholder_register_filing.migration_quarantine where family='filing_submissions' order by record_id loop
  select array_agg(key order by key) into actual_keys from jsonb_object_keys(q.original_row) key;
  if actual_keys is distinct from expected_keys or (q.original_row->>'id')::uuid is distinct from q.record_id
  then raise exception 'rf1086_quarantined_generic_record_invalid'; end if;
  if exists(select 1 from shareholder_register_filing.filing_submissions where id=q.record_id)
  then raise exception 'rf1086_rollback_conflicting_projection'; end if;
  select to_jsonb(p) into existing_row from public.filing_submissions p where id=q.record_id;
  if existing_row is not null and existing_row is distinct from q.original_row
  then raise exception 'rf1086_rollback_conflicting_projection'; end if;
  if existing_row is null then insert into public.filing_submissions select * from jsonb_populate_record(null::public.filing_submissions,q.original_row); end if;
 end loop;
end; $restore_generic_quarantine$;

do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.filing_overrides r join public.filing_overrides p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('filing_overrides',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.filing_overrides(id,preview_id,company_id,income_year,filing,field_target,old_value,new_value,reason,risk_level,owner_confirmed_by,owner_confirmed_at,created_by,created_at) select r.id,r.preview_id,r.company_id,r.income_year,r.filing,r.field_target,r.old_value,r.new_value,r.reason,r.risk_level,r.owner_confirmed_by,r.owner_confirmed_at,r.created_by,r.created_at from shareholder_register_filing.filing_overrides r on conflict(id) do update set id=excluded.id,preview_id=excluded.preview_id,company_id=excluded.company_id,income_year=excluded.income_year,filing=excluded.filing,field_target=excluded.field_target,old_value=excluded.old_value,new_value=excluded.new_value,reason=excluded.reason,risk_level=excluded.risk_level,owner_confirmed_by=excluded.owner_confirmed_by,owner_confirmed_at=excluded.owner_confirmed_at,created_by=excluded.created_by,created_at=excluded.created_at;
do $restore_generic_quarantine$
declare q record; existing_row jsonb; expected_keys text[]; actual_keys text[];
begin
 select array_agg(a.attname::text order by a.attname::text) into expected_keys from pg_catalog.pg_attribute a
 where a.attrelid='public.filing_overrides'::regclass and a.attnum>0 and not a.attisdropped;
 for q in select * from shareholder_register_filing.migration_quarantine where family='filing_overrides' order by record_id loop
  select array_agg(key order by key) into actual_keys from jsonb_object_keys(q.original_row) key;
  if actual_keys is distinct from expected_keys or (q.original_row->>'id')::uuid is distinct from q.record_id
  then raise exception 'rf1086_quarantined_generic_record_invalid'; end if;
  if exists(select 1 from shareholder_register_filing.filing_overrides where id=q.record_id)
  then raise exception 'rf1086_rollback_conflicting_projection'; end if;
  select to_jsonb(p) into existing_row from public.filing_overrides p where id=q.record_id;
  if existing_row is not null and existing_row is distinct from q.original_row
  then raise exception 'rf1086_rollback_conflicting_projection'; end if;
  if existing_row is null then insert into public.filing_overrides select * from jsonb_populate_record(null::public.filing_overrides,q.original_row); end if;
 end loop;
end; $restore_generic_quarantine$;

do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.filing_review_comments r join public.filing_review_comments p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('filing_review_comments',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.filing_review_comments(id,preview_id,company_id,target,severity,body,created_by,acknowledged_by,acknowledged_at,created_at) select r.id,r.preview_id,r.company_id,r.target,r.severity,r.body,r.created_by,r.acknowledged_by,r.acknowledged_at,r.created_at from shareholder_register_filing.filing_review_comments r on conflict(id) do update set id=excluded.id,preview_id=excluded.preview_id,company_id=excluded.company_id,target=excluded.target,severity=excluded.severity,body=excluded.body,created_by=excluded.created_by,acknowledged_by=excluded.acknowledged_by,acknowledged_at=excluded.acknowledged_at,created_at=excluded.created_at;
do $restore_generic_quarantine$
declare q record; existing_row jsonb; expected_keys text[]; actual_keys text[];
begin
 select array_agg(a.attname::text order by a.attname::text) into expected_keys from pg_catalog.pg_attribute a
 where a.attrelid='public.filing_review_comments'::regclass and a.attnum>0 and not a.attisdropped;
 for q in select * from shareholder_register_filing.migration_quarantine where family='filing_review_comments' order by record_id loop
  select array_agg(key order by key) into actual_keys from jsonb_object_keys(q.original_row) key;
  if actual_keys is distinct from expected_keys or (q.original_row->>'id')::uuid is distinct from q.record_id
  then raise exception 'rf1086_quarantined_generic_record_invalid'; end if;
  if exists(select 1 from shareholder_register_filing.filing_review_comments where id=q.record_id)
  then raise exception 'rf1086_rollback_conflicting_projection'; end if;
  select to_jsonb(p) into existing_row from public.filing_review_comments p where id=q.record_id;
  if existing_row is not null and existing_row is distinct from q.original_row
  then raise exception 'rf1086_rollback_conflicting_projection'; end if;
  if existing_row is null then insert into public.filing_review_comments select * from jsonb_populate_record(null::public.filing_review_comments,q.original_row); end if;
 end loop;
end; $restore_generic_quarantine$;

do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) - 'bank_balance' order by id) into a from public.opening_balance_setups t
 where shareholder_register_filing.classify_legacy_row_v1('opening_balance_setups',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.opening_balance_setups t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.opening_shareholders t
 where shareholder_register_filing.classify_legacy_row_v1('opening_shareholders',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.opening_shareholders t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.filing_previews t
 where shareholder_register_filing.classify_legacy_row_v1('filing_previews',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.filing_previews t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.filing_submissions t
 where shareholder_register_filing.classify_legacy_row_v1('filing_submissions',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.filing_submissions t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.filing_overrides t
 where shareholder_register_filing.classify_legacy_row_v1('filing_overrides',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.filing_overrides t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.filing_review_comments t
 where shareholder_register_filing.classify_legacy_row_v1('filing_review_comments',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.filing_review_comments t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.authority_permissions t
 where shareholder_register_filing.classify_legacy_row_v1('authority_permissions',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.authority_permissions t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.authority_test_runs t
 where shareholder_register_filing.classify_legacy_row_v1('authority_test_runs',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.authority_test_runs t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $restore_projection_triggers$ declare t record; begin
 for t in select * from rf151_reverse_triggers loop
  execute pg_catalog.format('alter table %s %s trigger %I',t.relation,
   case t.enabled when 'D' then 'disable' when 'A' then 'enable always' when 'R' then 'enable replica' else 'enable' end,t.name);
 end loop;
end; $restore_projection_triggers$;
create view public.filing_approval_snapshots with (security_invoker=true) as select * from shareholder_register_filing.filing_approval_snapshots;
grant select on public.filing_approval_snapshots to authenticated,service_role,legacy_rf1086_executor;
grant usage on schema shareholder_register_filing to authenticated,service_role,legacy_rf1086_executor;
create view public.production_filing_submissions with (security_invoker=true) as select * from shareholder_register_filing.production_filing_submissions;
grant select on public.production_filing_submissions to authenticated,service_role,legacy_rf1086_executor;
grant usage on schema shareholder_register_filing to authenticated,service_role,legacy_rf1086_executor;
create view public.production_filing_events with (security_invoker=true) as select * from shareholder_register_filing.production_filing_events;
grant select on public.production_filing_events to authenticated,service_role,legacy_rf1086_executor;
grant usage on schema shareholder_register_filing to authenticated,service_role,legacy_rf1086_executor;
create view public.production_feedback_artifacts with (security_invoker=true) as select * from shareholder_register_filing.production_feedback_artifacts;
grant select on public.production_feedback_artifacts to authenticated,service_role,legacy_rf1086_executor;
grant usage on schema shareholder_register_filing to authenticated,service_role,legacy_rf1086_executor;
-- Restore only the fourteen objects removed by the final contract. Receiver
-- implementations (Billing, Company Access, Documents and new-year) stay canonical.
do $restore_functions$ declare item record; statement text; n text; count_restored integer:=0; begin
 for item in select * from pg_catalog.jsonb_each((select original_objects from rf151_saved_objects))
 where pg_catalog.split_part(key,'(',1)=any(array['public.release_production_feedback_reconciliation','public.approve_production_filing','public.append_production_filing_event','public.begin_production_filing','public.claim_production_feedback_reconciliation','public.record_production_feedback_artifact','legacy_rf1086.assert_fresh_owner_v1','legacy_rf1086.actor_v1','legacy_rf1086.can_read_company_v1','legacy_rf1086.can_read_submission_v1','legacy_rf1086.assert_submission_v1','legacy_rf1086.prepare_operation_v1','public.append_production_feedback_reconciliation','public.rf1086_confirmation_forsendelse_id','backend_system.record_opening_snapshot_legacy_v1','backend_system.list_opening_snapshots_legacy_v1']) order by key loop
  if not(item.value ? 'acl') or item.value->>'definition' is null or item.value->>'owner' is null
  then raise exception 'rf1086_original_function_metadata_incomplete'; end if;
  statement:=item.value->>'definition';
  -- SET SCHEMA kept the physical row-type OIDs at expand. Restore that same
  -- result type as well as the exact physical SQL references; public views
  -- provide old read names, never a second INSERT ... ON CONFLICT target.
  foreach n in array array['filing_approval_snapshots','production_filing_submissions','production_filing_events','production_feedback_artifacts'] loop
   statement:=pg_catalog.replace(statement,'public.'||n,'shareholder_register_filing.'||n);
  end loop;
  execute statement;
  execute pg_catalog.format('alter function %s owner to %I',item.key,item.value->>'owner');
  count_restored:=count_restored+1;
 end loop;
 if count_restored<>16 then raise exception 'rf1086_original_function_inventory_incomplete'; end if;
end; $restore_functions$;
-- Clear default/new-object grants before replaying the recorded ACL (including
-- acldefault only when the saved ACL was SQL NULL, never an assumed public grant).
do $function_acl$ declare item record; a record; grantee text; saved_acl aclitem[]; signature text; begin
 for item in select * from pg_catalog.jsonb_each((select original_objects from rf151_saved_objects))
 where pg_catalog.split_part(key,'(',1)=any(array['public.release_production_feedback_reconciliation','public.approve_production_filing','public.append_production_filing_event','public.begin_production_filing','public.claim_production_feedback_reconciliation','public.record_production_feedback_artifact','legacy_rf1086.assert_fresh_owner_v1','legacy_rf1086.actor_v1','legacy_rf1086.can_read_company_v1','legacy_rf1086.can_read_submission_v1','legacy_rf1086.assert_submission_v1','legacy_rf1086.prepare_operation_v1','public.append_production_feedback_reconciliation','public.rf1086_confirmation_forsendelse_id','backend_system.record_opening_snapshot_legacy_v1','backend_system.list_opening_snapshots_legacy_v1']) loop
  signature:=item.key;
  for a in select distinct x.grantee from pg_catalog.pg_proc p cross join lateral pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) x where p.oid=pg_catalog.to_regprocedure(signature) loop
   grantee:=case when a.grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(a.grantee)) end;
   execute 'revoke all on function '||signature||' from '||grantee;
  end loop;
  if item.value->'acl'='null'::jsonb then
   saved_acl:=pg_catalog.acldefault('f',(select oid from pg_catalog.pg_roles where rolname=item.value->>'owner'));
  else saved_acl:=array(select value::aclitem from pg_catalog.jsonb_array_elements_text(item.value->'acl')); end if;
  for a in select * from pg_catalog.aclexplode(saved_acl) loop
   grantee:=case when a.grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(a.grantee)) end;
   execute 'grant '||a.privilege_type||' on function '||signature||' to '||grantee||case when a.is_grantable then ' with grant option' else '' end;
  end loop;
 end loop;
end; $function_acl$;
-- Existing physical-table policies survive SET SCHEMA; only the five exact
-- legacy helper policies removed by contract are recreated from saved metadata.
do $legacy_policies$ declare item record; policy jsonb; target text; roles_sql text; restored integer:=0; begin
 for item in select * from pg_catalog.jsonb_each((select original_relations from rf151_saved_objects)) loop
  if not(item.value ? 'policies') then raise exception 'rf1086_original_policy_metadata_incomplete'; end if;
  target:=case when item.key=any(array['filing_approval_snapshots','production_filing_submissions','production_filing_events','production_feedback_artifacts']) then 'shareholder_register_filing.' else 'public.' end||pg_catalog.quote_ident(item.key);
  for policy in select value from pg_catalog.jsonb_array_elements(item.value->'policies') where value->>'name'=any(array['legacy_rf1086_preview_read','legacy_rf1086_approval_read','legacy_rf1086_submission_read','legacy_rf1086_event_read','legacy_rf1086_artifact_read']) loop
   select pg_catalog.string_agg(case when value='public' then 'public' else pg_catalog.quote_ident(value) end,',') into roles_sql from pg_catalog.jsonb_array_elements_text(policy->'roles');
   execute pg_catalog.format('create policy %I on %s as %s for %s to %s%s%s',policy->>'name',target,
    case when (policy->>'permissive')::boolean then 'permissive' else 'restrictive' end,policy->>'command',roles_sql,
    case when policy->>'qual' is null then '' else ' using ('||(policy->>'qual')||')' end,
    case when policy->>'with_check' is null then '' else ' with check ('||(policy->>'with_check')||')' end);
   restored:=restored+1;
  end loop;
 end loop;
 if restored<>5 then raise exception 'rf1086_original_policy_inventory_incomplete'; end if;
end; $legacy_policies$;
-- SECTION C: replay captured original table owner, RLS, policies and effective ACL.
-- Execute before adding phase-specific overlap policies/grants and before original policies' helper retirement.
do $restore_opening_security$
declare table_name text; shape jsonb; relation jsonb; policy jsonb; role_names text; a record; grantee text; saved_acl aclitem[];
  original_path text:=pg_catalog.current_setting('search_path');
begin
  -- Original policy deparse was captured with public visible; schema metadata itself is qualified.
  perform pg_catalog.set_config('search_path','public,pg_catalog',true);
  for table_name in select name from rf151_reconstructed_openings order by name loop
    select s.original_opening_schema->table_name,s.original_relations->table_name into shape,relation
      from shareholder_register_filing.migration_state s where singleton;
    execute pg_catalog.format('alter table public.%I owner to %I',table_name,relation->>'owner');
    for policy in select value from pg_catalog.jsonb_array_elements(relation->'policies') loop
      select pg_catalog.string_agg(case when value='public' then 'public' else pg_catalog.quote_ident(value) end,',') into role_names
        from pg_catalog.jsonb_array_elements_text(policy->'roles');
      execute pg_catalog.format('create policy %I on public.%I as %s for %s to %s%s%s',policy->>'name',table_name,
        case when (policy->>'permissive')::boolean then 'permissive' else 'restrictive' end,policy->>'command',role_names,
        case when policy->>'qual' is null then '' else ' using ('||(policy->>'qual')||')' end,
        case when policy->>'with_check' is null then '' else ' with check ('||(policy->>'with_check')||')' end);
    end loop;
    execute pg_catalog.format('alter table public.%I %s row level security',table_name,case when (shape->>'rls_enabled')::boolean then 'enable' else 'disable' end);
    execute pg_catalog.format('alter table public.%I %sforce row level security',table_name,case when (relation->>'force_rls')::boolean then '' else 'no ' end);
    for a in select distinct x.grantee from pg_catalog.pg_class c
      cross join lateral pg_catalog.aclexplode(coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) x
      where c.oid=pg_catalog.to_regclass('public.'||table_name) loop
      grantee:=case when a.grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(a.grantee)) end;
      execute pg_catalog.format('revoke all on table public.%I from %s',table_name,grantee);
    end loop;
    if relation->'acl'='null'::jsonb then saved_acl:=pg_catalog.acldefault('r',(select oid from pg_catalog.pg_roles where rolname=relation->>'owner'));
    else saved_acl:=array(select value::aclitem from pg_catalog.jsonb_array_elements_text(relation->'acl')); end if;
    for a in select * from pg_catalog.aclexplode(saved_acl) loop
      grantee:=case when a.grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(a.grantee)) end;
      execute pg_catalog.format('grant %s on table public.%I to %s%s',a.privilege_type,table_name,grantee,case when a.is_grantable then ' with grant option' else '' end);
    end loop;
  end loop;
  perform pg_catalog.set_config('search_path',original_path,true);
end; $restore_opening_security$;


-- Restore only revoked pre-existing non-owner table grants; the original owner
-- was transferred at expand, so do not recreate its former implicit ALL rights.
do $legacy_table_acl$ declare n text; item jsonb; a record; grantee text; saved_acl aclitem[]; begin
 foreach n in array array['filing_approval_snapshots','production_filing_submissions','production_filing_events','production_feedback_artifacts'] loop
  select original_relations->n into item from rf151_saved_objects;
  if item->'acl'='null'::jsonb then saved_acl:=pg_catalog.acldefault('r',(select oid from pg_catalog.pg_roles where rolname=item->>'owner'));
  else saved_acl:=array(select value::aclitem from pg_catalog.jsonb_array_elements_text(item->'acl')); end if;
  for a in select * from pg_catalog.aclexplode(saved_acl) loop
   grantee:=case when a.grantee=0 then 'public' else pg_catalog.pg_get_userbyid(a.grantee) end;
   if grantee=any(array['legacy_rf1086_executor','authenticated','service_role']) then
    execute pg_catalog.format('grant %s on shareholder_register_filing.%I to %I%s',a.privilege_type,n,grantee,case when a.is_grantable then ' with grant option' else '' end);
   end if;
  end loop;
  execute pg_catalog.format('grant select,insert,update,delete on shareholder_register_filing.%I to postgres',n);
  execute pg_catalog.format('create policy rf151_old_function_owner on shareholder_register_filing.%I for all to postgres using(shareholder_register_filing.phase_v1()<>''contracted'') with check(shareholder_register_filing.phase_v1()<>''contracted'')',n);
 end loop;
end; $legacy_table_acl$;

create or replace function backend_system.admit_rf_opening_scope_v1() returns trigger
language plpgsql security definer set search_path='' as $function$
declare facts jsonb; actor text; family record; begin
 if exists(select 1 from shareholder_register_filing.migration_inventory where company_id=new.company_id and income_year=new.income_year) then return null; end if;
 actor:=shareholder_register_filing.verified_actor_v1()::text;
 if actor is null and shareholder_register_filing.phase_v1()='legacy_overlap' then return null; end if;
 facts:=shareholder_register_filing.read_scope_inventory_v1(new.company_id,new.income_year,actor);
 if (select count(*) from pg_catalog.jsonb_object_keys(facts))<>12 or (facts->'opening_balance_setups'->>'count')::integer<1
 then raise exception 'rf1086_scope_inventory_incomplete'; end if;
 for family in select * from pg_catalog.jsonb_each(facts) loop
  insert into shareholder_register_filing.migration_inventory(company_id,income_year,family,row_count,row_digest,quarantined_count)
  values(new.company_id,new.income_year,family.key,(family.value->>'count')::bigint,family.value->>'digest',
   (select count(*) from shareholder_register_filing.migration_quarantine q where q.company_id=new.company_id and (q.income_year=new.income_year or q.income_year is null)))
  on conflict do nothing;
 end loop;
 return null;
end; $function$;

-- Restore exact overlap implementations before installing their triggers.
create or replace function shareholder_register_filing.classify_legacy_row_v1(family text,row_data jsonb) returns text
language plpgsql stable security definer set search_path='' as $function$
declare p jsonb; s jsonb; candidate boolean:=false;
begin
  if family in ('opening_balance_setups','opening_shareholders') then candidate:=true;
  elsif family in ('filing_previews','filing_submissions','filing_overrides') then
    candidate:=shareholder_register_filing.is_rf_label_v1(row_data->>'filing');
  elsif family in ('authority_permissions','authority_test_runs') then
    candidate:=row_data->>'obligation'='aksjonaerregisteroppgaven';
  elsif family='filing_review_comments' then candidate:=row_data->>'target'='rf1086_preview';
  else raise exception 'rf1086_unknown_migration_family'; end if;
  -- The shared predecessor UI used this target for every obligation. The
  -- referenced preview, with matching company, determines a comment's owner.
  if family='filing_review_comments' then
    select pg_catalog.to_jsonb(v) into p from public.filing_previews v where v.id=(row_data->>'preview_id')::uuid;
    if p is not null and not shareholder_register_filing.is_rf_label_v1(p->>'filing') then
      return case when p->>'company_id'=row_data->>'company_id' then 'sibling' else 'quarantine' end;
    end if;
  end if;
  -- Conflicting labels/field targets cannot attest complete RF readiness.
  if family='filing_overrides' and not candidate and row_data->>'field_target' like 'rf1086.%'
  then return 'quarantine'; end if;
  if family in ('filing_submissions','filing_overrides','filing_review_comments') and row_data->>'preview_id' is not null then
    select pg_catalog.to_jsonb(v) into p from public.filing_previews v where v.id=(row_data->>'preview_id')::uuid;
    if p is not null and shareholder_register_filing.is_rf_label_v1(p->>'filing') then
      if shareholder_register_filing.classify_legacy_row_v1('filing_previews',p)<>'rf' then return 'quarantine'; end if;
      if (not candidate) or p->>'company_id' is distinct from row_data->>'company_id'
        or (row_data ? 'income_year' and p->>'income_year' is distinct from row_data->>'income_year')
        or (row_data ? 'filing' and p->>'filing' is distinct from row_data->>'filing')
      then return 'quarantine'; end if;
      candidate:=true;
    elsif candidate then return 'quarantine'; end if;
  end if;
  if candidate and family in ('opening_shareholders','filing_previews','filing_submissions') and row_data->>'setup_id' is not null then
    if shareholder_register_filing.phase_v1()='contracted' then
      select pg_catalog.to_jsonb(v) into s from shareholder_register_filing.opening_balance_setups v where v.id=(row_data->>'setup_id')::uuid;
    else
      select pg_catalog.to_jsonb(v) into s from public.opening_balance_setups v where v.id=(row_data->>'setup_id')::uuid;
    end if;
    if s is null or s->>'company_id' is distinct from row_data->>'company_id'
      or (row_data ? 'income_year' and s->>'income_year' is distinct from row_data->>'income_year')
    then return 'quarantine'; end if;
  end if;
  if candidate and family='filing_submissions' and row_data->>'authority_test_run_id' is not null then
    select pg_catalog.to_jsonb(v) into p from public.authority_test_runs v where v.id=(row_data->>'authority_test_run_id')::uuid;
    if p is null or p->>'company_id' is distinct from row_data->>'company_id' or p->>'obligation'<>'aksjonaerregisteroppgaven'
    then return 'quarantine'; end if;
  end if;
  return case when candidate then 'rf' else 'sibling' end;
end; $function$;

create or replace function shareholder_register_filing.sync_legacy_projection_v1() returns trigger
language plpgsql security definer set search_path='' as $function$
declare item jsonb; old_item jsonb; category text; v_cols text; v_update text; v_phase text;
begin
  if tg_table_name not in ('opening_balance_setups','opening_shareholders','filing_previews','filing_submissions',
    'filing_overrides','filing_review_comments','authority_permissions','authority_test_runs')
  then raise exception 'rf1086_unknown_migration_family'; end if;
  v_phase:=shareholder_register_filing.phase_v1();
  item:=case when tg_op='DELETE' then pg_catalog.to_jsonb(old) else pg_catalog.to_jsonb(new) end;
  if tg_op='UPDATE' then old_item:=pg_catalog.to_jsonb(old); end if;
  category:=shareholder_register_filing.classify_legacy_row_v1(tg_table_name,item);
  if tg_when='BEFORE' then
    if v_phase<>'legacy_overlap' and (category<>'sibling' or
      (old_item is not null and shareholder_register_filing.classify_legacy_row_v1(tg_table_name,old_item)<>'sibling'))
      and not(pg_catalog.pg_trigger_depth()>1 and pg_catalog.current_setting('role',true) in
        ('shareholder_register_filing_executor','ledger_workflow_executor'))
    then raise exception 'rf1086_legacy_writer_retired'; end if;
    return case when tg_op='DELETE' then old else new end;
  end if;
  if v_phase<>'legacy_overlap' then return null; end if;
  if category='quarantine' then
    insert into shareholder_register_filing.migration_quarantine(family,record_id,company_id,income_year,reason,original_row)
    values(tg_table_name,(item->>'id')::uuid,(item->>'company_id')::uuid,(item->>'income_year')::integer,'conflicting_rf_provenance',item)
    on conflict(family,record_id) do update set original_row=excluded.original_row;
    return null;
  end if;
  if tg_op='DELETE' or category='sibling' then
    execute pg_catalog.format('delete from shareholder_register_filing.%I where id=$1',tg_table_name)
      using (item->>'id')::uuid;
    return null;
  end if;
  select pg_catalog.string_agg(pg_catalog.quote_ident(a.attname),',' order by a.attnum),
    pg_catalog.string_agg(pg_catalog.format('%I=excluded.%I',a.attname,a.attname),',' order by a.attnum)
  into v_cols,v_update from pg_catalog.pg_attribute a
  where a.attrelid=pg_catalog.to_regclass('shareholder_register_filing.'||tg_table_name)
    and a.attnum>0 and not a.attisdropped;
  execute pg_catalog.format('insert into shareholder_register_filing.%I(%s) select %s from jsonb_populate_record(null::shareholder_register_filing.%I,$1) on conflict(id) do update set %s',tg_table_name,v_cols,v_cols,tg_table_name,v_update)
    using item;
  return null;
end; $function$;

create or replace function shareholder_register_filing.insert_preparation_row_v1(p_family text,p_row jsonb) returns jsonb
language plpgsql security definer set search_path='' as $function$
declare v_schema text; v_columns text; result jsonb; begin
 if p_family not in ('filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs')
 then raise exception 'rf1086_invalid_input'; end if;
 v_schema:=case when shareholder_register_filing.phase_v1()='legacy_overlap' then 'public' else 'shareholder_register_filing' end;
 select pg_catalog.string_agg(pg_catalog.quote_ident(a.attname),',' order by a.attnum) into v_columns
 from pg_catalog.pg_attribute a where a.attrelid=pg_catalog.to_regclass(v_schema||'.'||p_family)
   and a.attnum>0 and not a.attisdropped and p_row ? a.attname;
 execute pg_catalog.format('insert into %I.%I(%s) select %s from pg_catalog.jsonb_populate_record(null::%I.%I,$1) returning pg_catalog.to_jsonb(%I.*)',
   v_schema,p_family,v_columns,v_columns,v_schema,p_family,p_family) into result using p_row;
 return result;
end; $function$;

create or replace function shareholder_register_filing.acknowledge_review_comment_v1(p_comment_id uuid)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid; c shareholder_register_filing.filing_review_comments%rowtype; result jsonb; begin
 select * into c from shareholder_register_filing.filing_review_comments where id=p_comment_id for update;
 if c.id is null then raise exception 'rf1086_not_found'; end if;
 a:=shareholder_register_filing.assert_preparation_access_v1(c.company_id);
 if c.severity='hard_block' then raise exception 'rf1086_forbidden'; end if;
 if shareholder_register_filing.phase_v1()='legacy_overlap' then
  update public.filing_review_comments set acknowledged_by=a,acknowledged_at=pg_catalog.now() where id=c.id returning pg_catalog.to_jsonb(filing_review_comments.*) into result;
 else
  update shareholder_register_filing.filing_review_comments set acknowledged_by=a,acknowledged_at=pg_catalog.now() where id=c.id returning pg_catalog.to_jsonb(filing_review_comments.*) into result;
 end if;
 return result;
end; $function$;

create or replace function shareholder_register_filing.confirm_filing_permission_v1(p_company_id uuid,p_enabled boolean)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid:=shareholder_register_filing.assert_preparation_access_v1(p_company_id); result jsonb; v_schema text; begin
 if not public.company_access_has_fresh_mfa_v1() then raise exception 'rf1086_company_year_not_admitted'; end if;
 if p_enabled is null then raise exception 'rf1086_invalid_input'; end if;
 v_schema:=case when shareholder_register_filing.phase_v1()='legacy_overlap' then 'public' else 'shareholder_register_filing' end;
 execute pg_catalog.format('insert into %I.authority_permissions(company_id,obligation,submitter_user_id,confirmed_by,confirmed_at,production_enabled) values($1,''aksjonaerregisteroppgaven'',$2,$2,pg_catalog.now(),$3) on conflict(company_id,obligation) do update set submitter_user_id=excluded.submitter_user_id,confirmed_by=excluded.confirmed_by,confirmed_at=excluded.confirmed_at,production_enabled=excluded.production_enabled,updated_at=pg_catalog.now() returning pg_catalog.to_jsonb(authority_permissions.*)',v_schema)
 into result using p_company_id,a,p_enabled;
 return result;
end; $function$;

create or replace function shareholder_register_filing.record_simulation_v1(p_preview_id uuid,p_data jsonb)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid; p shareholder_register_filing.filing_previews%rowtype; result jsonb; v_schema text; begin
 select * into p from shareholder_register_filing.filing_previews where id=p_preview_id for update;
 if p.id is null then raise exception 'rf1086_not_found'; end if;
 a:=shareholder_register_filing.assert_preparation_access_v1(p.company_id);
 if p.status<>'ready' or not backend_system.rf1086_annual_readiness_ready_v1(p.company_id,p.income_year,'aksjonaerregisteroppgaven')
   or exists(select 1 from shareholder_register_filing.filing_review_comments c where c.preview_id=p.id and c.severity='hard_block')
   or exists(select 1 from shareholder_register_filing.filing_overrides o where o.company_id=p.company_id and o.income_year=p.income_year and o.risk_level='block' and o.filing=p.filing)
 then raise exception 'rf1086_company_year_not_admitted'; end if;
 -- Exact original upsert key preserves repeat simulation semantics.
 v_schema:=case when shareholder_register_filing.phase_v1()='legacy_overlap' then 'public' else 'shareholder_register_filing' end;
 execute pg_catalog.format('insert into %I.filing_submissions(preview_id,setup_id,company_id,income_year,filing,mode,adapter_mode,payload_hash,idempotency_key,status,calls,receipt_id,feedback_document_ids,feedback_items,receipt_metadata,submitted_payload_ref,submitted_payload,failure_code,failure_message,authority_confirmed_by,authority_confirmed_at,preview_confirmed_by,preview_confirmed_at,created_by,submitted_by) values($1,$2,$3,$4,$5,''simulation'',''simulation'',$6->>''payload_hash'',$6->>''idempotency_key'',$6->>''status'',$6->''calls'',$6->>''receipt_id'',$6->''feedback_document_ids'',$6->''feedback_items'',$6->''receipt_metadata'',$6->''submitted_payload_ref'',$6->''submitted_payload'',$6->>''failure_code'',$6->>''failure_message'',$7,($6->>''authority_confirmed_at'')::timestamptz,$7,($6->>''preview_confirmed_at'')::timestamptz,$7,$7) on conflict(preview_id) do update set mode=excluded.mode,adapter_mode=excluded.adapter_mode,payload_hash=excluded.payload_hash,idempotency_key=excluded.idempotency_key,status=excluded.status,calls=excluded.calls,receipt_id=excluded.receipt_id,feedback_document_ids=excluded.feedback_document_ids,feedback_items=excluded.feedback_items,receipt_metadata=excluded.receipt_metadata,submitted_payload_ref=excluded.submitted_payload_ref,submitted_payload=excluded.submitted_payload,failure_code=excluded.failure_code,failure_message=excluded.failure_message,authority_confirmed_by=excluded.authority_confirmed_by,authority_confirmed_at=excluded.authority_confirmed_at,preview_confirmed_by=excluded.preview_confirmed_by,preview_confirmed_at=excluded.preview_confirmed_at,created_by=excluded.created_by,submitted_by=excluded.submitted_by,updated_at=pg_catalog.now() returning pg_catalog.to_jsonb(filing_submissions.*)',v_schema)
 into result using p.id,p.setup_id,p.company_id,p.income_year,p.filing,p_data,a;
 return result;
end; $function$;

do $overlap_preparation$ declare n text; review_access text; begin
 foreach n in array array['opening_balance_setups','opening_shareholders','filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs'] loop
  execute pg_catalog.format('create trigger rf151_legacy_projection after insert or update or delete on public.%I for each row execute function shareholder_register_filing.sync_legacy_projection_v1()',n);
  execute pg_catalog.format('grant select,insert,update,delete on shareholder_register_filing.%I to postgres',n);
  execute pg_catalog.format('create policy rf151_overlap_copy on shareholder_register_filing.%I for all to postgres using(shareholder_register_filing.phase_v1()=''legacy_overlap'') with check(shareholder_register_filing.phase_v1()=''legacy_overlap'')',n);
  execute pg_catalog.format('grant select,insert,update on public.%I to shareholder_register_filing_store_owner',n);
  review_access:=case when n='filing_review_comments' then 'public.company_access_can_review_filing_v1(company_id)' else 'public.company_access_is_accepted_owner_v1(company_id)' end;
  execute pg_catalog.format('create policy rf151_backend_overlap on public.%I for all to shareholder_register_filing_store_owner using(shareholder_register_filing.phase_v1()=''legacy_overlap'' and %s) with check(shareholder_register_filing.phase_v1()=''legacy_overlap'' and %s)',n,review_access,review_access);
 end loop;
end; $overlap_preparation$;


create temporary table rf151_archive_restore_grant on commit drop as select pg_catalog.has_function_privilege(current_user,'public.company_archive_track_source_write_v1()','EXECUTE') had_execute;
grant execute on function public.company_archive_track_source_write_v1() to postgres;
CREATE TRIGGER company_archive_track_opening_balance_setups BEFORE INSERT OR DELETE OR UPDATE ON public.opening_balance_setups FOR EACH ROW WHEN (pg_catalog.pg_trigger_depth()=0) EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');
CREATE TRIGGER company_archive_track_opening_shareholders BEFORE INSERT OR DELETE OR UPDATE ON public.opening_shareholders FOR EACH ROW WHEN (pg_catalog.pg_trigger_depth()=0) EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');
do $restore_archive_exec$ begin if not(select had_execute from rf151_archive_restore_grant) then revoke execute on function public.company_archive_track_source_write_v1() from postgres; end if; end; $restore_archive_exec$;
-- Exact six-family canonical-to-public projection from forward cutover.
create function backend_system.sync_rf_preparation_projection_v1() returns trigger
language plpgsql security definer set search_path='' as $function$
declare row_data jsonb; v_cols text; v_updates text;
begin
 if shareholder_register_filing.phase_v1()<>'canonical_overlap' or pg_catalog.pg_trigger_depth()>1 then return null; end if;
 if tg_table_name not in ('filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs') then raise exception 'rf1086_overlap_trigger_invalid'; end if;
 row_data:=pg_catalog.to_jsonb(new);
 select pg_catalog.string_agg(pg_catalog.quote_ident(a.attname),',' order by a.attnum),
  pg_catalog.string_agg(pg_catalog.format('%I=excluded.%I',a.attname,a.attname),',' order by a.attnum)
 into v_cols,v_updates from pg_catalog.pg_attribute a where a.attrelid=pg_catalog.to_regclass('public.'||tg_table_name) and a.attnum>0 and not a.attisdropped;
 execute pg_catalog.format('insert into public.%I(%s) select %s from pg_catalog.jsonb_populate_record(null::public.%I,$1) on conflict(id) do update set %s',tg_table_name,v_cols,v_cols,tg_table_name,v_updates) using row_data;
 return null;
end; $function$;
revoke all on function backend_system.sync_rf_preparation_projection_v1() from public,anon,authenticated,service_role;

create trigger rf151_preparation_projection after insert or update on shareholder_register_filing.filing_previews for each row execute function backend_system.sync_rf_preparation_projection_v1();

create trigger rf151_preparation_projection after insert or update on shareholder_register_filing.filing_submissions for each row execute function backend_system.sync_rf_preparation_projection_v1();

create trigger rf151_preparation_projection after insert or update on shareholder_register_filing.filing_overrides for each row execute function backend_system.sync_rf_preparation_projection_v1();

create trigger rf151_preparation_projection after insert or update on shareholder_register_filing.filing_review_comments for each row execute function backend_system.sync_rf_preparation_projection_v1();

create trigger rf151_preparation_projection after insert or update on shareholder_register_filing.authority_permissions for each row execute function backend_system.sync_rf_preparation_projection_v1();

create trigger rf151_preparation_projection after insert or update on shareholder_register_filing.authority_test_runs for each row execute function backend_system.sync_rf_preparation_projection_v1();


-- Exact opening/bank coordinator from forward expand.
-- Temporary backend-system coordination; removed by the final RF contract.
-- The canonical Ledger function receives exact old input, never a posting-derived balance.
set local role ledger_store_owner;
create policy rf151_legacy_bank_capture on ledger.opening_bank_inputs for insert to ledger_store_owner
with check(pg_catalog.pg_trigger_depth()>0);
create policy rf151_legacy_bank_capture_read on ledger.opening_bank_inputs for select to ledger_store_owner
using(pg_catalog.pg_trigger_depth()>0);
create function ledger.capture_legacy_opening_bank_input_v1(p_snapshot_id uuid,p_company_id uuid,p_income_year integer,p_bank numeric,p_recorded_by uuid,p_recorded_at timestamptz)
returns void language plpgsql security definer set search_path='' as $function$
declare r ledger.opening_bank_inputs%rowtype; begin
 if pg_catalog.pg_trigger_depth()=0 then raise exception 'ledger_forbidden'; end if;
 insert into ledger.opening_bank_inputs values(p_snapshot_id,p_company_id,p_income_year,p_bank,p_recorded_by,p_recorded_at) on conflict do nothing;
 select * into r from ledger.opening_bank_inputs where snapshot_id=p_snapshot_id;
 if r.snapshot_id is null or (r.company_id,r.income_year,r.bank_balance_nok,r.recorded_by,r.recorded_at)
    is distinct from (p_company_id,p_income_year,p_bank,p_recorded_by,p_recorded_at)
 then raise exception 'rf1086_legacy_bank_projection_conflict'; end if;
end; $function$;
revoke all on function ledger.capture_legacy_opening_bank_input_v1(uuid,uuid,integer,numeric,uuid,timestamptz) from public,anon,authenticated,service_role;
grant execute on function ledger.capture_legacy_opening_bank_input_v1(uuid,uuid,integer,numeric,uuid,timestamptz),ledger.read_opening_bank_inputs_v1(uuid,integer,text) to postgres;
reset role;
create function backend_system.capture_legacy_rf_opening_bank_v1() returns trigger
language plpgsql security definer set search_path='' as $function$
begin
 if shareholder_register_filing.phase_v1()='legacy_overlap' then
  perform ledger.capture_legacy_opening_bank_input_v1(new.id,new.company_id,new.income_year,new.bank_balance,new.created_by,new.created_at);
 end if;
 return null;
end; $function$;
create trigger rf151_capture_legacy_bank after insert on public.opening_balance_setups
for each row execute function backend_system.capture_legacy_rf_opening_bank_v1();

create function backend_system.sync_rf_opening_projection_v1() returns trigger
language plpgsql security definer set search_path='' as $function$
declare company uuid; setup uuid; o record; bank record; h record; current_row jsonb; expected_row jsonb; actor text;
begin
 if shareholder_register_filing.phase_v1()='contracted' then return null; end if;
 if tg_table_name='opening_balance_setups' then company:=new.company_id; setup:=new.id;
 elsif tg_table_name='opening_shareholders' then company:=new.company_id; setup:=new.setup_id;
 else raise exception 'rf1086_overlap_trigger_invalid'; end if;
 -- Old-row copying already retains its own authoritative projection and original bank input.
 if shareholder_register_filing.phase_v1()='legacy_overlap' and exists(select 1 from public.opening_balance_setups p where p.id=setup)
 then return null; end if;
 actor:=shareholder_register_filing.verified_actor_v1()::text;
 select * into o from shareholder_register_filing.read_opening_snapshots_v1(company,null,actor) x where x.id=setup;
 if o.id is null then raise exception 'rf1086_opening_projection_missing'; end if;
 select * into bank from ledger.read_opening_bank_inputs_v1(company,o.income_year,actor) b where b.snapshot_id=setup;
 if bank.snapshot_id is null or bank.recorded_by<>o.created_by or bank.recorded_at<>o.created_at
 then raise exception 'rf1086_opening_bank_projection_missing'; end if;
 expected_row:=pg_catalog.to_jsonb(o)||pg_catalog.jsonb_build_object('bank_balance',bank.bank_balance_nok);
 select pg_catalog.to_jsonb(p) into current_row from public.opening_balance_setups p where p.id=setup;
 if current_row is not null and current_row is distinct from expected_row then raise exception 'rf1086_opening_projection_conflict'; end if;
 if current_row is null then
  insert into public.opening_balance_setups select * from pg_catalog.jsonb_populate_record(null::public.opening_balance_setups,expected_row);
 end if;
 for h in select * from shareholder_register_filing.read_opening_shareholders_v1(company,o.income_year,actor) x where x.setup_id=setup loop
  select pg_catalog.to_jsonb(p) into current_row from public.opening_shareholders p where p.id=h.id;
  if current_row is not null and current_row is distinct from pg_catalog.to_jsonb(h) then raise exception 'rf1086_opening_projection_conflict'; end if;
  if current_row is null then insert into public.opening_shareholders select * from pg_catalog.jsonb_populate_record(null::public.opening_shareholders,pg_catalog.to_jsonb(h)); end if;
 end loop;
 return null;
end; $function$;
revoke all on function backend_system.sync_rf_opening_projection_v1(),backend_system.capture_legacy_rf_opening_bank_v1() from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.read_opening_snapshots_v1(uuid,integer,text),shareholder_register_filing.read_opening_shareholders_v1(uuid,integer,text) to postgres;
create constraint trigger rf151_opening_projection after insert or update on shareholder_register_filing.opening_balance_setups
 deferrable initially deferred for each row execute function backend_system.sync_rf_opening_projection_v1();
create constraint trigger rf151_shareholder_projection after insert or update on shareholder_register_filing.opening_shareholders
 deferrable initially deferred for each row execute function backend_system.sync_rf_opening_projection_v1();


update shareholder_register_filing.migration_state set phase='canonical_overlap' where singleton;
-- Refuse any accidental canonical mutation, including timestamps/leases and
-- retained migration evidence. Only migration_state.phase may change.
do $unchanged_canonical$ declare r record; digest text; migration_role name:=current_user; begin
 for r in select a.*,h.digest expected from rf151_reverse_read_access a join rf151_reverse_hashes h using(relation) loop
  execute pg_catalog.format('select pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E''\n'' order by pg_catalog.to_jsonb(t)::text),pg_catalog.left(''x'',0)),''sha256''),''hex'') from %s t',r.relation) into digest;
  if digest is distinct from r.expected then raise exception 'rf1086_reverse_changed_canonical_evidence'; end if;
  execute pg_catalog.format('set local role %I',r.owner);
  execute pg_catalog.format('drop policy rf151_reverse_read_snapshot on %s',r.relation);
  if not r.had_select and r.owner<>migration_role then execute pg_catalog.format('revoke select on %s from %I',r.relation,migration_role); end if;
  execute 'reset role';
 end loop;
end; $unchanged_canonical$;

grant select,insert,update,delete on shareholder_register_filing.opening_balance_setups,shareholder_register_filing.opening_shareholders,shareholder_register_filing.filing_previews,shareholder_register_filing.filing_submissions,shareholder_register_filing.filing_overrides,shareholder_register_filing.filing_review_comments,shareholder_register_filing.authority_permissions,shareholder_register_filing.authority_test_runs,shareholder_register_filing.filing_approval_snapshots,shareholder_register_filing.production_filing_submissions,shareholder_register_filing.production_filing_events,shareholder_register_filing.production_feedback_artifacts to postgres;
do $restore_roles$ declare r record; begin
 if (select workflow_create from rf151_schema_grants) then revoke create on schema backend_system from ledger_workflow_store_owner; end if;
 if (select backend_create from rf151_schema_grants) then execute pg_catalog.format('revoke create on schema backend_system from %I',current_user); end if;
 if (select company_access_create from rf151_schema_grants) then revoke create on schema public from company_access_executor; end if;
 if (select ledger_create from rf151_schema_grants) then revoke create on schema ledger from ledger_store_owner; end if;
 for r in select * from rf151_borrowed_roles loop
  if r.prior is null then execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  else execute pg_catalog.format('grant %I to %I with admin %s, inherit %s, set %s granted by %I',r.role_name,current_user,
    r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore_roles$;

commit;
