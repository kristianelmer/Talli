-- Closed RF v2 persistence foundation. No runtime writer or consumer activation.
-- An RF-owned ephemeral proof authenticates chains supplied only by Governance.
-- No reverse Governance query/import is introduced. Original reporting-year
-- selection/status/hash and complete business validation remain a later guarded
-- Python producer prerequisite; opaque owner labels are not new SQL attestations.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_source_v2_roles(role_name text,prior jsonb) on commit drop;
create temporary table rf193_source_v2_create(added boolean) on commit drop;
do $borrow$
declare name text; prior jsonb; schema_owner text;
begin
 select pg_catalog.pg_get_userbyid(nspowner) into strict schema_owner from pg_catalog.pg_namespace where nspname='shareholder_register_filing';
 for name in select distinct value from unnest(array['shareholder_register_filing_store_owner',schema_owner]) value loop
  if not pg_catalog.pg_has_role(current_user,name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into prior
    from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(name) and m.member=current_user::regrole and m.grantor=m.member;
   insert into pg_temp.rf193_source_v2_roles values(name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',name,current_user,current_user);
  end if;
 end loop;
 insert into pg_temp.rf193_source_v2_create select not pg_catalog.has_schema_privilege('shareholder_register_filing_store_owner','shareholder_register_filing','CREATE');
 if (select added from pg_temp.rf193_source_v2_create) then
  execute pg_catalog.format('set local role %I',schema_owner);
  grant create on schema shareholder_register_filing to shareholder_register_filing_store_owner;
  reset role;
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;

create or replace function shareholder_register_filing.year_source_v2_require_internal_v1(valid boolean)
returns void language plpgsql immutable security invoker set search_path='' as $fn$
begin
 if valid is distinct from true then raise exception 'rf1086_source_storage_invalid'; end if;
end; $fn$;

-- Frozen source canonical semantics: decimal JSON numbers, unlike the RF
-- observation digest's decimal strings. Never use jsonb::text for a commitment.
create or replace function shareholder_register_filing.year_source_v2_json_internal_v1(value jsonb)
returns text language plpgsql immutable strict security invoker set search_path='' as $fn$
declare result text; kind text:=pg_catalog.jsonb_typeof(value);
begin
 if kind='object' then
  select '{'||coalesce(pg_catalog.string_agg(pg_catalog.to_json(key)::text||':'||shareholder_register_filing.year_source_v2_json_internal_v1(item),',' order by key collate "C"),'')||'}'
   into result from pg_catalog.jsonb_each(value) e(key,item);
 elsif kind='array' then
  select '['||coalesce(pg_catalog.string_agg(shareholder_register_filing.year_source_v2_json_internal_v1(item),',' order by ordinal),'')||']'
   into result from pg_catalog.jsonb_array_elements(value) with ordinality e(item,ordinal);
 elsif kind='number' then
  perform shareholder_register_filing.year_source_v2_require_internal_v1(value::text::numeric>=0);
  result:=value::text;
  if value::text::numeric=0 then result:='0';
  elsif position('.' in result)>0 then result:=pg_catalog.rtrim(pg_catalog.rtrim(result,'0'),'.'); end if;
 elsif kind in ('null','boolean','string') then result:=value::text;
 else raise exception 'rf1086_source_storage_invalid'; end if;
 return result;
end; $fn$;
create or replace function shareholder_register_filing.year_source_v2_sha_internal_v1(value jsonb)
returns text language sql immutable strict security invoker set search_path='' as $fn$
 select pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(shareholder_register_filing.year_source_v2_json_internal_v1(value),'UTF8')),'hex');
$fn$;

