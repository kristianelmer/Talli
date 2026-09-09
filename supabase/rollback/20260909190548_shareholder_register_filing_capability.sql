-- Full RF rollback follows receiver/backend rollback. Preserve every current RF row and bank input.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:rf1086:capability:v1',0));

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

create temporary table rf151_schema_grants on commit drop as select false as ledger_create,false as company_access_create,false as workflow_create,false as backend_create;

create temporary table rf151_saved_objects on commit drop as select original_objects,original_relations,original_foreign_policies,original_opening_schema from shareholder_register_filing.migration_state where singleton;

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

lock table public.opening_balance_setups,public.opening_shareholders,public.filing_previews,public.filing_submissions,public.filing_overrides,public.filing_review_comments,public.authority_permissions,public.authority_test_runs,shareholder_register_filing.opening_balance_setups,shareholder_register_filing.opening_shareholders,shareholder_register_filing.filing_previews,shareholder_register_filing.filing_submissions,shareholder_register_filing.filing_overrides,shareholder_register_filing.filing_review_comments,shareholder_register_filing.authority_permissions,shareholder_register_filing.authority_test_runs,shareholder_register_filing.filing_approval_snapshots,shareholder_register_filing.production_filing_submissions,shareholder_register_filing.production_filing_events,shareholder_register_filing.production_feedback_artifacts in access exclusive mode;

drop trigger if exists rf151_legacy_write_barrier on public.opening_balance_setups;

drop trigger if exists rf151_legacy_projection on public.opening_balance_setups;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.opening_balance_setups;

drop trigger if exists rf151_legacy_write_barrier on public.opening_shareholders;

drop trigger if exists rf151_legacy_projection on public.opening_shareholders;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.opening_shareholders;

drop trigger if exists rf151_legacy_write_barrier on public.filing_previews;

drop trigger if exists rf151_legacy_projection on public.filing_previews;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.filing_previews;

drop trigger if exists rf151_legacy_write_barrier on public.filing_submissions;

drop trigger if exists rf151_legacy_projection on public.filing_submissions;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.filing_submissions;

drop trigger if exists rf151_legacy_write_barrier on public.filing_overrides;

drop trigger if exists rf151_legacy_projection on public.filing_overrides;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.filing_overrides;

drop trigger if exists rf151_legacy_write_barrier on public.filing_review_comments;

drop trigger if exists rf151_legacy_projection on public.filing_review_comments;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.filing_review_comments;

drop trigger if exists rf151_legacy_write_barrier on public.authority_permissions;

drop trigger if exists rf151_legacy_projection on public.authority_permissions;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.authority_permissions;

drop trigger if exists rf151_legacy_write_barrier on public.authority_test_runs;

drop trigger if exists rf151_legacy_projection on public.authority_test_runs;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.authority_test_runs;

drop trigger if exists rf151_opening_projection on shareholder_register_filing.opening_balance_setups;

drop trigger if exists rf151_shareholder_projection on shareholder_register_filing.opening_shareholders;

drop trigger if exists rf151_scope_admission on shareholder_register_filing.opening_balance_setups;

drop trigger if exists rf151_capture_legacy_bank on public.opening_balance_setups;

alter table shareholder_register_filing.opening_balance_setups no force row level security;

grant select,insert,update,delete on shareholder_register_filing.opening_balance_setups to postgres;

alter table shareholder_register_filing.opening_shareholders no force row level security;

grant select,insert,update,delete on shareholder_register_filing.opening_shareholders to postgres;

alter table shareholder_register_filing.filing_previews no force row level security;

grant select,insert,update,delete on shareholder_register_filing.filing_previews to postgres;

alter table shareholder_register_filing.filing_submissions no force row level security;

grant select,insert,update,delete on shareholder_register_filing.filing_submissions to postgres;

alter table shareholder_register_filing.filing_overrides no force row level security;

grant select,insert,update,delete on shareholder_register_filing.filing_overrides to postgres;

alter table shareholder_register_filing.filing_review_comments no force row level security;

grant select,insert,update,delete on shareholder_register_filing.filing_review_comments to postgres;

alter table shareholder_register_filing.authority_permissions no force row level security;

grant select,insert,update,delete on shareholder_register_filing.authority_permissions to postgres;

