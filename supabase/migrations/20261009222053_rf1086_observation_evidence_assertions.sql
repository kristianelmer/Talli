-- Staged RF-owned evidence assertions. No consumer/runtime EXECUTE grant.
-- Identity/currentness/time only: not original bytes or economic equivalence.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_observation_evidence_role(prior jsonb) on commit drop;
do $borrow$
declare prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into prior from pg_catalog.pg_auth_members m
  where m.roleid=(select oid from pg_catalog.pg_roles where rolname='shareholder_register_filing_store_owner')
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.rf193_observation_evidence_role values(prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;

create or replace function shareholder_register_filing.assert_current_register_observation_v2(
 p_id uuid,p_company uuid,p_year integer,p_revision integer,p_sha text,p_not_after timestamptz,p_subject text
) returns void language plpgsql volatile security definer set search_path='' as $fn$
begin
 -- v1 preserves verified subject, accepted owner before/after the company lock,
 -- READ COMMITTED and exact active target. All RF lifecycle writers share it.
 perform shareholder_register_filing.assert_current_register_observation_v1(p_id,p_company,p_year,p_revision,p_sha,p_subject);
 if p_not_after is null or not pg_catalog.isfinite(p_not_after)
  or extract(year from p_not_after at time zone 'UTC') not between 1 and 9999
  or p_not_after>pg_catalog.clock_timestamp()
 then raise exception 'rf1086_register_observation_cutoff_invalid'; end if;
 if not exists(select 1 from shareholder_register_filing.register_observations
  where id=p_id and company_id=p_company and income_year=p_year and version=p_revision and fact_sha256=p_sha
   and confirmed_at<=p_not_after)
 then raise exception 'rf1086_register_observation_after_cutoff'; end if;
 -- The calling owner must mint this cutoff and use the identical instant for
 -- its new immutable event. This assertion cannot establish caller provenance.
end; $fn$;

create or replace function shareholder_register_filing.read_retained_register_observation_withdrawal_v1(
 p_id uuid,p_company uuid,p_year integer,p_observation uuid,p_revision integer,p_fact_sha text,
 p_withdrawal_sha text,p_not_after timestamptz,p_subject text
) returns text language plpgsql volatile security definer set search_path='' as $fn$
declare receipt shareholder_register_filing.register_observation_withdrawals%rowtype;
 captured_at timestamptz; canonical text;
begin
 if p_subject is null or nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'') is distinct from p_subject
 then raise exception 'rf1086_forbidden'; end if;
 perform shareholder_register_filing.lock_company_write_v1(p_company,false);
 if p_not_after is null or not pg_catalog.isfinite(p_not_after)
  or extract(year from p_not_after at time zone 'UTC') not between 1 and 9999
  or p_not_after>pg_catalog.clock_timestamp()
 then raise exception 'rf1086_register_observation_cutoff_invalid'; end if;
 select * into receipt from shareholder_register_filing.register_observation_withdrawals
  where id=p_id and company_id=p_company and income_year=p_year and observation_id=p_observation
   and observation_version=p_revision and observation_fact_sha256=p_fact_sha and withdrawal_sha256=p_withdrawal_sha;
 if not found then raise exception 'rf1086_register_withdrawal_evidence_mismatch'; end if;
 select confirmed_at into captured_at from shareholder_register_filing.register_observations
  where id=p_observation and company_id=p_company and income_year=p_year and version=p_revision and fact_sha256=p_fact_sha;
 if not found or receipt.withdrawn_at<captured_at
 then raise exception 'rf1086_register_withdrawal_storage_invalid'; end if;
 if receipt.withdrawn_at>p_not_after then raise exception 'rf1086_register_observation_after_cutoff'; end if;
 canonical:=shareholder_register_filing.withdrawal_receipt_text_internal_v1(receipt.id,receipt.company_id,
  receipt.income_year,receipt.actor_id,receipt.observation_id,receipt.observation_version,
  receipt.observation_fact_sha256,receipt.reason,receipt.withdrawn_at);
 if receipt.snapshot_text is distinct from canonical
  or receipt.request_sha256 is distinct from canonical::jsonb#>>'{withdrawal,request_sha256}'
  or receipt.withdrawal_sha256 is distinct from canonical::jsonb#>>'{withdrawal,withdrawal_sha256}'
 then raise exception 'rf1086_register_withdrawal_storage_invalid'; end if;
 -- Retained proof is historical: no active-head check or original-actor filter.
 -- Return canonical receipt bytes, never the actor-scoped idempotency key.
 return receipt.snapshot_text;
end; $fn$;
revoke all on function shareholder_register_filing.assert_current_register_observation_v2(uuid,uuid,integer,integer,text,timestamptz,text),
 shareholder_register_filing.read_retained_register_observation_withdrawal_v1(uuid,uuid,integer,uuid,integer,text,text,timestamptz,text)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor,
 corporate_governance_workflow_executor,corporate_governance_store_owner;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_observation_evidence_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
   current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
