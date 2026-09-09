"""RF cutover uses real migrations, transaction rollback and verified SQL roles."""
import json
import os
from pathlib import Path
import re
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

pytestmark = pytest.mark.authority_database
ROOT = Path(__file__).resolve().parents[3]
SCHEMA = 'shareholder_register_filing'
EXPAND = 'supabase/migrations/20260909190548_shareholder_register_filing_capability.sql'
CUTOVER = 'supabase/migrations/20260909190905_shareholder_register_filing_cutover.sql'
CONTRACT = 'supabase/contract-migrations/20260909190955_shareholder_register_filing_contract.sql'
ROLLBACK = 'supabase/rollback/20260909190548_shareholder_register_filing_capability.sql'


def migration(db, path):
    # The rehearsal owns one outer transaction, so every row, DDL and grant rolls back.
    db.execute('reset role')
    for (name,) in db.execute("select c.relname from pg_class c where c.relnamespace=pg_my_temp_schema() and c.relname like 'rf151_%' and c.relkind='r'").fetchall():
        db.execute(sql.SQL('drop table {}').format(sql.Identifier('pg_temp', name)))
    body = (ROOT / path).read_text()
    body = re.sub(r'(?m)^begin;\s*$', '', body, count=1)
    body = re.sub(r'commit;\s*$', '', body)
    try:
        db.execute(body)
    except psycopg.Error as error:
        error.add_note(path + ': ' + (error.diag.context or '').splitlines()[-1:][0] if error.diag.context else path)
        raise


@pytest.fixture
def db():
    url = os.environ.get('DATABASE_URL')
    assert url, 'DATABASE_URL must identify the owned disposable database'
    with psycopg.connect(url) as connection:
        try:
            if connection.execute("select to_regclass('shareholder_register_filing.migration_state')").fetchone()[0]:
                migration(connection, ROLLBACK)
            yield connection
        finally:
            connection.rollback()


def insert(db, relation, **row):
    db.execute(sql.SQL('insert into {} ({}) values ({})').format(
        sql.Identifier(*relation.split('.')), sql.SQL(',').join(map(sql.Identifier, row)),
        sql.SQL(',').join(sql.Placeholder() for _ in row)), tuple(row.values()))


def company(db, owner=None):
    owner = owner or uuid4()
    if not db.execute('select 1 from auth.users where id=%s', (owner,)).fetchone():
        insert(db, 'auth.users', id=owner, email=str(owner)+'@example.test')
    company_id = uuid4()
    insert(db, 'public.companies', id=company_id, org_number=str(100000000+company_id.int%899999999), name='RF migration fixture AS',
           entity_type='AS', address='Testveien 1', postal_code='0150', city='Oslo', status_text='aktiv', source='test', created_by=owner)
    insert(db, 'public.company_memberships', company_id=company_id, user_id=owner, role='owner', accepted_at=db.execute('select now()').fetchone()[0])
    return company_id, owner


def opening(db, company_id, owner):
    setup = uuid4()
    insert(db, 'public.opening_balance_setups', id=setup, company_id=company_id, income_year=2025,
           bank_balance=321, share_capital=30000, share_count=30, nominal_value=1000, created_by=owner)
    insert(db, 'public.opening_shareholders', id=uuid4(), setup_id=setup, company_id=company_id,
           shareholder_kind='norwegian_company', name='Fixture holder AS', org_number='930835978', share_count=30, created_by=owner)
    return setup


def preview(db, company_id, owner, setup):
    preview_id = uuid4()
    insert(db, 'public.filing_previews', id=preview_id, company_id=company_id, setup_id=setup, income_year=2025,
           filing='aksjonærregisteroppgaven', status='ready', preview='original immutable preview', hovedskjema_xml='<original/>',
           underskjema_xml=Jsonb({}), created_by=owner)
    return preview_id


def bind(db, actor, company_id, role='owner'):
    principal=db.execute('select current_user').fetchone()[0]
    db.execute(sql.SQL('grant shareholder_register_filing_executor to {} with inherit false,set true').format(sql.Identifier(principal)))
    now=db.execute('select floor(extract(epoch from now()))::bigint').fetchone()[0]
    claims=json.dumps({'sub':str(actor),'role':'authenticated','aal':'aal2','amr':[{'method':'totp','timestamp':now}]})
    db.execute("select set_config('request.jwt.claims',%s,true),set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true),set_config('talli.authorized_company_roles',%s,true)",
               (claims,str(actor),claims,json.dumps({str(company_id):role})))
    db.execute('set local role shareholder_register_filing_executor')


