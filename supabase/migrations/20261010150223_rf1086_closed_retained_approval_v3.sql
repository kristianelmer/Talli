-- Closed retained v3 review/approval. RF application owns annual policy.
-- SQL repeats live authority, exact structural/source/review commitments.
-- Legacy definitions and ordinary grants stay unchanged.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_approval_v3_roles(role_name text,prior jsonb) on commit drop;
create temporary table rf193_approval_v3_create(added boolean) on commit drop;
do $borrow$
declare name text; prior jsonb; schema_owner text;
begin
 select pg_catalog.pg_get_userbyid(nspowner) into strict schema_owner from pg_catalog.pg_namespace where nspname='shareholder_register_filing';
 for name in select distinct value from unnest(array['shareholder_register_filing_store_owner',schema_owner]) value loop
  if not pg_catalog.pg_has_role(current_user,name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into prior
    from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(name) and m.member=current_user::regrole and m.grantor=m.member;
   insert into pg_temp.rf193_approval_v3_roles values(name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',name,current_user,current_user);
  end if;
 end loop;
 insert into pg_temp.rf193_approval_v3_create select not pg_catalog.has_schema_privilege('shareholder_register_filing_store_owner','shareholder_register_filing','CREATE');
 if (select added from pg_temp.rf193_approval_v3_create) then
  execute pg_catalog.format('set local role %I',schema_owner);
  grant create on schema shareholder_register_filing to shareholder_register_filing_store_owner;
  reset role;
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;

-- Closed grammar only: annotations are fixed by RF, never taken from a payload.
-- Keep json numeric lexemes: jsonb normalizes exponent floats into integers.
-- No annual economics/readiness calculation or producer-origin authority here.
create or replace function shareholder_register_filing.assert_retained_annual_readiness_v2_shape_internal_v1(p_text text)
returns void language plpgsql immutable security invoker set search_path='' as $shape$
declare records constant jsonb:='{"CompanyId":{"value":"str"},"IncomeYear":{"value":"int"},"PreviewId":{"value":"str"},"Rf1086AnnualDocumentStatus":{"document_id":"str","linked_to":"str","status":"str"},"Rf1086AnnualReadinessInputs":{"accepted_bank_warning_count":"int","authority_to_submit_confirmed":"optional:bool","bank_balance_confirmed":"optional:bool","bank_transaction_count":"int","company_id":"CompanyId","documents":"array:Rf1086AnnualDocumentStatus","evidence_sha256":"mapping:str","has_unpaid_items":"optional:bool","income_year":"IncomeYear","interview_source_id":"optional:str","opening_bank_snapshot_ids":"array:str","opening_snapshot_ids":"array:str","period_lock_ids":"array:str","unmatched_bank_count":"int"},"Rf1086AnnualReadinessProofV2":{"accepted_warning_codes":"array:str","annual_inputs":"Rf1086AnnualReadinessInputs","issues":"array:Rf1086ReadinessIssue","not_evaluated":"array:str","proof_sha256":"str","readiness_status":"literal:ready,warning,blocked","required_warning_codes":"array:str","schema_version":"literal:rf1086-annual-readiness-v2","source":"Rf1086SourceReadinessProofV2"},"Rf1086ReadinessIssue":{"code":"str","level":"str","message":"str"},"Rf1086SourceReadinessEvidenceV2":{"case_sha256":"str","company_id":"CompanyId","freshness":"Rf1086YearSourceFreshnessV2","income_year":"IncomeYear","preview_id":"PreviewId","preview_payload_sha256":"str","rendering_profile":"str","schema_version":"literal:rf1086-source-readiness-evidence-v2","source_id":"Rf1086YearSourceId","source_sha256":"str","source_version":"int"},"Rf1086SourceReadinessProofV2":{"evidence":"Rf1086SourceReadinessEvidenceV2","issues":"array:Rf1086ReadinessIssue","not_evaluated":"array:str","proof_sha256":"str","readiness_status":"literal:ready,blocked","schema_version":"literal:rf1086-source-readiness-v2"},"Rf1086YearSourceFreshnessV2":{"company_identity_sha256":"str","documents_sha256":"str","governance_chain_enumeration_sha256":"str","governance_original_enumeration_sha256":"str","governance_projection_sha256":"str","governance_receipts_sha256":"str","source_id":"Rf1086YearSourceId","source_sha256":"str"},"Rf1086YearSourceId":{"value":"str"}}'::jsonb;
 raw json; work json[]; kinds text[]; value json; expected text; rules jsonb; item record;
begin
 if p_text is null or not(p_text is json object with unique keys)
 then raise exception 'rf1086_source_annual_evidence_invalid'; end if;
 raw:=p_text::json;
 if (select count(*) from pg_catalog.json_object_keys(raw))<>2
  or not(raw::jsonb ?& array['codec','proof']) or raw->>'codec' is distinct from 'rf1086-annual-readiness-v2'
 then raise exception 'rf1086_source_annual_evidence_invalid'; end if;
 work:=array[raw->'proof']; kinds:=array['Rf1086AnnualReadinessProofV2'];
 while pg_catalog.cardinality(work)>0 loop
  value:=work[1]; work:=work[2:]; expected:=kinds[1]; kinds:=kinds[2:];
  if expected like 'optional:%' then
   if pg_catalog.json_typeof(value)='null' then continue; end if;
   expected:=pg_catalog.substr(expected,10);
  end if;
  if expected in ('str','bool','int') then
   if (expected='str' and pg_catalog.json_typeof(value) is distinct from 'string')
    or (expected='bool' and pg_catalog.json_typeof(value) is distinct from 'boolean')
    or (expected='int' and (pg_catalog.json_typeof(value) is distinct from 'number' or (value#>>'{}') !~ '^-?(0|[1-9][0-9]*)$'))
   then raise exception 'rf1086_source_annual_evidence_invalid'; end if;
  elsif expected like 'literal:%' then
   if pg_catalog.json_typeof(value) is distinct from 'string'
    or not((value#>>'{}')=any(pg_catalog.string_to_array(pg_catalog.substr(expected,9),',')))
   then raise exception 'rf1086_source_annual_evidence_invalid'; end if;
  elsif expected like 'array:%' then
   if pg_catalog.json_typeof(value) is distinct from 'array'
   then raise exception 'rf1086_source_annual_evidence_invalid'; end if;
   for item in select v from pg_catalog.json_array_elements(value) v loop
    work:=pg_catalog.array_append(work,item.v); kinds:=pg_catalog.array_append(kinds,pg_catalog.substr(expected,7));
   end loop;
  elsif expected='mapping:str' then
   if pg_catalog.json_typeof(value) is distinct from 'object'
    or (select count(*) from pg_catalog.json_object_keys(value))<>1
    or not(value::jsonb ? 'mapping') or pg_catalog.json_typeof(value->'mapping') is distinct from 'object'
   then raise exception 'rf1086_source_annual_evidence_invalid'; end if;
   for item in select * from pg_catalog.json_each(value->'mapping') loop
    if pg_catalog.json_typeof(item.value) is distinct from 'string'
    then raise exception 'rf1086_source_annual_evidence_invalid'; end if;
   end loop;
  else
   rules:=records->expected;
   if rules is null or pg_catalog.json_typeof(value) is distinct from 'object'
    or (select count(*) from pg_catalog.json_object_keys(value))<>2
    or not(value::jsonb ?& array['record','fields']) or value->>'record' is distinct from expected
    or pg_catalog.json_typeof(value->'fields') is distinct from 'object'
    or (select count(*) from pg_catalog.json_object_keys(value->'fields'))<>(select count(*) from pg_catalog.jsonb_object_keys(rules))
    or not((value->'fields')::jsonb ?& array(select pg_catalog.jsonb_object_keys(rules)))
   then raise exception 'rf1086_source_annual_evidence_invalid'; end if;
   for item in select * from pg_catalog.jsonb_each_text(rules) loop
    work:=pg_catalog.array_append(work,value->'fields'->item.key); kinds:=pg_catalog.array_append(kinds,item.value);
   end loop;
  end if;
 end loop;
exception when invalid_text_representation or invalid_parameter_value or numeric_value_out_of_range then
 raise exception 'rf1086_source_annual_evidence_invalid';
end; $shape$;

-- Copy owned persistence versions without altering any released body/OID/ACL.
-- Annual policy is rebuilt from actual owner inputs by the held RF backend port;
-- these closed SQL contracts bind structure and repeat authorization/source facts.
do $versions$
declare old pg_catalog.pg_proc%rowtype; target text; definition text; body text;
 anchor text; replacement text;
begin
 select * into strict old from pg_catalog.pg_proc where oid='shareholder_register_filing.source_annual_binding_internal_v1(uuid,text)'::regprocedure;
 if old.proowner<>current_user::regrole or not old.prosecdef or old.provolatile<>'v'
  or old.proconfig is distinct from array['search_path=""']::text[]
  or pg_catalog.md5(old.prosrc)<>'80458681439b7113a8929f18a7e302e1'
  or old.prolang<>(select oid from pg_catalog.pg_language where lanname='plpgsql')
 then raise exception 'rf1086_approval_v3_definition_drift'; end if;
 body:=old.prosrc;
 anchor:='warnings jsonb;';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_approval_v3_definition_drift'; end if;
 body:=replace(body,anchor,'warnings jsonb; v shareholder_register_filing.year_source_versions%rowtype; source_fields jsonb;');
 anchor:=' if p_text is null then raise exception ''rf1086_source_annual_evidence_invalid''; end if;';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_approval_v3_definition_drift'; end if;
 replacement:=E' select * into v from shareholder_register_filing.year_source_versions where id=s.source_id;\n'
  ||E' if v.id is null or v.snapshot_text::jsonb->>''codec'' is distinct from ''rf1086-year-source-v2''\n'
  ||E'  or not exists(select 1 from shareholder_register_filing.year_source_heads h where h.company_id=s.company_id\n'
  ||E'   and h.income_year=s.income_year and h.source_id=s.source_id and h.source_sha256=s.source_sha256 and h.version=v.version)\n'
  ||E' then raise exception ''rf1086_source_preview_stale''; end if;\n'
  ||E' perform shareholder_register_filing.assert_year_source_v2_internal_v1(s.company_id,s.income_year,v.snapshot_text);\n'
  ||E' source_fields:=v.snapshot_text::jsonb#>''{snapshot,fields}'';\n'
  ||E' perform shareholder_register_filing.assert_retained_annual_readiness_v2_shape_internal_v1(p_text);\n'||anchor;
 body:=replace(body,anchor,replacement);
 if position('''rf1086-annual-readiness-v1''' in body)=0 or position('''Rf1086AnnualReadinessProof''' in body)=0
 then raise exception 'rf1086_approval_v3_definition_drift'; end if;
 body:=replace(replace(replace(body,'''rf1086-annual-readiness-v1''','''rf1086-annual-readiness-v2'''),
  '''Rf1086AnnualReadinessProof''','''Rf1086AnnualReadinessProofV2'''),
  '''rf1086-annual-readiness-binding-v1''','''rf1086-annual-readiness-binding-v2''');
 anchor:='  or proof->''not_evaluated'' is distinct from';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_approval_v3_definition_drift'; end if;
 replacement:=E'  or raw#>>''{proof,fields,source,record}'' is distinct from ''Rf1086SourceReadinessProofV2''\n'
  ||E'  or proof#>>''{source,fields,schema_version}'' is distinct from ''rf1086-source-readiness-v2''\n'
  ||E'  or pg_catalog.jsonb_typeof(proof#>''{source,fields}'') is distinct from ''object''\n'
  ||E'  or (select count(*) from pg_catalog.jsonb_object_keys(proof#>''{source,fields}''))<>6\n'
  ||E'  or raw#>>''{proof,fields,source,fields,evidence,record}'' is distinct from ''Rf1086SourceReadinessEvidenceV2''\n'
  ||E'  or pg_catalog.jsonb_typeof(evidence) is distinct from ''object''\n'
  ||E'  or (select count(*) from pg_catalog.jsonb_object_keys(evidence))<>11\n'
  ||E'  or evidence->>''schema_version'' is distinct from ''rf1086-source-readiness-evidence-v2''\n'
  ||E'  or evidence#>''{source_version}'' is distinct from pg_catalog.to_jsonb(v.version)\n'
  ||E'  or evidence->>''case_sha256'' is distinct from s.case_sha256\n'
  ||E'  or evidence->>''rendering_profile'' is distinct from s.profile\n'
  ||E'  or evidence->''freshness'' is distinct from source_fields->''freshness''\n'
  ||E'  or raw#>>''{proof,fields,annual_inputs,record}'' is distinct from ''Rf1086AnnualReadinessInputs''\n'
  ||E'  or pg_catalog.jsonb_typeof(inputs) is distinct from ''object''\n'
  ||E'  or (select count(*) from pg_catalog.jsonb_object_keys(inputs))<>14\n'||anchor;
 body:=replace(body,anchor,replacement);
 definition:=pg_catalog.pg_get_functiondef(old.oid);
 if length(definition)-length(replace(definition,old.prosrc,''))<>length(old.prosrc) then raise exception 'rf1086_approval_v3_definition_drift'; end if;
 definition:=replace(replace(definition,old.prosrc,body),'source_annual_binding_internal_v1(','source_annual_binding_internal_v2(');
 execute definition;

 select * into strict old from pg_catalog.pg_proc where oid='shareholder_register_filing.source_approval_context_internal_v2(uuid,uuid,text,text)'::regprocedure;
 if old.proowner<>current_user::regrole or not old.prosecdef or old.provolatile<>'v'
  or old.proconfig is distinct from array['search_path=""']::text[]
  or pg_catalog.md5(old.prosrc)<>'59e1ae0481a1b280b62baf6bb315fc88'
  or old.prolang<>(select oid from pg_catalog.pg_language where lanname='plpgsql')
  or position('source_annual_binding_internal_v1(p_preview,p_annual_text)' in old.prosrc)=0
  or position('''rf1086-source-review-v2''' in old.prosrc)=0
 then raise exception 'rf1086_approval_v3_definition_drift'; end if;
 body:=replace(replace(old.prosrc,'source_annual_binding_internal_v1(p_preview,p_annual_text)',
  'source_annual_binding_internal_v2(p_preview,p_annual_text)'),'''rf1086-source-review-v2''','''rf1086-source-review-v3''');
 -- Always consume current Gov/RF source proof, including an existing bridge.
 anchor:=' perform shareholder_register_filing.bridge_source_preview_v1(p_preview,s.payload_sha256,p_subject);';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_approval_v3_definition_drift'; end if;
 body:=replace(body,anchor,E' perform shareholder_register_filing.assert_source_register_observations_active_internal_v1(s.company_id,s.income_year,s.source_id,s.source_sha256);\n'||anchor);
 definition:=pg_catalog.pg_get_functiondef(old.oid);
 if length(definition)-length(replace(definition,old.prosrc,''))<>length(old.prosrc) then raise exception 'rf1086_approval_v3_definition_drift'; end if;
 execute replace(replace(definition,old.prosrc,body),'source_approval_context_internal_v2(','source_approval_context_internal_v3(');

 select * into strict old from pg_catalog.pg_proc where oid='shareholder_register_filing.append_source_approval_v2(uuid,uuid,text,text,text,text)'::regprocedure;
 if old.proowner<>current_user::regrole or not old.prosecdef or old.provolatile<>'v'
  or old.proconfig is distinct from array['search_path=""']::text[]
  or pg_catalog.md5(old.prosrc)<>'cc7329283bd9bed92d4c0524814a40a6'
  or old.prolang<>(select oid from pg_catalog.pg_language where lanname='plpgsql')
  or position('-- rf193-withdrawal-source-admission-v1' in old.prosrc)=0
  or position('source_approval_context_internal_v2(' in old.prosrc)=0
  or position('''production-source-approval-v2''' in old.prosrc)=0
 then raise exception 'rf1086_approval_v3_definition_drift'; end if;
 body:=replace(replace(old.prosrc,'source_approval_context_internal_v2(',
  'source_approval_context_internal_v3('),'''production-source-approval-v2''','''production-source-approval-v3''');
 anchor:='''source'',pg_catalog.jsonb_build_object(''id'',s.source_id';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_approval_v3_definition_drift'; end if;
 body:=replace(body,anchor,'''source'',pg_catalog.jsonb_build_object(''codec'',''rf1086-year-source-v2'',''id'',s.source_id');
 anchor:='''governanceEnumerationSha256'',freshness->>''governance_enumeration_sha256''';
 if length(body)-length(replace(body,anchor,''))<>length(anchor) then raise exception 'rf1086_approval_v3_definition_drift'; end if;
 body:=replace(body,anchor,'''governanceOriginalEnumerationSha256'',freshness->>''governance_original_enumeration_sha256'','||E'\n'
  ||'   ''governanceChainEnumerationSha256'',freshness->>''governance_chain_enumeration_sha256'','||E'\n'
  ||'   ''governanceProjectionSha256'',freshness->>''governance_projection_sha256''');
 definition:=pg_catalog.pg_get_functiondef(old.oid);
 if length(definition)-length(replace(definition,old.prosrc,''))<>length(old.prosrc) then raise exception 'rf1086_approval_v3_definition_drift'; end if;
 execute replace(replace(definition,old.prosrc,body),'append_source_approval_v2(','append_source_approval_v3(');
end; $versions$;

create or replace function shareholder_register_filing.read_source_approval_context_v3(
 p_preview uuid,p_entitlement uuid,p_annual_text text,p_subject text)
returns jsonb language sql volatile security definer set search_path='' as $fn$
 select shareholder_register_filing.source_approval_context_internal_v3(p_preview,p_entitlement,p_annual_text,p_subject)-'reviewText';
$fn$;

do $closed$
declare routine regprocedure; grantee_name text;
begin
 for routine in select unnest(array[
  'shareholder_register_filing.assert_retained_annual_readiness_v2_shape_internal_v1(text)'::regprocedure,
  'shareholder_register_filing.source_annual_binding_internal_v2(uuid,text)'::regprocedure,
  'shareholder_register_filing.source_approval_context_internal_v3(uuid,uuid,text,text)'::regprocedure,
  'shareholder_register_filing.read_source_approval_context_v3(uuid,uuid,text,text)'::regprocedure,
  'shareholder_register_filing.append_source_approval_v3(uuid,uuid,text,text,text,text)'::regprocedure]) loop
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
 if (select added from pg_temp.rf193_approval_v3_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='shareholder_register_filing';
  execute pg_catalog.format('set local role %I',schema_owner);
  revoke create on schema shareholder_register_filing from shareholder_register_filing_store_owner;
  reset role;
 end if;
 for item in select * from pg_temp.rf193_approval_v3_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',item.role_name,current_user,current_user);
  if item.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   item.role_name,current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