alter table shareholder_register_filing.authority_test_runs no force row level security;

grant select,insert,update,delete on shareholder_register_filing.authority_test_runs to postgres;

alter table shareholder_register_filing.filing_approval_snapshots no force row level security;

grant select,insert,update,delete on shareholder_register_filing.filing_approval_snapshots to postgres;

alter table shareholder_register_filing.production_filing_submissions no force row level security;

grant select,insert,update,delete on shareholder_register_filing.production_filing_submissions to postgres;

alter table shareholder_register_filing.production_filing_events no force row level security;

grant select,insert,update,delete on shareholder_register_filing.production_filing_events to postgres;

alter table shareholder_register_filing.production_feedback_artifacts no force row level security;

grant select,insert,update,delete on shareholder_register_filing.production_feedback_artifacts to postgres;

alter table ledger.opening_bank_inputs no force row level security; grant select on ledger.opening_bank_inputs to postgres;

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

update shareholder_register_filing.migration_state set phase='legacy_overlap' where singleton;

do $bank$ begin if exists(select 1 from shareholder_register_filing.opening_balance_setups r left join ledger.opening_bank_inputs b on b.snapshot_id=r.id and b.company_id=r.company_id and b.income_year=r.income_year where b.snapshot_id is null or b.recorded_by<>r.created_by or b.recorded_at<>r.created_at) then raise exception 'rf1086_rollback_bank_input_missing'; end if; end; $bank$;

insert into public.opening_balance_setups(id,company_id,income_year,bank_balance,share_capital,share_count,nominal_value,locked_at,created_by,created_at) select r.id,r.company_id,r.income_year,b.bank_balance_nok,r.share_capital,r.share_count,r.nominal_value,r.locked_at,r.created_by,r.created_at from shareholder_register_filing.opening_balance_setups r join ledger.opening_bank_inputs b on b.snapshot_id=r.id and b.company_id=r.company_id and b.income_year=r.income_year on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,income_year=excluded.income_year,bank_balance=excluded.bank_balance,share_capital=excluded.share_capital,share_count=excluded.share_count,nominal_value=excluded.nominal_value,locked_at=excluded.locked_at,created_by=excluded.created_by,created_at=excluded.created_at;

insert into public.opening_shareholders(id,setup_id,company_id,name,shareholder_kind,national_id,org_number,share_count,created_by,created_at) select r.id,r.setup_id,r.company_id,r.name,r.shareholder_kind,r.national_id,r.org_number,r.share_count,r.created_by,r.created_at from shareholder_register_filing.opening_shareholders r on conflict(id) do update set id=excluded.id,setup_id=excluded.setup_id,company_id=excluded.company_id,name=excluded.name,shareholder_kind=excluded.shareholder_kind,national_id=excluded.national_id,org_number=excluded.org_number,share_count=excluded.share_count,created_by=excluded.created_by,created_at=excluded.created_at;

insert into public.filing_previews(id,company_id,setup_id,income_year,filing,status,issues,preview,hovedskjema_xml,underskjema_xml,source,created_by,created_at) select r.id,r.company_id,r.setup_id,r.income_year,r.filing,r.status,r.issues,r.preview,r.hovedskjema_xml,r.underskjema_xml,r.source,r.created_by,r.created_at from shareholder_register_filing.filing_previews r on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,setup_id=excluded.setup_id,income_year=excluded.income_year,filing=excluded.filing,status=excluded.status,issues=excluded.issues,preview=excluded.preview,hovedskjema_xml=excluded.hovedskjema_xml,underskjema_xml=excluded.underskjema_xml,source=excluded.source,created_by=excluded.created_by,created_at=excluded.created_at;