@pytest.mark.parametrize('phase', [EXPAND, CUTOVER, CONTRACT], ids=['expand','cutover','contract'])
@pytest.mark.parametrize('member_role', ['owner','reviewer','read_only'])
def test_review_comment_preserves_owner_reviewer_access_and_read_only_denial(db, phase, member_role):
    company_id, owner = company(db)
    actor = owner
    if member_role != 'owner':
        actor=uuid4()
        insert(db,'auth.users',id=actor,email=str(actor)+'@example.test')
        insert(db,'public.company_memberships',company_id=company_id,user_id=actor,role=member_role,accepted_at=db.execute('select now()').fetchone()[0])
    preview_id=preview(db,company_id,owner,opening(db,company_id,owner))
    migration(db,EXPAND)
    if phase != EXPAND: migration(db,CUTOVER)
    if phase == CONTRACT: migration(db,CONTRACT)
    bind(db,actor,company_id,member_role)
    if member_role == 'read_only':
        with pytest.raises(psycopg.Error):
            with db.transaction():
                db.execute('select shareholder_register_filing.add_review_comment_v1(%s,%s,%s)',(preview_id,'advisory','Original review boundary'))
        assert db.execute('select count(*) from shareholder_register_filing.filing_review_comments where preview_id=%s',(preview_id,)).fetchone()[0] == 0
    else:
        row=db.execute('select shareholder_register_filing.add_review_comment_v1(%s,%s,%s)',(preview_id,'advisory','Original review boundary')).fetchone()[0]
        assert row['created_by']==str(actor) and row['preview_id']==str(preview_id)
        assert db.execute('select count(*) from shareholder_register_filing.filing_review_comments where id=%s',(row['id'],)).fetchone()[0] == 1


@pytest.mark.parametrize('family',['filing_review_comments','filing_overrides','filing_submissions'])
def test_preview_quarantine_propagates_to_its_dependent_rows_without_abandoning_migration(db,family):
    company_id, owner=company(db)
    foreign_company,_=company(db,owner)
    preview_id=preview(db,company_id,owner,opening(db,foreign_company,owner))
    record_id=uuid4()
    row=dict(id=record_id,preview_id=preview_id,company_id=company_id,created_by=owner)
    if family=='filing_review_comments':row.update(target='rf1086_preview',severity='advisory',body='Historical original comment')
    elif family=='filing_overrides':row.update(income_year=2025,filing='aksjonærregisteroppgaven',field_target='fixture',old_value='before',new_value='after',reason='Original history',risk_level='warning',owner_confirmed_by=owner,owner_confirmed_at=db.execute('select now()').fetchone()[0])
    else:row.update(income_year=2025,filing='aksjonærregisteroppgaven',status='receipt_stored')
    insert(db,'public.'+family,**row)
    original=db.execute(sql.SQL('select to_jsonb(t) from {} t where id=%s').format(sql.Identifier('public',family)),(record_id,)).fetchone()[0]
    migration(db,EXPAND)
    assert db.execute('select original_row from shareholder_register_filing.migration_quarantine where family=%s and record_id=%s',(family,record_id)).fetchone()[0]==original
    assert db.execute(sql.SQL('select count(*) from {} where id=%s').format(sql.Identifier(SCHEMA,family)),(record_id,)).fetchone()[0]==0
    assert db.execute(sql.SQL('select to_jsonb(t) from {} t where id=%s').format(sql.Identifier('public',family)),(record_id,)).fetchone()[0]==original


def test_all_reverse_phases_preserve_retained_rows_and_replay(db):
    company_id,owner=company(db)
    setup=opening(db,company_id,owner)
    preview_id=preview(db,company_id,owner,setup)
    original=db.execute('select to_jsonb(p) from public.filing_previews p where id=%s',(preview_id,)).fetchone()[0]
    for path in (EXPAND,CUTOVER,CONTRACT,
                 'supabase/rollback/20260909190955_shareholder_register_filing_contract.sql',
                 'supabase/rollback/20260909190905_shareholder_register_filing_cutover.sql',
                 CUTOVER,CONTRACT,ROLLBACK):
        migration(db,path)
    assert db.execute("select to_regnamespace('shareholder_register_filing')").fetchone()[0] is None
    assert db.execute('select to_jsonb(p) from public.filing_previews p where id=%s',(preview_id,)).fetchone()[0]==original
    assert db.execute('select bank_balance from public.opening_balance_setups where id=%s',(setup,)).fetchone()[0]==321


