-- #232: explicit finite activation for the one existing synthetic private fixture.
-- Apply only to owner-designated pkpyyxryfhfehrbhbynp after exact-candidate CI.
-- No persistent grants/memberships, tables, signing, submission or provider modes change.
-- Ordinary migrations and local topology rehearsals do not apply this artifact.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='30s';
do $preflight$
begin
 if pg_catalog.clock_timestamp()>='2026-10-30T18:00:00Z'::timestamptz then
  raise exception 'synthetic_tax_activation_expired';
 end if;
 if not exists(select 1 from public.companies c
  where c.id='53454096-3fb6-45a6-a9c8-35fa83824614'::uuid
   and c.org_number='992803750' and c.source='browser_test'
   and c.created_by='8ca24df3-12af-4be0-a534-4a26092c97bc'::uuid
   and c.name='Synthetic private Preview 714f7b19'
   and c.identity_confirmed_at is not null and c.identity_locked_at is not null) then
  raise exception 'synthetic_tax_fixture_changed';
 end if;
 if not pg_catalog.has_function_privilege('company_tax_filing_workflow_executor',
   'public.company_access_company_year_allows_consequential_v1(uuid,integer)','EXECUTE')
  or not pg_catalog.has_function_privilege('company_tax_filing_store_owner',
   'public.company_access_company_year_allows_consequential_v1(uuid,integer)','EXECUTE') then
  raise exception 'synthetic_tax_existing_eligibility_authority_missing';
 end if;
 if not exists(select 1 from pg_catalog.pg_proc p
  where p.oid='company_tax_filing.current_draft_writes_enabled_v2()'::regprocedure
   and p.proowner='company_tax_filing_store_owner'::regrole
   and pg_catalog.encode(extensions.digest(p.prosrc,'sha256'),'hex')='d95dd74167d5d388f9e389c2490723cf8e41bf2c04e41b03f38de0973ef67889')
  or not exists(select 1 from pg_catalog.pg_proc p
  where p.oid='company_tax_filing.store_delivery_draft_v2(text,text,text)'::regprocedure
   and p.proowner='company_tax_filing_store_owner'::regrole and p.prosecdef
   and pg_catalog.encode(extensions.digest(p.prosrc,'sha256'),'hex')='4be9c56ff505c25b25e9330b732b3d61aad11303fee22f4a94a5a44bead2d6c3') then
  raise exception 'synthetic_tax_predecessor_changed';
 end if;
end; $preflight$;
-- Borrow SET authority only for this transaction; restore its exact prior state.
create temporary table synthetic_tax_prior_authority(prior jsonb) on commit drop;
do $borrow$ declare prior jsonb; begin
 if not pg_catalog.pg_has_role(current_user,'company_tax_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into prior
  from pg_catalog.pg_auth_members m where m.roleid='company_tax_filing_store_owner'::regrole
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.synthetic_tax_prior_authority values(prior);
  execute pg_catalog.format('grant company_tax_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role company_tax_filing_store_owner;
create or replace function company_tax_filing.current_draft_writes_enabled_v2() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$
begin
 return pg_catalog.clock_timestamp()<'2026-10-30T18:00:00Z'::timestamptz
  and public.company_access_auth_uid_v1()='8ca24df3-12af-4be0-a534-4a26092c97bc'::uuid;
end; $function$;
create or replace function company_tax_filing.store_delivery_draft_v2(p_raw text,p_hash text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare value jsonb:=(p_raw::jsonb)->'draft';
begin
 if p_subject is distinct from '8ca24df3-12af-4be0-a534-4a26092c97bc'
  or value#>>'{prepared_by,subject,value}' is distinct from p_subject
  or value#>>'{envelope,source,company_id,value}' is distinct from '53454096-3fb6-45a6-a9c8-35fa83824614'
  or value#>'{envelope,source,income_year,value}' is distinct from '2025'::jsonb
  or value#>>'{envelope,source,organization_number}' is distinct from '992803750'
  or value#>>'{current_document,document_reference}' is distinct from 'synthetic-private-preview-992803750-2025-v1'
  or company_tax_filing.current_draft_writes_enabled_v2() is distinct from true then
  raise exception 'company_tax_return_unavailable';
 end if;
 perform company_tax_filing.lock_delivery_draft_archive_v1('53454096-3fb6-45a6-a9c8-35fa83824614'::uuid,2025,p_subject);
 if public.company_access_company_year_allows_consequential_v1('53454096-3fb6-45a6-a9c8-35fa83824614'::uuid,2025) is distinct from true then
  raise exception 'company_tax_return_unavailable';
 end if;
 return company_tax_filing.store_delivery_draft_record_v1(p_raw,p_hash,p_subject,'company-tax-delivery-draft-v2');
end; $function$;
reset role;
do $restore$ declare r record; begin
 for r in select * from pg_temp.synthetic_tax_prior_authority loop
  execute pg_catalog.format('revoke company_tax_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant company_tax_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
    current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
