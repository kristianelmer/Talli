"""Stdlib-only native Auth/Storage publication check, not just backend readiness.

A controller publishes a receipt only after owning replay. Every ingress request
rechecks the external cut AND each target-specific owner prefix, with no positive
cache. Bind mounts must be read-only, outside customer snapshots; a fresh target
UUID and independently held minimum head are required. OS custody controls the
writer. This is not authentication of a malicious journal/receipt administrator.
"""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from uuid import UUID

from talli_backend.application.disposition_receipts import progress_receipts

MAX_BODY = 1024 * 1024
MAX_JOURNAL = 16 * MAX_BODY
GENESIS = '0' * 64


def publication_is_current(*, journal: Path, receipt: Path, target: str,
                           stream: str, minimum_sequence: int, minimum_sha256: str) -> bool:
    try:
        target, stream = str(UUID(target)), str(UUID(stream))
        if (type(minimum_sequence) is not int or minimum_sequence < 0 or journal.is_symlink()
                or receipt.is_symlink() or not journal.is_file() or not receipt.is_file()
                or journal.stat().st_size > MAX_JOURNAL or receipt.stat().st_size > 4096):
            return False
        observed = json.loads(receipt.read_bytes())
        if not isinstance(observed,dict) or type(observed.get('sequence')) is not int:
            return False
        with closing(sqlite3.connect(journal.absolute().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            db.execute('begin')
            if db.execute('select stream from identity').fetchall() != [(stream,)]:
                return False
            rows = db.execute('select sequence,previous,body,digest from tombstones order by sequence limit 1001').fetchall()
            if len(rows)>1000 or minimum_sequence>len(rows):
                return False
            previous=GENESIS; total=0; expected={}
            for index,(sequence,parent,body,digest) in enumerate(rows,1):
                total+=len(body.encode())
                if (sequence!=index or parent!=previous or len(body.encode())>MAX_BODY or total>MAX_JOURNAL
                        or sha256((parent+'\n'+str(sequence)+'\n'+body).encode()).hexdigest()!=digest):
                    return False
                document=json.loads(body); plan=document['plan']; records=plan['records']
                if not isinstance(records,list) or not 0<len(records)<=10000:
                    return False
                commitment=sha256(body.encode()).hexdigest()
                for record in records:
                    if record['owner']!='documents':
                        return False
                    value={'operation_id':plan['operation_id'],'company_id':plan['company_id'],
                        'document_id':record['record_id'],'income_year':record['income_year'],
                        'generation':record['generation'],'content_sha256':record['content_sha256'],
                        'company_generation':plan['generation'],'plan_sha256':commitment,'action':record['action']}
                    current,legacy=progress_receipts(value)
                    key=(sequence,str(UUID(record['record_id'])))
                    if key in expected:return False
                    expected[key]=(current,*legacy)
                previous=digest
            minimum=GENESIS if minimum_sequence==0 else rows[minimum_sequence-1][3]
            if minimum!=minimum_sha256 or observed!={'target':target,'stream':stream,'sequence':len(rows),'sha256':previous}:
                return False
            applied=db.execute('select sequence,record,receipt from applied where target=? limit 1000001',(target,)).fetchall()
            if len(applied)!=len(expected):return False
            return all((seq,record) in expected and value in expected[(seq,record)] for seq,record,value in applied)
    except Exception:
        return False
