"""Synthetic Accounts rows for isolated migration and authorization rehearsals."""
from psycopg import sql

COMPANY = '15300000-0000-4000-8000-000000000001'
ACTORS = {name: f'15300000-0000-4000-8000-{index:012d}'
          for index, name in enumerate(('owner', 'second', 'reviewer', 'unaccepted', 'outsider'), 10)}
FAMILIES = ('filing_previews', 'authority_test_runs', 'authority_permissions',
            'filing_submissions', 'filing_overrides', 'filing_review_comments')
IDS = {name: f'15300000-0000-4000-8000-{index:012d}' for index, name in enumerate(FAMILIES, 20)}


def insert(db, schema, table, row):
    return db.execute(sql.SQL('insert into {}.{} ({}) values ({}) returning id').format(
        sql.Identifier(schema), sql.Identifier(table),
        sql.SQL(',').join(map(sql.Identifier, row)),
        sql.SQL(',').join(sql.Placeholder() for _ in row)), tuple(row.values())).fetchone()[0]


def seed(db):
    for actor in ACTORS.values():
        db.execute('insert into auth.users(id) values (%s)', (actor,))
    db.execute("insert into public.companies(id,org_number,name,entity_type,created_by) values (%s,'000000153','Synthetic Accounts153','AS',%s)", (COMPANY, ACTORS['owner']))
    for name, role, accepted in [('owner', 'owner', True), ('second', 'owner', True),
                                  ('reviewer', 'reviewer', True), ('unaccepted', 'owner', False)]:
        db.execute('insert into public.company_memberships(company_id,user_id,role,accepted_at) values (%s,%s,%s,case when %s then now() else null end)',
                   (COMPANY, ACTORS[name], role, accepted))
    rows = {
        'filing_previews': dict(income_year=2025, filing='årsregnskap', status='ready', preview='Synthetic Accounts migration'),
        'authority_test_runs': dict(obligation='aarsregnskap', status='pending', test_reference='synthetic-accounts153', recorded_by=ACTORS['owner']),
        'authority_permissions': dict(obligation='aarsregnskap', submitter_user_id=ACTORS['owner'], confirmed_by=ACTORS['owner']),
        'filing_submissions': dict(income_year=2025, filing='årsregnskap', status='ready', preview_id=IDS['filing_previews']),
        'filing_overrides': dict(income_year=2025, filing='årsregnskap', preview_id=IDS['filing_previews'],
            field_target='aarsregnskap.company.name', old_value='Before', new_value='After', reason='Synthetic reason', risk_level='warning',
            owner_confirmed_at='2026-07-14T12:00:00Z', owner_confirmed_by=ACTORS['owner']),
        'filing_review_comments': dict(preview_id=IDS['filing_previews'], severity='advisory', body='Synthetic review', target='rf1086_preview'),
    }
    for table in FAMILIES:
        row = rows[table]
        row.update(id=IDS[table], company_id=COMPANY)
        if table not in ('authority_test_runs', 'authority_permissions'):
            row['created_by'] = ACTORS['owner']
        insert(db, 'public', table, row)
    insert(db, 'public', 'filing_submissions', dict(rows['filing_submissions'],
        id='15300000-0000-4000-8000-000000000026', preview_id=None,
        mode='test_authority', adapter_mode='test_authority', authority_test_run_id=IDS['authority_test_runs']))
    return rows
