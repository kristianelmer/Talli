-- Closed Documents-owned validation of one retained metadata snapshot.
-- No current-document join, object-store IO, writer change or consumer grant.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table documents_original_integrity_role(prior jsonb) on commit drop;
create temporary table documents_original_integrity_create(added boolean) on commit drop;
do $borrow$
declare prior jsonb; schema_owner text;
begin
 if not pg_catalog.pg_has_role(current_user,'documents_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into prior from pg_catalog.pg_auth_members m where m.roleid='documents_store_owner'::regrole
   and m.member=current_user::regrole and m.grantor=m.member;
  insert into pg_temp.documents_original_integrity_role values(prior);
  execute pg_catalog.format('grant documents_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
 insert into pg_temp.documents_original_integrity_create values(not pg_catalog.has_schema_privilege('documents_store_owner','documents','CREATE'));
 if (select added from pg_temp.documents_original_integrity_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='documents';
  execute pg_catalog.format('set local role %I',schema_owner);
  grant create on schema documents to documents_store_owner;
  reset role;
 end if;
end; $borrow$;
set local role documents_store_owner;

create or replace function documents.original_integrity_require_internal_v1(valid boolean)
returns void language plpgsql immutable security invoker set search_path='' as $fn$
begin
 if valid is distinct from true then raise exception 'documents_evidence_mismatch'; end if;
end; $fn$;

-- Exactly evidence.py's primitive JSON subset: compact, C-sorted, UTF-8. No
-- jsonb::text whitespace, booleans, floats, arrays or incidental SQL columns.
create or replace function documents.original_integrity_json_internal_v1(value jsonb)
returns text language plpgsql immutable strict security invoker set search_path='' as $fn$
declare result text; kind text:=pg_catalog.jsonb_typeof(value);
begin
 if kind='object' then
  select '{'||coalesce(pg_catalog.string_agg(pg_catalog.to_json(key)::text||':'||
   documents.original_integrity_json_internal_v1(item),',' order by key collate "C"),'')||'}'
   into result from pg_catalog.jsonb_each(value) e(key,item);
 elsif kind in ('null','string') then result:=value::text;
 elsif kind='number' and value::text ~ '^-?(0|[1-9][0-9]*)$' then result:=value::text;
 else raise exception 'documents_evidence_mismatch'; end if;
 return result;
end; $fn$;

-- to_jsonb(timestamptz) strings have an explicit offset and at most six decimal
-- places. Normalize to Python UTC isoformat(), retaining microsecond precision.
create or replace function documents.original_integrity_time_internal_v1(value text)
returns text language plpgsql immutable security invoker set search_path='' as $fn$
declare pieces text[]; civil timestamp; utc_value timestamp; seconds integer; result text;
begin
 pieces:=pg_catalog.regexp_match(value,'^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(\.[0-9]{1,6})?([+-])([0-9]{2}):([0-9]{2})(:([0-9]{2}))?$');
 perform documents.original_integrity_require_internal_v1(pieces is not null);
 civil:=(pieces[1]||coalesce(pieces[2],''))::timestamp;
 perform documents.original_integrity_require_internal_v1(
  pg_catalog.to_char(civil,'YYYY-MM-DD"T"HH24:MI:SS')=pieces[1]
  and extract(year from civil) between 1 and 9999
  and pieces[4]::integer<24 and pieces[5]::integer<60 and coalesce(pieces[7]::integer,0)<60);
 seconds:=pieces[4]::integer*3600+pieces[5]::integer*60+coalesce(pieces[7]::integer,0);
 if pieces[3]='-' then seconds:=-seconds; end if;
 utc_value:=civil-seconds*interval '1 second';
 perform documents.original_integrity_require_internal_v1(extract(year from utc_value) between 1 and 9999);
 result:=pg_catalog.to_char(utc_value,'YYYY-MM-DD"T"HH24:MI:SS');
 if mod(extract(microseconds from utc_value),1000000)<>0 then result:=result||'.'||pg_catalog.to_char(utc_value,'US'); end if;
 return result||'+00:00';
exception when datetime_field_overflow or invalid_datetime_format or numeric_value_out_of_range then
 raise exception 'documents_evidence_mismatch';
end; $fn$;

-- The sole retained snapshot writer stores to_jsonb(public.documents), whose
-- 23-column shape predates all retained originals. Seven SQL-only columns are
-- shape-checked but absent from the unchanged 16-field DocumentRecord digest.
create or replace function documents.original_integrity_document_internal_v1(snapshot jsonb)
returns text language plpgsql immutable security invoker set search_path='' as $fn$
declare shape constant jsonb:='{
 "id":"uuid","company_id":"uuid","income_year":"year","document_type":"text",
 "name":"text","linked_to":"text","status":"text","retention_years":"integer",
 "storage_key":"text","created_by":"uuid","created_at":"time",
 "removed_at":"time?","removed_by":"uuid?","removal_reason":"text?",
 "content_type":"text?","declared_byte_length":"length?","byte_length":"length",
 "content_sha256":"sha","staged_at":"time?","quarantined_at":"time?",
 "quarantine_reason":"text?","final_status":"text?","removed_from_status":"text?"}'::jsonb;
 key text; expected text; item jsonb; rendered text; projected jsonb;
begin
 perform documents.original_integrity_require_internal_v1(pg_catalog.jsonb_typeof(snapshot)='object');
 perform documents.original_integrity_require_internal_v1(
  (select array_agg(k order by k collate "C") from pg_catalog.jsonb_object_keys(snapshot) k)
   =(select array_agg(k order by k collate "C") from pg_catalog.jsonb_object_keys(shape) k));
 for key,expected in select * from pg_catalog.jsonb_each_text(shape) loop
  item:=snapshot->key;
  if right(expected,1)='?' then
   if item='null'::jsonb then continue; end if;
   expected:=left(expected,-1);
  end if;
  if expected in ('integer','year','length') then
   perform documents.original_integrity_require_internal_v1(pg_catalog.jsonb_typeof(item)='number'
    and item::text ~ '^-?(0|[1-9][0-9]*)$' and length(item::text)<=11);
   perform documents.original_integrity_require_internal_v1(item::text::numeric between -2147483648 and 2147483647);
   if expected='year' then perform documents.original_integrity_require_internal_v1(item::text::integer between 2000 and 2100); end if;
   if expected='length' then perform documents.original_integrity_require_internal_v1(item::text::integer between 1 and 10485760); end if;
  else
   perform documents.original_integrity_require_internal_v1(pg_catalog.jsonb_typeof(item)='string');
   rendered:=item#>>'{}';
   if expected='uuid' then perform documents.original_integrity_require_internal_v1(rendered ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$');
   elsif expected='sha' then perform documents.original_integrity_require_internal_v1(rendered ~ '^[0-9a-f]{64}$');
   elsif expected='time' then perform documents.original_integrity_time_internal_v1(rendered); end if;
  end if;
 end loop;
 -- Integrity does not decide whether a historical document is eligible for a
 -- future consumer. Preserve every existing DocumentStatus and removal time.
 perform documents.original_integrity_require_internal_v1(snapshot->>'status' in ('staged','attached','quarantined','removed',
  'generated_unsigned','signed_owner_attested','missing_accepted','missing_accepted_warning','not_required','stored'));
 projected:=pg_catalog.jsonb_build_object(
  'document_id',pg_catalog.jsonb_build_object('value',snapshot->>'id'),
  'company_id',pg_catalog.jsonb_build_object('value',snapshot->>'company_id'),
  'income_year',pg_catalog.jsonb_build_object('value',(snapshot->>'income_year')::integer),
  'document_type',snapshot->>'document_type','name',snapshot->>'name','linked_to',snapshot->>'linked_to',
  'status',snapshot->>'status','retention_years',(snapshot->>'retention_years')::integer,
  'storage_key',snapshot->>'storage_key','content_type',coalesce(nullif(snapshot->>'content_type',''),'application/pdf'),
  'byte_length',(snapshot->>'byte_length')::integer,'content_sha256',snapshot->>'content_sha256',
  'created_by',pg_catalog.jsonb_build_object('kind','USER','subject',pg_catalog.jsonb_build_object('value',snapshot->>'created_by')),
  'created_at',documents.original_integrity_time_internal_v1(snapshot->>'created_at'),
  'removed_at',case when snapshot->'removed_at'='null'::jsonb then null
   else documents.original_integrity_time_internal_v1(snapshot->>'removed_at') end,
  'removal_reason',nullif(snapshot->>'removal_reason',''));
 return documents.original_integrity_json_internal_v1(projected);
exception when invalid_text_representation or numeric_value_out_of_range or program_limit_exceeded then
 raise exception 'documents_evidence_mismatch';
end; $fn$;

create or replace function documents.assert_historical_original_integrity_v1(
 p_original uuid,p_document uuid,p_company uuid,p_source_year integer,p_metadata text,p_content_sha text,
 p_length integer,p_retained_at timestamptz,p_not_after timestamptz,p_subject text)
returns table(document_text text) language plpgsql volatile security definer set search_path='' as $fn$
declare actor text:=nullif(pg_catalog.current_setting('talli.verified_actor_id',true),''); r record; canonical_text text;
begin
 if actor is null or p_subject is distinct from actor
  or actor !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
 then raise exception 'documents_forbidden'; end if;
 if public.company_access_is_accepted_owner_v1(p_company) is distinct from true then raise exception 'documents_forbidden'; end if;
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'documents_guard_requires_read_committed'; end if;
 if p_original is null or p_document is null or p_company is null or p_source_year is null or p_source_year not between 2000 and 2100
  or p_metadata is null or p_metadata !~ '^[0-9a-f]{64}$' or p_content_sha is null or p_content_sha !~ '^[0-9a-f]{64}$'
  or p_length is null or p_length not between 1 and 10485760 or p_retained_at is null or not pg_catalog.isfinite(p_retained_at)
  or extract(year from p_retained_at at time zone 'UTC') not between 1 and 9999
  or p_not_after is null or not pg_catalog.isfinite(p_not_after)
  or extract(year from p_not_after at time zone 'UTC') not between 1 and 9999
  or p_not_after>pg_catalog.clock_timestamp()
 then raise exception 'documents_invalid_input'; end if;
 perform public.company_archive_lock_company_v1(p_company);
 if public.company_access_is_accepted_owner_v1(p_company) is distinct from true then raise exception 'documents_forbidden'; end if;
 perform pg_catalog.set_config('talli.authorized_company_roles',pg_catalog.jsonb_build_object(p_company::text,'owner')::text,true);
 -- Select metadata only; existing immutable-row constraints bind stored byte
 -- length/SHA. This routine neither reads nor re-verifies object-store bytes.
 select id,document_id,company_id,source_income_year,metadata_sha256,content_sha256,byte_length,retained_at,document_snapshot
 into r from documents.retained_originals
 where id=p_original and document_id=p_document and company_id=p_company and source_income_year=p_source_year
  and metadata_sha256=p_metadata and content_sha256=p_content_sha and byte_length=p_length and retained_at=p_retained_at;
 if not found or p_retained_at>p_not_after then raise exception 'documents_evidence_mismatch'; end if;
 canonical_text:=documents.original_integrity_document_internal_v1(r.document_snapshot);
 if r.document_snapshot->>'id' is distinct from r.document_id::text
  or r.document_snapshot->>'company_id' is distinct from r.company_id::text
  or (r.document_snapshot->>'income_year')::integer is distinct from r.source_income_year
  or r.document_snapshot->>'content_sha256' is distinct from r.content_sha256
  or (r.document_snapshot->>'byte_length')::integer is distinct from r.byte_length
  or pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(canonical_text,'UTF8')),'hex') is distinct from r.metadata_sha256
 then raise exception 'documents_evidence_mismatch'; end if;
 return query select canonical_text;
end; $fn$;

-- Closed additive contract, including reinstallation after fixture-only grants.
do $closed$
declare signature text; grantee_name text;
begin
 for signature in select p.oid::regprocedure::text from pg_catalog.pg_proc p
  join pg_catalog.pg_namespace n on n.oid=p.pronamespace where n.nspname='documents'
   and p.proname in ('original_integrity_require_internal_v1','original_integrity_json_internal_v1',
    'original_integrity_time_internal_v1','original_integrity_document_internal_v1','assert_historical_original_integrity_v1')
 loop
  execute 'revoke all on function '||signature||' from public';
  for grantee_name in select distinct r.rolname from pg_catalog.pg_proc p
   cross join lateral pg_catalog.aclexplode(p.proacl) a join pg_catalog.pg_roles r on r.oid=a.grantee
   where p.oid=signature::regprocedure and a.grantee<>p.proowner
  loop execute pg_catalog.format('revoke all on function %s from %I',signature,grantee_name); end loop;
 end loop;
end; $closed$;
reset role;
do $restore$
declare r record; schema_owner text;
begin
 if (select added from pg_temp.documents_original_integrity_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='documents';
  execute pg_catalog.format('set local role %I',schema_owner);
  revoke create on schema documents from documents_store_owner;
  reset role;
 end if;
 for r in select * from pg_temp.documents_original_integrity_role loop
  execute pg_catalog.format('revoke documents_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant documents_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
   current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
