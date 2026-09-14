"""Real six-family Tax cutover, contract, rollback and re-cutover on a disposable DB."""
import json
import os
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
import pytest

pytestmark = pytest.mark.company_tax_database
ROOT = Path(__file__).resolve().parents[3]
fixture = json.loads((ROOT/'architecture/evidence/issues/152/legacy-characterization.json').read_text())
case = next(c for c in fixture['evidenceCases'] if c['id']=='synthetic-completed-pending-feedback')
payload = case['output']['value']
company = payload['authorityRun']['company_id']
owner = payload['authorityRun']['recorded_by']
families = ('filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs')

def snapshot(db):
 return {f:db.execute(f"select coalesce(jsonb_agg(to_jsonb(r) order by id),'[]'::jsonb) from public.{f} r").fetchone()[0] for f in families}

def environment_snapshot(db):
 return db.execute("""select jsonb_build_object(
 'memberships',(select jsonb_agg(to_jsonb(m) order by roleid,member,grantor) from pg_auth_members m),
 'schemas',(select jsonb_agg(jsonb_build_object('name',nspname,'owner',nspowner,'acl',nspacl) order by nspname) from pg_namespace where nspname in ('backend_system','company_tax_filing','shareholder_register_filing')),
 'openingAcl',(select relacl from pg_class where oid='shareholder_register_filing.opening_balance_setups'::regclass),
 'archiveGenerations',(select jsonb_agg(to_jsonb(g) order by company_id,income_year) from public.company_archive_source_generations g),
 'audit',(select jsonb_agg(to_jsonb(a) order by id) from public.audit_events a),
 'legacyRpc',pg_get_functiondef(to_regprocedure('public.import_company_tax_tt02_evidence(jsonb)')))""").fetchone()[0]