insert into public.filing_submissions(id,preview_id,company_id,setup_id,income_year,filing,mode,adapter_mode,payload_hash,idempotency_key,status,authority_confirmed_by,authority_confirmed_at,preview_confirmed_by,preview_confirmed_at,calls,receipt_id,feedback_document_ids,feedback_items,receipt_metadata,submitted_payload_ref,submitted_payload,failure_code,failure_message,created_by,submitted_by,created_at,updated_at,authority_test_run_id) select r.id,r.preview_id,r.company_id,r.setup_id,r.income_year,r.filing,r.mode,r.adapter_mode,r.payload_hash,r.idempotency_key,r.status,r.authority_confirmed_by,r.authority_confirmed_at,r.preview_confirmed_by,r.preview_confirmed_at,r.calls,r.receipt_id,r.feedback_document_ids,r.feedback_items,r.receipt_metadata,r.submitted_payload_ref,r.submitted_payload,r.failure_code,r.failure_message,r.created_by,r.submitted_by,r.created_at,r.updated_at,r.authority_test_run_id from shareholder_register_filing.filing_submissions r on conflict(id) do update set id=excluded.id,preview_id=excluded.preview_id,company_id=excluded.company_id,setup_id=excluded.setup_id,income_year=excluded.income_year,filing=excluded.filing,mode=excluded.mode,adapter_mode=excluded.adapter_mode,payload_hash=excluded.payload_hash,idempotency_key=excluded.idempotency_key,status=excluded.status,authority_confirmed_by=excluded.authority_confirmed_by,authority_confirmed_at=excluded.authority_confirmed_at,preview_confirmed_by=excluded.preview_confirmed_by,preview_confirmed_at=excluded.preview_confirmed_at,calls=excluded.calls,receipt_id=excluded.receipt_id,feedback_document_ids=excluded.feedback_document_ids,feedback_items=excluded.feedback_items,receipt_metadata=excluded.receipt_metadata,submitted_payload_ref=excluded.submitted_payload_ref,submitted_payload=excluded.submitted_payload,failure_code=excluded.failure_code,failure_message=excluded.failure_message,created_by=excluded.created_by,submitted_by=excluded.submitted_by,created_at=excluded.created_at,updated_at=excluded.updated_at,authority_test_run_id=excluded.authority_test_run_id;

insert into public.filing_overrides(id,preview_id,company_id,income_year,filing,field_target,old_value,new_value,reason,risk_level,owner_confirmed_by,owner_confirmed_at,created_by,created_at) select r.id,r.preview_id,r.company_id,r.income_year,r.filing,r.field_target,r.old_value,r.new_value,r.reason,r.risk_level,r.owner_confirmed_by,r.owner_confirmed_at,r.created_by,r.created_at from shareholder_register_filing.filing_overrides r on conflict(id) do update set id=excluded.id,preview_id=excluded.preview_id,company_id=excluded.company_id,income_year=excluded.income_year,filing=excluded.filing,field_target=excluded.field_target,old_value=excluded.old_value,new_value=excluded.new_value,reason=excluded.reason,risk_level=excluded.risk_level,owner_confirmed_by=excluded.owner_confirmed_by,owner_confirmed_at=excluded.owner_confirmed_at,created_by=excluded.created_by,created_at=excluded.created_at;

insert into public.filing_review_comments(id,preview_id,company_id,target,severity,body,created_by,acknowledged_by,acknowledged_at,created_at) select r.id,r.preview_id,r.company_id,r.target,r.severity,r.body,r.created_by,r.acknowledged_by,r.acknowledged_at,r.created_at from shareholder_register_filing.filing_review_comments r on conflict(id) do update set id=excluded.id,preview_id=excluded.preview_id,company_id=excluded.company_id,target=excluded.target,severity=excluded.severity,body=excluded.body,created_by=excluded.created_by,acknowledged_by=excluded.acknowledged_by,acknowledged_at=excluded.acknowledged_at,created_at=excluded.created_at;

insert into public.authority_permissions(id,company_id,obligation,submitter_user_id,confirmed_by,confirmed_at,production_enabled,updated_at) select r.id,r.company_id,r.obligation,r.submitter_user_id,r.confirmed_by,r.confirmed_at,r.production_enabled,r.updated_at from shareholder_register_filing.authority_permissions r on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,obligation=excluded.obligation,submitter_user_id=excluded.submitter_user_id,confirmed_by=excluded.confirmed_by,confirmed_at=excluded.confirmed_at,production_enabled=excluded.production_enabled,updated_at=excluded.updated_at;

