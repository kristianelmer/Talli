-- Private Preview only. One fictional 2025 company-year; all provider operations remain closed.
-- Apply manually to designated pkpyyxryfhfehrbhbynp after exact candidate gates.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='30s';
do $prestate$ begin
 if (select p.prosrc from pg_catalog.pg_proc p where p.oid='annual_accounts_filing.delivery_draft_writes_enabled_v1()'::regprocedure)
   is distinct from 'begin return false; end;'
  or (select pg_catalog.pg_get_userbyid(p.proowner) from pg_catalog.pg_proc p
      where p.oid='annual_accounts_filing.delivery_draft_writes_enabled_v1()'::regprocedure)
    is distinct from 'annual_accounts_filing_store_owner'
  or (select count(*) from annual_accounts_filing.delivery_drafts
      where company_id='53454096-3fb6-45a6-a9c8-35fa83824614'::uuid and income_year=2025)<>0
  or (select p.prosrc from pg_catalog.pg_proc p where p.oid='annual_accounts_filing.delivery_operations_enabled_v1()'::regprocedure)
    is distinct from 'begin return false; end;' then
  raise exception 'synthetic_accounts_prestate_changed'; end if;
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
create function annual_accounts_filing.synthetic_preview_draft_admission_v1() returns trigger
language plpgsql volatile security definer set search_path='' as $function$
declare body jsonb; corporate jsonb; ready jsonb; simulation jsonb; unsigned jsonb;
begin
 if pg_catalog.clock_timestamp()>='2026-10-30 18:00:00+00'::timestamptz
  or new.company_id is distinct from '53454096-3fb6-45a6-a9c8-35fa83824614'::uuid
  or new.income_year is distinct from 2025
  or (select count(*) from annual_accounts_filing.delivery_drafts d
      where d.company_id=new.company_id and d.income_year=new.income_year)<>0 then
  raise exception 'synthetic_accounts_draft_scope_closed'; end if;
 body:=new.canonical_json::jsonb;
 corporate:=body#>'{draft,source,owning_snapshots,corporate}';
 ready:=corporate->'readiness'; simulation:=corporate->'synthetic_signoff';
 unsigned:='{"annual_board_minutes":"e9751bd31ea0f01cadcfab06690d18f292400ceacebf2c6dbbbcc50da06c9866",'
   '"annual_general_meeting_minutes":"4b135a1af3fbe42d863ba0a60ea8a4c2a54e1b7eb9f967d573eb7b65ac362608"}'::jsonb;
 if (corporate-array['readiness','snapshot','synthetic_signoff']) is distinct from '{}'::jsonb
  or simulation->>'kind' is distinct from 'synthetic_accounts_signoff_v1'
  or simulation->>'companyId' is distinct from new.company_id::text
  or simulation->'incomeYear' is distinct from '2025'::jsonb
  or simulation->>'decisionId' is distinct from '81883db6-cf34-4140-be2e-e8c7e7070a65'
  or simulation->>'decisionSha256' is distinct from '8d6b6c12086eb4bb3c4adf5470630e1e81b92503a88d3997b2a67ba7999bceaf'
  or simulation->>'sourceSha256' is distinct from 'e9c9e448995b5d533a977a28eb085cb470432f231788e8fc87c158e17f49a93a'
  or simulation->'unsignedDocumentSha256' is distinct from unsigned
  or simulation->>'expiresAt' is distinct from '2026-10-30T18:00:00+00:00'
  or simulation->>'statement' is distinct from
   'Synthetic test sign-off only; originals are unsigned; no owner signed-copy attestation or finalization.'
  or ready->>'state' is distinct from 'facts_approved'
  or ready->'finalized' is distinct from 'false'::jsonb
  or ready->'annual_submission_ready' is distinct from 'false'::jsonb
  or ready->'finalization_id' is distinct from 'null'::jsonb
  or ready->'signed_artifact_hashes' is distinct from '{}'::jsonb
  or ready->'generated_artifact_hashes' is distinct from unsigned
  or ready->>'decision_hash' is distinct from simulation->>'decisionSha256'
  or ready->>'source_hash' is distinct from simulation->>'sourceSha256'
  or ready->'current_source_matches' is distinct from 'true'::jsonb
  or (select d.decision_hash from corporate_governance.annual_close_decisions d
      where d.id='81883db6-cf34-4140-be2e-e8c7e7070a65'::uuid and d.company_id=new.company_id
        and d.income_year=2025 and d.source_hash=simulation->>'sourceSha256')
    is distinct from simulation->>'decisionSha256'
  or (select pg_catalog.jsonb_object_agg(a.artifact_kind,a.content_sha256)
      from corporate_governance.annual_close_artifacts a
      where a.decision_id='81883db6-cf34-4140-be2e-e8c7e7070a65'::uuid and a.variant='unsigned')
    is distinct from unsigned
  or exists(select 1 from corporate_governance.annual_close_artifacts a
      where a.decision_id='81883db6-cf34-4140-be2e-e8c7e7070a65'::uuid and a.variant='signed_owner_attested')
  or exists(select 1 from corporate_governance.annual_close_finalizations f
      where f.decision_id='81883db6-cf34-4140-be2e-e8c7e7070a65'::uuid) then
  raise exception 'synthetic_accounts_draft_evidence_changed'; end if;
 return new;
end; $function$;
revoke all on function annual_accounts_filing.synthetic_preview_draft_admission_v1()
 from public,anon,authenticated,service_role,annual_accounts_filing_workflow_executor;
set local role annual_accounts_filing_store_owner;
create or replace function annual_accounts_filing.delivery_draft_writes_enabled_v1() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$
begin return pg_catalog.clock_timestamp()<'2026-10-30 18:00:00+00'::timestamptz; end; $function$;
reset role;
create trigger accounts_synthetic_preview_draft_admission before insert on annual_accounts_filing.delivery_drafts
 for each row execute function annual_accounts_filing.synthetic_preview_draft_admission_v1();
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
