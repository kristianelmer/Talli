-- Review-read rollback never removes unconditional downstream guards or evidence.
-- Retained rows refuse a predecessor rollback. Empty schemas retain the inert
-- table/functions; full disposable topology teardown remains separately owned.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_withdrawal_review_role(prior jsonb) on commit drop;
do $borrow$
declare prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into prior from pg_catalog.pg_auth_members m
   where m.roleid=(select oid from pg_catalog.pg_roles where rolname='shareholder_register_filing_store_owner')
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.rf193_withdrawal_review_role values(prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;
-- FORCE RLS would hide retained rows without an actor. Owner-only suspension and
-- the count share this transaction; any refusal rolls back the suspension too.
alter table shareholder_register_filing.register_observation_withdrawals no force row level security;
do $retained$
begin
 if exists(select 1 from shareholder_register_filing.register_observation_withdrawals)
 then raise exception 'rf1086_retained_withdrawals_block_rollback'; end if;
end; $retained$;
alter table shareholder_register_filing.register_observation_withdrawals force row level security;
revoke all on function shareholder_register_filing.append_register_observation_withdrawal_v1(uuid,integer,uuid,integer,text,text,text)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor,corporate_governance_workflow_executor;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_withdrawal_review_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
   current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