insert into public.authority_test_runs(id,company_id,obligation,environment,status,test_reference,feedback_summary,receipt_reference,archive_reference,evidence_url,payload_hash,recorded_by,recorded_at) select r.id,r.company_id,r.obligation,r.environment,r.status,r.test_reference,r.feedback_summary,r.receipt_reference,r.archive_reference,r.evidence_url,r.payload_hash,r.recorded_by,r.recorded_at from shareholder_register_filing.authority_test_runs r on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,obligation=excluded.obligation,environment=excluded.environment,status=excluded.status,test_reference=excluded.test_reference,feedback_summary=excluded.feedback_summary,receipt_reference=excluded.receipt_reference,archive_reference=excluded.archive_reference,evidence_url=excluded.evidence_url,payload_hash=excluded.payload_hash,recorded_by=excluded.recorded_by,recorded_at=excluded.recorded_at;

drop policy if exists "legacy_rf1086_approval_read" on shareholder_register_filing.filing_approval_snapshots;

drop policy if exists "legacy_rf1086_preview_read" on public.filing_previews;

drop policy if exists "legacy_rf1086_artifact_read" on shareholder_register_filing.production_feedback_artifacts;

drop policy if exists "legacy_rf1086_event_read" on shareholder_register_filing.production_filing_events;

drop policy if exists "legacy_rf1086_submission_read" on shareholder_register_filing.production_filing_submissions;

drop function if exists public.release_production_feedback_reconciliation(uuid, uuid);

drop function if exists public.approve_production_filing(uuid, uuid, jsonb, text, text);

drop function if exists public.append_production_filing_event(uuid, text, text, integer, text, uuid, text, text, text, boolean);

drop function if exists public.begin_production_filing(uuid);

drop function if exists public.claim_production_feedback_reconciliation(uuid, uuid);

drop function if exists public.record_production_feedback_artifact(uuid, uuid, uuid, text, text, bigint, text, text);

drop function if exists legacy_rf1086.assert_fresh_owner_v1(uuid);

drop function if exists legacy_rf1086.actor_v1();

drop function if exists legacy_rf1086.can_read_company_v1(uuid);

drop function if exists legacy_rf1086.can_read_submission_v1(uuid);

drop function if exists legacy_rf1086.assert_submission_v1(uuid);

drop function if exists legacy_rf1086.prepare_operation_v1(uuid, text, text, uuid);

drop function if exists public.append_production_feedback_reconciliation(uuid, uuid, uuid, text, text[], text, text);

drop view if exists public.filing_approval_snapshots;

alter table shareholder_register_filing.filing_approval_snapshots set schema public;

alter table public.filing_approval_snapshots owner to postgres;

drop view if exists public.production_filing_submissions;

alter table shareholder_register_filing.production_filing_submissions set schema public;

alter table public.production_filing_submissions owner to postgres;

drop view if exists public.production_filing_events;

alter table shareholder_register_filing.production_filing_events set schema public;

alter table public.production_filing_events owner to postgres;

drop view if exists public.production_feedback_artifacts;

alter table shareholder_register_filing.production_feedback_artifacts set schema public;

alter table public.production_feedback_artifacts owner to postgres;

alter table public.filing_approval_snapshots drop constraint filing_approval_snapshots_preview_id_fkey; alter table public.filing_approval_snapshots add constraint filing_approval_snapshots_preview_id_fkey foreign key(preview_id) references public.filing_previews(id) on delete restrict;

create temporary table rf151_function_schema_grants(schema_name name,role_name name,had_create boolean,primary key(schema_name,role_name)) on commit drop;
do $original_functions$ declare item record; signature text; schema_name text; function_owner text; current_grantee oid; v_acl record; grantee text; begin
 for item in select * from pg_catalog.jsonb_each((select original_objects from rf151_saved_objects)) loop
  schema_name:=pg_catalog.split_part(item.key,'.',1); function_owner:=item.value->>'owner';
  insert into rf151_function_schema_grants values(schema_name,function_owner,pg_catalog.has_schema_privilege(function_owner,schema_name,'CREATE')) on conflict do nothing;
  execute pg_catalog.format('grant create on schema %I to %I',schema_name,function_owner);
  execute pg_catalog.format('set local role %I',function_owner);
  execute item.value->>'definition';
  execute 'reset role';
  signature:=item.key;
  for current_grantee in select distinct a.grantee from pg_catalog.pg_proc p cross join lateral pg_catalog.aclexplode(p.proacl) a where p.oid=signature::regprocedure loop
   grantee:=case when current_grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(current_grantee)) end;
   execute 'revoke all on function '||signature||' from '||grantee;
  end loop;
  execute 'revoke all on function '||signature||' from public';
  if item.value->'acl'='null'::jsonb then
   execute 'grant execute on function '||signature||' to public,'||pg_catalog.quote_ident(function_owner);
  else
   for v_acl in select * from pg_catalog.aclexplode(array(select value::aclitem from pg_catalog.jsonb_array_elements_text(item.value->'acl'))) loop
    grantee:=case when v_acl.grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(v_acl.grantee)) end;
    execute 'grant execute on function '||signature||' to '||grantee||case when v_acl.is_grantable then ' with grant option' else '' end;
   end loop;
  end if;
 end loop;