def original_boundary(db):
    return db.execute("""select jsonb_build_object(
      'functions',(select jsonb_agg(jsonb_build_object('name',n.nspname||'.'||p.proname,'arguments',oidvectortypes(p.proargtypes),'body',pg_get_functiondef(p.oid),'owner',pg_get_userbyid(p.proowner),
        'acl',(select jsonb_agg(to_jsonb(a) order by grantor,grantee,privilege_type,is_grantable) from aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a)) order by n.nspname,p.proname,p.oid)
        from pg_proc p join pg_namespace n on n.oid=p.pronamespace where p.prokind='f' and (n.nspname='legacy_rf1086' or p.proname in
        ('approve_production_filing','begin_production_filing','append_production_filing_event','claim_production_feedback_reconciliation','release_production_feedback_reconciliation','append_production_feedback_reconciliation','record_production_feedback_artifact','record_opening_snapshot_legacy_v1','list_opening_snapshots_legacy_v1','read_rf_pilot_v1','lock_rf_pilot_v1','company_access_read_support_case','has_evidence_references_v1','rf1086_confirmation_forsendelse_id'))),
      'relations',(select jsonb_agg(jsonb_build_object('name',n.nspname||'.'||c.relname,'owner',pg_get_userbyid(c.relowner),'force',c.relforcerowsecurity,
        'columns',(select jsonb_agg(jsonb_build_array(a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,pg_get_expr(d.adbin,d.adrelid)) order by a.attnum) from pg_attribute a left join pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum where a.attrelid=c.oid and a.attnum>0 and not a.attisdropped),
        'constraints',(select jsonb_agg(jsonb_build_array(x.conname,x.contype,pg_get_constraintdef(x.oid),x.convalidated) order by x.conname) from pg_constraint x where x.conrelid=c.oid),
        'indexes',(select jsonb_agg(pg_get_indexdef(x.indexrelid) order by ic.relname) from pg_index x join pg_class ic on ic.oid=x.indexrelid where x.indrelid=c.oid),
        'triggers',(select jsonb_agg(jsonb_build_array(g.tgname,pg_get_triggerdef(g.oid),g.tgenabled) order by g.tgname) from pg_trigger g where g.tgrelid=c.oid and not g.tgisinternal),
        'acl',(select jsonb_agg(to_jsonb(a) order by grantor,grantee,privilege_type,is_grantable) from aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a),
        'policies',(select jsonb_agg(jsonb_build_object('name',p.polname,'roles',p.polroles,'command',p.polcmd,'permissive',p.polpermissive,'qual',pg_get_expr(p.polqual,p.polrelid),'check',pg_get_expr(p.polwithcheck,p.polrelid)) order by p.polname) from pg_policy p where p.polrelid=c.oid)) order by n.nspname,c.relname)
        from pg_class c join pg_namespace n on n.oid=c.relnamespace where (n.nspname='public' and c.relname in
          ('opening_balance_setups','opening_shareholders','filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs','filing_approval_snapshots','production_filing_submissions','production_filing_events','production_feedback_artifacts')) or (n.nspname='billing' and c.relname='production_pilot_entitlements')))
    """).fetchone()[0]


def test_full_rollback_restores_original_function_acl_table_policy_and_owners(db):
    original=original_boundary(db)
    for path in (EXPAND,CUTOVER,CONTRACT,ROLLBACK): migration(db,path)
    restored=original_boundary(db)
    for family in original:
        for before,after in zip(original[family],restored[family],strict=True):
            assert after==before, (family,before['name'],[field for field in before if before[field]!=after[field]])


@pytest.mark.parametrize('foreign_shares',[0,1],ids=['zero-shares','nonzero-shares'])
def test_quarantined_foreign_holder_keeps_opening_reads_unavailable_without_foreign_details(db,foreign_shares):
    company_id,owner=company(db)
    other,_=company(db,owner)  # The predecessor reader can see both companies.
    setup=opening(db,company_id,owner)
    foreign_holder=uuid4()
    insert(db,'public.opening_shareholders',id=foreign_holder,setup_id=setup,company_id=other,
           shareholder_kind='norwegian_company',name='Foreign row must stay concealed',org_number='930835978',share_count=foreign_shares,created_by=owner)
    migration(db,EXPAND)
    bind(db,owner,company_id)
    for name in ('read_opening_snapshots_v1','read_opening_shareholders_v1'):
        with pytest.raises(psycopg.Error,match='ledger_dependency_unavailable') as captured:
            with db.transaction():
                db.execute(sql.SQL('select * from shareholder_register_filing.{}(%s,%s,%s)').format(sql.Identifier(name)),(company_id,2025,str(owner)))
        assert str(foreign_holder) not in str(captured.value)
        assert 'Foreign row' not in str(captured.value)
        assert db.execute(sql.SQL('select * from shareholder_register_filing.{}(%s,%s,%s)').format(sql.Identifier(name)),(company_id,2024,str(owner))).fetchall()==[]


