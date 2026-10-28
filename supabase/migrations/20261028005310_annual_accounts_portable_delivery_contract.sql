-- Keep Accounts retention attestation valid after native catalog IDs change.
-- Existing v4 upgrades require the unchanged installed contract; no rebaselining
-- of changed permissions/helpers is permitted. Fresh installs use the portable
-- contract generators after the final capability topology is installed.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:annual-accounts-filing:migration:v1',0));
do $upgrade$
declare
 reader oid:=pg_catalog.to_regprocedure('annual_accounts_filing.read_source_snapshot_v4(uuid,integer,text)');
 body text; definition text; normalized text; literal text; expected jsonb;
 legacy_current jsonb; portable_current jsonb; prefix text:='expected_contract jsonb:=';
 start_at integer; extent integer; caller name:=current_user; prior jsonb; borrowed boolean:=false;
 before_acl text; before_owner oid; portable_body text:=$portable_body$
declare result jsonb; events jsonb; n bigint; bytes bigint; contract boolean; current_contract jsonb; expected_contract jsonb:=__EVENT_CONTRACT_MANIFEST__::jsonb; begin
 result:=annual_accounts_filing.read_source_snapshot_v2(p_company,p_year,p_subject);
 select count(*),coalesce(sum(pg_catalog.octet_length(e.canonical_json)),0) into n,bytes
  from annual_accounts_filing.delivery_events e where e.company_id=p_company and e.income_year=p_year;
 if n>10000 or bytes>67108864 then raise exception 'annual_accounts_unavailable'; end if;
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(e) order by e.sequence),'[]'::jsonb) into events
  from annual_accounts_filing.delivery_events e where e.company_id=p_company and e.income_year=p_year;
 select coalesce(pg_catalog.jsonb_object_agg(item.key,item.hash),'{}'::jsonb) into current_contract from (
 select 'function:'||p.proname as key,pg_catalog.md5(pg_catalog.jsonb_build_array(pg_catalog.pg_get_functiondef(p.oid),pg_catalog.pg_get_userbyid(p.proowner)::text)::text) as hash
 from pg_catalog.pg_proc p where p.oid in (
  'annual_accounts_filing.delivery_canonical_json_v1(jsonb,integer)'::regprocedure,
  'annual_accounts_filing.delivery_bytes_v1(text,integer)'::regprocedure,
  'annual_accounts_filing.delivery_json_original_v1(text)'::regprocedure,
  'annual_accounts_filing.delivery_record_scope_v1(text,uuid,uuid,integer,uuid)'::regprocedure,
  'annual_accounts_filing.delivery_link_v1(uuid,text,text)'::regprocedure,
  'annual_accounts_filing.delivery_known_instance_v1(uuid)'::regprocedure,
  'annual_accounts_filing.delivery_known_file_v1(uuid,text,text,text,timestamptz)'::regprocedure,
  'annual_accounts_filing.delivery_correction_known_file_v1(uuid,text,text,timestamptz)'::regprocedure,
  'annual_accounts_filing.delivery_correction_frame_valid_v1(uuid,jsonb)'::regprocedure,
  'annual_accounts_filing.delivery_creation_permitted_v2(uuid,uuid,integer)'::regprocedure,
  'annual_accounts_filing.append_delivery_event_v2(text,text,text)'::regprocedure,
  'annual_accounts_filing.append_delivery_event_v1(text,text,text)'::regprocedure,
  'annual_accounts_filing.read_source_snapshot_v2(uuid,integer,text)'::regprocedure)
 union all
 select 'constraint:'||x.conname,pg_catalog.md5(pg_catalog.pg_get_constraintdef(x.oid)||':'||x.convalidated::text)
 from pg_catalog.pg_constraint x where x.conrelid='annual_accounts_filing.delivery_events'::regclass
  and x.conname in ('accounts_delivery_event_scope','accounts_delivery_event_slots')
 union all
 select 'index:'||c.relname,pg_catalog.md5(pg_catalog.pg_get_indexdef(c.oid)||':'||i.indisvalid::text||':'||i.indisunique::text) from pg_catalog.pg_class c join pg_catalog.pg_index i on i.indexrelid=c.oid where c.oid='annual_accounts_filing.accounts_delivery_one_child_v1'::regclass
 union all
 select 'policy:'||n.nspname||'.'||c.relname||'.'||p.polname,
  pg_catalog.md5(pg_catalog.jsonb_build_object(
   'command',p.polcmd::text,'permissive',p.polpermissive,
   'roles',(select pg_catalog.jsonb_agg(case when r=0 then 'PUBLIC' else pg_catalog.pg_get_userbyid(r)::text end
    order by (case when r=0 then 'PUBLIC' else pg_catalog.pg_get_userbyid(r)::text end) collate pg_catalog."C") from pg_catalog.unnest(p.polroles) r),
   'using',pg_catalog.pg_get_expr(p.polqual,p.polrelid),
   'check',pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid))::text)
 from pg_catalog.pg_policy p join pg_catalog.pg_class c on c.oid=p.polrelid
 join pg_catalog.pg_namespace n on n.oid=c.relnamespace
 where p.polrelid in ('annual_accounts_filing.delivery_events'::regclass,'annual_accounts_filing.delivery_drafts'::regclass)
) item;
 contract:=current_contract=expected_contract;
 -- The contract covers executable helpers, exact checks and all retention
 -- policies. Reader/append ACLs remain explicit, never inferred from names.
 contract:=contract and not exists(
  select 1 from (values('anon'),('authenticated'),('service_role')) r(role)
  where pg_catalog.has_function_privilege(r.role,'annual_accounts_filing.append_delivery_event_v1(text,text,text)','EXECUTE')
   or pg_catalog.has_function_privilege(r.role,'annual_accounts_filing.append_delivery_event_v2(text,text,text)','EXECUTE')
   or pg_catalog.has_function_privilege(r.role,'annual_accounts_filing.read_source_snapshot_v4(uuid,integer,text)','EXECUTE')
   or pg_catalog.has_table_privilege(r.role,'annual_accounts_filing.delivery_events','SELECT,INSERT,UPDATE,DELETE'));

 if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'annual_accounts_mfa_required'; end if;
 return result||pg_catalog.jsonb_build_object('asOf',pg_catalog.clock_timestamp(),'contractVersion','annual-accounts-source-v4','deliveryEvents',events,
  'coverage',(result->'coverage')||pg_catalog.jsonb_build_object('contractVersion','annual-accounts-source-v4','deliveryEventCodecVersion','annual-accounts-delivery-events-v2',
   'deliveryEventCount',n,'deliveryEventContractValid',coalesce(contract,false),
   'deliveryOperationsEnabled',annual_accounts_filing.delivery_operations_enabled_v1(),
   'deliveryCorrectionsEnabled',annual_accounts_filing.delivery_corrections_enabled_v1(),
   'deliveryDraftWritesEnabled',annual_accounts_filing.delivery_draft_writes_enabled_v1(),
   'deliveryEventDigests',coalesce((select pg_catalog.jsonb_object_agg(e.sequence::text,e.event_sha256 order by e.sequence)
    from annual_accounts_filing.delivery_events e where e.company_id=p_company and e.income_year=p_year),'{}'::jsonb)));