end; $original_functions$;

grant select on rf151_saved_objects to billing_store_owner;
set local role billing_store_owner;
do $billing_policies$ declare p record; begin
 for p in select * from pg_catalog.jsonb_each((select original_foreign_policies from rf151_saved_objects)) loop
 execute pg_catalog.format('alter policy %I on billing.production_pilot_entitlements%s%s',p.key,case when p.value->>'qual' is null then '' else ' using ('||(p.value->>'qual')||')' end,case when p.value->>'check' is null then '' else ' with check ('||(p.value->>'check')||')' end);
 end loop;
end; $billing_policies$;
reset role;

do $restore_relations$ declare item record; current_grantee oid; acl record; target text; grantee text; begin
 for item in select * from pg_catalog.jsonb_each((select original_relations from rf151_saved_objects)) loop
  target:='public.'||pg_catalog.quote_ident(item.key);
  for current_grantee in select distinct a.grantee from pg_catalog.pg_class c cross join lateral pg_catalog.aclexplode(c.relacl) a where c.oid=pg_catalog.to_regclass(target) loop
   grantee:=case when current_grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(current_grantee)) end;
   execute 'revoke all on '||target||' from '||grantee;
  end loop;
  if item.value->'acl'='null'::jsonb then execute pg_catalog.format('grant all on %s to %I',target,item.value->>'owner');
  else
   for acl in select * from pg_catalog.aclexplode(array(select value::aclitem from pg_catalog.jsonb_array_elements_text(item.value->'acl'))) loop
    grantee:=case when acl.grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(acl.grantee)) end;
    execute 'grant '||acl.privilege_type||' on '||target||' to '||grantee||case when acl.is_grantable then ' with grant option' else '' end;
   end loop;
  end if;
  if (item.value->>'force_rls')::boolean then execute 'alter table '||target||' force row level security';
  else execute 'alter table '||target||' no force row level security'; end if;
 end loop;
end; $restore_relations$;

do $policies$ declare item record; begin
 for item in select n.nspname,c.relname,p.polname from pg_catalog.pg_policy p join pg_catalog.pg_class c on c.oid=p.polrelid join pg_catalog.pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and p.polname like 'rf151_%' loop
  execute pg_catalog.format('drop policy %I on %I.%I',item.polname,item.nspname,item.relname);
 end loop;
end; $policies$;

create policy "legacy_rf1086_approval_read" on public.filing_approval_snapshots for SELECT to "legacy_rf1086_executor" using (((user_id = legacy_rf1086.actor_v1()) AND legacy_rf1086.can_read_company_v1(company_id)));

create policy "legacy_rf1086_preview_read" on public.filing_previews for SELECT to "legacy_rf1086_executor" using (legacy_rf1086.can_read_company_v1(company_id));

create policy "legacy_rf1086_artifact_read" on public.production_feedback_artifacts for SELECT to "legacy_rf1086_executor" using (legacy_rf1086.can_read_submission_v1(submission_id));

create policy "legacy_rf1086_event_read" on public.production_filing_events for SELECT to "legacy_rf1086_executor" using (legacy_rf1086.can_read_submission_v1(submission_id));

create policy "legacy_rf1086_submission_read" on public.production_filing_submissions for SELECT to "legacy_rf1086_executor" using (((user_id = legacy_rf1086.actor_v1()) AND legacy_rf1086.can_read_company_v1(company_id)));