def test_composed_new_year_read_preserves_original_values_pagination_and_cursor(db):
    company_id,owner=company(db)
    other,_=company(db,owner)
    setup=opening(db,company_id,owner)
    setup2=opening(db,other,owner)
    originals=db.execute('select to_jsonb(o) from public.opening_balance_setups o where id=any(%s::uuid[]) order by created_at desc,id desc',([setup,setup2],)).fetchall()
    migration(db,EXPAND)
    bind(db,owner,company_id)
    db.execute('reset role')
    principal=db.execute('select current_user').fetchone()[0]
    db.execute(sql.SQL('grant ledger_workflow_executor to {} with inherit false,set true').format(sql.Identifier(principal)))
    db.execute('set local role ledger_workflow_executor')
    args=([company_id,other],None,1,str(owner).upper())
    first=db.execute('select * from backend_system.read_new_year_opening_snapshots_v1(%s,%s,%s,%s)',args).fetchone()
    assert len(first[0])==1 and first[2] and first[1]
    second=db.execute('select * from backend_system.read_new_year_opening_snapshots_v1(%s,%s,%s,%s)',(args[0],first[1],1,str(owner))).fetchone()
    assert len(second[0])==1 and not second[2]
    records=first[0]+second[0]
    assert [item['setupId'] for item in records]==[item[0]['id'] for item in originals]
    assert all(item['bankBalance']=='321' and item['shareCapital']=='30000' and item['nominalValue']=='1000' for item in records)
    assert all(len(item['shareholders'])==1 for item in records)


# Append to test_shareholder_register_filing_lifecycle.py; uses its existing
# db/migration/company/opening/preview/insert/bind helpers and imports.
# Synthetic retained rows only. The enclosing db fixture rolls back all row/DDL/ACL changes.
from datetime import timedelta

_RF_SUPPORT_KEYS = (
    'filing_approval_snapshots', 'production_filing_submissions',
    'production_filing_events', 'production_feedback_artifacts',
    'authority_permissions', 'authority_test_runs',
)


def _support_fixture_history(db):
    company_id, owner = company(db)
    now = db.execute('select now()').fetchone()[0]
    insert(db, 'public.support_operators', user_id=owner, role='admin', active=True)
    ids = {name: uuid4() for name in (*_RF_SUPPORT_KEYS, 'entitlement', 'document', 'sibling_permission', 'sibling_test')}
    # Existing test-only owner-role borrowing is contained in this test's outer rollback.
    principal = db.execute('select current_user').fetchone()[0]
    db.execute(sql.SQL('grant billing_store_owner,documents_store_owner to {} with inherit true,set true').format(sql.Identifier(principal)))
    preview_id = preview(db, company_id, owner, opening(db, company_id, owner))
    insert(db, 'billing.production_pilot_entitlements', id=ids['entitlement'], company_id=company_id,
           user_id=owner, income_year=2025, obligation='aksjonaerregisteroppgaven', case_profile='rf1086_no_activity_v1',
           status='pending', billing_exempt=True, system_user_external_reference='synthetic-retained-reference',
           starts_at=now-timedelta(days=2), expires_at=now-timedelta(days=1), evidence_reference='synthetic-support-history', approved_by=owner)
    insert(db, 'public.filing_approval_snapshots', id=ids['filing_approval_snapshots'], entitlement_id=ids['entitlement'],
           preview_id=preview_id, company_id=company_id, user_id=owner, income_year=2025,
           obligation='aksjonaerregisteroppgaven', case_profile='rf1086_no_activity_v1', adapter_version='rf1086-production-v1',
           payload_hash='a'*64, manifest_hash='b'*64, manifest=Jsonb({}), approved_by=owner)
    insert(db, 'public.production_filing_submissions', id=ids['production_filing_submissions'],
           approval_id=ids['filing_approval_snapshots'], entitlement_id=ids['entitlement'], company_id=company_id,
           user_id=owner, income_year=2025, obligation='aksjonaerregisteroppgaven', case_profile='rf1086_no_activity_v1',
           payload_hash='a'*64, adapter_version='rf1086-production-v1', environment='production', status='unknown', submitted_by=owner)
    insert(db, 'public.production_filing_events', id=ids['production_filing_events'],
           submission_id=ids['production_filing_submissions'], operation_name='post_hovedskjema',
           operation_state='unknown', failure_class='unknown', resulting_status='unknown')
    insert(db, 'public.documents', id=ids['document'], company_id=company_id, income_year=2025,
           document_type='authority_feedback', name='Synthetic retained support document',
           linked_to='production_filing_submission:'+str(ids['production_filing_submissions']), status='attached',
           storage_key=f'{company_id}/2025/{ids["document"]}.xml', created_by=owner)
    insert(db, 'public.production_feedback_artifacts', id=ids['production_feedback_artifacts'], company_id=company_id,
           submission_id=ids['production_filing_submissions'], document_id=ids['document'],
           authority_reference='synthetic-retained-document-reference', content_type='application/xml', byte_length=10,
           sha256='c'*64, classification='action_required')
    for name, obligation in [('authority_permissions', 'aksjonaerregisteroppgaven'), ('sibling_permission', 'skattemelding')]:
        insert(db, 'public.authority_permissions', id=ids[name], company_id=company_id, obligation=obligation,
               submitter_user_id=owner, confirmed_by=owner, production_enabled=False,
               confirmed_at=now-timedelta(hours=1), updated_at=now-timedelta(hours=1))
    for name, obligation, minutes in [('authority_test_runs', 'aksjonaerregisteroppgaven', 30), ('sibling_test', 'skattemelding', 5)]:
        insert(db, 'public.authority_test_runs', id=ids[name], company_id=company_id, obligation=obligation,
               recorded_by=owner, environment='manual_evidence', status='pending', test_reference='synthetic-'+name,
               recorded_at=now-timedelta(minutes=minutes))
    return company_id, owner, ids, now


