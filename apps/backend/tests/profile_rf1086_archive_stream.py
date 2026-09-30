"""Manual synthetic stream load regression; run from the backend dev environment.

Default: exactly 1 GiB; --small: 130 MiB; --single: 10 MiB.
Uses an OS pipe, no provider/database/object-store calls and no archive file.
Python-allocation ceiling is a fixture regression check, not production RSS sizing.
"""
import argparse
import asyncio
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import tracemalloc
from uuid import UUID

root=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(root/'apps/backend/src'),str(root/'apps/backend/tests')]
from talli_backend.application import shareholder_register_archive as c
from talli_backend.modules.documents.public import RetainedDocumentOriginal,RetainedDocumentOriginalSnapshot,document_metadata_sha256,DocumentId
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_feedback_archive_originals import feedback_archive,ACTOR

def rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == 'darwin' else value * 1024

import_peak=rss_bytes()
parser = argparse.ArgumentParser(description=__doc__)
size_group = parser.add_mutually_exclusive_group()
size_group.add_argument('--small', action='store_true')
size_group.add_argument('--single', action='store_true')
parser.add_argument('--emit', action='store_true', help=argparse.SUPPRESS)
args = parser.parse_args()
started=time.monotonic()
archive, template = feedback_archive()
# Exactly 1 GiB of synthetic original content. Retain metadata only, never all bytes.
sizes=([10*1024*1024] if args.single else [10*1024*1024]*13 if args.small else [10*1024*1024]*102+[4*1024*1024])
records={}
artifacts=[]
for i,size in enumerate(sizes):
    digest=sha256(bytes([i+1])*size).hexdigest()
    doc=replace(template.document, document_id=DocumentId(str(UUID(int=10000+i))),
        storage_key=f'{archive.company_id}/2025/{UUID(int=10000+i)}/receipt.xml',content_sha256=digest,byte_length=size)
    receipt=replace(template.original.receipt,original_id=str(UUID(int=20000+i)),document_id=doc.document_id,
        metadata_sha256=document_metadata_sha256(doc),content_sha256=digest,byte_length=size)
    records[str(doc.document_id)]=(doc,receipt,i,size)
    artifacts.append(replace(archive.feedback_artifacts[0],id=str(UUID(int=30000+i)),document_id=str(doc.document_id),
        sha256=digest,byte_length=size,original_id=receipt.original_id,original_metadata_sha256=receipt.metadata_sha256))
archive=replace(archive, feedback_artifacts=tuple(artifacts),
    production_submissions=(replace(archive.production_submissions[0], feedback_artifact_count=len(artifacts)),),
    production_events=(replace(archive.production_events[0],artifact_hashes=tuple(a.sha256 for a in artifacts)),))
query=rf.Rf1086ArchiveQuery(archive.company_id,archive.income_year,ACTOR)
fixture_peak=rss_bytes()
class Factory:
    async def session(self,token):
        class Session:
            actor_id=ACTOR
            async def read_retained_evidence(self,q):
                doc,receipt,i,size=records[str(q.document_id)]
                return RetainedDocumentOriginalSnapshot(doc,RetainedDocumentOriginal(receipt,bytes([i+1])*size))
        return Session()
if args.emit:
    tracemalloc.start()
    async def emit():
        stream=await c.prepare_archive_stream(archive,query=query,documents_factory=Factory(),access_token='synthetic',actor_id=ACTOR)
        total=0
        async for chunk in stream:
            sys.stdout.buffer.write(chunk);total+=len(chunk)
        sys.stdout.buffer.flush()
        assert tracemalloc.get_traced_memory()[1] < 256 * 1024 * 1024, "export retained excessive Python allocations"
        print(json.dumps({'wireBytes':total,'importPeak':import_peak,'fixturePeak':fixture_peak,'exportPeakRssBytes':rss_bytes(),'pythonAllocationBytes':tracemalloc.get_traced_memory()}),file=sys.stderr)
    asyncio.run(emit())
else:
    tracemalloc.start()
    with subprocess.Popen([sys.executable,__file__,'--emit',*(['--small'] if args.small else ['--single'] if args.single else [])],stdout=subprocess.PIPE,stderr=subprocess.PIPE) as child:
        try:
            restored,sources,feedback=c.verify_archive_stream(child.stdout,query=query,require_source_history=True,require_feedback_originals=True)
            assert restored==archive and sources==0 and feedback==len(sizes)
            output=child.stderr.read().decode()
            assert child.wait(timeout=10)==0,output
        except BaseException:
            child.terminate();child.wait(timeout=10);raise
    assert tracemalloc.get_traced_memory()[1] < 256 * 1024 * 1024, 'verifier retained excessive Python allocations'
    print(json.dumps({'status':'passed','originalBytes':sum(sizes),'originals':feedback,'sourceHistoryRequired':True,
        'strictFeedbackRequired':True,'importPeak':import_peak,'fixturePeak':fixture_peak,'verifyPeakRssBytes':rss_bytes(),
        'pythonAllocationBytes':tracemalloc.get_traced_memory(),'elapsedSeconds':round(time.monotonic()-started,3),'export':json.loads(output)}))
