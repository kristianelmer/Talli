-- Read immutable annual-close decisions under their existing company guard.
-- FOR UPDATE also needs an UPDATE RLS policy; these rows intentionally have none.
-- https://www.postgresql.org/docs/17/sql-createpolicy.html
-- No table access, reader semantics, browser authority or business writer changes.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table corporate_immutable_read_authority(role_name text, prior jsonb) on commit drop;
do $borrow$
declare p jsonb; r text;
begin
 foreach r in array array['corporate_governance_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(r)
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.corporate_immutable_read_authority values(r,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
set local role corporate_governance_store_owner;
do $patch$
declare row record; routine oid; body text; changed text; definition text; current_hash text;
begin
 if pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_functiondef(
  'corporate_governance.acquire_company_write_guard_v1(uuid,text)'::regprocedure),'UTF8')),'hex')<>'6f95422122bfc9e8145dfbc0cfccd7e5f865d60e21534b36fb2727ea86275343' then
  raise exception 'corporate_immutable_guard_definition_unproven'; end if;
 for row in select * from (values
  ('corporate_governance.approve_annual_close_v1(jsonb, text)','39979038231c272b6057d3b3e1d0ebc879dc91b3d64a779092dbf1b98a6bcf93','0a8e29712a186de71f77396dba4495da0a0d3a739e226221d031605de22a81e3'),
  ('corporate_governance.attest_annual_close_signed_artifact_v1(jsonb, text)','11c4660d763af3d7564219ea59686bd534a9e1912e7dbfee35c75c566bc1af7a','603def791c69a644a747a4645abf008882e04dded7eef90cc37e72ac4793020f'),
  ('corporate_governance.finalize_annual_close_v1(jsonb, text)','bea80877911c74288c78739d25cd317c0770f12c1e5093235437ce756860a5f7','1d036ec0a461a01a646d80b26a44ae29fe9ab79c0814e48981d9f3575c8dfe80'),
  ('corporate_governance.propose_annual_close_v1(jsonb, jsonb, jsonb, jsonb, text)','2edb8d6dcea2c007aeb6d88bac5b9045658a746ee102c364d5fd30763d21d4d3','7e5bbd9f4dcdadca30f64689e9b3811b8426ca13f0068d83fc1283d46872cdf0'),
  ('corporate_governance.record_annual_close_event_v1(jsonb, text)','1aa381ad9b2b2f601524f4b5a3d2615ff2749f75246e6f797f6d2deb79226812','0ace357c07eca6a62de7c9bce5430e4a2f4516825d12d7477be7711699a2af7e'),
  ('corporate_governance.register_annual_close_documents_v1(jsonb, text)','dde58370bf4b76c6c4c4a23d4ed9c93e44f0aff8ebef0e4648f6164dec8c59bf','e4d83e52930592a1ad864762afc23573ca60a9ccabdc6877b04fb0c987ef5d5f')
 ) expected(signature,before_hash,after_hash) loop
  routine:=pg_catalog.to_regprocedure(row.signature);
  select p.prosrc,pg_catalog.pg_get_functiondef(p.oid) into body,definition from pg_catalog.pg_proc p
   where p.oid=routine and p.proowner='corporate_governance_store_owner'::regrole and p.prosecdef;
  if body is null or pg_catalog.strpos(body,'rf193-company-write-guard-v1')=0 then
   raise exception 'corporate_immutable_guarded_reader_unproven'; end if;
  current_hash:=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(body,'UTF8')),'hex');
  if current_hash=row.after_hash then continue; end if;
  if current_hash<>row.before_hash then raise exception 'corporate_immutable_reader_definition_drift'; end if;
  changed:=pg_catalog.replace(body,'for update','/* accounts-immutable-row-read-v1: published company guard held */');
  if pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(changed,'UTF8')),'hex')<>row.after_hash then
   raise exception 'corporate_immutable_reader_patch_unproven'; end if;
  execute pg_catalog.replace(definition,body,changed);
 end loop;
end; $patch$;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.corporate_immutable_read_authority loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