def _support_case(db, company_id, operator, scopes, *, opened=True):
    db.execute('reset role')
    now = db.execute('select now()').fetchone()[0]
    case_id = uuid4()
    insert(db, 'public.support_access_grants', case_id=case_id, company_id=company_id,
           operator_user_id=operator, reason='service_recovery', scopes=scopes,
           starts_at=now-timedelta(minutes=1), expires_at=now+timedelta(hours=1), granted_by=operator)
    if opened:
        insert(db, 'public.support_case_openings', actor_id=operator, operation_id=uuid4(), case_id=case_id, company_id=company_id)
    return case_id


def _bind_support(db, actor, company_id):
    db.execute('reset role')
    bind(db, actor, company_id)
    db.execute('reset role')
    principal = db.execute('select current_user').fetchone()[0]
    db.execute(sql.SQL('grant company_access_executor to {} with inherit false,set true').format(sql.Identifier(principal)))
    db.execute('set local role company_access_executor')


def _contract_support_history(db):
    for path in (EXPAND, CUTOVER, CONTRACT):
        migration(db, path)


def test_support_reads_current_rf_permission_and_new_test_after_contract_without_duplicate_siblings(db):
    company_id, owner, ids, now = _support_fixture_history(db)
    case_id = _support_case(db, company_id, owner, ['authority'])
    _contract_support_history(db)
    bind(db, owner, company_id)
    permission = db.execute('select shareholder_register_filing.confirm_filing_permission_v1(%s,true)', (company_id,)).fetchone()[0]
    test = db.execute('select shareholder_register_filing.record_test_evidence_v1(%s,%s)', (company_id, Jsonb({
        'environment': 'manual_evidence', 'status': 'pending', 'test_reference': 'new-synthetic-post-contract',
        'feedback_summary': 'Synthetic pending result', 'receipt_reference': None, 'archive_reference': None, 'evidence_url': None, 'payload_hash': None,
    }))).fetchone()[0]
    _bind_support(db, owner, company_id)
    resources = db.execute('select resources from public.company_access_read_support_case(%s)', (case_id,)).fetchone()[0]
    permissions = resources['authority_permissions']
    assert {row['id'] for row in permissions} == {str(ids['authority_permissions']), str(ids['sibling_permission'])}
    assert len(permissions) == 2
    updated = next(row for row in permissions if row['id'] == str(ids['authority_permissions']))
    assert updated['production_enabled'] is True and updated['updated_at'] == permission['updated_at']
    sibling = next(row for row in permissions if row['id'] == str(ids['sibling_permission']))
    assert sibling['obligation'] == 'skattemelding' and sibling['production_enabled'] is False
    tests = resources['authority_test_runs']
    assert [row['id'] for row in tests] == [test['id'], str(ids['sibling_test']), str(ids['authority_test_runs'])]
    assert tests[0]['test_reference'] == 'new-synthetic-post-contract'
    assert all(set(row) == {'id','company_id','obligation','environment','status','test_reference','recorded_at'} for row in tests)
    db.execute('reset role')
    assert db.execute('select production_enabled from public.authority_permissions where id=%s', (ids['authority_permissions'],)).fetchone()[0] is False
    assert db.execute('select count(*) from public.authority_test_runs where id=%s', (test['id'],)).fetchone()[0] == 0


@pytest.mark.parametrize('purpose', ['billing', 'authority', 'production', 'documents'])
def test_support_purpose_still_binds_each_rf_array_when_operator_is_also_accepted_owner(db, purpose):
    company_id, owner, ids, _ = _support_fixture_history(db)
    case_id = _support_case(db, company_id, owner, [purpose])
    _contract_support_history(db)
    _bind_support(db, owner, company_id)
    resources = db.execute('select resources from public.company_access_read_support_case(%s)', (case_id,)).fetchone()[0]
    expected = {
        'authority': {'authority_permissions','authority_test_runs'},
        'production': {'filing_approval_snapshots','production_filing_submissions','production_filing_events'},
        'documents': {'production_feedback_artifacts'},
        'billing': set(),
    }[purpose]
    for key in _RF_SUPPORT_KEYS:
        if key in expected:
            assert str(ids[key]) in {row['id'] for row in resources[key]}, key
        else:
            assert resources[key] == [], key
    # Even an opened valid case cannot be reused for another tenant through the RF helper.
    empty = db.execute('select shareholder_register_filing.read_support_filing_history_v1(%s,%s)', (uuid4(),case_id)).fetchone()[0]
    assert all(empty[key] == [] for key in _RF_SUPPORT_KEYS)


