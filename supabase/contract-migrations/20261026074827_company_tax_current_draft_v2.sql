-- Retained current-authority originals for server-owned preparation. No filing
-- approval, provider mutation or commercial entitlement is introduced.
-- Install compatible readers f31ca2681815505fe52e9c6385133d64d92905ac
-- before separate activation; keep that reader baseline on rollback.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
do $predecessor$ begin
 if pg_catalog.to_regprocedure('company_tax_filing.store_delivery_draft_v1(text,text,text)') is null
  or not exists(select 1 from pg_catalog.pg_proc p
   where p.oid=pg_catalog.to_regprocedure('company_tax_filing.store_delivery_draft_v1(text,text,text)')
    and p.prosecdef and p.proowner='company_tax_filing_store_owner'::regrole
    and pg_catalog.encode(extensions.digest(p.prosrc,'sha256'),'hex')='1cf2f0c5b0b3388c58697e461399bc07cfa1cd8a25995d09488fdaceed907aa4') then
  raise exception 'company_tax_current_draft_predecessor_changed';
 end if;
end; $predecessor$;
create temporary table tax_current_draft_authority(prior jsonb) on commit drop;
do $borrow$ declare p jsonb; begin
 if not pg_catalog.pg_has_role(current_user,'company_tax_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid='company_tax_filing_store_owner'::regrole
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.tax_current_draft_authority values(p);
  execute pg_catalog.format('grant company_tax_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role company_tax_filing_store_owner;

create function company_tax_filing.current_draft_writes_enabled_v2() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$
-- Reader-first activation is deliberately separate from expansion.
begin return false; end; $function$;

create function company_tax_filing.store_delivery_draft_record_v1(p_raw text,p_hash text,p_subject text,p_codec text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=company_tax_filing.assert_return_available_v1(p_subject);
 body jsonb; value jsonb; source jsonb; current_doc jsonb; company uuid; year integer; filing uuid; key text;
 prior company_tax_filing.delivery_drafts%rowtype;
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'company_tax_return_unavailable'; end if;
 if p_codec is null or p_codec not in ('company-tax-delivery-draft-v1','company-tax-delivery-draft-v2')
  or p_raw is null or pg_catalog.octet_length(p_raw) not between 1 and 33554432
  or p_hash is distinct from pg_catalog.encode(extensions.digest(p_raw,'sha256'),'hex') then raise exception 'company_tax_return_invalid_input'; end if;
 body:=p_raw::jsonb; value:=body->'draft'; source:=value#>'{envelope,source}';
 if body->>'version' is distinct from p_codec or value#>>'{prepared_by,kind}' is distinct from 'USER'
  or value#>>'{prepared_by,subject,value}' is distinct from actor::text then raise exception 'company_tax_return_invalid_input'; end if;
 company:=(source#>>'{company_id,value}')::uuid; year:=(source#>>'{income_year,value}')::integer;
 filing:=(value->>'filing_id')::uuid; key:=value#>>'{command_key,value}';
 if company is null or year is distinct from 2025 or filing is null or key is null then raise exception 'company_tax_return_invalid_input'; end if;
 if p_codec='company-tax-delivery-draft-v2' then
  current_doc:=value->'current_document';
  if pg_catalog.jsonb_typeof(current_doc) is distinct from 'object'
   or current_doc#>>'{response,organization_number}' is distinct from source->>'organization_number'
   or current_doc#>'{response,income_year}' is distinct from source->'income_year'
   or current_doc->>'document_reference' is distinct from value#>>'{envelope,current_document_reference}'
   or current_doc->>'schema_sha256' is distinct from value#>>'{envelope,schema_sha256}'
   or coalesce(current_doc#>>'{response,raw_base64}','')='' then raise exception 'company_tax_return_invalid_input'; end if;
 end if;
 if not public.company_access_is_accepted_owner_v1(company) then raise exception 'company_tax_return_not_found'; end if;
 perform public.company_archive_lock_company_v1(company);
 perform company_tax_filing.assert_return_available_v1(p_subject);
 if not public.company_access_is_accepted_owner_v1(company) then raise exception 'company_tax_return_not_found'; end if;
 if company_tax_filing.delivery_draft_writes_enabled_v1() is distinct from true
  or (p_codec='company-tax-delivery-draft-v2' and company_tax_filing.current_draft_writes_enabled_v2() is distinct from true)
  then raise exception 'company_tax_return_unavailable'; end if;
 if p_codec='company-tax-delivery-draft-v2' and public.company_access_has_fresh_mfa_v1() is distinct from true
  then raise exception 'company_tax_evidence_mfa_required'; end if;
 select * into prior from company_tax_filing.delivery_drafts d
  where d.company_id=company and d.income_year=year and d.prepared_by=actor and d.command_key=key;
 if prior.id is not null then
  if prior.canonical_json<>p_raw or prior.draft_sha256<>p_hash then
   if p_codec='company-tax-delivery-draft-v1' then raise exception 'company_tax_return_invalid_input'; end if;
   raise exception 'company_tax_delivery_draft_conflict';
  end if;
  return pg_catalog.to_jsonb(prior);
 end if;
 insert into company_tax_filing.delivery_drafts(id,company_id,income_year,prepared_by,command_key,canonical_json,draft_sha256)
  values(filing,company,year,actor,key,p_raw,p_hash) returning * into prior;
 return pg_catalog.to_jsonb(prior);
end; $function$;

create or replace function company_tax_filing.store_delivery_draft_v1(p_raw text,p_hash text,p_subject text)
returns jsonb language sql volatile security definer set search_path='' as $function$
 select company_tax_filing.store_delivery_draft_record_v1(p_raw,p_hash,p_subject,'company-tax-delivery-draft-v1');
$function$;
create function company_tax_filing.store_delivery_draft_v2(p_raw text,p_hash text,p_subject text)
returns jsonb language sql volatile security definer set search_path='' as $function$
 select company_tax_filing.store_delivery_draft_record_v1(p_raw,p_hash,p_subject,'company-tax-delivery-draft-v2');
$function$;
revoke all on function company_tax_filing.store_delivery_draft_record_v1(text,text,text,text),
 company_tax_filing.current_draft_writes_enabled_v2() from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
revoke all on function company_tax_filing.store_delivery_draft_v2(text,text,text) from public,anon,authenticated,service_role;
grant execute on function company_tax_filing.store_delivery_draft_v2(text,text,text) to company_tax_filing_workflow_executor;
reset role;
do $restore$ declare r record; begin
 for r in select * from pg_temp.tax_current_draft_authority loop
  execute pg_catalog.format('revoke company_tax_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant company_tax_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
    current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