end; $portable_body$;
begin
 if reader is null then return; end if;
 if not pg_catalog.pg_has_role(caller,'annual_accounts_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into prior
   from pg_catalog.pg_auth_members m where m.roleid='annual_accounts_filing_store_owner'::regrole
    and m.member=pg_catalog.to_regrole(caller) and m.grantor=m.member;
  execute pg_catalog.format('grant annual_accounts_filing_store_owner to %I with set true granted by %I',caller,caller);
  borrowed:=true;
 end if;
 execute 'set local role annual_accounts_filing_store_owner';
 lock table annual_accounts_filing.delivery_drafts,annual_accounts_filing.delivery_events in share mode;
 select p.prosrc,pg_catalog.pg_get_functiondef(p.oid),p.proacl::text,p.proowner
 into body,definition,before_acl,before_owner from pg_catalog.pg_proc p
 where p.oid=reader and p.prokind='f' and p.prosecdef and not p.proleakproof
  and not p.proisstrict and p.provolatile='v' and p.proparallel='u'
  and p.proconfig=array['search_path=""']::text[]
  and pg_catalog.pg_get_userbyid(p.proowner)='annual_accounts_filing_store_owner';
 if body is null or exists(select 1 from pg_catalog.pg_roles where rolname='annual_accounts_filing_store_owner'
    and (rolsuper or rolbypassrls or rolcanlogin))
  or (select count(*) from pg_catalog.pg_class where oid in
   ('annual_accounts_filing.delivery_drafts'::regclass,'annual_accounts_filing.delivery_events'::regclass)
   and relrowsecurity and relforcerowsecurity and pg_catalog.pg_get_userbyid(relowner)='annual_accounts_filing_store_owner')<>2 then
  raise exception 'annual_accounts_portable_contract_predecessor_required'; end if;
 -- A legacy unqualified policy key must not hide another table's policy.
 if exists(select polname from pg_catalog.pg_policy where polrelid in
  ('annual_accounts_filing.delivery_drafts'::regclass,'annual_accounts_filing.delivery_events'::regclass)
  group by polname having count(*)>1) then raise exception 'annual_accounts_portable_contract_changed'; end if;
 -- Parse only the known quoted JSON manifest; never execute catalog text.
 start_at:=pg_catalog.strpos(body,prefix);
 if start_at=0 then raise exception 'annual_accounts_portable_contract_predecessor_required'; end if;
 start_at:=start_at+pg_catalog.length(prefix);
 extent:=pg_catalog.strpos(pg_catalog.substr(body,start_at),'::jsonb; begin')-1;
 if extent<3 then raise exception 'annual_accounts_portable_contract_predecessor_required'; end if;
 literal:=pg_catalog.substr(body,start_at,extent);
 if pg_catalog.left(literal,1)<>pg_catalog.chr(39) or pg_catalog.right(literal,1)<>pg_catalog.chr(39)
  or pg_catalog.strpos(pg_catalog.substr(literal,2,pg_catalog.length(literal)-2),pg_catalog.chr(39))<>0 then
  raise exception 'annual_accounts_portable_contract_predecessor_required'; end if;
 expected:=pg_catalog.substr(literal,2,pg_catalog.length(literal)-2)::jsonb;
 if pg_catalog.jsonb_typeof(expected)<>'object' then raise exception 'annual_accounts_portable_contract_predecessor_required'; end if;
 normalized:=pg_catalog.substr(body,1,start_at-1)||'__EVENT_CONTRACT_MANIFEST__'||pg_catalog.substr(body,start_at+extent);
 if pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(normalized,'UTF8')),'hex') not in
  ('b2d28c2a4e51d2f6c6a4cd9ba5de06bafd0aa067acfaad8d9619ab9ffb4fe33d','fd632344fe246d13abf3bb33956851c5639439aea746bb1cfb10d9934bc30e50') then
  raise exception 'annual_accounts_portable_contract_predecessor_required'; end if;