create or replace function shareholder_register_filing.year_source_v2_shape_internal_v1(expected text)
returns jsonb language plpgsql immutable security invoker set search_path='' as $fn$
declare shape jsonb;
begin
 case expected
 when 'ActorId' then shape:='{"kind":"enum:ActorKind:[\"USER\",\"SYSTEM\",\"SUPPORT_OPERATOR\"]","subject":"UserId"}'::jsonb;
 when 'CompanyId' then shape:='{"value":"uuid"}'::jsonb;
 when 'IncomeYear' then shape:='{"value":"year"}'::jsonb;
 when 'UserId' then shape:='{"value":"uuid"}'::jsonb;
 when 'Rf1086YearSourceId' then shape:='{"value":"uuid"}'::jsonb;
 when 'Rf1086RegisterObservationId' then shape:='{"value":"uuid"}'::jsonb;
 when 'Rf1086RegisterHolding' then shape:='{"shareholder_id":"text","name":"text","kind":"holding_kind","identifier":"text","share_count":"integer"}'::jsonb;
 when 'Rf1086RegisteredShareState' then shape:='{"share_capital":"amount","share_count":"integer","nominal_value":"amount","holdings":"list:Rf1086RegisterHolding"}'::jsonb;
 when 'Rf1086RegisterDocumentEvidence' then shape:='{"document_id":"uuid","company_id":"CompanyId","content_version_sha256":"sha","content_sha256":"sha","byte_length":"positive","document_type":"text","integrity_status":"text","created_at":"aware","metadata_sha256":"sha","role":"literal:[\"register_before\",\"register_after\",\"registration\"]","source_income_year":"IncomeYear?"}'::jsonb;
 when 'RecordRf1086RegisterObservation' then shape:='{"company_id":"CompanyId","actor_id":"ActorId","income_year":"IncomeYear","effective_at":"civil","event_kind":"literal:[\"cash_issue\",\"cash_nominal_increase\",\"loss_covering_reduction\"]","before":"Rf1086RegisteredShareState","after":"Rf1086RegisteredShareState","documents":"list:Rf1086RegisterDocumentEvidence","complete_register_confirmed":"boolean","registration_confirmed":"boolean","single_share_class_confirmed":"boolean","supersedes_observation_id":"Rf1086RegisterObservationId?","supersedes_observation_sha256":"sha?","correction_reason":"text?"}'::jsonb;
 when 'Rf1086RegisterObservationSnapshot' then shape:='{"observation_id":"Rf1086RegisterObservationId","version":"positive","command":"RecordRf1086RegisterObservation","confirmed_at":"aware","fact_sha256":"sha"}'::jsonb;
 when 'Rf1086Company' then shape:='{"org_number":"text","name":"text","address":"text","postal_code":"text","city":"text","income_year":"year","share_type":"text","contact_email":"text?"}'::jsonb;
 when 'Rf1086ShareSnapshot' then shape:='{"previous_share_capital":"amount","current_share_capital":"amount","previous_nominal_value":"amount","current_nominal_value":"amount","previous_share_count":"integer","current_share_count":"integer","previous_paid_in_share_capital":"amount","current_paid_in_share_capital":"amount","previous_paid_in_premium":"amount","current_paid_in_premium":"amount"}'::jsonb;
 when 'Rf1086Shareholder' then shape:='{"id":"text","kind":"enum:Rf1086ShareholderKind:[\"norwegian_person\",\"norwegian_company\"]","name":"text","national_id":"text?","org_number":"text?"}'::jsonb;
 when 'Rf1086ShareholderSnapshot' then shape:='{"shareholder_id":"text","previous_share_count":"integer","current_share_count":"integer"}'::jsonb;
 when 'Rf1086FormationAllocation' then shape:='{"shareholder_id":"text","share_count":"integer","acquisition_value":"amount"}'::jsonb;
 when 'Rf1086FormationEvent' then shape:='{"timestamp":"civil","issued_share_count":"integer","share_count_after":"integer","nominal_value":"amount","allocations":"list:Rf1086FormationAllocation","premium":"amount","type":"literal:[\"formation\"]"}'::jsonb;
 when 'Rf1086CashIssueEvent' then shape:='{"timestamp":"civil","issued_share_count":"integer","share_count_after":"integer","nominal_value":"amount","allocations":"list:Rf1086FormationAllocation","registration_confirmed":"literal:[true]","premium":"amount","type":"literal:[\"cash_issue\"]"}'::jsonb;
 when 'Rf1086NominalIncreaseAllocation' then shape:='{"shareholder_id":"text","share_count_basis":"integer","capital_increase":"amount","premium":"amount"}'::jsonb;
 when 'Rf1086CashNominalIncreaseEvent' then shape:='{"timestamp":"civil","capital_increase":"amount","nominal_value_increase":"amount","nominal_value_after":"amount","allocations":"list:Rf1086NominalIncreaseAllocation","registration_confirmed":"literal:[true]","premium":"amount","type":"literal:[\"cash_nominal_increase\"]"}'::jsonb;
 when 'Rf1086LossCoveringReductionEvent' then shape:='{"timestamp":"civil","capital_reduction":"amount","nominal_value_reduction":"amount","nominal_value_after":"amount","registration_confirmed":"literal:[true]","fund_issued_capital_before":"literal:[0]","type":"literal:[\"loss_covering_reduction\"]"}'::jsonb;
 when 'Rf1086ShareSaleEvent' then shape:='{"timestamp":"civil","seller_shareholder_id":"text","buyer_shareholder_id":"text","share_count":"integer","consideration":"amount","type":"literal:[\"share_sale\"]"}'::jsonb;
 when 'Rf1086DividendAllocation' then shape:='{"shareholder_id":"text","amount":"amount","share_count_basis":"integer"}'::jsonb;
 when 'Rf1086DividendEvent' then shape:='{"timestamp":"civil","total_amount":"amount","per_share_amount":"amount","allocations":"list:Rf1086DividendAllocation","type":"literal:[\"dividend\"]"}'::jsonb;
 when 'Rf1086Case' then shape:='{"case_id":"text","company":"Rf1086Company","share_snapshot":"Rf1086ShareSnapshot","shareholders":"list:Rf1086Shareholder","shareholder_snapshots":"list:Rf1086ShareholderSnapshot","events":"list:event"}'::jsonb;
 when 'Rf1086PaidInSourceFacts' then shape:='{"opening_capital":"amount","closing_capital":"amount","opening_premium":"amount","closing_premium":"amount"}'::jsonb;
 when 'Rf1086YearDocumentEvidence' then shape:='{"document_id":"uuid","company_id":"CompanyId","content_version_sha256":"sha","content_sha256":"sha","document_type":"text","integrity_status":"text","byte_length":"positive","created_at":"aware","metadata_sha256":"sha","source_income_year":"IncomeYear?"}'::jsonb;
 when 'Rf1086YearEventEvidence' then shape:='{"event_index":"integer","event_sha256":"sha","document_ids":"list:uuid","governance_receipt_id":"uuid?"}'::jsonb;
 when 'Rf1086YearGovernanceReceipt' then shape:='{"receipt_id":"uuid","company_id":"CompanyId","income_year":"IncomeYear","event_type":"text","economic_sha256":"sha","finalization_sha256":"sha","signed_document_hashes":"list:sha","active":"boolean","register_observation_id":"uuid?","register_observation_sha256":"sha?"}'::jsonb;
 when 'RecordRf1086YearSource' then shape:='{"company_id":"CompanyId","actor_id":"ActorId","income_year":"IncomeYear","case":"Rf1086Case","paid_in":"Rf1086PaidInSourceFacts","documents":"list:Rf1086YearDocumentEvidence","opening_document_ids":"list:uuid","closing_document_ids":"list:uuid","paid_in_document_ids":"list:uuid","event_evidence":"list:Rf1086YearEventEvidence","identities_reviewed":"boolean","complete_year_confirmed":"boolean","paid_in_reviewed":"boolean","no_activity_confirmed":"boolean","supersedes_source_id":"Rf1086YearSourceId?","supersedes_source_sha256":"sha?","correction_reason":"text?"}'::jsonb;
 when 'Rf1086YearRegisterFactV2' then shape:='{"observation_id":"Rf1086RegisterObservationId","version":"positive","fact_sha256":"sha"}'::jsonb;
 when 'Rf1086YearGovernanceHeadV2' then shape:='{"amendment_id":"uuid","revision":"positive","amendment_sha256":"sha"}'::jsonb;
 when 'Rf1086YearGovernanceLinkV2' then shape:='{"head":"Rf1086YearGovernanceHeadV2","previous_head":"Rf1086YearGovernanceHeadV2?","withdrawal_id":"uuid","withdrawal_sha256":"sha","target":"Rf1086YearRegisterFactV2","replacement":"Rf1086YearRegisterFactV2","recorded_at":"utc"}'::jsonb;
 when 'Rf1086YearGovernanceChainV2' then shape:='{"receipt_id":"uuid","company_id":"CompanyId","income_year":"IncomeYear","event_type":"text","original_finalization_sha256":"sha","original_anchor_sha256":"sha","original_recorded_at":"utc","original_register_fact":"Rf1086YearRegisterFactV2","amendments":"list:Rf1086YearGovernanceLinkV2","amendment_count":"integer","enumeration_sha256":"sha","head":"Rf1086YearGovernanceHeadV2?","effective_register_fact":"Rf1086YearRegisterFactV2","evidence_cutoff":"utc"}'::jsonb;
 when 'Rf1086YearGovernanceProjectionV2' then shape:='{"company_id":"CompanyId","income_year":"IncomeYear","original_enumeration_sha256":"sha","chain_enumeration_sha256":"sha","enumeration_sha256":"sha","chains":"list:Rf1086YearGovernanceChainV2","chain_count":"integer"}'::jsonb;
 when 'Rf1086YearGovernanceReceiptV2' then shape:='{"original":"Rf1086YearGovernanceReceipt","register_observation":"Rf1086RegisterObservationSnapshot?"}'::jsonb;
 when 'Rf1086YearSourceFreshnessV2' then shape:='{"source_id":"Rf1086YearSourceId","source_sha256":"sha","company_identity_sha256":"sha","documents_sha256":"sha","governance_receipts_sha256":"sha","governance_original_enumeration_sha256":"sha","governance_chain_enumeration_sha256":"sha","governance_projection_sha256":"sha"}'::jsonb;
 when 'Rf1086YearSourceSnapshotV2' then shape:='{"source_id":"Rf1086YearSourceId","version":"positive","company_id":"CompanyId","income_year":"IncomeYear","command":"RecordRf1086YearSource","confirmed_by":"ActorId","confirmed_at":"utc","governance_receipts":"list:Rf1086YearGovernanceReceiptV2","governance_projection":"Rf1086YearGovernanceProjectionV2","source_sha256":"sha","case_sha256":"sha","freshness":"Rf1086YearSourceFreshnessV2"}'::jsonb;
 else raise exception 'rf1086_source_storage_invalid'; end case;
 return shape;
