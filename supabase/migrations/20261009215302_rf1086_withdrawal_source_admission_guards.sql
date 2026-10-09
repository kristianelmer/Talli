-- RF-only downstream admission backstops. Withdrawal remains ungranted.
-- Historical replay/outcomes stay available; Governance/archive/readiness remain separate.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_withdrawal_admission_role(prior jsonb) on commit drop;
do $borrow$
declare prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into prior from pg_catalog.pg_auth_members m
   where m.roleid=(select oid from pg_catalog.pg_roles where rolname='shareholder_register_filing_store_owner')
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.rf193_withdrawal_admission_role values(prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;

-- Guard only references in the frozen source codec; not a second economics or
-- Governance-enumeration implementation. Both overloads require held scope locks.
create or replace function shareholder_register_filing.assert_source_register_observations_active_internal_v1(
 p_company uuid,p_year integer,p_snapshot text
) returns void language plpgsql volatile security invoker set search_path='' as $fn$
declare payload jsonb; fields jsonb; entry jsonb; receipt jsonb; evidence jsonb;
 receipt_ids text[]:='{}'; evidence_ids text[]:='{}'; target shareholder_register_filing.register_observations%rowtype;
 source_time timestamptz; reason text; events jsonb; event jsonb; event_kind text; event_index integer;
 evidence_indexes integer[]:='{}';
begin
 perform shareholder_register_filing.assert_source_approval_guards_v1(p_company,p_year);
 if p_snapshot is null or not(p_snapshot is json object with unique keys)
 then raise exception 'rf1086_source_storage_invalid'; end if;
 payload:=p_snapshot::jsonb;
 fields:=payload#>'{snapshot,fields}';
 if (select count(*) from pg_catalog.jsonb_object_keys(payload))<>2
  or payload->>'codec' is distinct from 'rf1086-year-source-v1'
  or payload#>>'{snapshot,record}' is distinct from 'Rf1086YearSourceSnapshot'
  or pg_catalog.jsonb_typeof(fields) is distinct from 'object'
  or fields->'company_id' is distinct from pg_catalog.jsonb_build_object('record','CompanyId','fields',pg_catalog.jsonb_build_object('value',p_company::text))
  or fields->'income_year' is distinct from pg_catalog.jsonb_build_object('record','IncomeYear','fields',pg_catalog.jsonb_build_object('value',p_year))
  or pg_catalog.jsonb_typeof(fields->'governance_receipts') is distinct from 'array'
  or pg_catalog.jsonb_typeof(fields#>'{confirmed_at,datetime}') is distinct from 'string'
  or (fields#>>'{confirmed_at,datetime}') !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?([+-]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?|Z)$'
  or fields#>>'{command,record}' is distinct from 'RecordRf1086YearSource'
  or fields#>>'{command,fields,case,record}' is distinct from 'Rf1086Case'
  or pg_catalog.jsonb_typeof(fields#>'{command,fields,case,fields,events}') is distinct from 'array'
  or pg_catalog.jsonb_typeof(fields#>'{command,fields,event_evidence}') is distinct from 'array'
 then raise exception 'rf1086_source_storage_invalid'; end if;
 events:=fields#>'{command,fields,case,fields,events}';
 if pg_catalog.jsonb_array_length(events)<>pg_catalog.jsonb_array_length(fields#>'{command,fields,event_evidence}')
  or fields#>'{command,fields,no_activity_confirmed}' is distinct from pg_catalog.to_jsonb(pg_catalog.jsonb_array_length(events)=0)
 then raise exception 'rf1086_source_storage_invalid'; end if;
 source_time:=(fields#>>'{confirmed_at,datetime}')::timestamptz;
 if not pg_catalog.isfinite(source_time) then raise exception 'rf1086_source_storage_invalid'; end if;
 for entry in select value from pg_catalog.jsonb_array_elements(fields->'governance_receipts') loop
  receipt:=entry->'fields';
  if pg_catalog.jsonb_typeof(entry) is distinct from 'object'
   or (select count(*) from pg_catalog.jsonb_object_keys(entry))<>2
   or entry->>'record' is distinct from 'Rf1086YearGovernanceReceipt'
   or pg_catalog.jsonb_typeof(receipt) is distinct from 'object'
   or not(receipt ?& array['receipt_id','company_id','income_year','event_type','economic_sha256','finalization_sha256','signed_document_hashes','active','register_observation_id','register_observation_sha256'])
   or (select count(*) from pg_catalog.jsonb_object_keys(receipt))<>10
   or receipt->'company_id' is distinct from fields->'company_id'
   or receipt->'income_year' is distinct from fields->'income_year'
   or pg_catalog.jsonb_typeof(receipt->'receipt_id') is distinct from 'string'
   or (receipt->>'receipt_id') !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
   or (receipt->>'receipt_id')=any(receipt_ids)
   or pg_catalog.jsonb_typeof(receipt->'event_type') is distinct from 'string'
   or nullif(pg_catalog.btrim(receipt->>'event_type'),'') is null
   or receipt->'active' is distinct from 'true'::jsonb
   or pg_catalog.jsonb_typeof(receipt->'economic_sha256') is distinct from 'string'
   or (receipt->>'economic_sha256') !~ '^[a-f0-9]{64}$'
   or pg_catalog.jsonb_typeof(receipt->'finalization_sha256') is distinct from 'string'
   or (receipt->>'finalization_sha256') !~ '^[a-f0-9]{64}$'
   or pg_catalog.jsonb_typeof(receipt->'signed_document_hashes') is distinct from 'array'
   or pg_catalog.jsonb_array_length(receipt->'signed_document_hashes')=0
   or exists(select 1 from pg_catalog.jsonb_array_elements(receipt->'signed_document_hashes') h
     where pg_catalog.jsonb_typeof(h) is distinct from 'string' or (h#>>'{}') !~ '^[a-f0-9]{64}$')
  then raise exception 'rf1086_source_storage_invalid'; end if;
  receipt_ids:=pg_catalog.array_append(receipt_ids,receipt->>'receipt_id');
  if receipt->'register_observation_id'='null'::jsonb and receipt->'register_observation_sha256'='null'::jsonb then
   if receipt->>'event_type'<>'dividend' then raise exception 'rf1086_source_storage_invalid'; end if;
   continue;
  end if;
  if pg_catalog.jsonb_typeof(receipt->'register_observation_id') is distinct from 'string'
   or (receipt->>'register_observation_id') !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
   or pg_catalog.jsonb_typeof(receipt->'register_observation_sha256') is distinct from 'string'
   or (receipt->>'register_observation_sha256') !~ '^[a-f0-9]{64}$'
  then raise exception 'rf1086_source_storage_invalid'; end if;
  -- The frozen receipt has no version. Resolve the immutable exact row; do not
  -- manufacture a version or accept a caller-supplied currentness assertion.
  select * into target from shareholder_register_filing.register_observations
   where id=(receipt->>'register_observation_id')::uuid and company_id=p_company and income_year=p_year
    and fact_sha256=receipt->>'register_observation_sha256';
  if target.id is null or target.confirmed_at>=source_time
  then raise exception 'rf1086_source_register_observation_stale'; end if;
  begin
   perform shareholder_register_filing.assert_register_observation_active_internal_v1(target.id,p_company,p_year,target.version,target.fact_sha256);
  exception when raise_exception then
   get stacked diagnostics reason=message_text;
   if reason='rf1086_register_predecessor_mismatch' then raise exception 'rf1086_source_register_observation_stale'; end if;
   raise;
  end;
 end loop;
 -- Structural event-to-evidence-to-receipt binding prevents deleting both
 -- reference collections or relabeling a capital receipt as a dividend. It
 -- follows the frozen codec's existing governed kinds, without economics.
 for entry in select value from pg_catalog.jsonb_array_elements(fields#>'{command,fields,event_evidence}') loop
  evidence:=entry->'fields';
  if pg_catalog.jsonb_typeof(entry) is distinct from 'object'
   or entry->>'record' is distinct from 'Rf1086YearEventEvidence'
   or (select count(*) from pg_catalog.jsonb_object_keys(entry))<>2
   or pg_catalog.jsonb_typeof(evidence) is distinct from 'object'
   or not(evidence ?& array['event_index','event_sha256','document_ids','governance_receipt_id'])
   or (select count(*) from pg_catalog.jsonb_object_keys(evidence))<>4
   or pg_catalog.jsonb_typeof(evidence->'event_index') is distinct from 'number'
   or (evidence->>'event_index') !~ '^(0|[1-9][0-9]*)$'
  then raise exception 'rf1086_source_storage_invalid'; end if;
  event_index:=(evidence->>'event_index')::integer;
  if event_index<0 or event_index>=pg_catalog.jsonb_array_length(events) or event_index=any(evidence_indexes)
  then raise exception 'rf1086_source_storage_invalid'; end if;
  evidence_indexes:=pg_catalog.array_append(evidence_indexes,event_index);
  event:=events->event_index;
  event_kind:=case event->>'record'
   when 'Rf1086FormationEvent' then 'formation' when 'Rf1086ShareSaleEvent' then 'share_sale'
   when 'Rf1086DividendEvent' then 'dividend' when 'Rf1086CashIssueEvent' then 'cash_issue'
   when 'Rf1086CashNominalIncreaseEvent' then 'cash_nominal_increase'
   when 'Rf1086LossCoveringReductionEvent' then 'loss_covering_reduction' end;
  if event_kind is null or event#>>'{fields,type}' is distinct from event_kind
   or pg_catalog.jsonb_typeof(event) is distinct from 'object'
   or (select count(*) from pg_catalog.jsonb_object_keys(event))<>2
   or pg_catalog.jsonb_typeof(event->'fields') is distinct from 'object'
  then raise exception 'rf1086_source_storage_invalid'; end if;
  if event_kind in ('formation','share_sale') then
   if evidence->'governance_receipt_id' is distinct from 'null'::jsonb
   then raise exception 'rf1086_source_storage_invalid'; end if;
   continue;
  end if;
  if pg_catalog.jsonb_typeof(evidence->'governance_receipt_id') is distinct from 'string'
   or (evidence->>'governance_receipt_id') !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
   or (evidence->>'governance_receipt_id')=any(evidence_ids)
   or not exists(select 1 from pg_catalog.jsonb_array_elements(fields->'governance_receipts') r
     where r#>>'{fields,receipt_id}'=evidence->>'governance_receipt_id'
      and r#>>'{fields,event_type}'=event_kind)
  then raise exception 'rf1086_source_storage_invalid'; end if;
  evidence_ids:=pg_catalog.array_append(evidence_ids,evidence->>'governance_receipt_id');
 end loop;
 if (select coalesce(pg_catalog.array_agg(x order by x),'{}'::text[]) from unnest(receipt_ids) x)
  is distinct from (select coalesce(pg_catalog.array_agg(x order by x),'{}'::text[]) from unnest(evidence_ids) x)
 then raise exception 'rf1086_source_storage_invalid'; end if;
exception when data_exception then
 raise exception 'rf1086_source_storage_invalid';
end; $fn$;

create or replace function shareholder_register_filing.assert_source_register_observations_active_internal_v1(
 p_company uuid,p_year integer,p_source uuid,p_source_sha text
) returns void language plpgsql volatile security invoker set search_path='' as $fn$
declare source shareholder_register_filing.year_source_versions%rowtype; fields jsonb;
begin
 perform shareholder_register_filing.assert_source_approval_guards_v1(p_company,p_year);
 select * into source from shareholder_register_filing.year_source_versions
  where id=p_source and company_id=p_company and income_year=p_year and source_sha256=p_source_sha;
 if source.id is null then raise exception 'rf1086_source_storage_invalid'; end if;
 perform shareholder_register_filing.assert_source_register_observations_active_internal_v1(p_company,p_year,source.snapshot_text);
 fields:=source.snapshot_text::jsonb#>'{snapshot,fields}';
 if fields#>>'{source_id,fields,value}' is distinct from source.id::text
  or fields->>'source_sha256' is distinct from source.source_sha256
  or (fields#>>'{confirmed_at,datetime}')::timestamptz is distinct from source.confirmed_at
 then raise exception 'rf1086_source_storage_invalid'; end if;
exception when data_exception then
 raise exception 'rf1086_source_storage_invalid';
end; $fn$;
revoke all on function shareholder_register_filing.assert_source_register_observations_active_internal_v1(uuid,integer,text),
 shareholder_register_filing.assert_source_register_observations_active_internal_v1(uuid,integer,uuid,text)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor,corporate_governance_workflow_executor;

-- Patch only the fresh-effect boundary, never shared context/recovery/finish.
-- Finite unique anchors and exact catalog comparisons fail closed on drift.
do $admission_guards$
declare spec record; before_row record; after_row record; definition text; body text; insertion text;
 marker constant text:='-- rf193-withdrawal-source-admission-v1';
begin
 for spec in select * from (values
  ('shareholder_register_filing.append_year_source_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamptz)',
   ' insert into shareholder_register_filing.year_source_versions values(',
   'perform shareholder_register_filing.assert_source_register_observations_active_internal_v1(p_company,p_year,p_snapshot);'),
  ('shareholder_register_filing.append_source_preview_v1(uuid,uuid,integer,uuid,text,text,text,text)',
   ' insert into shareholder_register_filing.source_previews(id,',
   'perform shareholder_register_filing.assert_source_register_observations_active_internal_v1(p_company,p_year,source.id,source.source_sha256);'),
  ('shareholder_register_filing.bridge_source_preview_v1(uuid,text,text)',
   ' insert into shareholder_register_filing.filing_previews(id,',
   'perform shareholder_register_filing.assert_source_register_observations_active_internal_v1(s.company_id,s.income_year,s.source_id,s.source_sha256);'),
  ('shareholder_register_filing.append_source_approval_v1(uuid,uuid,text,text,text,text)',
   ' update shareholder_register_filing.filing_approval_snapshots set invalidated_at=',
   'perform shareholder_register_filing.assert_source_register_observations_active_internal_v1(s.company_id,s.income_year,s.source_id,s.source_sha256);'),
  ('shareholder_register_filing.append_source_approval_v2(uuid,uuid,text,text,text,text)',
   ' update shareholder_register_filing.filing_approval_snapshots set invalidated_at=',
   'perform shareholder_register_filing.assert_source_register_observations_active_internal_v1(s.company_id,s.income_year,s.source_id,s.source_sha256);'),
  ('shareholder_register_filing.claim_source_submission_v1(uuid,text,uuid,text)',
   ' actual_head:=shareholder_register_filing.submission_head_internal_v1(a.company_id,a.income_year);',
   'perform shareholder_register_filing.assert_source_register_observations_active_internal_v1(a.company_id,a.income_year,b.source_id,b.source_sha256);'),
  ('shareholder_register_filing.claim_source_submission_v2(uuid,text,uuid,text,text)',
   ' actual_head:=shareholder_register_filing.submission_head_internal_v1(a.company_id,a.income_year);',
   'perform shareholder_register_filing.assert_source_register_observations_active_internal_v1(a.company_id,a.income_year,b.source_id,b.source_sha256);'),
  ('shareholder_register_filing.prepare_source_operation_v1(uuid,text,text,text,uuid,uuid,text,text)',
   ' insert into shareholder_register_filing.production_filing_events(submission_id,operation_name,operation_state,attempt,',
   'perform shareholder_register_filing.assert_source_register_observations_active_internal_v1(s.company_id,s.income_year,b.source_id,b.source_sha256);')
 ) guards(identity,anchor,guard) loop
  select * into before_row from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure(spec.identity);
  if before_row.oid is null or before_row.proowner<>current_user::regrole or not before_row.prosecdef
   or before_row.provolatile<>'v' or before_row.proconfig is distinct from array['search_path=""']::text[]
   or before_row.prolang<>(select oid from pg_catalog.pg_language where lanname='plpgsql')
  then raise exception 'rf1086_withdrawal_admission_definition_drift'; end if;
  insertion:=' '||marker||E'\n '||spec.guard||E'\n';
  if pg_catalog.strpos(before_row.prosrc,marker)>0 then
   if pg_catalog.strpos(before_row.prosrc,insertion||spec.anchor)=0
   then raise exception 'rf1086_withdrawal_admission_definition_drift'; end if;
   continue;
  end if;
  if pg_catalog.length(before_row.prosrc)-pg_catalog.length(pg_catalog.replace(before_row.prosrc,spec.anchor,''))<>pg_catalog.length(spec.anchor)
  then raise exception 'rf1086_withdrawal_admission_definition_drift'; end if;
  body:=pg_catalog.replace(before_row.prosrc,spec.anchor,insertion||spec.anchor);
  definition:=pg_catalog.pg_get_functiondef(before_row.oid);
  if pg_catalog.length(definition)-pg_catalog.length(pg_catalog.replace(definition,before_row.prosrc,''))<>pg_catalog.length(before_row.prosrc)
  then raise exception 'rf1086_withdrawal_admission_definition_drift'; end if;
  execute pg_catalog.replace(definition,before_row.prosrc,body);
  select * into after_row from pg_catalog.pg_proc where oid=before_row.oid;
  if (after_row.proowner,after_row.proacl,after_row.proconfig,after_row.prosecdef,after_row.provolatile,after_row.proparallel)
   is distinct from (before_row.proowner,before_row.proacl,before_row.proconfig,before_row.prosecdef,before_row.provolatile,before_row.proparallel)
  then raise exception 'rf1086_withdrawal_admission_definition_drift'; end if;
 end loop;
end; $admission_guards$;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_withdrawal_admission_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
   current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
