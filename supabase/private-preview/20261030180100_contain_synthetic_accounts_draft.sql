-- Restore reader-first Accounts write closure; preserve exact drafts and archives.
-- Apply only after verifying the installed finite marker and trigger hashes.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='30s';
do $prestate$ begin
 if pg_catalog.to_regprocedure('annual_accounts_filing.synthetic_preview_draft_admission_v1()') is null
  or not exists(select 1 from pg_catalog.pg_trigger
      where tgrelid='annual_accounts_filing.delivery_drafts'::regclass
       and tgname='accounts_synthetic_preview_draft_admission' and tgenabled='O') then
  raise exception 'synthetic_accounts_containment_prestate_changed'; end if;
end; $prestate$;
create temporary table synthetic_accounts_prior_authority(prior jsonb) on commit drop;
do $borrow$ declare prior jsonb; begin
 if not pg_catalog.pg_has_role(current_user,'annual_accounts_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into prior
   from pg_catalog.pg_auth_members m where m.roleid='annual_accounts_filing_store_owner'::regrole
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.synthetic_accounts_prior_authority values(prior);
  execute pg_catalog.format('grant annual_accounts_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role annual_accounts_filing_store_owner;
create or replace function annual_accounts_filing.delivery_draft_writes_enabled_v1() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$begin return false; end;$function$;
reset role;
drop trigger accounts_synthetic_preview_draft_admission on annual_accounts_filing.delivery_drafts;
drop function annual_accounts_filing.synthetic_preview_draft_admission_v1();
do $restore$ declare r record; begin
 for r in select * from pg_temp.synthetic_accounts_prior_authority loop
  execute pg_catalog.format('revoke annual_accounts_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant annual_accounts_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
    current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