end; $fn$;

-- Expected record/primitive types belong to the containing field. This closed
-- registry does not extend the frozen v1 parser or its accepted nested records.
create or replace function shareholder_register_filing.year_source_v2_decode_internal_v1(value jsonb,expected text)
returns jsonb language plpgsql immutable security invoker set search_path='' as $fn$
declare shape jsonb; result jsonb:='{}'::jsonb; key text; field_type text; token text; allowed jsonb;
begin
 if right(expected,1)='?' then
  if value='null'::jsonb then return value; end if;
  return shareholder_register_filing.year_source_v2_decode_internal_v1(value,left(expected,-1));
 end if;
 perform shareholder_register_filing.year_source_v2_require_internal_v1(value is not null and value<>'null'::jsonb);
 if left(expected,5)='list:' then
  perform shareholder_register_filing.year_source_v2_require_internal_v1(pg_catalog.jsonb_typeof(value)='array');
  select coalesce(pg_catalog.jsonb_agg(shareholder_register_filing.year_source_v2_decode_internal_v1(item,substring(expected from 6)) order by ordinal),'[]'::jsonb)
   into result from pg_catalog.jsonb_array_elements(value) with ordinality e(item,ordinal);
  return result;
 elsif left(expected,8)='literal:' then
  allowed:=substring(expected from 9)::jsonb;
  perform shareholder_register_filing.year_source_v2_require_internal_v1(exists(select 1 from pg_catalog.jsonb_array_elements(allowed) a(allowed_value) where allowed_value=value));
  return value;
 elsif left(expected,5)='enum:' then
  token:=split_part(expected,':',2); allowed:=substring(expected from length(token)+7)::jsonb;
  perform shareholder_register_filing.year_source_v2_require_internal_v1(pg_catalog.jsonb_typeof(value)='object' and value-array['enum','value']='{}'::jsonb
   and value->>'enum'=token and exists(select 1 from pg_catalog.jsonb_array_elements(allowed) a(allowed_value) where allowed_value=value->'value'));
  return value->'value';
 elsif expected in ('text','uuid','sha','integer','positive','year','boolean','amount') then
  if expected='amount' and pg_catalog.jsonb_typeof(value)='object' then
   perform shareholder_register_filing.year_source_v2_require_internal_v1(value-'decimal'='{}'::jsonb and pg_catalog.jsonb_typeof(value->'decimal')='string');
   token:=value->>'decimal';
   perform shareholder_register_filing.year_source_v2_require_internal_v1(token ~ '^-?(0|[1-9][0-9]*)(\.[0-9]+)?$' and token::numeric>=0);
   return pg_catalog.to_jsonb(token::numeric);
  elsif expected='boolean' then perform shareholder_register_filing.year_source_v2_require_internal_v1(pg_catalog.jsonb_typeof(value)='boolean');
  elsif expected in ('integer','positive','year','amount') then
   perform shareholder_register_filing.year_source_v2_require_internal_v1(pg_catalog.jsonb_typeof(value)='number' and length(value::text)<=4300 and value::text ~ '^(0|[1-9][0-9]*)$');
   if expected='positive' then perform shareholder_register_filing.year_source_v2_require_internal_v1(value::text::numeric>0);
   elsif expected='year' then perform shareholder_register_filing.year_source_v2_require_internal_v1(value::text::numeric between 2000 and 2100); end if;
  else
   perform shareholder_register_filing.year_source_v2_require_internal_v1(pg_catalog.jsonb_typeof(value)='string'); token:=value#>>'{}';
   if expected='uuid' then perform shareholder_register_filing.year_source_v2_require_internal_v1(token ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$');
   elsif expected='sha' then perform shareholder_register_filing.year_source_v2_require_internal_v1(token ~ '^[0-9a-f]{64}$'); end if;
  end if;
  return value;
 elsif expected='holding_kind' then
  if pg_catalog.jsonb_typeof(value)='string' then
   perform shareholder_register_filing.year_source_v2_require_internal_v1(value#>>'{}' in ('norwegian_person','norwegian_company')); return value;
  end if;
  return shareholder_register_filing.year_source_v2_decode_internal_v1(value,'enum:Rf1086ShareholderKind:["norwegian_person","norwegian_company"]');
 elsif expected in ('civil','aware','utc') then
  perform shareholder_register_filing.year_source_v2_require_internal_v1(pg_catalog.jsonb_typeof(value)='object' and value-'datetime'='{}'::jsonb and pg_catalog.jsonb_typeof(value->'datetime')='string');
  perform shareholder_register_filing.observation_evidence_time_internal_v1(value->>'datetime',expected<>'civil');
  if expected='utc' then perform shareholder_register_filing.year_source_v2_require_internal_v1(right(value->>'datetime',6)='+00:00'); end if;
  return value->'datetime';
 elsif expected='event' then
  perform shareholder_register_filing.year_source_v2_require_internal_v1(value->>'record' in ('Rf1086FormationEvent','Rf1086ShareSaleEvent','Rf1086DividendEvent','Rf1086CashIssueEvent','Rf1086LossCoveringReductionEvent'));
  return shareholder_register_filing.year_source_v2_decode_internal_v1(value,value->>'record');
 end if;
 shape:=shareholder_register_filing.year_source_v2_shape_internal_v1(expected);
 perform shareholder_register_filing.year_source_v2_require_internal_v1(pg_catalog.jsonb_typeof(value)='object' and value-array['record','fields']='{}'::jsonb
  and value->>'record'=expected and pg_catalog.jsonb_typeof(value->'fields')='object'
  and (select pg_catalog.array_agg(k order by k) from pg_catalog.jsonb_object_keys(value->'fields') k)
    =(select pg_catalog.array_agg(k order by k) from pg_catalog.jsonb_object_keys(shape) k));
 for key,field_type in select * from pg_catalog.jsonb_each_text(shape) loop
  result:=result||pg_catalog.jsonb_build_object(key,shareholder_register_filing.year_source_v2_decode_internal_v1(value#>array['fields',key],field_type));
 end loop;
 return result;
exception when data_exception then raise exception 'rf1086_source_storage_invalid';
end; $fn$;

create or replace function shareholder_register_filing.year_source_v2_validate_internal_v1(encoded text)
returns jsonb language plpgsql immutable security invoker set search_path='' as $fn$
declare raw jsonb; s jsonb; c jsonb; projection jsonb; fresh jsonb; calculated text; ordered jsonb;
 chain jsonb; link jsonb; effective jsonb; head jsonb; last_at timestamptz; capture_at timestamptz;
 seen text[]; heads text[]; withdrawals text[]; ids text[]:='{}'; descriptors jsonb:='[]'::jsonb; ordinal integer;
 document jsonb; receipt jsonb; item jsonb; event jsonb; indexes integer[]:='{}'; receipt_ids text[]:='{}'; selected_ids text[]:='{}';
 event_index integer; reason text;
begin
 perform shareholder_register_filing.year_source_v2_require_internal_v1(encoded is not null and encoded is json object with unique keys);
 raw:=encoded::jsonb;
 -- Raw integer lexemes must match the unchanged Python emitter: JSONB alone
 -- would erase malformed exponent/fractional-zero integers before validation.
 perform shareholder_register_filing.year_source_v2_require_internal_v1(
  encoded=shareholder_register_filing.observation_evidence_json_internal_v1(raw)
  and raw-array['codec','snapshot']='{}'::jsonb and raw->>'codec'='rf1086-year-source-v2');
 s:=shareholder_register_filing.year_source_v2_decode_internal_v1(raw->'snapshot','Rf1086YearSourceSnapshotV2');
 c:=s->'command'; projection:=s->'governance_projection'; fresh:=s->'freshness';
 capture_at:=shareholder_register_filing.observation_evidence_time_internal_v1(s->>'confirmed_at',true);
 perform shareholder_register_filing.year_source_v2_require_internal_v1(s->'company_id'=c->'company_id' and s->'income_year'=c->'income_year'
  and s->'confirmed_by'=c->'actor_id' and c#>'{case,company,income_year}'=s#>'{income_year,value}'
  and c->'identities_reviewed'='true'::jsonb and c->'complete_year_confirmed'='true'::jsonb and c->'paid_in_reviewed'='true'::jsonb
  and c->'no_activity_confirmed'=pg_catalog.to_jsonb(pg_catalog.jsonb_array_length(c#>'{case,events}')=0)
  and projection->'company_id'=s->'company_id' and projection->'income_year'=s->'income_year'
  and projection->'chain_count'=pg_catalog.to_jsonb(pg_catalog.jsonb_array_length(projection->'chains')));
 if s->'version'='1'::jsonb then
  perform shareholder_register_filing.year_source_v2_require_internal_v1(c->'supersedes_source_id'='null'::jsonb
   and c->'supersedes_source_sha256'='null'::jsonb and c->'correction_reason'='null'::jsonb);
 else
  perform shareholder_register_filing.year_source_v2_require_internal_v1(c->'supersedes_source_id'<>'null'::jsonb and c->'supersedes_source_id'<>s->'source_id'
   and c->'supersedes_source_sha256'<>'null'::jsonb and nullif(pg_catalog.btrim(c->>'correction_reason',U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'),'') is not null);
 end if;
 for chain in select value from pg_catalog.jsonb_array_elements(projection->'chains') loop
  perform shareholder_register_filing.year_source_v2_require_internal_v1(chain->'company_id'=s->'company_id'
   and chain->>'event_type' in ('cash_issue','loss_covering_reduction') and not(chain->>'receipt_id'=any(ids))
   and chain->'amendment_count'=pg_catalog.to_jsonb(pg_catalog.jsonb_array_length(chain->'amendments')));
  ids:=array_append(ids,chain->>'receipt_id'); effective:=chain->'original_register_fact'; head:='null'::jsonb;
  last_at:=(chain->>'original_recorded_at')::timestamptz; ordinal:=0;
  seen:=array[effective#>>'{observation_id,value}']; heads:='{}'; withdrawals:='{}';
  perform shareholder_register_filing.year_source_v2_require_internal_v1(effective->'observation_id'<>s->'source_id');
  for link in select value from pg_catalog.jsonb_array_elements(chain->'amendments') loop
   ordinal:=ordinal+1;
   perform shareholder_register_filing.year_source_v2_require_internal_v1(link#>'{head,revision}'=pg_catalog.to_jsonb(ordinal)
    and link->'previous_head'=head and link->'target'=effective and (link->>'recorded_at')::timestamptz>last_at
    and not(link#>>'{head,amendment_id}'=any(heads)) and not(link->>'withdrawal_id'=any(withdrawals))
    and not(link#>>'{replacement,observation_id,value}'=any(seen)) and link#>'{replacement,observation_id}'<>s->'source_id');
   effective:=link->'replacement'; head:=link->'head'; last_at:=(link->>'recorded_at')::timestamptz;
   seen:=array_append(seen,effective#>>'{observation_id,value}'); heads:=array_append(heads,head->>'amendment_id'); withdrawals:=array_append(withdrawals,link->>'withdrawal_id');
  end loop;
  perform shareholder_register_filing.year_source_v2_require_internal_v1(chain->'head'=head and chain->'effective_register_fact'=effective
   and (chain->>'evidence_cutoff')::timestamptz=last_at and last_at<capture_at);
  descriptors:=descriptors||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('event_id',chain->'receipt_id',
   'income_year',chain#>'{income_year,value}','anchor_sha256',chain->'original_anchor_sha256','amendment_count',chain->'amendment_count','enumeration_sha256',chain->'enumeration_sha256'));
 end loop;
 perform shareholder_register_filing.year_source_v2_require_internal_v1(ids=(select coalesce(array_agg(i order by i collate "C"),'{}'::text[]) from unnest(ids) i)
  and projection->>'chain_enumeration_sha256'=shareholder_register_filing.year_source_v2_sha_internal_v1(pg_catalog.jsonb_build_array(
   'corporate-reporting-register-evidence-v1',pg_catalog.jsonb_build_object('company_id',s#>'{company_id,value}','income_year',s#>'{income_year,value}',
    'chain_count',projection->'chain_count','chains',descriptors)))
  and projection->>'enumeration_sha256'=shareholder_register_filing.year_source_v2_sha_internal_v1(pg_catalog.jsonb_build_array(
   'corporate-reporting-register-evidence-projection-v1',pg_catalog.jsonb_build_object('company_id',s#>'{company_id,value}','income_year',s#>'{income_year,value}',
    'original_enumeration_sha256',projection->'original_enumeration_sha256','chain_enumeration_sha256',projection->'chain_enumeration_sha256'))));
 ids:='{}';
 for document in select value from pg_catalog.jsonb_array_elements(c->'documents') loop
  perform shareholder_register_filing.year_source_v2_require_internal_v1(document->'company_id'=s->'company_id' and not(document->>'document_id'=any(ids))
   and document->'content_version_sha256'=document->'content_sha256' and document->>'integrity_status' in ('attached','stored','generated_unsigned','signed_owner_attested'));
  ids:=array_append(ids,document->>'document_id');
 end loop;
 for item in select value from pg_catalog.jsonb_array_elements(c->'opening_document_ids') union all
  select value from pg_catalog.jsonb_array_elements(c->'closing_document_ids') union all select value from pg_catalog.jsonb_array_elements(c->'paid_in_document_ids') loop
  perform shareholder_register_filing.year_source_v2_require_internal_v1(item#>>'{}'=any(ids));
 end loop;
 for item in select value from pg_catalog.jsonb_array_elements(s->'governance_receipts') loop
  receipt:=item->'original';
  perform shareholder_register_filing.year_source_v2_require_internal_v1(receipt->'company_id'=s->'company_id' and receipt->'income_year'=s->'income_year'
   and receipt->'active'='true'::jsonb and not(receipt->>'receipt_id'=any(receipt_ids)) and pg_catalog.jsonb_array_length(receipt->'signed_document_hashes')>0);
  receipt_ids:=array_append(receipt_ids,receipt->>'receipt_id');
  if receipt->>'event_type'='dividend' then
   perform shareholder_register_filing.year_source_v2_require_internal_v1(item->'register_observation'='null'::jsonb and receipt->'register_observation_id'='null'::jsonb and receipt->'register_observation_sha256'='null'::jsonb);
  else
   select value into chain from pg_catalog.jsonb_array_elements(projection->'chains') where value->'receipt_id'=receipt->'receipt_id' and value->'income_year'=s->'income_year';
   perform shareholder_register_filing.year_source_v2_require_internal_v1(found and chain->'event_type'=receipt->'event_type'
    and receipt->'register_observation_id'=chain#>'{original_register_fact,observation_id,value}'
    and receipt->'register_observation_sha256'=chain#>'{original_register_fact,fact_sha256}' and receipt->'finalization_sha256'=chain->'original_finalization_sha256'
    and item->'register_observation'<>'null'::jsonb and item#>'{register_observation,observation_id}'=chain#>'{effective_register_fact,observation_id}'
    and item#>'{register_observation,version}'=chain#>'{effective_register_fact,version}' and item#>'{register_observation,fact_sha256}'=chain#>'{effective_register_fact,fact_sha256}'
    and item#>'{register_observation,command,company_id}'=s->'company_id' and item#>'{register_observation,command,income_year}'=s->'income_year'
    and item#>'{register_observation,command,event_kind}'=receipt->'event_type'
    and shareholder_register_filing.observation_evidence_time_internal_v1(item#>>'{register_observation,confirmed_at}',true)<capture_at
    and shareholder_register_filing.observation_evidence_time_internal_v1(item#>>'{register_observation,confirmed_at}',true)<=(chain->>'evidence_cutoff')::timestamptz);
   for document in select value from pg_catalog.jsonb_array_elements(item#>'{register_observation,command,documents}') loop
    perform shareholder_register_filing.year_source_v2_require_internal_v1(exists(select 1 from pg_catalog.jsonb_array_elements(c->'documents') d where d=document-'role'));
   end loop;
  end if;
 end loop;
 perform shareholder_register_filing.year_source_v2_require_internal_v1(receipt_ids=(select coalesce(array_agg(i order by i collate "C"),'{}'::text[]) from unnest(receipt_ids) i)
  and not exists(select 1 from pg_catalog.jsonb_array_elements(projection->'chains') ch where ch->'income_year'=s->'income_year' and not(ch->>'receipt_id'=any(receipt_ids)))
  and pg_catalog.jsonb_array_length(c->'event_evidence')=pg_catalog.jsonb_array_length(c#>'{case,events}'));
 for item in select value from pg_catalog.jsonb_array_elements(c->'event_evidence') loop
  event_index:=(item->>'event_index')::integer;
  perform shareholder_register_filing.year_source_v2_require_internal_v1(event_index<pg_catalog.jsonb_array_length(c#>'{case,events}') and not(event_index=any(indexes)));
  indexes:=array_append(indexes,event_index); event:=c#>array['case','events',event_index::text];
  perform shareholder_register_filing.year_source_v2_require_internal_v1(item->>'event_sha256'=shareholder_register_filing.year_source_v2_sha_internal_v1(event)
   and not exists(select 1 from pg_catalog.jsonb_array_elements(item->'document_ids') d where not(d#>>'{}'=any(ids))));
  if event->>'type' in ('formation','share_sale') then
   perform shareholder_register_filing.year_source_v2_require_internal_v1(item->'governance_receipt_id'='null'::jsonb);
  else
   select value into receipt from pg_catalog.jsonb_array_elements(s->'governance_receipts') r(value) where value#>'{original,receipt_id}'=item->'governance_receipt_id';
   perform shareholder_register_filing.year_source_v2_require_internal_v1(found and receipt#>'{original,event_type}'=event->'type' and not(item->>'governance_receipt_id'=any(selected_ids)));
   selected_ids:=array_append(selected_ids,item->>'governance_receipt_id');
   if event->>'type'<>'dividend' then
    perform shareholder_register_filing.year_source_v2_require_internal_v1(receipt#>'{register_observation,command,effective_at}'=event->'timestamp');
   end if;
  end if;
 end loop;
 perform shareholder_register_filing.year_source_v2_require_internal_v1(receipt_ids=(select coalesce(array_agg(i order by i collate "C"),'{}'::text[]) from unnest(selected_ids) i));
 calculated:=shareholder_register_filing.year_source_v2_sha_internal_v1(pg_catalog.jsonb_build_object('schema','rf1086-year-source-v2',
  'source_id',s->'source_id','version',s->'version','command',c,'confirmed_at',s->'confirmed_at','governance_receipts',s->'governance_receipts',
  'governance_projection',projection,'company_identity_sha256',fresh->'company_identity_sha256'));
 select coalesce(pg_catalog.jsonb_agg(d order by (d->>'document_id') collate "C"),'[]'::jsonb) into ordered from pg_catalog.jsonb_array_elements(c->'documents') d;
 perform shareholder_register_filing.year_source_v2_require_internal_v1(s->>'source_sha256'=calculated and s->>'case_sha256'=shareholder_register_filing.year_source_v2_sha_internal_v1(c->'case')
  and fresh=pg_catalog.jsonb_build_object('source_id',s->'source_id','source_sha256',calculated,'company_identity_sha256',fresh->'company_identity_sha256',
   'documents_sha256',shareholder_register_filing.year_source_v2_sha_internal_v1(ordered),'governance_receipts_sha256',shareholder_register_filing.year_source_v2_sha_internal_v1(s->'governance_receipts'),
   'governance_original_enumeration_sha256',projection->'original_enumeration_sha256','governance_chain_enumeration_sha256',projection->'chain_enumeration_sha256','governance_projection_sha256',projection->'enumeration_sha256'));
 return s;
exception when data_exception or program_limit_exceeded then raise exception 'rf1086_source_storage_invalid';
 when raise_exception then
  get stacked diagnostics reason=message_text;
  if reason='rf1086_register_storage_invalid' then raise exception 'rf1086_source_storage_invalid'; end if;
  raise;
end; $fn$;

-- Translation of the public Governance wire's source reference, not a call to
-- foreign private policy/codecs. Original canonical facts use the frozen ID box.
create or replace function shareholder_register_filing.year_source_v2_row_internal_v1(s jsonb,r shareholder_register_filing.year_source_versions)
returns void language plpgsql immutable security invoker set search_path='' as $fn$
begin
 perform shareholder_register_filing.year_source_v2_require_internal_v1(
  s#>>'{source_id,value}'=r.id::text and s#>>'{company_id,value}'=r.company_id::text
  and s#>'{income_year,value}'=pg_catalog.to_jsonb(r.income_year) and s->'version'=pg_catalog.to_jsonb(r.version)
  and s#>>'{confirmed_by,kind}'='USER' and s#>>'{confirmed_by,subject,value}'=r.actor_id::text and s->>'source_sha256'=r.source_sha256
  and (s->>'confirmed_at')::timestamptz=r.confirmed_at
  and (s#>>'{command,supersedes_source_id,value}') is not distinct from r.predecessor_id::text
  and (s#>>'{command,supersedes_source_sha256}') is not distinct from r.predecessor_sha256
  and (s#>>'{command,correction_reason}') is not distinct from r.correction_reason
  and shareholder_register_filing.year_source_v2_sha_internal_v1(s->'command')=r.request_sha256);
end; $fn$;

-- RF-owned compact proof values share the same closed field types as the v2
-- source codec, without accepting stored wrappers or a foreign private payload.
create or replace function shareholder_register_filing.year_source_v2_compact_internal_v1(value jsonb,expected text)
returns jsonb language plpgsql immutable security invoker set search_path='' as $fn$
declare shape jsonb; result jsonb:='{}'::jsonb; key text; field_type text;
begin
 if right(expected,1)='?' then
  if value='null'::jsonb then return value; end if;
  return shareholder_register_filing.year_source_v2_compact_internal_v1(value,left(expected,-1));
 end if;
 if left(expected,5)='list:' then
  perform shareholder_register_filing.year_source_v2_require_internal_v1(pg_catalog.jsonb_typeof(value)='array');
  select coalesce(pg_catalog.jsonb_agg(shareholder_register_filing.year_source_v2_compact_internal_v1(item,substring(expected from 6)) order by ordinal),'[]'::jsonb)
   into result from pg_catalog.jsonb_array_elements(value) with ordinality e(item,ordinal);
  return result;
 elsif expected='utc' then
  return shareholder_register_filing.year_source_v2_decode_internal_v1(pg_catalog.jsonb_build_object('datetime',value),expected);
 elsif expected in ('text','uuid','sha','integer','positive','year') or left(expected,8)='literal:' then
  return shareholder_register_filing.year_source_v2_decode_internal_v1(value,expected);
 end if;
 -- Only these RF-owned chain value types belong to this public proof contract.
 perform shareholder_register_filing.year_source_v2_require_internal_v1(expected in ('CompanyId','IncomeYear','Rf1086RegisterObservationId',
  'Rf1086YearRegisterFactV2','Rf1086YearGovernanceHeadV2','Rf1086YearGovernanceLinkV2','Rf1086YearGovernanceChainV2'));
 shape:=shareholder_register_filing.year_source_v2_shape_internal_v1(expected);
 perform shareholder_register_filing.year_source_v2_require_internal_v1(pg_catalog.jsonb_typeof(value)='object'
  and (select array_agg(k order by k) from pg_catalog.jsonb_object_keys(value) k)=(select array_agg(k order by k) from pg_catalog.jsonb_object_keys(shape) k));
 for key,field_type in select * from pg_catalog.jsonb_each_text(shape) loop
  result:=result||pg_catalog.jsonb_build_object(key,shareholder_register_filing.year_source_v2_compact_internal_v1(value->key,field_type));
 end loop;
 return result;
end; $fn$;

-- No IF NOT EXISTS/adoption/owner transfer. The session's temp namespace may
-- contain a caller-created substitute: every producer, consumer and invalidator
-- checks its catalog before qualified access. A bad object only denies that
-- caller's transaction; it can never supply trusted evidence.
create or replace function shareholder_register_filing.year_source_v2_proof_catalog_internal_v1()
returns oid language plpgsql volatile security invoker set search_path='' as $fn$
declare object_id oid; owner_id oid:='shareholder_register_filing_store_owner'::regrole;
begin
 select c.oid into object_id from pg_catalog.pg_class c where c.relnamespace=pg_catalog.pg_my_temp_schema()
  and c.relname='rf1086_year_source_governance_proofs';
 if object_id is null then return null; end if;
 if not exists(select 1 from pg_catalog.pg_class c where c.oid=object_id and c.relowner=owner_id
  and c.relkind='r' and c.relpersistence='t' and not c.relispartition and not c.relrowsecurity and not c.relforcerowsecurity and c.reloftype=0)
 or (select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(a.attname,a.atttypid::text,a.attnotnull) order by a.attnum)
     from pg_catalog.pg_attribute a where a.attrelid=object_id and a.attnum>0)
  is distinct from pg_catalog.jsonb_build_array(
   pg_catalog.jsonb_build_array('transaction_id','pg_catalog.xid8'::regtype::oid::text,true),
   pg_catalog.jsonb_build_array('actor_id','pg_catalog.uuid'::regtype::oid::text,true),
   pg_catalog.jsonb_build_array('company_id','pg_catalog.uuid'::regtype::oid::text,true),
   pg_catalog.jsonb_build_array('income_year','pg_catalog.int4'::regtype::oid::text,true),
   pg_catalog.jsonb_build_array('source_sha256','pg_catalog.text'::regtype::oid::text,true),
   pg_catalog.jsonb_build_array('proof','pg_catalog.jsonb'::regtype::oid::text,true))
 or exists(select 1 from pg_catalog.pg_attribute a where a.attrelid=object_id and a.attnum>0
  and (a.attisdropped or a.attgenerated<>'' or a.attidentity<>'' or a.atthasdef or a.atttypmod<>-1 or a.attinhcount<>0 or not a.attislocal))
 or exists(select 1 from pg_catalog.pg_class c cross join lateral pg_catalog.aclexplode(coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
  where c.oid=object_id and (a.grantee<>owner_id or a.grantor<>owner_id))
 or exists(select 1 from pg_catalog.pg_attribute c cross join lateral pg_catalog.aclexplode(c.attacl) a
  where c.attrelid=object_id and (a.grantee<>owner_id or a.grantor<>owner_id))
 or exists(select 1 from pg_catalog.pg_attrdef where adrelid=object_id)
 or exists(select 1 from pg_catalog.pg_constraint where conrelid=object_id)
 or exists(select 1 from pg_catalog.pg_rewrite where ev_class=object_id)
 or exists(select 1 from pg_catalog.pg_trigger where tgrelid=object_id)
 or exists(select 1 from pg_catalog.pg_inherits where inhrelid=object_id or inhparent=object_id)
 or exists(select 1 from pg_catalog.pg_index where indrelid=object_id)
 then raise exception 'rf1086_source_governance_evidence_changed'; end if;
 return object_id;
end; $fn$;

create or replace function shareholder_register_filing.receive_year_source_governance_proof_v1(
 p_company uuid,p_year integer,p_source_sha text,p_proof jsonb,p_subject text)
returns void language plpgsql volatile security definer set search_path='' as $fn$
declare actor uuid; chains jsonb; descriptors jsonb; ids text[];
begin
 actor:=shareholder_register_filing.verified_actor_v1();
 if actor is null or actor::text is distinct from p_subject then raise exception 'rf1086_forbidden'; end if;
 perform shareholder_register_filing.assert_source_approval_guards_v1(p_company,p_year);
 perform shareholder_register_filing.year_source_v2_require_internal_v1(p_company is not null and p_year between 2000 and 2100
  and p_source_sha ~ '^[0-9a-f]{64}$' and pg_catalog.jsonb_typeof(p_proof)='object'
  and p_proof-array['codec','company_id','income_year','chain_count','chain_enumeration_sha256','chains']='{}'::jsonb
  and p_proof ?& array['codec','company_id','income_year','chain_count','chain_enumeration_sha256','chains']
  and p_proof->>'codec'='rf1086-year-governance-proof-v1' and p_proof->'company_id'=pg_catalog.to_jsonb(p_company::text)
  and p_proof->'income_year'=pg_catalog.to_jsonb(p_year));
 chains:=shareholder_register_filing.year_source_v2_compact_internal_v1(p_proof->'chains','list:Rf1086YearGovernanceChainV2');
 perform shareholder_register_filing.year_source_v2_require_internal_v1(chains=p_proof->'chains'
  and p_proof->'chain_count'=pg_catalog.to_jsonb(pg_catalog.jsonb_array_length(chains))
  and not exists(select 1 from pg_catalog.jsonb_array_elements(chains) c where c#>>'{company_id,value}' is distinct from p_company::text));
 select coalesce(array_agg(c->>'receipt_id' order by position),'{}'::text[]),
  coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('event_id',c->'receipt_id','income_year',c#>'{income_year,value}',
   'anchor_sha256',c->'original_anchor_sha256','amendment_count',c->'amendment_count','enumeration_sha256',c->'enumeration_sha256') order by position),'[]'::jsonb)
  into ids,descriptors from pg_catalog.jsonb_array_elements(chains) with ordinality e(c,position);
 perform shareholder_register_filing.year_source_v2_require_internal_v1(ids=(select coalesce(array_agg(i order by i collate "C"),'{}'::text[]) from (select distinct unnest(ids) i) unique_ids)
  and p_proof->>'chain_enumeration_sha256'=shareholder_register_filing.year_source_v2_sha_internal_v1(pg_catalog.jsonb_build_array(
   'corporate-reporting-register-evidence-v1',pg_catalog.jsonb_build_object('company_id',p_company::text,'income_year',p_year,'chain_count',p_proof->'chain_count','chains',descriptors))));
 if shareholder_register_filing.year_source_v2_proof_catalog_internal_v1() is null then
  if not pg_catalog.has_database_privilege(current_user,pg_catalog.current_database(),'TEMP') then
   raise exception 'rf1086_source_governance_evidence_changed';
  end if;
  create temporary table pg_temp.rf1086_year_source_governance_proofs(
   transaction_id xid8 not null,actor_id uuid not null,company_id uuid not null,income_year integer not null,source_sha256 text not null,proof jsonb not null) on commit drop;
  perform shareholder_register_filing.year_source_v2_proof_catalog_internal_v1();
 end if;
 delete from pg_temp.rf1086_year_source_governance_proofs where transaction_id=pg_catalog.pg_current_xact_id()
  and actor_id=actor and company_id=p_company and income_year=p_year and source_sha256=p_source_sha;
 insert into pg_temp.rf1086_year_source_governance_proofs values(pg_catalog.pg_current_xact_id(),actor,p_company,p_year,p_source_sha,p_proof);
exception when data_exception or no_data_found or too_many_rows then raise exception 'rf1086_source_storage_invalid';
end; $fn$;

-- Gov may invalidate the whole company, including proofs for other years. NULL
-- is reserved for its TRUNCATE trigger. No identity gate: this must invalidate
-- after every successful owned mutation, including privileged maintenance.
create or replace function shareholder_register_filing.invalidate_year_source_governance_proofs_v1(p_company uuid)
returns void language plpgsql volatile security definer set search_path='' as $fn$
begin
 if shareholder_register_filing.year_source_v2_proof_catalog_internal_v1() is not null then
  delete from pg_temp.rf1086_year_source_governance_proofs where p_company is null or company_id=p_company;
 end if;
end; $fn$;

create or replace function shareholder_register_filing.assert_year_source_v2_internal_v1(p_company uuid,p_year integer,p_snapshot text)
returns void language plpgsql volatile security invoker set search_path='' as $fn$
declare s jsonb; projection jsonb; authoritative jsonb; chain jsonb;
 receipt jsonb; wrapper jsonb; source_fact jsonb; captured record; retained shareholder_register_filing.year_source_versions%rowtype;
 reason text; subject text:=shareholder_register_filing.verified_actor_v1()::text;
begin
 perform shareholder_register_filing.assert_source_approval_guards_v1(p_company,p_year);
 s:=shareholder_register_filing.year_source_v2_validate_internal_v1(p_snapshot);
 perform shareholder_register_filing.year_source_v2_require_internal_v1(s#>>'{company_id,value}'=p_company::text and s#>'{income_year,value}'=pg_catalog.to_jsonb(p_year));
 select * into retained from shareholder_register_filing.year_source_versions where id=(s#>>'{source_id,value}')::uuid;
 if found then perform shareholder_register_filing.year_source_v2_row_internal_v1(s,retained); end if;
 projection:=s->'governance_projection';
 if shareholder_register_filing.year_source_v2_proof_catalog_internal_v1() is null then
  raise exception 'rf1086_source_governance_evidence_changed';
 end if;
 select proof into authoritative from pg_temp.rf1086_year_source_governance_proofs
  where transaction_id=pg_catalog.pg_current_xact_id() and actor_id=shareholder_register_filing.verified_actor_v1()
   and company_id=p_company and income_year=p_year and source_sha256=s->>'source_sha256';
 if authoritative is distinct from pg_catalog.jsonb_build_object('codec','rf1086-year-governance-proof-v1',
  'company_id',p_company::text,'income_year',p_year,'chain_count',projection->'chain_count',
  'chain_enumeration_sha256',projection->'chain_enumeration_sha256','chains',projection->'chains')
 then raise exception 'rf1086_source_governance_evidence_changed'; end if;
 for wrapper in select value from pg_catalog.jsonb_array_elements(s->'governance_receipts') loop
  if wrapper->'register_observation'='null'::jsonb then continue; end if;
  select value into chain from pg_catalog.jsonb_array_elements(projection->'chains') where value->'receipt_id'=wrapper#>'{original,receipt_id}';
  source_fact:=chain->'effective_register_fact';
  begin
   select * into strict captured from shareholder_register_filing.read_current_register_observation_evidence_v1(
    (source_fact#>>'{observation_id,value}')::uuid,p_company,p_year,(source_fact->>'version')::integer,source_fact->>'fact_sha256',(chain->>'evidence_cutoff')::timestamptz,subject);
  exception when raise_exception then
   get stacked diagnostics reason=message_text;
   if reason in ('rf1086_register_predecessor_mismatch','rf1086_register_observation_after_cutoff')
    then raise exception 'rf1086_source_register_observation_stale'; end if;
   raise;
  end;
  -- Preserve exact legacy wrapper values/offsets, never normalize a retained
  -- observation into new bytes while accepting its old digest label.
  select value into receipt from pg_catalog.jsonb_array_elements(p_snapshot::jsonb#>'{snapshot,fields,governance_receipts}')
   where value#>>'{fields,original,fields,receipt_id}'=wrapper#>>'{original,receipt_id}';
  if captured.snapshot_text::jsonb->'snapshot' is distinct from receipt#>'{fields,register_observation}'
  then raise exception 'rf1086_source_register_observation_stale'; end if;
 end loop;
exception when data_exception or no_data_found or too_many_rows then raise exception 'rf1086_source_storage_invalid';
end; $fn$;

-- Preserve every existing hook's position relative to replay/currentness. Only
-- the owned raw-source assertion dispatches; its v1 branch remains byte-exact.
do $dispatch$
declare old record; changed record; definition text; body text;
 marker constant text:='-- rf193-source-codec-dispatch-v2';
 anchor constant text:=' payload:=p_snapshot::jsonb;'; insertion text;
begin
 select * into strict old from pg_catalog.pg_proc where oid='shareholder_register_filing.assert_source_register_observations_active_internal_v1(uuid,integer,text)'::regprocedure;
 insertion:=E'\n '||marker||E'\n if payload->>''codec''=''rf1086-year-source-v2'' then\n  perform shareholder_register_filing.assert_year_source_v2_internal_v1(p_company,p_year,p_snapshot);\n  return;\n end if;';
 if position(marker in old.prosrc)>0 then
  if position(anchor||insertion in old.prosrc)=0 then raise exception 'rf1086_source_v2_definition_drift'; end if;
 else
  if old.proowner<>current_user::regrole or old.prosecdef or old.provolatile<>'v' or old.proconfig is distinct from array['search_path=""']::text[]
   or length(old.prosrc)-length(replace(old.prosrc,anchor,''))<>length(anchor)
  then raise exception 'rf1086_source_v2_definition_drift'; end if;
  body:=replace(old.prosrc,anchor,anchor||insertion); definition:=pg_catalog.pg_get_functiondef(old.oid);
  if length(definition)-length(replace(definition,old.prosrc,''))<>length(old.prosrc) then raise exception 'rf1086_source_v2_definition_drift'; end if;
  execute replace(definition,old.prosrc,body);
  select * into strict changed from pg_catalog.pg_proc where oid=old.oid;
  if (changed.proowner,changed.proacl,changed.proconfig,changed.prosecdef,changed.provolatile,changed.proparallel) is distinct from
   (old.proowner,old.proacl,old.proconfig,old.prosecdef,old.provolatile,old.proparallel) then raise exception 'rf1086_source_v2_definition_drift'; end if;
 end if;
end; $dispatch$;

-- Derive the new closed append from the released owned writer, retaining its
-- lock order, predecessor/duplicate behavior and table insertion exactly. This
-- RPC is not a replay endpoint: committed historical lookup remains separate.
do $append$
declare old record; definition text; body text; original_body text; marker constant text:='-- rf193-source-v1-downgrade-fence';
 anchor constant text:=' insert into shareholder_register_filing.year_source_versions values(';
 fence_anchor constant text:=' -- rf193-withdrawal-source-admission-v1'; fence text; binding text;
begin
 select * into strict old from pg_catalog.pg_proc where oid='shareholder_register_filing.append_year_source_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamptz)'::regprocedure;
 fence:=E' '||marker||E'\n if exists(select 1 from shareholder_register_filing.year_source_versions v where v.id=h.source_id and v.company_id=p_company and v.income_year=p_year and v.snapshot_text::jsonb->>''codec''=''rf1086-year-source-v2'') then\n  raise exception ''rf1086_source_codec_downgrade'';\n end if;\n';
 original_body:=old.prosrc;
 if position(marker in original_body)>0 then
  if position(fence||fence_anchor in original_body)=0 then raise exception 'rf1086_source_v2_definition_drift'; end if;
  original_body:=replace(original_body,fence,'');
 end if;
 if old.proowner<>current_user::regrole or not old.prosecdef or old.provolatile<>'v' or old.proconfig is distinct from array['search_path=""']::text[]
  or length(original_body)-length(replace(original_body,anchor,''))<>length(anchor)
  or length(original_body)-length(replace(original_body,'''rf1086-year-source-v1''',''))<>length('''rf1086-year-source-v1''')
  or length(original_body)-length(replace(original_body,'''Rf1086YearSourceSnapshot''',''))<>length('''Rf1086YearSourceSnapshot''')
  or length(original_body)-length(replace(original_body,fence_anchor,''))<>length(fence_anchor)
  or position('perform shareholder_register_filing.assert_source_register_observations_active_internal_v1(p_company,p_year,p_snapshot);' in original_body)=0
 then raise exception 'rf1086_source_v2_definition_drift'; end if;
 binding:=E' perform shareholder_register_filing.year_source_v2_row_internal_v1(shareholder_register_filing.year_source_v2_validate_internal_v1(p_snapshot),\n  row(p_id,p_company,p_year,p_version,a,p_key,p_request_sha,p_source_sha,p_previous,p_previous_sha,p_reason,p_snapshot,p_confirmed_at)::shareholder_register_filing.year_source_versions);\n if h.source_id is not null and not exists(select 1 from shareholder_register_filing.year_source_versions v where v.id=h.source_id and v.confirmed_at<p_confirmed_at)\n then raise exception ''rf1086_source_predecessor_mismatch''; end if;\n';
 body:=replace(replace(original_body,'''rf1086-year-source-v1''','''rf1086-year-source-v2'''),'''Rf1086YearSourceSnapshot''','''Rf1086YearSourceSnapshotV2''');
 body:=replace(body,anchor,binding||anchor);
 definition:=pg_catalog.pg_get_functiondef(old.oid);
 if length(definition)-length(replace(definition,old.prosrc,''))<>length(old.prosrc) then raise exception 'rf1086_source_v2_definition_drift'; end if;
 definition:=replace(definition,'FUNCTION shareholder_register_filing.append_year_source_v1(','FUNCTION shareholder_register_filing.append_year_source_v2(');
 execute replace(definition,old.prosrc,body);
 if old.prosrc=original_body then
  execute replace(pg_catalog.pg_get_functiondef(old.oid),old.prosrc,replace(original_body,fence_anchor,fence||fence_anchor));
 end if;
 if exists(select 1 from pg_catalog.pg_proc p where p.oid=old.oid and
  (p.proowner,p.proacl,p.proconfig,p.prosecdef,p.provolatile,p.proparallel) is distinct from
  (old.proowner,old.proacl,old.proconfig,old.prosecdef,old.provolatile,old.proparallel)) then raise exception 'rf1086_source_v2_definition_drift'; end if;
end; $append$;

-- Reapplication also removes accidental fixture grants. Old v1 contracts and
-- their runtime ACLs are never included in this closure.
do $closed$
declare routine regprocedure; grantee_name text;
begin
 for routine in select p.oid::regprocedure from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
  where n.nspname='shareholder_register_filing' and p.proname in ('year_source_v2_require_internal_v1','year_source_v2_json_internal_v1','year_source_v2_sha_internal_v1',
   'year_source_v2_shape_internal_v1','year_source_v2_decode_internal_v1','year_source_v2_validate_internal_v1','year_source_v2_row_internal_v1',
   'year_source_v2_compact_internal_v1','year_source_v2_proof_catalog_internal_v1','receive_year_source_governance_proof_v1','invalidate_year_source_governance_proofs_v1',
   'assert_year_source_v2_internal_v1','append_year_source_v2') loop
  execute pg_catalog.format('revoke all on function %s from public',routine);
  for grantee_name in select distinct r.rolname from pg_catalog.pg_proc p cross join lateral pg_catalog.aclexplode(p.proacl) a
   join pg_catalog.pg_roles r on r.oid=a.grantee where p.oid=routine::oid and a.grantee<>p.proowner loop
   execute pg_catalog.format('revoke all on function %s from %I',routine,grantee_name);
  end loop;
 end loop;
end; $closed$;
reset role;
do $restore$
declare item record; schema_owner text;
begin
 if (select added from pg_temp.rf193_source_v2_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='shareholder_register_filing';
  execute pg_catalog.format('set local role %I',schema_owner);
  revoke create on schema shareholder_register_filing from shareholder_register_filing_store_owner;
  reset role;
 end if;
 for item in select * from pg_temp.rf193_source_v2_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',item.role_name,current_user,current_user);
  if item.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   item.role_name,current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