grant execute on function public.company_archive_track_source_write_v1() to postgres;

drop trigger if exists company_archive_track_filing_previews on public.filing_previews;

CREATE TRIGGER company_archive_track_filing_previews BEFORE INSERT OR DELETE OR UPDATE ON public.filing_previews FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');

drop trigger if exists company_archive_track_filing_submissions on public.filing_submissions;

CREATE TRIGGER company_archive_track_filing_submissions BEFORE INSERT OR DELETE OR UPDATE ON public.filing_submissions FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');

drop trigger if exists company_archive_track_filing_review_comments on public.filing_review_comments;

CREATE TRIGGER company_archive_track_filing_review_comments BEFORE INSERT OR DELETE OR UPDATE ON public.filing_review_comments FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

drop trigger if exists company_archive_track_authority_permissions on public.authority_permissions;

CREATE TRIGGER company_archive_track_authority_permissions BEFORE INSERT OR DELETE OR UPDATE ON public.authority_permissions FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

drop trigger if exists company_archive_track_authority_test_runs on public.authority_test_runs;

CREATE TRIGGER company_archive_track_authority_test_runs BEFORE INSERT OR DELETE OR UPDATE ON public.authority_test_runs FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

drop trigger if exists company_archive_track_opening_balance_setups on public.opening_balance_setups;

CREATE TRIGGER company_archive_track_opening_balance_setups BEFORE INSERT OR DELETE OR UPDATE ON public.opening_balance_setups FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');

drop trigger if exists company_archive_track_opening_shareholders on public.opening_shareholders;

CREATE TRIGGER company_archive_track_opening_shareholders BEFORE INSERT OR DELETE OR UPDATE ON public.opening_shareholders FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

revoke execute on function public.company_archive_track_source_write_v1() from postgres;

drop function if exists backend_system.read_new_year_opening_snapshots_v1(uuid[],text,integer,text,integer);

drop function if exists backend_system.sync_rf_preparation_projection_v1();

drop function if exists backend_system.sync_rf_opening_projection_v1();

drop function if exists backend_system.capture_legacy_rf_opening_bank_v1();

drop function if exists backend_system.admit_rf_opening_scope_v1();

drop function if exists backend_system.rf_opening_quarantine_count_v1(uuid,uuid[]);

drop function if exists backend_system.rf1086_stored_release_inputs_v1(uuid,integer,text);

drop function if exists backend_system.rf1086_annual_readiness_ready_v1(uuid,integer,text);

drop function if exists backend_system.rf1086_technical_release_ready_v1();

drop function ledger.record_opening_bank_input_v1(uuid,uuid,integer,numeric,text);
drop function ledger.read_opening_bank_inputs_v1(uuid,integer,text);
drop function if exists ledger.capture_legacy_opening_bank_input_v1(uuid,uuid,integer,numeric,uuid,timestamptz);
drop table ledger.opening_bank_inputs;

revoke select,insert,update on public.opening_balance_setups from shareholder_register_filing_store_owner;

revoke select,insert,update on public.opening_shareholders from shareholder_register_filing_store_owner;

revoke select,insert,update on public.filing_previews from shareholder_register_filing_store_owner;

revoke select,insert,update on public.filing_submissions from shareholder_register_filing_store_owner;

revoke select,insert,update on public.filing_overrides from shareholder_register_filing_store_owner;

revoke select,insert,update on public.filing_review_comments from shareholder_register_filing_store_owner;

revoke select,insert,update on public.authority_permissions from shareholder_register_filing_store_owner;

revoke select,insert,update on public.authority_test_runs from shareholder_register_filing_store_owner;

drop schema shareholder_register_filing cascade;

drop function public.company_access_can_review_filing_v1(uuid); drop function public.company_access_read_rf_company_identity_v1(uuid,text);

revoke shareholder_register_filing_executor from talli_ledger_backend;

do $function_schema_cleanup$ declare r record; begin
 for r in select * from rf151_function_schema_grants where not had_create loop
 execute pg_catalog.format('revoke create on schema %I from %I',r.schema_name,r.role_name);
 end loop;
end; $function_schema_cleanup$;

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
