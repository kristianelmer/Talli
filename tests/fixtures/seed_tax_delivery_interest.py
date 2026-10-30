"""One declared synthetic owning-ledger change; real read contracts consume it."""
import json,os,sys
from pathlib import Path
from uuid import UUID
from urllib.parse import urlsplit

import psycopg

root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'apps/backend/src'),str(root/'apps/backend/tests')]
from talli_backend.shared.kernel import ActorId,ActorKind,UserId
from test_company_tax_correction_database import change_owning_ledger_fixture

url=os.environ['DATABASE_URL'];assert urlsplit(url).hostname=='127.0.0.1'
value=json.load(sys.stdin);company=str(UUID(value['companyId']));owner=str(UUID(value['owner']))
with psycopg.connect(url) as db:
    assert db.execute('select name from public.companies where id=%s',(company,)).fetchone()==('Synthetic Tax Browser AS',)
    assert db.execute('select count(*) from public.company_memberships where company_id=%s and user_id=%s and role=%s and accepted_at is not null',
        (company,owner,'owner')).fetchone()==(1,)
change_owning_ledger_fixture(((url,None,company,ActorId(ActorKind.USER,UserId(owner)),None),None,None))
print('Synthetic owning interest recorded; grants restored.')
