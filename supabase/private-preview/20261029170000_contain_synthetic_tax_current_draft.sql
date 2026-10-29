-- #232 containment: preserve readers and all exact stored originals.
-- Only use after matching the installed finite activation's saved function hashes.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='30s';
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
-- Reader-first activation is deliberately separate from expansion.
begin return false; end; $function$;
create or replace function company_tax_filing.store_delivery_draft_v2(p_raw text,p_hash text,p_subject text)
returns jsonb language sql volatile security definer set search_path='' as $function$
 select company_tax_filing.store_delivery_draft_record_v1(p_raw,p_hash,p_subject,'company-tax-delivery-draft-v2');
$function$;
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
