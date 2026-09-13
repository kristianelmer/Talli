"""Only synthetic company/year admission; no settlement or journal result seeded."""
import json,os,sys
from pathlib import Path
from uuid import UUID
import psycopg
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'apps/backend/src'),str(root/'apps/backend/tests')]
from test_shareholder_register_filing_lifecycle import company,_admit_opening_year
value=json.load(sys.stdin)
with psycopg.connect(os.environ['DATABASE_URL']) as db:
    cid,owner=company(db,UUID(value['owner']))
    db.execute("update public.companies set name='Synthetic Tax Browser AS',identity_confirmed_at=now(),identity_locked_at=now() where id=%s",(cid,))
    _admit_opening_year(db,cid,owner)
print(json.dumps({'companyId':str(cid)}))