@pytest.mark.parametrize('invalid_case', ['missing','unopened','revoked','expired','inactive_operator'])
def test_support_receiver_rejects_invalid_case_before_returning_retained_rf_history(db, invalid_case):
    company_id, owner, _, now = _support_fixture_history(db)
    case_id = _support_case(db, company_id, owner, ['authority','production','documents'], opened=invalid_case != 'unopened')
    _contract_support_history(db)
    if invalid_case == 'missing':
        case_id = uuid4()
    elif invalid_case == 'revoked':
        db.execute("update public.support_access_grants set revoked_at=now(),revoked_by=%s,revocation_reason='case_closed' where case_id=%s", (owner,case_id))
    elif invalid_case == 'expired':
        db.execute("update public.support_access_grants set starts_at=now()-interval '2 hours',expires_at=now()-interval '1 hour' where case_id=%s", (case_id,))
    elif invalid_case == 'inactive_operator':
        db.execute('update public.support_operators set active=false where user_id=%s', (owner,))
    _bind_support(db, owner, company_id)
    with pytest.raises(psycopg.errors.RaiseException, match='support_access_not_available'):
        with db.transaction():
            db.execute('select resources from public.company_access_read_support_case(%s)', (case_id,))


@pytest.mark.parametrize('phase',[EXPAND,CUTOVER,CONTRACT],ids=['expand','cutover','contract'])
def test_successful_resimulation_clears_predecessor_failure_columns(db,phase):
    company_id,owner=company(db)
    setup=opening(db,company_id,owner)
    preview_id=preview(db,company_id,owner,setup)
    submission=uuid4()
    insert(db,'public.filing_submissions',id=submission,preview_id=preview_id,company_id=company_id,setup_id=setup,
           income_year=2025,filing='aksjonærregisteroppgaven',status='failed_retryable',failure_code='retained_failure',
           failure_message='Retained previous failure',created_by=owner)
    insert(db,'public.filing_readiness_snapshots',company_id=company_id,income_year=2025,obligation='aksjonaerregisteroppgaven',status='ready',ready=True,created_by=owner)
    migration(db,EXPAND)
    if phase!=EXPAND:migration(db,CUTOVER)
    if phase==CONTRACT:migration(db,CONTRACT)
    bind(db,owner,company_id)
    now=db.execute('select now()').fetchone()[0].isoformat()
    result=db.execute('select shareholder_register_filing.record_simulation_v1(%s,%s)',(preview_id,Jsonb({
        'payload_hash':'a'*64,'idempotency_key':str(uuid4()),'status':'receipt_stored','calls':[],
        'receipt_id':'synthetic-simulation-receipt','feedback_document_ids':[],'feedback_items':[],
        'receipt_metadata':{},'submitted_payload_ref':{},'submitted_payload':{},'authority_confirmed_at':now,
        'preview_confirmed_at':now,'failure_code':None,'failure_message':None,
    }))).fetchone()[0]
    assert result['id']==str(submission) and result['status']=='receipt_stored'
    assert result['failure_code'] is None and result['failure_message'] is None


def _new_year_reader(db,owner,company_id):
    bind(db,owner,company_id)
    db.execute('reset role')
    principal=db.execute('select current_user').fetchone()[0]
    db.execute(sql.SQL('grant ledger_workflow_executor to {} with inherit false,set true').format(sql.Identifier(principal)))
    db.execute('set local role ledger_workflow_executor')


def test_year_scoped_archive_opening_does_not_read_another_year_quarantine(db):
    company_id,owner=company(db)
    other,_=company(db,owner)
    bad=opening(db,company_id,owner)
    db.execute('update public.opening_balance_setups set income_year=2024 where id=%s',(bad,))
    good=opening(db,company_id,owner)
    insert(db,'public.opening_shareholders',id=uuid4(),setup_id=bad,company_id=other,
           shareholder_kind='norwegian_company',name='Foreign historic holder',org_number='930835978',share_count=0,created_by=owner)
    migration(db,EXPAND)
    _new_year_reader(db,owner,company_id)
    for year in (None,2024):
        with pytest.raises(psycopg.Error,match='ledger_dependency_unavailable'):
            with db.transaction():
                db.execute('select * from backend_system.read_new_year_opening_snapshots_v1(%s,null,1,%s,%s)',([company_id],str(owner),year))
    items,cursor,has_more=db.execute('select * from backend_system.read_new_year_opening_snapshots_v1(%s,null,1,%s,2025)',([company_id],str(owner))).fetchone()
    assert [item['setupId'] for item in items]==[str(good)]
    assert cursor is None and has_more is False