@pytest.mark.parametrize('scenario', ['normal','set-only','changed-rpc','changed-trigger','missing-trigger','quarantine'])
def test_filing_migration_lifecycle(scenario):
    url = os.environ.get('DATABASE_URL')
    assert url, 'DATABASE_URL must identify the owned disposable database'
    assert conninfo_to_dict(url).get('host') in ('localhost','127.0.0.1','::1')
    checks = []
    def check(label, value):
        assert value, label
        checks.append(label)
    with psycopg.connect(url,autocommit=True) as db:
        db.execute('begin')
        try:
            assert db.execute("select to_regclass('backend_system.company_tax_return_migration_state') is null").fetchone()[0], 'Run before the explicitly ordered filing expansion'
            db.execute('insert into auth.users(id) values(%s)',(owner,))
            db.execute("insert into public.companies(id,org_number,name,entity_type,created_by) values(%s,%s,'Synthetic Tax152 expansion','AS',%s)",(company,case['input']['expectedCompanyOrgNumber'],owner))
            db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',now())",(company,owner))
            db.execute("select set_config('request.jwt.claims',%s,true)",(json.dumps({'sub':owner,'role':'authenticated','aal':'aal2'}),))
            db.execute('set local role authenticated')
            db.execute('select public.import_company_tax_tt02_evidence(%s)',(Jsonb(payload),))
            for index,(label,obligation) in enumerate((('skattemelding for AS','skattemelding'),('årsregnskap','aarsregnskap'))):
             preview=f'00000000-0000-0000-0001-{index:012d}'
             db.execute("insert into public.filing_previews(id,company_id,income_year,filing,status,preview,created_by) values(%s,%s,2025,%s,'ready','Synthetic preview',%s)",(preview,company,label,owner))
             db.execute("insert into public.filing_overrides(preview_id,company_id,income_year,filing,field_target,old_value,new_value,reason,risk_level,owner_confirmed_by,owner_confirmed_at,created_by) values(%s,%s,2025,%s,'synthetic','old','new','Synthetic reason','advisory',%s,now(),%s)",(preview,company,label,owner,owner))
             db.execute("insert into public.filing_review_comments(preview_id,company_id,target,severity,body,created_by) values(%s,%s,'rf1086_preview','advisory','Synthetic comment',%s)",(preview,company,owner))
             db.execute("insert into public.authority_permissions(company_id,obligation,submitter_user_id,confirmed_by) values(%s,%s,%s,%s)",(company,obligation,owner,owner))
             if index==1:
              db.execute("insert into public.authority_test_runs(company_id,obligation,environment,status,test_reference,recorded_by) values(%s,%s,'manual_evidence','pending','synthetic-accounts',%s)",(company,obligation,owner))
              db.execute("insert into public.filing_submissions(preview_id,company_id,income_year,filing,status,created_by) values(%s,%s,2025,%s,'ready',%s)",(preview,company,label,owner))
            db.execute('reset role')
            before=snapshot(db);environment=environment_snapshot(db)
            for name in ('20260914200000_company_tax_return_expand','20260914201000_company_tax_return_read_contracts','20260914202000_company_tax_return_import_contract','20260914203000_company_tax_return_preparation_contracts'):
             db.execute((ROOT/f'supabase/contract-migrations/{name}.sql').read_text().removesuffix('commit;\n').replace('begin;\n','',1))
            # Exercise a legacy write after expansion; cutover must capture its latest value.
            db.execute("update public.filing_previews set preview='Latest synthetic Tax preview' where filing='skattemelding for AS' and company_id=%s",(company,))
            before=snapshot(db);environment=environment_snapshot(db)
            cutover=ROOT/'supabase/contract-migrations/20260914012503_company_tax_return_cutover.sql'
            if scenario == 'set-only':
             db.execute('grant company_tax_filing_store_owner to postgres with inherit false,set true')
             environment=environment_snapshot(db)
            if scenario == 'changed-rpc':
             db.execute("create or replace function public.import_company_tax_tt02_evidence(p_payload jsonb) returns jsonb language plpgsql security definer set search_path='' as $$ begin raise exception 'changed writer'; end; $$")
            if scenario == 'changed-trigger':
             db.execute('alter table public.filing_previews disable trigger company_archive_track_filing_previews')
            if scenario == 'missing-trigger':
             db.execute('drop trigger company_archive_track_filing_previews on public.filing_previews')
            if scenario == 'quarantine':
             db.execute("insert into public.filing_previews(company_id,income_year,filing,status,preview,created_by) values(%s,2025,'unknown obligation','ready','Ambiguous source',%s)",(company,owner))
            errors = {'changed-rpc':'company_tax_return_legacy_writer_changed',
             'changed-trigger':'company_tax_return_source_trigger_changed',
             'missing-trigger':'company_tax_return_source_trigger_changed',
             'quarantine':'company_tax_return_cutover_quarantine'}
            if scenario in errors:
             source_before=snapshot(db)
             with pytest.raises(psycopg.Error) as caught:
              with db.transaction():
               db.execute(cutover.read_text().removesuffix('commit;\n').replace('begin;\n','',1))
             assert caught.value.diag.message_primary==errors[scenario]
             assert snapshot(db)==source_before
             assert db.execute('select phase from backend_system.company_tax_return_migration_state').fetchone()[0]=='expanded'
             return
            db.execute(cutover.read_text().removesuffix('commit;\n').replace('begin;\n','',1))
            check('cutover activated',db.execute('select phase from backend_system.company_tax_return_migration_state').fetchone()[0]=='cutover')
            for f in families:
             tax=[r for r in before[f] if r.get('filing')=='skattemelding for AS' or r.get('obligation')=='skattemelding' or (f=='filing_review_comments' and r['preview_id']=='00000000-0000-0000-0001-000000000000')]
             actual=db.execute(f"select coalesce(jsonb_agg(to_jsonb(t) order by id),'[]'::jsonb) from company_tax_filing.{f} t").fetchone()[0]
             check(f+' exact Tax transfer including latest legacy write',actual==tax and len(tax)==1)
             check(f+' exact Accounts preservation',snapshot(db)[f]==[r for r in before[f] if r not in tax])
            after=environment_snapshot(db)
            for key in ('memberships','schemas','openingAcl','archiveGenerations','audit'):
             check(key+' unchanged',after[key]==environment[key])
            db.execute('grant company_tax_filing_workflow_executor to postgres with inherit false,set true')
            import time
            claims={'sub':owner,'role':'authenticated','aal':'aal2','amr':[{'method':'totp','timestamp':int(time.time())}]}
            for key,value in [('request.jwt.claims',json.dumps(claims)),('talli.verified_actor_id',owner),('talli.verified_actor_claims',json.dumps(claims))]:
             db.execute('select set_config(%s,%s,true)',(key,value))
            db.execute('set local role company_tax_filing_workflow_executor')
            result=db.execute('select company_tax_filing.read_workspace_v1(%s,2025,%s)',(company,owner)).fetchone()[0]
            check('real owner read after cutover',len(result['previews'])==1)
            comment=db.execute("select company_tax_filing.add_review_comment_v1('00000000-0000-0000-0001-000000000000','advisory','Post-cutover comment',%s)",(owner,)).fetchone()[0]
            check('owned comment mutation works',comment['body']=='Post-cutover comment')
            db.execute('reset role')
            # Exercise receipt retention through the real Documents executor, with no
            # company membership supplying the filing SELECT policy.
            document='00000000-0000-0000-0002-000000000001'
            db.execute('grant company_tax_filing_store_owner to postgres with inherit false,set true')
            db.execute('set local role company_tax_filing_store_owner')
            db.execute('update company_tax_filing.filing_submissions set receipt_id=%s where company_id=%s',(document,company))
            db.execute('reset role')
            db.execute('grant documents_executor to postgres with inherit false,set true')
            db.execute("select set_config('request.jwt.claims','{}',true)")
            db.execute('set local role documents_executor')
            check('Documents sees owned Tax receipt reference',db.execute('select documents.has_evidence_references_v1(%s)',(document,)).fetchone()[0])
            db.execute('reset role')
            db.execute("select set_config('request.jwt.claims',%s,true)",(json.dumps(claims),))
            check('owned write advances archive generation',environment_snapshot(db)['archiveGenerations']!=environment['archiveGenerations'])
            for f in families:
             tax=next(r for r in before[f] if r.get('filing')=='skattemelding for AS' or r.get('obligation')=='skattemelding' or (f=='filing_review_comments' and r['preview_id']=='00000000-0000-0000-0001-000000000000'))
             db.execute('savepoint old_writer');db.execute('set local role authenticated')
             try:
              db.execute(f'insert into public.{f} select (jsonb_populate_record(null::public.{f},%s)).*',(Jsonb(tax),))
              raise AssertionError('old writer unexpectedly succeeded '+f)
             except psycopg.Error as error:
              assert error.sqlstate in ('23514','23503','42501') or error.diag.message_primary=='rf1086_legacy_writer_retired'
              db.execute('rollback to savepoint old_writer')
              checks.append(f+' old write rejected')
             db.execute('release savepoint old_writer')
            db.execute('reset role')
            # Contract rollback keeps the owned writer; full rollback restores latest writes.
            contract=ROOT/'supabase/contract-migrations/20260914012930_company_tax_return_contract.sql'
            db.execute(contract.read_text().removesuffix('commit;\n').replace('begin;\n','',1))
            check('contract removes old RPC',db.execute("select to_regprocedure('public.import_company_tax_tt02_evidence(jsonb)') is null").fetchone()[0])
            db.execute('drop table pg_temp.tax152_contract_roles')
            db.execute((ROOT/'supabase/rollback/20260914012930_company_tax_return_contract.sql').read_text().removesuffix('commit;\n').replace('begin;\n','',1))
            check('contract rollback keeps canonical Tax phase',db.execute('select phase from backend_system.company_tax_return_migration_state').fetchone()[0]=='cutover')
            db.execute('drop table pg_temp.tax152_contract_roles')
            db.execute(contract.read_text().removesuffix('commit;\n').replace('begin;\n','',1))
            rollback=ROOT/'supabase/rollback/20260914012503_company_tax_return_cutover.sql'
            generations=environment_snapshot(db)['archiveGenerations']
            # Temp relations are normally dropped by each artifact's COMMIT. This test
            # keeps a single outer rollback, so it explicitly drops only that artifact's temps.
            def drop_artifact_temps():
             for name in ('tax152_cutover_roles','tax152_trigger_modes','tax152_generations','tax152_archive_grant','tax152_current_rows','tax152_rollback_rows','tax152_rollback_siblings'):
              db.execute(f'drop table if exists pg_temp.{name}')
            drop_artifact_temps()
            db.execute(rollback.read_text().removesuffix('commit;\n').replace('begin;\n','',1))
            check('full rollback restores legacy phase',db.execute('select phase from backend_system.company_tax_return_migration_state').fetchone()[0]=='rolled_back')
            check('full rollback restores exact legacy RPC',environment_snapshot(db)['legacyRpc']==environment['legacyRpc'])
            check('latest owned comment restored',db.execute('select body from public.filing_review_comments where id=%s',(comment['id'],)).fetchone()[0]=='Post-cutover comment')
            check('rollback leaves archive generations unchanged',environment_snapshot(db)['archiveGenerations']==generations)
            db.execute('set local role company_tax_filing_workflow_executor')
            db.execute('savepoint unavailable')
            try:
             db.execute('select company_tax_filing.read_workspace_v1(%s,2025,%s)',(company,owner))
             raise AssertionError('rolled back source was available')
            except psycopg.Error as error:
             assert error.diag.message_primary=='company_tax_return_unavailable'
             db.execute('rollback to savepoint unavailable')
            db.execute('release savepoint unavailable');db.execute('reset role')
            checks.append('old backend unavailable after full rollback')
            drop_artifact_temps()
            db.execute(cutover.read_text().removesuffix('commit;\n').replace('begin;\n','',1))
            check('re-cutover carries latest owned comment',db.execute('select body from company_tax_filing.filing_review_comments where id=%s',(comment['id'],)).fetchone()[0]=='Post-cutover comment')
            check('re-cutover leaves archive generations unchanged',environment_snapshot(db)['archiveGenerations']==generations)
            assert len(checks)>=37
        finally:
            db.execute('rollback')
            assert db.execute("select to_regclass('backend_system.company_tax_return_migration_state') is null and not exists(select 1 from public.companies where id=%s)",(company,)).fetchone()[0]
