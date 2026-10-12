-- Closed RF-owned proof of one current stored observation. No writer change,
-- history-completeness assertion, Documents byte proof or consumer activation.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_evidence_reader_role(prior jsonb) on commit drop;
create temporary table rf193_evidence_reader_create(added boolean) on commit drop;
do $borrow$
declare prior jsonb; schema_owner text;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into prior from pg_catalog.pg_auth_members m where m.roleid='shareholder_register_filing_store_owner'::regrole
   and m.member=current_user::regrole and m.grantor=m.member;
  insert into pg_temp.rf193_evidence_reader_role values(prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
 insert into pg_temp.rf193_evidence_reader_create values(not pg_catalog.has_schema_privilege('shareholder_register_filing_store_owner','shareholder_register_filing','CREATE'));
 if (select added from pg_temp.rf193_evidence_reader_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='shareholder_register_filing';
  execute pg_catalog.format('set local role %I',schema_owner);
  grant create on schema shareholder_register_filing to shareholder_register_filing_store_owner;
  reset role;
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;

create or replace function shareholder_register_filing.observation_evidence_require_internal_v1(valid boolean)
returns void language plpgsql immutable security invoker set search_path='' as $fn$
begin
 if valid is distinct from true then raise exception 'rf1086_register_storage_invalid'; end if;
end; $fn$;

-- The existing Python codec emits sorted compact UTF-8 JSON. This helper is
-- deliberately private and accepts only the primitive types in that codec.
create or replace function shareholder_register_filing.observation_evidence_json_internal_v1(value jsonb)
returns text language plpgsql immutable strict security invoker set search_path='' as $fn$
declare result text; kind text:=pg_catalog.jsonb_typeof(value);
begin
 if kind='object' then
  select '{'||coalesce(pg_catalog.string_agg(pg_catalog.to_json(key)::text||':'||
   shareholder_register_filing.observation_evidence_json_internal_v1(item),',' order by key collate "C"),'')||'}'
   into result from pg_catalog.jsonb_each(value) e(key,item);
 elsif kind='array' then
  select '['||coalesce(pg_catalog.string_agg(shareholder_register_filing.observation_evidence_json_internal_v1(item),',' order by ordinal),'')||']'
   into result from pg_catalog.jsonb_array_elements(value) with ordinality e(item,ordinal);
 elsif kind in ('null','boolean','string') then result:=value::text;
 elsif kind='number' and value::text ~ '^-?(0|[1-9][0-9]*)$' then result:=value::text;
 else raise exception 'rf1086_register_storage_invalid'; end if;
 return result;
end; $fn$;

-- Validate Python datetime.isoformat() output, preserving document offsets in
-- the hash. Compute the instant manually: PostgreSQL does not parse fractional
-- offset seconds, which Python's fixed-offset datetime supports.
create or replace function shareholder_register_filing.observation_evidence_time_internal_v1(value text,aware boolean)
returns timestamptz language plpgsql immutable security invoker set search_path='' as $fn$
declare pieces text[]; civil timestamp; offset_text text; offset_seconds numeric:=0; rendered text;
begin
 perform shareholder_register_filing.observation_evidence_require_internal_v1(value is not null);
 pieces:=pg_catalog.regexp_match(value,'^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(\.[0-9]{6})?([+-][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{6})?)?)?$');
 perform shareholder_register_filing.observation_evidence_require_internal_v1(pieces is not null and (pieces[3] is not null)=aware);
 civil:=(pieces[1]||coalesce(pieces[2],''))::timestamp;
 rendered:=pg_catalog.to_char(civil,'YYYY-MM-DD"T"HH24:MI:SS');
 if mod(extract(microseconds from civil),1000000)<>0 then rendered:=rendered||'.'||pg_catalog.to_char(civil,'US'); end if;
 perform shareholder_register_filing.observation_evidence_require_internal_v1(rendered=pieces[1]||coalesce(pieces[2],'')
  and extract(year from civil) between 1 and 9999);
 offset_text:=pieces[3];
 if aware then
  perform shareholder_register_filing.observation_evidence_require_internal_v1(substring(offset_text from 2 for 2)::integer<24
   and substring(offset_text from 5 for 2)::integer<60
   and (pieces[4] is null or substring(pieces[4] from 2)::numeric<60));
  offset_seconds:=substring(offset_text from 2 for 2)::numeric*3600+substring(offset_text from 5 for 2)::numeric*60
   +coalesce(substring(pieces[4] from 2)::numeric,0);
  -- isoformat omits zero offset seconds/fractions and always spells UTC +00:00.
  perform shareholder_register_filing.observation_evidence_require_internal_v1(
   (pieces[4] is null or substring(pieces[4] from 2)::numeric<>0)
   and (pieces[5] is null or pieces[5]<>'.000000')
   and (offset_seconds<>0 or offset_text='+00:00'));
  if left(offset_text,1)='-' then offset_seconds:=-offset_seconds; end if;
 end if;
 return (civil-offset_seconds*interval '1 second') at time zone 'UTC';
exception when datetime_field_overflow or invalid_datetime_format or numeric_value_out_of_range then
 raise exception 'rf1086_register_storage_invalid';
end; $fn$;

-- Expected types come from the containing field, never from untrusted tags.
-- Return precisely the unwrapped dataclass/enum/Decimal values used by the
-- released fact/request digest, not the storage wrapper JSON.
create or replace function shareholder_register_filing.observation_evidence_decode_internal_v1(value jsonb,expected text)
returns jsonb language plpgsql immutable security invoker set search_path='' as $fn$
declare shape jsonb; result jsonb:='{}'::jsonb; key text; field_type text; text_value text;
begin
 if right(expected,1)='?' then
  if value='null'::jsonb then return value; end if;
  return shareholder_register_filing.observation_evidence_decode_internal_v1(value,left(expected,-1));
 end if;
 perform shareholder_register_filing.observation_evidence_require_internal_v1(value is not null and value<>'null'::jsonb);
 if left(expected,5)='list:' then
  perform shareholder_register_filing.observation_evidence_require_internal_v1(pg_catalog.jsonb_typeof(value)='array');
  select coalesce(pg_catalog.jsonb_agg(shareholder_register_filing.observation_evidence_decode_internal_v1(item,substring(expected from 6)) order by ordinal),'[]'::jsonb)
   into result from pg_catalog.jsonb_array_elements(value) with ordinality e(item,ordinal);
  return result;
 elsif expected in ('text','nonblank','uuid','sha','positive_integer','year','boolean') then
  if expected='boolean' then perform shareholder_register_filing.observation_evidence_require_internal_v1(pg_catalog.jsonb_typeof(value)='boolean');
  elsif expected in ('positive_integer','year') then
   -- Match the unchanged Python 3.12 codec's default decimal-integer limit.
   -- Decimal wrapper strings follow their separate amount rules below.
   perform shareholder_register_filing.observation_evidence_require_internal_v1(pg_catalog.jsonb_typeof(value)='number'
    and length(value::text)<=4300 and value::text ~ '^[1-9][0-9]*$');
   if expected='year' then perform shareholder_register_filing.observation_evidence_require_internal_v1(value::text::numeric between 2000 and 2100); end if;
  else
   perform shareholder_register_filing.observation_evidence_require_internal_v1(pg_catalog.jsonb_typeof(value)='string');
   text_value:=value#>>'{}';
   if expected='nonblank' then
    -- Python str.strip whitespace, independent of server locale.
    perform shareholder_register_filing.observation_evidence_require_internal_v1(pg_catalog.btrim(text_value,U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000')<>'');
   elsif expected='uuid' then
    perform shareholder_register_filing.observation_evidence_require_internal_v1(text_value ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$');
   elsif expected='sha' then perform shareholder_register_filing.observation_evidence_require_internal_v1(text_value ~ '^[0-9a-f]{64}$'); end if;
  end if;
  return value;
 elsif expected='decimal' then
  perform shareholder_register_filing.observation_evidence_require_internal_v1(pg_catalog.jsonb_typeof(value)='object' and value-'decimal'='{}'::jsonb and pg_catalog.jsonb_typeof(value->'decimal')='string');
  text_value:=value->>'decimal';
  perform shareholder_register_filing.observation_evidence_require_internal_v1(text_value ~ '^(0|[1-9][0-9]*)(\.[0-9]{1,6})?$' and text_value::numeric>0);
  if position('.' in text_value)>0 then text_value:=pg_catalog.rtrim(pg_catalog.rtrim(text_value,'0'),'.'); end if;
  return pg_catalog.to_jsonb(text_value);
 elsif expected in ('civil','aware') then
  perform shareholder_register_filing.observation_evidence_require_internal_v1(pg_catalog.jsonb_typeof(value)='object' and value-'datetime'='{}'::jsonb and pg_catalog.jsonb_typeof(value->'datetime')='string');
  perform shareholder_register_filing.observation_evidence_time_internal_v1(value->>'datetime',expected='aware');
  if expected='civil' then perform shareholder_register_filing.observation_evidence_require_internal_v1(length(value->>'datetime')=19); end if;
  return value->'datetime';
 elsif expected='ActorKind' then
  perform shareholder_register_filing.observation_evidence_require_internal_v1(pg_catalog.jsonb_typeof(value)='object' and value-array['enum','value']='{}'::jsonb
   and value->>'enum'='ActorKind' and pg_catalog.jsonb_typeof(value->'value')='string' and value->>'value' in ('USER','SYSTEM','SUPPORT_OPERATOR'));
  return value->'value';
 end if;
 shape:=case expected
  when 'Rf1086RegisterObservationSnapshot' then '{"observation_id":"Rf1086RegisterObservationId","version":"positive_integer","command":"RecordRf1086RegisterObservation","confirmed_at":"aware","fact_sha256":"sha"}'::jsonb
  when 'RecordRf1086RegisterObservation' then '{"company_id":"CompanyId","actor_id":"ActorId","income_year":"IncomeYear","effective_at":"civil","event_kind":"text","before":"Rf1086RegisteredShareState","after":"Rf1086RegisteredShareState","documents":"list:Rf1086RegisterDocumentEvidence","complete_register_confirmed":"boolean","registration_confirmed":"boolean","single_share_class_confirmed":"boolean","supersedes_observation_id":"Rf1086RegisterObservationId?","supersedes_observation_sha256":"sha?","correction_reason":"nonblank?"}'::jsonb
  when 'Rf1086RegisteredShareState' then '{"share_capital":"decimal","share_count":"positive_integer","nominal_value":"decimal","holdings":"list:Rf1086RegisterHolding"}'::jsonb
  when 'Rf1086RegisterHolding' then '{"shareholder_id":"nonblank","name":"nonblank","kind":"text","identifier":"text","share_count":"positive_integer"}'::jsonb
  when 'Rf1086RegisterDocumentEvidence' then '{"document_id":"uuid","company_id":"CompanyId","content_version_sha256":"sha","content_sha256":"sha","byte_length":"positive_integer","document_type":"nonblank","integrity_status":"text","created_at":"aware","metadata_sha256":"sha","role":"text","source_income_year":"IncomeYear?"}'::jsonb
  when 'ActorId' then '{"kind":"ActorKind","subject":"UserId"}'::jsonb
  when 'CompanyId' then '{"value":"uuid"}'::jsonb
  when 'UserId' then '{"value":"uuid"}'::jsonb
  when 'IncomeYear' then '{"value":"year"}'::jsonb
  when 'Rf1086RegisterObservationId' then '{"value":"uuid"}'::jsonb
  else null end;
 perform shareholder_register_filing.observation_evidence_require_internal_v1(shape is not null and pg_catalog.jsonb_typeof(value)='object'
  and value-array['record','fields']='{}'::jsonb and value->>'record'=expected and pg_catalog.jsonb_typeof(value->'fields')='object');
 perform shareholder_register_filing.observation_evidence_require_internal_v1(
  (select array_agg(k order by k collate "C") from pg_catalog.jsonb_object_keys(value->'fields') k)
   =(select array_agg(k order by k collate "C") from pg_catalog.jsonb_object_keys(shape) k));
 for key,field_type in select * from pg_catalog.jsonb_each_text(shape) loop
  result:=result||pg_catalog.jsonb_build_object(key,shareholder_register_filing.observation_evidence_decode_internal_v1(value->'fields'->key,field_type));
 end loop;
 return result;
end; $fn$;

create or replace function shareholder_register_filing.observation_evidence_state_internal_v1(value jsonb)
returns void language plpgsql immutable security invoker set search_path='' as $fn$
declare holder jsonb; ordered jsonb;
begin
 perform shareholder_register_filing.observation_evidence_require_internal_v1((value->>'share_capital')::numeric>=30000
  and (value->>'share_capital')::numeric=(value->>'nominal_value')::numeric*(value->>'share_count')::numeric
  and pg_catalog.jsonb_array_length(value->'holdings')>0);
 for holder in select * from pg_catalog.jsonb_array_elements(value->'holdings') loop
  perform shareholder_register_filing.observation_evidence_require_internal_v1(
   (holder->>'kind'='norwegian_person' and holder->>'identifier' ~ '^[0-9]{11}$')
   or (holder->>'kind'='norwegian_company' and holder->>'identifier' ~ '^[0-9]{9}$'));
 end loop;
 perform shareholder_register_filing.observation_evidence_require_internal_v1(
  (select sum((h->>'share_count')::numeric) from pg_catalog.jsonb_array_elements(value->'holdings') h)=(value->>'share_count')::numeric
  and not exists(select 1 from pg_catalog.jsonb_array_elements(value->'holdings') h group by h->>'shareholder_id' having count(*)>1)
  and not exists(select 1 from pg_catalog.jsonb_array_elements(value->'holdings') h group by h->>'kind',h->>'identifier' having count(*)>1));
 select pg_catalog.jsonb_agg(h order by (h->>'shareholder_id') collate "C") into ordered from pg_catalog.jsonb_array_elements(value->'holdings') h;
 perform shareholder_register_filing.observation_evidence_require_internal_v1(ordered=value->'holdings');
end; $fn$;

create or replace function shareholder_register_filing.observation_evidence_validate_internal_v1(encoded text)
returns jsonb language plpgsql immutable security invoker set search_path='' as $fn$
declare payload jsonb; snapshot jsonb; command jsonb; before_state jsonb; after_state jsonb; doc jsonb; ordered jsonb;
 captured timestamptz; utc_text text; fact text; request text;
begin
 perform shareholder_register_filing.observation_evidence_require_internal_v1(encoded is json object with unique keys);
 payload:=encoded::jsonb;
 perform shareholder_register_filing.observation_evidence_require_internal_v1(payload-array['codec','snapshot']='{}'::jsonb
  and payload->>'codec'='rf1086-register-observation-v1'
  and shareholder_register_filing.observation_evidence_json_internal_v1(payload)=encoded);
 snapshot:=shareholder_register_filing.observation_evidence_decode_internal_v1(payload->'snapshot','Rf1086RegisterObservationSnapshot');
 command:=snapshot->'command'; before_state:=command->'before'; after_state:=command->'after';
 perform shareholder_register_filing.observation_evidence_require_internal_v1(command->'complete_register_confirmed'='true'::jsonb
  and command->'registration_confirmed'='true'::jsonb and command->'single_share_class_confirmed'='true'::jsonb
  and substring(command->>'effective_at' from 1 for 4)::integer=(command#>>'{income_year,value}')::integer);
 perform shareholder_register_filing.observation_evidence_state_internal_v1(before_state);
 perform shareholder_register_filing.observation_evidence_state_internal_v1(after_state);
 perform shareholder_register_filing.observation_evidence_require_internal_v1(not exists(
  select 1 from pg_catalog.jsonb_array_elements(before_state->'holdings') old
  join pg_catalog.jsonb_array_elements(after_state->'holdings') new on old->>'shareholder_id'=new->>'shareholder_id'
  where old-'share_count' is distinct from new-'share_count'));
 if command->>'event_kind'='cash_issue' then
  perform shareholder_register_filing.observation_evidence_require_internal_v1((after_state->>'share_count')::numeric>(before_state->>'share_count')::numeric
   and (after_state->>'nominal_value')::numeric=(before_state->>'nominal_value')::numeric
   and not exists(select 1 from pg_catalog.jsonb_array_elements(before_state->'holdings') old
    where not exists(select 1 from pg_catalog.jsonb_array_elements(after_state->'holdings') new
     where new->>'shareholder_id'=old->>'shareholder_id' and (new->>'share_count')::numeric>=(old->>'share_count')::numeric)));
 elsif command->>'event_kind' in ('cash_nominal_increase','loss_covering_reduction') then
  perform shareholder_register_filing.observation_evidence_require_internal_v1(before_state->'share_count'=after_state->'share_count'
   and before_state->'holdings'=after_state->'holdings'
   and (case when command->>'event_kind'='cash_nominal_increase' then (after_state->>'nominal_value')::numeric>(before_state->>'nominal_value')::numeric
        else (after_state->>'nominal_value')::numeric<(before_state->>'nominal_value')::numeric end));
 else raise exception 'rf1086_register_storage_invalid'; end if;
 captured:=shareholder_register_filing.observation_evidence_time_internal_v1(snapshot->>'confirmed_at',true);
 perform shareholder_register_filing.observation_evidence_require_internal_v1(extract(year from captured at time zone 'UTC') between 1 and 9999);
 perform shareholder_register_filing.observation_evidence_require_internal_v1(substring(snapshot->>'confirmed_at' from 1 for 10)::date
  >=substring(command->>'effective_at' from 1 for 10)::date);
 for doc in select * from pg_catalog.jsonb_array_elements(command->'documents') loop
  perform shareholder_register_filing.observation_evidence_require_internal_v1(doc->'company_id'=command->'company_id'
   and doc->'content_version_sha256'=doc->'content_sha256' and doc->>'integrity_status' in ('attached','generated_unsigned','signed_owner_attested','stored')
   and doc->>'role' in ('register_before','register_after','registration')
   and shareholder_register_filing.observation_evidence_time_internal_v1(doc->>'created_at',true)<=captured);
 end loop;
 perform shareholder_register_filing.observation_evidence_require_internal_v1(
  (select array_agg(distinct d->>'role' order by d->>'role') from pg_catalog.jsonb_array_elements(command->'documents') d)
   =array['register_after','register_before','registration']
  and not exists(select 1 from pg_catalog.jsonb_array_elements(command->'documents') d group by d->>'document_id',d->>'role' having count(*)>1)
  and not exists(select 1 from pg_catalog.jsonb_array_elements(command->'documents') a join pg_catalog.jsonb_array_elements(command->'documents') b
   on a->>'document_id'=b->>'document_id' where (a-array['role','created_at']) is distinct from (b-array['role','created_at'])
    or shareholder_register_filing.observation_evidence_time_internal_v1(a->>'created_at',true)
       is distinct from shareholder_register_filing.observation_evidence_time_internal_v1(b->>'created_at',true)));
 select pg_catalog.jsonb_agg(d order by (d->>'document_id') collate "C",(d->>'role') collate "C") into ordered from pg_catalog.jsonb_array_elements(command->'documents') d;
 perform shareholder_register_filing.observation_evidence_require_internal_v1(ordered=command->'documents'
  and ((snapshot->>'version')::numeric=1)=(command->'supersedes_observation_id'='null'::jsonb)
  and command->'supersedes_observation_id' is distinct from snapshot->'observation_id'
  and (case when command->'supersedes_observation_id'='null'::jsonb then command->'supersedes_observation_sha256'='null'::jsonb and command->'correction_reason'='null'::jsonb
       else command->'supersedes_observation_sha256'<>'null'::jsonb and command->'correction_reason'<>'null'::jsonb end));
 utc_text:=pg_catalog.to_char(captured at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS');
 if mod(extract(microseconds from captured at time zone 'UTC'),1000000)<>0 then utc_text:=utc_text||'.'||pg_catalog.to_char(captured at time zone 'UTC','US'); end if;
 utc_text:=utc_text||'+00:00';
 fact:=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(shareholder_register_filing.observation_evidence_json_internal_v1(
  pg_catalog.jsonb_build_array('rf1086-register-observation-v1',snapshot->'observation_id',snapshot->'version',command,utc_text)),'UTF8')),'hex');
 request:=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(shareholder_register_filing.observation_evidence_json_internal_v1(
  pg_catalog.jsonb_build_array('rf1086-register-observation-request-v1',command)),'UTF8')),'hex');
 perform shareholder_register_filing.observation_evidence_require_internal_v1(fact=snapshot->>'fact_sha256');
 return pg_catalog.jsonb_build_object('snapshot',snapshot,'request_sha256',request);
exception when invalid_text_representation or numeric_value_out_of_range or program_limit_exceeded then
 raise exception 'rf1086_register_storage_invalid';
end; $fn$;

create or replace function shareholder_register_filing.read_current_register_observation_evidence_v1(
 p_id uuid,p_company uuid,p_year integer,p_revision integer,p_sha text,p_not_after timestamptz,p_subject text
) returns table(snapshot_text text,confirmed_at timestamptz)
language plpgsql volatile security definer set search_path='' as $fn$
declare retained shareholder_register_filing.register_observations%rowtype; proof jsonb; snapshot jsonb; command jsonb;
begin
 perform shareholder_register_filing.assert_current_register_observation_v2(p_id,p_company,p_year,p_revision,p_sha,p_not_after,p_subject);
 select * into retained from shareholder_register_filing.register_observations where id=p_id and company_id=p_company and income_year=p_year;
 perform shareholder_register_filing.observation_evidence_require_internal_v1(found);
 proof:=shareholder_register_filing.observation_evidence_validate_internal_v1(retained.snapshot_text);
 snapshot:=proof->'snapshot'; command:=snapshot->'command';
 perform shareholder_register_filing.observation_evidence_require_internal_v1(
  snapshot#>>'{observation_id,value}'=retained.id::text and command#>>'{company_id,value}'=retained.company_id::text
  and command#>>'{income_year,value}'=retained.income_year::text and snapshot->>'version'=retained.version::text
  and command#>>'{actor_id,subject,value}'=retained.actor_id::text and snapshot->>'fact_sha256'=retained.fact_sha256
  and shareholder_register_filing.observation_evidence_time_internal_v1(snapshot->>'confirmed_at',true)=retained.confirmed_at
  and (command#>>'{supersedes_observation_id,value}') is not distinct from retained.predecessor_id::text
  and (command->>'supersedes_observation_sha256') is not distinct from retained.predecessor_sha256
  and (command->>'correction_reason') is not distinct from retained.correction_reason
  and proof->>'request_sha256'=retained.request_sha256);
 return query select retained.snapshot_text,retained.confirmed_at;
end; $fn$;

-- None of these helpers or the public reader is executable by a consumer yet.
-- Reinstallation removes accidental test grants, not just named runtime roles.
do $closed$
declare routine regprocedure; grantee_name text;
begin
 for routine in select p.oid::regprocedure from pg_catalog.pg_proc p
  where p.pronamespace='shareholder_register_filing'::regnamespace and p.proname in (
   'observation_evidence_require_internal_v1','observation_evidence_json_internal_v1','observation_evidence_time_internal_v1',
   'observation_evidence_decode_internal_v1','observation_evidence_state_internal_v1','observation_evidence_validate_internal_v1',
   'read_current_register_observation_evidence_v1') loop
  execute pg_catalog.format('revoke all on function %s from public',routine);
  for grantee_name in select distinct r.rolname from pg_catalog.pg_proc p cross join lateral pg_catalog.aclexplode(p.proacl) a
   join pg_catalog.pg_roles r on r.oid=a.grantee where p.oid=routine and a.grantee<>p.proowner loop
   execute pg_catalog.format('revoke all on function %s from %I',routine,grantee_name);
  end loop;
 end loop;
end; $closed$;
reset role;
do $restore$
declare r record; schema_owner text;
begin
 if (select added from pg_temp.rf193_evidence_reader_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='shareholder_register_filing';
  execute pg_catalog.format('set local role %I',schema_owner);
  revoke create on schema shareholder_register_filing from shareholder_register_filing_store_owner;
  reset role;
 end if;
 for r in select * from pg_temp.rf193_evidence_reader_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
   current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