def test_new_year_cursor_binds_optional_year_without_changing_all_year_default(db):
    company_id,owner=company(db)
    other,_=company(db,owner)
    opening(db,company_id,owner);opening(db,other,owner)
    migration(db,EXPAND)
    _new_year_reader(db,owner,company_id)
    ids=[company_id,other]
    _,year_cursor,more=db.execute('select * from backend_system.read_new_year_opening_snapshots_v1(%s,null,1,%s,2025)',(ids,str(owner))).fetchone()
    assert more
    for wrong_year in (None,2024):
        with pytest.raises(psycopg.Error,match='ledger_invalid_cursor'):
            with db.transaction():
                db.execute('select * from backend_system.read_new_year_opening_snapshots_v1(%s,%s,1,%s,%s)',(ids,year_cursor,str(owner),wrong_year))
    second=db.execute('select * from backend_system.read_new_year_opening_snapshots_v1(%s,%s,1,%s,2025)',(ids,year_cursor,str(owner))).fetchone()
    assert len(second[0])==1 and second[2] is False


def test_final_opening_split_retires_old_projection_and_keeps_sibling_fk_without_foreign_grants(db):
    company_id,owner=company(db)
    setup=opening(db,company_id,owner)
    for path in (EXPAND,CUTOVER,CONTRACT):migration(db,path)
    assert db.execute("select to_regclass('public.opening_balance_setups'),to_regclass('public.opening_shareholders')").fetchone()==(None,None)
    assert db.execute("select to_regprocedure('backend_system.list_opening_snapshots_legacy_v1(uuid[],text,integer,text)'),to_regprocedure('backend_system.record_opening_snapshot_legacy_v1(uuid,integer,numeric,numeric,integer,numeric,jsonb,text)')").fetchone()==(None,None)
    assert not db.execute("select exists(select 1 from pg_attribute where attrelid='ledger.entries'::regclass and attname='setup_id' and not attisdropped)").fetchone()[0]
    assert db.execute("select count(*) from pg_trigger where tgname in ('rf151_opening_projection','rf151_shareholder_projection','rf151_capture_legacy_bank')").fetchone()[0]==0
    bind(db,owner,company_id)
    db.execute('set local role authenticated')
    sibling=uuid4()
    insert(db,'public.filing_previews',id=sibling,company_id=company_id,setup_id=setup,income_year=2025,filing='arsregnskap',status='ready',preview='Unchanged sibling writer',created_by=owner)
    assert db.execute('select id from public.filing_previews where id=%s',(sibling,)).fetchone()[0]==sibling
    assert not db.execute("select has_table_privilege('authenticated','shareholder_register_filing.opening_balance_setups','SELECT,INSERT,UPDATE,DELETE')").fetchone()[0]
    with pytest.raises(psycopg.Error,match='rf1086_legacy_writer_retired'):
        with db.transaction():
            insert(db,'public.filing_previews',id=uuid4(),company_id=company_id,setup_id=setup,income_year=2025,filing='aksjonærregisteroppgaven',status='ready',preview='Rejected obsolete writer',created_by=owner)


def _admit_opening_year(db,company_id,owner):
    from talli_backend.modules.company_access import public as access
    from test_annual_purchase_basis_runtime import legal_fields
    now=db.execute("select now()-interval '1 second'").fetchone()[0]
    assessment,admission=uuid4(),uuid4()
    base=dict(company_id=company_id,accounting_year=2026,capability_manifest=Jsonb(access.CAPABILITY_MANIFEST),
              capability_manifest_version=access.CURRENT_CAPABILITY_MANIFEST_VERSION,capability_manifest_sha256=access.CURRENT_CAPABILITY_MANIFEST_SHA256)
    insert(db,'public.company_eligibility_assessments',**base,id=assessment,operation_id=uuid4(),trigger='initial_admission',assessed_at=now,
           decision='supported',public_facts=Jsonb({'source':'fixture'}),public_facts_sha256='a'*64,answers=Jsonb({'fixture':'yes'}),answers_sha256='b'*64,
           consequential_operations_allowed=True,archive_export_available=True,evaluator_version='2026.1',assessed_by=owner,next_step_code='CONTINUE_COMPANY_YEAR',next_step='Fortsett.')
    promise={'accountingYear':2026,'startsOn':'2026-01-01','endsOn':'2026-12-31','reconstructionRequiredFrom':'2026-01-01','onlyAccountingAndFilingProduct':True,'customerClaims':access.CAPABILITY_MANIFEST['promise']['customerClaims']}
    insert(db,'public.company_year_admissions',**base,id=admission,eligibility_assessment_id=assessment,company_year_promise=Jsonb(promise),
           company_year_promise_sha256=access._canonical_sha256(promise),reconstruct_from='2026-01-01',admitted_by=owner,admitted_at=now)
    name,org=db.execute('select name,org_number from public.companies where id=%s',(company_id,)).fetchone()
    accepted=dict(company_id=company_id,accepted_by=owner,accepted_at=now,customer_legal_name=name,customer_org_number=org)
    insert(db,'public.company_year_acceptances',**accepted,**legal_fields(privacy=True),id=uuid4(),company_year_admission_id=admission,accounting_year=2026,
           capability_manifest_version=access.CURRENT_CAPABILITY_MANIFEST_VERSION,capability_manifest_sha256=access.CURRENT_CAPABILITY_MANIFEST_SHA256)
    insert(db,'public.customer_agreement_acceptances',**accepted,**legal_fields(),id=uuid4())


