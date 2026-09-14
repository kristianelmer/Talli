"""Only synthetic company/year admission; no settlement or journal result seeded."""
import json,os,sys
from pathlib import Path
from uuid import UUID,uuid4
import psycopg
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'apps/backend/src'),str(root/'apps/backend/tests')]
from test_shareholder_register_filing_lifecycle import company,_admit_opening_year,insert
value=json.load(sys.stdin)
with psycopg.connect(os.environ['DATABASE_URL']) as db:
    cid,owner=company(db,UUID(value['owner']))
    db.execute("update public.companies set name='Synthetic Tax Browser AS',identity_confirmed_at=now(),identity_locked_at=now() where id=%s",(cid,))
    year=value.get('incomeYear',2026)
    assert year in (2025,2026)
    if year==2026:
        _admit_opening_year(db,cid,owner)
    else:
        # Historical evidence import is available for a legacy company. Do not
        # fabricate a 2025 admission under the 2026-only company-year promise.
        from test_annual_purchase_basis_runtime import legal_fields
        name,org=db.execute('select name,org_number from public.companies where id=%s',(cid,)).fetchone()
        insert(db,'public.customer_agreement_acceptances',id=uuid4(),company_id=cid,accepted_by=owner,
            accepted_at=db.execute('select now()').fetchone()[0],customer_legal_name=name,
            customer_org_number=org,**legal_fields())
    org=db.execute('select org_number from public.companies where id=%s',(cid,)).fetchone()[0]
print(json.dumps({'companyId':str(cid),'orgNumber':org}))