select coalesce(pg_catalog.jsonb_object_agg(item.key,item.hash),'{}'::jsonb) into legacy_current from (
 select 'function:'||p.proname as key,pg_catalog.md5(pg_catalog.pg_get_functiondef(p.oid)||':'||p.proowner::text) as hash
 from pg_catalog.pg_proc p where p.oid in (
  'annual_accounts_filing.delivery_canonical_json_v1(jsonb,integer)'::regprocedure,
  'annual_accounts_filing.delivery_bytes_v1(text,integer)'::regprocedure,
  'annual_accounts_filing.delivery_json_original_v1(text)'::regprocedure,
  'annual_accounts_filing.delivery_record_scope_v1(text,uuid,uuid,integer,uuid)'::regprocedure,
  'annual_accounts_filing.delivery_link_v1(uuid,text,text)'::regprocedure,
  'annual_accounts_filing.delivery_known_instance_v1(uuid)'::regprocedure,
  'annual_accounts_filing.delivery_known_file_v1(uuid,text,text,text,timestamptz)'::regprocedure,
  'annual_accounts_filing.delivery_correction_known_file_v1(uuid,text,text,timestamptz)'::regprocedure,
  'annual_accounts_filing.delivery_correction_frame_valid_v1(uuid,jsonb)'::regprocedure,
  'annual_accounts_filing.delivery_creation_permitted_v2(uuid,uuid,integer)'::regprocedure,
  'annual_accounts_filing.append_delivery_event_v2(text,text,text)'::regprocedure,
  'annual_accounts_filing.append_delivery_event_v1(text,text,text)'::regprocedure,
  'annual_accounts_filing.read_source_snapshot_v2(uuid,integer,text)'::regprocedure)
 union all
 select 'constraint:'||x.conname,pg_catalog.md5(pg_catalog.pg_get_constraintdef(x.oid)||':'||x.convalidated::text)
 from pg_catalog.pg_constraint x where x.conrelid='annual_accounts_filing.delivery_events'::regclass
  and x.conname in ('accounts_delivery_event_scope','accounts_delivery_event_slots')
 union all
 select 'index:'||c.relname,pg_catalog.md5(pg_catalog.pg_get_indexdef(c.oid)||':'||i.indisvalid::text||':'||i.indisunique::text) from pg_catalog.pg_class c join pg_catalog.pg_index i on i.indexrelid=c.oid where c.oid='annual_accounts_filing.accounts_delivery_one_child_v1'::regclass
 union all
 select 'policy:'||p.polname,pg_catalog.md5(pg_catalog.to_jsonb(p)::text)
 from pg_catalog.pg_policy p where p.polrelid in ('annual_accounts_filing.delivery_events'::regclass,'annual_accounts_filing.delivery_drafts'::regclass)
) item;
select coalesce(pg_catalog.jsonb_object_agg(item.key,item.hash),'{}'::jsonb) into portable_current from (
 select 'function:'||p.proname as key,pg_catalog.md5(pg_catalog.jsonb_build_array(pg_catalog.pg_get_functiondef(p.oid),pg_catalog.pg_get_userbyid(p.proowner)::text)::text) as hash
 from pg_catalog.pg_proc p where p.oid in (
  'annual_accounts_filing.delivery_canonical_json_v1(jsonb,integer)'::regprocedure,
  'annual_accounts_filing.delivery_bytes_v1(text,integer)'::regprocedure,
  'annual_accounts_filing.delivery_json_original_v1(text)'::regprocedure,
  'annual_accounts_filing.delivery_record_scope_v1(text,uuid,uuid,integer,uuid)'::regprocedure,
  'annual_accounts_filing.delivery_link_v1(uuid,text,text)'::regprocedure,
  'annual_accounts_filing.delivery_known_instance_v1(uuid)'::regprocedure,
  'annual_accounts_filing.delivery_known_file_v1(uuid,text,text,text,timestamptz)'::regprocedure,
  'annual_accounts_filing.delivery_correction_known_file_v1(uuid,text,text,timestamptz)'::regprocedure,
  'annual_accounts_filing.delivery_correction_frame_valid_v1(uuid,jsonb)'::regprocedure,
  'annual_accounts_filing.delivery_creation_permitted_v2(uuid,uuid,integer)'::regprocedure,
  'annual_accounts_filing.append_delivery_event_v2(text,text,text)'::regprocedure,
  'annual_accounts_filing.append_delivery_event_v1(text,text,text)'::regprocedure,
  'annual_accounts_filing.read_source_snapshot_v2(uuid,integer,text)'::regprocedure)
 union all
 select 'constraint:'||x.conname,pg_catalog.md5(pg_catalog.pg_get_constraintdef(x.oid)||':'||x.convalidated::text)
 from pg_catalog.pg_constraint x where x.conrelid='annual_accounts_filing.delivery_events'::regclass
  and x.conname in ('accounts_delivery_event_scope','accounts_delivery_event_slots')
 union all
 select 'index:'||c.relname,pg_catalog.md5(pg_catalog.pg_get_indexdef(c.oid)||':'||i.indisvalid::text||':'||i.indisunique::text) from pg_catalog.pg_class c join pg_catalog.pg_index i on i.indexrelid=c.oid where c.oid='annual_accounts_filing.accounts_delivery_one_child_v1'::regclass
 union all
 select 'policy:'||n.nspname||'.'||c.relname||'.'||p.polname,
  pg_catalog.md5(pg_catalog.jsonb_build_object(
   'command',p.polcmd::text,'permissive',p.polpermissive,
   'roles',(select pg_catalog.jsonb_agg(case when r=0 then 'PUBLIC' else pg_catalog.pg_get_userbyid(r)::text end
    order by (case when r=0 then 'PUBLIC' else pg_catalog.pg_get_userbyid(r)::text end) collate pg_catalog."C") from pg_catalog.unnest(p.polroles) r),
   'using',pg_catalog.pg_get_expr(p.polqual,p.polrelid),
   'check',pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid))::text)
 from pg_catalog.pg_policy p join pg_catalog.pg_class c on c.oid=p.polrelid
 join pg_catalog.pg_namespace n on n.oid=c.relnamespace
 where p.polrelid in ('annual_accounts_filing.delivery_events'::regclass,'annual_accounts_filing.delivery_drafts'::regclass)
) item;
 if exists(select 1 from (values('anon'),('authenticated'),('service_role')) r(role)
  where pg_catalog.has_function_privilege(r.role,'annual_accounts_filing.append_delivery_event_v1(text,text,text)','EXECUTE')
   or pg_catalog.has_function_privilege(r.role,'annual_accounts_filing.append_delivery_event_v2(text,text,text)','EXECUTE')
   or pg_catalog.has_function_privilege(r.role,reader,'EXECUTE')
   or pg_catalog.has_table_privilege(r.role,'annual_accounts_filing.delivery_events','SELECT,INSERT,UPDATE,DELETE')) then
  raise exception 'annual_accounts_portable_contract_permission_mismatch'; end if;
 if normalized=portable_body then
  if expected is distinct from portable_current then raise exception 'annual_accounts_portable_contract_changed'; end if;
  portable_body:=body;
 else
  if expected is distinct from legacy_current then raise exception 'annual_accounts_portable_contract_changed'; end if;
  portable_body:=pg_catalog.replace(portable_body,'__EVENT_CONTRACT_MANIFEST__',pg_catalog.quote_literal(portable_current::text));
  execute pg_catalog.replace(definition,body,portable_body);
 end if;
 execute pg_catalog.format('set local role %I',caller);
 if borrowed then
  execute pg_catalog.format('revoke annual_accounts_filing_store_owner from %I granted by %I',caller,caller);
  if prior is not null then
   execute pg_catalog.format('grant annual_accounts_filing_store_owner to %I with admin %s, inherit %s, set %s granted by %I',
    caller,(prior->>'admin')::boolean,(prior->>'inherit')::boolean,(prior->>'set')::boolean,caller);
  end if;
 end if;
 if not exists(select 1 from pg_catalog.pg_proc where oid=reader and prosrc=portable_body
  and proowner=before_owner and proacl::text is not distinct from before_acl) then
  raise exception 'annual_accounts_portable_contract_postcondition'; end if;
end; $upgrade$;
commit;