def _record_split_opening(db,company_id,owner):
    return db.execute('select shareholder_register_filing.record_opening_snapshot_v1(%s,2026,30000,30,1000,%s,%s)',
        (company_id,Jsonb([{'name':'New owner AS','shareholderKind':'norwegian_company','orgNumber':'930835978','shareCount':30}]),str(owner))).fetchone()[0]


@pytest.mark.parametrize('phase',[EXPAND,CUTOVER],ids=['legacy-overlap','canonical-overlap'])
def test_split_opening_projection_waits_for_exact_ledger_bank_and_admits_scope_atomically(db,phase):
    company_id,owner=company(db);_admit_opening_year(db,company_id,owner)
    migration(db,EXPAND)
    if phase==CUTOVER:migration(db,CUTOVER)
    _new_year_reader(db,owner,company_id)
    with pytest.raises(psycopg.Error,match='rf1086_opening_bank_projection_missing'):
        with db.transaction():
            _record_split_opening(db,company_id,owner)
            db.execute('set constraints all immediate')
    assert db.execute('select * from backend_system.read_new_year_opening_snapshots_v1(%s,null,1,%s,2026)',([company_id],str(owner))).fetchone()[0]==[]
    snapshot=_record_split_opening(db,company_id,owner)
    db.execute('select * from ledger.record_opening_bank_input_v1(%s,%s,2026,123.45,%s)',(snapshot,company_id,str(owner)))
    db.execute('set constraints all immediate')
    items=db.execute('select * from backend_system.read_new_year_opening_snapshots_v1(%s,null,1,%s,2026)',([company_id],str(owner))).fetchone()[0]
    assert len(items)==1 and items[0]['setupId']==str(snapshot) and items[0]['bankBalance']=='123.45'
    db.execute('reset role')
    actual=db.execute('select to_jsonb(o) from public.opening_balance_setups o where id=%s',(snapshot,)).fetchone()[0]
    expected=db.execute("select to_jsonb(o)||jsonb_build_object('bank_balance',b.bank_balance_nok) from shareholder_register_filing.opening_balance_setups o join ledger.opening_bank_inputs b on b.snapshot_id=o.id where o.id=%s",(snapshot,)).fetchone()[0]
    assert actual==expected
    assert db.execute('select count(*) from shareholder_register_filing.migration_inventory where company_id=%s and income_year=2026',(company_id,)).fetchone()[0]==12


def test_contracted_legacy_rf_projection_rejects_direct_deletion(db):
    company_id,owner=company(db)
    preview_id=preview(db,company_id,owner,opening(db,company_id,owner))
    for path in (EXPAND,CUTOVER,CONTRACT):migration(db,path)
    with pytest.raises(psycopg.Error,match='rf1086_legacy_writer_retired'):
        with db.transaction():db.execute('delete from public.filing_previews where id=%s',(preview_id,))
    assert db.execute('select count(*) from public.filing_previews where id=%s',(preview_id,)).fetchone()[0]==1


def test_frozen_projection_fixture_cleanup_restores_trigger_modes_on_success_and_rollback(db):
    from test_rf1086_database_runtime import delete_legacy_fixture_projections
    company_id,owner=company(db)
    preview_id=preview(db,company_id,owner,opening(db,company_id,owner))
    for path in (EXPAND,CUTOVER,CONTRACT):migration(db,path)
    def modes():
        return db.execute("select t.tgrelid,t.tgname,t.tgenabled from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and not t.tgisinternal order by 1,2").fetchall()
    original=modes()
    with pytest.raises(RuntimeError,match='rollback janitor'):
        with db.transaction():
            delete_legacy_fixture_projections(db,company_id)
            assert not db.execute('select 1 from public.filing_previews where id=%s',(preview_id,)).fetchone()
            assert modes()==original
            raise RuntimeError('rollback janitor')
    assert db.execute('select 1 from public.filing_previews where id=%s',(preview_id,)).fetchone()
    assert modes()==original
    delete_legacy_fixture_projections(db,company_id)
    assert not db.execute('select 1 from public.filing_previews where id=%s',(preview_id,)).fetchone()
    assert modes()==original
